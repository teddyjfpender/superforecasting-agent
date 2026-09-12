"""RPC background work keeps the originating session's runtime/tool scope."""

from threading import Lock
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting import delegations

pytestmark = pytest.mark.usefixtures('isolated_runtime_host')


def test_background_rpc_captures_parent_scope_and_retains_failed_close(monkeypatch):
    from agent.tenant_runtime import get_toggle
    from tools.approval import get_current_session_key
    from tui_gateway import server

    monkeypatch.setattr(delegations, '_pending_cleanup', {})
    monkeypatch.setattr(delegations, '_active_subagents', {})
    parent = SimpleNamespace(model='parent-model', provider='fixture', close=Mock(), enabled_toolsets=[])
    session = {'session_key': 'parent-durable', 'history': [], 'history_lock': Lock(), 'agent': parent}
    server._host.sessions['runtime'] = session
    monkeypatch.setattr(server, '_session_toggles', {'parent-durable': {'MODEL': 'session-model', 'TUI_MAX_TURNS': '7'}})
    config = Mock(return_value={})
    monkeypatch.setattr(server, '_load_cfg', config)
    monkeypatch.setattr(server, '_get_db', lambda: None)
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    monkeypatch.setattr('superforecasting_agent.tooling.startup_selection.resolve_startup_toolsets', lambda *args, **kwargs: [])
    jobs, events = [], []
    monkeypatch.setattr(server._host.workers, 'start', lambda run, **kwargs: jobs.append(run))
    monkeypatch.setattr(server, '_emit', lambda *args: events.append(args))
    seen = {}
    child = SimpleNamespace(close=Mock(side_effect=[False, None]))
    def run(**kwargs):
        assert get_current_session_key() == 'parent-durable'
        assert get_toggle('MODEL') == 'session-model'
        return {'final_response': 'saved answer'}
    child.run_conversation = Mock(side_effect=run)
    def build(**kwargs):
        seen.update(kwargs)
        assert get_current_session_key() == 'parent-durable'
        return child
    monkeypatch.setattr('agent.agent_factory.build_agent', build)
    previous_scope = get_current_session_key()
    previous_model = get_toggle('MODEL')
    result = server.handle_request({'id': 1, 'method': 'prompt.background', 'params': {'session_id': 'runtime', 'text': 'question'}})
    task_id = result['result']['task_id']
    jobs[0]()
    assert seen['runtime'] == {}
    assert seen['provider'] == 'fixture' and seen['model'] == 'parent-model'
    assert seen['max_iterations'] == 7 and seen['enabled_toolsets'] == []
    assert seen['session_id'] == task_id
    config.assert_called_once()
    assert get_current_session_key() == previous_scope
    assert get_toggle('MODEL') == previous_model
    assert session['_background_jobs'] == 0
    assert len(delegations.pending_cleanup(session_key='parent-durable')) == 1
    assert events[-1][0:2] == ('background.complete', 'runtime')
    assert events[-1][2]['task_id'] == task_id
    assert 'saved answer' in events[-1][2]['text']
    assert 'Cleanup pending' in events[-1][2]['text']
    assert delegations.retry_cleanup(session_key='parent-durable') == (1, 0)
