import pytest
from forecasting import ForecastLedger
from forecasting.domains import market_domain, set_question_domain
from forecasting.learning import active_lessons_for_question
from forecasting.market_nightly import record_pending
from forecasting.models import ValidationError


def test_nightly_domain_routes_lessons_without_enabling_benchmark_calibration(tmp_path):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    lesson = ledger.create_calibration_lesson(scope_type='domain', scope_ref='politics',
        lesson='Check the electoral reference class.', status='active')
    record_pending(ledger, [{'id': 'election', 'question': 'Will the election proposal pass?',
        'category': 'Elections', 'close_time': '2099-10-01T00:00:00Z', 'probability': .5}],
        '2026-09-11T00:00:00Z', lambda _: .6)
    q = ledger.list_questions()[0]
    assert q.domain == 'politics'
    assert q.metadata['acquisition_origin'] == 'market_nightly'
    assert lesson['id'] in {x['id'] for x in active_lessons_for_question(ledger, q)}
    snapshot = ledger.get_current_snapshot(q.id)
    assert snapshot.forecast_origin == 'market_nightly' and not snapshot.calibration_eligible
    assert not ledger.list_scheduled_reviews()
    assert market_domain({'question': 'Will the president win?', 'category': 'Other'}) == (None, 'unknown_source_category')


def test_domain_correction_is_explicit_audited_and_preserves_snapshot(tmp_path):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    q = ledger.create_question(title='Will the election proposal pass?',
        resolution_criteria='Yes if the official election board certifies passage.', domain='market_nightly')
    before = ledger.create_snapshot(question_id=q.id, probability_or_distribution=.6, rationale='Initial assessment.')
    changed = set_question_domain(ledger, q.id, domain='politics', expected_domain='market_nightly', reason='Verified election contract.')
    assert changed.metadata['domain_history'][0]['from'] == 'market_nightly'
    assert changed.metadata['acquisition_origin'] == 'market_nightly'
    assert ledger.get_snapshot(before.forecast_id) == before
    with pytest.raises(ValidationError, match='changed since review'):
        set_question_domain(ledger, q.id, domain='weather', expected_domain='market_nightly', reason='Stale review')
    with pytest.raises(ValidationError, match='acquisition'):
        set_question_domain(ledger, q.id, domain='market_nightly', expected_domain='politics', reason='Wrong axis')
