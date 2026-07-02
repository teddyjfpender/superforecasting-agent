"""Question machine-readiness composite for the operator's Desk.

The operator's insight: a forecast question carries hidden machine-workability
parameters — the watched sources the desk can refresh, the structured ensemble
components a reforecast can move, the reference classes for the outside view, an
EXECUTABLE update trigger (source_ref + operator + numeric threshold), an ENABLED
scheduled review, and the resolution scaffolding (close_time, impact, resolution
rule). When these are missing the autonomous desk is literally lacking the inputs
it needs to keep the forecast alive — and nothing on the surface shows it.

This module scores that readiness 0-100 and, for every unmet dimension, emits a
gap with an EXACT operator fix hint. The scorer is a PURE function of values the
desk payload already holds in memory (or fetches ONCE, batched) — no per-question
query lives in :func:`question_machine_readiness`; the batched counts are supplied
by the caller (``build_workspace_payload``). :func:`build_question_readiness` is
the single-question convenience the ``forecast.question.readiness`` RPC uses.
"""

from __future__ import annotations

from typing import Any

# Dimension weights (sum to 100). The autonomy-critical trio — the watched sources
# the desk refreshes, the structured components a reforecast moves, and the enabled
# schedule that FIRES that reforecast — carry the heaviest weight, because without
# them the autonomous loop cannot run at all. The reference class + executable
# trigger are the next tier (the outside view + the machine-fireable alert), then
# the resolution scaffolding (close_time / impact / resolution rule) is table
# stakes but cheap to set.
READINESS_WEIGHTS: dict[str, int] = {
    "watches": 20,
    "components": 20,
    "scheduled": 18,
    "ref_classes": 12,
    "triggers": 12,
    "close_time": 6,
    "impact": 6,
    "resolution_rule": 6,
}

READINESS_LABELS: dict[str, str] = {
    "watches": "watched sources",
    "components": "structured components",
    "scheduled": "enabled review schedule",
    "ref_classes": "reference classes",
    "triggers": "executable update trigger",
    "close_time": "close time",
    "impact": "impact",
    "resolution_rule": "resolution rule",
}


def has_executable_trigger(update_triggers: Any) -> bool:
    """True when ANY trigger is machine-fireable — i.e. carries a ``source_ref``, an
    ``operator`` in :data:`forecasting.models.TRIGGER_OPERATORS`, and a numeric
    ``threshold``. Mirrors :func:`forecasting.models.evaluate_update_triggers`'
    executability test (parsed in memory off the question row — no query)."""
    from forecasting.models import TRIGGER_OPERATORS

    for trigger in update_triggers or []:
        if not isinstance(trigger, dict):
            continue
        threshold = trigger.get("threshold")
        if (
            trigger.get("source_ref")
            and trigger.get("operator") in TRIGGER_OPERATORS
            and isinstance(threshold, (int, float))
            and not isinstance(threshold, bool)
        ):
            return True
    return False


def _is_set(value: Any) -> bool:
    """A field counts as 'set' when it is a non-None, non-blank value."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def _fix_hint(key: str, question_id: str) -> str:
    """The EXACT operator fix for an unmet dimension — a concrete command where a
    clean CLI path exists, and ALWAYS 'or a T task' (a Desk task job, the free-text
    fix loop) as the universal fallback the operator can dispatch from the desk."""
    qid = question_id
    hints = {
        "watches": (
            f"no watched sources — `forecast watch add <source> --question {qid}` "
            f"(see `forecast sources`), or a T task"
        ),
        "components": (
            "current snapshot has no structured ensemble_components — reforecast so "
            "the estimate decomposes into named drivers (Desk U), or a T task"
        ),
        "scheduled": (
            f"no enabled scheduled review — `forecast schedule add --question {qid} "
            f"--cadence weekly`, or a T task"
        ),
        "ref_classes": (
            f"no active reference class — `forecast base-rate {qid} --name <class> "
            f"--base-rate <p>`, or a T task"
        ),
        "triggers": (
            f"no executable update trigger — `forecast set-decision {qid} "
            f"--update-trigger '{{\"mechanism\":\"...\",\"source_ref\":\"fred:CPIAUCSL\","
            f"\"operator\":\">\",\"threshold\":3.0}}'`, or a T task"
        ),
        "close_time": (
            "close_time not set — set it in the question settings, or a T task"
        ),
        "impact": (
            "impact not set — set it in the question settings, or a T task"
        ),
        "resolution_rule": (
            "resolution rule missing — set the resolution criteria in the question "
            "settings, or a T task"
        ),
    }
    return hints[key]


def question_machine_readiness(
    *,
    question_id: str,
    watch_count: int,
    has_components: bool,
    ref_class_count: int,
    update_triggers: Any,
    has_scheduled_review: bool,
    close_time: Any,
    impact: Any,
    resolution_rule: Any,
) -> dict[str, Any]:
    """Score a question's machine-readiness 0-100 and list its gaps.

    PURE: every input is a value the caller already holds (the batched counts +
    in-memory question/snapshot fields). Returns ``{score, gaps}`` where each gap
    is ``{key, label, fix_hint}`` for an UNMET dimension, in weight order.
    """
    met = {
        "watches": int(watch_count or 0) > 0,
        "components": bool(has_components),
        "scheduled": bool(has_scheduled_review),
        "ref_classes": int(ref_class_count or 0) > 0,
        "triggers": has_executable_trigger(update_triggers),
        "close_time": _is_set(close_time),
        "impact": _is_set(impact),
        "resolution_rule": _is_set(resolution_rule),
    }
    score = sum(weight for key, weight in READINESS_WEIGHTS.items() if met[key])
    gaps = [
        {"key": key, "label": READINESS_LABELS[key], "fix_hint": _fix_hint(key, question_id)}
        for key in READINESS_WEIGHTS
        if not met[key]
    ]
    return {"score": score, "gaps": gaps}


def build_question_readiness(ledger: Any, question_id: str) -> dict[str, Any]:
    """Full machine-readiness composite for ONE question (the settings-modal RPC).

    Fetches the single-question values directly (this is not the batched book path,
    so a handful of per-question reads is correct here) and returns the composite
    plus ``question_id``/``title`` for display. Raises through ``ledger.get_question``
    when the id is unknown."""
    question = ledger.get_question(question_id)
    try:
        snapshot = ledger.get_current_snapshot(question_id)
    except Exception:  # noqa: BLE001 — a missing snapshot just means no components
        snapshot = None
    components = getattr(snapshot, "ensemble_components", None)
    has_components = bool(components) if isinstance(components, dict) else False

    watch_count = len(
        ledger.list_watched_sources(
            scope_type="question", scope_ref=question_id, status="active"
        )
    )
    ref_class_count = len(
        [rc for rc in ledger.list_reference_classes(question_id) if rc.get("status") == "active"]
    )
    has_scheduled_review = question_id in ledger.next_review_by_question()

    composite = question_machine_readiness(
        question_id=question_id,
        watch_count=watch_count,
        has_components=has_components,
        ref_class_count=ref_class_count,
        update_triggers=list(question.update_triggers or []),
        has_scheduled_review=has_scheduled_review,
        close_time=question.close_time,
        impact=question.impact,
        resolution_rule=question.resolution_criteria,
    )
    composite["question_id"] = question_id
    composite["title"] = question.title
    composite["src_count"] = watch_count
    return composite
