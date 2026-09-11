"""Real-ledger recovery, with unresolved outcomes and forecast values conserved."""
import pytest
from forecasting import ForecastLedger
from forecasting.lifecycle import lifecycle_status, run_lifecycle


def test_missing_handoff_is_recovered_without_resolving_overdue_question(tmp_path):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    resolved = ledger.create_question(title='Will the verified release ship?', resolution_criteria='Resolves yes if the official release confirms shipment; otherwise no.')
    pending = ledger.create_question(title='Will the pending release ship?', resolution_criteria='Resolves yes if the official release confirms shipment; otherwise no.', close_time='2026-01-01T00:00:00Z')
    snapshot = ledger.create_snapshot(question_id=resolved.id, probability_or_distribution=.7, rationale='Before announcement.')
    ledger.resolve_question(question_id=resolved.id, outcome='yes', auto_score=False)
    with ledger._connect() as conn:
        conn.execute("DELETE FROM operational_tasks WHERE task_type='finalize_resolution'")
    report = lifecycle_status(ledger)
    assert report['counts']['missing_tasks'] == 1
    assert report['attention'][0]['question_id'] == pending.id
    assert run_lifecycle(ledger, owner='test')[0]['status'] == 'completed'
    assert run_lifecycle(ledger, owner='test') == []
    assert lifecycle_status(ledger)['counts']['unfinished'] == 0
    assert ledger.get_current_snapshot(resolved.id).forecast_id == snapshot.forecast_id
    assert ledger.get_question(pending.id).status == 'active'
    assert ledger.get_latest_resolution(pending.id) is None
    assert len(ledger.list_postmortems(question_id=resolved.id)) == 1


