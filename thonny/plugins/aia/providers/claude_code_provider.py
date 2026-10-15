# Copyright (c) 2026 Jakub Šenkýř
# SPDX-License-Identifier: MIT
"""Demo provider: the Claude Code CLI (``claude -p``) instead of an API key.

Runs under the account the CLI is signed in to on this computer, so it is meant
for demos by the teacher, never for students. No SDK: the CLI is a separate
program found on PATH, and each request is one short-lived ``claude -p`` process.

The process is isolated from the teacher's own Claude Code setup as far as the
CLI allows (checked against Claude Code 2.1.283, 2026-09-28):

- ``--tools ""`` and ``--strict-mcp-config``: plain text answers, no tools, no MCP servers;
- ``--system-prompt-file``: the mentor prompt replaces Claude Code's own system prompt
  (a file, because the prompt carries the student's code and a Windows command
  line is limited to ~32k characters);
- settings ``claudeMdExcludes``: the user's ``~/.claude/CLAUDE.md`` is not loaded
  (without it the whole personal CLAUDE.md ends up in the mentor's context);
- settings ``disableAllHooks`` and ``CLAUDE_CODE_DISABLE_AUTO_MEMORY``: no hooks, no memory;
- a neutral working directory in the temp folder, no session persistence.

What stays in the context: the account e-mail, the platform and the date, which
the CLI adds on its own. ``--bare`` would drop more, but it also disables the
subscription (OAuth) login, which is the whole point of this provider.
"""

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Dict, Iterator, List, Optional

from thonny.plugins.aia.providers.base import REQUEST_TIMEOUT, LLMProvider

logger = logging.getLogger(__name__)

# The CLI needs a few seconds to start before the first token arrives.
FIRST_TOKEN_TIMEOUT = REQUEST_TIMEOUT

ISOLATION_SETTINGS = {
    "disableAllHooks": True,
    "claudeMdExcludes": ["**/CLAUDE.md", "**/CLAUDE.local.md"],
}

# Full IDs, not the CLI aliases: "sonnet" etc. move to each new release on their own
# (on 2026-10-09 they meant the 5.5 models). Same models as the Anthropic provider.
MODELS = ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"]


class ClaudeCodeTimeout(Exception):
    """No output from the CLI for too long (name contains "Timeout" for friendly_error)."""


class ClaudeCodeError(Exception):
    """The CLI ended with an error (not signed in, model refused, ...)."""


def find_claude_executable() -> Optional[str]:
    return shutil.which("claude")


def build_prompt(messages: List[Dict[str, str]]) -> str:
    """One prompt from the chat history - ``claude -p`` takes a single user turn.

    A lone message goes as is; a longer history is written out as a transcript
    ending with the student's latest message.
    """
    if not messages:
        return ""
    if len(messages) == 1:
        return messages[0]["content"]
    names = {"user": "Student", "assistant": "Mentor"}
    history = "\n\n".join(
        f"{names.get(m['role'], m['role'])}: {m['content']}" for m in messages[:-1]
    )
    return (
        "Conversation so far (you are the Mentor):\n\n"
        f"{history}\n\n"
        "The student's new message - answer it as the Mentor:\n\n"
        f"{messages[-1]['content']}"
    )


def build_command(executable: str, model: str, system_prompt_file: str) -> List[str]:
    return [
        executable,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--tools",
        "",
        "--strict-mcp-config",
        "--no-session-persistence",
        "--settings",
        json.dumps(ISOLATION_SETTINGS),
        "--model",
        model,
        "--system-prompt-file",
        system_prompt_file,
    ]


def text_from_event(event: dict) -> Optional[str]:
    """Text of a streamed delta, None for every other stream-json event."""
    if event.get("type") != "stream_event":
        return None
    inner = event.get("event") or {}
    if inner.get("type") != "content_block_delta":
        return None
    delta = inner.get("delta") or {}
    if delta.get("type") != "text_delta":
        return None
    return delta.get("text") or None


class ClaudeCodeProvider(LLMProvider):
    """Streams answers from ``claude -p`` (Claude Code CLI signed in on this computer)."""

    def __init__(self, executable: str, popen=subprocess.Popen):
        self._executable = executable
        self._popen = popen

    def stream_chat(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        model: str,
    ) -> Iterator[str]:
        workdir = tempfile.mkdtemp(prefix="thonny-aia-claude-")
        prompt_file = os.path.join(workdir, "system-prompt.txt")
        with open(prompt_file, "w", encoding="utf-8") as f:
            f.write(system_prompt)

        env = dict(os.environ, CLAUDE_CODE_DISABLE_AUTO_MEMORY="1")
        env.pop("CLAUDECODE", None)  # Thonny started from a Claude Code terminal
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = self._popen(
            build_command(self._executable, model, prompt_file),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            **kwargs,
        )
        lines: "queue.Queue" = queue.Queue()
        stderr_tail: List[str] = []

        def read_stdout():
            for line in proc.stdout:
                lines.put(line)
            lines.put(None)

        def read_stderr():  # drained continuously, a full pipe would block the CLI
            for line in proc.stderr:
                stderr_tail.append(line)
                del stderr_tail[:-20]

        try:
            threading.Thread(target=read_stdout, daemon=True).start()
            threading.Thread(target=read_stderr, daemon=True).start()
            proc.stdin.write(build_prompt(messages))
            proc.stdin.close()

            got_text = False
            while True:
                try:
                    line = lines.get(timeout=FIRST_TOKEN_TIMEOUT)
                except queue.Empty:
                    raise ClaudeCodeTimeout("Claude Code did not answer in time")
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    logger.debug("AIA claude: non-JSON line %r", line[:200])
                    continue
                text = text_from_event(event)
                if text:
                    got_text = True
                    yield text
                elif event.get("type") == "result":
                    if event.get("is_error"):
                        raise ClaudeCodeError(str(event.get("result") or "Claude Code error"))
                    if not got_text and event.get("result"):
                        yield str(event["result"])  # CLI without partial messages
                    return

            proc.wait(timeout=5)
            if proc.returncode:
                stderr = "".join(stderr_tail).strip()
                raise ClaudeCodeError(stderr[-300:] or f"claude exited with {proc.returncode}")
        finally:
            if proc.poll() is None:
                proc.kill()  # cancel or error: do not leave the CLI running
            shutil.rmtree(workdir, ignore_errors=True)

    def is_available(self) -> bool:
        return bool(self._executable)

    def get_display_name(self) -> str:
        return "Claude Code (demo)"

    def get_default_model(self) -> str:
        return MODELS[0]

    def get_available_models(self) -> List[str]:
        return list(MODELS)
