"""Re-registering an RPC family must bind it to the receiving server owner."""

from types import SimpleNamespace

from tui_gateway import server, tools_rpc


def test_tools_registration_keeps_original_callbacks(monkeypatch):
    from superforecasting_agent.hosting.runtime import RuntimeHost
    monkeypatch.setattr("superforecasting_agent.tooling.inventory.toolset_inventory", lambda selection: list(selection or []))
    def make_server(label):
        handlers = {}
        def register(name):
            return lambda fn: handlers.setdefault(name, fn)
        return SimpleNamespace(
            _host=RuntimeHost(), _methods=handlers, method=register, rpc_validated=register,
            _load_enabled_toolsets=lambda: [label],
            _ok=lambda rid, result: {"result": result},
            _err=lambda rid, code, message: {"error": message},
        )
    first, second = make_server("first"), make_server("second")
    tools_rpc.register(first)
    tools_rpc.register(second)
    assert first._methods["tools.list"](1, {})["result"]["toolsets"] == ["first"]
    assert second._methods["tools.list"](1, {})["result"]["toolsets"] == ["second"]
    assert not hasattr(tools_rpc, "_core")


def test_command_registration_keeps_receiving_owner():
    from tui_gateway import commands_rpc
    from superforecasting_agent.hosting.runtime import RuntimeHost

    def make_server(label):
        handlers = {}
        def register(name):
            return lambda fn: handlers.setdefault(name, fn)
        return SimpleNamespace(
            _host=RuntimeHost(), _methods=handlers, method=register, rpc_validated=register,
            _ok=lambda rid, result: {"owner": label, "result": result},
            _err=lambda rid, code, message: {"owner": label, "error": {"code": code, "message": message}},
            _TUI_EXTRA=[], _TUI_HIDDEN=set(), _load_cfg=lambda: {},
        )
    first, second = make_server("first"), make_server("second")
    commands_rpc.register(first)
    original = first._methods["command.resolve"]
    commands_rpc.register(second)
    assert original(1, {"name": "help"})["owner"] == "first"
    assert second._methods["command.resolve"](1, {"name": "help"})["owner"] == "second"
    assert not hasattr(commands_rpc, "_core")


def test_every_import_bound_rpc_family_rebinds_its_server_dependencies(monkeypatch):
    """Audit the import/registration relationship rather than a frozen file list."""
    import ast
    import importlib
    from pathlib import Path

    for path in sorted(Path(server.__file__).parent.glob('*rpc.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        imports = {}
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == 'tui_gateway.server':
                imports.update({alias.asname or alias.name: alias.name for alias in node.names})
            elif isinstance(node, ast.Import):
                imports.update({alias.asname: None for alias in node.names
                                if alias.name == 'tui_gateway.server' and alias.asname})
        if not imports:
            continue
        family = importlib.import_module(f'tui_gateway.{path.stem}')
        handlers = {}
        def register(name):
            return lambda fn: handlers.setdefault(name, fn)
        replacement = SimpleNamespace(method=register, rpc_validated=register)
        for attribute in imports.values():
            if attribute is not None:
                setattr(replacement, attribute, object())
        with monkeypatch.context() as restore:
            for name in imports:
                restore.setattr(family, name, getattr(family, name))
            family.register(replacement)
            for name, attribute in imports.items():
                expected = replacement if attribute is None else getattr(replacement, attribute)
                assert getattr(family, name) is expected, (path.name, name)
            assert handlers, path.name
