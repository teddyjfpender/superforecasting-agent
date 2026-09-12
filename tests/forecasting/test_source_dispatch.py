"""Structured acquisition is usable without agent execution or a forecast ledger."""
import subprocess
import sys

from forecasting import appconfig
from forecasting.sources import dispatch
from superforecasting_agent.storage import forecast_configuration


def test_source_dispatch_imports_without_execution_layers():
    result = subprocess.run(
        [sys.executable, "-c", '''
import importlib.abc
import sys
class BlockExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'tools', 'agent', 'cli', 'gateway', 'tui_gateway'}:
            raise AssertionError('source acquisition imported execution layer: ' + fullname)
sys.meta_path.insert(0, BlockExecution())
from forecasting.sources.dispatch import load_source_items
try:
    load_source_items('unsupported', 'example', {})
except ValueError:
    pass
else:
    raise AssertionError('unsupported adapter was accepted')
'''],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_config_compatibility_shares_reader_and_overrides():
    previous = forecast_configuration.get_config()
    try:
        appconfig.configure(environ={}, config_file={})
        assert appconfig.get_config() is forecast_configuration.get_config()
        appconfig.set_override('FRED_API_KEY', 'test-key')
        assert forecast_configuration.secret('FRED_API_KEY') == 'test-key'
        forecast_configuration.set_override('FRED_API_KEY', 'replacement-key')
        assert appconfig.secret('FRED_API_KEY') == 'replacement-key'
    finally:
        forecast_configuration._config = previous


def test_dispatch_preserves_source_identity_and_options(monkeypatch):
    args = {'limit': 7, 'since': '2026-01-01', 'api_base_url': 'https://example.invalid'}
    original = dict(args)
    records = [object()]
    calls = []

    def fetch(source, **options):
        calls.append((source, options))
        return records

    monkeypatch.setattr(dispatch, 'load_fred_observations', fetch)
    assert dispatch.load_source_items('adapter:fred', 'UNRATE', args) is records
    assert calls == [('UNRATE', original)]
    assert args == original
