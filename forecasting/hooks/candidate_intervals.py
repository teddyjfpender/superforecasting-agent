"""Compute per-candidate vote-share intervals (the honest sources, in precedence).

A vote-share forecast commits a flat ``{candidate: share}`` PMF. The Desk wants a
per-candidate uncertainty band — p05/median/p95 per candidate — stored out-of-band in
``metadata.candidate_share_intervals_pp`` (percentage POINTS). This module computes
that band AT COMMIT TIME from what the forecast already carries, so a committer never
has to hand-author it, and it is NEVER a fabricated tightness.

Precedence (richest-disagreement first — the same order the G2 tests pin):

  1. ``panel``   — the ensemble carries >= MIN_SPREAD_SAMPLES per-candidate share
                   vectors (each model / reference-class / panel / poll component is a
                   "panelist"). The empirical spread of a candidate across those views
                   IS the desk's own measured uncertainty. This is source (a).
  2. ``model``   — a Monte-Carlo vote-share model emitted per-candidate QUANTILES
                   directly (a component carrying a ``quantiles`` map). Use them. (b)
  3. ``default`` — neither: a documented width tied to evidence THINNESS (the thesis
                   -band precedent — sigma grows as evidence thins, stated in
                   provenance), NEVER a fabricated sharpness. The LEADER inherits the
                   payload's own published interval (interval_90 / q05..q95) where it
                   carries one, so the default branch keeps the real leader band. (c)

**Coherence by construction.** Every emitted interval sets ``median`` to the committed
share exactly (0pp off), guarantees ``p05 <= median <= p95``, and clamps the bounds to
``[0, hi]``. So :func:`forecasting.hooks.distribution.assess_candidate_intervals` (the
G2 validator) PASSES on anything this returns — the two are coupled on purpose.

Pure + stdlib-only (math); no ledger IO. The ledger/CLI supply the components +
evidence count; the computation is unit-testable in isolation.
"""

from __future__ import annotations

import math
from typing import Any

from forecasting.hooks.distribution import _is_residual_share_name, candidate_shares

# A candidate's spread is only trustworthy when several independent views priced it;
# below this many per-candidate component vectors the "spread" is noise, so we fall
# through to the model / default source rather than pretend to a tight empirical band.
MIN_SPREAD_SAMPLES = 3

# Default-width tuning (percentage POINTS), tied to evidence thinness. base * (1/sqrt
# (evidence)) so a single-source forecast gets the widest band; floored/capped so it
# is neither absurdly wide nor a fabricated sharpness. Documented in provenance.
DEFAULT_BASE_HALF_WIDTH_PP = 10.0
DEFAULT_MIN_HALF_WIDTH_PP = 4.0
DEFAULT_MAX_HALF_WIDTH_PP = 25.0


