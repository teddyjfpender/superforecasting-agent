"""Reading interactive settings must not configure the host process."""
import builtins
import os

import pytest

from superforecasting_agent.runtime.interactive_config import load_cli_config, read_cli_config


@pytest.mark.parametrize("gateway", [False, True])
def test_read_shares_defaults_but_only_load_bridges_environment(tmp_path, monkeypatch, gateway):
    monkeypatch.setenv("_HERMES_GATEWAY", "1" if gateway else "0")
    path = tmp_path / 'config.yaml'
    path.write_text('terminal:\n  backend: ssh\n  cwd: /remote/desk\nagent:\n  personalities:\n    analyst: careful\n', encoding='utf-8')
    monkeypatch.setenv('TERMINAL_CWD', '/host/desk')
    before = dict(os.environ)
    read = read_cli_config(tmp_path, tmp_path / 'missing.yaml')
    assert dict(os.environ) == before
    loaded = load_cli_config(tmp_path, tmp_path / 'missing.yaml', False, lambda _: None)
    assert loaded['agent'] == read['agent']
    assert os.environ['TERMINAL_CWD'] == ('/host/desk' if gateway else '/remote/desk')
    assert loaded['agent']['personalities']['analyst'] == 'careful'


def test_gateway_personalities_do_not_import_cli_or_mutate_environment(tmp_path, monkeypatch):
    from tui_gateway import server

    monkeypatch.setattr(server, '_hermes_home', tmp_path)
    (tmp_path / 'config.yaml').write_text('agent:\n  personalities:\n    analyst: careful\n', encoding='utf-8')
    for key in ('SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG', 'FORECAST_IGNORE_USER_CONFIG', 'HERMES_IGNORE_USER_CONFIG'):
        monkeypatch.delenv(key, raising=False)
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == 'cli':
            raise AssertionError('personality lookup imported presentation')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    before = dict(os.environ)
    assert server._available_personalities()['analyst'] == 'careful'
    assert dict(os.environ) == before
