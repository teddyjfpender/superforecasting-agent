import json
import pytest
from forecasting import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.censoring import score, threshold_probability


def space():
    return OutcomeSpace(type='numeric', choices=[], units='days', censoring={'threshold': 6, 'inclusive': True})


def test_complete_censored_lifecycle_and_packet_round_trip(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='How many days until the shipment arrives?',
        resolution_criteria='Observe delivery delay; after six days report the delay as at least six days.', outcome_space=space())
    snapshot = ledger.create_snapshot(question_id=q.id, probability_or_distribution={'mean': 6, 'sd': 2}, rationale='Gaussian predictive delay.')
    observed = {'kind': 'right_censored', 'lower_bound': 6, 'inclusive': True,
        'observed_through': '2026-09-01T00:00:00Z', 'units': 'days'}
    resolution = ledger.resolve_question(question_id=q.id, outcome=observed, resolution_source='https://example.org/delivery-status')
    scored = ledger.score_snapshot(snapshot.forecast_id)
    assert scored.proper_score == pytest.approx(.25) and scored.brier_score is None
    assert not scored.calibration_eligible
    assert resolution.outcome['lower_bound'] == 6
    ledger.create_postmortem(question_id=q.id)
    packet = json.loads(ledger.export_question(q.id, fmt='json'))
    restored = ForecastLedger(tmp_path/'restored.db'); restored.import_packet(packet)
    assert restored.get_latest_resolution(q.id).outcome == observed
    assert restored.get_question(q.id).outcome_space.censoring == space().censoring
    assert packet['scores'][0]['score_rule'] == 'right_censored_threshold_brier_v1'


def test_exact_and_censored_observations_use_same_proper_event_score():
    payload = {'p0': .1, 'p4': .6, 'p6_plus': .3}
    assert threshold_probability(payload, space().censoring) == .3
    assert score(payload, 4, space())['proper_score'] == pytest.approx(.09)
    assert score(payload, 8, space())['proper_score'] == pytest.approx(.49)
    # Expected Brier risk uniquely minimizes at the actual event probability.
    truth = .3
    losses = {p: truth*(p-1)**2+(1-truth)*p*p for p in (.1, .3, .6)}
    assert losses[.3] < losses[.1] and losses[.3] < losses[.6]
    with pytest.raises(ValidationError, match='splits'):
        threshold_probability(payload, {'threshold': 7, 'inclusive': True})


def test_censoring_rejects_fake_point_tail_and_unit_mismatch_before_resolution(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='How many days until delivery?', resolution_criteria='Resolve to elapsed days according to the official delivery record.', outcome_space=space())
    with pytest.raises(ValidationError, match='predictive distribution'):
        ledger.create_snapshot(question_id=q.id, probability_or_distribution=6, rationale='A mean is not a tail probability.')
    with pytest.raises(ValidationError, match='matching units'):
        ledger.resolve_question(question_id=q.id, outcome={'kind': 'right_censored', 'lower_bound': 6,
            'inclusive': True, 'observed_through': '2026-09-01T00:00:00Z', 'units': 'hours'})
    assert ledger.get_latest_resolution(q.id) is None
    assert ledger.get_question(q.id).status == 'active'


def test_agent_tool_declares_censoring_without_fake_categorical_choices(tmp_path):
    from tools.forecast_actions.questions import create_question
    ledger = ForecastLedger(tmp_path/'tool.db')
    create_question({'title': 'How many days until delivery?',
        'resolution_criteria': 'Resolve elapsed days according to the official delivery record.',
        'outcome_type': 'numeric', 'units': 'days', 'censoring': {'threshold': 6, 'inclusive': True}}, ledger)
    assert ledger.list_questions()[0].outcome_space == space()


@pytest.mark.parametrize('tail', [None, True, '0.8', -0.1, 1.1, float('nan')])
def test_explicit_tail_never_falls_back_to_valid_gaussian(tail):
    contract = {'threshold': 6, 'inclusive': True, 'probability_key': 'p_gte_6_days'}
    payload = {'mean': 6, 'sd': 2}
    if tail is not None:
        payload['p_gte_6_days'] = tail
    with pytest.raises(ValidationError, match='fallback is forbidden'):
        threshold_probability(payload, contract)
    payload['p_gte_6_days'] = .8
    assert threshold_probability(payload, contract) == .8


@pytest.mark.parametrize('outcome', [True, {}, float('inf'), 'unmeasured'])
def test_unscoreable_cannot_bypass_confirmed_numeric_validation(tmp_path, outcome):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Measured delivery time?', resolution_criteria='Resolve to the official measured delivery time.',
        outcome_space=OutcomeSpace(type='numeric', choices=[], units='days'))
    with pytest.raises(ValidationError):
        ledger.resolve_question(question_id=q.id, outcome=outcome, scoreable=False)
    assert ledger.get_latest_resolution(q.id) is None
    assert ledger.get_question(q.id).status == 'active'


def test_packet_import_cannot_forge_censored_score_or_drop_tail(tmp_path):
    from copy import deepcopy
    ledger = ForecastLedger(tmp_path/'source.db')
    declared = space()
    declared.censoring['probability_key'] = 'p_gte_6_days'
    q = ledger.create_question(title='How many days until delivery?', resolution_criteria='Resolve elapsed days according to the official delivery record.', outcome_space=declared)
    ledger.create_snapshot(question_id=q.id, probability_or_distribution={'mean': 6, 'sd': 2, 'p_gte_6_days': .8}, rationale='Explicit elicited tail.')
    ledger.resolve_question(question_id=q.id, outcome=8)
    packet = json.loads(ledger.export_question(q.id, fmt='json'))
    for index, kind in enumerate(('score', 'snapshot', 'outcome')):
        bad = deepcopy(packet)
        if kind == 'score':
            bad['scores'][0]['proper_score'] = .25
        elif kind == 'snapshot':
            del bad['forecast_history'][0]['probability_or_distribution']['p_gte_6_days']
        else:
            bad['resolution']['outcome'] = 'unknown'
        target = ForecastLedger(tmp_path/f'target-{index}.db')
        with pytest.raises(ValidationError):
            target.import_packet(bad)
        assert target.list_questions() == []


def test_packet_boolean_strings_cannot_enable_scoring(tmp_path):
    ledger = ForecastLedger(tmp_path/'source.db')
    q = ledger.create_question(title='Will delivery occur?', resolution_criteria='Resolve yes on official confirmation of delivery.')
    ledger.resolve_question(question_id=q.id, outcome='yes')
    packet = json.loads(ledger.export_question(q.id, fmt='json'))
    packet['resolution']['scoreable'] = 'false'
    target = ForecastLedger(tmp_path/'target.db')
    with pytest.raises(ValidationError, match='boolean'):
        target.import_packet(packet)
    assert target.list_questions() == []
