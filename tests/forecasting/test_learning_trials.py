"""Prospective trial invariants: isolation, frozen policy, missingness and scoring."""
import json
import pytest
from forecasting import ForecastLedger
from forecasting.learning_trials import create_trial, run_trial, trial_report, recover_trial, trial_records
from forecasting.models import ValidationError


@pytest.fixture
def trial_setup(tmp_path, monkeypatch):
    now = ['2026-09-01T00:00:00Z']
    monkeypatch.setattr('forecasting.learning_trials.utc_now_iso', lambda: now[0])
    monkeypatch.setattr('forecasting.ledger.evidence.utc_now_iso', lambda: now[0])
    monkeypatch.setattr('forecasting.ledger.resolutions.utc_now_iso', lambda: now[0])
    ledger = ForecastLedger(tmp_path/'ledger.db')
    questions = [ledger.create_question(title=f'Will shipment number {i} arrive by October?',
        resolution_criteria='YES if the official delivery report confirms arrival by October 1.',
        close_time='2026-10-01T00:00:00Z', domain='logistics') for i in range(2)]
    for q in questions:
        ledger.add_evidence(question_id=q.id, source_or_note='Dispatch confirmed in the shipping report.', published_at=now[0])
    lesson = ledger.create_calibration_lesson(scope_type='domain', scope_ref='logistics', lesson='UNIQUE_LEARNING_GUIDANCE',
        status='active', recommended_adjustment={'probability_delta': .05})
    trial = create_trial(ledger, assignments={q.id:'event-'+str(i) for i,q in enumerate(questions)},
        model='fixture', provider='fixture', min_clusters=2)
    return ledger, questions, lesson, trial['trial_id'], now


def fixture_runner(messages, settings):
    context = json.loads(messages[1]['content'])
    assert settings['tool_budget'] == 0
    assert context['case']['evidence']
    return {'content': {'forecast': .7 if 'learning_guidance' in context else .4, 'rationale': 'Use the dispatch evidence.'}, 'model': 'fixture', 'endpoint': 'fixture'}


def test_trial_is_frozen_paired_and_never_writes_live_forecasts(trial_setup):
    ledger, questions, lesson, tid, now = trial_setup
    ledger.update_calibration_lesson(lesson['id'], recommended_adjustment={'probability_delta': -.2})
    run_trial(ledger, tid, runner=fixture_runner)
    _, cases, arms = trial_records(ledger, tid)
    assert all(ledger.get_current_snapshot(q.id) is None for q in questions)
    for case in cases:
        pair = {a['arm']: a for a in arms if a['question_id']==case['question_id']}
        control = json.loads(pair['control']['request'])[1]['content']
        treatment = json.loads(pair['learning']['request'])[1]['content']
        assert 'UNIQUE_LEARNING_GUIDANCE' not in control and 'EDITED_LATER' not in control
        assert 'UNIQUE_LEARNING_GUIDANCE' in treatment and 'EDITED_LATER' not in treatment
        assert json.loads(control)['case'] == json.loads(treatment)['case']
        assert json.loads(pair['learning']['output'])['forecast'] == pytest.approx(.75)
    now[0]='2026-10-02T00:00:00Z'
    for q in questions:
        ledger.resolve_question(question_id=q.id,outcome='yes')
    report=trial_report(ledger,tid)
    assert len(report['comparisons'])==2
    assert report['estimates'][0]['mean_gain']==pytest.approx(.36-.0625)
    assert report['estimates'][0]['status']=='benefit_supported_in_this_trial'
    assert not ledger.list_scores()  # trial evidence cannot inflate live calibration


