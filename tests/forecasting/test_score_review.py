from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace


def test_categorical_uniform_forecast_is_not_a_binary_high_brier_miss(tmp_path):
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='Exact score?', resolution_criteria='Resolves to the official match score at the end of normal time, excluding extra time.',
        domain='sports', outcome_space=OutcomeSpace(type='categorical', choices=['0-0','1-0','0-1','other']))
    ledger.create_snapshot(question_id=q.id, probability_or_distribution={k:.25 for k in q.outcome_space.choices}, rationale='Uniform reference')
    ledger.resolve_question(question_id=q.id, outcome='1-0')
    score = ledger.score_question(q.id)
    assert score.brier_score == .75
    assert ledger._auto_postmortem_error_tags(score) == []
    assert ledger._auto_postmortem_lesson(q, score) == ''
    counts = ledger._error_counts_for_profile(scores=[score], postmortems=[{'score_record_id':score.id,
        'calibration_adjustment':{'error_tags':['high_brier_miss']}}])
    assert counts['high_brier_miss'] == 0
    profile = ledger.update_domain_error_profile(q)
    assert 'elevated_mean_brier' not in profile['recurring_errors']


def test_extreme_wrong_categorical_forecast_still_requests_review(tmp_path):
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='Exact score?', resolution_criteria='Resolves to the official match score at the end of normal time, excluding extra time.',
        outcome_space=OutcomeSpace(type='categorical', choices=['a','b','c','d']))
    ledger.create_snapshot(question_id=q.id, probability_or_distribution={'a':.97,'b':.01,'c':.01,'d':.01}, rationale='Very confident')
    ledger.resolve_question(question_id=q.id, outcome='b')
    score = ledger.score_question(q.id)
    assert 'high_brier_miss' in ledger._auto_postmortem_error_tags(score)
