"""Append-only interview revisions in the forecast ledger's transaction boundary."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING, Literal

from forecasting.interviews.models import InterviewDraft
from forecasting.models import ValidationError, utc_now_iso

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_buffers (
            interview_id TEXT NOT NULL, question_id TEXT NOT NULL,
            buffer_revision INTEGER NOT NULL CHECK(buffer_revision > 0),
            base_revision INTEGER NOT NULL, request_id TEXT NOT NULL,
            document TEXT, saved_at TEXT NOT NULL,
            PRIMARY KEY(interview_id, question_id),
            FOREIGN KEY(interview_id, base_revision)
                REFERENCES forecast_interview_revisions(interview_id, revision)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_buffer_receipts (
            interview_id TEXT NOT NULL, request_id TEXT NOT NULL,
            digest TEXT NOT NULL, receipt TEXT NOT NULL,
            PRIMARY KEY(interview_id, request_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_promotions (
            job_id TEXT PRIMARY KEY,
            repetition INTEGER NOT NULL,
            preview_digest TEXT NOT NULL,
            question_id TEXT NOT NULL,
            forecast_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_evaluation_requests (
            interview_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            spec TEXT NOT NULL,
            job_id TEXT NOT NULL,
            PRIMARY KEY (interview_id, request_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_contexts (
            interview_id TEXT PRIMARY KEY,
            document TEXT NOT NULL,
            digest TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_generation_requests (
            interview_id TEXT NOT NULL,
            request_id TEXT NOT NULL,
            spec TEXT NOT NULL,
            job_id TEXT NOT NULL,
            PRIMARY KEY (interview_id, request_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_revisions (
            interview_id TEXT NOT NULL,
            revision INTEGER NOT NULL CHECK (revision > 0),
            request_id TEXT NOT NULL,
            actor TEXT NOT NULL CHECK (actor IN ('user', 'agent')),
            document TEXT NOT NULL,
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (interview_id, revision),
            UNIQUE (interview_id, request_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_interview_commits (
            interview_id TEXT PRIMARY KEY,
            revision INTEGER NOT NULL,
            question_id TEXT NOT NULL REFERENCES forecast_questions(id),
            committed_at TEXT NOT NULL,
            FOREIGN KEY (interview_id, revision)
                REFERENCES forecast_interview_revisions(interview_id, revision)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS forecast_article_attachments (
            question_id TEXT NOT NULL REFERENCES forecast_questions(id),
            digest TEXT NOT NULL,
            evidence_id TEXT NOT NULL REFERENCES evidence_items(id),
            interview_id TEXT,
            PRIMARY KEY (question_id, digest)
        )
    """)


