"""Conversation ownership ends only after callers relinquish exact agents."""

import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from agent.conversation_lifecycle import AgentConversations
from superforecasting_agent.hosting.workers import HostStopping


@pytest.mark.parametrize('failure', [False, True])
def test_fresh_agent_closes_after_success_or_failure(failure):
    agent = Mock()
    agent.close.return_value = None
    agent.run_conversation.side_effect = ValueError('provider failure') if failure else None
    owner = AgentConversations(lambda: agent, fresh=True)
    if failure:
        with pytest.raises(ValueError, match='provider failure'):
            owner.run('request', system_message='policy')
    else:
        assert owner.run('request', system_message='policy') is agent.run_conversation.return_value
    agent.close.assert_called_once()
    owner.close()
    agent.close.assert_called_once()


def test_reused_agent_closes_once_at_batch_end():
    agent = Mock()
    factory = Mock(return_value=agent)
    owner = AgentConversations(factory, fresh=False)
    for _ in range(3):
        owner.run('request', system_message='policy')
    factory.assert_called_once()
    agent.close.assert_not_called()
    owner.close()
    owner.close()
    agent.close.assert_called_once()
    with pytest.raises(HostStopping):
        owner.run('late request', system_message='policy')


@pytest.mark.parametrize('fresh', [False, True])
def test_close_cannot_dispose_an_inflight_conversation(fresh):
    entered, release = threading.Event(), threading.Event()
    agent = Mock()
    def run(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        return 'saved result'
    agent.run_conversation.side_effect = run
    owner = AgentConversations(lambda: agent, fresh=fresh)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner.run, 'request', system_message='policy')
        try:
            assert entered.wait(3)
            with pytest.raises(RuntimeError, match='still running'):
                owner.close()
            agent.close.assert_not_called()
        finally:
            release.set()
        assert future.result(timeout=3) == 'saved result'
    owner.close()
    agent.close.assert_called_once()


def test_failed_cleanup_retains_exact_handle_for_retry():
    agent = Mock()
    agent.close.side_effect = [OSError('transport not closed'), False, None]
    owner = AgentConversations(lambda: agent, fresh=True)
    with pytest.raises(OSError, match='transport not closed'):
        owner.run('request', system_message='policy')
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        owner.close()
    owner.close()
    assert agent.close.call_count == 3
    owner.close()
    assert agent.close.call_count == 3


@pytest.mark.parametrize('fresh', [False, True])
def test_deadline_interrupts_exact_agent_rejects_late_result_and_retires_it(fresh):
    expired = threading.Event()
    first = Mock()
    first.interrupt.side_effect = expired.set
    def run(*args, **kwargs):
        assert expired.wait(3)
        return 'late probability'
    first.run_conversation.side_effect = run
    replacement = Mock()
    factory = Mock(side_effect=[first, replacement])
    owner = AgentConversations(factory, fresh=fresh)
    with pytest.raises(TimeoutError):
        owner.run('request', system_message='policy', timeout=0.02)
    first.interrupt.assert_called_once_with()
    first.close.assert_called_once_with()
    owner.run('next', system_message='policy', timeout=3)
    replacement.interrupt.assert_not_called()
    owner.close()


def test_expired_uncooperative_call_keeps_ownership_until_it_returns():
    expired, release = threading.Event(), threading.Event()
    agent = Mock()
    agent.interrupt.side_effect = expired.set
    def run(*args, **kwargs):
        assert release.wait(3)
        return 'late result'
    agent.run_conversation.side_effect = run
    owner = AgentConversations(lambda: agent, fresh=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(owner.run, 'request', system_message='policy', timeout=0.02)
        try:
            assert expired.wait(3)
            assert not future.done()
            with pytest.raises(RuntimeError, match='still running'):
                owner.close()
            agent.close.assert_not_called()
        finally:
            release.set()
        with pytest.raises(TimeoutError):
            future.result(timeout=3)
    owner.close()
    agent.close.assert_called_once_with()


@pytest.mark.parametrize('timeout', [0, -1, float('nan'), float('inf'), True])
def test_invalid_deadline_never_constructs_an_agent(timeout):
    factory = Mock()
    owner = AgentConversations(factory, fresh=True)
    with pytest.raises(ValueError, match='finite positive'):
        owner.run('request', system_message='policy', timeout=timeout)
    factory.assert_not_called()
    owner.close()
