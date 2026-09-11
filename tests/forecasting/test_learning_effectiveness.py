import json
import pytest
from forecasting import ForecastLedger
from forecasting.learning_evaluation import learning_effectiveness
from forecasting.learning import active_lessons_for_question, lesson_application_decisions
from forecasting.models import ValidationError


def test_effectiveness_does_not_cherry_pick_latest_and_preserves_ledger(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='Will shipment occur?', resolution_criteria='Yes if the official report confirms shipment.', close_time='2026-02-01T00:00:00Z')
    monkeypatch.setattr('forecasting.ledger.snapshots.utc_now_iso', lambda:'2026-01-01T00:00:00Z')
    first = ledger.create_snapshot(question_id=q.id,probability_or_distribution=.2,rationale='First call')
    ledger.create_snapshot(question_id=q.id,probability_or_distribution=.9,rationale='Later call')
    monkeypatch.setattr('forecasting.ledger.resolutions.utc_now_iso', lambda:'2026-02-02T00:00:00Z')
    ledger.resolve_question(question_id=q.id,outcome='yes')
    before = len(ledger.list_scores())
    report=learning_effectiveness(ledger)
    assert report['counts']['scored_distinct_questions']==1
    assert report['records'][0]['forecast_id']==first.forecast_id
    assert report['records'][0]['score']==pytest.approx(.64)
    assert len(ledger.list_scores())==before
    assert report['status']=='benefit_not_established'


def test_missing_conditions_never_enforce_or_supersede(tmp_path):
    ledger=ForecastLedger(tmp_path/'db')
    q=ledger.create_question(title='Will it be hot?',resolution_criteria='Yes if official temperature exceeds 30.',domain='weather')
    old=ledger.create_calibration_lesson(scope_type='domain',scope_ref='weather',lesson='Old advisory',status='active')
    new=ledger.create_calibration_lesson(scope_type='domain',scope_ref='weather',lesson='Conditional replacement',status='active',supersedes_lesson_id=old['id'],recommended_adjustment={'applicability':{'metadata_equals':{'weather.phase':'POST_MAXIMUM'}}})
    assert [l['id'] for l in active_lessons_for_question(ledger,q)]==[old['id']]
    assert [l['id'] for l in active_lessons_for_question(ledger,q,context={'weather':{'phase':'POST_MAXIMUM'}})]==[new['id']]
    decisions=lesson_application_decisions(ledger,q,.5,{},[],{})
    decision=next(d for d in decisions if d['lesson_id']==new['id'])
    assert decision['reason']=='condition_unknown:weather.phase'
    assert not decision['applied']
    with pytest.raises(ValidationError):
        ledger.update_calibration_lesson(new['id'],recommended_adjustment={'applicability':{'outcome_types':'binary'}})


def test_weather_tail_prose_does_not_compile_candidate_rule(tmp_path):
    ledger=ForecastLedger(tmp_path/'db')
    lesson=ledger.create_calibration_lesson(scope_type='domain',scope_ref='weather',lesson='Narrow supported temperature tails.',recommended_adjustment={'adjustment':'compress tails'})
    assert 'rule' not in lesson['recommended_adjustment']


def test_resolution_json_vector_is_not_a_string(tmp_path):
    from forecasting.models import OutcomeSpace
    ledger=ForecastLedger(tmp_path/'db')
    q=ledger.create_question(title='What shares will candidates receive?',resolution_criteria='Official certified percentages for each named candidate.',outcome_space=OutcomeSpace(type='distribution',choices=['A','B'],bounds=[0,100],units='percent'))
    resolution=ledger.resolve_question(question_id=q.id,outcome=json.dumps({'A':60,'B':40}),auto_score=False)
    assert resolution.outcome=={'A':60,'B':40}


def test_resolution_time_controls_settlement_queue(tmp_path):
    from forecasting.lifecycle import lifecycle_status
    ledger=ForecastLedger(tmp_path/'db')
    q=ledger.create_question(title='Will the year-long basket outperform?',resolution_criteria='Yes if annual return exceeds benchmark.',close_time='2026-01-01T00:00:00Z',resolution_time='2027-01-01T00:00:00Z')
    assert not lifecycle_status(ledger,now='2026-09-01T00:00:00Z')['attention']
    assert lifecycle_status(ledger,now='2027-01-02T00:00:00Z')['attention'][0]['question_id']==q.id


