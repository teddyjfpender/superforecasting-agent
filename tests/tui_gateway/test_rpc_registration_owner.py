"""Re-registering an RPC family must bind it to the receiving server owner."""

from types import SimpleNamespace
from unittest.mock import Mock

from tui_gateway import server, tools_rpc


def test_tools_registration_rebinds_runtime_and_callbacks(monkeypatch):
    original = tools_rpc._core
    monkeypatch.setattr(tools_rpc, '_core', original)
    monkeypatch.setattr(tools_rpc, '_ok', tools_rpc._ok)
    monkeypatch.setattr(tools_rpc, '_err', tools_rpc._err)
    monkeypatch.setattr(tools_rpc, '_reset_session_agent', tools_rpc._reset_session_agent)
    old = SimpleNamespace(_host=SimpleNamespace(sessions={}), _load_enabled_toolsets=lambda: None)
    tools_rpc._core = old
    handlers = {}
    def register(name):
        return lambda fn: handlers.setdefault(name, fn)
    replacement = SimpleNamespace(
        _host=SimpleNamespace(sessions={}), _load_enabled_toolsets=lambda: [],
        method=register, rpc_validated=register,
        _ok=Mock(), _err=Mock(), _reset_session_agent=Mock(),
    )
    tools_rpc.register(replacement)
    assert tools_rpc._session_toolsets({'session_id': 'runtime'}) == []
    assert tools_rpc._core is replacement
    assert tools_rpc._reset_session_agent is replacement._reset_session_agent
    assert tools_rpc._ok is replacement._ok
    assert tools_rpc._err is replacement._err
    assert 'tools.list' in handlers


def test_command_registration_rebinds_receiving_owner(monkeypatch):
    from tui_gateway import commands_rpc

    names = ('_core', '_ok', '_err', '_TUI_EXTRA', '_TUI_HIDDEN')
    for name in names:
        monkeypatch.setattr(commands_rpc, name, getattr(commands_rpc, name))
    def register(name):
        return lambda fn: fn
    replacement = SimpleNamespace(
        method=register, rpc_validated=register, _ok=Mock(), _err=Mock(),
        _TUI_EXTRA=[], _TUI_HIDDEN=set(),
    )
    commands_rpc.register(replacement)
    assert commands_rpc._core is replacement
    for name in names[1:]:
        assert getattr(commands_rpc, name) is getattr(replacement, name)
