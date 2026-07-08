"""Thesis-level belief aggregation for the Superforecasting Agent.

Aggregate the *latest* beliefs of several weighted "member" forecasts into a
single thesis-level health probability, a 0..100 score, and an **honest**
uncertainty band. The agent is uncertainty-honest, so this module obeys two
hard rules:

* **Never fabricate precision.** A member with no calibrated dispersion
  contributes *zero* to the band rather than an invented standard deviation.
* **Never fake variance reduction.** Members co-move, so the band uses a
  correlated-variance formula (``rho`` couples every pair). The naive
  independence formula ``sum(w^2 sigma^2)`` is deliberately refused; it is
  only honoured when the caller passes the explicit float ``rho=0.0``.

This is pure math: stdlib ``math`` plus a few reused primitives from
:mod:`forecasting.bayes_toolkit`. No DB, no I/O, no ``datetime.now`` (the
``now`` reference instant is injected so callers/tests stay deterministic).

Input contract — see :func:`aggregate_thesis`. Each member dict carries a
``kind`` (``"binary"`` or ``"distribution"``), a ``direction``
(``"support"`` or ``"inverted"``), a raw ``weight``, an ``as_of`` timestamp,
and a belief payload. Distribution members are reduced upstream (e.g. by
``dashboard._distribution_view``) to ``{mean, sd, ci90, pmf, median}`` before
they reach this module — this module never reduces a raw distribution itself.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

# ── Reused bayes_toolkit primitives ─────────────────────────────────────────
# ``logit`` / ``inv_logit`` power the log-odds health pool (§2.4) and the
# leave-one-out marginals (§2.7). ``normal_cdf(x, mean, sd) == Phi((x-mean)/sd)``
# gives the threshold-on-normal signal (§2.1.2): ``Phi((mean-target)/sd)`` is
# ``normal_cdf(mean, target, sd)``. ``normal_ppf`` inverts the copula draw into
# a per-member latent threshold (§event: ``u_i < p_i ⇔ z_i < Phi⁻¹(p_i)``).
from forecasting.bayes_toolkit import inv_logit, logit, normal_cdf, normal_ppf

# NumPy is the fast path for the Gaussian-copula Monte Carlo (§event). It is
# optional — the module keeps a deterministic pure-python fallback so the event
# layer works offline, just at a lower draw count. Mirrors bayes_toolkit's guard.
try:  # pragma: no cover - numpy optional
    import numpy as _np
except Exception:  # pragma: no cover - numpy optional
    _np = None

__all__ = [
    "ThesisAggregate",
    "aggregate_thesis",
    "ThesisEventResult",
    "simulate_thesis_event",
    "ThesisEventBand",
    "simulate_thesis_event_band",
    "derive_member_probability_interval",
]

# Default staleness horizon when a member omits ``max_age_days``.
_DEFAULT_MAX_AGE_DAYS = 45.0
# Hard-coded: never extremize the pool — members co-move, sharpening would lie.
_EXTREMIZE_FACTOR = 1.0
# 90% central interval half-width in standard-normal units.
_Z90 = 1.645
# Clamp bounds.
_S_BAND_EPS = 1e-4   # binary signal clamp (keeps the Bernoulli proxy finite)
_LOGIT_EPS = 1e-6    # log-odds pool clamp (keeps logit finite)


# ── Small local helpers (kept local where bayes_toolkit doesn't cleanly fit) ─


def _clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` into ``[lo, hi]`` (plain, non-raising — unlike _clamp_prob)."""

    return lo if x < lo else hi if x > hi else x


def _coerce_float(value: Any) -> float | None:
    """Best-effort finite float, else ``None`` (booleans rejected)."""

    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_instant(text: Any) -> datetime | None:
    """Parse an ISO8601 string to an aware UTC ``datetime`` (None if unusable)."""

    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _bucket_value(entry: Mapping[str, Any]) -> float | None:
    """Representative numeric value of a PMF bucket from its label.

    Accepts ``{"label": ..., "probability": ...}`` or ``{"bucket": ..., "p": ...}``.
    The label may be a bare number (``"4.2"``), a ``ge_/le_`` / comparator form
    (``"bucket_ge_4_4"``, ">=4.4", "<4.0"), or a range (``"4.0-4.4"``) whose
    midpoint is used.
    """

    label = entry.get("label", entry.get("bucket"))
    if label is None:
        return None
    if isinstance(label, (int, float)) and not isinstance(label, bool):
        return float(label) if math.isfinite(float(label)) else None
    text = str(label).strip().lower()

    # Pull every number out of the label, normalising underscores used as
    # decimal separators in storage keys like ``bucket_ge_4_4`` → ``4.4``.
    nums: list[float] = []
    for token in re.findall(r"-?\d+(?:\.\d+)?", text.replace("_", ".")):
        try:
            value = float(token)
        except ValueError:
            continue
        if math.isfinite(value):
            nums.append(value)
    if not nums:
        return None
    if len(nums) >= 2:
        return (nums[0] + nums[1]) / 2.0   # range midpoint
    return nums[0]


def _bucket_prob(entry: Mapping[str, Any]) -> float | None:
    """Probability mass of a PMF bucket (``probability`` or ``p`` key)."""

    return _coerce_float(entry.get("probability", entry.get("p")))


# ── §2.1 + §2.6: per-member signal s_raw and its 0..1-unit dispersion sigma ──


def _binary_signal(member: Mapping[str, Any]) -> tuple[float | None, float, str | None]:
    """Binary member → (s_raw, sigma, flag). sigma is the Bernoulli proxy."""

    p = _coerce_float(member.get("probability"))
    if p is None:
        return None, 0.0, None
    p = _clamp(p, _S_BAND_EPS, 1.0 - _S_BAND_EPS)
    sigma = math.sqrt(p * (1.0 - p))
    return p, sigma, "bernoulli_proxy"


def _pmf_signal(
    pmf: Sequence[Mapping[str, Any]], target: float, hi_is_good: bool
) -> tuple[float | None, float, str | None]:
    """PMF mass past ``target`` (exact, no parametric assumption) + pmf sigma."""

    pairs: list[tuple[float, float]] = []
    total = 0.0
    for entry in pmf:
        if not isinstance(entry, Mapping):
            continue
        value = _bucket_value(entry)
        prob = _bucket_prob(entry)
        if value is None or prob is None or prob < 0:
            continue
        pairs.append((value, prob))
        total += prob
    if not pairs or total <= 0:
        return None, 0.0, None

    # Good side of the target. hi_is_good → values strictly above target are good.
    good = 0.0
    for value, prob in pairs:
        is_good = value > target if hi_is_good else value < target
        if is_good:
            good += prob
    s_raw = _clamp(good / total, 0.0, 1.0)

    # sigma of the *signal* lives in 0..1 units; the pmf's own sd is in outcome
    # units and is not directly comparable. Use the Bernoulli proxy of the
    # past-target mass — an honest 0..1-unit dispersion for a probability.
    sigma = math.sqrt(s_raw * (1.0 - s_raw))
    return s_raw, sigma, "pmf_mass"


def _normal_threshold_signal(
    mean: float, sd: float, target: float, hi_is_good: bool
) -> tuple[float, float, str]:
    """Phi((mean-target)/sd) with a slope-mapped 0..1-unit sigma."""

    s_raw = normal_cdf(mean, target, sd)   # == Phi((mean - target) / sd)
    if not hi_is_good:
        s_raw = 1.0 - s_raw
    s_raw = _clamp(s_raw, 0.0, 1.0)
    # Map the native sd into signal space via the local slope of s_raw wrt mean:
    #   d/dmean Phi((mean-target)/sd) = phi((mean-target)/sd) / sd
    # so delta_s ≈ phi(z)/sd * sd = phi(z); clamp to [0, 0.5] (phi(0)≈0.399).
    z = (mean - target) / sd
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    sigma = _clamp(phi, 0.0, 0.5)
    return s_raw, sigma, "normal_threshold"


