"""Summary reads are shared application operations, independent of dashboard."""
import builtins

import pytest

from forecasting.application.aggregate_summaries import build_factor_summary, build_thesis_summary
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError


@pytest.mark.parametrize('operation', [build_factor_summary, build_thesis_summary])
@pytest.mark.parametrize('limit', [-1, True, 1.5, '2'])
def test_invalid_summary_limit_fails_before_storage(operation, limit):
    with pytest.raises(ValidationError, match='summary limit'):
        operation(ledger=object(), limit=limit)


def test_tool_reads_shared_summaries_without_dashboard(tmp_path, monkeypatch):
    import json
    from tools.forecasting_tool import forecast_ledger_tool

    path = tmp_path / 'summary.db'
    ledger = ForecastLedger(db_path=str(path))
    ledger.initialize_schema()
    question = ledger.create_question(
        title='Aggregate fixture?', resolution_criteria='Resolves from the aggregate health of its tagged member forecasts at the close date.',
        outcome_space=OutcomeSpace(type='thesis'),
    )
    original = builtins.__import__
    attempted = []
    def guarded(name, *args, **kwargs):
        if name.startswith('forecasting.dashboard') or name == 'cli':
            attempted.append(name)
            raise AssertionError('summary read imported presentation')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    report = json.loads(forecast_ledger_tool({'action': 'thesis_dashboard', 'db': str(path)}))
    assert report['success'] is True, report
    assert report['theses'] == build_thesis_summary(ledger=ledger)
    assert report['factors'] == []
    assert report['theses'][0]['id'] == question.id
    assert report['theses'][0]['status'] == 'withheld'
    assert attempted == []
