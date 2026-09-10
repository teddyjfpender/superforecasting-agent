"""Helpers that turn reviewed calibration memory into forecast adjustments."""

from __future__ import annotations

import math
from typing import Any

from forecasting.bayes_toolkit import inv_logit, logit as _bayes_logit, platt_scale
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


def should_apply_active_lessons(
    use_active_lessons: bool | None, forecast_origin: str | None
) -> bool:
    """Decide whether to auto-apply active calibration-lesson adjustments.

    The ledger's learned calibration correction is DERIVED FROM THE LIVE STRATUM
    (``synthesize_bias_lessons`` measures ``forecast_origin='live'`` only), so it
    is DEFAULT-ON for ``live`` commits only. ``backtest`` / ``imported_baseline``
    commits are NEVER auto-adjusted — folding a live-derived correction into a
    closed-book backtest would contaminate the very benchmark that grounds
    ``can_claim_live_superforecasting``. Those origins apply lessons ONLY on an
    explicit opt-in. ``exploratory`` commits are never adjusted (they are not
    calibration-scored, so a correction would be noise).

    ``use_active_lessons`` is tri-state:
      * ``None``  — unset; use the origin default (on for live, off otherwise);
      * ``True``  — explicit opt-in (adjust even a backtest/imported commit);
      * ``False`` — explicit opt-out (commit the raw number).
    """

    origin = (forecast_origin or "live").strip().lower()
    if origin == "exploratory":
        return False
    if use_active_lessons is None:
        return origin == "live"
    return bool(use_active_lessons)


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
    # Global and domain bias reports share outcomes (and the global prior).
    # Consult both, but apply only the most specific learned numeric correction.
    bias_scales = [
        lesson for lesson in selected
        if (lesson.get("metadata") or {}).get("source") == "calibration_bias"
        and (lesson.get("recommended_adjustment") or {}).get("basis") == "signed_calibration_error"
        and (_optional_float((lesson.get("recommended_adjustment") or {}).get("logit_scale")) or 0) > 0
    ]
    chosen_bias = max(
        bias_scales,
        key=lambda lesson: (
            lesson.get("scope_type") == "domain",
            lesson.get("created_at") or "",
            lesson["id"],
        ),
        default=None,
    )
    for lesson in selected:
        recommended = dict(lesson.get("recommended_adjustment") or {})
        item = {
            "id": lesson["id"],
            "scope_type": lesson.get("scope_type"),
            "scope_ref": lesson.get("scope_ref"),
        }
        if lesson in bias_scales and lesson is not chosen_bias:
            item["numeric_adjustment_skipped"] = "more_specific_calibration_bias_applied"
            applied_lessons.append(item)
            continue
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
        # Additive log-odds shift: inv_logit(logit(p) + shift). This is
        # platt_scale with alpha=1 and d=exp(shift); we keep it as an explicit
        # shift for readability (and to avoid an exp round-trip).
        adjusted = inv_logit(_bayes_logit(adjusted) + logit_shift)
        adjustment["applied_logit_shift"] = logit_shift
        changed = True
    if logit_scale != 1.0:
        # Base-rate-neutral confidence rescale around 0.5 == the desk's single
        # recalibration kernel platt_scale(p, alpha=logit_scale, d=1.0). The legacy
        # private operator was _sigmoid(_logit(p)*scale) where _logit clamped p to
        # 1e-6; platt_scale's logit clamps to 1e-9, so we PRE-CLAMP to 1e-6 here to
        # stay byte-identical to the legacy operator even at exact-0/1 boundary inputs.
        adjusted = platt_scale(min(max(adjusted, 1e-6), 1.0 - 1e-6), alpha=logit_scale, d=1.0)
        adjustment["applied_logit_scale"] = logit_scale
        changed = True
    if changed:
        adjustment["raw_probability"] = float(payload)
        payload = round(min(max(adjusted, 0.01), 0.99), 6)
    return payload, refs, adjustment


def _canonical_question_type(question: Any) -> str | None:
    """A candidate-SHARE distribution (vote share) is the sub-type the share-
    compression + scoreability lessons target. It is a `distribution` outcome that
    carries named choices (candidates); a continuous numeric distribution has none.
    Surfacing it as an extra question_type scope lets a lesson scoped
    `question_type:vote-share-distribution` match a `distribution` vote-share
    question — without matching continuous distributions."""
    osp = getattr(question, "outcome_space", None)
    if osp is not None and getattr(osp, "type", None) == "distribution" and getattr(osp, "choices", None):
        return "vote-share-distribution"
    return None


def _in_scope_lessons(ledger: ForecastLedger, question: Any) -> list[dict[str, Any]]:
    scopes: list[tuple[str, str | None]] = [("global", None)]
    if question.domain:
        scopes.append(("domain", question.domain))
    for topic in question.topics:
        scopes.append(("topic", topic))
        if question.domain:
            # domain_topic lessons are stored colon-joined ("politics:nyc-primaries"),
            # the form lesson_scope_to_applies_to parses — so a lesson scoped to a
            # domain+topic matches a question carrying that domain AND that topic.
            scopes.append(("domain_topic", f"{question.domain}:{topic}"))
    if question.outcome_space.type:
        scopes.append(("question_type", question.outcome_space.type))
    _canonical = _canonical_question_type(question)
    if _canonical:
        scopes.append(("question_type", _canonical))

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


