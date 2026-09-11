"""Shared benchmark operations reject unsafe sources before doing any work."""
import builtins

import pytest

from forecasting.application import benchmarks


@pytest.mark.parametrize('source', ['agent-protocol', 'dataset', 'typo', '', None])
def test_safe_suite_rejects_nonoffline_sources_before_reading_or_writing(source, monkeypatch):
    def unexpected():
        pytest.fail('invalid source reached dataset access')
    monkeypatch.setattr(benchmarks, 'list_builtin_benchmarks', unexpected)
    with pytest.raises(ValueError, match='Safe benchmarks require'):
        benchmarks.run_safe_benchmarks(object(), source)


def test_unknown_probability_source_does_not_silently_become_baseline():
    with pytest.raises(ValueError, match='Unknown backtest probability source'):
        benchmarks.apply_probability_source([], 'misspelled-source')


def test_safe_suite_never_imports_presentation(tmp_path, monkeypatch):
    from forecasting.ledger import ForecastLedger
    monkeypatch.setattr(benchmarks, 'list_builtin_benchmarks', lambda: [{'name': 'ownership'}])
    monkeypatch.setattr(benchmarks, 'load_builtin_benchmark', lambda _: [{
        'id': 'ownership-case', 'title': 'Will the fixture resolve yes?',
        'as_of': '2026-01-01T00:00:00Z', 'close_time': '2026-02-01T00:00:00Z',
        'outcome': 'yes',
        'baselines': [{'baseline_type': 'market', 'source': 'fixture', 'probability': 0.6}],
    }])
    original = builtins.__import__
    attempted = []
    def guarded(name, *args, **kwargs):
        if name in ('cli', 'forecasting.cli') or name.startswith('forecasting.cli.'):
            attempted.append(name)
            raise AssertionError('benchmark operation imported presentation')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    ledger = ForecastLedger(db_path=str(tmp_path / 'benchmarks.db'))
    ledger.initialize_schema()
    result = benchmarks.run_safe_benchmarks(ledger, 'baseline-ensemble')
    assert result['runs'] == len(ledger.list_backtest_runs()) > 0
    assert result['scored'] > 0
    assert attempted == []
