"""Search helpers for forecast ledger questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem, ForecastQuestion, ForecastSnapshot


_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ForecastSearchMatch:
    question: ForecastQuestion
    current_snapshot: ForecastSnapshot | None
    latest_evidence: EvidenceItem | None
    score: int
    matched_fields: list[str] = field(default_factory=list)
    snippets: dict[str, str] = field(default_factory=dict)


def normalize_search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return " ".join(normalize_search_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{key} {normalize_search_text(item)}" for key, item in value.items())
    return " ".join(_WORD_RE.findall(str(value).lower()))


def search_tokens(query: str) -> list[str]:
    return _WORD_RE.findall(query.lower())


def search_forecasts(
    ledger: ForecastLedger,
    query: str,
    *,
    status: str | None = "active",
    domain: str | None = None,
    topic: str | None = None,
    limit: int = 20,
) -> list[ForecastSearchMatch]:
    """Rank forecast questions by question metadata and recent ledger context."""

    raw_query = query.strip()
    tokens = search_tokens(raw_query)
    normalized_query = normalize_search_text(raw_query)
    if not tokens or not normalized_query:
        return []

    question_status = None if status in {None, "all"} else status
    candidates = ledger.list_questions(status=question_status, domain=domain, limit=None)
    topic_filter = normalize_search_text(topic) if topic else ""
    matches: list[ForecastSearchMatch] = []

    for question in candidates:
        if topic_filter and topic_filter not in normalize_search_text(question.topics):
            continue
        match = _score_question(ledger, question, normalized_query, tokens)
        if match.score > 0:
            matches.append(match)

    matches.sort(
        key=lambda item: (
            item.score,
            item.current_snapshot.as_of if item.current_snapshot else "",
            item.question.created_at,
        ),
        reverse=True,
    )
    return matches[: max(limit, 0)]


def match_to_dict(match: ForecastSearchMatch) -> dict[str, Any]:
    question = match.question
    current = match.current_snapshot
    latest_evidence = match.latest_evidence
    return {
        "question": {
            "id": question.id,
            "title": question.title,
            "status": question.status,
            "domain": question.domain,
            "topics": question.topics,
            "close_time": question.close_time,
            "resolution_time": question.resolution_time,
        },
        "current_forecast": current.__dict__ if current else None,
        "latest_evidence": latest_evidence.__dict__ if latest_evidence else None,
        "score": match.score,
        "matched_fields": match.matched_fields,
        "snippets": match.snippets,
    }


def _score_question(
    ledger: ForecastLedger,
    question: ForecastQuestion,
    normalized_query: str,
    tokens: list[str],
) -> ForecastSearchMatch:
    current = ledger.get_current_snapshot(question.id)
    evidence = ledger.list_evidence(question.id)
    assumptions = ledger.list_assumptions(question.id)
    reference_classes = ledger.list_reference_classes(question.id)
    model_runs = ledger.list_model_runs(question.id)
    latest_evidence = evidence[-1] if evidence else None

    fields = _question_search_fields(
        question,
        current=current,
        evidence=evidence,
        assumptions=assumptions,
        reference_classes=reference_classes,
        model_runs=model_runs,
    )
    score = 0
    matched_fields: list[str] = []
    snippets: dict[str, str] = {}

    for name, weight, value in fields:
        text = normalize_search_text(value)
        if not text:
            continue
        field_score = _field_score(text, normalized_query, tokens, weight)
        if field_score <= 0:
            continue
        score += field_score
        if name not in matched_fields:
            matched_fields.append(name)
        if name not in snippets and len(snippets) < 4:
            snippets[name] = _snippet(value)

    return ForecastSearchMatch(
        question=question,
        current_snapshot=current,
        latest_evidence=latest_evidence,
        score=score,
        matched_fields=matched_fields,
        snippets=snippets,
    )


def _question_search_fields(
    question: ForecastQuestion,
    *,
    current: ForecastSnapshot | None,
    evidence: list[EvidenceItem],
    assumptions: list[dict[str, Any]],
    reference_classes: list[dict[str, Any]],
    model_runs: list[dict[str, Any]],
) -> list[tuple[str, int, Any]]:
    short_id = question.id.split("_", 1)[-1][:8]
    fields: list[tuple[str, int, Any]] = [
        ("id", 100, [question.id, short_id]),
        ("title", 18, question.title),
        ("description", 10, question.description),
        ("resolution_criteria", 9, question.resolution_criteria),
        ("resolution_source", 8, question.resolution_source),
        ("domain", 12, question.domain),
        ("topics", 12, question.topics),
        ("tags", 8, question.tags),
        ("status", 4, question.status),
        ("owner", 3, question.owner),
        ("impact", 3, question.impact),
    ]
    if current:
        fields.extend(
            [
                ("current_rationale", 14, current.rationale),
                ("current_method", 6, current.method),
                ("current_assumptions", 8, current.key_assumptions),
                ("current_components", 5, current.ensemble_components),
            ]
        )
    for item in evidence[-12:]:
        fields.extend(
            [
                ("evidence_claim", 12, item.claim),
                ("evidence_summary", 10, item.summary),
                ("evidence_source", 7, [item.source_name, item.source_url, item.source_type]),
                ("evidence_metadata", 4, item.metadata),
            ]
        )
    for item in assumptions:
        fields.append(("assumption", 8, [item.get("text"), item.get("status"), item.get("notes")]))
    for item in reference_classes:
        fields.append(
            (
                "reference_class",
                9,
                [
                    item.get("name"),
                    item.get("inclusion_criteria"),
                    item.get("exclusion_criteria"),
                    item.get("status"),
                    item.get("notes"),
                ],
            )
        )
    for item in model_runs[-8:]:
        fields.append(("model_run", 5, [item.get("model_type"), item.get("status"), item.get("diagnostics")]))
    return fields


def _field_score(text: str, normalized_query: str, tokens: list[str], weight: int) -> int:
    if text == normalized_query:
        return weight * 8
    score = weight * 3 if normalized_query in text else 0
    matched = sum(1 for token in tokens if token in text)
    if matched:
        score += weight * matched
        if matched == len(tokens):
            score += weight * 2
    return score


def _snippet(value: Any, *, limit: int = 140) -> str:
    if isinstance(value, (list, tuple, set)):
        raw = " ".join(str(item) for item in value if item is not None)
    elif isinstance(value, dict):
        raw = " ".join(f"{key}={item}" for key, item in value.items())
    else:
        raw = "" if value is None else str(value)
    compact = " ".join(raw.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)].rstrip() + "..."
