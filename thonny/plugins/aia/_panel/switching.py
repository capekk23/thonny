"""Toggle between the built-in AssistantView and AIAView (Thonny 4.x / 5.0.x).

AssistantView registers ``self.handle_toplevel_response`` with
``workbench.bind("ToplevelResponse", ...)`` in its constructor, so replacing the
attribute afterwards has no effect. Instead we ``unbind`` that bound method while
AIA is enabled and bind it back when it is disabled. As a fallback (e.g. the
view gets created later), AssistantView is hidden whenever it tries to show
itself while AIA is enabled.
"""

import logging

logger = logging.getLogger(__name__)

_state = {
    "assistant_unbound": None,  # the AssistantView instance we unbound, if any
    "aia_handler": None,  # AIAView.handle_toplevel_response while bound
}


def install_switching_logic(wb):
    """Set up the toggle mechanism. Called once from load_plugin()."""

    def _apply_state(*_args):
        if wb.get_option("aia.enabled"):
            _activate_aia(wb)
        else:
            _deactivate_aia(wb)

    # React to the checkbox in Tools > Options
    try:
        wb.get_variable("aia.enabled").trace_add("write", _apply_state)
    except Exception:
        logger.debug("Could not trace aia.enabled variable", exc_info=True)

    def _on_show_view(event):
        if not wb.get_option("aia.enabled"):
            return
        view_id = getattr(event, "view_id", None)
        if view_id is None and isinstance(event, dict):
            view_id = event.get("view_id")
        if view_id == "AssistantView":
            wb.after_idle(lambda: _suppress_assistant_view(wb))

    try:
        wb.bind("ShowView", _on_show_view, True)
    except Exception:
        logger.debug("Could not bind ShowView event", exc_info=True)

    # Defer initial activation until the workbench has created its views
    if wb.get_option("aia.enabled"):
        wb.after(500, lambda: _activate_aia(wb))


def _suppress_assistant_view(wb):
    try:
        view = wb.get_view("AssistantView", create=False)
    except Exception:
        view = None
    if view is not None and _state["assistant_unbound"] is not view:
        try:
            wb.unbind("ToplevelResponse", view.handle_toplevel_response)
            _state["assistant_unbound"] = view
        except Exception:
            logger.debug("Could not unbind AssistantView handler", exc_info=True)
    try:
        wb.hide_view("AssistantView")
    except Exception:
        pass


def _activate_aia(wb):
    """Enable AIA: silence AssistantView, show AIAView, bind its handler."""
    _suppress_assistant_view(wb)

    try:
        aia_view = wb.get_view("AIAView")
        if _state["aia_handler"] is None:
            _state["aia_handler"] = aia_view.handle_toplevel_response
            wb.bind("ToplevelResponse", _state["aia_handler"], True)
        wb.show_view("AIAView", set_focus=False)
    except Exception:
        logger.debug("Could not activate AIAView", exc_info=True)


def _deactivate_aia(wb):
    """Disable AIA: give ToplevelResponse back to AssistantView, hide AIAView."""
    view = _state["assistant_unbound"]
    if view is not None:
        try:
            wb.bind("ToplevelResponse", view.handle_toplevel_response, True)
        except Exception:
            logger.debug("Could not re-bind AssistantView handler", exc_info=True)
        _state["assistant_unbound"] = None

    if _state["aia_handler"] is not None:
        try:
            wb.unbind("ToplevelResponse", _state["aia_handler"])
        except Exception:
            logger.debug("Could not unbind AIAView handler", exc_info=True)
        _state["aia_handler"] = None

    try:
        wb.hide_view("AIAView")
    except Exception:
        pass
