"""Append-only settlement decisions with durable, exactly-once reminder creation."""
from __future__ import annotations

import uuid
import json
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime, utc_now_iso

STATES = ('ready', 'awaiting_source', 'future_outcome', 'identity_unresolved', 'censoring_required', 'no_historical_forecast')


def initialize_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS settlement_reviews (
        id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES forecast_questions(id),
        state TEXT NOT NULL, reason TEXT NOT NULL, source TEXT NOT NULL,
        next_action TEXT NOT NULL, owner TEXT NOT NULL, revisit_at TEXT,
        created_at TEXT NOT NULL, notified_at TEXT)''')
    conn.execute('CREATE INDEX IF NOT EXISTS settlement_reviews_question ON settlement_reviews(question_id, created_at)')


def latest_reviews(ledger):
    with ledger._connect() as conn:
        return {r['question_id']: dict(r) for r in conn.execute('SELECT * FROM settlement_reviews ORDER BY rowid')}


def record_review(ledger, *, question_id, state, reason, source, next_action, owner, revisit_at=None, now=None):
    if state not in STATES:
        raise ValidationError('unknown settlement review state')
    if not all(isinstance(s, str) and s.strip() for s in (reason, source, next_action, owner)):
        raise ValidationError('review requires reason, source, next_action and owner')
    stamp = parse_timestamp(now, field_name='now') or utc_now_iso()
    revisit = parse_timestamp(revisit_at, field_name='revisit_at')
    if state not in ('ready', 'no_historical_forecast') and not revisit:
        raise ValidationError('deferred reviews require a revisit time')
    if revisit and timestamp_to_datetime(revisit) <= timestamp_to_datetime(stamp):
        raise ValidationError('revisit time must be in the future')
    with ledger.transaction(immediate=True):
        q = ledger.get_question(question_id)
        if state == 'no_historical_forecast':
            with ledger._connect() as conn:
                count = conn.execute('SELECT count(*) FROM forecast_snapshots WHERE question_id=?', (q.id,)).fetchone()[0]
            if q.status != 'resolved' or count:
                raise ValidationError('no_historical_forecast requires a resolved question with no snapshots')
            if revisit:
                raise ValidationError('no_historical_forecast is a documented terminal limitation, not a scheduled retry')
        elif q.status == 'resolved':
            raise ValidationError('resolved questions do not need settlement review')
        review_id = 'sr_' + uuid.uuid4().hex[:12]
        with ledger._connect() as conn:
            conn.execute('INSERT INTO settlement_reviews (id,question_id,state,reason,source,next_action,owner,revisit_at,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                (review_id, q.id, state, reason.strip(), source.strip(), next_action.strip(), owner.strip(), revisit, stamp))
            if state == 'no_historical_forecast':
                conn.execute("""UPDATE operational_tasks SET status='completed',
                    disposition='no_historical_forecast', result=?, error=NULL,
                    completed_at=?, updated_at=? WHERE question_id=? AND task_type='finalize_resolution'
                    AND status NOT IN ('completed', 'leased')""",
                    (json.dumps({'settlement_review_id': review_id}), stamp, stamp, q.id))
        for alert in ledger.list_alerts():
            if alert.scope_ref == q.id and alert.reason.startswith('settlement_review:'):
                ledger.acknowledge_alert(alert.id, ack_note='Superseded by review '+review_id, disposition='reviewed')
    return latest_reviews(ledger)[q.id]


def emit_due_reminders(ledger, *, now=None):
    stamp = parse_timestamp(now, field_name='now') or utc_now_iso()
    emitted = []
    with ledger.transaction(immediate=True):
        for review in latest_reviews(ledger).values():
            if review['notified_at'] or not review['revisit_at'] or timestamp_to_datetime(review['revisit_at']) > timestamp_to_datetime(stamp):
                continue
            if ledger.get_question(review['question_id']).status == 'resolved':
                continue
            alert = ledger.create_alert(severity='medium', scope_type='question', scope_ref=review['question_id'],
                reason='settlement_review:'+review['id'],
                recommended_action=f"{review['owner']}: {review['next_action']} (state: {review['state']}; source: {review['source']})", now=stamp)
            with ledger._connect() as conn:
                conn.execute('UPDATE settlement_reviews SET notified_at=? WHERE id=?', (stamp, review['id']))
            emitted.append(alert.id)
    return emitted
