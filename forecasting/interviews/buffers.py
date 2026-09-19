"""Durable unconfirmed editor buffers, separate from confirmed interview revisions."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from forecasting.interviews.store import InterviewStore
from forecasting.models import ValidationError, utc_now_iso
from protocol.rpc.interviews import InterviewBufferReceipt, InterviewBufferSaveRequest

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger


def save_buffer(ledger: ForecastLedger, request: InterviewBufferSaveRequest) -> dict:
    # Revalidate mutated model instances too; every caller shares this boundary.
    request = InterviewBufferSaveRequest.model_validate(
        request.model_dump(), strict=True
    )
    encoded = json.dumps(
        request.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    with ledger.transaction(immediate=True) as conn:
        retry = conn.execute(
            "SELECT digest,receipt FROM forecast_interview_buffer_receipts WHERE interview_id=? AND request_id=?",
            (request.interview_id, request.request_id),
        ).fetchone()
        if retry:
            if retry["digest"] != digest:
                raise ValidationError(
                    "buffer request identifier reused for different content"
                )
            # The receipt acknowledges that revision, not that it is still current.
            # Its replay cannot resurrect content discarded by a later revision.
            return json.loads(retry["receipt"])
        record = InterviewStore(ledger).read(request.interview_id)
        if (
            record["document"]["status"] == "cancelled"
            or conn.execute(
                "SELECT 1 FROM forecast_interview_commits WHERE interview_id=?",
                (request.interview_id,),
            ).fetchone()
        ):
            raise ValidationError("closed interviews cannot save editor buffers")
        if record["revision"] != request.base_revision:
            raise ValidationError(
                "interview changed; reload before saving editor buffer"
            )
        question = next(
            (
                q
                for q in record["document"]["questions"]
                if q["id"] == request.question_id
            ),
            None,
        )
        if question is None:
            raise ValidationError("unknown interview question")
        if request.buffer:
            choices = {item["id"] for item in question["choices"]}
            if (
                request.buffer.choice > len(choices)
                or not set(request.buffer.selected) <= choices
            ):
                raise ValidationError(
                    "editor selection does not match interview choices"
                )
            if len(set(request.buffer.selected)) != len(request.buffer.selected):
                raise ValidationError("duplicate editor selections")
        previous = conn.execute(
            "SELECT buffer_revision FROM forecast_interview_buffers WHERE interview_id=? AND question_id=?",
            (request.interview_id, request.question_id),
        ).fetchone()
        revision = previous["buffer_revision"] if previous else 0
        if revision != request.expected_buffer_revision:
            raise ValidationError("editor buffer changed; reload before saving")
        receipt = InterviewBufferReceipt(
            interview_id=request.interview_id,
            question_id=request.question_id,
            base_revision=request.base_revision,
            buffer_revision=revision + 1,
            request_id=request.request_id,
            saved_at=utc_now_iso(),
            discarded=request.buffer is None,
        ).model_dump()
        conn.execute(
            "INSERT INTO forecast_interview_buffers VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(interview_id,question_id) DO UPDATE SET buffer_revision=excluded.buffer_revision,"
            "base_revision=excluded.base_revision,request_id=excluded.request_id,document=excluded.document,saved_at=excluded.saved_at",
            (
                request.interview_id,
                request.question_id,
                revision + 1,
                request.base_revision,
                request.request_id,
                request.buffer.model_dump_json() if request.buffer else None,
                receipt["saved_at"],
            ),
        )
        # Receipts contain a content digest and acknowledgement, never the editor text.
        conn.execute(
            "INSERT INTO forecast_interview_buffer_receipts VALUES (?,?,?,?)",
            (
                request.interview_id,
                request.request_id,
                digest,
                json.dumps(receipt, sort_keys=True),
            ),
        )
        return receipt


def read_buffers(ledger: ForecastLedger, interview_id: str) -> dict:
    with ledger.transaction() as conn:
        record = InterviewStore(ledger).read(interview_id)
        closed = (
            record["document"]["status"] == "cancelled"
            or conn.execute(
                "SELECT 1 FROM forecast_interview_commits WHERE interview_id=?",
                (interview_id,),
            ).fetchone()
            is not None
        )
        if closed:
            return {"buffers": []}
        rows = conn.execute(
            "SELECT * FROM forecast_interview_buffers WHERE interview_id=? ORDER BY question_id",
            (interview_id,),
        ).fetchall()
        return {
            "buffers": [
                {
                    key: row[key]
                    for key in (
                        "interview_id",
                        "question_id",
                        "base_revision",
                        "buffer_revision",
                        "request_id",
                        "saved_at",
                    )
                }
                | {
                    "buffer": json.loads(row["document"]) if row["document"] else None,
                    "discarded": row["document"] is None,
                    "stale": row["base_revision"] != record["revision"],
                }
                for row in rows
            ]
        }
