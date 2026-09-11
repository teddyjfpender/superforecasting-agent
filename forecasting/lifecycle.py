"""Lifecycle inspection and recovery over the existing durable task queue.

Close dates request settlement review, never establish outcomes. Recovery only
finalizes already-confirmed resolutions; research and probability updates retain
their existing explicit commands and gates.
"""

from __future__ import annotations

import uuid
import json
from typing import Any

from forecasting.models import parse_timestamp, timestamp_to_datetime, utc_now_iso


def lifecycle_status(ledger, *, now: str | None = None) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        # Only the latest eligible resolution, the current committed snapshot,
        # and its non-invalidated score/postmortem can complete this lifecycle.
        unfinished = [dict(r) for r in conn.execute("""
            SELECT q.id AS question_id, q.title, q.current_forecast_id AS forecast_id,
                   r.id AS resolution_id,
                   CASE WHEN q.current_forecast_id IS NULL THEN 'forecast_missing'
                        WHEN s.id IS NULL THEN 'score_missing'
                        ELSE 'postmortem_missing' END AS reason
            FROM forecast_questions q
            JOIN resolutions r ON r.id = (
                SELECT id FROM resolutions WHERE question_id = q.id
                  AND resolution_status = 'confirmed' AND criteria_satisfied = 1
                  AND scoreable = 1 ORDER BY resolved_at DESC, rowid DESC LIMIT 1)
            LEFT JOIN score_records s ON s.forecast_id = q.current_forecast_id
                AND s.resolution_id = r.id AND s.invalidated_by_correction_id IS NULL
            WHERE q.status = 'resolved' AND (s.id IS NULL OR NOT EXISTS (
                SELECT 1 FROM postmortems p WHERE p.score_record_id = s.id
                  AND p.invalidated_by_correction_id IS NULL))
            ORDER BY q.id
        """)]
        attention = [dict(r) for r in conn.execute("""
            SELECT id AS question_id, title, close_time, resolution_time, next_review_at,
                   CASE WHEN julianday(COALESCE(resolution_time, close_time)) <= julianday(?)
                        THEN 'settlement_review' ELSE 'review_overdue' END AS reason
            FROM forecast_questions WHERE status = 'active'
              AND (julianday(COALESCE(resolution_time, close_time)) <= julianday(?)
                   OR julianday(next_review_at) <= julianday(?)) ORDER BY id
        """, (stamp, stamp, stamp))]
        tasks = [dict(r) for r in conn.execute("""
            SELECT id, question_id, status, available_at, lease_expires_at,
                   attempt_count, max_attempts, error, idempotency_key
            FROM operational_tasks WHERE task_type = 'finalize_resolution'
              AND status != 'completed' ORDER BY created_at, id
        """)]
        ready = conn.execute("""
            SELECT COUNT(*) FROM operational_tasks WHERE task_type = 'finalize_resolution'
              AND attempt_count < max_attempts AND julianday(available_at) <= julianday(?)
              AND (status = 'pending' OR
                   (status = 'leased' AND julianday(lease_expires_at) <= julianday(?)))
        """, (stamp, stamp)).fetchone()[0]
        keys = {r[0] for r in conn.execute(
            "SELECT idempotency_key FROM operational_tasks WHERE task_type = 'finalize_resolution'"
        )}
    with ledger._connect() as conn:
        reviews = {}
        for note in conn.execute("SELECT question_id, body, metadata, created_at FROM analyst_notes ORDER BY created_at, rowid"):
            meta = json.loads(note["metadata"] or "{}")
            if meta.get("lifecycle_review"):
                reviews[note["question_id"]] = {"body": note["body"], "source": meta.get("source"),
                    "revisit_at": meta.get("revisit_at"), "created_at": note["created_at"]}
    from forecasting.settlement_reviews import latest_reviews
    durable_reviews = latest_reviews(ledger)
    for row in unfinished + attention:
        if row['question_id'] in durable_reviews:
            row['settlement'] = durable_reviews[row['question_id']]
    reminder_due = sum(bool(r['revisit_at'] and not r['notified_at'] and
        timestamp_to_datetime(r['revisit_at']) <=
        timestamp_to_datetime(stamp))
        for r in durable_reviews.values() if ledger.get_question(r['question_id']).status != 'resolved')
    for row in unfinished + attention:
        if row["question_id"] in reviews:
            row["review"] = reviews[row["question_id"]]
    limitations = [r for r in unfinished if r.get('settlement', {}).get('state') == 'no_historical_forecast' and r['forecast_id'] is None]
    unfinished = [r for r in unfinished if r not in limitations]
    for row in attention:
        review = row.get('settlement', {})
        if review.get('revisit_at') and timestamp_to_datetime(review['revisit_at']) > timestamp_to_datetime(stamp):
            row['reason'] = 'waiting:' + review['state']
    for row in unfinished:
        row["task_missing"] = f"finalize-resolution:{row['resolution_id']}" not in keys
    return {
        "as_of": stamp, "settlement_reviews": list(durable_reviews.values()), "limitations": limitations, "attention": attention, "unfinished": unfinished, "tasks": tasks,
        "counts": {
            "settlement_review": sum(r["reason"] == "settlement_review" for r in attention),
            "review_overdue": sum(r["reason"] == "review_overdue" for r in attention),
            "unfinished": len(unfinished), "ready_tasks": ready,
            "review_reminders_due": reminder_due,
            "deferred_settlements": sum(r['state'] not in ('ready', 'no_historical_forecast') and ledger.get_question(r['question_id']).status != 'resolved' for r in durable_reviews.values()),
            "documented_unscoreable": sum(r['state'] == 'no_historical_forecast' for r in durable_reviews.values()),
            "missing_tasks": sum(r["task_missing"] and r["forecast_id"] is not None for r in unfinished),
            "failed_tasks": sum(r["status"] in ("failed", "dead_letter") for r in tasks),
        },
    }


def run_lifecycle(ledger, *, owner: str, now: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Recover missing handoffs, then use the same leased, retryable finalizer.

    Never resets exhausted retries or edits probabilities/resolutions. Duplicate
    runs reuse the resolution key and the existing score/postmortem identities.
    """
    from forecasting.settlement_reviews import emit_due_reminders
    emit_due_reminders(ledger, now=now)
    report = lifecycle_status(ledger, now=now)
    with ledger._connect() as conn:
        for row in report["unfinished"]:
            if not row["task_missing"] or row["forecast_id"] is None:
                continue
            conn.execute("""
                INSERT OR IGNORE INTO operational_tasks
                    (id, task_type, lane, question_id, status, priority, available_at,
                     idempotency_key, created_at, updated_at)
                VALUES (?, 'finalize_resolution', 'deterministic_critical', ?, 'pending',
                        100, ?, ?, ?, ?)
            """, (f"ot_{uuid.uuid4().hex[:12]}", row["question_id"], report["as_of"],
                  f"finalize-resolution:{row['resolution_id']}", report["as_of"], report["as_of"]))
    return ledger.run_resolution_finalization_tasks(owner=owner, now=report["as_of"], limit=limit)
