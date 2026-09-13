"""Delegation defaults and reads belong to runtime, independent of presentation."""
import builtins

import pytest

from superforecasting_agent.runtime import config
from superforecasting_agent.runtime.interactive_config import read_cli_config
from superforecasting_agent.runtime.interactive_defaults import default_cli_config
from tools import delegate_tool


def test_delegation_defaults_have_one_owner_and_are_detached():
    first = default_cli_config()
    second = default_cli_config()
    assert first['delegation'] == config.DEFAULT_CONFIG['delegation']
    first['delegation']['max_iterations'] = 999
    assert second['delegation'] == config.DEFAULT_CONFIG['delegation']


def test_cli_preserves_explicit_delegation_override(tmp_path, monkeypatch):
    for key in ('SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG', 'FORECAST_IGNORE_USER_CONFIG', 'HERMES_IGNORE_USER_CONFIG'):
        monkeypatch.delenv(key, raising=False)
    (tmp_path / 'config.yaml').write_text('delegation:\n  max_iterations: 45\n  model: configured-child\n', encoding='utf-8')
    loaded = read_cli_config(tmp_path, tmp_path / 'missing.yaml')
    assert loaded['delegation']['max_iterations'] == 45
    assert loaded['delegation']['model'] == 'configured-child'


def test_delegation_reads_current_runtime_without_importing_cli(monkeypatch):
    cached = {'delegation': {'model': 'first', 'args': ['original']}}
    monkeypatch.setattr(config, 'load_config_readonly', lambda: cached)
    original_import = builtins.__import__
    attempted = []

    def guarded_import(name, *args, **kwargs):
        if name == 'cli':
            attempted.append(name)
            raise AssertionError('delegation imported presentation')
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', guarded_import)
    loaded = delegate_tool._load_config()
    assert loaded == cached['delegation']
    loaded['args'].append('mutation')
    assert cached['delegation']['args'] == ['original']
    cached['delegation']['model'] = 'updated'
    assert delegate_tool._load_config()['model'] == 'updated'
    assert attempted == []


@pytest.mark.parametrize('value', [None, False, 'invalid', []])
def test_malformed_delegation_section_is_not_returned(value, monkeypatch):
    monkeypatch.setattr(config, 'load_config_readonly', lambda: {'delegation': value})
    assert delegate_tool._load_config() == {}
