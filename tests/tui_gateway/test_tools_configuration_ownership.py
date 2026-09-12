"""The desk applies combined tool changes before one durable configuration save."""
from copy import deepcopy
import builtins

import pytest


@pytest.mark.parametrize('broken_mcp', [False, True])
def test_combined_configuration_saves_once_without_wizard_imports(monkeypatch, broken_mcp):
    from superforecasting_agent.runtime import config
    from superforecasting_agent.tooling import selection
    from tui_gateway import server

    durable = {
        'model': 'retained', 'platform_toolsets': {'cli': ['web', 'memory']},
        'mcp_servers': {'fixture': None if broken_mcp else {'tools': {'exclude': []}}},
    }
    original = deepcopy(durable)
    writes = []
    monkeypatch.setattr(config, 'load_config', lambda: deepcopy(durable))
    monkeypatch.setattr(selection, '_get_plugin_toolset_keys', lambda: set())
    def save(value):
        writes.append(deepcopy(value))
        durable.clear()
        durable.update(deepcopy(value))
    monkeypatch.setattr(config, 'save_config', save)
    original_import = builtins.__import__
    attempted = []
    def guarded(name, *args, **kwargs):
        if name in ('superforecasting_agent.runtime.tools_config', 'superforecasting_agent.runtime.setup', 'cli'):
            attempted.append(name)
            raise AssertionError('tool operation imported interactive setup')
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    response = server.handle_request({
        'jsonrpc': '2.0', 'id': 'tools', 'method': 'tools.configure',
        'params': {'action': 'disable', 'names': ['memory', 'fixture:search']},
    })
    assert attempted == []
    if broken_mcp:
        assert 'error' in response
        assert writes == []
        assert durable == original
    else:
        assert 'result' in response, response
        assert len(writes) == 1
        assert 'memory' not in durable['platform_toolsets']['cli']
        assert durable['mcp_servers']['fixture']['tools']['exclude'] == ['search']
        assert durable['model'] == 'retained'


def test_invalid_action_does_not_mutate_configuration():
    from superforecasting_agent.tooling.selection import apply_mcp_change, apply_toolset_change
    for operation, args in [(apply_mcp_change, (['fixture:search'],)), (apply_toolset_change, ('cli', ['memory']))]:
        cfg = {'platform_toolsets': {'cli': ['memory']}}
        before = deepcopy(cfg)
        with pytest.raises(ValueError, match='Unknown tools action'):
            operation(cfg, *args, 'typo')
        assert cfg == before


@pytest.mark.parametrize('broken_mcp', [False, True])
def test_cli_combined_configuration_also_saves_once(monkeypatch, broken_mcp):
    from argparse import Namespace
    from superforecasting_agent.runtime import tools_config
    from superforecasting_agent.tooling import selection

    durable = {'platform_toolsets': {'cli': ['web', 'memory']},
               'mcp_servers': {'fixture': None if broken_mcp else {}}}
    original = deepcopy(durable)
    writes = []
    monkeypatch.setattr(tools_config, 'load_config', lambda: deepcopy(durable))
    monkeypatch.setattr(selection, '_get_plugin_toolset_keys', lambda: set())
    monkeypatch.setattr(tools_config, 'save_config', lambda cfg: writes.append(deepcopy(cfg)))
    args = Namespace(tools_action='disable', platform='cli', names=['memory', 'fixture:search'])
    if broken_mcp:
        with pytest.raises(AttributeError):
            tools_config.tools_disable_enable_command(args)
        assert writes == []
    else:
        tools_config.tools_disable_enable_command(args)
        assert len(writes) == 1
        assert 'memory' not in writes[0]['platform_toolsets']['cli']
        assert writes[0]['mcp_servers']['fixture']['tools']['exclude'] == ['search']
    assert durable == original