def active_lessons_for_question(ledger: ForecastLedger, question: Any) -> list[dict[str, Any]]:
    """Use explicit in-scope supersession, never guess precedence from prose.

    A narrower replacement only supersedes the old lesson where both match;
    invalidated/inactive replacements cannot suppress an otherwise active lesson.
    """
    lessons = _in_scope_lessons(ledger, question)
    superseded = {item.get("supersedes_lesson_id") for item in lessons}
    return [item for item in lessons if item["id"] not in superseded]


def lesson_scope_to_applies_to(lesson: dict[str, Any]) -> dict[str, Any]:
    """Force-stamp a lesson's enforcement scope from its OWN scope_type/scope_ref —
    never from author-supplied applies_to — so a domain:politics lesson can only
    ever match politics forecasts (no scope-widening attack)."""
    scope_type = lesson.get("scope_type")
    scope_ref = lesson.get("scope_ref")
    if scope_type == "domain" and scope_ref:
        return {"domain": [scope_ref]}
    if scope_type == "domain_topic" and scope_ref:
        # best-effort: match the domain prefix ("politics:elections:primaries" -> politics)
        return {"domain": [str(scope_ref).split(":", 1)[0]]}
    if scope_type == "question_type" and scope_ref:
        # The canonical 'vote-share-distribution' sub-type maps to the REAL outcome
        # type 'distribution' (a vote-share question's actual type) so the force-
        # stamped applies_to matches the commit context's outcome_type. Retrieval has
        # already scoped the lesson to candidate-share distributions, so a continuous
        # distribution never retrieves it -> this never over-applies.
        real_type = "distribution" if scope_ref == "vote-share-distribution" else scope_ref
        return {"outcome_type": [real_type]}
    # global / topic: no DSL applies_to dimension — applies broadly; the rule's own
    # check predicate is responsible for self-limiting.
    return {}


def compile_lesson_rules(ledger: ForecastLedger, question: Any) -> list[Any]:
    """Compile active in-scope calibration lessons that carry a ``rule`` (a RuleSpec
    fragment under ``recommended_adjustment['rule']``) into enforceable SimpleRules.

    This is what makes a STRUCTURAL/process lesson (not just a numeric bias) actually
    bite at commit: the rule's check predicate is evaluated against the candidate
    forecast's real signals. The rule id is namespaced ``lesson:<lesson_id>`` (so the
    coverage audit can attribute firings and the override-floor can protect it) and
    its ``applies_to`` is force-stamped from the lesson's own scope. A rule that fails
    validation is skipped (a broken lesson must never brick a commit)."""
    try:
        from forecasting.hooks.dsl import RuleSpec, compile_rule, validate_rule
    except Exception:
        return []
    compiled: list[Any] = []
    known: set[str] = set()
    for lesson in active_lessons_for_question(ledger, question):
        recommended = lesson.get("recommended_adjustment") or {}
        rule = recommended.get("rule")
        if not isinstance(rule, dict) or not isinstance(rule.get("check"), dict):
            continue
        spec_dict = dict(rule)
        spec_dict["id"] = f"lesson:{lesson['id']}"
        spec_dict["applies_to"] = lesson_scope_to_applies_to(lesson)  # never author-supplied
        spec = RuleSpec.from_dict(spec_dict)
        if any(issue.severity == "error" for issue in validate_rule(spec, known_ids=known)):
            continue
        known.add(spec.id)
        compiled.append(compile_rule(spec))
    return compiled


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


def lesson_application_decisions(ledger, question, payload, adjustment, refs, rule_report):
    """Explain actual commit behavior; a successful commit is not rule compliance.

    Keep the verdict and source IDs on the immutable snapshot so later lesson
    edits cannot rewrite what the agent used. Advisory consultation is distinct
    from a numerical adjustment or a successfully evaluated rule.
    """
    adjustment = adjustment or {}
    items = {i.get("id"): i for i in adjustment.get("applied_active_lessons", []) if isinstance(i, dict)}
    verdicts = {v["rule_id"]: v for v in rule_report.get("verdicts", [])}
    raw = _optional_float(adjustment.get("raw_probability"))
    value = _optional_float(payload)
    decisions = []
    candidates = _in_scope_lessons(ledger, question)
    superseded = {item.get("supersedes_lesson_id"): item["id"] for item in candidates}
    for lesson in candidates:
        lid = lesson["id"]
        recommended = lesson.get("recommended_adjustment") or {}
        item = items.get(lid, {})
        if isinstance(recommended.get("rule"), dict):
            kind = "rule"
            verdict = verdicts.get(f"lesson:{lid}")
            applied = bool(verdict and verdict.get("passed"))
            reason = "rule_passed" if applied else ("rule_failed" if verdict else "rule_not_evaluated")
        elif any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")):
            kind = "numeric"
            skipped = item.get("numeric_adjustment_skipped")
            applied = bool(item and not skipped and raw is not None and value is not None and abs(value - raw) > 1e-9)
            reason = skipped or ("numeric_adjustment_applied" if applied else "no_numeric_change")
        else:
            kind, applied = "advisory", False
            reason = "consulted_advisory" if lid in refs else "not_recorded_as_consulted"
        if lid in superseded:
            applied, reason = False, f"superseded_by:{superseded[lid]}"
        decisions.append({
            "lesson_id": lid, "kind": kind, "applied": applied, "reason": reason,
            "consulted": lid in refs, "scope_type": lesson.get("scope_type"),
            "scope_ref": lesson.get("scope_ref"), "lesson_updated_at": lesson.get("updated_at"),
            "source_score_record_refs": list(lesson.get("source_score_record_refs") or []),
            "source_postmortem_refs": list(lesson.get("source_postmortem_refs") or []),
        })
    return decisions
