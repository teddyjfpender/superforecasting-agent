import pytest
from forecasting import ForecastLedger
from forecasting.settlement_reviews import record_review, emit_due_reminders, latest_reviews
from forecasting.lifecycle import lifecycle_status, run_lifecycle
from forecasting.models import ValidationError


def question(ledger):
    return ledger.create_question(title='Will the official result confirm the event?',resolution_criteria='YES if the official publication confirms the event.',close_time='2026-08-01T00:00:00Z')


def test_deferred_review_reminds_once_and_survives_restart(tmp_path):
    ledger=ForecastLedger(tmp_path/'db');q=question(ledger)
    review=record_review(ledger,question_id=q.id,state='awaiting_source',reason='Certified result unavailable',source='https://example.org/results',next_action='Retrieve certified totals',owner='operator',revisit_at='2026-09-02T00:00:00Z',now='2026-09-01T00:00:00Z')
    assert lifecycle_status(ledger,now='2026-09-01T00:00:00Z')['attention'][0]['reason']=='waiting:awaiting_source'
    ledger=ForecastLedger(tmp_path/'db')
    assert lifecycle_status(ledger,now='2026-09-02T00:00:00Z')['counts']['review_reminders_due']==1
    run_lifecycle(ledger,owner='test',now='2026-09-02T00:00:00Z')
    alerts=[a for a in ledger.list_alerts() if a.reason=='settlement_review:'+review['id']]
    assert len(alerts)==1
    ledger.acknowledge_alert(alerts[0].id)
    assert emit_due_reminders(ledger,now='2026-09-03T00:00:00Z')==[]
    assert ledger.get_question(q.id).status=='active' and ledger.get_current_snapshot(q.id) is None


def test_review_supersession_cancels_old_reminder(tmp_path):
    ledger=ForecastLedger(tmp_path/'db');q=question(ledger)
    for date in ['2026-09-02T00:00:00Z','2026-09-10T00:00:00Z']:
        record_review(ledger,question_id=q.id,state='identity_unresolved',reason='Need canonical identity',source='https://example.org',next_action='Bind market ID',owner='operator',revisit_at=date,now='2026-09-01T00:00:00Z')
    assert emit_due_reminders(ledger,now='2026-09-03T00:00:00Z')==[]
    assert latest_reviews(ledger)[q.id]['revisit_at']=='2026-09-10T00:00:00Z'


def test_missing_forecast_is_documented_without_fabricating_history(tmp_path):
    ledger=ForecastLedger(tmp_path/'db');q=question(ledger)
    ledger.resolve_question(question_id=q.id,outcome='yes')
    record_review(ledger,question_id=q.id,state='no_historical_forecast',reason='No pre-outcome forecast exists',source='Ledger history',next_action='Retain outcome without a performance claim',owner='operator')
    report=lifecycle_status(ledger)
    assert not report['unfinished'] and len(report['limitations'])==1
    assert report['counts']['documented_unscoreable']==1
    assert not ledger.list_scores()
    assert report['counts']['ready_tasks'] == 0
    assert run_lifecycle(ledger, owner='test') == []


def test_defer_requires_a_real_next_action_and_date(tmp_path):
    ledger=ForecastLedger(tmp_path/'db');q=question(ledger)
    with pytest.raises(ValidationError):
        record_review(ledger,question_id=q.id,state='awaiting_source',reason='Pending',source='Official source',next_action='Fetch',owner='operator')
    assert not latest_reviews(ledger)


def test_reminder_and_marker_roll_back_together(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path/'db'); q = question(ledger)
    record_review(ledger, question_id=q.id, state='awaiting_source', reason='Pending source', source='Official report',
        next_action='Check report', owner='operator', revisit_at='2026-09-02T00:00:00Z', now='2026-09-01T00:00:00Z')
    original = ledger.create_alert
    def interrupted(**kwargs):
        original(**kwargs)
        raise RuntimeError('worker interrupted after alert insert')
    monkeypatch.setattr(ledger, 'create_alert', interrupted)
    with pytest.raises(RuntimeError):
        emit_due_reminders(ledger, now='2026-09-03T00:00:00Z')
    assert not ledger.list_alerts()
    assert latest_reviews(ledger)[q.id]['notified_at'] is None
    monkeypatch.setattr(ledger, 'create_alert', original)
    assert len(emit_due_reminders(ledger, now='2026-09-03T00:00:00Z')) == 1


def test_abandoned_lease_finishes_as_documented_limitation(tmp_path):
    ledger = ForecastLedger(tmp_path/'db'); q = question(ledger)
    ledger.resolve_question(question_id=q.id, outcome='yes')
    with ledger._connect() as conn:
        conn.execute("UPDATE operational_tasks SET status='leased',lease_owner='gone',lease_expires_at='2020-01-01T00:00:00Z' WHERE question_id=?", (q.id,))
    record_review(ledger, question_id=q.id, state='no_historical_forecast', reason='No forecast exists',
        source='Ledger', next_action='Retain without score', owner='operator')
    results = run_lifecycle(ledger, owner='recovery')
    assert len(results) == 1 and results[0]['disposition'] == 'no_historical_forecast'
    assert results[0]['status'] == 'completed' and not ledger.list_scores()
    assert not run_lifecycle(ledger, owner='recovery')