def _bounds_from_dist(dist: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Lo/hi bounds for the min-max map: explicit ``lo``/``hi`` else ``ci90``."""

    lo = _coerce_float(dist.get("lo", dist.get("low")))
    hi = _coerce_float(dist.get("hi", dist.get("high")))
    if lo is None or hi is None:
        ci90 = dist.get("ci90")
        if isinstance(ci90, (list, tuple)) and len(ci90) == 2:
            lo = _coerce_float(ci90[0]) if lo is None else lo
            hi = _coerce_float(ci90[1]) if hi is None else hi
    return lo, hi


def _distribution_signal(
    member: Mapping[str, Any]
) -> tuple[float | None, float, str | None]:
    """Reduce a (already-summarised) distribution member to (s_raw, sigma, flag).

    Priority order per §2.1: PMF-mass → normal-threshold → bounded min-max.
    """

    dist = member.get("dist")
    if not isinstance(dist, Mapping):
        return None, 0.0, None
    target = _coerce_float(member.get("target"))
    hi_is_good = bool(member.get("hi_is_good", True))

    pmf = dist.get("pmf")
    mean = _coerce_float(dist.get("mean"))
    sd = _coerce_float(dist.get("sd"))

    # 1. PMF mass past target — exact, preferred.
    if isinstance(pmf, Sequence) and not isinstance(pmf, (str, bytes)) and pmf and target is not None:
        s_raw, sigma, flag = _pmf_signal(pmf, target, hi_is_good)
        if s_raw is not None:
            return s_raw, sigma, flag

    # 2. Threshold-on-normal.
    if mean is not None and sd is not None and sd > 0 and target is not None:
        return _normal_threshold_signal(mean, sd, target, hi_is_good)

    # 3. Bounded index / min-max.
    if mean is not None:
        lo, hi = _bounds_from_dist(dist)
        if lo is not None and hi is not None and hi > lo:
            s_raw = _clamp((mean - lo) / (hi - lo), 0.0, 1.0)
            if not hi_is_good:
                s_raw = 1.0 - s_raw
            # No calibrated dispersion → degenerate point map (no band weight).
            return s_raw, 0.0, "point_map_degenerate"

    return None, 0.0, None


# ── §2.3: staleness → freshness multiplier ──────────────────────────────────


def _freshness(
    age_days: float | None, max_age_days: float | None
) -> tuple[float, str | None]:
    """Map member age to a freshness multiplier (§2.3). None age → fresh."""

    max_age = max_age_days if (max_age_days and max_age_days > 0) else _DEFAULT_MAX_AGE_DAYS
    if age_days is None:
        return 1.0, None
    if age_days <= max_age:
        return 1.0, None
    if age_days <= 2.0 * max_age:
        decayed = 1.0 - (age_days - max_age) / max_age
        return _clamp(decayed, 0.15, 1.0), None
    return 0.0, "stale"


# ── Output dataclass ─────────────────────────────────────────────────────────


@dataclass
class ThesisAggregate:
    """Aggregated thesis-level belief with an honest, correlated band.

    All ``None`` headline fields mean *withheld, not fabricated*: either no
    usable member signal (``health``/``thesis_score`` None) or no calibrated
    dispersion (``band`` None). ``components`` always lists every input member
    (even weight-0 / unusable rows) for auditability.
    """

    health: float | None              # 0..1 log-odds-pooled health probability
    thesis_score: float | None        # 0..100 weighted-mean score
    band: tuple[float, float, float] | None  # (q05, q50, q95) on the 0..100 scale
    coverage: float                   # sum(w_eff) / sum(weight_raw) ∈ (0, 1]
    n_eff: float                      # Kish-style effective sample size
    rho: float                        # correlation actually applied
    components: list[dict[str, Any]]  # per-member breakdown (see module docstring)
    spread: dict[str, float]          # disagreement summary over usable s_i
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Compact ledger payload; omits band keys when the band is withheld."""

        payload: dict[str, Any] = {
            "health": self.health,
            "thesis_score": self.thesis_score,
            "coverage": self.coverage,
            "n_eff": self.n_eff,
        }
        if self.band is not None:
            payload["q05"], payload["q50"], payload["q95"] = self.band
        return payload


# ── Internal: assemble usable rows ───────────────────────────────────────────


@dataclass
class _Row:
    member_id: str
    title: str | None
    kind: str
    direction: str
    weight_raw: float
    as_of: str | None
    s_raw: float | None
    s_i: float | None
    sigma: float
    fresh: float
    w_eff: float
    status: str
    flags: list[str]


def _build_row(member: Mapping[str, Any], now: datetime | None) -> _Row:
    """Compute s_raw, direction-flipped s_i, sigma, freshness and w_eff."""

    member_id = str(member.get("member_id", ""))
    title = member.get("title")
    kind = str(member.get("kind", "")).lower()
    direction = str(member.get("direction", "support")).lower()
    weight_raw = _coerce_float(member.get("weight")) or 0.0
    if weight_raw < 0:
        weight_raw = 0.0
    as_of = member.get("as_of") if isinstance(member.get("as_of"), str) else None
    flags: list[str] = []

    # §2.1 raw signal + 0..1-unit sigma.
    if kind == "binary":
        s_raw, sigma, flag = _binary_signal(member)
    elif kind == "distribution":
        s_raw, sigma, flag = _distribution_signal(member)
    else:
        s_raw, sigma, flag = None, 0.0, None
    if flag:
        flags.append(flag)

    # §2.3 staleness. Age needs both an as_of and a `now` reference.
    age_days: float | None = None
    instant = _parse_instant(as_of)
    if instant is not None and now is not None:
        age_days = max(0.0, (now - instant).total_seconds() / 86400.0)
    fresh, stale_flag = _freshness(age_days, _coerce_float(member.get("max_age_days")))

    # Determine status + effective weight (down-weight, never silent-drop).
    if s_raw is None:
        status = "unusable"
        flags.append("unusable")
        fresh = 0.0
        s_i: float | None = None
    else:
        # §2.2 direction flip applied LAST and uniformly.
        s_i = s_raw if direction != "inverted" else 1.0 - s_raw
        if instant is None and as_of is not None:
            # An as_of we couldn't parse is a missing snapshot for staleness.
            flags.append("missing")
            fresh = 0.0
        if stale_flag:
            flags.append(stale_flag)
        if fresh <= 0.0:
            status = "stale" if stale_flag else ("missing" if "missing" in flags else "zeroed")
        else:
            status = "ok"

    w_eff = weight_raw * fresh
    return _Row(
        member_id=member_id,
        title=title,
        kind=kind,
        direction=direction,
        weight_raw=weight_raw,
        as_of=as_of,
        s_raw=s_raw,
        s_i=s_i,
        sigma=sigma if s_i is not None else 0.0,
        fresh=fresh,
        w_eff=w_eff,
        status=status,
        flags=flags,
    )


def _pooled_health(rows: Sequence[_Row], w_norm: Sequence[float]) -> float:
    """§2.4 log-odds pool of s_i with extremize factor hard-fixed to 1.0."""

    total = 0.0
    for row, wn in zip(rows, w_norm):
        if row.s_i is None or wn <= 0:
            continue
        total += wn * logit(_clamp(row.s_i, _LOGIT_EPS, 1.0 - _LOGIT_EPS))
    return inv_logit(_EXTREMIZE_FACTOR * total)


def _spread_summary(values: Sequence[float]) -> dict[str, float]:
    """Disagreement summary {min,p25,median,p75,max,iqr} over usable s_i."""

    if not values:
        return {}
    ordered = sorted(values)

    def _quantile(q: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = q * (len(ordered) - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[lo]
        frac = pos - lo
        return ordered[lo] * (1.0 - frac) + ordered[hi] * frac

    p25 = _quantile(0.25)
    p75 = _quantile(0.75)
    return {
        "min": ordered[0],
        "p25": p25,
        "median": _quantile(0.5),
        "p75": p75,
        "max": ordered[-1],
        "iqr": p75 - p25,
    }


# ── Public entry point ───────────────────────────────────────────────────────


def aggregate_thesis(
    members: Sequence[Mapping[str, Any]],
    *,
    rho: float | str = 0.4,
    now: str | None = None,
    correlation_matrix: Mapping[Any, float] | None = None,
) -> ThesisAggregate:
    """Aggregate weighted member beliefs into a thesis-level health/score/band.

    Args:
        members: list of member dicts (see module docstring / input contract).
        rho: pairwise correlation for the honest variance (§2.6). A float in
            ``[0, 0.95]`` is used as a constant. ``"estimate"`` derives
            ``rho = clamp(0.6 - 0.25*spread_of_s, 0, 0.95)`` from the spread of
            usable signals. **Independence (rho == 0) is only honoured when the
            caller passes the explicit float ``0.0``** — it is never a default.
        now: ISO8601 reference instant for staleness. ``None`` treats every
            member as fresh (no ``datetime.now`` is ever called here).

    Returns:
        A :class:`ThesisAggregate`. Headline fields are ``None`` (withheld, not
        fabricated) when there is no usable signal or no calibrated dispersion.
    """

    now_dt = _parse_instant(now)
    rows = [_build_row(member, now_dt) for member in members]

    weight_raw_total = sum(r.weight_raw for r in rows)
    W = sum(r.w_eff for r in rows)
    coverage = (W / weight_raw_total) if weight_raw_total > 0 else 0.0

    # §2.3 all-stale / all-missing guard: withhold rather than emit a number.
    if W <= 0:
        components = [_component_row(r, w_norm=0.0, contribution=0.0, marginal=0.0)
                     for r in rows]
        return ThesisAggregate(
            health=None,
            thesis_score=None,
            band=None,
            coverage=0.0,
            n_eff=0.0,
            rho=(0.4 if rho == "estimate" else float(rho) if isinstance(rho, (int, float)) else 0.4),
            components=components,
            spread={},
            notes=["withheld: no usable member signal (not fabricated)"],
        )

    w_norm = [r.w_eff / W for r in rows]
    usable_idx = [i for i, r in enumerate(rows) if r.s_i is not None and r.w_eff > 0]
    usable_s = [rows[i].s_i for i in usable_idx]  # type: ignore[misc]

    # ── rho resolution (§2.6) ────────────────────────────────────────────────
    notes: list[str] = []
    if isinstance(rho, str):
        if rho == "estimate":
            spread_of_s = (max(usable_s) - min(usable_s)) if len(usable_s) > 1 else 0.0
            rho_val = _clamp(0.6 - 0.25 * spread_of_s, 0.0, 0.95)
        else:
            raise ValueError(f"rho must be a float or 'estimate', got {rho!r}")
    else:
        rho_val = _clamp(float(rho), 0.0, 0.95)

    # Optional pairwise correlation MATRIX: members co-move UNEQUALLY (coding<->
    # nvidia tighter than coding<->power), so a thesis can supply real pairwise
    # correlations that override the scalar rho per pair (falling back to rho_val
    # where a pair is unspecified). Keys accepted as {a,b} / (a,b) / "a:b" / "a|b".
    norm_corr: dict[frozenset[str], float] = {}
    if correlation_matrix:
        for key, value in correlation_matrix.items():
            if isinstance(key, (frozenset, set, tuple, list)):
                ids = frozenset(str(k) for k in key)
            elif isinstance(key, str) and ("|" in key or ":" in key):
                ids = frozenset(key.split("|" if "|" in key else ":", 1))
            else:
                ids = frozenset()
            if len(ids) == 2:
                norm_corr[ids] = _clamp(float(value), 0.0, 0.95)
        if norm_corr:
            notes.append(f"pairwise correlation matrix applied ({len(norm_corr)} pair(s))")

    def _pair_rho(i: int, j: int) -> float:
        if i == j:
            return 1.0
        if norm_corr:
            paired = norm_corr.get(frozenset({rows[i].member_id, rows[j].member_id}))
            if paired is not None:
                return paired
        return rho_val

    # ── §2.4 health (log-odds pool) ──────────────────────────────────────────
    health = _pooled_health(rows, w_norm)

    # ── §2.5 score (weighted arithmetic mean) ────────────────────────────────
    score = 100.0 * sum(wn * (r.s_i or 0.0) for r, wn in zip(rows, w_norm) if r.s_i is not None)

    # ── §2.6 honest correlated band ──────────────────────────────────────────
    sigmas = [r.sigma for r in rows]
    has_dispersion = any(rows[i].sigma > 0 for i in usable_idx)
    only_binary = all(rows[i].kind == "binary" for i in usable_idx) if usable_idx else True

    band: tuple[float, float, float] | None
    if not has_dispersion or only_binary:
        band = None
        notes.append("no calibrated dispersion; band withheld")
    else:
        var = 0.0
        for i in range(len(rows)):
            if rows[i].s_i is None:
                continue
            for j in range(len(rows)):
                if rows[j].s_i is None:
                    continue
                rho_ij = _pair_rho(i, j)
                var += w_norm[i] * w_norm[j] * rho_ij * sigmas[i] * sigmas[j]
        sd_score = 100.0 * math.sqrt(max(var, 0.0))
        q05 = _clamp(score - _Z90 * sd_score, 0.0, 100.0)
        q95 = _clamp(score + _Z90 * sd_score, 0.0, 100.0)
        band = (q05, score, q95)

    # ── n_eff: Kish-style effective N with the correlation matrix R ───────────
    # n_eff = (sum w_eff)^2 / (w_eff^T R w_eff). With unit diagonal and rho off-
    # diagonal, the denominator inflates with correlation, so n_eff < n_members.
    denom = 0.0
    for i in range(len(rows)):
        for j in range(len(rows)):
            rho_ij = _pair_rho(i, j)
            denom += rows[i].w_eff * rows[j].w_eff * rho_ij
    n_eff = (W * W / denom) if denom > 0 else 0.0

    # ── §2.7 per-member contributions + leave-one-out marginals ──────────────
    components: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        contribution = 100.0 * w_norm[idx] * (row.s_i or 0.0) if row.s_i is not None else 0.0
        marginal = _leave_one_out_delta(rows, idx, health, W)
        components.append(_component_row(row, w_norm[idx], contribution, marginal))

    spread = _spread_summary([s for s in usable_s])

    return ThesisAggregate(
        health=health,
        thesis_score=score,
        band=band,
        coverage=coverage,
        n_eff=n_eff,
        rho=rho_val,
        components=components,
        spread=spread,
        notes=notes,
    )


def _leave_one_out_delta(
    rows: Sequence[_Row], drop: int, health_all: float, W_all: float
) -> float:
    """health(all) - health(all but ``drop``) on the renormalised pool."""

    dropped = rows[drop]
    if dropped.s_i is None or dropped.w_eff <= 0:
        return 0.0
    W_rest = W_all - dropped.w_eff
    if W_rest <= 0:
        return 0.0   # the only contributor — undefined "all but i"
    total = 0.0
    for i, row in enumerate(rows):
        if i == drop or row.s_i is None or row.w_eff <= 0:
            continue
        wn = row.w_eff / W_rest
        total += wn * logit(_clamp(row.s_i, _LOGIT_EPS, 1.0 - _LOGIT_EPS))
    health_rest = inv_logit(_EXTREMIZE_FACTOR * total)
    return health_all - health_rest


def _component_row(
    row: _Row, w_norm: float, contribution: float, marginal: float
) -> dict[str, Any]:
    """Serialise one member row to the components payload shape."""

    return {
        "member_id": row.member_id,
        "title": row.title,
        "kind": row.kind,
        "direction": row.direction,
        "weight": row.weight_raw,
        "w_norm": w_norm,
        "s_raw": row.s_raw,
        "s_i": row.s_i,
        "sigma": row.sigma,
        "contribution_pts": contribution,
        "marginal_health_delta": marginal,
        "as_of": row.as_of,
        "status": row.status,
        "flags": list(row.flags),
    }


# ════════════════════════════════════════════════════════════════════════════
# EVENT-PROBABILITY LAYER — a thesis as a JOINT THRESHOLD EVENT, not a mean index
# ════════════════════════════════════════════════════════════════════════════
#
# ``aggregate_thesis`` above returns a *mean index* (a weighted-mean health/score
# with a correlated band). But a thesis like "Democrats take back the Senate" is
# a **joint threshold event**: P(number of member successes ≥ K). A mean is
# damped and threshold-insensitive — it moves ~linearly with each member and can
# barely twitch when a battleground crosses 50%, even though the *event* pivots
# there. And correlation, which only ever entered the mean's BAND, is first-class
# for the event: co-moving races collapse toward all-or-nothing.
#
# This layer answers the operator's exact complaint — "I'd have thought it would
# use some kind of monte carlo... it isn't treated equally to the underlying
# questions" — with a Gaussian-copula Monte Carlo over the SAME binary member
# beliefs the mean consumes, seeded deterministically by the caller.

# Finite-difference bump for the per-member P(event) sensitivity ("which race
# matters"): re-score with p_i ± 2pp on the SAME latent draws.
_EVENT_DELTA = 0.02
# Keep member probabilities strictly interior so ``normal_ppf`` stays finite.
_PPF_EPS = 1e-6
# Draw counts: numpy fast path vs the pure-python fallback (kept small so it
# stays snappy offline). Explicit ``n_draws`` overrides the numpy default.
_EVENT_DRAWS_NUMPY = 20_000
_EVENT_DRAWS_PYTHON = 2_000
# Cholesky jitter ladder — pairwise correlation overrides can make Σ indefinite;
# nudging the diagonal recovers the nearest usable PD matrix (with a note).
_CHOL_JITTER = (0.0, 1e-9, 1e-7, 1e-5, 1e-3)


@dataclass
class ThesisEventResult:
    """P(joint threshold event) for a thesis, from a Gaussian-copula MC.

    ``event_probability`` is ``None`` (withheld, not fabricated) when no binary
    member participates. The count distribution + per-member sensitivities are
    the readouts a mean index can never give: the shape of the seat count and
    *which* member most moves the event.
    """

    event_probability: float | None
    event: dict[str, Any]                     # echoed spec incl. resolved threshold K
    count_distribution: dict[str, float]      # {p10, p50, p90, mean} of #successes
    sensitivities: list[dict[str, Any]]       # per participating member: ∂P/∂p_i
    participants: int                         # binary members in the event
    excluded: list[dict[str, Any]]            # non-binary / unusable members + why
    backend: str                              # "numpy" | "python"
    n_draws: int
    rho: float
    seed: int
    notes: list[str] = field(default_factory=list)

    def top_sensitivities(self, k: int = 5) -> list[dict[str, Any]]:
        """The ``k`` members whose ±2pp move swings P(event) most (by |Δ|)."""

        return sorted(
            self.sensitivities,
            key=lambda s: -abs(s.get("delta_p_event") or 0.0),
        )[:k]

    def to_payload(self) -> dict[str, Any]:
        """Compact dict stamped into the thesis snapshot alongside the mean index."""

        return {
            "event_probability": self.event_probability,
            "event": self.event,
            "count_distribution": self.count_distribution,
            "top_sensitivities": self.top_sensitivities(5),
        }


def _normalize_event_corr(
    correlation_matrix: Mapping[Any, float] | None
) -> dict[frozenset[str], float]:
    """Parse a pairwise correlation map into {member_a, member_b} -> rho.

    Same key-shape resolution as :func:`aggregate_thesis` ({a,b} / (a,b) /
    "a:b" / "a|b"), clamped to the honest ``[0, 0.95]`` band.
    """

    norm: dict[frozenset[str], float] = {}
    if not correlation_matrix:
        return norm
    for key, value in correlation_matrix.items():
        if isinstance(key, (frozenset, set, tuple, list)):
            ids = frozenset(str(k) for k in key)
        elif isinstance(key, str) and ("|" in key or ":" in key):
            ids = frozenset(key.split("|" if "|" in key else ":", 1))
        else:
            ids = frozenset()
        if len(ids) == 2:
            coerced = _coerce_float(value)
            if coerced is not None:
                norm[ids] = _clamp(coerced, 0.0, 0.95)
    return norm


def _build_corr_matrix(
    ids: Sequence[str], rho_val: float, pairwise: Mapping[frozenset[str], float]
) -> list[list[float]]:
    """n×n correlation matrix: unit diagonal, scalar ``rho_val`` off-diagonal,
    with per-pair overrides (members co-move UNEQUALLY)."""

    n = len(ids)
    matrix = [[1.0 if i == j else rho_val for j in range(n)] for i in range(n)]
    if pairwise:
        for i in range(n):
            for j in range(i + 1, n):
                override = pairwise.get(frozenset({ids[i], ids[j]}))
                if override is not None:
                    matrix[i][j] = matrix[j][i] = override
    return matrix


def _cholesky_py(matrix: Sequence[Sequence[float]]) -> list[list[float]] | None:
    """Lower-triangular Cholesky factor L (Σ = L Lᵀ); None if not PD."""

    n = len(matrix)
    L = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1):
            s = sum(L[i][k] * L[j][k] for k in range(j))
            if i == j:
                d = matrix[i][i] - s
                if d <= 0:
                    return None
                L[i][j] = math.sqrt(d)
            else:
                L[i][j] = (matrix[i][j] - s) / L[j][j]
    return L


def _cholesky_with_jitter(
    matrix: list[list[float]], *, use_numpy: bool
) -> tuple[Any, str | None]:
    """Cholesky with a jitter ladder for near-singular Σ from pair overrides.

    Returns (L, note) where L is a numpy array (fast path) or list-of-lists
    (fallback). ``note`` flags when the diagonal was nudged to recover PD-ness.
    """

    n = len(matrix)
    for jitter in _CHOL_JITTER:
        trial = matrix
        if jitter > 0:
            trial = [
                [matrix[i][j] + (jitter if i == j else 0.0) for j in range(n)]
                for i in range(n)
            ]
        if use_numpy:
            try:
                L = _np.linalg.cholesky(_np.asarray(trial, dtype=float))
            except Exception:
                continue
        else:
            L = _cholesky_py(trial)
            if L is None:
                continue
        note = None if jitter == 0 else f"correlation matrix jittered ({jitter:g}) to nearest PD"
        return L, note
    # Total fallback: independence (identity). Should be unreachable for rho∈[0,0.95].
    if use_numpy:
        return _np.eye(n), "correlation matrix not PD; fell back to independence"
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)], (
        "correlation matrix not PD; fell back to independence"
    )


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile over a pre-sorted sequence."""

    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _sensitivity_rows(
    parts: Sequence[dict[str, Any]],
    p_event: float,
    plus: Sequence[float],
    minus: Sequence[float],
    deltas: Sequence[float],
) -> list[dict[str, Any]]:
    """Assemble the per-member ∂P/∂p_i readout from the re-scored MC estimates."""

    rows: list[dict[str, Any]] = []
    for part, pe_plus, pe_minus, denom in zip(parts, plus, minus, deltas):
        swing = pe_plus - pe_minus
        rows.append({
            "member_id": part["member_id"],
            "title": part["title"],
            "direction": part["direction"],
            "p": part["p"],
            # ∂P(event)/∂p_i on the SAME draws (the honest "which race matters").
            "sensitivity": (swing / denom) if denom else 0.0,
            # Total P(event) swing across the ±2pp bump (already event-scaled).
            "delta_p_event": swing,
            "p_event_at_plus": pe_plus,
            "p_event_at_minus": pe_minus,
        })
    return rows


def _simulate_numpy(
    p_vec: Sequence[float], counter: Sequence[bool], matrix: list[list[float]],
    K: int, n_draws: int, seed: int,
) -> tuple[float, dict[str, float], list[float], list[float], list[float], str | None]:
    """Vectorised Gaussian-copula MC. success_i = (z_i < Φ⁻¹(p_i)) XOR counter_i."""

    np = _np
    n = len(p_vec)
    L, note = _cholesky_with_jitter(matrix, use_numpy=True)
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal((n_draws, n)) @ L.T            # correlated latents
    thresholds = np.array([normal_ppf(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in p_vec])
    counter_arr = np.asarray(counter, dtype=bool)
    raw = Z < thresholds                                   # (draws, n) underlying-yes
    success = raw ^ counter_arr                            # counter → NOT the event
    succ_int = success.astype(np.int64)
    counts = succ_int.sum(axis=1)
    p_event = float(np.mean(counts >= K))
    dist = {
        "p10": float(np.percentile(counts, 10)),
        "p50": float(np.percentile(counts, 50)),
        "p90": float(np.percentile(counts, 90)),
        "mean": float(np.mean(counts)),
    }

    plus: list[float] = []
    minus: list[float] = []
    deltas: list[float] = []
    for i in range(n):
        zc = Z[:, i]
        base = counts - succ_int[:, i]                     # drop member i's contribution
        p_plus = min(1.0 - _PPF_EPS, p_vec[i] + _EVENT_DELTA)
        p_minus = max(_PPF_EPS, p_vec[i] - _EVENT_DELTA)
        raw_p = zc < normal_ppf(p_plus)
        raw_m = zc < normal_ppf(p_minus)
        s_p = (raw_p ^ counter[i]).astype(np.int64)
        s_m = (raw_m ^ counter[i]).astype(np.int64)
        plus.append(float(np.mean((base + s_p) >= K)))
        minus.append(float(np.mean((base + s_m) >= K)))
        deltas.append(p_plus - p_minus)
    return p_event, dist, plus, minus, deltas, note


def _simulate_python(
    p_vec: Sequence[float], counter: Sequence[bool], matrix: list[list[float]],
    K: int, n_draws: int, seed: int,
) -> tuple[float, dict[str, float], list[float], list[float], list[float], str | None]:
    """Pure-stdlib Gaussian-copula MC (deterministic via ``random.Random(seed)``)."""

    n = len(p_vec)
    L, note = _cholesky_with_jitter(matrix, use_numpy=False)
    rng = random.Random(seed)
    thresholds = [normal_ppf(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in p_vec]

    z_cols: list[list[float]] = [[0.0] * n_draws for _ in range(n)]
    succ_cols: list[list[int]] = [[0] * n_draws for _ in range(n)]
    counts = [0] * n_draws
    for d in range(n_draws):
        x = [rng.gauss(0.0, 1.0) for _ in range(n)]
        cnt = 0
        for i in range(n):
            Li = L[i]
            zi = 0.0
            for k in range(i + 1):
                zi += Li[k] * x[k]
            z_cols[i][d] = zi
            raw = zi < thresholds[i]
            success = (not raw) if counter[i] else raw
            si = 1 if success else 0
            succ_cols[i][d] = si
            cnt += si
        counts[d] = cnt
    ge = sum(1 for c in counts if c >= K)
    p_event = ge / n_draws
    ordered = sorted(counts)
    dist = {
        "p10": _quantile(ordered, 0.10),
        "p50": _quantile(ordered, 0.50),
        "p90": _quantile(ordered, 0.90),
        "mean": sum(counts) / n_draws,
    }

    plus: list[float] = []
    minus: list[float] = []
    deltas: list[float] = []
    for i in range(n):
        p_plus = min(1.0 - _PPF_EPS, p_vec[i] + _EVENT_DELTA)
        p_minus = max(_PPF_EPS, p_vec[i] - _EVENT_DELTA)
        t_plus = normal_ppf(p_plus)
        t_minus = normal_ppf(p_minus)
        zc = z_cols[i]
        sc = succ_cols[i]
        ge_p = 0
        ge_m = 0
        for d in range(n_draws):
            base = counts[d] - sc[d]
            raw_p = zc[d] < t_plus
            raw_m = zc[d] < t_minus
            s_p = (not raw_p) if counter[i] else raw_p
            s_m = (not raw_m) if counter[i] else raw_m
            if base + (1 if s_p else 0) >= K:
                ge_p += 1
            if base + (1 if s_m else 0) >= K:
                ge_m += 1
        plus.append(ge_p / n_draws)
        minus.append(ge_m / n_draws)
        deltas.append(p_plus - p_minus)
    return p_event, dist, plus, minus, deltas, note


def simulate_thesis_event(
    members: Sequence[Mapping[str, Any]],
    event: Mapping[str, Any],
    *,
    rho: float | str = 0.4,
    correlation_matrix: Mapping[Any, float] | None = None,
    n_draws: int | None = None,
    seed: int = 0,
) -> ThesisEventResult:
    """Monte-Carlo P(joint threshold event) over a thesis's binary members.

    The thesis headline that ``aggregate_thesis`` reports is a mean index —
    damped and threshold-insensitive. This treats the thesis as the event it
    actually is: P(#member successes ≥ K), via a **Gaussian copula** so that
    correlation (which only ever entered the mean's band) drives the headline.

    Args:
        members: the SAME belief rows ``aggregate_thesis`` consumes. Only binary
            members participate; distribution members are excluded (with a note).
        event: ``{"kind": "count_threshold", "threshold": K}`` | ``{"kind": "all"}``
            | ``{"kind": "any"}``. ``all`` → K = #participants; ``any`` → K = 1.
        rho: scalar pairwise correlation (float in ``[0, 0.95]``) or ``"estimate"``
            (derived from the spread of the participating probabilities), resolved
            exactly as in :func:`aggregate_thesis`.
        correlation_matrix: optional per-pair overrides (members co-move
            unequally), same key-shapes as :func:`aggregate_thesis`.
        n_draws: MC draws. Defaults to 20k on the numpy fast path, 2k on the
            pure-python fallback. Determinism is per-path: the same ``seed``
            reproduces the same result on the same backend.
        seed: deterministic RNG seed. The CALLER derives it from (thesis_id,
            as_of) — this function never touches ``Date.now`` or a global RNG.

    Returns:
        A :class:`ThesisEventResult`. ``event_probability`` is ``None`` (withheld,
        not fabricated) when no binary member participates.
    """

    kind = str(event.get("kind", "")).lower()
    if kind not in {"count_threshold", "all", "any"}:
        raise ValueError(
            f"event kind must be 'count_threshold', 'all' or 'any', got {kind!r}"
        )

    # ── Participants: binary members only; everything else is excluded (honest) ─
    parts: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for member in members:
        member_id = str(member.get("member_id", ""))
        title = member.get("title")
        mkind = str(member.get("kind", "")).lower()
        if mkind != "binary":
            excluded.append({
                "member_id": member_id, "title": title, "kind": mkind or "unknown",
                "reason": "non-binary member excluded from the count event",
            })
            continue
        p = _coerce_float(member.get("probability"))
        if p is None:
            excluded.append({
                "member_id": member_id, "title": title, "kind": "binary",
                "reason": "no usable probability",
            })
            continue
        direction = str(member.get("direction", "support")).lower()
        parts.append({
            "member_id": member_id,
            "title": title,
            "direction": direction,
            "p": _clamp(p, 0.0, 1.0),
            "counter": direction == "inverted",
        })

    notes: list[str] = []
    if excluded:
        n_dist = sum(1 for e in excluded if e["kind"] not in {"binary", "unknown"})
        if n_dist:
            notes.append(
                f"{n_dist} distribution member(s) excluded from the event "
                "(a count threshold is defined over binary members only)"
            )
        n_bad = sum(1 for e in excluded if e["reason"] == "no usable probability")
        if n_bad:
            notes.append(f"{n_bad} binary member(s) had no usable probability")

    n = len(parts)

    # ── Resolve the threshold K from the event kind ──────────────────────────
    if kind == "all":
        K = n
    elif kind == "any":
        K = 1
    else:
        raw_k = event.get("threshold")
        if raw_k is None:
            raise ValueError("count_threshold event requires an integer 'threshold'")
        try:
            K = int(raw_k)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"threshold must be an integer, got {raw_k!r}") from exc
    event_echo = {"kind": kind, "threshold": K, "participants": n}

    # Withhold rather than fabricate when nothing participates.
    if n == 0:
        notes.append("withheld: no binary member participates in the event")
        return ThesisEventResult(
            event_probability=None, event=event_echo,
            count_distribution={}, sensitivities=[], participants=0,
            excluded=excluded, backend="none", n_draws=0,
            rho=(0.4 if rho == "estimate" else float(rho) if isinstance(rho, (int, float)) else 0.4),
            seed=seed, notes=notes,
        )

    # ── rho resolution (mirrors aggregate_thesis) ────────────────────────────
    if isinstance(rho, str):
        if rho == "estimate":
            ps = [part["p"] for part in parts]
            spread = (max(ps) - min(ps)) if len(ps) > 1 else 0.0
            rho_val = _clamp(0.6 - 0.25 * spread, 0.0, 0.95)
        else:
            raise ValueError(f"rho must be a float or 'estimate', got {rho!r}")
    else:
        rho_val = _clamp(float(rho), 0.0, 0.95)

    pairwise = _normalize_event_corr(correlation_matrix)
    if pairwise:
        notes.append(f"pairwise correlation matrix applied ({len(pairwise)} pair(s))")
    ids = [part["member_id"] for part in parts]
    matrix = _build_corr_matrix(ids, rho_val, pairwise)

    p_vec = [part["p"] for part in parts]
    counter = [part["counter"] for part in parts]

    # ── Backend selection + draw count ───────────────────────────────────────
    use_numpy = _np is not None
    if n_draws is None:
        draws = _EVENT_DRAWS_NUMPY if use_numpy else _EVENT_DRAWS_PYTHON
    else:
        draws = max(int(n_draws), 1)
        if not use_numpy and draws > _EVENT_DRAWS_PYTHON:
            # Keep the stdlib fallback snappy; note the honest cap.
            draws = _EVENT_DRAWS_PYTHON
            notes.append(f"pure-python fallback: n_draws capped to {_EVENT_DRAWS_PYTHON}")
    backend = "numpy" if use_numpy else "python"

    simulate = _simulate_numpy if use_numpy else _simulate_python
    p_event, dist, plus, minus, deltas, chol_note = simulate(
        p_vec, counter, matrix, K, draws, seed
    )
    if chol_note:
        notes.append(chol_note)

    sensitivities = _sensitivity_rows(parts, p_event, plus, minus, deltas)

    return ThesisEventResult(
        event_probability=p_event,
        event=event_echo,
        count_distribution=dist,
        sensitivities=sensitivities,
        participants=n,
        excluded=excluded,
        backend=backend,
        n_draws=draws,
        rho=rho_val,
        seed=seed,
        notes=notes,
    )


# ════════════════════════════════════════════════════════════════════════════
# EVENT-PROBABILITY BAND — the honest interval ON THE HEADLINE ITSELF
# ════════════════════════════════════════════════════════════════════════════
#
# ``simulate_thesis_event`` returns a POINT P(event). It conditions on member
# POINT probabilities and a POINT rho, so it can only ever be a point — even
# though every one of those inputs is itself uncertain. That is exactly the
# operator's complaint: the thesis headline is published as a dot with no
# interval, and (for an all-binary thesis) the mean-index band is honestly
# WITHHELD because binary members carry no calibrated 0..1-unit dispersion
# (see ``aggregate_thesis``: ``if not has_dispersion or only_binary``).
#
# The epistemically honest interval propagates PARAMETER uncertainty via a
# SECOND-ORDER (nested) Monte Carlo:
#
#   * OUTER loop — draw a parameter set: perturb each member probability in
#     LOGIT space (a member that publishes only a point is not certain; its true
#     probability could differ) and jitter rho over a documented sensitivity
#     range. A member that DOES publish an interval (``p_ci90`` / ``p_sd``)
#     overrides the default width with its own — thin inputs stay honestly wide,
#     rich inputs tighten.
#   * INNER loop — re-run the SAME Gaussian-copula event MC at that parameter
#     draw, sharing ONE base latent matrix across every outer draw (common
#     random numbers). CRN cancels the inner MC noise so the resulting spread is
#     PARAMETER uncertainty, not sampling jitter.
#
# Publishing p10/p50/p90 of the EVENT PROBABILITY itself gives the thesis the
# interval band the site + TUI already know how to render. When no binary member
# participates the band is WITHHELD (never fabricated), mirroring the point sim.

# Default epistemic width for a member that publishes only a POINT probability:
# a std-dev in LOGIT units. 0.35 logit ≈ a ±1σ band of roughly ±4-8pp near the
# middle (tighter in the tails) — "we trust the point, but not to the last few
# points." A member that publishes its own interval overrides this per-member.
_EVENT_BAND_SIGMA_LOGIT = 0.35
# rho is a judgement call, so the band samples it uniformly over rho ± this
# spread (clamped to the honest [0, 0.95]); it is a sensitivity range, not noise.
_EVENT_BAND_RHO_SPREAD = 0.15
# Draw counts. OUTER = parameter draws (the band's resolution); INNER = copula
# draws per parameter set (kept modest — CRN across outer draws means the inner
# noise cancels, so the band needs far fewer inner draws than the point sim).
_EVENT_BAND_OUTER_NUMPY = 200
_EVENT_BAND_INNER_NUMPY = 4_000
_EVENT_BAND_OUTER_PYTHON = 48
_EVENT_BAND_INNER_PYTHON = 600
# Band quantiles reported for the event probability.
_BAND_QUANTILES = (0.10, 0.50, 0.90)

# ── Per-member probability interval (the EARNED-band source) ──────────────────
# Minimum per-model component samples for a trustworthy empirical spread — below
# this the "spread" is noise, so we fall to the documented default (mirrors the
# candidate-interval MIN_SPREAD_SAMPLES precedent).
_MEMBER_SPREAD_MIN_SAMPLES = 3
# Evidence-thinness DEFAULT half-width in LOGIT units for a point-only member:
# base / sqrt(evidence), floored + capped. A single-source member gets the widest
# default; never a fabricated sharpness. (The event band's own point-only fallback
# is a flat sigma=0.35; this default is evidence-tied and carries provenance.)
_MEMBER_DEFAULT_BASE_LOGIT = 0.6
_MEMBER_DEFAULT_MIN_LOGIT = 0.2
_MEMBER_DEFAULT_MAX_LOGIT = 1.0


def derive_member_probability_interval(
    committed_p: Any,
    *,
    component_probs: Sequence[Any] | None = None,
    evidence_count: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A binary member's own 90% probability interval + provenance, in the shipped
    candidate-interval PRECEDENCE (panel spread > evidence-thinness default).

    Returns ``({"p_ci90": [lo, hi]}, {"source", "params"})``. ``p_ci90`` is exactly
    what :func:`simulate_thesis_event_band` consumes to widen/tighten a member's
    parameter draw. When the ensemble priced the member several ways the band is
    EARNED — the empirical p05..p95 spread of the per-model component probabilities.
    Otherwise it is a documented evidence-thinness default centred on the committed
    probability (wider as evidence thins). Never a fabricated tightness.
    """
    cp = _coerce_float(committed_p)
    p = _clamp(cp if cp is not None else 0.5, _LOGIT_EPS, 1.0 - _LOGIT_EPS)
    samples = sorted(
        x for x in (_coerce_float(v) for v in (component_probs or []))
        if x is not None and 0.0 <= x <= 1.0
    )
    # ── source (a): panel / ensemble spread (the earned band) ─────────────────
    if len(samples) >= _MEMBER_SPREAD_MIN_SAMPLES:
        lo = _clamp(_quantile(samples, 0.05), _LOGIT_EPS, 1.0 - _LOGIT_EPS)
        hi = _clamp(_quantile(samples, 0.95), _LOGIT_EPS, 1.0 - _LOGIT_EPS)
        if hi > lo:
            return (
                {"p_ci90": [round(lo, 6), round(hi, 6)]},
                {"source": "panel", "params": {"n_components": len(samples), "method": "empirical_spread_p05_p95"}},
            )
    # ── source (c): evidence-thinness default (logit half-width around p) ─────
    n = max(int(evidence_count or 0), 1)
    hw = _clamp(_MEMBER_DEFAULT_BASE_LOGIT / math.sqrt(n), _MEMBER_DEFAULT_MIN_LOGIT, _MEMBER_DEFAULT_MAX_LOGIT)
    lo = inv_logit(logit(p) - _Z90 * hw)
    hi = inv_logit(logit(p) + _Z90 * hw)
    return (
        {"p_ci90": [round(lo, 6), round(hi, 6)]},
        {"source": "default", "params": {"half_width_logit": round(hw, 4), "evidence_count": int(evidence_count or 0),
                                          "base_logit": _MEMBER_DEFAULT_BASE_LOGIT}},
    )


@dataclass
class ThesisEventBand:
    """A parameter-uncertainty INTERVAL on a thesis's P(event) headline.

    ``p10`` / ``p50`` / ``p90`` are quantiles of the event probability itself
    under a second-order Monte Carlo that propagates member-probability and rho
    uncertainty. All three are ``None`` (withheld, not fabricated) when no binary
    member participates — the same honesty gate as :func:`simulate_thesis_event`.

    The reported band is GUARANTEED to bracket ``center`` (the point headline it
    annotates): the central-in-band invariant an interval must never violate.
    """

    center: float | None                      # the point P(event) the band annotates
    p10: float | None
    p50: float | None
    p90: float | None
    participants: int
    param_draws: int                           # OUTER parameter draws
    inner_draws: int                           # INNER copula draws per parameter set
    rho: float                                 # the point rho the sampling centres on
    rho_spread: float                          # rho sampled over rho ± this (clamped)
    sigma_logit_default: float                 # default logit-space width for point-only members
    members_with_interval: int                 # members whose own interval set the width
    members_defaulted: int                     # members that used the default width
    backend: str                               # "numpy" | "python" | "none"
    seed: int
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Flat numeric band fields for the snapshot payload (headline-scale)."""

        if self.p10 is None or self.p90 is None:
            return {}
        return {
            "event_p10": self.p10,
            "event_p50": self.p50,
            "event_p90": self.p90,
        }


def _member_logit_sigma(part: Mapping[str, Any], default_sigma: float) -> tuple[float, bool]:
    """Per-member logit-space std dev for the parameter draw.

    A member may publish its OWN uncertainty, which overrides the default:
      * ``p_ci90`` == ``[lo, hi]`` → sigma = (logit(hi) - logit(lo)) / (2·z90)
      * ``p_sd``   (0..1 std dev)  → sigma ≈ p_sd / (p·(1-p))   (delta method)
    Returns ``(sigma_logit, used_member_interval)``. Falls back to ``default``
    when the member is point-only (or its published width is unusable).
    """

    p = _clamp(_coerce_float(part.get("p")) or 0.5, _PPF_EPS, 1.0 - _PPF_EPS)
    ci = part.get("p_ci90")
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        lo = _coerce_float(ci[0])
        hi = _coerce_float(ci[1])
        if lo is not None and hi is not None:
            lo = _clamp(lo, _PPF_EPS, 1.0 - _PPF_EPS)
            hi = _clamp(hi, _PPF_EPS, 1.0 - _PPF_EPS)
            if hi > lo:
                sigma = (logit(hi) - logit(lo)) / (2.0 * _Z90)
                if math.isfinite(sigma) and sigma > 0:
                    return sigma, True
    sd = _coerce_float(part.get("p_sd"))
    if sd is not None and sd > 0:
        slope = p * (1.0 - p)
        if slope > 0:
            sigma = sd / slope
            if math.isfinite(sigma) and sigma > 0:
                return sigma, True
    return default_sigma, False


def _event_prob_numpy(
    Z_base: Any, L: Any, p_vec: Sequence[float], counter: Any, K: int
) -> float:
    """P(#successes ≥ K) for ONE parameter set, reusing the base latents Z_base."""

    np = _np
    Z = Z_base @ L.T
    thresholds = np.array([normal_ppf(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in p_vec])
    success = (Z < thresholds) ^ counter
    counts = success.astype(np.int64).sum(axis=1)
    return float(np.mean(counts >= K))


def _simulate_band_numpy(
    p_vec: Sequence[float], counter: Sequence[bool], sigmas: Sequence[float],
    rho_val: float, rho_spread: float, pairwise: Mapping[frozenset[str], float],
    ids: Sequence[str], K: int, inner: int, outer: int, seed: int,
) -> tuple[float, list[float], str | None]:
    """Vectorised second-order MC: returns (point, outer_samples, chol_note)."""

    np = _np
    n = len(p_vec)
    counter_arr = np.asarray(counter, dtype=bool)
    logits = np.array([logit(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in p_vec])
    sig = np.asarray(sigmas, dtype=float)

    # ONE base latent matrix, shared across every outer draw (common random
    # numbers): the outer spread is then PARAMETER uncertainty, not MC noise.
    base_rng = np.random.default_rng(seed)
    Z_base = base_rng.standard_normal((inner, n))

    # Point estimate on the SAME latents (so it sits inside the parameter cloud).
    L0, note = _cholesky_with_jitter(_build_corr_matrix(ids, rho_val, pairwise), use_numpy=True)
    point = _event_prob_numpy(Z_base, L0, p_vec, counter_arr, K)

    param_rng = np.random.default_rng(seed ^ 0x9E3779B9)
    samples: list[float] = []
    for _ in range(outer):
        z = param_rng.standard_normal(n) * sig
        pv = 1.0 / (1.0 + np.exp(-(logits + z)))
        rho_draw = _clamp(rho_val + (param_rng.random() * 2.0 - 1.0) * rho_spread, 0.0, 0.95)
        L, _n = _cholesky_with_jitter(_build_corr_matrix(ids, rho_draw, pairwise), use_numpy=True)
        samples.append(_event_prob_numpy(Z_base, L, pv, counter_arr, K))
    return point, samples, note


def _simulate_band_python(
    p_vec: Sequence[float], counter: Sequence[bool], sigmas: Sequence[float],
    rho_val: float, rho_spread: float, pairwise: Mapping[frozenset[str], float],
    ids: Sequence[str], K: int, inner: int, outer: int, seed: int,
) -> tuple[float, list[float], str | None]:
    """Pure-stdlib second-order MC (deterministic via ``random.Random(seed)``)."""

    n = len(p_vec)
    logits = [logit(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in p_vec]

    # One base latent matrix (list-of-rows), shared across outer draws.
    base_rng = random.Random(seed)
    Z_base = [[base_rng.gauss(0.0, 1.0) for _ in range(n)] for _ in range(inner)]

    def _event_prob(L: list[list[float]], pv: Sequence[float]) -> float:
        thresholds = [normal_ppf(_clamp(p, _PPF_EPS, 1.0 - _PPF_EPS)) for p in pv]
        ge = 0
        for x in Z_base:
            cnt = 0
            for i in range(n):
                Li = L[i]
                zi = 0.0
                for k in range(i + 1):
                    zi += Li[k] * x[k]
                raw = zi < thresholds[i]
                success = (not raw) if counter[i] else raw
                if success:
                    cnt += 1
            if cnt >= K:
                ge += 1
        return ge / inner

    L0, note = _cholesky_with_jitter(_build_corr_matrix(ids, rho_val, pairwise), use_numpy=False)
    point = _event_prob(L0, p_vec)

    param_rng = random.Random(seed ^ 0x9E3779B9)
    samples: list[float] = []
    for _ in range(outer):
        pv = [inv_logit(logits[i] + param_rng.gauss(0.0, 1.0) * sigmas[i]) for i in range(n)]
        rho_draw = _clamp(rho_val + (param_rng.random() * 2.0 - 1.0) * rho_spread, 0.0, 0.95)
        L, _n = _cholesky_with_jitter(_build_corr_matrix(ids, rho_draw, pairwise), use_numpy=False)
        samples.append(_event_prob(L, pv))
    return point, samples, note


def simulate_thesis_event_band(
    members: Sequence[Mapping[str, Any]],
    event: Mapping[str, Any],
    *,
    rho: float | str = 0.4,
    correlation_matrix: Mapping[Any, float] | None = None,
    inner_draws: int | None = None,
    param_draws: int | None = None,
    seed: int = 0,
    rho_spread: float = _EVENT_BAND_RHO_SPREAD,
    sigma_logit: float = _EVENT_BAND_SIGMA_LOGIT,
    center: float | None = None,
) -> ThesisEventBand:
    """A second-order Monte-Carlo INTERVAL on a thesis's P(event) headline.

    ``simulate_thesis_event`` gives the point; this propagates the uncertainty in
    its INPUTS — each member probability (perturbed in logit space, using the
    member's own published interval where it has one, else ``sigma_logit``) and
    rho (jittered over ``rho ± rho_spread``) — through the SAME Gaussian-copula
    event MC, and reports p10/p50/p90 of the event probability itself.

    Args:
        members / event / rho / correlation_matrix: exactly as
            :func:`simulate_thesis_event` (only binary members participate).
        inner_draws: copula draws per parameter set (default 4k numpy / 600 py).
        param_draws: OUTER parameter draws (default 200 numpy / 48 py).
        seed: deterministic RNG seed (the CALLER derives it from thesis id/as_of).
        rho_spread: half-width of the uniform rho sensitivity range.
        sigma_logit: default logit-space std dev for members that publish only a
            point probability (documented epistemic width — never zero).
        center: the point P(event) the band must bracket (typically the headline
            from :func:`simulate_thesis_event`); defaults to this MC's own point.

    Returns:
        A :class:`ThesisEventBand`. p10/p50/p90 are ``None`` (withheld) when no
        binary member participates. The reported band always brackets ``center``.
    """

    kind = str(event.get("kind", "")).lower()
    if kind not in {"count_threshold", "all", "any"}:
        raise ValueError(
            f"event kind must be 'count_threshold', 'all' or 'any', got {kind!r}"
        )

    # Participants: binary members only (mirror simulate_thesis_event exactly).
    parts: list[dict[str, Any]] = []
    for member in members:
        if str(member.get("kind", "")).lower() != "binary":
            continue
        p = _coerce_float(member.get("probability"))
        if p is None:
            continue
        direction = str(member.get("direction", "support")).lower()
        parts.append({
            "member_id": str(member.get("member_id", "")),
            "p": _clamp(p, 0.0, 1.0),
            "counter": direction == "inverted",
            "p_ci90": member.get("p_ci90"),
            "p_sd": member.get("p_sd"),
        })

    n = len(parts)

    if kind == "all":
        K = n
    elif kind == "any":
        K = 1
    else:
        raw_k = event.get("threshold")
        if raw_k is None:
            raise ValueError("count_threshold event requires an integer 'threshold'")
        try:
            K = int(raw_k)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"threshold must be an integer, got {raw_k!r}") from exc

    if isinstance(rho, str):
        if rho == "estimate":
            ps = [part["p"] for part in parts]
            spread = (max(ps) - min(ps)) if len(ps) > 1 else 0.0
            rho_val = _clamp(0.6 - 0.25 * spread, 0.0, 0.95)
        else:
            raise ValueError(f"rho must be a float or 'estimate', got {rho!r}")
    else:
        rho_val = _clamp(float(rho), 0.0, 0.95)

    # Withhold (never fabricate) when nothing participates.
    if n == 0:
        return ThesisEventBand(
            center=None, p10=None, p50=None, p90=None, participants=0,
            param_draws=0, inner_draws=0, rho=rho_val, rho_spread=rho_spread,
            sigma_logit_default=sigma_logit, members_with_interval=0,
            members_defaulted=0, backend="none", seed=seed,
            notes=["withheld: no binary member participates in the event band"],
        )

    pairwise = _normalize_event_corr(correlation_matrix)
    ids = [part["member_id"] for part in parts]
    p_vec = [part["p"] for part in parts]
    counter = [part["counter"] for part in parts]

    sigmas: list[float] = []
    with_interval = 0
    for part in parts:
        sig, used = _member_logit_sigma(part, sigma_logit)
        sigmas.append(sig)
        if used:
            with_interval += 1
    defaulted = n - with_interval

    use_numpy = _np is not None
    if use_numpy:
        inner = max(int(inner_draws), 1) if inner_draws else _EVENT_BAND_INNER_NUMPY
        outer = max(int(param_draws), 1) if param_draws else _EVENT_BAND_OUTER_NUMPY
        simulate = _simulate_band_numpy
        backend = "numpy"
    else:
        inner = min(int(inner_draws), _EVENT_BAND_INNER_PYTHON) if inner_draws else _EVENT_BAND_INNER_PYTHON
        outer = min(int(param_draws), _EVENT_BAND_OUTER_PYTHON) if param_draws else _EVENT_BAND_OUTER_PYTHON
        inner = max(inner, 1)
        outer = max(outer, 1)
        simulate = _simulate_band_python
        backend = "python"

    point, samples, chol_note = simulate(
        p_vec, counter, sigmas, rho_val, rho_spread, pairwise, ids, K,
        inner, outer, seed,
    )

    notes: list[str] = []
    if chol_note:
        notes.append(chol_note)
    if defaulted:
        notes.append(
            f"{defaulted} member(s) publish only a point probability; propagated "
            f"an epistemic width of sigma={sigma_logit:g} in logit space (documented default)"
        )
    if with_interval:
        notes.append(f"{with_interval} member(s) used their own published interval width")

    ordered = sorted(samples)
    q10 = _quantile(ordered, _BAND_QUANTILES[0])
    q50 = _quantile(ordered, _BAND_QUANTILES[1])
    q90 = _quantile(ordered, _BAND_QUANTILES[2])

    # Central-in-band: the reported band MUST bracket the point it annotates.
    # ``center`` is the headline (from simulate_thesis_event) when the caller
    # supplies it, else this MC's own point. Widen minimally if MC noise put the
    # point just outside its own parameter cloud (an interval that excluded its
    # own headline would be the real lie).
    annotated = center if center is not None else point
    lo = min(q10, annotated)
    hi = max(q90, annotated)
    if lo < q10 or hi > q90:
        notes.append("band widened to bracket the point headline (central-in-band)")
    # Keep the reported median inside [lo, hi] (it always is: q10 ≤ q50 ≤ q90).
    p50 = _clamp(q50, lo, hi)
    assert lo <= annotated <= hi, "central-in-band invariant violated"

    return ThesisEventBand(
        center=annotated,
        p10=lo,
        p50=p50,
        p90=hi,
        participants=n,
        param_draws=outer,
        inner_draws=inner,
        rho=rho_val,
        rho_spread=rho_spread,
        sigma_logit_default=sigma_logit,
        members_with_interval=with_interval,
        members_defaulted=defaulted,
        backend=backend,
        seed=seed,
        notes=notes,
    )