@pytest.mark.parametrize('names', [['definitely-unknown'], ['discord'], ['missing:read'], ['fixture:read']])
def test_rejected_or_unchanged_tools_do_not_reset_session(monkeypatch, names):
    from unittest.mock import Mock
    from superforecasting_agent.hosting.runtime import RuntimeHost
    from superforecasting_agent.runtime import config
    from tui_gateway import server, tools_rpc

    monkeypatch.setattr(server, '_host', RuntimeHost())
    session = {'history': [{'role': 'user', 'content': 'preserve'}]}
    server._host.sessions.register('runtime', session)
    monkeypatch.setattr(config, 'load_config', lambda: {
        'mcp_servers': {'fixture': {'tools': {'exclude': ['read']}}},
    })
    save, reset = Mock(), Mock()
    monkeypatch.setattr(config, 'save_config', save)
    monkeypatch.setattr(tools_rpc, '_reset_session_agent', reset)
    response = server.handle_request({'id': 1, 'method': 'tools.configure',
                                     'params': {'action': 'disable', 'names': names, 'session_id': 'runtime'}})
    assert response['result']['changed'] == []
    assert response['result']['reset'] is False
    assert session['history'][0]['content'] == 'preserve'
    save.assert_not_called()
    reset.assert_not_called()


def test_failed_combined_tool_edit_preserves_callers_snapshot():
    from superforecasting_agent.tooling.selection import change_tools

    config = {'platform_toolsets': {'cli': ['memory']}, 'mcp_servers': {'broken': None}}
    before = deepcopy(config)
    with pytest.raises((AttributeError, TypeError)):
        change_tools(config, 'cli', ['memory', 'broken:read'], 'disable')
    assert config == before


@pytest.mark.parametrize('names', [None, [], 'web', 42, {'web': True}, [42], [None],
                                  [''], ['  '], ['web', False], ['fixture:'], [':read'],
                                  ['fixture:  ']])
def test_malformed_tool_names_fail_before_configuration_access(monkeypatch, names):
    from unittest.mock import Mock
    from superforecasting_agent.runtime import config
    from superforecasting_agent.tooling.selection import change_tools
    from tui_gateway import server, tools_rpc

    snapshot = {'platform_toolsets': {'cli': ['web']}}
    before = deepcopy(snapshot)
    with pytest.raises(ValueError):
        change_tools(snapshot, 'cli', names, 'disable')
    assert snapshot == before
    load, save, reset = Mock(), Mock(), Mock()
    monkeypatch.setattr(config, 'load_config', load)
    monkeypatch.setattr(config, 'save_config', save)
    monkeypatch.setattr(tools_rpc, '_reset_session_agent', reset)
    response = server.handle_request({'id': 1, 'method': 'tools.configure',
                                     'params': {'action': 'disable', 'names': names}})
    assert response['error']['code'] == 4018
    load.assert_not_called()
    save.assert_not_called()
    reset.assert_not_called()


@pytest.mark.parametrize('action', [None, [], {}, 42, True, 'typo'])
def test_malformed_tool_action_is_a_validation_error(monkeypatch, action):
    from unittest.mock import Mock
    from superforecasting_agent.runtime import config
    from superforecasting_agent.tooling.selection import change_tools
    from tui_gateway import server

    snapshot = {'platform_toolsets': {'cli': ['web']}}
    before = deepcopy(snapshot)
    with pytest.raises(ValueError, match='Unknown tools action'):
        change_tools(snapshot, 'cli', ['web'], action)
    assert snapshot == before
    load = Mock()
    monkeypatch.setattr(config, 'load_config', load)
    response = server.handle_request({'id': 1, 'method': 'tools.configure',
                                     'params': {'action': action, 'names': ['web']}})
    assert response['error']['code'] == 4017
    load.assert_not_called()


def test_tool_names_normalize_without_coercion():
    from superforecasting_agent.tooling.selection import normalize_tool_names

    assert normalize_tool_names([' web ', 'web', 'fixture:read']) == ['web', 'fixture:read']
