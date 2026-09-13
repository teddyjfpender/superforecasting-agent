"""Deterministic supervisor ownership tests without a browser or network."""

import threading
from types import SimpleNamespace

import pytest

from tools import browser_supervisor as bs


class Supervisor:
    def __init__(self, *, task_id="task", cdp_url="old", **kwargs):
        self.cdp_url = cdp_url
        self._thread = SimpleNamespace(is_alive=lambda: True)
        self._loop = SimpleNamespace(is_running=lambda: True)
        self._stop_requested = False
        self.stop_calls = 0
        self.fail_stop = False

    def start(self, **kwargs):
        pass

    def stop(self):
        self.stop_calls += 1
        self._stop_requested = True
        if self.fail_stop:
            raise OSError("close failed")


def test_failed_close_is_retained_and_retried_before_replacement(monkeypatch):
    registry = bs._SupervisorRegistry()
    old = Supervisor()
    old.fail_stop = True
    registry._by_task["task"] = old
    created = []
    def factory(**kwargs):
        created.append(Supervisor(**kwargs))
        return created[-1]
    monkeypatch.setattr(bs, "CDPSupervisor", factory)
    with pytest.raises(OSError):
        registry.get_or_start("task", "new")
    assert registry._by_task["task"] is old
    assert registry.get("task") is None
    assert not created
    old.fail_stop = False
    new = registry.get_or_start("task", "new")
    assert registry.get("task") is new
    assert old.stop_calls == 2


def test_start_failure_retains_handle_when_cleanup_fails(monkeypatch):
    registry = bs._SupervisorRegistry()
    broken = Supervisor()
    broken.fail_stop = True
    def fail_start(**kwargs):
        raise ValueError("start failed")
    broken.start = fail_start
    monkeypatch.setattr(bs, "CDPSupervisor", lambda **kwargs: broken)
    with pytest.raises(OSError) as caught:
        registry.get_or_start("task", "old")
    assert isinstance(caught.value.__context__, ValueError)
    assert registry._by_task["task"] is broken
    broken.fail_stop = False
    registry.stop("task")
    assert "task" not in registry._by_task


def test_concurrent_start_cannot_publish_over_owned_start(monkeypatch):
    registry = bs._SupervisorRegistry()
    entered, release = threading.Event(), threading.Event()
    instance = Supervisor()
    def start(**kwargs):
        entered.set()
        assert release.wait(3)
    instance.start = start
    monkeypatch.setattr(bs, "CDPSupervisor", lambda **kwargs: instance)
    outcomes = []
    worker = threading.Thread(target=lambda: outcomes.append(registry.get_or_start("task", "old")))
    worker.start()
    try:
        assert entered.wait(3)
        with pytest.raises(RuntimeError, match="in progress"):
            registry.get_or_start("task", "new")
        with pytest.raises(RuntimeError, match="in progress"):
            registry.stop("task")
        assert registry.get("task") is None
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert outcomes == [instance]
    assert registry.get("task") is instance


def test_stop_all_attempts_other_handles_and_retains_failures():
    registry = bs._SupervisorRegistry()
    failed, healthy = Supervisor(), Supervisor()
    failed.fail_stop = True
    registry._by_task.update(failed=failed, healthy=healthy)
    with pytest.raises(RuntimeError, match="1 browser"):
        registry.stop_all()
    assert registry._by_task == {"failed": failed}
    assert healthy.stop_calls == 1


def test_old_stop_snapshot_does_not_close_replacement():
    registry = bs._SupervisorRegistry()
    old, new = Supervisor(), Supervisor()
    registry._by_task["task"] = new
    registry._stop_owned("task", old)
    assert new.stop_calls == 0
    assert registry.get("task") is new


def test_stop_timeout_does_not_report_inactive():
    supervisor = bs.CDPSupervisor.__new__(bs.CDPSupervisor)
    supervisor._loop = None
    supervisor._thread = SimpleNamespace(join=lambda **kwargs: None, is_alive=lambda: True)
    supervisor._state_lock = threading.Lock()
    supervisor._active = True
    with pytest.raises(TimeoutError):
        supervisor.stop(timeout=0)
    assert supervisor._active is True
    assert supervisor._stop_requested is True
