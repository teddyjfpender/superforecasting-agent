"""Delayed cleanup may only remove tracking for the captured browser resource."""


def test_close_completion_preserves_replacement_tracking(monkeypatch):
    from tools import browser_tool as browser

    old = {"session_name": "old", "bb_session_id": None}
    replacement = {"session_name": "new", "bb_session_id": None}
    monkeypatch.setattr(browser, "_active_sessions", {"task": old})
    monkeypatch.setattr(browser, "_session_last_activity", {"task": 1})
    monkeypatch.setattr(browser, "_last_active_session_key", {"task": "task"})
    monkeypatch.setattr(browser, "_recording_sessions", {"task"})
    monkeypatch.setattr(browser, "_stop_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser.os.path, "exists", lambda path: False)
    calls = []
    def command(task, action, args, **kwargs):
        calls.append((action, kwargs["_session_info"]))
        if action == "record":
            # Deterministic interleaving: replacement publishes while the old
            # resource's stop-recording request is in flight.
            browser._active_sessions[task] = replacement
            browser._session_last_activity[task] = 2
        return {"success": True}
    monkeypatch.setattr(browser, "_run_browser_command", command)
    browser.cleanup_browser("task")
    assert calls == [("record", old), ("close", old)]
    assert browser._active_sessions["task"] is replacement
    assert browser._session_last_activity["task"] == 2
    assert browser._last_active_session_key == {"task": "task"}
    assert "task" in browser._recording_sessions
