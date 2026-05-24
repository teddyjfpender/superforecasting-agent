"""Forecast ensemble helpers."""

from __future__ import annotations

import math
from datetime import datetime
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


def linear_trend_projection(
    series: list[Any],
    *,
    target_date: str | None = None,
    target_x: float | None = None,
    date_field: str = "date",
    value_field: str = "value",
) -> dict[str, Any]:
    """Project a numeric series with an ordinary least-squares trend.

    Rows may be ``{"date": "2026-01-01", "value": 10}``,
    ``{"x": 0, "value": 10}``, or two-item ``[x, value]`` pairs. Date rows use
    elapsed days from the first observation as ``x``.
    """

    points = _trend_points(series, date_field=date_field, value_field=value_field)
    if len(points) < 2:
        raise ValidationError("trend_projection requires at least two numeric observations")
    if target_date and target_x is not None:
        raise ValidationError("trend_projection accepts target_date or target_x, not both")

    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator <= 0:
        raise ValidationError("trend_projection requires observations with varying x values")

    slope = sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
    intercept = y_mean - slope * x_mean
    residuals = [y - (intercept + slope * x) for x, y in points]
    residual_sum_squares = sum(value**2 for value in residuals)
    total_sum_squares = sum((y - y_mean) ** 2 for y in ys)
    r_squared = 1.0 if total_sum_squares == 0 else 1.0 - residual_sum_squares / total_sum_squares
    residual_std = math.sqrt(residual_sum_squares / max(len(points) - 2, 1))

    first_date = _first_observation_date(series, date_field=date_field)
    projected_x = _trend_target_x(
        target_date=target_date,
        target_x=target_x,
        first_date=first_date,
        fallback=max(xs),
    )
    projected_value = intercept + slope * projected_x

    return {
        "count": len(points),
        "intercept": intercept,
        "slope": slope,
        "slope_unit": "per_day" if first_date else "per_step",
        "r_squared": r_squared,
        "residual_std": residual_std,
        "latest_x": xs[-1],
        "latest_value": ys[-1],
        "target_x": projected_x,
        "target_date": target_date,
        "projected_value": projected_value,
    }


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


def _trend_points(series: list[Any], *, date_field: str, value_field: str) -> list[tuple[float, float]]:
    first_date = _first_observation_date(series, date_field=date_field)
    points: list[tuple[float, float]] = []
    for index, row in enumerate(series):
        x_raw: Any
        y_raw: Any
        if isinstance(row, dict):
            y_raw = row.get(value_field)
            x_raw = row.get("x")
            if x_raw is None:
                date_raw = row.get(date_field)
                x_raw = _days_since_first(date_raw, first_date) if first_date else index
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            x_raw, y_raw = row[0], row[1]
        else:
            raise ValidationError("trend_projection observations must be objects or [x, value] pairs")
        points.append(
            (
                _coerce_finite_number(x_raw, "trend_projection x"),
                _coerce_finite_number(y_raw, "trend_projection value"),
            )
        )
    return points


def _first_observation_date(series: list[Any], *, date_field: str) -> datetime | None:
    for row in series:
        if isinstance(row, dict) and row.get(date_field):
            return _parse_iso_datetime(row[date_field], field_name=date_field)
    return None


def _trend_target_x(
    *,
    target_date: str | None,
    target_x: float | None,
    first_date: datetime | None,
    fallback: float,
) -> float:
    if target_x is not None:
        return _coerce_finite_number(target_x, "target_x")
    if target_date:
        if first_date is None:
            raise ValidationError("target_date requires dated trend_projection observations")
        return (_parse_iso_datetime(target_date, field_name="target_date") - first_date).total_seconds() / 86400
    return fallback


def _days_since_first(value: Any, first_date: datetime | None) -> float:
    if first_date is None:
        raise ValidationError("dated trend_projection observation has no first date")
    return (_parse_iso_datetime(value, field_name="date") - first_date).total_seconds() / 86400


def _parse_iso_datetime(value: Any, *, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be an ISO date or timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO date or timestamp") from exc


def _coerce_finite_number(raw: Any, field_name: str) -> float:
    if isinstance(raw, bool):
        raise ValidationError(f"{field_name} must be numeric")
    if isinstance(raw, (int, float)):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValidationError(f"{field_name} must be numeric") from exc
    else:
        raise ValidationError(f"{field_name} must be numeric")
    if not math.isfinite(value):
        raise ValidationError(f"{field_name} must be finite")
    return value
