"""Global browser changes drain and exclude task lifecycle operations."""

import threading

import pytest

from superforecasting_agent.hosting.browser_connection import change_browser_endpoint
from superforecasting_agent.hosting.browser_sessions import (
    browser_endpoint_transition,
    browser_session_lifecycle,
)


def test_transition_drains_old_operations_and_blocks_new_ones():
    active, release_active = threading.Event(), threading.Event()
    cleaning, release_cleanup = threading.Event(), threading.Event()
    newcomer = threading.Event()
    environment = {"BROWSER_CDP_URL": "old"}
    failures = []
    def guarded(fn):
        def run():
            try:
                fn()
            except BaseException as exc:
                failures.append(exc)
        return run
    def operation():
        with browser_session_lifecycle("old-task"):
            active.set()
            assert release_active.wait(3)
    def cleanup():
        # The transition can call its own nested global and per-task cleanup.
        with browser_endpoint_transition(), browser_session_lifecycle("old-task"):
            cleaning.set()
            assert release_cleanup.wait(3)
    def change():
        change_browser_endpoint("new", environment=environment, cleanup=cleanup)
    def new_operation():
        with browser_session_lifecycle("new-task"):
            newcomer.set()
            assert environment["BROWSER_CDP_URL"] == "new"
    old = threading.Thread(target=guarded(operation))
    transition = threading.Thread(target=guarded(change))
    new = threading.Thread(target=guarded(new_operation))
    old.start()
    try:
        assert active.wait(3)
        transition.start()
        assert not cleaning.wait(0.2)
        release_active.set()
        assert cleaning.wait(3)
        new.start()
        assert not newcomer.wait(0.2)
        assert environment["BROWSER_CDP_URL"] == "old"
    finally:
        release_active.set()
        release_cleanup.set()
        for worker in (old, transition, new):
            if worker.ident is not None:
                worker.join(3)
    assert not failures
    assert all(not worker.is_alive() for worker in (old, transition, new))
    assert newcomer.is_set()


def test_task_cannot_deadlock_by_upgrading_to_global_transition():
    with browser_session_lifecycle("task"):
        with pytest.raises(RuntimeError, match="during a task operation"):
            with browser_endpoint_transition():
                pytest.fail("upgrade must not be admitted")
    with browser_endpoint_transition(), browser_session_lifecycle("task"):
        pass


def test_endpoint_change_waits_for_running_browser_command(monkeypatch, tmp_path):
    import os
    from types import SimpleNamespace
    from tools import browser_tool as browser

    monkeypatch.setattr(browser, "_find_agent_browser", lambda: "/fake/agent-browser")
    monkeypatch.setattr(browser, "_requires_real_termux_browser_install", lambda cmd: False)
    monkeypatch.setattr(browser, "_is_local_mode", lambda: False)
    monkeypatch.setattr(browser, "_get_browser_engine", lambda: "auto")
    monkeypatch.setattr(browser, "_socket_safe_tmpdir", lambda: str(tmp_path))
    monkeypatch.setattr(browser, "_start_browser_cleanup_thread", lambda: None)
    monkeypatch.setattr(browser, "_update_session_activity", lambda task: None)
    monkeypatch.setattr(browser, "_active_sessions", {"task": {"session_name": "owned"}})
    entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    def popen(cmd, **kwargs):
        os.write(kwargs["stdout"], b'{"success":true,"data":{}}')
        return SimpleNamespace(returncode=0)
    def wait(proc, timeout):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr(browser.subprocess, "Popen", popen)
    monkeypatch.setattr(browser, "_wait_browser_process", wait)
    results, failures = [], []
    environment = {"BROWSER_CDP_URL": "old"}
    def run():
        try:
            results.append(browser._run_browser_command("task", "snapshot", [], timeout=3))
        except BaseException as exc:
            failures.append(exc)
    def change():
        try:
            change_browser_endpoint("new", environment=environment, cleanup=cleaned.set)
        except BaseException as exc:
            failures.append(exc)
    command, transition = threading.Thread(target=run), threading.Thread(target=change)
    command.start()
    try:
        assert entered.wait(3)
        transition.start()
        assert not cleaned.wait(0.2)
        assert environment["BROWSER_CDP_URL"] == "old"
    finally:
        release.set()
        command.join(3)
        if transition.ident is not None:
            transition.join(3)
    assert not command.is_alive() and not transition.is_alive()
    assert not failures
    assert results[0]["success"] is True
    assert cleaned.is_set()
    assert environment["BROWSER_CDP_URL"] == "new"


@pytest.mark.parametrize("backend", ["cdp", "camofox"])
def test_direct_backend_operation_blocks_endpoint_change(monkeypatch, backend):
    from tools import browser_cdp_tool, browser_camofox

    entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    errors = []
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return '{"success": true}'
    if backend == "cdp":
        monkeypatch.setattr(browser_cdp_tool, "_browser_cdp_via_supervisor", blocked)
        operation = lambda: browser_cdp_tool.browser_cdp("Runtime.evaluate", frame_id="frame", task_id="task")
    else:
        monkeypatch.setattr(browser_camofox, "_sessions", {"task": {"user_id": "user"}})
        monkeypatch.setattr(browser_camofox, "_delete", blocked)
        operation = lambda: browser_camofox.camofox_close(task_id="task")
    environment = {"BROWSER_CDP_URL": "old"}
    def run():
        try:
            operation()
        except BaseException as exc:
            errors.append(exc)
    def change():
        try:
            change_browser_endpoint("new", environment=environment, cleanup=cleaned.set)
        except BaseException as exc:
            errors.append(exc)
    worker, transition = threading.Thread(target=run), threading.Thread(target=change)
    worker.start()
    try:
        assert entered.wait(3)
        transition.start()
        assert not cleaned.wait(0.2)
    finally:
        release.set()
        worker.join(3)
        if transition.ident is not None:
            transition.join(3)
    assert not errors
    assert not worker.is_alive() and not transition.is_alive()
    assert cleaned.is_set() and environment["BROWSER_CDP_URL"] == "new"


def test_cross_task_nesting_rejects_without_poisoning_admission():
    with browser_session_lifecycle("first"):
        with browser_session_lifecycle("first"):
            with pytest.raises(RuntimeError, match="across tasks"):
                with browser_session_lifecycle("second"):
                    pytest.fail("unordered nested acquisition must not be admitted")
    # Rejection must leave both per-task and global admission available.
    with browser_session_lifecycle("second"):
        pass
    with browser_endpoint_transition():
        with browser_session_lifecycle("first"), browser_session_lifecycle("second"):
            pass