def test_failed_arm_cannot_be_rerolled_or_dropped_from_denominator(trial_setup):
    ledger, questions, _, tid, now=trial_setup
    count=[]
    def fail(messages,config):
        count.append(1)
        raise TimeoutError('interrupted provider')
    run_trial(ledger,tid,runner=fail,limit=1)
    run_trial(ledger,tid,runner=fixture_runner)
    report=run_trial(ledger,tid,runner=fail)
    assert len(count)==1
    assert report['arm_status_counts']=={'failed':1,'completed':3}
    now[0]='2026-10-02T00:00:00Z'
    for q in questions: ledger.resolve_question(question_id=q.id,outcome='yes')
    report=trial_report(ledger,tid)
    assert report['assigned_questions']==2 and report['exclusions']['incomplete_pair']==1
    assert report['estimates'][0]['status']=='benefit_not_established'


def test_expired_worker_is_visible_without_repeating_model_call(trial_setup):
    ledger, _, _, tid, now=trial_setup
    with ledger._connect() as conn:
        conn.execute("UPDATE learning_trial_arms SET status='running',lease_until='2026-09-01T00:00:00Z' WHERE trial_id=?",(tid,))
    now[0]='2026-09-01T01:00:00Z'
    assert recover_trial(ledger,tid)['arm_status_counts']=={'interrupted':4}


def test_closed_questions_cannot_be_enrolled(trial_setup):
    ledger, questions, _, _, now=trial_setup
    now[0]='2026-10-02T00:00:00Z'
    with pytest.raises(ValidationError,match='future close'):
        create_trial(ledger,assignments={questions[0].id:'event'},model='fixture',provider='fixture')


def test_model_mismatch_is_not_an_accuracy_result(trial_setup):
    ledger, questions, _, tid, now=trial_setup
    def mismatch(messages, settings):
        r=fixture_runner(messages,settings)
        r['model']='other' if 'learning_guidance' in messages[1]['content'] else 'fixture'
        return r
    run_trial(ledger,tid,runner=mismatch)
    now[0]='2026-10-02T00:00:00Z'
    for q in questions: ledger.resolve_question(question_id=q.id,outcome='yes')
    assert trial_report(ledger,tid)['exclusions']['provider_model_mismatch']==2


def test_completed_trial_does_not_initialize_provider_again(trial_setup, monkeypatch):
    ledger, _, _, tid, _ = trial_setup
    run_trial(ledger, tid, runner=fixture_runner)
    def unexpected(config):
        raise AssertionError('completed trial must not initialize provider')
    monkeypatch.setattr('forecasting.learning_trials.provider_runner', unexpected)
    assert run_trial(ledger, tid)['arm_status_counts'] == {'completed': 4}


def test_bad_provider_receipt_is_durable_failure(trial_setup):
    ledger, _, _, tid, _ = trial_setup
    result = run_trial(ledger, tid, runner=lambda *_: {'content': object()}, limit=1)
    assert result['arm_status_counts']['failed'] == 1
    assert 'running' not in result['arm_status_counts']


def test_corrupted_packet_report_excludes_instead_of_claiming_gain(trial_setup):
    ledger, _, _, tid, _ = trial_setup
    with ledger._connect() as conn:
        conn.execute("UPDATE learning_trial_cases SET packet_hash='tampered' WHERE trial_id=?", (tid,))
    assert trial_report(ledger, tid)['exclusions'] == {'packet_integrity_mismatch': 2}


def test_probability_adjustments_never_convert_physical_units(tmp_path):
    from forecasting.learning import apply_active_lesson_adjustments
    from forecasting.models import OutcomeSpace
    ledger = ForecastLedger(tmp_path/'units.db')
    question = ledger.create_question(title='Daily maximum temperature', resolution_criteria='Official station maximum in Celsius.',
        outcome_space=OutcomeSpace(type='numeric', units='Celsius'))
    lesson = ledger.create_calibration_lesson(scope_type='global', scope_ref=None, lesson='Probability correction', status='active',
        recommended_adjustment={'probability_delta': .05, 'logit_shift': .1})
    value, refs, adjustment = apply_active_lesson_adjustments(ledger=ledger, question=question, payload=34.5,
        calibration_lesson_refs=[], calibration_adjustment={})
    assert value == 34.5 and refs == [lesson['id']]
    assert 'applied_probability_delta' not in adjustment
    assert adjustment['applied_active_lessons'][0]['numeric_adjustment_skipped'] == 'binary_probability_adjustment_not_applicable'


