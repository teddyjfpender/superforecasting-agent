"""Reload persistence stays in the gateway profile without classic CLI imports."""
import builtins

import yaml


def test_reload_always_preserves_profile_settings_without_cli(tmp_path, monkeypatch):
    from tools import mcp_tool
    from tui_gateway import server

    monkeypatch.setattr(server, '_hermes_home', tmp_path)
    monkeypatch.setattr(mcp_tool, 'shutdown_mcp_servers', lambda: None)
    monkeypatch.setattr(mcp_tool, 'discover_mcp_tools', lambda: None)
    path = tmp_path / 'config.yaml'
    path.write_text('model: fixture\napprovals:\n  other_setting: true\n', encoding='utf-8')
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == 'cli':
            raise AssertionError('gateway persistence imported the classic CLI')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    response = server.handle_request({'jsonrpc': '2.0', 'id': 'reload', 'method': 'reload.mcp',
                                      'params': {'confirm': True, 'always': True}})
    assert response['result']['status'] == 'reloaded'
    assert yaml.safe_load(path.read_text(encoding='utf-8')) == {
        'model': 'fixture', 'approvals': {'other_setting': True, 'mcp_reload_confirm': False},
    }