def test_failed_scoring_stays_retryable_and_visible(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    question = ledger.create_question(title='Will scoring recover?', resolution_criteria='Resolves yes if the official release confirms shipment; otherwise no.')
    ledger.create_snapshot(question_id=question.id, probability_or_distribution=.7, rationale='Before announcement.')
    ledger.resolve_question(question_id=question.id, outcome='yes', auto_score=False)
    def fail(*a, **k):
        raise RuntimeError('temporary scoring interruption')
    monkeypatch.setattr(ledger, 'score_question', fail)
    results = run_lifecycle(ledger, owner='test')
    assert results[0]['error'] == 'temporary scoring interruption'
    report = lifecycle_status(ledger)
    assert report['counts']['unfinished'] == 1
    assert report['tasks'][0]['attempt_count'] == 1
    assert report['tasks'][0]['error'] == 'temporary scoring interruption'


def test_superseded_resolution_task_cannot_finalize_another_outcome(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolves yes if the official release confirms shipment; otherwise no.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.7, rationale='Before announcement.')
    monkeypatch.setattr('forecasting.ledger.resolutions.utc_now_iso', lambda: '2026-09-10T00:00:00Z')
    old = ledger.resolve_question(question_id=q.id, outcome='yes', auto_score=False)
    latest = ledger.resolve_question(question_id=q.id, outcome='no', auto_score=False)
    assert ledger.get_latest_resolution(q.id, confirmed_only=True).id == latest.id
    result = run_lifecycle(ledger, owner='test')
    assert sorted(r['disposition'] for r in result) == ['resolved_by_resolution', 'superseded_resolution']
    assert ledger.get_current_score(q.id).resolution_id == latest.id
    assert all(s.resolution_id != old.id for s in ledger.list_scores())
    assert len(ledger.list_postmortems(question_id=q.id)) == 1


def test_cli_does_not_silently_ignore_question_scope(monkeypatch):
    from argparse import Namespace
    from forecasting.cli import doctor_admin
    def unexpected_ledger(*args):
        raise AssertionError('must not open or mutate the global ledger')
    monkeypatch.setattr(doctor_admin, '_ledger', unexpected_ledger)
    with pytest.raises(SystemExit, match='full ledger'):
        doctor_admin._cmd_lifecycle(Namespace(action='run', question_id='fq_only_this_one'))


def test_postmortem_lesson_failure_rolls_back_and_retry_preserves_lineage(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.9, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='no', auto_score=False)
    original = ledger.create_calibration_lesson
    def fail(**kwargs):
        original(**kwargs)
        raise RuntimeError('interrupted after lesson write')
    monkeypatch.setattr(ledger, 'create_calibration_lesson', fail)
    with pytest.raises(RuntimeError, match='interrupted'):
        ledger.create_postmortem(question_id=q.id, lesson='Check the release base rate.')
    assert ledger.list_postmortems(question_id=q.id) == []
    assert ledger.list_scores() == []
    assert ledger.list_calibration_lessons() == []
    monkeypatch.setattr(ledger, 'create_calibration_lesson', original)
    postmortem = ledger.create_postmortem(question_id=q.id, lesson='Check the release base rate.')
    assert ledger.create_postmortem(question_id=q.id)['id'] == postmortem['id']
    lessons = ledger.list_calibration_lessons()
    assert len(lessons) == 1
    assert lessons[0]['source_postmortem_refs'] == [postmortem['id']]


def test_concurrent_scores_and_postmortems_are_idempotent(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'ledger.db'
    ledger = ForecastLedger(path)
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.7, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='yes', auto_score=False)
    peers = [ForecastLedger(path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda peer: peer.create_postmortem(question_id=q.id), peers))
    assert len({row['id'] for row in rows}) == 1
    assert len(ledger.list_scores()) == 1


def test_historical_missing_lesson_is_visible_and_recoverable(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.9, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='no', auto_score=False)
    run_lifecycle(ledger, owner='test')
    postmortem = ledger.list_postmortems(question_id=q.id)[0]
    assert postmortem['lesson']
    with ledger._connect() as conn:
        conn.execute('DELETE FROM calibration_lessons')
    assert lifecycle_status(ledger)['unfinished'][0]['reason'] == 'lesson_missing'
    result = run_lifecycle(ledger, owner='repair')
    assert result[0]['disposition'] == 'repaired_lesson_handoff'
    assert lifecycle_status(ledger)['counts']['unfinished'] == 0
    assert ledger.list_postmortems(question_id=q.id)[0]['id'] == postmortem['id']
    assert len(ledger.list_calibration_lessons()) == 1
    assert run_lifecycle(ledger, owner='repair') == []


def test_resolution_retry_reuses_identity_and_handoff(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    first = ledger.resolve_question(question_id=q.id, outcome='yes', auto_score=False)
    retry = ledger.resolve_question(question_id=q.id, outcome='yes', auto_score=False)
    assert retry.id == first.id
    with ledger._connect() as conn:
        assert conn.execute('SELECT count(*) FROM resolutions').fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM operational_tasks WHERE task_type='finalize_resolution'").fetchone()[0] == 1


def test_caught_nested_failure_does_not_commit_partial_postmortem(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.9, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='no', auto_score=False)
    def fail(**kwargs):
        raise RuntimeError('lesson unavailable')
    monkeypatch.setattr(ledger, 'create_calibration_lesson', fail)
    with ledger.transaction(immediate=True):
        with pytest.raises(RuntimeError):
            ledger.create_postmortem(question_id=q.id, lesson='Check the base rate.')
        assert ledger.list_scores() == []
        assert ledger.list_postmortems(question_id=q.id) == []
    assert ledger.get_latest_resolution(q.id) is not None


def test_explicit_rescore_preserves_correction_lineage(tmp_path):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.9, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='no')
    run_lifecycle(ledger, owner='initial')
    prior = ledger.create_postmortem(question_id=q.id, lesson='Check the base rate.')
    replacement = ledger.score_question(q.id, force=True)
    old = ledger.get_score(prior['score_record_id'])
    assert old.invalidated_by_correction_id
    assert replacement.id != old.id
    assert [s.id for s in ledger.list_scores()] == [replacement.id]
    assert ledger.get_postmortem(prior['id'])['invalidated_by_correction_id'] == old.invalidated_by_correction_id

    assert run_lifecycle(ledger, owner='rescore')[0]['status'] == 'completed'
    assert ledger.list_postmortems(question_id=q.id)[0]['score_record_id'] == replacement.id
    assert lifecycle_status(ledger)['counts']['unfinished'] == 0


def test_historical_lesson_repair_failure_uses_durable_attempt_queue(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path/'ledger.db')
    q = ledger.create_question(title='Will the release ship?', resolution_criteria='Resolve yes only on the official release announcement.')
    ledger.create_snapshot(question_id=q.id, probability_or_distribution=.9, rationale='Before announcement.')
    ledger.resolve_question(question_id=q.id, outcome='no', auto_score=False)
    run_lifecycle(ledger, owner='test')
    with ledger._connect() as conn:
        conn.execute('DELETE FROM calibration_lessons')
    def fail(**kwargs):
        raise RuntimeError('lesson persistence unavailable')
    monkeypatch.setattr(ledger, 'create_calibration_lesson', fail)
    result = run_lifecycle(ledger, owner='repair')
    assert result[0]['error'] == 'lesson persistence unavailable'
    report = lifecycle_status(ledger)
    task = next(t for t in report['tasks'] if t['idempotency_key'].endswith(':lesson'))
    assert task['attempt_count'] == 1
    assert task['error'] == 'lesson persistence unavailable'
    assert report['unfinished'][0]['reason'] == 'lesson_missing'