def test_duplicate_model_fields_are_rejected(trial_setup):
    ledger, _, _, tid, _ = trial_setup
    report = run_trial(ledger, tid, runner=lambda *_: {'model': 'fixture', 'endpoint': 'fixture',
        'content': '{"forecast":0.2,"forecast":0.8,"rationale":"Ambiguous"}'}, limit=1)
    assert report['arm_status_counts']['failed'] == 1
    assert any('duplicate JSON key' in (a['error'] or '') for a in report['arms'])


def test_concurrent_workers_never_repeat_a_claimed_arm(trial_setup):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    ledger, _, _, tid, _ = trial_setup
    calls = []
    lock = threading.Lock()
    def runner(messages, settings):
        with lock:
            calls.append(messages)
        time.sleep(.02)
        return fixture_runner(messages, settings)
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = [pool.submit(run_trial, ledger, tid, runner=runner) for _ in range(2)]
        for run in runs:
            run.result()
    assert len(calls) == 4
    assert trial_report(ledger, tid)['arm_status_counts'] == {'completed': 4}


def test_single_json_fence_is_unwrapped_without_another_call(trial_setup):
    ledger, _, _, tid, _ = trial_setup
    calls = []
    def runner(*_):
        calls.append(1)
        return {'model': 'fixture', 'endpoint': 'fixture', 'content': '```json\n{"forecast":0.6,"rationale":"Recorded evidence"}\n```'}
    report = run_trial(ledger, tid, runner=runner, limit=1)
    assert len(calls) == 1 and report['arm_status_counts']['completed'] == 1
    _, _, arms = trial_records(ledger, tid)
    receipt = next(a['response'] for a in arms if a['response'])
    assert json.loads(receipt)['content'].startswith('```json')


def test_real_score_provenance_and_quarantine_are_enforced(trial_setup, monkeypatch):
    ledger, questions, _, _, now = trial_setup
    monkeypatch.setattr('forecasting.ledger.scoring.utc_now_iso', lambda: now[0])
    source = ledger.create_question(title='Did the prior shipment arrive?', resolution_criteria='YES if the official delivery report confirms arrival.')
    ledger.create_snapshot(question_id=source.id, probability_or_distribution=.8, rationale='Prior dispatch evidence')
    ledger.resolve_question(question_id=source.id, outcome='yes')
    score = ledger.score_question(source.id)
    assert score.audit_quarantine_reason is None
    ledger.create_calibration_lesson(scope_type='domain', scope_ref='logistics', lesson='Lesson with actual score lineage.',
        status='active', source_score_record_refs=[score.id])
    config = {'assignments': {q.id:'event-'+str(i) for i,q in enumerate(questions)}, 'model':'fixture', 'provider':'fixture'}
    tid = create_trial(ledger, **config)['trial_id']
    run_trial(ledger, tid, runner=fixture_runner)
    with ledger._connect() as conn:
        conn.execute("UPDATE score_records SET audit_quarantine_reason='fixture artifact',calibration_eligible=0 WHERE id=?", (score.id,))
    assert ledger.get_score(score.id).audit_quarantine_reason == 'fixture artifact'
    packet = json.loads(ledger.export_question(source.id, fmt='json'))
    assert packet['scores'][0]['audit_quarantine_reason'] == 'fixture artifact'
    with pytest.raises(ValidationError, match='invalid or overlapping'):
        create_trial(ledger, **config)
    now[0] = '2026-10-02T00:00:00Z'
    for q in questions:
        ledger.resolve_question(question_id=q.id, outcome='yes')
    assert trial_report(ledger, tid)['exclusions']['lesson_source_invalidated'] == 2


