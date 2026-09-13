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


def test_stop_retains_socket_until_connection_cleanup_finishes(monkeypatch):
    """Reader exit must not let the owning loop retire an in-flight close."""
    import asyncio

    async def scenario():
        close_started = asyncio.Event()
        reader_returned = asyncio.Event()
        allow_close = asyncio.Event()
        ready = asyncio.Event()
        closed = False

        class Socket:
            async def close(self):
                nonlocal closed
                close_started.set()
                await allow_close.wait()
                closed = True

        socket = Socket()
        supervisor = bs.CDPSupervisor("close-race", "ws://fixture.invalid")
        supervisor._loop = asyncio.get_running_loop()

        async def connect(*args, **kwargs):
            return socket

        async def attach():
            ready.set()

        async def read():
            await close_started.wait()
            reader_returned.set()

        monkeypatch.setattr(bs.websockets, "connect", connect)
        monkeypatch.setattr(supervisor, "_attach_initial_page", attach)
        monkeypatch.setattr(supervisor, "_read_loop", read)
        running = asyncio.create_task(supervisor._run())
        await ready.wait()
        stopping = asyncio.create_task(asyncio.to_thread(supervisor.stop))
        try:
            await reader_returned.wait()
            # Let the reader's awaiting owner enter its finally block.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not running.done(), "owning loop returned before its socket closed"
            assert not closed
        finally:
            allow_close.set()
            await stopping
            await running
        assert closed
        assert supervisor._ws is None

    asyncio.run(scenario())


def test_stop_during_connect_retires_late_socket_without_attaching(monkeypatch):
    import asyncio

    async def scenario():
        connecting, connected = asyncio.Event(), asyncio.Event()
        closed = False

        class Socket:
            async def close(self):
                nonlocal closed
                closed = True

        async def connect(*args, **kwargs):
            connecting.set()
            await connected.wait()
            return Socket()

        async def unexpected_attach():
            pytest.fail("a stopped supervisor must not attach a new page")

        async def read():
            await asyncio.Event().wait()

        supervisor = bs.CDPSupervisor("connect-race", "ws://fixture.invalid")
        monkeypatch.setattr(bs.websockets, "connect", connect)
        monkeypatch.setattr(supervisor, "_attach_initial_page", unexpected_attach)
        monkeypatch.setattr(supervisor, "_read_loop", read)
        running = asyncio.create_task(supervisor._run())
        await connecting.wait()
        supervisor._stop_requested = True
        connected.set()
        await running
        assert closed
        assert supervisor._ws is None
        assert not supervisor._active

    asyncio.run(scenario())
