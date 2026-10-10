"""Request handling of the _panel AIAView without a Tk window.

The view is built with ``__new__`` and its few Tk touch points (text insert,
busy state, ``after`` polling) are replaced by recorders, so the logic around
request ids, cancelling and the worker thread can run in plain pytest.
"""

import queue
import threading

import pytest


def make_view(module):
    view = module.AIAView.__new__(module.AIAView)
    view._conversation = []
    view._events = queue.Queue()
    view._request_id = 0
    view._cancel_event = None
    view._partial = []
    view._polling = False
    view.inserted = []
    view.busy = []
    view._insert = lambda text, tag=None: view.inserted.append(text)
    view._set_busy = lambda busy: view.busy.append(busy)
    view.after = lambda ms, func: None
    return view


def start_request(view):
    """The state _request_llm_response() leaves behind, without a provider."""
    view._request_id += 1
    view._cancel_event = threading.Event()
    view._partial = []
    view._set_busy(True)
    return view._request_id, view._cancel_event


@pytest.fixture
def panel_view(fake_thonny):
    from thonny.plugins.aia._panel import view as module

    return module


def test_cancel_before_first_token_frees_the_panel_at_once(panel_view):
    view = make_view(panel_view)
    start_request(view)

    view._on_cancel()

    assert view.busy[-1] is False  # Send is enabled again, no waiting for the worker
    assert view._cancel_event is None
    assert any("[cancelled]" in text for text in view.inserted)


def test_late_events_of_a_cancelled_request_are_dropped(panel_view):
    view = make_view(panel_view)
    request_id, _ = start_request(view)
    view._on_cancel()
    shown = list(view.inserted)

    view._events.put((request_id, "chunk", "late text"))
    view._events.put((request_id, "error", "late error"))
    view._events.put((request_id, "done", " [cancelled]"))
    view._poll_events()

    assert view.inserted == shown
    assert view._conversation == []


def test_partial_answer_is_kept_when_cancelled_mid_stream(panel_view):
    view = make_view(panel_view)
    request_id, _ = start_request(view)
    view._events.put((request_id, "chunk", "Think about "))
    view._poll_events()

    view._on_cancel()

    assert view._conversation == [{"role": "assistant", "content": "Think about "}]


def test_next_request_after_cancel_runs_normally(panel_view):
    view = make_view(panel_view)
    old_id, _ = start_request(view)
    view._on_cancel()

    new_id, _ = start_request(view)
    view._events.put((old_id, "chunk", "stale"))
    view._events.put((new_id, "chunk", "fresh"))
    view._events.put((new_id, "done", ""))
    view._poll_events()

    assert "stale" not in view.inserted
    assert view._conversation == [{"role": "assistant", "content": "fresh"}]
    assert view.busy[-1] is False


def test_worker_closes_the_stream_of_a_cancelled_request(panel_view):
    view = make_view(panel_view)
    request_id, cancel_event = start_request(view)
    gate = threading.Event()
    closed = threading.Event()

    class SlowProvider:
        def stream_chat(self, system_prompt, messages, model):
            try:
                gate.wait(5)  # e.g. a slow service before the first token
                yield "first"
                yield "second"
            finally:
                closed.set()

    worker = threading.Thread(
        target=view._stream_in_background,
        args=(request_id, cancel_event, SlowProvider(), "openai", "", [], "m"),
        daemon=True,
    )
    worker.start()
    view._on_cancel()
    assert view.busy[-1] is False  # freed before the provider sent anything

    gate.set()
    worker.join(5)
    assert closed.is_set()
    events = []
    while not view._events.empty():
        events.append(view._events.get_nowait())
    assert ("chunk" not in {kind for _, kind, _ in events})
    view._poll_events()
    assert view._conversation == []


class _FakeText:
    def __init__(self):
        self.deleted = []

    def tag_ranges(self, tag):
        return ("2.5", "2.31") if tag == "loading_text" else ()

    def delete(self, start, end):
        self.deleted.append((start, end))

    def configure(self, **kwargs):
        pass


def test_local_loading_note_disappears_with_first_token(panel_view):
    view = make_view(panel_view)
    request_id, _ = start_request(view)
    view._messages_text = _FakeText()
    view._loading = True  # set by _request_llm_response for the Ollama provider

    view._events.put((request_id, "chunk", "Ahoj"))
    view._poll_events()

    assert view._messages_text.deleted == [("2.5", "2.31")]
    assert view._loading is False and view.inserted[-1] == "Ahoj"


def test_local_loading_note_disappears_on_cancel(panel_view):
    view = make_view(panel_view)
    start_request(view)
    view._messages_text = _FakeText()
    view._loading = True

    view._on_cancel()

    assert view._messages_text.deleted == [("2.5", "2.31")] and view._loading is False
