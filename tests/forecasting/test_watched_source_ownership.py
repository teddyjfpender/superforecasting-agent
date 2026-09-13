"""Watched acquisition isolates source failures and never owns ledger writes."""
import subprocess
import sys
from types import SimpleNamespace

from forecasting.sources import watched


def test_malformed_adapter_options_do_not_discard_other_sources(monkeypatch):
    seen = []
    def load(adapter, source, args):
        seen.append(source)
        return [SimpleNamespace(probability=0.6)]
    monkeypatch.setattr(watched, 'load_source_items', load)
    specs = [
        {'source_type': 'manifold', 'source': 'first'},
        {'source_type': 'manifold', 'source': 'malformed', 'args': 'not a mapping'},
        {'source_type': 'manifold', 'source': 'last'},
    ]
    results = watched.fetch_watched_source_payloads(specs)
    assert [row['source'] for row in results] == ['first', 'malformed', 'last']
    assert [row['success'] for row in results] == [True, False, True]
    assert results[1]['error']
    assert results[1]['payloads'] == []
    assert set(seen) == {'first', 'last'}
    assert specs[1]['args'] == 'not a mapping'


def test_acquisition_imports_without_execution_or_ledger():
    result = subprocess.run([sys.executable, '-c', '''
import importlib.abc
import sys
class BlockConsumers(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent', 'tools', 'cli', 'gateway', 'tui_gateway'} or fullname == 'forecasting.ledger':
            raise AssertionError('acquisition imported consumer: ' + fullname)
sys.meta_path.insert(0, BlockConsumers())
from forecasting.sources.watched import fetch_watched_source_payloads
assert fetch_watched_source_payloads([]) == []
'''], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
