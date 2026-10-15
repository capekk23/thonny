# Copyright (c) 2026 Jakub Šenkýř
# SPDX-License-Identifier: MIT
"""Claude Code CLI provider (demo) with a fake ``subprocess.Popen`` - no real CLI runs."""

import io
import json
import threading

import pytest


def delta(text):
    return json.dumps(
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": text},
            },
        }
    )


RESULT_OK = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": "x"})


class FakeProc:
    """Popen stand-in: records the call, serves stdout lines, can block before them."""

    def __init__(self, lines, returncode=0, gate=None, stderr=""):
        self._lines = [line + "\n" for line in lines]
        self.returncode = None
        self._final_code = returncode
        self._gate = gate
        self.killed = False
        self.stdin = io.StringIO()
        self.stdin.close = lambda: setattr(self, "prompt", self.stdin.getvalue())
        self.stderr = io.StringIO(stderr)
        self.stdout = self._stdout()

    def _stdout(self):
        if self._gate is not None:
            self._gate.wait(5)
        for line in self._lines:
            yield line
        self.returncode = self._final_code

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = self._final_code
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def make_provider(module, proc):
    calls = []

    def popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return proc

    return module.ClaudeCodeProvider("claude", popen=popen), calls


@pytest.fixture
def cc(fake_thonny):
    from thonny.plugins.aia.providers import claude_code_provider

    return claude_code_provider


def test_streams_text_deltas_and_isolates_the_cli(cc):
    proc = FakeProc([json.dumps({"type": "system", "subtype": "init"}), delta("Ahoj"), delta(" světe"), RESULT_OK])
    provider, calls = make_provider(cc, proc)

    chunks = list(provider.stream_chat("MENTOR PROMPT", [{"role": "user", "content": "Co je cyklus?"}], "sonnet"))

    assert chunks == ["Ahoj", " světe"]
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["claude", "-p"]
    assert cmd[cmd.index("--tools") + 1] == ""
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    settings = json.loads(cmd[cmd.index("--settings") + 1])
    assert settings["disableAllHooks"] is True
    assert "**/CLAUDE.md" in settings["claudeMdExcludes"]
    assert cmd[cmd.index("--model") + 1] == "sonnet"
    assert "--system-prompt-file" in cmd and "MENTOR PROMPT" not in cmd  # file, not argv
    assert kwargs["env"]["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert proc.prompt == "Co je cyklus?"  # question goes through stdin


def test_history_becomes_a_transcript_ending_with_the_new_message(cc):
    prompt = cc.build_prompt(
        [
            {"role": "user", "content": "Proč mi to padá?"},
            {"role": "assistant", "content": "Co říká chybová hláška?"},
            {"role": "user", "content": "IndexError"},
        ]
    )
    assert "Student: Proč mi to padá?" in prompt
    assert "Mentor: Co říká chybová hláška?" in prompt
    assert prompt.rstrip().endswith("IndexError")
    assert "Student: IndexError" not in prompt


def test_error_result_raises(cc):
    proc = FakeProc([json.dumps({"type": "result", "is_error": True, "result": "Not logged in"})])
    provider, _ = make_provider(cc, proc)
    with pytest.raises(cc.ClaudeCodeError, match="Not logged in"):
        list(provider.stream_chat("", [{"role": "user", "content": "x"}], "sonnet"))


def test_result_text_is_used_when_no_deltas_came(cc):
    proc = FakeProc([json.dumps({"type": "result", "is_error": False, "result": "Celá odpověď"})])
    provider, _ = make_provider(cc, proc)
    assert list(provider.stream_chat("", [{"role": "user", "content": "x"}], "sonnet")) == ["Celá odpověď"]


def test_failed_process_reports_stderr(cc):
    proc = FakeProc([], returncode=1, stderr="error: unknown option\n")
    provider, _ = make_provider(cc, proc)
    with pytest.raises(cc.ClaudeCodeError, match="unknown option"):
        list(provider.stream_chat("", [{"role": "user", "content": "x"}], "sonnet"))


def test_silent_cli_times_out_and_is_killed(cc, monkeypatch):
    monkeypatch.setattr(cc, "FIRST_TOKEN_TIMEOUT", 0.2)
    gate = threading.Event()  # never opened: the CLI prints nothing
    proc = FakeProc([delta("late")], gate=gate)
    provider, _ = make_provider(cc, proc)
    with pytest.raises(cc.ClaudeCodeTimeout):
        list(provider.stream_chat("", [{"role": "user", "content": "x"}], "sonnet"))
    assert proc.killed
    gate.set()


def test_closing_the_stream_kills_the_cli(cc):
    proc = FakeProc([delta("a"), delta("b"), RESULT_OK])
    proc.returncode = None
    provider, _ = make_provider(cc, proc)
    stream = provider.stream_chat("", [{"role": "user", "content": "x"}], "sonnet")
    assert next(stream) == "a"
    proc.returncode = None  # still running
    stream.close()  # what the panel worker does after Cancel
    assert proc.killed


def test_registered_only_when_claude_is_on_path(fake_thonny, monkeypatch):
    from thonny.plugins.aia import _common
    from thonny.plugins.aia.providers import claude_code_provider

    monkeypatch.setattr(_common, "package_installed", lambda name: False)
    monkeypatch.setattr(claude_code_provider, "find_claude_executable", lambda: None)
    core = _common.AIACore()
    core.register_providers()
    assert "claude_code" not in core.providers

    fake_thonny.options["aia.provider"] = "claude_code"
    assert "'claude' command" in core.check_ready()

    monkeypatch.setattr(claude_code_provider, "find_claude_executable", lambda: "C:/x/claude.exe")
    core = _common.AIACore()
    core.register_providers()
    assert core.check_ready() is None
    assert core.get_current_model(core.get_current_provider()) == "claude-sonnet-5-5"
    assert _common.provider_display_name("claude_code") == "Claude Code (demo)"


def test_timeout_gets_the_friendly_message(cc):
    from thonny.plugins.aia._common import friendly_error

    assert "did not answer in time" in friendly_error(cc.ClaudeCodeTimeout("x"), "claude_code")
