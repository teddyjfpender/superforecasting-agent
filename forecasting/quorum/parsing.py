"""Quorum response parsing + belief-trajectory coercion (carved from ``quorum.py``).

The Wave-4 §W3.a ``parsing`` leaf: ``parse_panelist_response`` /
``parse_judge_response`` and the ``_opt_*`` / ``_coerce_*`` / belief-trajectory
coercion helpers that turn raw model text into :class:`ModelForecast` /
:class:`JudgeSynthesis`. Imported back into :mod:`forecasting.quorum.core` (the
parsers ``run_quorum`` calls, plus the ``__all__`` surface) and re-exported by
the package façade, so ``from forecasting.quorum import parse_panelist_response``
is byte-for-byte unchanged.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from forecasting.agent_protocol import parse_agent_protocol_response
from forecasting.models import ValidationError
from forecasting.quorum.core import (
    DirectionalConfidence,
    JudgeSynthesis,
    ModelForecast,
    _VALID_DIRECTIONAL_CONFIDENCE,
)

# ── Parsing ──────────────────────────────────────────────────────────────────


def parse_panelist_response(response: Any, model: str) -> ModelForecast:
    """Parse one panelist's JSON response into a :class:`ModelForecast`.

    Reuses the robust JSON extraction from :mod:`agent_protocol` (handles
    fenced blocks and surrounding prose). Raises :class:`ValidationError` with
    the model name on a bad response so the caller can record it as an errored
    panelist rather than aborting the whole quorum.
    """

    try:
        parsed = parse_agent_protocol_response(response)
    except ValueError as exc:
        raise ValidationError(f"{model}: {exc}") from exc
    payload = _reparse_full(response)
    trajectory = _parse_belief_trajectory(payload.get("belief_trajectory"))
    # BLF A1: the final belief IS the commit. When the panelist emitted a belief
    # trajectory, its last step's probability is the committed number (the belief the
    # evidence walked to); absent a trajectory, the top-level ``probability`` stands.
    committed = float(parsed["probability"])
    if trajectory and trajectory[-1].get("probability") is not None:
        committed = float(trajectory[-1]["probability"])
    return ModelForecast(
        model=model,
        probability=committed,
        confidence_low=_opt_prob(payload.get("confidence_low")),
        confidence_high=_opt_prob(payload.get("confidence_high")),
        rationale=str(parsed.get("rationale") or ""),
        reasons_up=_str_list(payload.get("reasons_up")),
        reasons_down=_str_list(payload.get("reasons_down")),
        change_my_mind=_str_list(payload.get("change_my_mind")),
        crux=(str(payload["crux"]).strip() if payload.get("crux") else None),
        belief_trajectory=trajectory,
    )


def parse_judge_response(response: Any, judge_model: str | None) -> JudgeSynthesis:
    payload = _reparse_full(response)
    prob = _opt_prob(payload.get("probability"))
    return JudgeSynthesis(
        probability=prob,
        rationale=str(payload.get("rationale") or "").strip(),
        reasons_up=_str_list(payload.get("reasons_up")),
        reasons_down=_str_list(payload.get("reasons_down")),
        change_my_mind=_str_list(payload.get("change_my_mind")),
        blind_spots=_str_list(payload.get("blind_spots")),
        consensus=_str_list(payload.get("consensus")),
        contradictions=_str_list(payload.get("contradictions")),
        judge_model=judge_model,
        directional_confidence=_normalize_confidence(
            payload.get("directional_confidence")
        ),
        information_gap=_coerce_bool(payload.get("information_gap")),
        clarifying_queries=_str_list(payload.get("clarifying_queries")),
        market_deviation_justification=_opt_justification(
            payload.get("market_deviation_justification")
        ),
    )


def _opt_justification(value: Any) -> str | None:
    """Coerce the judge's market-deviation justification to a clean string or None.

    An empty/whitespace/garbage value collapses to ``None`` (the no-justification
    state) so a blank field can never be read as a real named edge — a large
    deviation with an empty justification is pulled toward the market.
    """

    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _coerce_bool(value: Any) -> bool:
    """Tolerant truthy parse for the judge's information_gap flag.

    Accepts a real bool, common string tokens (``true``/``yes``/``1``), or a
    number; anything missing/garbage collapses to ``False`` (the non-triggering
    default) so a malformed judge response can never spuriously start a research
    round.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # NaN != 0 is True; guard it so garbage collapses to False as intended.
        return value == value and value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "y", "1"}
    return False


