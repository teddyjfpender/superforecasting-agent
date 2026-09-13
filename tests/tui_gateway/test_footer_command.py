"""Shared footer transitions preserve concurrent settings and bypass the worker."""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import yaml

from superforecasting_agent.application.footer import footer_command
from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway import server


def test_concurrent_toggles_are_atomic(tmp_path):
    path = tmp_path / 'config.yaml'
    path.write_text('model: fixture\ndisplay:\n  runtime_footer:\n    enabled: false\n', encoding='utf-8')
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: footer_command('', path), range(10)))
    assert outputs.count('Runtime footer: ON') == 5
    assert outputs.count('Runtime footer: OFF') == 5
    config = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert config['model'] == 'fixture'
    assert config['display']['runtime_footer']['enabled'] is False


def test_status_and_invalid_commands_do_not_write(tmp_path):
    path = tmp_path / 'config.yaml'
    assert 'Runtime footer: OFF' in footer_command('status', path)
    assert not path.exists()
    with pytest.raises(ValueError, match='Usage:'):
        footer_command('on extra', path)
    assert not path.exists()
    path.write_text('display:\n  runtime_footer:\n    enabled: "false"\n', encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='must be a boolean'):
        footer_command('', path)
    assert path.read_bytes() == before


def test_cli_and_native_footer_share_profile_operation(tmp_path, monkeypatch, capsys):
    import cli
    from superforecasting_agent import constants

    monkeypatch.setattr(cli, '_hermes_home', tmp_path)
    monkeypatch.setattr(cli, '_cprint', print)
    monkeypatch.setattr(constants, 'get_agent_home', lambda: tmp_path)
    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions['runtime'] = {'session_key': 'durable', 'history': []}
    monkeypatch.setattr(server, '_start_agent_build', Mock(side_effect=AssertionError('unexpected agent')))
    shell = object.__new__(cli.HermesCLI)
    shell._handle_footer_command('/footer on')
    assert 'Runtime footer: ON' in capsys.readouterr().out
    response = server.handle_request({'id': 1, 'method': 'slash.exec', 'params': {'session_id': 'runtime', 'command': 'footer'}})
    assert response['result']['output'] == 'Runtime footer: OFF'
    shell._handle_footer_command('/footer status')
    assert 'Runtime footer: OFF' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_gateway_toggle_uses_global_flag_not_platform_override(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import gateway.run as runtime
    from gateway.config import Platform

    path = tmp_path / 'config.yaml'
    config = {'display': {'runtime_footer': {'enabled': False}, 'platforms': {'telegram': {'runtime_footer': {'enabled': True}}}}}
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    monkeypatch.setattr(runtime, '_hermes_home', tmp_path)
    monkeypatch.setattr(runtime, '_load_gateway_config', lambda: config)
    monkeypatch.setattr(runtime, '_resolve_gateway_model', lambda cfg: 'fixture')
    runner = object.__new__(runtime.GatewayRunner)
    event = SimpleNamespace(message='/footer', source=SimpleNamespace(platform=Platform.TELEGRAM))
    await runner._handle_footer_command(event)
    saved = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert saved['display']['runtime_footer']['enabled'] is True
    assert saved['display']['platforms'] == config['display']['platforms']
    await runner._handle_footer_command(event)
    assert yaml.safe_load(path.read_text(encoding='utf-8'))['display']['runtime_footer']['enabled'] is False
