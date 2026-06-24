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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

# ── Reused bayes_toolkit primitives ─────────────────────────────────────────
# ``logit`` / ``inv_logit`` power the log-odds health pool (§2.4) and the
# leave-one-out marginals (§2.7). ``normal_cdf(x, mean, sd) == Phi((x-mean)/sd)``
# gives the threshold-on-normal signal (§2.1.2): ``Phi((mean-target)/sd)`` is
# ``normal_cdf(mean, target, sd)``.
from forecasting.bayes_toolkit import inv_logit, logit, normal_cdf

__all__ = ["ThesisAggregate", "aggregate_thesis"]

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
