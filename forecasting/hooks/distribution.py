"""Distribution / uncertainty-bounds assessment + auto-fix for forecast hooks.

Wraps ``forecasting.dashboard._distribution_view`` (the canonical parser that the
Desk charts use) to answer: is this distribution well-formed + renderable, and if
not, what is wrong + can we mechanically fix it? Malformed bounds (inverted,
non-nested, out-of-range, degenerate) are what make the Desk charts look absurd.

Pure + stdlib-only (math); no ledger IO.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and math.isfinite(x)


# Distribution-summary keys (mean/sd/quantiles/intervals) — a payload whose numeric
# keys are these is a continuous summary, NOT candidate shares.
_DIST_STAT_KEYS = frozenset({
    "mean", "median", "mode", "expected", "value", "point", "sd", "sigma", "stdev",
    "std", "variance", "var", "q01", "q05", "q10", "q25", "q50", "q75", "q90", "q95", "q99",
    "p05", "p10", "p25", "p50", "p75", "p90", "p95", "ci50", "ci80", "ci90", "ci95",
    "lower", "upper", "low", "high", "min", "max",
})


def _is_candidate_share_pmf(payload: dict) -> bool:
    """A candidate-SHARE PMF: at least two numeric NAMED shares (keys that are not
    distribution-summary stats) summing to ~1 or ~100. Renderable as bars over the
    candidates — the shape a vote-share forecast takes."""
    numeric = {
        str(key).strip().lower(): float(value)
        for key, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    shares = {key: value for key, value in numeric.items() if key not in _DIST_STAT_KEYS}
    if len(shares) < 2:
        return False
    total = sum(shares.values())
    return (0.9 <= total <= 1.1) or (90.0 <= total <= 110.0)


@dataclass
class DistributionAssessment:
    is_distribution: bool                 # payload parses as a continuous distribution
    renderable: bool = True               # central tendency + >=1 ordered interval present
    ordered: bool = True                  # every interval has lo <= hi
    nested: bool = True                   # ci50 sits inside ci90
    finite: bool = True                   # all moments/interval bounds finite
    in_range: bool = True                 # all values within OutcomeSpace bounds
    degenerate: bool = False              # a present interval has zero width
    central_within: bool = True           # the central tendency lies INSIDE its band
    has_units: bool = True                # units declared (charts need them)
    width_ratio: float | None = None      # widest interval width / question range
    issues: list[str] = field(default_factory=list)

    @property
    def well_formed(self) -> bool:
        return (
            self.ordered and self.nested and self.finite and self.in_range
            and not self.degenerate and self.central_within
        )


_DIST_TYPES = {"distribution", "numeric", "thesis"}


def assess_distribution(
    payload: Any,
    *,
    outcome_type: str | None = None,
    bounds: list[float] | None = None,
    units: str | None = None,
) -> DistributionAssessment | None:
    """Assess a distribution payload. Returns None for binary / plain categorical
    forecasts (no continuous distribution to validate). For a distribution/numeric
    question whose payload the chart parser can't render (e.g. a bare point estimate
    or median-only with no parseable interval), returns an assessment flagged
    not-renderable rather than None, since that is exactly a chart-rendering gap."""
    # Only assess genuinely-continuous questions. Binary (scalar) and categorical
    # (PMF, governed by the tail-audit rules) are not continuous distributions —
    # even when a dict payload incidentally parses via _distribution_view. An
    # unknown type (None) is assessed best-effort.
    if outcome_type is not None and outcome_type not in _DIST_TYPES:
        return None
    try:
        from forecasting.dashboard import _distribution_view
    except Exception:
        return None
    view = _distribution_view(payload)
    if view is None:
        # Not parseable as a continuous distribution. Only flag it when the
        # QUESTION is distribution/numeric (a binary scalar is correctly None).
        if outcome_type in _DIST_TYPES and isinstance(payload, dict):
            # A candidate-SHARE PMF (vote share: {candidate: share} over >=2 named
            # candidates summing to ~1 or ~100) is RENDERABLE as bars over candidates
            # — a categorical-style distribution, not a continuous one. Recognize it
            # so a vote-share forecast commits LIVE (and engages its lessons) instead
            # of being forced exploratory, which bypasses every gate.
            if _is_candidate_share_pmf(payload):
                return DistributionAssessment(is_distribution=True, renderable=True, has_units=bool(units))
            return DistributionAssessment(
                is_distribution=True, renderable=False, has_units=bool(units),
                issues=["distribution payload has no renderable central tendency + interval (charts use the same parser)"],
            )
        return None

    # A parsed PMF (categorical-style candidate shares, e.g. probability-scale vote
    # share) is renderable as bars over the outcomes — it is NOT a continuous band, so
    # it does not need a central tendency + interval. Recognize it as renderable.
    if view.get("pmf"):
        return DistributionAssessment(is_distribution=True, renderable=True, has_units=bool(units))

    mean, median, sd = view.get("mean"), view.get("median"), view.get("sd")
    ci50, ci90 = view.get("ci50"), view.get("ci90")
    a = DistributionAssessment(is_distribution=True)

    lo_b, hi_b = (bounds[0], bounds[1]) if (bounds and len(bounds) == 2 and _finite(bounds[0]) and _finite(bounds[1]) and bounds[0] <= bounds[1]) else (None, None)

    central = median if _finite(median) else (mean if _finite(mean) else None)
    intervals = [("ci50", ci50), ("ci90", ci90)]
    present = [(name, iv) for name, iv in intervals if iv]

    # renderable: a central tendency + at least one interval
    if central is None or not present:
        a.renderable = False
        a.issues.append("distribution lacks a central tendency (median/mean) + at least one interval (ci90)")

    for name, iv in present:
        if not (isinstance(iv, (list, tuple)) and len(iv) == 2 and _finite(iv[0]) and _finite(iv[1])):
            a.finite = False
            a.issues.append(f"{name} has a non-finite / malformed bound")
            continue
        lo, hi = iv
        if lo > hi:
            a.ordered = False
            a.issues.append(f"{name} is inverted (lo {lo} > hi {hi})")
        if lo == hi:
            a.degenerate = True
            a.issues.append(f"{name} is degenerate (zero width)")
        if lo_b is not None and (min(lo, hi) < lo_b or max(lo, hi) > hi_b):
            a.in_range = False
            a.issues.append(f"{name} extends outside the question bounds [{lo_b}, {hi_b}]")

    # nesting: ci50 must sit inside ci90
    if ci50 and ci90 and all(_finite(v) for v in (*ci50, *ci90)):
        lo50, hi50 = min(ci50), max(ci50)
        lo90, hi90 = min(ci90), max(ci90)
        if lo50 < lo90 or hi50 > hi90:
            a.nested = False
            a.issues.append("ci50 is not nested inside ci90")

    # central-in-band: the expected value MUST lie inside its own interval. A point
    # outside its band is never a valid forecast — this is the disconnected-band bug
    # (mean 44.7 with ci90 [-4.7, 5]); it was previously uncaught. Check against the
    # widest present interval (ci90 preferred, else ci50).
    if central is not None:
        band = ci90 if (ci90 and all(_finite(v) for v in ci90)) else (ci50 if (ci50 and all(_finite(v) for v in ci50)) else None)
        if band is not None:
            blo, bhi = min(band), max(band)
            if not (blo <= central <= bhi):
                a.central_within = False
                a.issues.append(f"central tendency {central} lies OUTSIDE its band [{blo}, {bhi}]")

    # width ratio (advisory): widest interval vs the question range
    widest = None
    for _name, iv in present:
        if iv and _finite(iv[0]) and _finite(iv[1]):
            widest = max(widest or 0.0, abs(iv[1] - iv[0]))
    if widest is not None:
        rng = (hi_b - lo_b) if lo_b is not None else (abs(central) if (central and central) else None)
        if rng and rng > 0:
            a.width_ratio = widest / rng

    if not units:
        a.has_units = False  # advisory: the chart axis needs units

    return a


def autofix_distribution(payload: Any, *, bounds: list[float] | None = None) -> tuple[Any, list[str]]:
    """Mechanically repair a distribution payload so it renders cleanly: reorder
    inverted intervals, clamp to bounds, and nest ci50 inside ci90. Writes the
    corrected intervals back under canonical ``interval_50_*`` / ``interval_90_*``
    keys (which the parser prefers). Returns (fixed_payload, applied_fixes). A
    non-distribution payload is returned unchanged."""
    try:
        from forecasting.dashboard import _distribution_view
    except Exception:
        return payload, []
    if not isinstance(payload, dict):
        return payload, []

    fixes: list[str] = []
    work = dict(payload)
    # Derive a mean from the median when absent, so the chart parser (which needs
    # a mean) can render a median-only distribution.
    if not any(str(k).lower() == "mean" for k in work):
        med = next((work[k] for k in work if str(k).lower() == "median"), None)
        if _finite(med):
            work["mean"] = med
            fixes.append("derived mean from median")

    view = _distribution_view(work)
    if view is None:
        return (work if fixes else payload), fixes

    lo_b, hi_b = (bounds[0], bounds[1]) if (bounds and len(bounds) == 2 and _finite(bounds[0]) and _finite(bounds[1]) and bounds[0] <= bounds[1]) else (None, None)
    fixed = dict(work)

    def _norm(iv, pct: str):
        if not (iv and _finite(iv[0]) and _finite(iv[1])):
            return None
        lo, hi = iv
        if lo > hi:
            lo, hi = hi, lo
            fixes.append(f"reordered ci{pct}")
        if lo_b is not None:
            nlo, nhi = max(lo_b, min(lo, hi_b)), max(lo_b, min(hi, hi_b))
            if (nlo, nhi) != (lo, hi):
                fixes.append(f"clamped ci{pct} to bounds")
            lo, hi = nlo, nhi
        return [lo, hi]

    ci90 = _norm(view.get("ci90"), "90")
    ci50 = _norm(view.get("ci50"), "50")
    if ci50 and ci90 and (ci50[0] < ci90[0] or ci50[1] > ci90[1]):
        ci50 = [max(ci50[0], ci90[0]), min(ci50[1], ci90[1])]
        if ci50[0] > ci50[1]:
            ci50 = [ci90[0], ci90[1]]
        fixes.append("nested ci50 inside ci90")

    if ci90:
        fixed["interval_90_low"], fixed["interval_90_high"] = ci90[0], ci90[1]
    if ci50:
        fixed["interval_50_low"], fixed["interval_50_high"] = ci50[0], ci50[1]
    return (fixed if fixes else payload), fixes
