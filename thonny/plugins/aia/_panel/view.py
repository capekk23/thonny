"""AIAView - custom chat panel for Thonny without the Chat API (4.x, 5.0.x).

Replaces the built-in rule-based AssistantView when AIA is enabled.

Threading: the LLM request runs in a worker thread that never touches Tk. It
only puts events into a queue.Queue, which the UI thread drains with
``after()`` polling. Every event carries a request id, so events from a
superseded (cancelled) request are dropped.
"""

import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

from thonny import get_workbench

from thonny.plugins.aia._common import (
    AIACore,
    friendly_error,
    prepare_messages,
    snapshot_editor_context,
)
from thonny.plugins.aia.prompts import build_system_prompt

logger = logging.getLogger(__name__)

POLL_MS = 50

# Shown until the first token of a local model arrives: on CPU, loading gpt-oss:20b took
# 35-55 s and processing the prompt up to 40 s more, with nothing in the panel (Jakub 2026-10-10)
LOCAL_LOADING = "Loading the local model..."


class AIAView(ttk.Frame):
    """Chat panel that provides AI-powered programming assistance."""

    def __init__(self, master):
        super().__init__(master)

        self._core = AIACore()
        self._core.register_providers()
        self._conversation: List[Dict[str, str]] = []

        self._events: "queue.Queue" = queue.Queue()
        self._request_id = 0  # id of the request whose events are shown
        self._cancel_event: Optional[threading.Event] = None
        self._partial: List[str] = []
        self._polling = False
        self._loading = False  # LOCAL_LOADING is in the messages area

        self._build_ui()

    # --- UI ---

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)  # messages area expands
        self.rowconfigure(1, weight=0)  # input area fixed

        messages_frame = ttk.Frame(self)
        messages_frame.grid(row=0, column=0, sticky="nsew")
        messages_frame.columnconfigure(0, weight=1)
        messages_frame.rowconfigure(0, weight=1)

        self._messages_text = tk.Text(
            messages_frame,
            wrap="word",
            state="disabled",
            borderwidth=0,
            padx=8,
            pady=8,
            spacing1=2,
            spacing3=2,
        )
        self._messages_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(messages_frame, command=self._messages_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self._messages_text.configure(yscrollcommand=scrollbar.set)

        self._configure_tags()
        self._show_welcome()

        input_frame = ttk.Frame(self)
        input_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
        input_frame.columnconfigure(0, weight=1)

        # height=1 is only the minimum: the button column sets the row height and the
        # input stretches to it, so its edges line up with Send and Clear
        self._input_text = tk.Text(input_frame, height=1, wrap="word", borderwidth=1, relief="solid")
        self._input_text.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._input_text.bind("<Return>", self._on_enter)

        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=0, column=1, sticky="ns")

        self._send_button = ttk.Button(button_frame, text="Send", width=7, command=self._on_send)
        self._send_button.pack(side="top", pady=(0, 2))

        self._cancel_button = ttk.Button(
            button_frame, text="Cancel", width=7, command=self._on_cancel, state="disabled"
        )
        self._cancel_button.pack(side="top", pady=(0, 2))

        ttk.Button(button_frame, text="Clear", width=7, command=self.clear_conversation).pack(
            side="top"
        )

    def _configure_tags(self):
        bold_font = ("TkDefaultFont", 9, "bold")

        self._messages_text.tag_configure("user_header", font=bold_font, foreground="#1a5276")
        self._messages_text.tag_configure("assistant_header", font=bold_font, foreground="#117a65")
        self._messages_text.tag_configure(
            "system_text", foreground="#7f8c8d", font=("TkDefaultFont", 8)
        )
        self._messages_text.tag_configure("error_text", foreground="#c0392b")
        self._messages_text.tag_configure("auto_label", foreground="#7f8c8d")
        self._messages_text.tag_configure("loading_text", foreground="#7f8c8d")

    def _show_welcome(self):
        self._insert(
            "AIA - AI Mentor Assistant\n"
            "Type a question below (Enter sends, Shift+Enter = new line).\n",
            "system_text",
        )

    def _insert(self, text: str, tag: Optional[str] = None):
        self._messages_text.configure(state="normal")
        if tag:
            self._messages_text.insert("end", text, tag)
        else:
            self._messages_text.insert("end", text)
        self._messages_text.configure(state="disabled")
        self._messages_text.see("end")

    def _set_busy(self, busy: bool):
        self._send_button.configure(state="disabled" if busy else "normal")
        self._cancel_button.configure(state="normal" if busy else "disabled")
        self._input_text.configure(state="disabled" if busy else "normal")
        if not busy:
            self._input_text.focus_set()

    # --- Event handling ---

    def handle_toplevel_response(self, msg):
        """Bound to ToplevelResponse while AIA is enabled. Auto-explain errors."""
        if not get_workbench().get_option("aia.enabled"):
            return

        error_info = msg.get("user_exception")
        if not error_info:
            return

        type_name = error_info.get("type_name", "Error")
        message = error_info.get("message", "")
        lineno = error_info.get("lineno")

        parts = [f"I ran my code and got this error: {type_name}: {message}"]
        if lineno:
            parts.append(f"(line {lineno})")

        traceback_text = error_info.get("traceback_text", "")
        if traceback_text:
            parts.append(f"\n{traceback_text.strip()}")

        # A new error supersedes an answer that is still streaming
        self._abort_current_request()
        self._add_user_message("\n".join(parts), auto=True)
        self._request_llm_response()

        get_workbench().show_view("AIAView", set_focus=False)

    def _on_enter(self, event):
        """Enter sends the message, Shift+Enter inserts a newline."""
        if event.state & 0x0001:  # Shift
            return None
        self._on_send()
        return "break"

    def _on_send(self):
        if self._cancel_event is not None:
            return  # a request is running
        text = self._input_text.get("1.0", "end-1c").strip()
        if not text:
            return
        self._input_text.delete("1.0", "end")
        self._add_user_message(text, auto=False)
        self._request_llm_response()

    def _on_cancel(self):
        # Free the panel right away: the worker may be blocked before the first
        # token (e.g. a slow service) and only sees the event when the
        # next chunk arrives - it closes the stream then, its events are dropped.
        self._abort_current_request()

    # --- Conversation management ---

    def _add_user_message(self, text: str, auto: bool = False):
        self._conversation.append({"role": "user", "content": text})
        self._insert("\nYou (auto): " if auto else "\nYou: ", "user_header")
        if auto:
            self._insert("(error detected) ", "auto_label")
        self._insert(f"{text}\n")

    def _abort_current_request(self):
        """Stop showing the running request (if any) and keep its partial answer."""
        if self._cancel_event is None:
            return
        self._cancel_event.set()
        self._request_id += 1  # drop its remaining events
        self._finish(" [cancelled]")

    def _request_llm_response(self):
        """Collect everything on the UI thread, then stream in a worker thread."""
        problem = self._core.check_ready()
        if problem:
            self._insert(f"\n{problem}\n", "error_text")
            return

        wb = get_workbench()
        provider_id = self._core.get_current_provider_id()
        provider = self._core.get_current_provider()
        model = self._core.get_current_model(provider)

        ctx = snapshot_editor_context(wb)
        system_prompt = build_system_prompt(
            mentoring_level=wb.get_option("aia.mentoring_level"),
            current_code=ctx["code"],
            current_file_name=ctx["file_name"],
            imported_files=ctx["imported_files"],
        )
        api_messages = prepare_messages(self._conversation)

        self._request_id += 1
        self._cancel_event = threading.Event()
        self._partial = []
        self._set_busy(True)
        self._insert("\nAIA: ", "assistant_header")
        if provider_id == "ollama":
            self._insert(LOCAL_LOADING, "loading_text")
            self._loading = True

        threading.Thread(
            target=self._stream_in_background,
            args=(
                self._request_id,
                self._cancel_event,
                provider.frozen(),  # settings read here, on the UI thread
                provider_id,
                system_prompt,
                api_messages,
                model,
            ),
            daemon=True,
        ).start()
        self._start_polling()

    def _stream_in_background(
        self, request_id, cancel_event, provider, provider_id, system_prompt, api_messages, model
    ):
        """Worker thread: no Tk calls, only queue puts."""
        put = self._events.put
        stream = None
        try:
            stream = provider.stream_chat(system_prompt, api_messages, model)
            for chunk_text in stream:
                if cancel_event.is_set():
                    put((request_id, "done", " [cancelled]"))
                    return
                put((request_id, "chunk", chunk_text))
            put((request_id, "done", ""))
        except Exception as e:
            logger.exception("AIA: error during chat completion")
            put((request_id, "error", friendly_error(e, provider_id, model)))
        finally:
            close = getattr(stream, "close", None)
            if close is not None:
                try:
                    close()  # releases the HTTP stream on cancel
                except Exception:
                    logger.debug("Error closing stream", exc_info=True)

    def _start_polling(self):
        if not self._polling:
            self._polling = True
            self.after(POLL_MS, self._poll_events)

    def _poll_events(self):
        try:
            while True:
                request_id, kind, payload = self._events.get_nowait()
                if request_id != self._request_id:
                    continue  # superseded request
                if kind == "chunk":
                    self._hide_loading()
                    self._partial.append(payload)
                    self._insert(payload)
                elif kind == "done":
                    self._finish(payload)
                elif kind == "error":
                    self._hide_loading()
                    self._insert(f"\n{payload}", "error_text")
                    self._finish("")
        except queue.Empty:
            pass

        if self._cancel_event is not None:
            self.after(POLL_MS, self._poll_events)
        else:
            self._polling = False

    def _hide_loading(self):
        """Remove LOCAL_LOADING once the answer (or an error, or Cancel) takes its place."""
        if not getattr(self, "_loading", False):
            return
        self._loading = False
        text = self._messages_text
        ranges = text.tag_ranges("loading_text")
        text.configure(state="normal")
        for i in range(len(ranges) - 2, -1, -2):
            text.delete(ranges[i], ranges[i + 1])
        text.configure(state="disabled")

    def _finish(self, suffix: str):
        self._hide_loading()
        if suffix:
            self._insert(suffix)
        self._insert("\n")
        full_response = "".join(self._partial)
        if full_response:
            self._conversation.append({"role": "assistant", "content": full_response})
        self._partial = []
        self._cancel_event = None
        self._set_busy(False)

    def clear_conversation(self):
        """Forget the chat history (starts a fresh conversation)."""
        self._abort_current_request()
        self._conversation.clear()
        self._messages_text.configure(state="normal")
        self._messages_text.delete("1.0", "end")
        self._messages_text.configure(state="disabled")
        self._show_welcome()
