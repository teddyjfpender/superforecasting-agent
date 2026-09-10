"""Real-ledger recovery, with unresolved outcomes and forecast values conserved."""
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
