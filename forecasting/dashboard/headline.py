"""Distribution-headline / distribution-view formatting (carved from ``dashboard.py``).

The Wave-4 §W3.b ``headline`` section: the headline scalar extractors
(``_headline_numeric`` / ``_finite_number`` / ``_headline_delta``), the full
``_distribution_view`` renderer (moments, quantiles, PMF rows) with its
moment/PMF/Z key tables, and the compact ``_distribution_headline`` /
``_short_candidate_label`` one-liners. Pure formatting — no ledger, no I/O.
Imported back into :mod:`forecasting.dashboard.core` (the workspace sections and
the ``thesis`` leaf consume these shared helpers) and re-exported by the façade
unchanged.
"""
from __future__ import annotations

import math
import re
from typing import Any

def _headline_delta(previous: Any, current: Any) -> float | None:
    """Change in the headline value (probability or mean) between two snapshots."""

    prev = _headline_numeric(previous)
    curr = _headline_numeric(current)
    if prev is None or curr is None:
        return None
    return curr - prev


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` for bool/NaN/Inf/non-numeric.

    Non-finite values (NaN, ±Inf) are rejected because they corrupt the
    time-series chart. Finite values outside [0, 1] are kept on purpose:
    numeric / distribution outcomes (e.g. a CPI mean of 3.1) legitimately
    exceed the probability range.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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


_MOMENT_MEAN_KEYS = ("mean", "mu", "expected")
_MOMENT_SD_KEYS = ("sd", "sigma", "std", "stdev")
_NON_PMF_KEYS = {
    "mean",
    "mu",
    "expected",
    "median",
    "mode",
    "sd",
    "sigma",
    "std",
    "stdev",
    "variance",
    "var",
    "skew",
    "skewness",
    "kurtosis",
    "value",
}
_Z90 = 1.6449  # standard-normal quantile for a 90% central interval
_Z50 = 0.6745  # ...and 50%


def _distribution_view(payload: Any) -> dict[str, Any] | None:
    """Split a distribution payload into moments / intervals / bucket PMF.

    A distribution forecast (e.g. CPI YoY) stores a continuous summary
    (``mean``/``median``/``sd``, ``interval_50_*``/``interval_90_*``,
    ``equivalent_normal_*``) *and* a discrete bucket PMF
    (``bucket_le_4_0``…``bucket_ge_4_4``) in one dict, mixing probability and
    outcome-unit values. This separates them so the TUI can chart the mean in
    its units, draw the PMF as its own histogram, and show the moments as a
    stat block — instead of plotting everything on one nonsensical scale.

    Returns ``None`` for scalars / non-dict payloads (binary forecasts) or
    dicts with no recoverable mean (plain categorical PMFs are handled
    elsewhere).
    """

    if not isinstance(payload, dict):
        return None

    moments: dict[str, float] = {}
    intervals: dict[str, list[float | None]] = {}
    equivalent: dict[str, float] = {}
    pmf: dict[str, float] = {}
    quantiles: dict[int, float] = {}

    for raw_key, raw_value in payload.items():
        value = _finite_number(raw_value)
        if value is None:
            continue
        key = str(raw_key).lower()

        interval = re.match(r"^(?:interval|ci|hdi|pi)[_-]?(\d{1,2})[_-]?(low|lo|l|high|hi|h)$", key)
        if interval:
            pctile = interval.group(1)
            side = 0 if interval.group(2) in ("low", "lo", "l") else 1
            intervals.setdefault(pctile, [None, None])[side] = value
            continue
        # Quantile keys (q05/q50/q95, quantile_25, percentile_90) — a common
        # distribution representation the model uses. Parse BEFORE the PMF catch
        # so percent-valued quantiles (e.g. CPI's q05=0.05, in [0,1]) aren't
        # mistaken for probability mass. Bare pNN keys stay PMF (count buckets).
        qmatch = re.match(r"^(?:q|quantile|percentile)[_-]?(\d{1,3})$", key)
        if qmatch:
            pct = int(qmatch.group(1))
            if 1 <= pct <= 99:
                quantiles[pct] = value
            continue
        if key.startswith("equivalent_normal_"):
            equivalent[key[len("equivalent_normal_") :]] = value
            continue
        if key in _MOMENT_MEAN_KEYS:
            moments.setdefault("mean", value)
            continue
        if key == "median":
            moments["median"] = value
            continue
        if key in _MOMENT_SD_KEYS:
            moments.setdefault("sd", value)
            continue
        if key in _NON_PMF_KEYS:
            continue
        # Remaining numeric entries that look like probability mass.
        if 0.0 <= value <= 1.0:
            pmf[str(raw_key)] = value

    # Fold quantiles into the canonical shape: q50 -> median, q25/q75 -> 50%
    # interval, q05/q95 -> 90% interval, and a normal-equivalent sd from the
    # widest available pair so the stat block + chart band always render.
    if quantiles:
        if 50 in quantiles:
            moments.setdefault("median", quantiles[50])
            moments.setdefault("mean", quantiles[50])
        if 25 in quantiles and 75 in quantiles:
            existing = intervals.setdefault("50", [None, None])
            existing[0] = existing[0] if existing[0] is not None else quantiles[25]
            existing[1] = existing[1] if existing[1] is not None else quantiles[75]
        if 5 in quantiles and 95 in quantiles:
            existing = intervals.setdefault("90", [None, None])
            existing[0] = existing[0] if existing[0] is not None else quantiles[5]
            existing[1] = existing[1] if existing[1] is not None else quantiles[95]
        if "sd" not in moments:
            if 5 in quantiles and 95 in quantiles:
                moments["sd"] = (quantiles[95] - quantiles[5]) / 3.2897
            elif 10 in quantiles and 90 in quantiles:
                moments["sd"] = (quantiles[90] - quantiles[10]) / 2.5631
            elif 25 in quantiles and 75 in quantiles:
                moments["sd"] = (quantiles[75] - quantiles[25]) / 1.349

    # Count distributions (p0, p1, ..., p6_plus) carry their uncertainty in the
    # PMF, not in quantile keys, so derive the median / 90% interval / sd from the
    # discrete CDF. Without this the chart band falls back to a degenerate
    # confidence-score band (e.g. +/- 0.06) that misrepresents a Poisson count.
    # Only when EVERY pmf label is count-like and no interval is already present
    # (so the CPI bucket-mixture, which ships interval_* keys, is untouched).
    if pmf and not intervals and "sd" not in moments:
        counts: dict[int, float] = {}
        all_counts = True
        for label, prob in pmf.items():
            match = re.match(r"^p_?(\d+)(?:_?plus|\+)?$", str(label).lower())
            if match:
                counts[int(match.group(1))] = counts.get(int(match.group(1)), 0.0) + prob
            else:
                all_counts = False
                break
        total = sum(counts.values()) if all_counts else 0.0
        if all_counts and counts and total > 0:
            ordered = sorted(counts.items())
            expected = sum(value * (prob / total) for value, prob in ordered)
            variance = sum((value - expected) ** 2 * (prob / total) for value, prob in ordered)
            cdf = 0.0
            q05 = q50 = q95 = None
            for value, prob in ordered:
                cdf += prob / total
                if q05 is None and cdf >= 0.05:
                    q05 = value
                if q50 is None and cdf >= 0.5:
                    q50 = value
                if q95 is None and cdf >= 0.95:
                    q95 = value
            if q50 is not None:
                moments.setdefault("median", float(q50))
            moments.setdefault("mean", expected)
            moments["sd"] = variance ** 0.5
            if q05 is not None and q95 is not None:
                intervals.setdefault("90", [float(q05), float(q95)])

    mean = moments.get("mean")
    if mean is None:
        mean = equivalent.get("mean")
    sd = moments.get("sd")
    if sd is None:
        sd = equivalent.get("sd")
    median = moments.get("median")

    pmf_rows: list[dict[str, Any]] | None = None
    if len(pmf) >= 2:
        total = sum(pmf.values())
        if 0.8 <= total <= 1.2:  # a genuine probability mass, not stray fields
            pmf_rows = [
                {"label": label, "probability": value}
                for label, value in sorted(pmf.items(), key=lambda kv: kv[1], reverse=True)
            ]

    if mean is None and pmf_rows is None:
        return None

    def _interval(pctile: str, z: float) -> list[float] | None:
        existing = intervals.get(pctile)
        if existing and existing[0] is not None and existing[1] is not None:
            return [existing[0], existing[1]]
        if mean is not None and sd is not None:
            return [mean - z * sd, mean + z * sd]
        return None

    return {
        "mean": mean,
        "median": median,
        "sd": sd,
        "ci50": _interval("50", _Z50),
        "ci90": _interval("90", _Z90),
        "pmf": pmf_rows,
    }


# Distribution-summary keys to drop when a categorical / vote-share PMF is rendered
# as a headline (mirrors the TUI's distributionBars filter): a HYBRID payload can
# carry candidate shares AND a bolted-on leader distribution, and only the candidate
# entries belong in the headline — never mean/median/sd/quantiles/intervals.
_PMF_STAT_KEYS = {
    "mean", "mu", "sd", "sigma", "std", "stdev", "variance", "expected", "value",
    "median", "mode", "lower", "upper", "low", "high", "min", "max",
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
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        num = float(val)
        if not math.isfinite(num) or _is_pmf_stat_key(key):
            continue
        entries.append((str(key), num))
    if len(entries) < 2:
        return None
    entries.sort(key=lambda kv: kv[1], reverse=True)
    scale = 100.0 if all(0.0 <= v <= 1.0 for _, v in entries) else 1.0
    return " · ".join(f"{_short_candidate_label(k)} {v * scale:.1f}" for k, v in entries)
