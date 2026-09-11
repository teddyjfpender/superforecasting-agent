"""An old agent must not reclaim replacement resources on repeated close."""

import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

from agent import session_lifecycle
from tools import terminal_tool


def make_agent():
    return SimpleNamespace(
        session_id="resource-close-owner",
        _resource_close_lock=threading.RLock(),
        _active_children_lock=threading.Lock(),
        _active_children=[],
        client=None,
    )


def test_repeated_close_preserves_replacement_environment(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    original, replacement = Mock(), Mock()
    monkeypatch.setattr(terminal_tool, "_active_environments", {agent.session_id: original})
    monkeypatch.setattr(process_registry.process_registry, "kill_all", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_browser", Mock())
    session_lifecycle.close(agent)
    original.cleanup.assert_called_once()
    terminal_tool._active_environments[agent.session_id] = replacement

    session_lifecycle.close(agent)

    assert terminal_tool._active_environments[agent.session_id] is replacement
    replacement.cleanup.assert_not_called()
    process_registry.process_registry.kill_all.assert_called_once()
    session_lifecycle.cleanup_browser.assert_called_once()


def test_concurrent_close_waits_for_the_resource_owner(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def cleanup(task_id):
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(process_registry.process_registry, "kill_all", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_vm", cleanup)
    browser = Mock()
    monkeypatch.setattr(session_lifecycle, "cleanup_browser", browser)

    def second_close():
        second_started.set()
        session_lifecycle.close(agent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(session_lifecycle.close, agent)
        try:
            assert entered.wait(3)
            second = pool.submit(second_close)
            assert second_started.wait(3)
            assert not second.done()
        finally:
            release.set()
        first.result(timeout=3)
        second.result(timeout=3)
    process_registry.process_registry.kill_all.assert_called_once()
    browser.assert_called_once()


def test_client_eviction_and_close_do_not_close_the_same_client_twice(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    client = object()
    agent.client = client
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def close_client(value, **kwargs):
        assert value is client
        entered.set()
        assert release.wait(3)

    agent._close_openai_client = Mock(side_effect=close_client)
    monkeypatch.setattr(process_registry.process_registry, "kill_all", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_vm", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_browser", Mock())

    def close():
        second_started.set()
        session_lifecycle.close(agent)

    with ThreadPoolExecutor(max_workers=2) as pool:
        eviction = pool.submit(session_lifecycle.release_clients, agent)
        try:
            assert entered.wait(3)
            shutdown = pool.submit(close)
            assert second_started.wait(3)
            assert not shutdown.done()
        finally:
            release.set()
        eviction.result(timeout=3)
        shutdown.result(timeout=3)
    agent._close_openai_client.assert_called_once()
    assert agent.client is None


def test_cleanup_callback_can_reenter_close(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    monkeypatch.setattr(process_registry.process_registry, "kill_all", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_vm", lambda _: session_lifecycle.close(agent))
    browser = Mock()
    monkeypatch.setattr(session_lifecycle, "cleanup_browser", browser)
    session_lifecycle.close(agent)
    browser.assert_called_once()
