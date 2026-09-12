"""Dashboard delegation requests cannot operate outside their live session."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tools import async_delegation, delegate_tool
from superforecasting_agent.hosting import delegations
from tui_gateway import server


@pytest.fixture
def owners(monkeypatch):
    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions.register('desk', {'session_key': 'root-desk', 'history': []})
    server._host.sessions.register('other', {'session_key': 'root-other', 'history': []})
    monkeypatch.setattr(delegations, '_spawn_paused', False)
    monkeypatch.setattr(delegations, '_spawn_paused_sessions', set())
    agents = {key: Mock() for key in ('root-desk', 'root-other', '')}
    monkeypatch.setattr(delegations, '_active_subagents', {
        key: {'subagent_id': key, 'session_key': key, 'agent': agent}
        for key, agent in agents.items()
    })
    monkeypatch.setattr(async_delegation, '_records', {
        key: {'delegation_id': key, 'session_key': key, 'status': 'running'} for key in agents
    })
    return agents


def rpc(method, session='desk', **params):
    return server.handle_request({'id': 1, 'method': method,
                                 'params': {'session_id': session, **params}})


def test_status_and_interrupt_select_only_owned_records(owners):
    status = rpc('delegation.status')['result']
    assert [r['subagent_id'] for r in status['active']] == ['root-desk']
    assert [r['delegation_id'] for r in status['async']] == ['root-desk']
    assert rpc('subagent.interrupt', subagent_id='root-other')['result']['found'] is False
    owners['root-other'].interrupt.assert_not_called()
    assert rpc('subagent.interrupt', subagent_id='root-desk')['result']['found'] is True
    owners['root-desk'].interrupt.assert_called_once()


def test_pause_is_per_session_and_honors_global_admin_pause(owners):
    assert rpc('delegation.pause', paused=True)['result']['paused'] is True
    assert rpc('delegation.status')['result']['paused'] is True
    assert rpc('delegation.status', 'other')['result']['paused'] is False
    assert delegate_tool.is_spawn_paused(session_key='root-desk') is True
    delegate_tool.set_spawn_paused(True)
    assert rpc('delegation.pause', paused=False)['result']['paused'] is True
    assert delegate_tool.is_spawn_paused(session_key='root-other') is True


@pytest.mark.parametrize('method', ['delegation.status', 'delegation.pause', 'subagent.interrupt'])
def test_missing_owner_never_selects_global_scope(owners, method):
    assert 'error' in rpc(method, None, subagent_id='root-other')
    for agent in owners.values():
        agent.interrupt.assert_not_called()


@pytest.mark.parametrize('value', ['false', 0, None, [], {}])
def test_pause_requires_actual_boolean(owners, value):
    assert rpc('delegation.pause', paused=value)['error']['code'] == 4004
    with pytest.raises(ValueError, match='boolean'):
        delegations.set_spawn_paused(value, session_key='root-desk')
    assert not delegate_tool.is_spawn_paused(session_key='root-desk')


def test_nested_child_owner_is_root_not_child_session():
    parent = SimpleNamespace(session_id='root-desk')
    child = SimpleNamespace(session_id='child', _delegation_owner_key=delegate_tool._delegation_session_key(parent))
    grandchild = SimpleNamespace(session_id='grandchild', _delegation_owner_key=delegate_tool._delegation_session_key(child))
    assert delegate_tool._delegation_session_key(grandchild) == 'root-desk'


def test_nested_dispatch_obeys_root_pause_before_building(owners):
    import json

    delegate_tool.set_spawn_paused(True, session_key='root-desk')
    child = SimpleNamespace(session_id='child-session', _delegation_owner_key='root-desk')
    result = json.loads(delegate_tool.delegate_task(goal='grandchild', parent_agent=child))
    assert 'paused' in result['error']


def test_duplicate_registration_and_stale_retirement_preserve_live_owner(owners):
    original = delegations._active_subagents['root-desk']
    replacement = Mock()
    with pytest.raises(RuntimeError, match='already registered'):
        delegations.register_subagent({'subagent_id': 'root-desk', 'agent': replacement})
    delegations.unregister_subagent('root-desk', agent=replacement)
    assert delegations._active_subagents['root-desk'] is original
    delegations.unregister_subagent('root-desk', agent=owners['root-desk'])
    assert 'root-desk' not in delegations._active_subagents


def test_collision_during_child_start_closes_only_rejected_child(owners):
    from unittest.mock import MagicMock
    from tests.tools.test_delegate import _make_mock_parent

    child = MagicMock()
    child._subagent_id = 'root-desk'
    child._credential_pool = None
    result = delegate_tool._run_single_child(0, 'collision', child, _make_mock_parent())
    assert result['status'] == 'error'
    assert 'already registered' in result['error']
    child.run_conversation.assert_not_called()
    child.close.assert_called_once()
    assert delegations._active_subagents['root-desk']['agent'] is owners['root-desk']
    owners['root-desk'].close.assert_not_called()
