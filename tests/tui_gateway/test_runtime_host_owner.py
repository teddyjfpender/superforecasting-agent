"""Exercise host lifetime without importing an RPC server or presentation runtime."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost


def callbacks(host):
    return dict(
        stop_services=Mock(),
        release_prompts=Mock(),
        interrupt_delegations=Mock(),
        close_session=lambda sid, session, db: host.sessions.retire(
            sid, lambda _: None, drained=True
        ),
    )


def test_failed_service_stop_blocks_restart_even_without_sessions_or_database():
    host = RuntimeHost()
    operations = callbacks(host)
    operations["stop_services"].side_effect = [OSError("service still owned"), None]
    assert not host.shutdown(0, **operations)
    reset = Mock()
    with pytest.raises(RuntimeError, match="incomplete"):
        host.start(reset_services=reset)
    reset.assert_not_called()
    assert host.shutdown(0, **operations)
    assert host.shutdown(0, **operations)
    assert operations["stop_services"].call_count == 2
    host.start(reset_services=reset)
    reset.assert_called_once()
    assert not host.workers.stopping
    operations["stop_services"].side_effect = None
    assert host.shutdown(0, **operations)


def test_close_callback_must_release_membership_before_database_close():
    host = RuntimeHost()
    db = SimpleNamespace(close=Mock())
    host.store._connection = db
    session = {"session_key": "durable"}
    host.sessions.register("runtime", session)
    operations = callbacks(host)
    retire = operations["close_session"]
    operations["close_session"] = Mock()
    assert not host.shutdown(0, **operations)
    assert host.sessions["runtime"] is session
    db.close.assert_not_called()
    operations["close_session"] = retire
    assert host.shutdown(0, **operations)
    db.close.assert_called_once()


def test_prompt_release_failure_preserves_resources_for_retry():
    host = RuntimeHost()
    db = SimpleNamespace(close=Mock())
    host.store._connection = db
    agent = SimpleNamespace(interrupt=Mock())
    session = {"session_key": "durable", "agent": agent}
    host.sessions.register("runtime", session)
    operations = callbacks(host)
    operations["release_prompts"].side_effect = [OSError("prompt release failed"), None]
    assert not host.shutdown(0, **operations)
    assert session["cancel_requested"]
    agent.interrupt.assert_called_once()
    db.close.assert_not_called()
    assert host.shutdown(0, **operations)
    db.close.assert_called_once()


def test_failed_restart_does_not_reopen_admission():
    host = RuntimeHost()
    operations = callbacks(host)
    assert host.shutdown(0, **operations)
    old_workers = host.workers
    with pytest.raises(OSError, match="reset failed"):
        host.start(reset_services=Mock(side_effect=OSError("reset failed")))
    assert host.workers is old_workers
    assert host.workers.stopping
    host.start(reset_services=Mock())
    assert host.workers is not old_workers
    assert not host.workers.stopping
    assert host.shutdown(0, **operations)


def test_shutdown_retains_command_resources_until_operation_exits():
    import threading
    from concurrent.futures import ThreadPoolExecutor

    host = RuntimeHost()
    session = {"session_key": "durable"}
    host.sessions.register("runtime", session)
    entered, release = threading.Event(), threading.Event()
    stops = []
    def command():
        with host.command(session) as stop:
            stops.append(stop)
            entered.set()
            assert release.wait(3)
    operations = callbacks(host)
    retire = operations["close_session"]
    operations["close_session"] = Mock(side_effect=retire)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(command)
        try:
            assert entered.wait(3)
            assert not host.shutdown(0, **operations)
            assert stops[0].is_set()
            assert session["_active_calls"] == 1
            operations["close_session"].assert_not_called()
        finally:
            release.set()
        future.result(timeout=3)
    assert "_command_stops" not in session
    assert host.shutdown(0, **operations)


def test_command_cancellation_is_session_scoped_and_keeps_replacements():
    host = RuntimeHost()
    first, second = {}, {}
    host.sessions.register("first", first)
    host.sessions.register("second", second)
    old = host.command(first)
    old_stop = old.__enter__()
    try:
        with host.command(first) as newer, host.command(second) as unrelated:
            old.__exit__(None, None, None)
            assert host.interrupt_commands(first) == 1
            assert newer.is_set()
            assert not old_stop.is_set()
            assert not unrelated.is_set()
    finally:
        old.__exit__(None, None, None)
    assert not first.get("_command_stops")
    assert not second.get("_command_stops")


def test_shutdown_during_command_admission_cannot_miss_cancellation(monkeypatch):
    host = RuntimeHost()
    session = {}
    host.sessions.register("runtime", session)
    admit = host.workers._admit
    def stop_after_admission():
        admit()
        host.workers.stop()
    monkeypatch.setattr(host.workers, "_admit", stop_after_admission)
    with host.command(session) as stop:
        assert stop.is_set()
    assert host.workers.drain(0)


def test_commands_reject_foreign_session_ownership():
    host = RuntimeHost()
    with pytest.raises(ValueError, match="does not belong"):
        with host.command({}):
            pytest.fail("foreign session was admitted")
    host.workers.stop()
    assert host.workers.drain(0)
