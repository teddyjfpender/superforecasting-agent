import pytest
from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.censoring import threshold_probability
from forecasting.censoring_policy import policy_preview, convert_policy


def test_explicit_tail_is_not_silently_replaced_by_gaussian():
    payload = {'mean': 78, 'sd': 43, 'p_gt_45_days': .72, 'q50': 66}
    contract = {'threshold': 45, 'inclusive': False, 'probability_key': 'p_gt_45_days'}
    assert threshold_probability(payload, contract) == .72
    assert threshold_probability({'mean': 78, 'sd': 43}, {'threshold': 45, 'inclusive': False}) != .72
    with pytest.raises(ValidationError, match='fallback is forbidden'):
        threshold_probability({'mean': 78, 'sd': 43}, contract)
    with pytest.raises(ValidationError):
        threshold_probability(payload, {'threshold': 45, 'inclusive': False})


@pytest.mark.parametrize('key', ['p_gte_45_days', 'p_gt_46_days', 'p_yes', None])
def test_explicit_tail_key_must_match_event(key):
    with pytest.raises(ValidationError, match='exact threshold'):
        threshold_probability({'p_gt_45_days': .72}, {'threshold': 45, 'inclusive': False, 'probability_key': key})


def test_conversion_is_reviewed_atomic_and_preserves_forecasts(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Launch delay?', resolution_criteria='No launch by cutoff is right-censored at >45 days.',
        outcome_space=OutcomeSpace(type='distribution', choices=[], units='days'))
    snap = ledger.create_snapshot(question_id=q.id, probability_or_distribution={'mean':78, 'sd':43, 'p_gt_45_days': .72}, rationale='Launch slips')
    spec = dict(contract={'threshold':45,'inclusive':False,'probability_key':'p_gt_45_days'},
                criteria_quote='right-censored at >45 days', reason='Exact historical event probability takes precedence over an inferred Gaussian.')
    review = policy_preview(ledger, q.id, **spec)
    with pytest.raises(ValidationError, match='changed since'):
        convert_policy(ledger, q.id, expected_sha256='stale', **spec)
    assert ledger.get_question(q.id).outcome_space.censoring is None
    convert_policy(ledger, q.id, expected_sha256=review['original_sha256'], **spec)
    assert ledger.get_snapshot(snap.forecast_id) == snap
    assert ledger.get_question(q.id).metadata['censoring_policy_reviews'][0]['original_sha256'] == review['original_sha256']
    ledger.resolve_question(question_id=q.id, outcome={'kind':'right_censored', 'lower_bound':45, 'inclusive':False,
        'observed_through':'2026-07-15T00:00:00Z', 'units':'days'})
    score = ledger.score_question(q.id)
    assert score.proper_score == pytest.approx(.0784)
    assert not score.calibration_eligible
    with pytest.raises(ValidationError, match='already has'):
        convert_policy(ledger, q.id, expected_sha256=review['original_sha256'], **spec)
