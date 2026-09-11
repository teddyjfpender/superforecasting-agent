"""Forecast headline formatting and compatibility exports for summary consumers.

Distribution interpretation belongs to forecasting.distribution_summary. This
module owns candidate labels and compact display strings, retaining the existing
private summary aliases for dashboard callers.
"""

from __future__ import annotations

from typing import Any

from forecasting.distribution_summary import (
    _NON_PMF_KEYS,
    finite_number as _finite_number,
    summarize_distribution as _distribution_view,
)


def _headline_delta(previous: Any, current: Any) -> float | None:
    """Change in the headline value (probability or mean) between two snapshots."""

    prev = _headline_numeric(previous)
    curr = _headline_numeric(current)
    if prev is None or curr is None:
        return None
    return curr - prev


def _headline_numeric(payload: Any) -> float | None:
    """Pick one finite numeric value per forecast for time-series charting.

    Binary/numeric forecasts are a bare float. Probability dicts collapse to
    the max outcome probability; ``{mean: ...}`` distributions to the mean.
    Returns ``None`` when nothing finite can be extracted.
    """

    scalar = _finite_number(payload)
    if scalar is not None:
        return scalar
    if isinstance(payload, dict):
        for key in ("mean", "mu", "expected", "value"):
            candidate = _finite_number(payload.get(key))
            if candidate is not None:
                return candidate
        numeric = [
            number
            for value in payload.values()
            if (number := _finite_number(value)) is not None
        ]
        if numeric and all(0.0 <= value <= 1.0 for value in numeric):
            return max(numeric)
        if numeric:
            return numeric[0]
    return None


# Distribution-summary keys to drop when a categorical / vote-share PMF is rendered
# as a headline (mirrors the TUI's distributionBars filter): a HYBRID payload can
# carry candidate shares AND a bolted-on leader distribution, and only the candidate
# entries belong in the headline — never mean/median/sd/quantiles/intervals.
_PMF_STAT_KEYS = {
    "mean",
    "mu",
    "sd",
    "sigma",
    "std",
    "stdev",
    "variance",
    "expected",
    "value",
    "median",
    "mode",
    "lower",
    "upper",
    "low",
    "high",
    "min",
    "max",
}


def _is_pmf_stat_key(key: Any) -> bool:
    k = str(key).strip().lower()
    # Moment / interval / bucket keys of a CONTINUOUS distribution are not candidates.
    # (The TUI side skips this filter because headline_kind=='distribution' already
    # routes distributions to the μ/σ path; format_probability has no such guard, so
    # it must reject them here to keep distributions on their JSON fallback.)
    if k in _PMF_STAT_KEYS or k in _NON_PMF_KEYS:
        return True
    if k.startswith(("ci", "interval", "bucket", "equivalent", "range")):
        return True
    return len(k) >= 2 and k[0] in "qp" and k[1].isdigit()


def _short_candidate_label(name: Any, max_len: int = 11) -> str:
    trimmed = str(name).strip()
    if len(trimmed) <= max_len:
        return trimmed
    words = trimmed.split()
    if len(words) == 2 and 0 < len(words[-1]) <= max_len:
        return words[-1]
    return trimmed[: max(0, max_len - 1)] + "…"


def _distribution_headline(value: dict) -> str | None:
    """Value-sorted, leader-first headline for a categorical / vote-share PMF dict.

    "Farage 67.0 · Binface 16.5 · Fox 4.0 · Other 12.5" — sorted DESC so the leader
    is always first, 1dp, no braces/quotes, surnames for long names. This replaces
    the old ``json.dumps(sort_keys=True)`` dump that ordered by KEY and truncated the
    leader mid-string. Fraction-scale dicts (every value in [0,1]) render as
    percentages (×100). Returns ``None`` when it is not a ≥2-candidate PMF, so the
    caller can fall back. Every surface reading ``probability_display`` (the TUI's
    fallback and the website export) inherits this.
    """

    entries: list[tuple[str, float]] = []
    for key, val in value.items():
        num = _finite_number(val)
        if num is None or _is_pmf_stat_key(key):
            continue
        entries.append((str(key), num))
    if len(entries) < 2:
        return None
    entries.sort(key=lambda kv: kv[1], reverse=True)
    scale = 100.0 if all(0.0 <= v <= 1.0 for _, v in entries) else 1.0
    return " · ".join(
        f"{_short_candidate_label(k)} {v * scale:.1f}" for k, v in entries
    )
