"""Stopped session pollers cannot drain shared work or start model turns."""

import queue
import threading
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tools.process_registry import process_registry
from tui_gateway import server


@pytest.mark.parametrize("state", ["stopped", "finalized", "closing", "acquiring", "busy"])
def test_unadmitted_completion_remains_queued(monkeypatch, state):
    stop = threading.Event()
    event = {"type": "completion", "session_id": "fixture-process", "command": "fixture", "exit_code": 0}

    class CompletionQueue(queue.Queue):
        def get(self, *args, **kwargs):
            result = super().get(*args, **kwargs)
            if state == "acquiring":
                stop.set()
            return result

    pending = CompletionQueue()
    pending.put(event)
    monkeypatch.setattr(process_registry, "completion_queue", pending)
    monkeypatch.setattr(process_registry, "is_completion_consumed", lambda _: False)
    monkeypatch.setattr(server, "_host", RuntimeHost())
    emit = Mock(side_effect=AssertionError("unadmitted event was displayed"))
    run = Mock(side_effect=AssertionError("unadmitted model turn"))
    monkeypatch.setattr(server, "_emit", emit)
    monkeypatch.setattr(server, "_run_prompt_submit", run)
    session = {"history_lock": threading.Lock(), "session_key": "fixture-session"}
    if state == "stopped":
        stop.set()
    elif state == "finalized":
        session["_finalized"] = True
    elif state == "closing":
        session["_closing"] = True
    elif state == "busy":
        session["running"] = True
        monkeypatch.setattr(stop, "wait", lambda timeout: stop.set())

    server._notification_poller_loop(stop, "fixture", session)

    assert pending.get_nowait() is event
    assert pending.empty()
    emit.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("kind", ["async_delegation", "completion", "watch_match", "watch_disabled"])
def test_foreign_notification_stays_with_its_session(monkeypatch, kind):
    stop = threading.Event()
    event = {"type": kind, "session_key": "owner", "session_id": "process", "_route_attempts": 1000000}
    pending = queue.Queue()
    pending.put(event)
    monkeypatch.setattr(process_registry, "completion_queue", pending)
    monkeypatch.setattr(process_registry, "is_completion_consumed", lambda _: False)
    monkeypatch.setattr(stop, "wait", lambda _: stop.set())
    run = Mock(side_effect=AssertionError("foreign result started a turn"))
    emit = Mock(side_effect=AssertionError("foreign result was displayed"))
    monkeypatch.setattr(server, "_run_prompt_submit", run)
    monkeypatch.setattr(server, "_emit", emit)
    server._notification_poller_loop(stop, "foreign", {"session_key": "foreign"})
    assert pending.get_nowait() is event
    assert server._route_async_completion(event, "owner") == "consume"
    run.assert_not_called()
    emit.assert_not_called()
