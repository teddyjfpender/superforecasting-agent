"""An old agent must not reclaim replacement resources on repeated close."""

import threading

import pytest
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


def test_eviction_detaches_client_before_cleanup_can_install_replacement(monkeypatch):
    agent = make_agent()
    original, replacement = object(), object()
    agent.client = original

    def close_client(client, **kwargs):
        assert client is original
        assert agent.client is None
        agent.client = replacement

    agent._close_openai_client = Mock(side_effect=close_client)
    session_lifecycle.release_clients(agent)
    assert agent.client is replacement


def test_closed_agent_cannot_rebuild_client():
    from agent import openai_clients

    agent = make_agent()
    agent._resources_closed = True
    agent._client_lock = threading.RLock()
    agent._openai_client_lock = lambda: agent._client_lock
    agent._create_openai_client = Mock(side_effect=AssertionError("closed owner rebuilt"))
    assert not openai_clients._replace_primary_openai_client(agent, reason="test")
    agent._create_openai_client.assert_not_called()


def test_close_during_construction_disposes_unpublished_client(monkeypatch):
    from agent import openai_clients
    from tools import process_registry

    agent = make_agent()
    agent._client_lock = threading.RLock()
    agent._openai_client_lock = lambda: agent._client_lock
    agent._client_kwargs = {}
    client = object()
    monkeypatch.setattr(session_lifecycle, "cleanup_vm", Mock())
    monkeypatch.setattr(session_lifecycle, "cleanup_browser", Mock())
    monkeypatch.setattr(process_registry.process_registry, "kill_all", Mock())

    def build(*args, **kwargs):
        session_lifecycle.close(agent)
        return client

    agent._create_openai_client = build
    agent._close_openai_client = Mock()
    assert not openai_clients._replace_primary_openai_client(agent, reason="test")
    assert agent.client is None
    agent._close_openai_client.assert_called_once_with(client, reason="closed_during_build", shared=True)


def test_concurrent_rebuild_survives_eviction_cleanup():
    from agent import openai_clients

    agent = make_agent()
    agent._client_lock = threading.RLock()
    agent._openai_client_lock = lambda: agent._client_lock
    agent._client_kwargs = {}
    original, replacement = object(), object()
    agent.client = original
    agent._create_openai_client = lambda *args, **kwargs: replacement
    entered, release = threading.Event(), threading.Event()
    closed = []

    def close_client(client, **kwargs):
        if client is None:
            return
        closed.append(client)
        if client is original:
            entered.set()
            assert release.wait(3)

    agent._close_openai_client = close_client
    with ThreadPoolExecutor(max_workers=2) as pool:
        eviction = pool.submit(session_lifecycle.release_clients, agent)
        try:
            assert entered.wait(3)
            assert openai_clients._replace_primary_openai_client(agent, reason="rebuild")
        finally:
            release.set()
        eviction.result(timeout=3)
    assert agent.client is replacement
    assert closed == [original]


def test_failed_child_close_retries_handle_without_reaping_replacement(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    child = Mock()
    child.close.side_effect = [OSError('temporary cleanup failure'), None]
    agent._active_children = [child]
    kill = Mock()
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', kill)
    original, replacement = Mock(), Mock()
    monkeypatch.setattr(terminal_tool, '_active_environments', {agent.session_id: original})
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', Mock())
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        session_lifecycle.close(agent)
    assert agent._pending_child_closes == [child]
    terminal_tool._active_environments[agent.session_id] = replacement
    session_lifecycle.close(agent)
    assert agent._pending_child_closes == []
    assert child.close.call_count == 2
    kill.assert_called_once()
    replacement.cleanup.assert_not_called()
    session_lifecycle.close(agent)
    assert child.close.call_count == 2


def test_failed_child_eviction_retains_handle_for_full_shutdown(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    child = Mock()
    child.release_clients.side_effect = OSError('eviction failure')
    child.close.side_effect = [OSError('close failure'), None]
    agent._active_children = [child]
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        session_lifecycle.release_clients(agent)
    assert agent._pending_child_closes == [child]
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_vm', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', Mock())
    session_lifecycle.close(agent)
    assert agent._pending_child_closes == []
    child.release_clients.assert_called_once()
    assert child.close.call_count == 2


def test_child_cleanup_failure_does_not_skip_siblings_or_repeat_on_reentry(monkeypatch):
    from tools import process_registry

    agent = make_agent()
    first, second = Mock(), Mock()
    def fail():
        session_lifecycle.close(agent)
        raise OSError('cleanup failure')
    first.close.side_effect = fail
    second.close.side_effect = lambda: session_lifecycle.close(agent)
    agent._active_children = [first, second, first]
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_vm', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', Mock())
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        session_lifecycle.close(agent)
    first.close.assert_called_once()
    second.close.assert_called_once()
    assert agent._pending_child_closes == [first]


def test_host_retains_agent_until_failed_child_disposal_succeeds(monkeypatch):
    from superforecasting_agent.hosting.sessions import dispose_session
    from tools import process_registry

    agent = make_agent()
    child = Mock()
    child.close.side_effect = [OSError('temporary disposal failure'), None]
    agent._active_children = [child]
    agent.close = lambda: session_lifecycle.close(agent)
    session = {'agent': agent}
    monkeypatch.setattr(process_registry.process_registry, 'kill_all', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_vm', Mock())
    monkeypatch.setattr(session_lifecycle, 'cleanup_browser', Mock())
    with pytest.raises(RuntimeError, match='Session cleanup incomplete'):
        dispose_session(session, release_notifications=lambda: None)
    assert session['_cleanup_pending']
    assert 'agent' not in session['_disposed_resources']
    dispose_session(session, release_notifications=lambda: None)
    assert not session['_cleanup_pending']
    assert session['_disposed_resources']['agent'] is agent
    assert child.close.call_count == 2