def test_snapshot_rule_conditions_and_frozen_lesson_version(tmp_path):
    ledger=ForecastLedger(tmp_path/'db')
    q=ledger.create_question(title='Will it be hot?',resolution_criteria='Yes if official temperature exceeds 30.',domain='weather')
    lesson=ledger.create_calibration_lesson(scope_type='domain',scope_ref='weather',lesson='Check an outside-view anchor after peak.',status='active',recommended_adjustment={
        'applicability':{'metadata_equals':{'weather.phase':'POST_MAXIMUM'}},
        'rule':{'category':'reasoning','severity':'error','check':{'signal':'reference_classes.count','op':'>=','value':1},'message':'Need an anchor'}})
    snap=ledger.create_snapshot(question_id=q.id,probability_or_distribution=.7,rationale='Phase unknown')
    assert snap.metadata['lesson_decisions'][0]['reason']=='condition_unknown:weather.phase'
    with pytest.raises(ValidationError,match='anchor'):
        ledger.create_snapshot(question_id=q.id,probability_or_distribution=.7,rationale='Peak passed',metadata={'weather':{'phase':'POST_MAXIMUM'}})
    ledger.update_calibration_lesson(lesson['id'],recommended_adjustment={})
    saved=ledger.get_snapshot(snap.forecast_id).metadata['lesson_decisions'][0]
    assert saved['recommended_adjustment']['rule']['severity']=='error'
    assert saved['lesson_text']=='Check an outside-view anchor after peak.'


@pytest.mark.parametrize('outcome', ['garbage', 'NaN', 'Infinity', True, [], {'value': 4}])
def test_bad_numeric_resolution_does_not_close_question(tmp_path, outcome):
    from forecasting.models import OutcomeSpace
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='What numeric value will be published?', resolution_criteria='Resolved to the numeric value published in the official report at the resolution time.', outcome_space=OutcomeSpace(type='numeric', units='count'))
    with pytest.raises(ValidationError):
        ledger.resolve_question(question_id=q.id, outcome=outcome)
    assert ledger.get_question(q.id).status == 'active'
    assert ledger.get_latest_resolution(q.id) is None
    with ledger._connect() as conn:
        assert conn.execute('SELECT count(*) FROM operational_tasks').fetchone()[0] == 0


@pytest.mark.parametrize('outcome', [
    '{"A":60,"A":40,"B":40}', '{bad json',
    {'A': True, 'B': 40}, {'A': '60', 'B': 40}, {'A': float('nan'), 'B': 40},
    {'A': 60}, {'A': 60, 'B': 40, ' C ': 0}, {'A': 60, ' a ': 0, 'B': 40},
    {'A': -1, 'B': 101}, {'A': .6, 'B': .4},
])
def test_bad_vectors_are_rejected_before_any_resolution_write(tmp_path, outcome):
    from forecasting.models import OutcomeSpace
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='What shares will candidates receive?', resolution_criteria='Resolved to the numeric value published in the official report at the resolution time.', outcome_space=OutcomeSpace(type='distribution', choices=['A', 'B'], units='percent'))
    ledger.create_snapshot(question_id=q.id, probability_or_distribution={'A': .6, 'B': .4}, rationale='Candidate shares', forecast_origin='exploratory')
    with pytest.raises(ValidationError):
        ledger.resolve_question(question_id=q.id, outcome=outcome)
    assert ledger.get_question(q.id).status == 'active'
    assert ledger.get_latest_resolution(q.id) is None
    assert not ledger.list_scores()


def test_numeric_transport_string_is_stored_as_number(tmp_path):
    from forecasting.models import OutcomeSpace
    ledger = ForecastLedger(tmp_path/'db')
    q = ledger.create_question(title='What value will be published?', resolution_criteria='Resolved to the numeric value published in the official report at the resolution time.', outcome_space=OutcomeSpace(type='numeric', units='count'))
    result = ledger.resolve_question(question_id=q.id, outcome='4.25', auto_score=False)
    assert result.outcome == 4.25
    assert isinstance(result.outcome, float)
