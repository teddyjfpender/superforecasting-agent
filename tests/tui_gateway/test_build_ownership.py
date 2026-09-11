"""Failed initialization cannot strand admission or replace owned resources."""
import threading
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.builds import retry_build, start_build


def failed_session():
    ready = threading.Event()
    ready.set()
    return {
        "agent_ready": ready, "agent_build_started": True,
        "agent_error": "initialization failed", "agent": object(),
    }


def test_rejected_worker_admission_finishes_error_state_and_can_retry():
    session = {"agent_ready": threading.Event(), "agent_build_started": False}
    with pytest.raises(RuntimeError, match="stopping"):
        start_build(
            session, build=Mock(),
            start=Mock(side_effect=RuntimeError("stopping")),
        )
    assert session["agent_ready"].is_set()
    assert "could not start" in session["agent_error"]
    built = Mock()

    def start():
        start_build(session, build=built, start=lambda callback: callback())

    assert retry_build(session, cleanup=Mock(), start=start) == "started"
    built.assert_called_once_with(session["agent_ready"])
    assert not session["agent_error"]


def test_failed_cleanup_retains_agent_and_blocks_rebuild_until_retry():
    session = failed_session()
    old = session["agent"]
    ready = session["agent_ready"]
    cleanup = Mock(side_effect=[OSError("still owned"), None])
    start = Mock()
    assert retry_build(session, cleanup=cleanup, start=start) == "unavailable"
    assert session["agent"] is old
    assert session["agent_ready"] is ready
    start.assert_not_called()
    assert "cleanup pending" in session["agent_error"]
    assert retry_build(session, cleanup=cleanup, start=start) == "started"
    assert session["agent"] is None
    assert session["agent_ready"] is not ready
    start.assert_called_once()


def test_active_initialization_is_not_replaced():
    session = failed_session()
    session["agent_ready"].clear()
    cleanup, start = Mock(), Mock()
    assert retry_build(session, cleanup=cleanup, start=start, timeout=0) == "unavailable"
    cleanup.assert_not_called()
    start.assert_not_called()


def test_healthy_agent_needs_no_rebuild_or_cleanup():
    session = failed_session()
    session["agent_error"] = None
    cleanup, start = Mock(), Mock()
    assert retry_build(session, cleanup=cleanup, start=start) == "ready"
    cleanup.assert_not_called()
    start.assert_not_called()


def test_cleanup_can_take_history_lock_and_completed_attempt_is_not_replayed():
    session = failed_session()
    session["history_lock"] = threading.Lock()

    def cleanup():
        assert session["history_lock"].acquire(timeout=0.1)
        session["history_lock"].release()

    callbacks = []
    built = Mock()

    def start():
        start_build(session, build=built, start=callbacks.append)

    assert retry_build(session, cleanup=cleanup, start=start) == "started"
    assert len(callbacks) == 1
    start()
    assert len(callbacks) == 1
    callbacks[0]()
    built.assert_called_once_with(session["agent_ready"])


def test_sign_in_recovery_retires_partial_agent_before_starting_replacement(monkeypatch):
    from superforecasting_agent.hosting.runtime import RuntimeHost
    from tui_gateway import server

    monkeypatch.setattr(server, "_host", RuntimeHost())
    session = failed_session()
    agent = Mock()
    agent.close.side_effect = [OSError("retry close"), None]
    session.update(agent=agent, session_key="durable", running=False)
    server._host.sessions["runtime"] = session
    restart = Mock()
    release = Mock()
    monkeypatch.setattr(server, "_start_agent_build", restart)
    monkeypatch.setattr("tools.approval.unregister_gateway_notify", release)

    assert not server._refresh_agent_credentials_after_auth("runtime", "openai-codex")
    assert session["agent"] is agent
    restart.assert_not_called()
    agent.switch_model.assert_not_called()
    assert server._refresh_agent_credentials_after_auth("runtime", "openai-codex")
    assert session["agent"] is None
    assert agent.close.call_count == 2
    release.assert_called_once_with("durable")
    restart.assert_called_once_with("runtime", session)
