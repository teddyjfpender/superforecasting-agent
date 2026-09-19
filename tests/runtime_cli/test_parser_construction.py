"""The real runtime command tree is inspectable without executing CLI startup."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from superforecasting_agent.runtime import main as runtime


def test_builtin_construction_skips_startup_and_plugin_discovery(monkeypatch):
    import plugins.memory as memory
    from superforecasting_agent.runtime import plugins

    def forbidden(*args, **kwargs):
        raise AssertionError('construction must not invoke startup or discovery')
    for name in ('_cleanup_quarantined_exes', '_try_launch_top_level_tui_fast_path', '_plugin_cli_discovery_needed'):
        monkeypatch.setattr(runtime, name, forbidden)
    monkeypatch.setattr(memory, 'discover_plugin_cli_commands', forbidden)
    monkeypatch.setattr(plugins, 'discover_plugins', forbidden)
    parser, choices = runtime.build_runtime_parser()
    assert {'forecast', 'data', 'model', 'logs', 'gateway', 'profile'} <= choices.choices.keys()
    args = parser.parse_args(['logs', '--lines', '7'])
    assert args.lines == 7 and args.func is runtime.cmd_logs
    assert parser.parse_args(['forecast', 'list']).forecast_command == 'list'
    # The optimization list can deliberately include help, but cannot invent roots.
    assert runtime._BUILTIN_SUBCOMMANDS - choices.choices.keys() == {'help'}


def test_plugin_parser_contributions_are_explicit_and_keep_handlers(monkeypatch):
    import plugins.memory as memory
    from superforecasting_agent.runtime import plugins

    calls = []
    def setup(parser):
        parser.add_argument('--fixture', default='default')
    def handler(args):
        calls.append(args.fixture)
    command = {'name': 'fixture-plugin', 'help': 'Fixture', 'setup_fn': setup, 'handler_fn': handler}
    monkeypatch.setattr(memory, 'discover_plugin_cli_commands', lambda: [])
    monkeypatch.setattr(plugins, 'discover_plugins', lambda: calls.append('discovery'))
    monkeypatch.setattr(plugins, 'get_plugin_manager', lambda: SimpleNamespace(_cli_commands={'fixture': command}))
    parser, choices = runtime.build_runtime_parser(include_plugins=True)
    args = parser.parse_args(['fixture-plugin', '--fixture', 'value'])
    assert args.func is handler
    assert calls == ['discovery']  # Construction never executes the callback.
    args.func(args)
    assert calls == ['discovery', 'value']


@pytest.mark.parametrize('arguments', [['--help'], ['--version'], ['forecast', '--help'], ['logs', '--help']])
def test_real_entrypoint_help_and_version_need_no_credentials(tmp_path, arguments):
    env = {key: value for key, value in os.environ.items()
           if not any(marker in key for marker in ('API_KEY', 'TOKEN', 'PASSWORD'))}
    env.update(SUPERFORECASTING_AGENT_HOME=str(tmp_path), HERMES_HOME=str(tmp_path))
    result = subprocess.run([sys.executable, '-m', 'superforecasting_agent', *arguments],
                            input='', capture_output=True, text=True, env=env, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip()
    assert 'Traceback' not in result.stderr


def test_runtime_inventory_walks_actual_parser_without_duplicate_alias_pages():
    from scripts.docgen.runtime_commands_doc import render

    result = render()
    assert result.count('| `superforecasting-agent logs` |') == 1
    assert '| `superforecasting-agent forecast import fred` |' in result
    assert 'superforecasting_agent.runtime.main.cmd_logs' in result
    assert 'Plugin commands are intentionally excluded' in result
    assert render() == result


def test_main_dispatch_uses_constructed_parser_and_executes_once(monkeypatch):
    from superforecasting_agent.runtime import config

    calls = []
    monkeypatch.setattr(runtime, '_cleanup_quarantined_exes', lambda: calls.append('startup'))
    monkeypatch.setattr(runtime, '_try_launch_top_level_tui_fast_path', lambda argv: False)
    monkeypatch.setattr(config, 'get_container_exec_info', lambda: None)
    monkeypatch.setattr(runtime, 'cmd_logs', lambda args: calls.append(('logs', args.lines)))
    monkeypatch.setattr(sys, 'argv', ['superforecasting-agent', 'logs', '--lines', '7'])
    runtime._main()
    assert calls == ['startup', ('logs', 7)]