def test_cli_report_shows_both_raw_forecasts_and_frozen_lesson_refs(trial_setup, monkeypatch, capsys):
    from argparse import Namespace
    from forecasting.cli.learning_operations import handle_trial
    ledger, _, lesson, tid, _ = trial_setup
    monkeypatch.setattr('forecasting.cli.core._ledger', lambda args: ledger)
    handle_trial(Namespace(trial_action='report', id=tid))
    pending = json.loads(capsys.readouterr().out)
    assert all('forecast' not in arm for arm in pending['arms'])
    run_trial(ledger, tid, runner=fixture_runner)
    handle_trial(Namespace(trial_action='report', id=tid))
    report = json.loads(capsys.readouterr().out)
    assert all(arm['question_title'] and arm['rationale'] for arm in report['arms'])
    for arm in report['arms']:
        if arm['arm'] == 'learning':
            assert arm['raw_forecast'] == .7 and arm['forecast'] == pytest.approx(.75)
            assert arm['frozen_lesson_refs'] == [lesson['id']]
        else:
            assert arm['forecast'] == .4 and arm['frozen_lesson_refs'] == []


def test_transport_failure_stops_before_consuming_remaining_arms(trial_setup):
    ledger, _, _, tid, _ = trial_setup
    calls = []
    def unavailable(*_):
        calls.append(1)
        raise RuntimeError('HTTP 429: input token quota exhausted')
    result = run_trial(ledger, tid, runner=unavailable)
    assert result['arm_status_counts'] == {'failed': 1, 'pending': 3}
    assert len(calls) == 1
    resumed = run_trial(ledger, tid, runner=fixture_runner)
    assert resumed['arm_status_counts'] == {'failed': 1, 'completed': 3}


def test_execution_change_does_not_strand_completed_evaluation(trial_setup, monkeypatch):
    ledger, questions, _, tid, now = trial_setup
    run_trial(ledger, tid, runner=fixture_runner)
    monkeypatch.setattr('forecasting.learning_trials.kernel_identity', lambda: 'new-transport')
    with pytest.raises(ValidationError, match='implementation changed'):
        run_trial(ledger, tid, runner=fixture_runner)
    now[0] = '2026-10-02T00:00:00Z'
    for q in questions:
        ledger.resolve_question(question_id=q.id, outcome='yes')
    assert len(trial_report(ledger, tid)['comparisons']) == 2
    monkeypatch.setattr('forecasting.trial_contracts.evaluation_identity', lambda: 'new-score-policy')
    assert trial_report(ledger, tid)['exclusions'] == {'scoring_version_changed': 2}


def test_stored_output_tampering_cannot_improve_trial_score(trial_setup):
    ledger, questions, _, tid, now = trial_setup
    run_trial(ledger, tid, runner=fixture_runner)
    with ledger._connect() as conn:
        conn.execute("UPDATE learning_trial_arms SET output=json_set(output,'$.forecast',1.0) WHERE trial_id=? AND arm='learning'", (tid,))
    now[0] = '2026-10-02T00:00:00Z'
    for q in questions:
        ledger.resolve_question(question_id=q.id, outcome='yes')
    assert trial_report(ledger, tid)['exclusions'] == {'unscoreable_pair': 2}


def test_candidate_readiness_does_not_treat_unbacked_guidance_as_learning_evidence(trial_setup):
    from forecasting.trial_readiness import candidate_report
    ledger, questions, _, _, _ = trial_setup
    report = candidate_report(ledger)
    selected = [c for c in report['candidates'] if c['question_id'] in {q.id for q in questions}]
    assert len(selected) == 2
    assert all(c['readiness_gaps'] == ['no_outcome_backed_lesson'] for c in selected)
    assert all(c['evidence_count'] and c['lesson_refs'] for c in selected)


