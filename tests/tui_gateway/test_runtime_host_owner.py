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
