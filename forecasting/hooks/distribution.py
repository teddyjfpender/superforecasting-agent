"""Distribution / uncertainty-bounds assessment + auto-fix for forecast hooks.

Wraps ``forecasting.distribution_summary.summarize_distribution`` (the canonical parser that the
Desk charts use) to answer: is this distribution well-formed + renderable, and if
not, what is wrong + can we mechanically fix it? Malformed bounds (inverted,
non-nested, out-of-range, degenerate) are what make the Desk charts look absurd.

Pure + stdlib-only (math); no ledger IO.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from forecasting.distribution_summary import summarize_distribution


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


# Residual / catch-all outcome names (prefix-matched): unanchored mass is allowed
# to live here, so these are exempt from the per-candidate anchor + interval gates.
# Kept in sync with tail_audit._RESIDUAL_NAMES / _RESIDUAL_PREFIXES.
_RESIDUAL_SHARE_PREFIXES = ("other", "others", "any other", "someone else", "some other", "field", "none of the above")


def _is_residual_share_name(name: str) -> bool:
    n = str(name).strip().lower()
    return any(n == p or n.startswith(p) for p in _RESIDUAL_SHARE_PREFIXES)


# A CDF / threshold ANNOTATION key (p_below_3_5, p_above_50, prob_x, cdf_…) is a
# continuous-distribution annotation, NOT a candidate share — excluded from share
# extraction so a continuous payload whose two annotation probabilities incidentally
# sum to ~1 is not misread as a vote-share board (the p_below false positive).
_ANNOTATION_KEY_RE = re.compile(
    r"^(p_?(below|above|under|over|out|lt|gt|le|ge|lte|gte|less|greater)|prob|pr_|cdf|pct_(below|above))"
)


def _is_share_stat_key(name: str) -> bool:
    """True when a payload key is a distribution SUMMARY (mean/sd/quantile/interval)
    or a CDF annotation — i.e. NOT a named candidate share. Live vote-share boards
    store the shares alongside a leader mean/quantiles + interval_50/90_* bounds, so
    those must be excluded to recover the candidate shares (which sum to ~100)."""
    n = str(name).strip().lower()
    if n in _DIST_STAT_KEYS:
        return True
    if n.startswith("interval_") or n.startswith("ci_"):
        return True
    if _ANNOTATION_KEY_RE.match(n):
        return True
    return False


def candidate_shares(payload: Any) -> dict[str, float] | None:
    """Extract the NAMED candidate shares from a vote-share PMF, normalized to
    FRACTIONS (0-1), preserving the original outcome keys. Returns None when the
    payload is not a candidate-share PMF (fewer than two named numeric shares, or
    they do not sum to ~1 / ~100).

    This is the SINGLE share-extraction path shared by the sharpness metric
    (``ForecastLedger._sharpness``), the G1 tail base-rate rule, the G2 interval
    coherence rule, and the G6 coherence check, so those consumers never disagree
    about what a share board is or which scale it lives on. Recognition uses the
    loose ±10% band (so a mis-summed board is still SEEN as a share PMF and gets a
    precise coherence message rather than a generic not-renderable one); the tight
    ±2% coherence check lives in :func:`assess_distribution`."""
    if not isinstance(payload, dict):
        return None
    shares: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Exclude distribution stats / interval bounds / CDF annotations; what
            # remains is the named candidate shares. Live vote-share boards store
            # BOTH (candidates + a leader mean/quantiles + interval_* bounds), so the
            # shares must be recovered by exclusion, not by rejecting the whole payload.
            if not _is_share_stat_key(key):
                shares[str(key)] = float(value)
    if len(shares) < 2:
        return None
    total = sum(shares.values())
    if 0.9 <= total <= 1.1:
        return dict(shares)                       # already fractional
    if 90.0 <= total <= 110.0:
        return {k: v / 100.0 for k, v in shares.items()}  # percentage points -> fraction
    return None


# G4 · granularity discipline. The round-number ANCHORS a lazy model reaches for
# instead of committing the number the evidence computes: every 0.10 multiple in the
# open interval, plus the quarter-points. 0.0 / 1.0 are excluded (degenerate
# certainty is a different concern, not round-number hedging).
_ROUND_ANCHORS: tuple[float, ...] = (0.1, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9)
# How close a pooled component must land to the committed p for the roundness to be
# "earned" (a pool that genuinely computes 0.60 is not anchoring).
_EARNED_ROUND_TOLERANCE = 0.005


def _binary_probability(payload: Any) -> float | None:
    """The committed binary probability (a bare float), or None for any other
    payload shape. A bool is not a probability."""
    if isinstance(payload, (int, float)) and not isinstance(payload, bool):
        p = float(payload)
        return p if 0.0 <= p <= 1.0 else None
    return None


def _component_probabilities(components: Any) -> list[float]:
    """Extract the numeric pooled probabilities from an ensemble_components blob
    (a list of rows or the ``{components: [...]}`` wrapper), best-effort. Reads the
    ``probability`` / ``value`` / ``estimate`` field off each row."""
    rows: Any = components
    if isinstance(rows, dict):
        rows = rows.get("components", rows)
    out: list[float] = []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, (list, tuple)):
        return out
    for row in rows:
        value: Any = None
        if isinstance(row, dict):
            for key in ("probability", "value", "estimate", "p"):
                if isinstance(row.get(key), (int, float)) and not isinstance(row.get(key), bool):
                    value = row.get(key)
                    break
        elif isinstance(row, (int, float)) and not isinstance(row, bool):
            value = row
        if value is not None and math.isfinite(float(value)):
            out.append(float(value))
    return out


def is_round_number_anchored(
    payload: Any,
    components: Any,
    *,
    uncertainty_justified: bool = False,
) -> bool:
    """G4 — is the committed binary probability a round-number ANCHOR the evidence
    did not compute? True when ``payload`` is a binary p that sits exactly on a round
    anchor (a 0.10 multiple, or 0.25/0.5/0.75), no pooled component lands within
    :data:`_EARNED_ROUND_TOLERANCE` of it (so the roundness is not earned), and no
    ``uncertainty_justified`` escape is recorded. Pure arithmetic on data already in
    scope — non-binary payloads and justified/earned rounds return False (passing)."""
    if uncertainty_justified:
        return False
    p = _binary_probability(payload)
    if p is None:
        return False
    if not any(abs(p - anchor) <= 1e-9 for anchor in _ROUND_ANCHORS):
        return False
    for value in _component_probabilities(components):
        if abs(value - p) <= _EARNED_ROUND_TOLERANCE:
            return False  # a pooled component actually produced this number — earned
    return True


def _is_candidate_share_pmf(payload: dict) -> bool:
    """A candidate-SHARE PMF: at least two numeric NAMED shares (keys that are not
    distribution-summary stats) summing to ~1 or ~100. Renderable as bars over the
    candidates — the shape a vote-share forecast takes."""
    return candidate_shares(payload) is not None


# Ordered quantile vocabularies (percentiles). A continuous payload must have a
# MONOTONE quantile chain — a payload with q25 > q75 is a reasoning error the
# ci-pair ordering check never caught (only the ci50/ci90 pairs were validated).
_QUANTILE_CHAINS: tuple[tuple[str, ...], ...] = (
    ("q01", "q05", "q10", "q25", "q50", "q75", "q90", "q95", "q99"),
    ("p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"),
)


def _share_coherence_issues(payload: Any) -> list[str]:
    """G6 coherence for a vote-share PMF: the named shares must sum to ~100 (within
    ±2%, tighter than the ±10% recognition band) and none may be negative. Returns
    the list of issue strings (empty when coherent)."""
    shares = candidate_shares(payload)
    if shares is None:
        return []
    issues: list[str] = []
    total = sum(shares.values())              # normalized to a fraction
    if abs(total - 1.0) > 0.02 + 1e-9:        # ±2% of 100, inclusive (float-safe)
        issues.append(f"candidate shares sum to {total * 100:.1f}, not ~100")
    negatives = [name for name, value in shares.items() if value < 0]
    if negatives:
        issues.append(f"candidate share(s) are negative: {', '.join(negatives)}")
    return issues


def _quantile_monotonicity_issues(payload: Any) -> list[str]:
    """G6 coherence for a continuous payload: the present quantiles must ascend.
    Reads the raw quantile keys (q01..q99 / p01..p99) off the payload and reports
    any inversion (an earlier quantile larger than a later one)."""
    if not isinstance(payload, dict):
        return []
    lowered: dict[str, float] = {}
    for key, value in payload.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            lowered[str(key).strip().lower()] = float(value)
    issues: list[str] = []
    for chain in _QUANTILE_CHAINS:
        present = [(name, lowered[name]) for name in chain if name in lowered and math.isfinite(lowered[name])]
        for (lo_name, lo_val), (hi_name, hi_val) in zip(present, present[1:]):
            if lo_val > hi_val:
                issues.append(f"quantiles are not monotone: {lo_name} ({lo_val}) > {hi_name} ({hi_val})")
    return issues


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
    coherent: bool = True                 # G6: share PMF sums to ~100 + non-negative / quantiles monotone
    width_ratio: float | None = None      # widest interval width / question range
    issues: list[str] = field(default_factory=list)

    @property
    def well_formed(self) -> bool:
        return (
            self.ordered and self.nested and self.finite and self.in_range
            and not self.degenerate and self.central_within and self.coherent
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
    view = summarize_distribution(payload)
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
                _sc = _share_coherence_issues(payload)
                return DistributionAssessment(
                    is_distribution=True, renderable=True, has_units=bool(units),
                    coherent=not _sc, issues=list(_sc),
                )
            return DistributionAssessment(
                is_distribution=True, renderable=False, has_units=bool(units),
                issues=["distribution payload has no renderable central tendency + interval (charts use the same parser)"],
            )
        return None

    # A parsed PMF (categorical-style candidate shares, e.g. probability-scale vote
    # share) is renderable as bars over the outcomes — it is NOT a continuous band, so
    # it does not need a central tendency + interval. Recognize it as renderable, but
    # still G6-check the share coherence (sum ~100, non-negative).
    if view.get("pmf"):
        _sc = _share_coherence_issues(payload)
        return DistributionAssessment(
            is_distribution=True, renderable=True, has_units=bool(units),
            coherent=not _sc, issues=list(_sc),
        )

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

    # G6 monotonicity: the raw quantile chain (q01..q99 / p01..p99) must ascend.
    # Only the ci50/ci90 pairs were ordered/nested before, so a payload with
    # q25 > q75 slipped through. An inversion is a reasoning error, not a fixable
    # bound — flag it (autofix does not silently sort it).
    _mono = _quantile_monotonicity_issues(payload)
    if _mono:
        a.ordered = False
        a.issues.extend(_mono)

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

    # A HYBRID vote-share board (candidate shares + a leader mean/quantiles) parses
    # as continuous here, but still owes G6 share coherence on its candidate shares
    # (sum ~100, non-negative) — the pure-share branches above only catch boards with
    # no continuous summary.
    _sc = _share_coherence_issues(payload)
    if _sc:
        a.coherent = False
        a.issues.extend(_sc)

    if not units:
        a.has_units = False  # advisory: the chart axis needs units

    return a


def assess_candidate_intervals(
    payload: Any,
    intervals_raw: Any,
    *,
    bounds: list[float] | None = None,
    tolerance_pp: float = 2.0,
) -> tuple[bool, float | None, list[str]]:
    """Validate per-candidate vote-share intervals (the out-of-band
    ``metadata.candidate_share_intervals_pp = {candidate: {p05, median|p50, p95}}``).

    Returns ``(coherent, coverage, issues)``:
      * ``coherent`` — every PRESENT interval is finite, ``p05 <= median <= p95``,
        the median sits within ``tolerance_pp`` of the committed share, and the
        bounds lie inside the question range. A malformed band (a claim contradicting
        its own point) is worse than no band.
      * ``coverage`` — covered named non-residual candidates / total named
        non-residual candidates (``None`` when the payload is not a share PMF).
      * ``issues`` — the human-facing problem strings (empty when coherent).

    Absence is HONEST: no intervals ⇒ ``coherent=True`` (nothing to contradict) and
    ``coverage=0.0``. Building the intervals is P2; this gate only rejects garbage.
    Intervals are stored in percentage POINTS; the committed shares are normalized
    to fractions here so pp / fractional payloads compare on one scale."""
    shares = candidate_shares(payload)
    if shares is None:
        return True, None, []
    named = {name: value for name, value in shares.items() if not _is_residual_share_name(name)}
    if not isinstance(intervals_raw, dict) or not intervals_raw:
        return True, 0.0, []  # absence is honest — the presence gate (P2) judges it, not this one

    def _num(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    tol = abs(float(tolerance_pp)) / 100.0
    lo_b, hi_b = (None, None)
    if bounds and len(bounds) == 2 and _finite(bounds[0]) and _finite(bounds[1]) and bounds[0] <= bounds[1]:
        # bounds are on the payload scale; normalize pp bounds (e.g. [0,100]) to fractions
        _scale = 0.01 if float(bounds[1]) > 1.5 else 1.0
        lo_b, hi_b = float(bounds[0]) * _scale, float(bounds[1]) * _scale
    issues: list[str] = []
    covered = 0
    for name, share in named.items():
        iv = intervals_raw.get(name)
        if not isinstance(iv, dict):
            continue
        lo = _num(iv.get("p05"))
        mid = _num(iv.get("median", iv.get("p50")))
        hi = _num(iv.get("p95"))
        if lo is None and mid is None and hi is None:
            continue
        covered += 1
        # intervals are pp -> fractions to compare against the (fractional) share
        lo_f = lo / 100.0 if lo is not None else None
        mid_f = mid / 100.0 if mid is not None else None
        hi_f = hi / 100.0 if hi is not None else None
        present = [v for v in (lo_f, mid_f, hi_f) if v is not None]
        if lo_f is not None and hi_f is not None and lo_f > hi_f:
            issues.append(f"{name}: p05 ({lo}) > p95 ({hi})")
        if mid_f is not None and lo_f is not None and mid_f < lo_f:
            issues.append(f"{name}: median ({mid}) < p05 ({lo})")
        if mid_f is not None and hi_f is not None and mid_f > hi_f:
            issues.append(f"{name}: median ({mid}) > p95 ({hi})")
        if mid_f is not None and abs(mid_f - share) > tol:
            issues.append(f"{name}: median {mid_f * 100:.1f}pp is >{tolerance_pp:.0f}pp off the committed share {share * 100:.1f}pp")
        for label, value in (("p05", lo_f), ("median", mid_f), ("p95", hi_f)):
            if value is None:
                continue
            if value < 0:
                issues.append(f"{name}: {label} is negative")
            elif lo_b is not None and (value < lo_b or value > hi_b):
                issues.append(f"{name}: {label} is outside the question bounds")
    coverage = (covered / len(named)) if named else None
    return (not issues), coverage, issues


def autofix_distribution(payload: Any, *, bounds: list[float] | None = None) -> tuple[Any, list[str]]:
    """Mechanically repair a distribution payload so it renders cleanly: reorder
    inverted intervals, clamp to bounds, and nest ci50 inside ci90. Writes the
    corrected intervals back under canonical ``interval_50_*`` / ``interval_90_*``
    keys (which the parser prefers). Returns (fixed_payload, applied_fixes). A
    non-distribution payload is returned unchanged."""
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

    view = summarize_distribution(work)
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
