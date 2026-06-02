"""Helpers that turn reviewed calibration memory into forecast adjustments."""

from __future__ import annotations

import math
from typing import Any

from forecasting.ledger import ForecastLedger

LEARNING_REVIEW_REASONS = frozenset(
    {
        "calibration_lesson_review",
        "domain_error_profile_review",
    }
)
LEARNED_ERROR_REVIEW_PREFIX = "domain_error_profile_applies:"


def is_learned_error_review_reason(reason: str | None) -> bool:
    return str(reason or "").startswith(LEARNED_ERROR_REVIEW_PREFIX)


def learned_error_profile_id(reason: str | None) -> str | None:
    text = str(reason or "")
    if not text.startswith(LEARNED_ERROR_REVIEW_PREFIX):
        return None
    profile_id = text[len(LEARNED_ERROR_REVIEW_PREFIX) :].strip()
    return profile_id or None


def is_learning_review_reason(reason: str | None) -> bool:
    text = str(reason or "")
    return text in LEARNING_REVIEW_REASONS or is_learned_error_review_reason(text)


def apply_active_lesson_adjustments(
    *,
    ledger: ForecastLedger,
    question: Any,
    payload: Any,
    calibration_lesson_refs: list[str],
    calibration_adjustment: dict[str, Any],
) -> tuple[Any, list[str], dict[str, Any]]:
    """Attach active lessons for a question and apply supported adjustments.

    Supported numeric adjustment keys are deliberately small and explicit:
    ``probability_delta`` adjusts the probability directly, while
    ``logit_shift`` applies a shift in log-odds space. Unsupported keys remain
    preserved inside the lesson but do not silently affect a saved probability.
    """

    lessons = active_lessons_for_question(ledger, question)
    existing_refs = set(calibration_lesson_refs)
    selected = [lesson for lesson in lessons if lesson["id"] not in existing_refs]
    if not selected:
        return payload, calibration_lesson_refs, calibration_adjustment

    refs = calibration_lesson_refs + [lesson["id"] for lesson in selected]
    adjustment = dict(calibration_adjustment)
    applied_lessons = []
    probability_delta = 0.0
    logit_shift = 0.0
    logit_scale = 1.0
    for lesson in selected:
        recommended = dict(lesson.get("recommended_adjustment") or {})
        item = {
            "id": lesson["id"],
            "scope_type": lesson.get("scope_type"),
            "scope_ref": lesson.get("scope_ref"),
        }
        delta = _optional_float(recommended.get("probability_delta"))
        if delta is not None:
            probability_delta += delta
            item["probability_delta"] = delta
        shift = _optional_float(recommended.get("logit_shift"))
        if shift is not None:
            logit_shift += shift
            item["logit_shift"] = shift
        # Base-rate-neutral confidence rescale (sharpen >1 / flatten <1) around
        # 0.5. Emitted by the signed-calibration-bias loop instead of a shift so
        # a confidence correction never chases the realized yes/no base rate.
        scale = _optional_float(recommended.get("logit_scale"))
        if scale is not None and scale > 0:
            logit_scale *= scale
            item["logit_scale"] = scale
        applied_lessons.append(item)

    if applied_lessons:
        adjustment["applied_active_lessons"] = applied_lessons

    if isinstance(payload, bool) or not isinstance(payload, (int, float)):
        return payload, refs, adjustment

    adjusted = float(payload)
    changed = False
    if probability_delta:
        adjusted += probability_delta
        adjustment["applied_probability_delta"] = probability_delta
        changed = True
    if logit_shift:
        adjusted = _sigmoid(_logit(adjusted) + logit_shift)
        adjustment["applied_logit_shift"] = logit_shift
        changed = True
    if logit_scale != 1.0:
        adjusted = _sigmoid(_logit(adjusted) * logit_scale)
        adjustment["applied_logit_scale"] = logit_scale
        changed = True
    if changed:
        adjustment["raw_probability"] = float(payload)
        payload = round(min(max(adjusted, 0.01), 0.99), 6)
    return payload, refs, adjustment


def active_lessons_for_question(ledger: ForecastLedger, question: Any) -> list[dict[str, Any]]:
    scopes: list[tuple[str, str | None]] = [("global", None)]
    if question.domain:
        scopes.append(("domain", question.domain))
    for topic in question.topics:
        scopes.append(("topic", topic))
    if question.outcome_space.type:
        scopes.append(("question_type", question.outcome_space.type))

    lessons: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope_type, scope_ref in scopes:
        for lesson in ledger.list_calibration_lessons(
            scope_type=scope_type,
            scope_ref=scope_ref,
            active_only=True,
        ):
            if lesson["id"] in seen:
                continue
            seen.add(lesson["id"])
            lessons.append(lesson)
    return lessons


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))
