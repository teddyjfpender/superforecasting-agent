"""Failed child disposal remains owned, visible and retryable by its session."""
from concurrent.futures import ThreadPoolExecutor
import threading
from unittest.mock import MagicMock, Mock

import pytest

from superforecasting_agent.hosting import delegations
from superforecasting_agent.tooling.background import describe_background, stop_background
from tools import async_delegation, delegate_tool, process_registry


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(delegations, '_active_subagents', {})
    monkeypatch.setattr(delegations, '_pending_cleanup', {})
    monkeypatch.setattr(async_delegation, '_records', {})
    monkeypatch.setattr(process_registry, 'process_registry', process_registry.ProcessRegistry())


def test_child_failure_preserves_result_and_handle_until_owned_retry():
    from tests.tools.test_delegate import _make_mock_parent

    child = MagicMock()
    child._subagent_id = 'child'
    child._credential_pool = None
    child.run_conversation.return_value = {'final_response': 'saved result', 'completed': True, 'api_calls': 1, 'messages': []}
    child.close.side_effect = [RuntimeError('transport disposal failed'), None]
    parent = _make_mock_parent()
    parent.session_id = 'desk'
    result = delegate_tool._run_single_child(0, 'work', child, parent)
    assert result['status'] == 'completed'
    assert 'transport disposal failed' in describe_background(agent_running=False, session_key='desk')
    assert delegations.list_active_subagents(session_key='desk')[0]['status'] == 'cleanup_pending'
    assert delegations.retry_cleanup(session_key='other') == (0, 0)
    child.close.assert_called_once()
    assert 'Completed cleanup for 1' in stop_background(session_key='desk')
    assert delegations.pending_cleanup(session_key='desk') == []
    assert delegations.list_active_subagents(session_key='desk') == []
    assert delegations.retry_cleanup(session_key='desk') == (0, 0)
    assert child.close.call_count == 2


def test_incomplete_close_is_not_reported_as_success():
    child = Mock()
    child.close.return_value = False
    cleanup = delegations.ChildCleanup(child, subagent_id=None, session_key='desk')
    assert cleanup.close() is False
    output = stop_background(session_key='desk')
    assert 'Cleanup still pending for 1' in output
    assert 'cleanup reported incomplete' in output
    assert len(delegations.pending_cleanup(session_key='desk')) == 1


def test_simultaneous_cleanup_calls_close_the_exact_child_once():
    entered, release = threading.Event(), threading.Event()
    child = Mock()
    def close():
        entered.set()
        assert release.wait(2)
    child.close.side_effect = close
    cleanup = delegations.ChildCleanup(child, subagent_id='child', session_key='desk')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cleanup.close)
        assert entered.wait(2)
        second = pool.submit(cleanup.close)
        release.set()
        assert first.result() is True
        assert second.result() is True
    child.close.assert_called_once()


def test_base_exception_retains_handle_without_swallowing_shutdown():
    child = Mock()
    child.close.side_effect = [KeyboardInterrupt(), None]
    cleanup = delegations.ChildCleanup(child, subagent_id='child', session_key='desk')
    with pytest.raises(KeyboardInterrupt):
        cleanup.close()
    assert delegations.pending_cleanup(session_key='desk')[0]['error'] == 'KeyboardInterrupt'
    assert delegations.retry_cleanup(session_key='desk') == (1, 0)


def test_session_close_remains_pending_until_owned_children_dispose():
    from superforecasting_agent.hosting.sessions import dispose_session

    child = Mock()
    child.close.side_effect = [RuntimeError('failed'), RuntimeError('still failed'), None]
    cleanup = delegations.ChildCleanup(child, subagent_id='child', session_key='desk')
    assert cleanup.close() is False
    other = Mock()
    other.close.return_value = False
    assert delegations.ChildCleanup(other, subagent_id='other', session_key='other').close() is False
    parent = Mock()
    parent.close.return_value = None
    session = {'session_key': 'desk', 'agent': parent}
    release = Mock()
    with pytest.raises(RuntimeError, match='delegated child cleanup'):
        dispose_session(session, release_notifications=release)
    assert session['_cleanup_pending'] is True
    dispose_session(session, release_notifications=release)
    assert session['_cleanup_pending'] is False
    parent.close.assert_called_once()
    release.assert_called_once()
    other.close.assert_called_once()
    assert len(delegations.pending_cleanup(session_key='other')) == 1


def test_session_close_retries_a_false_resource_result():
    from superforecasting_agent.hosting.sessions import dispose_session

    parent = Mock()
    parent.close.side_effect = [False, None]
    session = {'agent': parent}
    release = Mock()
    with pytest.raises(RuntimeError, match='cleanup reported incomplete'):
        dispose_session(session, release_notifications=release)
    assert 'agent' not in session['_disposed_resources']
    dispose_session(session, release_notifications=release)
    assert parent.close.call_count == 2
