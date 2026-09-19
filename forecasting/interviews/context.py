"""Frozen ledger inputs for reproducible interview and scenario model calls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from forecasting.models import ValidationError, utc_now_iso

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger
    from forecasting.models import ForecastQuestion


def capture_context(
    ledger: ForecastLedger, interview_id: str, question: ForecastQuestion
) -> tuple[dict, str]:
    """Called inside begin's transaction; never replace a prior capture."""
    baseline = (
        ledger.get_snapshot(question.current_forecast_id)
        if question.current_forecast_id
        else None
    )
    if baseline and baseline.question_id != question.id:
        raise ValidationError("baseline belongs to a different question")
    evidence = ledger.list_evidence(question.id)
    # Keep the complete packet durable. A prompt's size limit is a separate
    # admission check; it must never silently discard evidence or provenance.
    context = {
        "schema_version": 1,
        "captured_at": utc_now_iso(),
        "question": asdict(question),
        "baseline": asdict(baseline) if baseline else None,
        "evidence": [asdict(item) for item in evidence],
        "reference_classes": ledger.list_reference_classes(question.id),
        "prior_interview": previous_interview(ledger, question.id),
    }
    document = json.dumps(
        context, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    digest = hashlib.sha256(document.encode()).hexdigest()
    with ledger.transaction(immediate=True) as conn:
        conn.execute(
            "INSERT INTO forecast_interview_contexts (interview_id, document, digest) VALUES (?, ?, ?)",
            (interview_id, document, digest),
        )
    return context, digest


def read_context(ledger: ForecastLedger, interview_id: str, digest: str) -> dict:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT document, digest FROM forecast_interview_contexts WHERE interview_id = ?",
            (interview_id,),
        ).fetchone()
    if (
        row is None
        or row["digest"] != digest
        or hashlib.sha256(row["document"].encode()).hexdigest() != digest
    ):
        raise ValidationError("frozen interview context is missing or corrupt")
    return json.loads(row["document"])


def previous_interview(ledger: ForecastLedger, question_id: str) -> dict | None:
    """Latest non-cancelled review, or the committed interview that created it.

    A prior draft is historical elicitation, not the active forecast. Bind the
    exact revision and content so later edits cannot rewrite inherited provenance.
    """
    from protocol.interviews import InterviewDraft

    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT r.* FROM forecast_interview_revisions r "
            "LEFT JOIN forecast_interview_commits c ON c.interview_id = r.interview_id "
            "WHERE ((json_extract(r.document, '$.question_id') = ? AND "
            "r.revision = (SELECT MAX(v.revision) FROM forecast_interview_revisions v "
            "WHERE v.interview_id = r.interview_id)) OR "
            "(c.question_id = ? AND c.revision = r.revision)) "
            "AND json_extract(r.document, '$.status') != 'cancelled' "
            "ORDER BY r.created_at DESC, r.rowid DESC LIMIT 1",
            (question_id, question_id),
        ).fetchone()
    if row is None:
        return None
    if hashlib.sha256(row["document"].encode()).hexdigest() != row["digest"]:
        raise ValidationError("prior interview revision is corrupt")
    InterviewDraft.model_validate_json(row["document"])
    return {
        "interview_id": row["interview_id"],
        "revision": row["revision"],
        "digest": row["digest"],
        "document": json.loads(row["document"]),
    }
