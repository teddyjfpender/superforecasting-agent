"""Panel calls own their agent until all conversation work has finished."""

from unittest.mock import Mock

import pytest

from agent import agent_factory
from forecasting.quorum import make_aiagent_runner


@pytest.mark.parametrize('two_turn', [False, True])
@pytest.mark.parametrize('failure', [None, 'call', 'response', 'reconcile'])
def test_panel_agent_is_closed_once_after_the_complete_call(monkeypatch, two_turn, failure):
    agent = Mock()
    events = []
    def converse(*args, **kwargs):
        events.append('turn')
        if failure == 'call':
            raise RuntimeError('model failed')
        if failure == 'response':
            return {'failed': True, 'error': 'provider rejected'}
        return {'final_response': 'answer'}
    agent.run_conversation.side_effect = converse
    agent.close.side_effect = lambda: events.append('close')
    monkeypatch.setattr(agent_factory, 'build_agent', lambda **kwargs: agent)
    runner = make_aiagent_runner()
    def reconcile(text):
        if failure == 'reconcile':
            raise RuntimeError('invalid blind result')
        return 'reconcile'
    def run():
        if two_turn:
            return runner.two_turn('model', 'system', 'blind', reconcile)
        return runner('model', 'system', 'question')
    if failure in {'call', 'response'} or (two_turn and failure == 'reconcile'):
        with pytest.raises(RuntimeError):
            run()
    else:
        run()
    agent.close.assert_called_once_with()
    assert events[-1] == 'close'
    assert events.count('turn') == (2 if two_turn and failure is None else 1)


def test_timeout_does_not_close_an_agent_while_its_call_is_active(monkeypatch):
    import threading

    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    agent = Mock()
    def converse(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return {'final_response': 'late answer'}
    agent.run_conversation.side_effect = converse
    agent.close.side_effect = closed.set
    monkeypatch.setattr(agent_factory, 'build_agent', lambda **kwargs: agent)
    runner = make_aiagent_runner(timeout=0.1)
    try:
        with pytest.raises(RuntimeError, match='timed out'):
            runner('model', 'system', 'question')
        assert started.is_set()
        assert not closed.is_set()
    finally:
        release.set()
        assert closed.wait(3)
    agent.close.assert_called_once_with()


def test_close_failure_preserves_the_conversation_error_context(monkeypatch):
    agent = Mock()
    agent.run_conversation.side_effect = RuntimeError('model failed')
    agent.close.side_effect = OSError('cleanup incomplete')
    monkeypatch.setattr(agent_factory, 'build_agent', lambda **kwargs: agent)
    runner = make_aiagent_runner()
    with pytest.raises(OSError, match='cleanup incomplete') as error:
        runner('model', 'system', 'question')
    assert isinstance(error.value.__context__, RuntimeError)
    assert str(error.value.__context__) == 'model failed'
    agent.close.assert_called_once_with()
