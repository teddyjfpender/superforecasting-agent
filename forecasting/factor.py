"""Weighted-basket factor return / volatility / downside aggregator (§15).

Pure math (stdlib ``math`` only — no DB/IO, no NumPy). Aggregates a basket of
constituent *return distributions* (each ``mean`` ± ``sd`` in the basket's
units, with a ``long``/``short`` ``direction``) into a single factor-return
distribution: an expected return, a **correlation-honest** volatility, normal
return quantiles, and a left-tail downside (5% worst return + expected
shortfall).

Honesty rails (this is a Superforecasting Agent component):

* **Never fabricate precision.** A constituent with no ``sd`` contributes
  *zero* variance and is flagged ``no_dispersion`` — we never invent a spread.
* **Never fake variance reduction.** The factor variance uses the full
  correlated quadratic form ``w' (R∘ΣΣ) w`` with a default ``rho=0.4``; the
  independence formula ``Σ w² σ²`` is *refused* unless the caller explicitly
  passes ``rho=0.0``. Correlated variance therefore exceeds the naive
  independent sum, and the Kish ``n_eff`` is strictly below the constituent
  count — co-moving names do not buy free diversification.
* **No fabricated max-drawdown.** A path-dependent maximum drawdown cannot be
  honestly recovered from a single-horizon return distribution, so we report a
  *left-tail downside* instead: the 5th-percentile return (``downside``) and the
  normal expected shortfall below it (``cvar``).

Staleness down-weighting mirrors :mod:`forecasting.thesis` (§2.3): a constituent
whose latest snapshot is older than ``max_age_days`` decays linearly to a 0.15
floor, then to 0 past twice the horizon, withholding rather than guessing.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from forecasting.bayes_toolkit import normal_cdf

__all__ = ["FactorAggregate", "aggregate_factor"]

# Default staleness horizon when a constituent omits ``max_age_days`` (days).
_DEFAULT_MAX_AGE_DAYS = 45.0
# 90% central-interval half-width in standard-normal units (z for the 5%/95%).
_Z90 = 1.645
# Freshness floor reached at the decay knee (between max_age and 2*max_age).
_FRESH_FLOOR = 0.15
# Default correlation when the caller does not override it.
_DEFAULT_RHO = 0.4


# ── Small local helpers (stdlib math only) ───────────────────────────────────


def _clamp(x: float, lo: float, hi: float) -> float:
    """Clamp ``x`` into ``[lo, hi]`` (plain, non-raising)."""

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


def _normal_pdf(z: float) -> float:
    """Standard-normal density φ(z).

    ``bayes_toolkit`` exposes the normal CDF/PPF but no pdf, so this small
    primitive is implemented locally (stdlib only). ``φ(1.645) ≈ 0.10311``,
    giving the expected-shortfall multiplier ``φ(z)/0.05 ≈ 2.063``.
    """

    return math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)


def _freshness(
    age_days: float | None, max_age_days: float | None
) -> tuple[float, str | None]:
    """Map constituent age to a freshness multiplier (§2.3 shape). None → fresh."""

    max_age = max_age_days if (max_age_days and max_age_days > 0) else _DEFAULT_MAX_AGE_DAYS
    if age_days is None:
        return 1.0, None
    if age_days <= max_age:
        return 1.0, None
    if age_days <= 2.0 * max_age:
        decayed = 1.0 - (age_days - max_age) / max_age
        return _clamp(decayed, _FRESH_FLOOR, 1.0), None
    return 0.0, "stale"


# ── Internal per-constituent row ─────────────────────────────────────────────


@dataclass
class _Row:
    member_id: str
    title: str | None
    direction: str
    weight_raw: float
    as_of: str | None
    mu: float | None          # direction-signed mean (None → no usable snapshot)
    sigma: float              # >= 0 dispersion (0 when sd missing)
    fresh: float
    w_eff: float
    status: str
    flags: list[str]


def _build_row(member: Mapping[str, Any], now: datetime | None) -> _Row:
    """Compute the direction-signed mean, sigma, freshness and effective weight."""

    member_id = str(member.get("member_id", ""))
    title = member.get("title") if isinstance(member.get("title"), str) else None
    direction = str(member.get("direction", "long")).lower()
    weight_raw = _coerce_float(member.get("weight")) or 0.0
    if weight_raw < 0:
        weight_raw = 0.0
    as_of = member.get("as_of") if isinstance(member.get("as_of"), str) else None
    flags: list[str] = []

    mean = _coerce_float(member.get("mean"))
    sd = _coerce_float(member.get("sd"))

    # Sigma: never invent dispersion. Missing/negative sd → 0 + a flag.
    if sd is None:
        sigma = 0.0
        if mean is not None:
            flags.append("no_dispersion")
    elif sd < 0:
        sigma = 0.0
        flags.append("no_dispersion")
    else:
        sigma = sd

    # §2.3 staleness. Age needs both an as_of and a `now` reference.
    age_days: float | None = None
    instant = _parse_instant(as_of)
    if instant is not None and now is not None:
        age_days = max(0.0, (now - instant).total_seconds() / 86400.0)
    fresh, stale_flag = _freshness(age_days, _coerce_float(member.get("max_age_days")))

    if mean is None:
        # No usable snapshot → withhold this constituent entirely (never guess).
        status = "missing"
        flags.append("missing")
        fresh = 0.0
        mu: float | None = None
    else:
        # Direction sign applied last and uniformly.
        mu = mean if direction != "short" else -mean
        if instant is None and as_of is not None:
            # An as_of we couldn't parse is a missing snapshot for staleness.
            flags.append("missing")
            fresh = 0.0
        if stale_flag:
            flags.append(stale_flag)
        if fresh <= 0.0:
            status = "stale" if stale_flag else ("missing" if "missing" in flags else "zeroed")
        elif fresh < 1.0:
            status = "decayed"
        else:
            status = "ok"

    w_eff = weight_raw * fresh

    return _Row(
        member_id=member_id,
        title=title,
        direction=direction,
        weight_raw=weight_raw,
        as_of=as_of,
        mu=mu,
        sigma=sigma,
        fresh=fresh,
        w_eff=w_eff,
        status=status,
        flags=flags,
    )


def _component_row(
    row: _Row, *, w_norm: float, contribution: float
) -> dict[str, Any]:
    """Per-constituent audit record (every input row appears, even weight-0)."""

    return {
        "member_id": row.member_id,
        "title": row.title,
        "weight": row.weight_raw,
        "w_norm": w_norm,
        "direction": row.direction,
        "mu": row.mu,                 # direction-signed mean
        "sigma": row.sigma,
        "contribution": contribution,
        "status": row.status,
        "flags": list(row.flags),
    }


# ── Output dataclass ─────────────────────────────────────────────────────────


@dataclass
class FactorAggregate:
    """Aggregated factor-return distribution with an honest correlated band.

    ``None`` headline fields mean *withheld, not fabricated*: there was no usable
    constituent (every name stale/missing). ``components`` always lists every
    input constituent (even weight-0 / withheld rows) for auditability.

    ``downside`` is the 5th-percentile return and ``cvar`` the normal expected
    shortfall below it — deliberately *not* a path-dependent max drawdown, which
    cannot be honestly recovered from a single-horizon return distribution.
    """

    mean: float | None            # factor expected return
    sd: float | None              # factor volatility (sqrt of correlated Var)
    q05: float | None
    q50: float | None
    q95: float | None
    downside: float | None        # == q05 (5% worst return)
    cvar: float | None            # expected shortfall (5%) under normality
    coverage: float               # sum(w_eff) / sum(weight_raw) ∈ (0, 1]
    n_eff: float                  # Kish-style effective sample size
    rho: float                    # correlation actually applied
    components: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        """Compact ledger payload; omits any ``None`` headline keys."""

        payload: dict[str, Any] = {
            "factor_mean": self.mean,
            "factor_sd": self.sd,
            "volatility": self.sd,
            "q05": self.q05,
            "q50": self.q50,
            "q95": self.q95,
            "downside": self.downside,
            "cvar": self.cvar,
            "coverage": self.coverage,
            "n_eff": self.n_eff,
        }
        return {k: v for k, v in payload.items() if v is not None}


# ── Public entry point ───────────────────────────────────────────────────────


def aggregate_factor(
    constituents: Sequence[Mapping[str, Any]],
    *,
    rho: float | str = _DEFAULT_RHO,
    now: str | None = None,
) -> FactorAggregate:
    """Aggregate constituent return distributions into a factor distribution.

    Args:
        constituents: basket members, each a mapping with ``member_id``,
            ``title``, ``weight`` (raw, pre-normalization, >= 0), ``direction``
            (``"long"``/``"short"``), ``as_of`` (ISO8601 of latest snapshot),
            ``max_age_days`` (None → 45), ``mean`` (expected return), and ``sd``
            (return dispersion; None → contributes 0 variance, never invented).
        rho: pairwise correlation for the variance quadratic form. A float in
            ``[0, 0.95]`` (default ``0.4``); ``"estimate"`` derives a mild
            constant from the dispersion of the signed means. Independence
            (``0.0``) is honored **only** when the caller passes the explicit
            float ``0.0``.
        now: ISO8601 reference instant for staleness. ``None`` treats every
            constituent as fresh (no ``datetime.now`` is ever called here).

    Returns:
        A :class:`FactorAggregate`. Headline fields are ``None`` (withheld, not
        fabricated) when there is no usable constituent.
    """

    now_dt = _parse_instant(now)
    rows = [_build_row(member, now_dt) for member in constituents]

    weight_raw_total = sum(r.weight_raw for r in rows)
    W = sum(r.w_eff for r in rows)
    coverage = (W / weight_raw_total) if weight_raw_total > 0 else 0.0

    # Resolve the requested rho up front (also used in the withheld branch so the
    # echoed value is honest about what *would* have been applied).
    if isinstance(rho, str):
        if rho != "estimate":
            raise ValueError(f"rho must be a float or 'estimate', got {rho!r}")
        rho_requested = "estimate"
    else:
        rho_requested = _clamp(float(rho), 0.0, 0.95)

    # All-stale / all-missing guard: withhold rather than emit a number.
    if W <= 0:
        components = [_component_row(r, w_norm=0.0, contribution=0.0) for r in rows]
        return FactorAggregate(
            mean=None,
            sd=None,
            q05=None,
            q50=None,
            q95=None,
            downside=None,
            cvar=None,
            coverage=0.0,
            n_eff=0.0,
            rho=(_DEFAULT_RHO if rho_requested == "estimate" else float(rho_requested)),
            components=components,
            notes=["withheld: no usable constituent (not fabricated)"],
        )

    w_norm = [r.w_eff / W for r in rows]
    usable_idx = [i for i, r in enumerate(rows) if r.mu is not None and r.w_eff > 0]
    usable_mu = [rows[i].mu for i in usable_idx]  # type: ignore[misc]

    notes: list[str] = []

    # ── rho resolution ───────────────────────────────────────────────────────
    if rho_requested == "estimate":
        # Mild constant from the spread of the signed means. Wider disagreement
        # → lower implied co-movement (but never below 0 or above 0.95).
        if len(usable_mu) > 1:
            lo, hi = min(usable_mu), max(usable_mu)
            denom = max(abs(lo), abs(hi), 1e-9)
            spread_norm = (hi - lo) / denom
        else:
            spread_norm = 0.0
        rho_val = _clamp(0.6 - 0.25 * spread_norm, 0.0, 0.95)
        notes.append("rho estimated from constituent dispersion")
    else:
        rho_val = float(rho_requested)

    # ── Factor mean: weight-normalised average of signed means ───────────────
    mu_f = sum(w_norm[i] * rows[i].mu for i in usable_idx)  # type: ignore[arg-type]

    # ── Correlation-honest factor variance: w' (R∘ΣΣ) w ──────────────────────
    # Var_f = Σ_i Σ_j w_norm_i w_norm_j rho_ij sigma_i sigma_j, rho_ii = 1.
    var_f = 0.0
    for i in usable_idx:
        for j in usable_idx:
            rho_ij = 1.0 if i == j else rho_val
            var_f += w_norm[i] * w_norm[j] * rho_ij * rows[i].sigma * rows[j].sigma
    var_f = max(var_f, 0.0)
    sigma_f = math.sqrt(var_f)

    has_dispersion = any(rows[i].sigma > 0 for i in usable_idx)
    if not has_dispersion:
        notes.append("degenerate: no dispersion")

    # ── n_eff: Kish-style effective N with the correlation matrix R ───────────
    # n_eff = (Σ w_eff)^2 / (w_eff' R w_eff). Off-diagonal rho inflates the
    # denominator, so correlated names yield n_eff < n_constituents.
    denom = 0.0
    for i in range(len(rows)):
        for j in range(len(rows)):
            rho_ij = 1.0 if i == j else rho_val
            denom += rows[i].w_eff * rows[j].w_eff * rho_ij
    n_eff = (W * W / denom) if denom > 0 else 0.0

    # ── Normal-approx return quantiles ───────────────────────────────────────
    notes.append("normal_approx")
    q05 = mu_f - _Z90 * sigma_f
    q50 = mu_f
    q95 = mu_f + _Z90 * sigma_f

    # ── Left-tail downside (NOT a fabricated max-drawdown) ───────────────────
    downside = q05
    if sigma_f > 0:
        # Expected shortfall below the 5th percentile under normality:
        # ES = mu - sigma * φ(z_0.05)/0.05, with φ(1.645) ≈ 0.1031.
        es_multiplier = _normal_pdf(_Z90) / 0.05
        cvar = mu_f - sigma_f * es_multiplier
        # Honest loss probability P[return < 0] under the normal approximation,
        # via the audited bayes_toolkit CDF (reused, not reimplemented).
        prob_loss = float(normal_cdf(0.0, mean=mu_f, sd=sigma_f))
    else:
        cvar = mu_f
        prob_loss = 1.0 if mu_f < 0 else 0.0
    notes.append(f"prob_loss={prob_loss:.4f}")

    # ── Per-constituent contributions (Σ contribution == mu_f) ───────────────
    components: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        contribution = (
            w_norm[idx] * row.mu if (row.mu is not None and row.w_eff > 0) else 0.0
        )
        components.append(_component_row(row, w_norm=w_norm[idx], contribution=contribution))

    return FactorAggregate(
        mean=mu_f,
        sd=sigma_f,
        q05=q05,
        q50=q50,
        q95=q95,
        downside=downside,
        cvar=cvar,
        coverage=coverage,
        n_eff=n_eff,
        rho=rho_val,
        components=components,
        notes=notes,
    )
