"""Resolve a screenshot point into an observed, guarded browser action."""


def visual_act(session, x, y, text=None):
    """Act on viewport CSS coordinates from the session's latest fresh frame."""
    from .session import SessionError, commit_word

    with session.lock:
        page = session.page
        if (not page or not getattr(session, "frame", None)
                or getattr(session, "_visual_frame_marker", None) != page.get("marker")
                or page.get("marker") is None or not getattr(session, "_visual_frame_state", None)):
            raise SessionError("A fresh screenshot is required. Observe again.")
        if text is not None and not isinstance(text, str):
            raise SessionError("Text must be a string")
        try:
            action = session.browser.observe_point(page, x, y, text=text, visual_state=session._visual_frame_state)
        except ValueError as error:
            raise SessionError(str(error)) from error
        label = action.get("label", "")
        if any(a and a.lower() in label.lower() for a in getattr(session, "avoid", [])):
            raise SessionError("The target is on the avoid list. Nothing executed.")
        steps = (getattr(session, "test", None) or {}).get("steps", [])
        current = next((s for s in steps if s.get("status") in {"running", "pending"}), {})
        intent = " ".join([getattr(session, "goal", None) or "", current.get("title", "")]).lower()
        word = commit_word(label) if action["kind"] == "click" else None
        commit = bool(word or action.get("submits"))
        if getattr(session, "read_only", False) and (
                text is not None or commit or action.get("role") in {"checkbox", "radio", "switch"}):
            raise SessionError("This intent is read-only. Nothing executed.")
        if commit and not ((word and word in intent) or (action.get("submits") and "submit" in intent)):
            raise SessionError("A committing action needs an explicit goal or step. Nothing executed.")
        if text:
            stated = " ".join([getattr(session, "goal", None) or ""]
                              + [s.get("title", "") for s in steps]
                              + list(getattr(session, "notes", []))).lower()
            if text.strip().lower() not in stated:
                raise SessionError("The value is not stated in the goal, plan, or notes. Nothing executed.")
        original = page["actions"]
        page["actions"] = [*original, action]
        try:
            return session.act(ref=action["id"], text=text, by="pilot")
        finally:
            if session.page is page:
                page["actions"] = original


def visual_hover(session, x, y):
    """Hover on a safe point in the latest fresh screenshot."""
    from .session import SessionError

    with session.lock:
        page = session.page
        if (not page or not getattr(session, "frame", None) or not getattr(session, "last_capture_ok", False)
                or getattr(session, "_visual_frame_marker", None) != page.get("marker")
                or page.get("marker") is None or not getattr(session, "_visual_frame_state", None)):
            raise SessionError("A fresh screenshot is required. Observe again.")
        try:
            action = session.browser.observe_point(page, x, y, visual_state=session._visual_frame_state)
        except ValueError as error:
            raise SessionError(str(error)) from error
        return session._hover_action(action)
