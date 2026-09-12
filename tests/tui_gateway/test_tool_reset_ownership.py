"""Tool-triggered resets reserve admission and retain resources on failure."""
import threading
from unittest.mock import Mock

import pytest

from tui_gateway import server


@pytest.fixture
def reset_case(monkeypatch):
    old, new, worker = Mock(), Mock(), Mock()
    session = {'agent': old, 'slash_worker': worker, 'session_key': 'durable',
               'history': [{'role': 'user', 'content': 'preserve'}],
               'history_lock': threading.Lock(), 'history_version': 7}
    build = Mock(return_value=new)
    monkeypatch.setattr(server, '_make_agent', build)
    monkeypatch.setattr(server, '_set_session_context', lambda key: None)
    monkeypatch.setattr(server, '_clear_session_context', lambda token: None)
    monkeypatch.setattr(server, '_initialize_built_agent', lambda *args: None)
    monkeypatch.setattr(server, '_session_info', lambda agent: {'model': 'replacement'})
    monkeypatch.setattr(server, '_load_show_reasoning', lambda: False)
    monkeypatch.setattr(server, '_load_tool_progress_mode', lambda: 'off')
    monkeypatch.setattr('tools.approval.unregister_gateway_notify', Mock())
    return session, old, new, worker, build


def test_reset_releases_previous_agent_and_worker_before_construction(reset_case):
    session, old, new, worker, build = reset_case
    def construct(*args, **kwargs):
        old.close.assert_called_once()
        worker.close.assert_called_once()
        assert session['_replacing'] and session['running']
        return new
    build.side_effect = construct
    assert server._reset_session_agent('runtime', session) == {'model': 'replacement'}
    assert session['agent'] is new
    assert session['history'] == [] and session['history_version'] == 8
    assert not session['running'] and not session['_replacing']
    new.close.assert_not_called()


def test_failed_disposal_preserves_old_owner_and_history(reset_case):
    session, old, _, _, build = reset_case
    old.close.side_effect = OSError('transport busy')
    with pytest.raises(RuntimeError, match='cleanup incomplete'):
        server._reset_session_agent('runtime', session)
    assert session['agent'] is old
    assert session['history_version'] == 7
    assert session['history'][0]['content'] == 'preserve'
    assert session['_cleanup_pending']
    build.assert_not_called()


def test_failed_reconstruction_preserves_history_and_records_error(reset_case):
    session, old, _, _, build = reset_case
    build.side_effect = RuntimeError('provider unavailable')
    with pytest.raises(RuntimeError, match='history preserved'):
        server._reset_session_agent('runtime', session)
    old.close.assert_called_once()
    assert session['agent'] is None
    assert session['agent_ready'].is_set()
    assert session['agent_error'] == 'provider unavailable'
    assert session['history_version'] == 7
    assert session['history'][0]['content'] == 'preserve'


def test_busy_tool_change_never_saves_configuration(monkeypatch):
    from superforecasting_agent.hosting.runtime import RuntimeHost
    from superforecasting_agent.runtime import config

    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions.register('runtime', {'running': True, 'history_lock': threading.Lock()})
    monkeypatch.setattr(config, 'load_config', lambda: {'platform_toolsets': {'cli': ['web']}})
    save = Mock()
    monkeypatch.setattr(config, 'save_config', save)
    response = server.handle_request({'id': 1, 'method': 'tools.configure',
                                     'params': {'action': 'disable', 'names': ['web'], 'session_id': 'runtime'}})
    assert 'error' in response
    assert 'busy' in response['error']['message']
    save.assert_not_called()