def _num(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return float(value)
    return None


def _norm_key(name: str) -> str:
    return str(name).strip().lower()


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile (q in [0,1]) over an ASCENDING list. numpy-free
    so the computation has no optional-dependency branch."""
    if not sorted_values:
        return float("nan")
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = q * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    frac = pos - lo
    return sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac


def _component_distributions(components: Any) -> list[dict[str, float]]:
    """Extract the per-candidate share vectors carried by ensemble components, each
    normalized to FRACTIONS (0-1). A component is a share vector when its
    ``distribution`` / ``probability_or_distribution`` value is a dict of >= 2 numeric
    named shares summing to ~1 or ~100 (reusing the single share-extraction path)."""
    rows = components
    if isinstance(components, dict):
        rows = components.get("components", components)
    if not isinstance(rows, (list, tuple)):
        return []
    out: list[dict[str, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("distribution")
        if not isinstance(raw, dict):
            raw = row.get("probability_or_distribution")
        shares = candidate_shares(raw) if isinstance(raw, dict) else None
        if shares:
            out.append(shares)
    return out


def _model_quantiles(components: Any) -> dict[str, dict[str, float]] | None:
    """A Monte-Carlo vote-share model that emitted per-candidate quantiles directly:
    a component whose source starts ``model:`` carrying a ``quantiles`` map
    ``{candidate: {p05, median|p50, p95}}`` (pp or fraction). Returns the map
    normalized to FRACTIONS, or None when no such component exists."""
    rows = components
    if isinstance(components, dict):
        rows = components.get("components", components)
    if not isinstance(rows, (list, tuple)):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source", "") or "")
        quant = row.get("quantiles")
        if not source.startswith("model:") or not isinstance(quant, dict) or not quant:
            continue
        # Infer scale from the medians (pp if any median > 1.5).
        meds = [_num((v or {}).get("median", (v or {}).get("p50"))) for v in quant.values() if isinstance(v, dict)]
        meds = [m for m in meds if m is not None]
        scale = 0.01 if (meds and max(meds) > 1.5) else 1.0
        out: dict[str, dict[str, float]] = {}
        for cand, iv in quant.items():
            if not isinstance(iv, dict):
                continue
            lo, mid, hi = _num(iv.get("p05")), _num(iv.get("median", iv.get("p50"))), _num(iv.get("p95"))
            entry = {k: v * scale for k, v in (("p05", lo), ("median", mid), ("p95", hi)) if v is not None}
            if entry:
                out[str(cand)] = entry
        if out:
            return out
    return None


def _payload_leader_interval(payload: dict, shares: dict[str, float]) -> tuple[float, float] | None:
    """The LEADER's published interval carried on a hybrid vote-share payload as
    ``interval_90_low/high`` (or ``q05``/``q95``), normalized to FRACTIONS. Returns
    ``(lo, hi)`` on the leader's scale, or None. Vote-share payloads store the leading
    candidate's own distribution alongside the shares (see the live boards), so the
    leader owns a real band even when the tail does not."""
    lo = _num(payload.get("interval_90_low"))
    hi = _num(payload.get("interval_90_high"))
    if lo is None or hi is None:
        lo = _num(payload.get("q05"))
        hi = _num(payload.get("q95"))
    if lo is None or hi is None:
        return None
    # The published interval is on the SAME scale as the shares (both pp or both
    # fraction). candidate_shares already normalized shares to fractions; a leader at
    # ~0.67 vs a bound at 75.5 means the bounds are pp -> divide.
    leader_share = max(shares.values()) if shares else 0.0
    scale = 0.01 if (max(abs(lo), abs(hi)) > 1.5 and leader_share <= 1.5) else 1.0
    lo, hi = lo * scale, hi * scale
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _default_half_width_frac(evidence_count: int) -> float:
    """Evidence-thinness-tied half-width (FRACTION). The thesis-band precedent: the
    band widens as evidence thins (1/sqrt(evidence)), floored + capped so it is a
    documented default, never a fabricated sharpness."""
    n = max(int(evidence_count or 0), 1)
    hw_pp = DEFAULT_BASE_HALF_WIDTH_PP / math.sqrt(n)
    hw_pp = max(DEFAULT_MIN_HALF_WIDTH_PP, min(DEFAULT_MAX_HALF_WIDTH_PP, hw_pp))
    return hw_pp / 100.0


def _coherent_entry(share: float, lo: float | None, hi: float | None, hi_bound: float) -> dict[str, float]:
    """Assemble one coherent per-candidate interval (pp) from a proposed lo/hi around
    the committed share. Median is pinned to the share; lo/hi are widened to bracket it
    and clamped to ``[0, hi_bound]``. Coherence-by-construction for the G2 validator."""
    lo = share if lo is None else min(lo, share)
    hi = share if hi is None else max(hi, share)
    lo = max(0.0, lo)
    hi = min(hi_bound, hi)
    # Clamps can never invert a pinned median (median == share, lo<=share<=hi).
    return {
        "p05": round(lo * 100.0, 4),
        "median": round(share * 100.0, 4),
        "p95": round(hi * 100.0, 4),
    }


def compute_candidate_share_intervals(
    payload: Any,
    *,
    components: Any = None,
    evidence_count: int = 0,
    bounds: list[float] | None = None,
) -> tuple[dict[str, dict[str, float]] | None, dict[str, Any] | None]:
    """Compute per-candidate ``{candidate: {p05, median, p95}}`` intervals (percentage
    POINTS) for a vote-share PMF, plus a provenance stamp ``{source, params}``.

    Returns ``(None, None)`` when the payload is not a candidate-share PMF (so the
    caller stamps nothing). Otherwise ``source`` is one of ``panel`` / ``model`` /
    ``default`` per the module precedence, and every emitted interval is coherent by
    construction (median == committed share, p05 <= median <= p95, within ``[0, hi]``).
    """
    shares = candidate_shares(payload)
    if shares is None or not isinstance(payload, dict):
        return None, None

    # Upper bound in FRACTIONS (share scale). A vote-share axis is [0, 100] pp -> [0,1].
    hi_bound = 1.0
    if bounds and len(bounds) == 2:
        b0, b1 = _num(bounds[0]), _num(bounds[1])
        if b1 is not None and b1 > 0:
            hi_bound = (b1 / 100.0) if b1 > 1.5 else b1
    hi_bound = max(hi_bound, max(shares.values(), default=0.0))  # never clip a committed share

    # ── source (a): panel / ensemble spread ──────────────────────────────────────
    dists = _component_distributions(components)
    # Only the component vectors that priced EVERY named candidate contribute a full
    # sample row, so the spread is comparable across candidates.
    def _lookup(dist: dict[str, float], cand: str) -> float | None:
        if cand in dist:
            return dist[cand]
        nk = _norm_key(cand)
        for k, v in dist.items():
            if _norm_key(k) == nk:
                return v
        return None

    full = [d for d in dists if all(_lookup(d, cand) is not None for cand in shares)]
    if len(full) >= MIN_SPREAD_SAMPLES:
        intervals: dict[str, dict[str, float]] = {}
        for cand, share in shares.items():
            samples = sorted(_lookup(d, cand) for d in full)  # type: ignore[misc]
            lo = _percentile(samples, 0.05)
            hi = _percentile(samples, 0.95)
            intervals[cand] = _coherent_entry(share, lo, hi, hi_bound)
        return intervals, {"source": "panel", "params": {"n_components": len(full), "method": "empirical_spread_p05_p95"}}

    # ── source (b): a Monte-Carlo model's per-candidate quantiles ────────────────
    mq = _model_quantiles(components)
    if mq:
        intervals = {}
        for cand, share in shares.items():
            iv = mq.get(cand) or (next((v for k, v in mq.items() if _norm_key(k) == _norm_key(cand)), None))
            if isinstance(iv, dict):
                intervals[cand] = _coherent_entry(share, iv.get("p05"), iv.get("p95"), hi_bound)
            else:
                hw = _default_half_width_frac(evidence_count)
                intervals[cand] = _coherent_entry(share, share - hw, share + hw, hi_bound)
        return intervals, {"source": "model", "params": {"model_quantiles": True}}

    # ── source (c): evidence-state-tied default width (+ real leader band) ────────
    hw = _default_half_width_frac(evidence_count)
    leader_iv = _payload_leader_interval(payload, shares)
    leader_cand = max(shares, key=lambda k: shares[k]) if shares else None
    intervals = {}
    for cand, share in shares.items():
        if cand == leader_cand and leader_iv is not None:
            intervals[cand] = _coherent_entry(share, leader_iv[0], leader_iv[1], hi_bound)
        else:
            intervals[cand] = _coherent_entry(share, share - hw, share + hw, hi_bound)
    params: dict[str, Any] = {
        "base_half_width_pp": DEFAULT_BASE_HALF_WIDTH_PP,
        "half_width_pp": round(hw * 100.0, 3),
        "evidence_count": int(evidence_count or 0),
        "floor_pp": DEFAULT_MIN_HALF_WIDTH_PP,
        "cap_pp": DEFAULT_MAX_HALF_WIDTH_PP,
        "leader_from_payload_interval": leader_iv is not None,
    }
    return intervals, {"source": "default", "params": params}
