"""Cloud browser disposal stays with the creating provider until confirmed."""

from types import SimpleNamespace

import pytest

from tools import browser_tool as browser


def test_failed_cloud_close_retains_creating_provider_and_blocks_reuse(monkeypatch):
    monkeypatch.setattr(browser, "_active_sessions", {})
    monkeypatch.setattr(browser, "_session_last_activity", {})
    monkeypatch.setattr(browser, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(browser, "_update_session_activity", lambda task: None)
    monkeypatch.setattr(browser, "_ensure_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_stop_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_get_cdp_override", lambda: "")
    monkeypatch.setattr(browser, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser, "_maybe_stop_recording", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "_run_browser_command", lambda *args, **kwargs: {"success": True})
    monkeypatch.setattr(browser.os.path, "exists", lambda path: False)
    attempts = []
    def close(session_id):
        attempts.append(session_id)
        return len(attempts) > 1
    original = SimpleNamespace(create_session=lambda task: {"session_name": "owned", "bb_session_id": "remote"}, close_session=close)
    monkeypatch.setattr(browser, "_get_cloud_provider", lambda: original)
    session = browser._get_session_info("task")
    def wrong_provider():
        raise AssertionError("must not resolve the current provider during disposal")
    monkeypatch.setattr(browser, "_get_cloud_provider", wrong_provider)
    with pytest.raises(RuntimeError, match="did not confirm"):
        browser.cleanup_browser("task")
    assert browser._active_sessions["task"] is session
    with pytest.raises(RuntimeError, match="cleanup is pending"):
        browser._get_session_info("task")
    browser.cleanup_browser("task")
    assert "task" not in browser._active_sessions
    assert attempts == ["remote", "remote"]
