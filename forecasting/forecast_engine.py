"""Deterministic forecast-engine heuristics for local backtest replay."""

from __future__ import annotations

import math
from typing import Any


MARKET_EXTREMIZATION = 1.35
GENERAL_EXTREMIZATION = 1.10
EVIDENCE_LOGIT_NUDGE = 0.15


def forecast_engine_binary_probability(case: dict[str, Any]) -> dict[str, Any] | None:
    """Generate a binary forecast from pre-cutoff case inputs.

    This is intentionally deterministic and local. It uses explicit baselines,
    reference-class base rates, and evidence stance metadata, but never reads the
    dataset's generated ``probability`` field. That makes it suitable for
    benchmark replay plumbing without pretending an LLM produced the number.
    """

    components = _components(case)
    if not components:
        components = [{"name": "naive", "probability": 0.5, "weight": 1.0}]

    weighted_sum = sum(row["probability"] * row["weight"] for row in components)
    total_weight = sum(row["weight"] for row in components)
    if total_weight <= 0:
        return None

    probability = weighted_sum / total_weight
    evidence_nudge = _evidence_nudge(case)
    has_market_or_crowd = any(row["name"] in {"market", "crowd"} for row in components)
    scale = MARKET_EXTREMIZATION if has_market_or_crowd else GENERAL_EXTREMIZATION
    probability = _sigmoid(_logit(probability) * scale + evidence_nudge)

    return {
        "probability": round(min(max(probability, 0.01), 0.99), 6),
        "components": components,
        "evidence_nudge": evidence_nudge,
        "extremization": scale,
    }


def _components(case: dict[str, Any]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    for baseline in case.get("baselines") or []:
        if not isinstance(baseline, dict):
            continue
        probability = _optional_probability(baseline.get("probability"))
        if probability is None:
            continue
        baseline_type = str(baseline.get("baseline_type") or "imported")
        source = str(baseline.get("source") or baseline_type)
        if baseline_type in {"naive_0_5", "uniform"}:
            continue
        name = "market" if baseline_type == "market" else "crowd" if baseline_type == "crowd" else baseline_type
        components.append(
            {
                "name": name,
                "source": source,
                "probability": probability,
                "weight": _component_weight(baseline_type),
            }
        )

    base_rate = case.get("base_rate", case.get("base_rate_probability"))
    base_rate_probability = _optional_probability(base_rate)
    if base_rate_probability is not None and not any(row["name"] == "base_rate" for row in components):
        components.append(
            {
                "name": "base_rate",
                "source": "dataset",
                "probability": base_rate_probability,
                "weight": 2.0,
            }
        )
    return components


def _component_weight(baseline_type: str) -> float:
    if baseline_type in {"market", "crowd"}:
        return 4.0
    if baseline_type == "base_rate":
        return 2.0
    if baseline_type == "prior_agent":
        return 1.5
    return 1.0


def _evidence_nudge(case: dict[str, Any]) -> float:
    score = 0
    for item in case.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        stance = str(item.get("stance") or "").strip().lower()
        if stance == "increases":
            score += 1
        elif stance == "decreases":
            score -= 1
    return max(min(score * EVIDENCE_LOGIT_NUDGE, 0.45), -0.45)


def _optional_probability(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        probability = float(value)
    elif isinstance(value, str):
        try:
            probability = float(value)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        return None
    return probability


def _logit(probability: float) -> float:
    probability = min(max(probability, 1e-6), 1 - 1e-6)
    return math.log(probability / (1 - probability))


def _sigmoid(value: float) -> float:
    return 1 / (1 + math.exp(-value))
