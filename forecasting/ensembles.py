"""Forecast ensemble helpers."""

from __future__ import annotations

import math
from typing import Any

from forecasting.models import ValidationError


def weighted_binary_probability(components: dict[str, Any]) -> float | None:
    """Return a weighted binary probability from component specs.

    Supported shapes:

    - ``{"base_rate": {"probability": 0.4, "weight": 2}}``
    - ``{"components": [{"name": "base_rate", "probability": 0.4, "weight": 2}]}``

    Returns ``None`` when no usable components are supplied.
    """

    rows = _component_rows(components)
    if not rows:
        return None
    weighted_sum = 0.0
    total_weight = 0.0
    for row in rows:
        probability = _coerce_probability(row.get("probability"))
        weight = _coerce_weight(row.get("weight", 1.0))
        weighted_sum += probability * weight
        total_weight += weight
    if total_weight <= 0:
        raise ValidationError("ensemble component weights must sum to a positive value")
    return weighted_sum / total_weight


def bayesian_binary_update(
    *,
    prior: float,
    likelihood_if_true: float,
    likelihood_if_false: float,
) -> float:
    """Return ``P(true | evidence)`` for a binary hypothesis."""

    prior = _coerce_probability(prior)
    likelihood_if_true = _coerce_probability(likelihood_if_true)
    likelihood_if_false = _coerce_probability(likelihood_if_false)
    numerator = likelihood_if_true * prior
    denominator = numerator + likelihood_if_false * (1.0 - prior)
    if denominator <= 0:
        raise ValidationError("Bayesian update denominator must be positive")
    return numerator / denominator


def _component_rows(components: dict[str, Any]) -> list[dict[str, Any]]:
    if not components:
        return []
    if isinstance(components.get("components"), list):
        return [row for row in components["components"] if isinstance(row, dict)]
    rows = []
    for name, value in components.items():
        if isinstance(value, dict) and "probability" in value:
            row = dict(value)
            row.setdefault("name", name)
            rows.append(row)
    return rows


def _coerce_probability(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValidationError("ensemble component probability must be numeric")
    value = float(raw)
    if not math.isfinite(value) or not (0 <= value <= 1):
        raise ValidationError("ensemble component probability must be between 0 and 1")
    return value


def _coerce_weight(raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValidationError("ensemble component weight must be numeric")
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise ValidationError("ensemble component weight must be non-negative")
    return value