class InterviewStore:
    """No draft operation creates a forecast snapshot or changes its probability."""

    def __init__(self, ledger: ForecastLedger):
        self.ledger = ledger

    def read(self, interview_id: str, revision: int | None = None) -> dict:
        with self.ledger._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_interview_revisions WHERE interview_id = ? "
                + ("AND revision = ? " if revision is not None else "")
                + "ORDER BY revision DESC LIMIT 1",
                (interview_id, revision) if revision is not None else (interview_id,),
            ).fetchone()
        if row is None:
            raise ValidationError("interview revision not found")
        return {**dict(row), "document": json.loads(row["document"])}

    def list_latest(self, question_id: str | None = None) -> list[dict]:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                "SELECT r.interview_id FROM forecast_interview_revisions r "
                "WHERE r.revision = (SELECT MAX(v.revision) FROM forecast_interview_revisions v "
                "WHERE v.interview_id = r.interview_id) "
                "AND json_extract(r.document, '$.question_id') IS ? "
                "AND json_extract(r.document, '$.status') != 'cancelled' "
                "AND NOT EXISTS (SELECT 1 FROM forecast_interview_commits c WHERE c.interview_id = r.interview_id) "
                "ORDER BY r.created_at DESC, r.rowid DESC LIMIT 50",
                (question_id,),
            ).fetchall()
        return [self.read(row["interview_id"]) for row in rows]

    def save(
        self,
        interview_id: str,
        draft: InterviewDraft,
        *,
        expected_revision: int,
        request_id: str,
        actor: Literal["user", "agent"],
    ) -> dict:
        if not interview_id.strip() or not request_id.strip():
            raise ValidationError("interview and request identifiers are required")
        if actor not in {"user", "agent"}:
            raise ValidationError("unknown interview actor")
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValidationError("invalid expected revision")
        # Revalidate mutable nested lists and dictionaries even for model callers.
        draft = InterviewDraft.model_validate(draft.model_dump())
        document = json.dumps(
            draft.model_dump(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        digest = hashlib.sha256(document.encode()).hexdigest()
        with self.ledger.transaction(immediate=True) as conn:
            retry = conn.execute(
                "SELECT revision, digest, actor FROM forecast_interview_revisions "
                "WHERE interview_id = ? AND request_id = ?",
                (interview_id, request_id),
            ).fetchone()
            if retry is not None:
                if (
                    retry["digest"] != digest
                    or retry["actor"] != actor
                    or retry["revision"] != expected_revision + 1
                ):
                    raise ValidationError(
                        "request identifier reused for a different revision"
                    )
                return self.read(interview_id, retry["revision"])
            if conn.execute(
                "SELECT 1 FROM forecast_interview_commits WHERE interview_id = ?",
                (interview_id,),
            ).fetchone():
                raise ValidationError("committed interviews cannot be edited")
            previous = conn.execute(
                "SELECT revision, document FROM forecast_interview_revisions "
                "WHERE interview_id = ? ORDER BY revision DESC LIMIT 1",
                (interview_id,),
            ).fetchone()
            if (previous["revision"] if previous else 0) != expected_revision:
                raise ValidationError("interview changed; reload before saving")
            old = (
                InterviewDraft.model_validate_json(previous["document"])
                if previous
                else None
            )
            if old:
                if draft.parent_interview != old.parent_interview:
                    raise ValidationError("prior interview provenance is immutable")
                if draft.context_digest != old.context_digest:
                    raise ValidationError(
                        "interview context is immutable; start a new interview"
                    )
                if draft.seed != old.seed:
                    raise ValidationError("source seed provenance is immutable")
                if (draft.mode, draft.question_id, draft.baseline_forecast_id) != (
                    old.mode,
                    old.question_id,
                    old.baseline_forecast_id,
                ):
                    raise ValidationError("interview target and baseline are immutable")
                if old.status == "cancelled":
                    raise ValidationError("cancelled interviews cannot be edited")
                old_questions = {q.id: q for q in old.questions}
                answered_ids = {a.question_id for a in old.answers}
                current_questions = {q.id: q for q in draft.questions}
                if any(
                    current_questions.get(qid) != old_questions[qid]
                    for qid in answered_ids
                ):
                    raise ValidationError(
                        "answered questions cannot change meaning; create a new question identifier"
                    )
            inherited = None
            if draft.parent_interview and not draft.context_digest:
                raise ValidationError("inherited assumptions require frozen provenance")
            if draft.context_digest:
                from forecasting.interviews.context import read_context

                context = read_context(self.ledger, interview_id, draft.context_digest)
                if (
                    context["question"]["id"] != draft.question_id
                    or (
                        context["baseline"]["forecast_id"]
                        if context["baseline"]
                        else None
                    )
                    != draft.baseline_forecast_id
                ):
                    raise ValidationError(
                        "frozen context belongs to a different baseline"
                    )
                prior = context.get("prior_interview")
                expected_parent = (
                    {key: prior[key] for key in ("interview_id", "revision", "digest")}
                    if prior
                    else None
                )
                actual_parent = (
                    draft.parent_interview.model_dump()
                    if draft.parent_interview
                    else None
                )
                if actual_parent != expected_parent:
                    raise ValidationError(
                        "prior interview provenance does not match frozen context"
                    )
                if prior:
                    inherited = InterviewDraft.model_validate(prior["document"])
                    if old is None and (
                        draft.assumptions != inherited.assumptions
                        or draft.scenarios != inherited.scenarios
                    ):
                        raise ValidationError(
                            "initial inherited assumptions and scenarios must match their source"
                        )
                frozen_refs = {item["id"] for item in context["evidence"]}
                if set(draft.evidence_refs) != frozen_refs:
                    raise ValidationError(
                        "new evidence requires a new frozen interview"
                    )
            if draft.question_id:
                question = self.ledger.get_question(draft.question_id)
                if draft.baseline_forecast_id:
                    baseline = self.ledger.get_snapshot(draft.baseline_forecast_id)
                    if baseline.question_id != question.id:
                        raise ValidationError(
                            "baseline belongs to a different question"
                        )
            if actor == "agent":
                prior_ownership = old or inherited
                old_user = (
                    {a.question_id: a for a in old.answers if a.actor == "user"}
                    if old
                    else {}
                )
                new_user = {
                    a.question_id: a for a in draft.answers if a.actor == "user"
                }
                old_assumptions = (
                    {a.id: a for a in prior_ownership.assumptions if a.actor == "user"}
                    if prior_ownership
                    else {}
                )
                new_assumptions = {
                    a.id: a for a in draft.assumptions if a.actor == "user"
                }
                old_scenarios = (
                    {
                        item.id: item
                        for item in prior_ownership.scenarios
                        if item.actor == "user"
                    }
                    if prior_ownership
                    else {}
                )
                new_scenarios = {
                    item.id: item for item in draft.scenarios if item.actor == "user"
                }
                if new_scenarios != old_scenarios:
                    raise ValidationError(
                        "agents cannot invent, edit or remove user scenarios"
                    )
                if new_assumptions != old_assumptions:
                    raise ValidationError(
                        "agents cannot invent, edit or remove user assumptions"
                    )
                if new_user != old_user:
                    raise ValidationError(
                        "agents cannot invent, edit or remove user answers"
                    )
            if old:
                linked_assumptions = {
                    key
                    for scenario in old.scenarios
                    for key in [*scenario.conditions, *scenario.excluded_assumption_ids]
                } | {
                    key
                    for question in old.questions
                    if any(a.question_id == question.id for a in old.answers)
                    for key in question.assumption_ids
                }
                previous_assumptions = {a.id: a for a in old.assumptions}
                for assumption in draft.assumptions:
                    if (
                        assumption.id in linked_assumptions
                        and assumption.statement
                        != previous_assumptions[assumption.id].statement
                    ):
                        raise ValidationError(
                            "linked assumptions cannot change meaning; add a new driver and rebuild its scenarios or questions"
                        )
            conn.execute(
                "INSERT INTO forecast_interview_revisions "
                "(interview_id, revision, request_id, actor, document, digest, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    interview_id,
                    expected_revision + 1,
                    request_id,
                    actor,
                    document,
                    digest,
                    utc_now_iso(),
                ),
            )
            if draft.status == "cancelled":
                conn.execute(
                    "UPDATE forecast_interview_buffers SET document=NULL WHERE interview_id=?",
                    (interview_id,),
                )
            return self.read(interview_id)
