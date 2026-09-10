"""Lifecycle inspection and recovery over the existing durable task queue.

Close dates request settlement review, never establish outcomes. Recovery only
finalizes already-confirmed resolutions; research and probability updates retain
their existing explicit commands and gates.
"""

from __future__ import annotations

import uuid
from typing import Any

from forecasting.models import parse_timestamp, utc_now_iso


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
            SELECT id AS question_id, title, close_time, next_review_at,
                   CASE WHEN julianday(close_time) <= julianday(?)
                        THEN 'settlement_review' ELSE 'review_overdue' END AS reason
            FROM forecast_questions WHERE status = 'active'
              AND (julianday(close_time) <= julianday(?)
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
    for row in unfinished:
        row["task_missing"] = f"finalize-resolution:{row['resolution_id']}" not in keys
    return {
        "as_of": stamp, "attention": attention, "unfinished": unfinished, "tasks": tasks,
        "counts": {
            "settlement_review": sum(r["reason"] == "settlement_review" for r in attention),
            "review_overdue": sum(r["reason"] == "review_overdue" for r in attention),
            "unfinished": len(unfinished), "ready_tasks": ready,
            "missing_tasks": sum(r["task_missing"] and r["forecast_id"] is not None for r in unfinished),
            "failed_tasks": sum(r["status"] in ("failed", "dead_letter") for r in tasks),
        },
    }


def run_lifecycle(ledger, *, owner: str, now: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
    """Recover missing handoffs, then use the same leased, retryable finalizer.

    Never resets exhausted retries or edits probabilities/resolutions. Duplicate
    runs reuse the resolution key and the existing score/postmortem identities.
    """
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