def test_live_pacing_leaves_unattempted_arms_pending(trial_setup, monkeypatch):
    ledger, _, _, tid, _ = trial_setup
    monkeypatch.setattr('forecasting.learning_trials.require_preflight', lambda *_: {'model': 'fixture', 'endpoint': 'fixture'})
    monkeypatch.setattr('forecasting.learning_trials.provider_runner', lambda *_: fixture_runner)
    result = run_trial(ledger, tid)
    assert result['arm_status_counts'] == {'completed': 1, 'pending': 3}
    assert result['execution_pause']['reason'] == 'provider_quota_pacing'
    assert run_trial(ledger, tid)['arm_status_counts'] == result['arm_status_counts']


def test_reviewed_legacy_packets_evaluate_without_rewriting_history(trial_setup):
    from pathlib import Path
    from forecasting.learning_trials import arm_messages
    from forecasting import trial_contracts
    ledger, questions, _, tid, now = trial_setup
    run_trial(ledger, tid, runner=fixture_runner)
    trial, cases, arms = trial_records(ledger, tid)
    registry = json.loads(Path(trial_contracts.__file__).with_name('trial_compatibility.json').read_text())
    config = json.loads(trial['config'])
    config.pop('evaluation_identity')
    config['prompt_version'] = 'paired-learning-v2'
    with ledger._connect() as conn:
        conn.execute('UPDATE learning_trials SET config=?,scoring_kernel=? WHERE id=?', (json.dumps(config), next(iter(registry)), tid))
        for case in cases:
            for arm in ('control', 'learning'):
                conn.execute('UPDATE learning_trial_arms SET request=? WHERE trial_id=? AND question_id=? AND arm=?',
                             (json.dumps(arm_messages(case, arm)), tid, case['question_id'], arm))
    before = trial_records(ledger, tid)
    now[0] = '2026-10-02T00:00:00Z'
    for q in questions:
        ledger.resolve_question(question_id=q.id, outcome='yes')
    assert len(trial_report(ledger, tid)['comparisons']) == 2
    assert trial_records(ledger, tid) == before
    with ledger._connect() as conn:
        conn.execute("UPDATE learning_trials SET scoring_kernel='unreviewed' WHERE id=?", (tid,))
    assert trial_report(ledger, tid)['exclusions'] == {'scoring_version_changed': 2}


def test_cluster_whitespace_does_not_inflate_independence(trial_setup):
    ledger, questions, _, _, _ = trial_setup
    report = create_trial(ledger, assignments={questions[0].id: 'shared-event', questions[1].id: ' shared-event '},
                          model='fixture', provider='fixture')
    assert report['assigned_questions'] == 2
    assert report['assigned_clusters'] == 1


def test_new_trial_and_readiness_exclude_invalidated_evidence(trial_setup):
    from forecasting.trial_readiness import candidate_report
    ledger, questions, _, _, _ = trial_setup
    with ledger._connect() as conn:
        conn.execute("UPDATE evidence_items SET metadata=? WHERE question_id=?", ('{"invalidated":true}', questions[0].id))
    candidate = next(c for c in candidate_report(ledger)['candidates'] if c['question_id'] == questions[0].id)
    assert 'missing_pre_cutoff_evidence' in candidate['readiness_gaps']
    with pytest.raises(ValidationError, match='pre-cutoff evidence'):
        create_trial(ledger, assignments={questions[0].id:'new-event'}, model='fixture', provider='fixture')


def test_synthetic_score_cannot_support_new_trial_learning(trial_setup):
    from forecasting.trial_inputs import score_support_problem
    from types import SimpleNamespace
    source = SimpleNamespace(calibration_eligible=False, calibration_weight=1,
        invalidated_by_correction_id=None, audit_quarantine_reason=None,
        question_id='historical', scored_at='2026-08-01T00:00:00Z')
    assert score_support_problem(source, '2026-09-01T00:00:00Z') == 'ineligible_source_score'
    source.calibration_eligible = True
    assert score_support_problem(source, '2026-09-01T00:00:00Z') is None
    assert score_support_problem(source, '2026-09-01T00:00:00Z', ['historical']) == 'overlapping_source_outcome'
