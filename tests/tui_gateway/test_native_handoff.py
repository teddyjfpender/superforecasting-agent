"""Native handoff owns the actual session and never launches the classic worker."""

from contextlib import closing
from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.storage.session import SessionDB
from superforecasting_agent.storage import turns
from tui_gateway import server


@pytest.mark.parametrize('completed', [False, True])
def test_native_handoff_routes_actual_session(tmp_path, monkeypatch, completed):
    import gateway.config as config
    from superforecasting_agent.application import handoff

    monkeypatch.setattr(server, '_host', RuntimeHost())
    session = {'session_key': 'durable', 'history': [], 'history_lock': Lock()}
    server._host.sessions['runtime'] = session
    monkeypatch.setattr(server, '_start_agent_build', Mock(side_effect=AssertionError('agent')))
    destination = SimpleNamespace(platforms={config.Platform.TELEGRAM: SimpleNamespace(enabled=True)}, get_home_channel=lambda p: SimpleNamespace(chat_id='fixture'))
    monkeypatch.setattr(config, 'load_gateway_config', lambda: destination)
    with closing(SessionDB(db_path=tmp_path / 'state.db')) as db:
        monkeypatch.setattr(server, '_get_db', lambda: db)
        def wait(store, key, attempt, *, stop):
            assert store is db and key == 'durable'
            assert session['running'] and session['_command_stops']
            background = server.handle_request({'id': 4, 'method': 'prompt.background', 'params': {'session_id': 'runtime', 'text': 'racing background'}})
            assert background['error']['code'] == 4009
            with pytest.raises(ValueError, match='handoff is in progress'):
                turns.start(db, key, 'racing turn')
            assert db.claim_handoff(key, attempt_id=attempt)
            if completed:
                assert db.complete_handoff(key, attempt_id=attempt)
            return handoff.observe_handoff(db, key, attempt)
        monkeypatch.setattr(handoff, 'wait_for_handoff', wait)
        result = server.handle_request({'id': 1, 'method': 'slash.exec', 'params': {'session_id': 'runtime', 'command': 'handoff telegram'}})
        assert 'error' not in result
        assert session['handoff_complete'] is completed
        assert not session['running'] and not session.get('_command_stops')
        state = db.get_handoff_state('durable')
        assert state['state'] == ('completed' if completed else 'running')
        response = server.handle_request({'id': 2, 'method': 'prompt.submit', 'params': {'session_id': 'runtime', 'text': 'blocked'}})
        assert 'error' in response
        server._start_agent_build.assert_not_called()
        if not completed:
            assert db.complete_handoff('durable', attempt_id=state['attempt_id'])
            response = server.handle_request({'id': 3, 'method': 'prompt.submit', 'params': {'session_id': 'runtime', 'text': 'late completion'}})
            assert response['error']['code'] == 4009
            server._start_agent_build.assert_not_called()


def test_handoff_rejects_active_durable_turn(tmp_path):
    with closing(SessionDB(db_path=tmp_path / 'state.db')) as db:
        db.create_session('durable', source='tui')
        turn = turns.start(db, 'durable', 'active work')
        assert not db.request_handoff('durable', 'telegram')
        turns.transition(db, turn, 'interrupted')
        assert db.request_handoff('durable', 'telegram')


@pytest.mark.parametrize('method', ['prompt.submit', 'prompt.background'])
@pytest.mark.parametrize('claimed', [False, True])
def test_reconnected_session_observes_durable_handoff(tmp_path, monkeypatch, method, claimed):
    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions['runtime'] = {'session_key': 'durable', 'history': [], 'history_lock': Lock()}
    monkeypatch.setattr(server, '_start_agent_build', Mock(side_effect=AssertionError('agent')))
    with closing(SessionDB(db_path=tmp_path / 'state.db')) as db:
        db.create_session('durable', source='tui')
        assert db.request_handoff('durable', 'telegram')
        if claimed:
            assert db.claim_handoff('durable', attempt_id=db.get_handoff_state('durable')['attempt_id'])
        monkeypatch.setattr(server, '_get_db', lambda: db)
        result = server.handle_request({'id': 1, 'method': method, 'params': {'session_id': 'runtime', 'text': 'reconnected work'}})
        assert result['error']['code'] == 4009
        assert 'handoff is in progress' in result['error']['message']
        server._start_agent_build.assert_not_called()


@pytest.mark.parametrize('method', ['prompt.submit', 'prompt.background'])
def test_handoff_read_failure_is_not_no_handoff(tmp_path, monkeypatch, method):
    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions['runtime'] = {'session_key': 'durable', 'history': [], 'history_lock': Lock()}
    monkeypatch.setattr(server, '_start_agent_build', Mock(side_effect=AssertionError('agent')))
    db = SessionDB(db_path=tmp_path / 'state.db')
    db.close()
    monkeypatch.setattr(server, '_get_db', lambda: db)
    result = server.handle_request({'id': 1, 'method': method, 'params': {'session_id': 'runtime', 'text': 'unsafe work'}})
    assert result['error']['code'] == 5030
    assert 'Cannot verify handoff' in result['error']['message']
    server._start_agent_build.assert_not_called()
