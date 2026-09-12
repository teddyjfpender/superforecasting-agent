"""Concurrent callers must share one resource allocation per browser task."""

import threading
from types import SimpleNamespace

from tools import browser_tool as browser


def test_concurrent_creation_allocates_once_without_blocking_other_tasks(monkeypatch):
    monkeypatch.setattr(browser, "_active_sessions", {})
    monkeypatch.setattr(browser, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(browser, "_update_session_activity", lambda task: None)
    monkeypatch.setattr(browser, "_ensure_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_get_cdp_override", lambda: "")
    entered, release, duplicate = threading.Event(), threading.Event(), threading.Event()
    calls = []
    lock = threading.Lock()
    def create(task):
        with lock:
            calls.append(task)
            if calls.count("shared") > 1:
                duplicate.set()
        if task == "shared":
            entered.set()
            assert release.wait(3)
        return {"session_name": task, "bb_session_id": task}
    monkeypatch.setattr(browser, "_get_cloud_provider", lambda: SimpleNamespace(create_session=create))
    results, errors = [], []
    def get():
        try:
            results.append(browser._get_session_info("shared"))
        except BaseException as exc:
            errors.append(exc)
    first = threading.Thread(target=get)
    second = threading.Thread(target=get)
    first.start()
    try:
        assert entered.wait(3)
        second.start()
        other = browser._get_session_info("other")
        assert other["session_name"] == "other"
        assert not duplicate.wait(0.2), "allocated an orphan resource for the same task"
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert len(results) == 2 and results[0] is results[1]
    assert calls.count("shared") == 1


def test_failed_creation_releases_admission_for_retry(monkeypatch):
    import pytest

    monkeypatch.setattr(browser, "_active_sessions", {})
    monkeypatch.setattr(browser, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(browser, "_update_session_activity", lambda task: None)
    monkeypatch.setattr(browser, "_ensure_cdp_supervisor", lambda task: None)
    monkeypatch.setattr(browser, "_get_cdp_override", lambda: "")
    calls = []
    def create(task):
        calls.append(task)
        if len(calls) == 1:
            raise OSError("provider unavailable")
        return {"session_name": task, "bb_session_id": task}
    def fail_local(task):
        raise OSError("local unavailable")
    monkeypatch.setattr(browser, "_get_cloud_provider", lambda: SimpleNamespace(create_session=create))
    monkeypatch.setattr(browser, "_create_local_session", fail_local)
    with pytest.raises(RuntimeError, match="fallback also failed"):
        browser._get_session_info("retry")
    result = browser._get_session_info("retry")
    assert result is browser._active_sessions["retry"]
    assert calls == ["retry", "retry"]