def _normalize_confidence(value: Any) -> DirectionalConfidence:
    """Coerce a judge's self-reported confidence to a valid label.

    Tolerant by design: any missing/unknown/garbage value collapses to
    ``'medium'`` — the non-overriding default — so a malformed judge response
    can never accidentally trip the override gate.
    """

    if isinstance(value, str):
        token = value.strip().lower()
        if token in _VALID_DIRECTIONAL_CONFIDENCE:
            return token  # type: ignore[return-value]
    return "medium"


def _reparse_full(response: Any) -> dict[str, Any]:
    """Get the full JSON object (agent_protocol's parser keeps only some keys)."""

    from forecasting.agent_protocol import _coerce_json_response

    try:
        return _coerce_json_response(response)
    except ValueError:
        return {}


def _text_has_json_object(text: str) -> bool:
    """True when ``text`` carries a parseable JSON object (fenced/prose-embedded)."""

    if not text:
        return False
    from forecasting.agent_protocol import _coerce_json_response

    try:
        _coerce_json_response(text)
        return True
    except ValueError:
        return False


def _assemble_response_text(result: Mapping[str, Any]) -> str:
    """Best text to parse from a successful agent result.

    A reasoning model sometimes emits the structured answer INSIDE its thinking
    trace and leaves the visible final message empty (or as prose), so when the
    visible ``final_response`` carries no parseable JSON object we fall back to the
    ``last_reasoning`` trace. This NEVER fabricates: if neither the visible message
    nor the reasoning carries a JSON object, the visible text is returned verbatim
    so the downstream parser still errors honestly (empty vs prose).
    """

    final = str(result.get("final_response") or "").strip()
    if _text_has_json_object(final):
        return final
    reasoning = str(result.get("last_reasoning") or "").strip()
    if reasoning and _text_has_json_object(reasoning):
        return reasoning
    return final or reasoning


def _opt_prob(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(p) or not 0.0 <= p <= 1.0:
        return None
    return p


def _str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


def _belief_step(raw: Any, index: int) -> dict[str, Any] | None:
    """Normalize one linguistic-belief-state step (BLF A1) into the recorded schema.

    Returns ``{step, probability, confidence, evidence_for, evidence_against,
    open_questions, moved_by}`` — the belief slot plus the one-line ``moved_by``
    naming the evidence that moved the number. A step with no parseable probability
    is dropped (a belief revision without a number is not a revision); ``step``
    falls back to the 1-based position when the model omitted it. Tolerant by
    design so a malformed step can never abort the whole panelist parse."""

    if not isinstance(raw, Mapping):
        return None
    probability = _opt_prob(raw.get("probability"))
    if probability is None:
        probability = _opt_prob(raw.get("p"))
    if probability is None:
        return None
    try:
        step = int(raw.get("step"))
    except (TypeError, ValueError):
        step = index + 1
    confidence = raw.get("confidence")
    return {
        "step": step,
        "probability": probability,
        "confidence": str(confidence).strip().lower() if confidence else None,
        "evidence_for": _str_list(raw.get("evidence_for")),
        "evidence_against": _str_list(raw.get("evidence_against")),
        "open_questions": _str_list(raw.get("open_questions")),
        "moved_by": (str(raw.get("moved_by")).strip() if raw.get("moved_by") else None),
    }


def _parse_belief_trajectory(raw: Any) -> list[dict[str, Any]]:
    """The ordered belief trajectory (BLF A1) from a panelist payload.

    Returns a list of normalized belief steps; ``[]`` when the field is absent or
    carries nothing parseable — so a legacy/stub response with no trajectory yields
    an empty trajectory and the committed number stands alone (byte-compatible)."""

    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        step = _belief_step(item, index)
        if step is not None:
            out.append(step)
    return out
