"""Immutable, advisory lesson selection for questionnaire model inputs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from forecasting.learning import (
    active_lessons_for_question,
    lesson_applicability,
    lesson_candidates_for_question,
    lesson_cutoff_reason,
)
from forecasting.models import (
    LedgerNotFoundError,
    ValidationError,
    timestamp_to_datetime,
)
from forecasting.trial_inputs import score_support_problem

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger
    from forecasting.models import ForecastQuestion


@dataclass(frozen=True)
class UnclassifiedOutcome:
    type: None = None
    choices: tuple[str, ...] = ()


@dataclass(frozen=True)
class UnclassifiedInterviewTarget:
    """A policy query target, never a scoreable or persisted forecast question."""

    id: str
    domain: None = None
    topics: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    outcome_space: UnclassifiedOutcome = field(default_factory=UnclassifiedOutcome)


def capture_lessons(
    ledger: ForecastLedger,
    question: ForecastQuestion | UnclassifiedInterviewTarget,
    cutoff: str,
) -> dict[str, Any]:
    """Reuse scope, applicability and supersession; never apply an adjustment.

    Counts describe recorded score support, not statistical independence. There
    is no canonical cluster assignment for the lesson library, so its independent
    cluster count remains unknown rather than treating questions as independent.
    """
    context = {"_fact_cutoff": cutoff}
    selected = {
        item["id"]
        for item in active_lessons_for_question(ledger, question, context=context)
    }
    records = []
    for lesson in sorted(
        lesson_candidates_for_question(ledger, question), key=lambda item: item["id"]
    ):
        reason = lesson_cutoff_reason(lesson, cutoff)
        if reason is None and lesson.get("invalidated_by_correction_id"):
            reason = "invalidated_lesson"
        if reason is None and lesson["status"] != "active":
            reason = "inactive_lesson"
        applicable, applicability_reason = lesson_applicability(
            lesson, question, context, ledger=ledger
        )
        if reason is None and not applicable:
            reason = applicability_reason
        if reason is None and lesson["id"] not in selected:
            reason = "superseded_in_scope"
        scores = []
        postmortems = []
        support_problems = []
        score_ids = set(lesson["source_score_record_refs"])
        for postmortem_id in sorted(set(lesson["source_postmortem_refs"])):
            try:
                postmortem = ledger.get_postmortem(postmortem_id)
            except LedgerNotFoundError:
                support_problems.append("missing_source_postmortem")
                continue
            if postmortem.get("invalidated_by_correction_id") or not postmortem.get(
                "calibration_eligible"
            ):
                support_problems.append("ineligible_source_postmortem")
                continue
            try:
                created = timestamp_to_datetime(postmortem["created_at"])
                at = timestamp_to_datetime(cutoff)
                if created is None or at is None:
                    support_problems.append("invalid_postmortem_timestamp")
                    continue
                if created > at:
                    support_problems.append("post_cutoff_source_postmortem")
                    continue
            except (KeyError, ValueError, TypeError, ValidationError):
                support_problems.append("invalid_postmortem_timestamp")
                continue
            score_id = postmortem.get("score_record_id")
            if not isinstance(score_id, str) or not score_id:
                support_problems.append("missing_postmortem_score")
                continue
            score_ids.add(score_id)
            postmortems.append(postmortem)
        for score_id in sorted(score_ids):
            try:
                score = ledger.get_score(score_id)
            except (KeyError, LedgerNotFoundError, ValidationError):
                support_problems.append("missing_source_score")
                continue
            problem = score_support_problem(score, cutoff, (question.id,))
            if problem:
                support_problems.append(problem)
            else:
                scores.append(score)
        if reason is None and support_problems:
            reason = support_problems[0]
        document = json.dumps(
            lesson, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        records.append({
            "lesson_id": lesson["id"],
            "revision": lesson["updated_at"],
            "content_digest": hashlib.sha256(document.encode()).hexdigest(),
            "lesson": lesson,
            "included": reason is None,
            "reason": reason or applicability_reason,
            "advisory_only": True,
            "score_support": [asdict(score) for score in scores],
            "postmortem_support": postmortems,
            "support_score_count": len(scores),
            "distinct_outcome_count": len({score.question_id for score in scores}),
            "independent_cluster_count": None,
            "cluster_count_reason": "no_verified_cluster_assignment",
            "support_problems": sorted(set(support_problems)),
        })
    return {
        "schema_version": 1,
        "policy": "interview-lessons-v1",
        "cutoff": cutoff,
        "records": records,
    }


def model_lessons(selection: dict[str, Any]) -> dict[str, Any]:
    """Keep exclusion receipts without exposing inadmissible guidance to the model."""
    records = selection["records"]
    return {
        "schema_version": selection["schema_version"],
        "policy": selection["policy"],
        "cutoff": selection["cutoff"],
        "records": [item for item in records if item["included"]],
        "exclusions": [
            {"lesson_id": item["lesson_id"], "reason": item["reason"]}
            for item in records
            if not item["included"]
        ],
    }
