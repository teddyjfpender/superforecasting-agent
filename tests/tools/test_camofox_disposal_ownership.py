"""Failed remote disposal preserves Camofox ownership for a truthful retry."""

import json

import pytest

from tools import browser_camofox as camofox, browser_tool as browser


def test_failed_close_retains_exact_session_until_success(monkeypatch):
    session = {"user_id": "owned-user", "tab_id": "owned-tab", "session_key": "owned"}
    monkeypatch.setattr(camofox, "_sessions", {"task": session})
    attempts = []
    def delete(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise OSError("remote unavailable")
        return {"ok": True}
    monkeypatch.setattr(camofox, "_delete", delete)
    failed = json.loads(camofox.camofox_close("task"))
    assert failed == {"success": False, "closed": False, "error": "remote unavailable"}
    assert camofox._sessions["task"] is session
    assert json.loads(camofox.camofox_close("task")) == {"success": True, "closed": True}
    assert "task" not in camofox._sessions
    assert attempts == ["/sessions/owned-user", "/sessions/owned-user"]
    camofox.camofox_close("task")
    assert len(attempts) == 2


def test_remote_close_failure_reaches_task_cleanup_owner(monkeypatch):
    session = {"user_id": "owned-user"}
    monkeypatch.setattr(camofox, "_sessions", {"task": session})
    monkeypatch.setattr(camofox, "_get_camofox_config", lambda: {})
    monkeypatch.setattr(camofox, "_camofox_identity_override", lambda *args: None)
    monkeypatch.setattr(browser, "_is_camofox_mode", lambda: True)
    monkeypatch.setattr(browser, "_stop_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_active_sessions", {})
    def fail(path):
        raise OSError("remote unavailable")
    monkeypatch.setattr(camofox, "_delete", fail)
    with pytest.raises(RuntimeError, match="remote unavailable"):
        browser.cleanup_browser("task")
    assert camofox._sessions["task"] is session


@pytest.mark.parametrize("healthy_key", ["healthy", "failed::local"])
def test_global_cleanup_finds_camofox_only_sessions_after_mode_change(monkeypatch, healthy_key):
    monkeypatch.setattr(camofox, "_sessions", {"failed": {"user_id": "one"}, healthy_key: {"user_id": "two"}})
    monkeypatch.setattr(camofox, "_get_camofox_config", lambda: {})
    monkeypatch.setattr(camofox, "_camofox_identity_override", lambda *args: None)
    monkeypatch.setattr(browser, "_active_sessions", {})
    monkeypatch.setattr(browser, "_is_camofox_mode", lambda: False)
    monkeypatch.setattr(browser, "_stop_cdp_supervisor", lambda task: None)
    from tools.browser_supervisor import SUPERVISOR_REGISTRY
    stopped = []
    monkeypatch.setattr(SUPERVISOR_REGISTRY, "stop_all", lambda: stopped.append(True))
    attempts = []
    def delete(path):
        attempts.append(path)
        if path.endswith("one"):
            raise OSError("offline")
        return {"ok": True}
    monkeypatch.setattr(camofox, "_delete", delete)
    with pytest.raises(RuntimeError, match="cleanup incomplete"):
        browser.cleanup_all_browsers()
    assert attempts == ["/sessions/one", "/sessions/two"]
    assert camofox.camofox_session_keys() == ("failed",)
    assert stopped == [True]
