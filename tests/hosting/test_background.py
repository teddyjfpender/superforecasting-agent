"""Deterministic background ownership through failures, stop and session close."""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting import delegations
from superforecasting_agent.hosting.background import start_background
from superforecasting_agent.hosting.sessions import dispose_session, reserve_close, SessionBusy
from superforecasting_agent.hosting.workers import RuntimeWorkers
from superforecasting_agent.tooling.background import stop_background, describe_background


@pytest.fixture
def owners(monkeypatch):
    monkeypatch.setattr(delegations, '_pending_cleanup', {})
    monkeypatch.setattr(delegations, '_active_subagents', {})
    monkeypatch.setattr('tools.process_registry.process_registry.list_sessions', lambda **kwargs: [])
    monkeypatch.setattr('tools.async_delegation.list_async_delegations', lambda **kwargs: [])
    return {'session_key': 'parent'}


def launch(monkeypatch, session, agent, *, report=None):
    jobs = []
    workers = Mock(spec=RuntimeWorkers)
    workers.stopping = False
    workers.start.side_effect = lambda run, **kwargs: jobs.append(run)
    build = Mock(return_value=agent)
    monkeypatch.setattr('agent.agent_factory.build_agent', build)
    report = report or Mock()
    start_background(session, workers, task_id='background', text='question',
                     options=lambda: {'provider': 'inherited'}, scope=nullcontext, report=report)
    return jobs[0], build, report


@pytest.mark.parametrize('failure', [RuntimeError('transport disposal failed'), False])
def test_failed_close_remains_owned_and_session_close_retries(monkeypatch, owners, failure):
    agent = SimpleNamespace(run_conversation=Mock(return_value={'final_response': 'answer'}),
                            close=Mock(side_effect=[failure, False, None]))
    run, build, report = launch(monkeypatch, owners, agent)
    assert owners['_background_jobs'] == 1
    with pytest.raises(SessionBusy):
        reserve_close(owners)
    run()
    build.assert_called_once_with(runtime={}, provider='inherited')
    assert owners['_background_jobs'] == 0
    assert owners['_background_agents'] == {}
    assert len(delegations.pending_cleanup(session_key='parent')) == 1
    assert 'answer' in report.call_args.args[0]
    assert 'Cleanup pending' in report.call_args.args[0]
    assert 'Cleanup pending' in describe_background(agent_running=False, session_key='parent')
    assert delegations.retry_cleanup(session_key='other') == (0, 0)
    reserve_close(owners)
    release = Mock()
    with pytest.raises(RuntimeError, match='cleanup.*pending'):
        dispose_session(owners, release_notifications=release)
    assert owners['_cleanup_pending'] is True
    dispose_session(owners, release_notifications=release)
    dispose_session(owners, release_notifications=release)
    assert agent.close.call_count == 3
    release.assert_called_once()
    assert delegations.pending_cleanup(session_key='parent') == []


def test_stop_targets_running_background_and_retries_failed_cleanup(monkeypatch, owners):
    agent = SimpleNamespace(close=Mock(side_effect=[False, None]), interrupt=Mock())
    def conversation(**kwargs):
        assert 'background' in describe_background(agent_running=False, session_key='parent')
        stop_background(session_key='other')
        agent.interrupt.assert_not_called()
        assert 'Interrupted 1 of 1 background agent' in stop_background(session_key='parent')
        return 'answer'
    agent.run_conversation = conversation
    run, _, _ = launch(monkeypatch, owners, agent)
    run()
    agent.interrupt.assert_called_once()
    assert 'Completed cleanup for 1 child agent' in stop_background(session_key='parent')
    agent.close.assert_called_with()
    assert agent.close.call_count == 2
    assert delegations.list_active_subagents(session_key='parent') == []


def test_report_failure_does_not_repeat_execution_or_drop_failed_close(monkeypatch, owners):
    agent = SimpleNamespace(run_conversation=Mock(side_effect=RuntimeError('provider failed')),
                            close=Mock(side_effect=[False, None]))
    report = Mock(side_effect=OSError('transport disconnected'))
    run, _, _ = launch(monkeypatch, owners, agent, report=report)
    run()
    agent.run_conversation.assert_called_once()
    report.assert_called_once()
    assert 'provider failed' in report.call_args.args[0]
    assert delegations.retry_cleanup(session_key='parent') == (1, 0)


def test_thread_start_failure_releases_session_reservation(owners):
    workers = Mock(spec=RuntimeWorkers)
    workers.start.side_effect = RuntimeError('cannot start worker')
    options = Mock()
    with pytest.raises(RuntimeError, match='cannot start worker'):
        start_background(owners, workers, task_id='background', text='question',
                         options=options, scope=nullcontext, report=Mock())
    options.assert_not_called()
    assert owners['_background_jobs'] == 0


def test_real_worker_keeps_credential_context_and_can_be_stopped(monkeypatch, owners):
    from threading import Event
    from agent.tenant_runtime import set_tenant_runtime, clear_tenant_runtime, get_credential_context

    entered, release = Event(), Event()
    workers = RuntimeWorkers()
    agent = SimpleNamespace(close=Mock(side_effect=[False, None]), interrupt=Mock(side_effect=lambda *args: release.set()))
    def conversation(**kwargs):
        assert get_credential_context() == {'api_key': 'parent-fixture'}
        entered.set()
        assert release.wait(5)
        return 'interrupted result'
    agent.run_conversation = Mock(side_effect=conversation)
    monkeypatch.setattr('agent.agent_factory.build_agent', lambda **kwargs: agent)
    token = set_tenant_runtime(credential={'api_key': 'parent-fixture'})
    try:
        start_background(owners, workers, task_id='thread-child', text='question',
                         options=lambda: {}, scope=nullcontext, report=Mock())
    finally:
        clear_tenant_runtime(token)
    try:
        assert entered.wait(5)
        with pytest.raises(SessionBusy):
            reserve_close(owners)
        assert 'Interrupted 1 of 1 background agent' in stop_background(session_key='parent')
    finally:
        release.set()
        workers.stop()
        assert workers.drain(5)
    assert owners['_background_jobs'] == 0
    assert 'Completed cleanup for 1 child agent' in stop_background(session_key='parent')
    assert agent.close.call_count == 2
