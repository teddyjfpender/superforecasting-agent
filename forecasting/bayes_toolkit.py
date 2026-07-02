"""Bayesian / probabilistic forecasting scratchpad toolkit.

A dedicated, auditable toolkit for the kinds of probability work a
superforecaster does by hand: likelihood-ratio updating, log-odds pooling of
disagreeing sources, evidence weighting that separates reliability from
relevance and discounts correlated signals, reference-class base-rate
blending, poll-to-probability conversion, prediction-market de-vigging,
double-counting checks, sensitivity analysis, and forecast-diff decomposition.

Design goals (from docs/plans/feedback-forecaster-tooling-bayesian-example.md):

* **Auditable, reusable, not ad hoc.** Every routine returns both a
  machine-readable payload (``to_dict``) for the ledger and a human-readable
  rationale (``to_text``) for forecast notes.
* **Industry-standard libraries.** Uses NumPy for vectorised/linear-algebra
  work and SciPy's ``scipy.stats.norm`` for the normal distribution when they
  are importable; falls back to exact ``math.erf``-based implementations so the
  toolkit never hard-fails on a minimal install.

The math primitives (``prob_to_odds`` … ``forecast_diff``) are intentionally
small and composable so the agent can chain them, while the higher-level
``combine_forecasts`` / ``polls_to_win_probability`` / ``combine_markets``
helpers package the common end-to-end recipes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from forecasting.models import ValidationError

# ── Optional industry-standard accelerators ─────────────────────────────────
# NumPy + SciPy are the preferred backends (the feedback explicitly asked for
# "industry-standard python libraries"). They are auto-provisioned via
# tools/lazy_deps.py ("forecast.bayes") and degrade to exact stdlib math so the
# toolkit works on any install.
try:  # pragma: no cover - import guard
    import numpy as _np
except Exception:  # pragma: no cover - numpy optional
    _np = None

# SciPy's ``scipy.stats`` costs ~0.3s to import and would tax *every* CLI run,
# agent-tool load and TUI first paint even though the vast majority of calls hit
# the pure-stdlib helpers. So we do NOT import it eagerly: the module-global
# ``_scipy_stats`` sentinel stays ``None`` until first use and is populated
# lazily via ``_get_scipy_stats``. ``_scipy_stats_probed`` records that we have
# already attempted the (possibly failing) import so we never retry it per call.
_scipy_stats = None
_scipy_stats_probed = False


def _get_scipy_stats():
    """Return ``scipy.stats`` (cached) or ``None`` if unavailable. Lazy import."""

    global _scipy_stats, _scipy_stats_probed
    if _scipy_stats is None and not _scipy_stats_probed:
        _scipy_stats_probed = True
        try:  # pragma: no cover - import guard
            from scipy import stats as _stats_mod
        except Exception:  # pragma: no cover - scipy optional
            _stats_mod = None
        _scipy_stats = _stats_mod
    return _scipy_stats


_EPS = 1e-9


def using_industry_libraries() -> dict[str, bool]:
    """Report which industry-standard backends are active (for diagnostics)."""

    return {"numpy": _np is not None, "scipy": _get_scipy_stats() is not None}


def ensure_industry_backends() -> dict[str, bool]:
    """Best-effort provision NumPy + SciPy (the toolkit's preferred backends).

    Triggers the lazy-install of the ``forecast.bayes`` dependency group and
    re-imports the modules. A no-op once installed, and harmless offline (the
    toolkit keeps working on the stdlib fallback). Returns which backends are
    active afterwards.
    """

    global _np, _scipy_stats, _scipy_stats_probed
    if _np is not None and _get_scipy_stats() is not None:
        return using_industry_libraries()
    try:
        from tools.lazy_deps import ensure as _lazy_ensure

        _lazy_ensure("forecast.bayes", prompt=False)
    except Exception:
        pass
    if _np is None:
        try:  # pragma: no cover - depends on environment
            import numpy as _np_mod

            _np = _np_mod
        except Exception:
            pass
    if _scipy_stats is None:
        try:  # pragma: no cover - depends on environment
            from scipy import stats as _stats_mod

            _scipy_stats = _stats_mod
        except Exception:
            pass
        _scipy_stats_probed = True
    return using_industry_libraries()


# ── Numeric coercion / clamping ─────────────────────────────────────────────


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name} must be numeric, not boolean")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be a number") from exc
    if not math.isfinite(number):
        raise ValidationError(f"{field_name} must be finite")
    return number


def _clamp_prob(p: float, field_name: str = "probability") -> float:
    number = _finite(p, field_name)
    if number < 0 or number > 1:
        raise ValidationError(f"{field_name} must be between 0 and 1")
    # Keep strictly interior so odds/logit stay finite.
    return min(1.0 - _EPS, max(_EPS, number))


def _round(value: float, places: int = 4) -> float:
    return round(float(value), places)


# ── 1. Bayesian update scratchpad ───────────────────────────────────────────


def prob_to_odds(p: float) -> float:
    """Convert a probability to odds (p / (1 - p))."""

    p = _clamp_prob(p)
    return p / (1.0 - p)


def odds_to_prob(o: float) -> float:
    """Convert odds to a probability (o / (1 + o))."""

    o = _finite(o, "odds")
    if o < 0:
        raise ValidationError("odds must be non-negative")
    return o / (1.0 + o)


def logit(p: float) -> float:
    """Log-odds of a probability."""

    return math.log(prob_to_odds(p))


def inv_logit(x: float) -> float:
    """Inverse logit (logistic sigmoid) → probability."""

    x = _finite(x, "log-odds")
    # Numerically stable logistic.
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def apply_lr(prior_p: float, lr: float) -> float:
    """Apply a single likelihood ratio to a prior probability."""

    prior_odds = prob_to_odds(prior_p)
    lr = _finite(lr, "likelihood_ratio")
    if lr <= 0:
        raise ValidationError("likelihood_ratio must be positive")
    return odds_to_prob(prior_odds * lr)


def apply_lrs(prior_p: float, lrs: Sequence[float]) -> float:
    """Apply a sequence of likelihood ratios (assumes conditional independence)."""

    odds = prob_to_odds(prior_p)
    for lr in lrs:
        value = _finite(lr, "likelihood_ratio")
        if value <= 0:
            raise ValidationError("likelihood_ratio must be positive")
        odds *= value
    return odds_to_prob(odds)


def log_odds_update(prior_p: float, evidence_weights: Sequence[float]) -> float:
    """Update in log-odds space by summing additive log-LR contributions.

    ``evidence_weights`` are additive shifts in log-odds (natural log of each
    likelihood ratio). Positive shifts raise the probability.
    """

    total = logit(prior_p)
    for weight in evidence_weights:
        total += _finite(weight, "evidence_weight")
    return inv_logit(total)


def decompose_update(prior_p: float, posterior_p: float) -> dict[str, float]:
    """Infer the implied likelihood ratio (and log-odds shift) of an update.

    Answers "what evidence strength did moving from prior to posterior imply?"
    """

    prior_odds = prob_to_odds(prior_p)
    posterior_odds = prob_to_odds(posterior_p)
    lr = posterior_odds / prior_odds
    return {
        "implied_lr": _round(lr, 4),
        "log_odds_shift": _round(math.log(lr), 4),
        "prob_delta": _round(_clamp_prob(posterior_p) - _clamp_prob(prior_p), 4),
    }


# ── Normal distribution (SciPy preferred, exact stdlib fallback) ─────────────


def normal_cdf(x: float, mean: float = 0.0, sd: float = 1.0) -> float:
    """Standard normal CDF via SciPy when available, else exact math.erf."""

    sd = _finite(sd, "sd")
    if sd <= 0:
        raise ValidationError("sd must be positive")
    z = (_finite(x, "x") - _finite(mean, "mean")) / sd
    _stats = _get_scipy_stats()
    if _stats is not None:
        return float(_stats.norm.cdf(z))
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def normal_ppf(q: float) -> float:
    """Inverse standard normal CDF (quantile function)."""

    q = _finite(q, "quantile")
    if not (0.0 < q < 1.0):
        raise ValidationError("quantile must be strictly between 0 and 1")
    _stats = _get_scipy_stats()
    if _stats is not None:
        return float(_stats.norm.ppf(q))
    return _acklam_ppf(q)


def _acklam_ppf(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF (no SciPy)."""

    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


# ── 3. Ensemble combiners ───────────────────────────────────────────────────


def linear_pool(probabilities: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Weighted arithmetic mean of probabilities (the naive average)."""

    probs, ws = _probs_and_weights(probabilities, weights)
    return sum(p * w for p, w in zip(probs, ws)) / sum(ws)


def mean_probability(probabilities: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Weighted arithmetic mean of probabilities — the convexity-backed baseline.

    Alias of :func:`linear_pool`, named for its role as the AIA P1.4 simple-mean
    BASELINE. Brier is convex in the forecast, so by Jensen's inequality the Brier
    of the mean is no worse than the mean of the components' Briers
    (``Brier(mean(p)) <= mean(Brier(p))``) for a fixed outcome. That makes the
    naive average the formal floor any odds pool or judge synthesis must beat to
    justify its extra machinery. Selectable as the ``'mean'`` panel-aggregation
    method; the desk DEFAULT stays ``trimmed_geomean_odds``.
    """

    return linear_pool(probabilities, weights)


def log_pool(probabilities: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Normalised weighted geometric mean of probabilities (log-linear pool).

    For a binary event this normalises ``p`` and ``1-p`` separately so the
    result is a valid probability.
    """

    probs, ws = _probs_and_weights(probabilities, weights)
    total_w = sum(ws)
    log_yes = sum(w * math.log(p) for p, w in zip(probs, ws)) / total_w
    log_no = sum(w * math.log(1.0 - p) for p, w in zip(probs, ws)) / total_w
    yes, no = math.exp(log_yes), math.exp(log_no)
    return yes / (yes + no)


def log_odds_pool(probabilities: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Weighted average in log-odds space (geometric pooling of odds).

    The superforecasting workhorse: respects confident minority views better
    than a linear average and is the recommended default for combining sources.
    """

    probs, ws = _probs_and_weights(probabilities, weights)
    total_w = sum(ws)
    pooled_logit = sum(w * logit(p) for p, w in zip(probs, ws)) / total_w
    return inv_logit(pooled_logit)


def geometric_pool_odds(probabilities: Sequence[float], weights: Sequence[float] | None = None) -> float:
    """Alias for :func:`log_odds_pool` (weighted geometric mean of odds)."""

    return log_odds_pool(probabilities, weights)


# The classic logistic-vs-normal variance-matching extremization slope
# (Neyman-Roughgarden's n>50 limit). The theory-grounded value to ACTIVATE the
# terminal calibration with — but never the kernel default (see below).
PLATT_ALPHA_VARIANCE_MATCH = math.sqrt(3.0)


def platt_scale(p: float, alpha: float = 1.0, d: float = 1.0) -> float:
    """Platt-style affine recalibration in log-odds space.

    ``platt_scale(p) = inv_logit(alpha * logit(p) + log(d))`` — the single
    recalibration operator the desk uses everywhere (extremization, the learned
    confidence rescale, and the panel's terminal calibration stage). ``alpha``
    is the log-odds slope (``>1`` sharpens away from 0.5, ``<1`` flattens
    toward it, ``==1`` leaves the slope unchanged); ``d`` is a multiplicative
    odds bias (``d>1`` shifts toward YES, ``d<1`` toward NO, ``d==1`` is
    unbiased). The default ``alpha=1.0`` is the exact IDENTITY (modulo the
    interior clamp) — the kernel never silently extremizes; callers that want the
    variance-matching slope pass :data:`PLATT_ALPHA_VARIANCE_MATCH` explicitly.

    This is the Baron-2014 extremizing aggregator's recalibration kernel: a
    log-odds pool followed by ``platt_scale`` is precisely "Platt-of-the-
    geometric-mean-of-odds" (see :func:`combine_forecasts`).
    """

    alpha = _finite(alpha, "alpha")
    if alpha <= 0:
        raise ValidationError("platt_scale alpha must be positive")
    d = _finite(d, "d")
    if d <= 0:
        raise ValidationError("platt_scale d must be positive")
    return inv_logit(alpha * logit(p) + math.log(d))


def platt_scale_anchored(p: float, base_rate: float, alpha: float = 1.0) -> float:
    """Platt recalibration that extremizes the deviation from a BASE RATE.

    ``platt_scale_anchored(p, base_rate, alpha) =
        inv_logit(logit(base_rate) + alpha * (logit(p) - logit(base_rate)))``

    Unlike :func:`platt_scale` (which sharpens away from the implicit 0.5
    reference), this sharpens ``p``'s deviation from the *reference-class base
    rate*. AIA P2.3: on the 899-question Metaculus panel this base-rate-anchored
    form significantly outperformed every 0.5-anchored method — extremizing
    "how far is this question's forecast from its reference class" is the right
    quantity to amplify, not "how far from a coin flip".

    Invariants (pinned in tests):

    * ``alpha == 1`` is the EXACT identity (returns ``p``) for any base rate.
    * ``base_rate == 0.5`` reduces EXACTLY to :func:`platt_scale` (``d == 1``),
      because ``logit(0.5) == 0``.

    ``base_rate`` and ``p`` are guarded into the open interval ``(0, 1)`` so the
    log-odds stay finite; ``alpha`` must be positive.
    """

    alpha = _finite(alpha, "alpha")
    if alpha <= 0:
        raise ValidationError("platt_scale_anchored alpha must be positive")
    anchor = logit(base_rate)  # _clamp_prob via prob_to_odds keeps it interior
    return inv_logit(anchor + alpha * (logit(p) - anchor))


def extremize(p: float, factor: float = 1.0) -> float:
    """Sharpen a probability away from 0.5 by scaling its log-odds.

    ``factor > 1`` extremizes; ``factor == 1`` is a no-op. Justified when
    pooling several *independent* sources that agree.

    A THIN ALIAS of :func:`platt_scale` with ``alpha=factor`` (and ``d=1.0``)
    so there is exactly ONE recalibration operator on the desk. Behaviour is
    identical to the historical ``inv_logit(factor * logit(p))`` for every
    caller (``platt_scale`` adds ``log(d)=log(1.0)=0``).
    """

    factor = _finite(factor, "factor")
    if factor <= 0:
        raise ValidationError("extremize factor must be positive")
    return platt_scale(p, alpha=factor, d=1.0)


def de_extremize(p: float, factor: float = 1.0) -> float:
    """Pull a probability toward 0.5 (inverse of :func:`extremize`)."""

    factor = _finite(factor, "factor")
    if factor <= 0:
        raise ValidationError("de-extremize factor must be positive")
    return extremize(p, 1.0 / factor)


@dataclass
class PoolResult:
    """Outcome of combining several probability sources."""

    method: str
    probability: float
    components: list[dict[str, Any]]
    extremize_factor: float = 1.0
    pre_extremize_probability: float | None = None
    effective_independent_sources: float | None = None
    correlation_applied: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "probability": _round(self.probability),
            "pre_extremize_probability": (
                None if self.pre_extremize_probability is None else _round(self.pre_extremize_probability)
            ),
            "extremize_factor": _round(self.extremize_factor, 3),
            "correlation_applied": self.correlation_applied,
            "effective_independent_sources": (
                None if self.effective_independent_sources is None
                else _round(self.effective_independent_sources, 2)
            ),
            "components": self.components,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [f"Combined probability: {self.probability:.3f}  (method: {self.method})"]
        for comp in self.components:
            lines.append(
                f"  - {comp.get('name', '?')}: p={comp.get('probability'):.3f}"
                f"  weight={comp.get('weight'):.3f}"
                + (f"  eff_weight={comp['effective_weight']:.3f}" if "effective_weight" in comp else "")
            )
        if self.pre_extremize_probability is not None and self.extremize_factor != 1.0:
            lines.append(
                f"  pre-extremize: {self.pre_extremize_probability:.3f}"
                f" → extremized x{self.extremize_factor:g} → {self.probability:.3f}"
            )
        if self.effective_independent_sources is not None:
            lines.append(
                f"  effective independent sources: {self.effective_independent_sources:.2f}"
            )
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def combine_forecasts(
    components: Sequence[Mapping[str, Any]],
    *,
    method: str = "log_odds_pool",
    extremize: float = 1.0,
    correlation_matrix: Any = None,
) -> PoolResult:
    """Combine probability sources without naively averaging them.

    ``components``: ``[{"name", "p"/"probability", "weight"?}]``.
    ``method``: ``log_odds_pool`` (default) | ``linear_pool`` | ``log_pool``.
    ``correlation_matrix``: an NxN matrix, or the string ``"estimate"`` to
    infer a mild positive correlation from how tightly the sources agree.
    """

    rows = _normalize_components(components)
    if not rows:
        raise ValidationError("combine_forecasts needs at least one component")
    names = [r["name"] for r in rows]
    probs = [r["probability"] for r in rows]
    weights = [r["weight"] for r in rows]

    notes: list[str] = []
    effective_weights = list(weights)
    n_eff: float | None = None
    correlation_applied = False

    corr = _resolve_correlation(correlation_matrix, probs)
    if corr is not None:
        effective_weights, n_eff = _correlation_adjust_weights(weights, corr)
        correlation_applied = True
        notes.append(
            "correlation-adjusted weights: shared signal between sources downweighted"
        )

    pooler = {
        "log_odds_pool": log_odds_pool,
        "logit": log_odds_pool,
        "geometric": log_odds_pool,
        "geo_mean_odds": log_odds_pool,
        "log_odds_weighted": log_odds_pool,
        "weighted_log_odds": log_odds_pool,
        "log_odds": log_odds_pool,
        "linear_pool": linear_pool,
        "linear": linear_pool,
        "weighted_ensemble": linear_pool,
        "weighted_average": linear_pool,
        "log_pool": log_pool,
        "log_linear": log_pool,
    }.get(str(method).strip().lower())
    if pooler is None:
        raise ValidationError(
            f"unknown pooling method '{method}'"
            " (use log_odds_pool, linear_pool, or log_pool)"
        )

    pooled = pooler(probs, effective_weights)
    pre = pooled
    factor = _finite(extremize, "extremize")
    if factor <= 0:
        raise ValidationError("extremize factor must be positive")
    # Baron-2014 == Platt-of-geometric-mean identity: for ``method='log_odds_pool'``
    # the pool is the (weighted) geometric mean of odds, so extremizing it is
    # exactly ``platt_scale(geometric_mean_of_odds(p_i), alpha=factor)`` — one and
    # the same recalibration kernel. ``extremize`` is a thin alias of
    # :func:`platt_scale` (alpha=factor, d=1.0), so this equals
    # ``platt_scale(pooled, alpha=factor)`` by construction. The regression test
    # ``test_log_odds_pool_extremize_is_platt_of_geomean`` pins the identity.
    final = globals()["extremize"](pooled, factor) if factor != 1.0 else pooled
    if factor != 1.0 and correlation_applied and n_eff is not None and n_eff < len(rows):
        notes.append(
            "extremization kept modest because sources are correlated"
            f" (≈{n_eff:.1f} independent of {len(rows)})"
        )

    total_eff = sum(effective_weights)
    comp_out: list[dict[str, Any]] = []
    for name, p, w, ew in zip(names, probs, weights, effective_weights):
        entry = {"name": name, "probability": _round(p), "weight": _round(w, 3)}
        if correlation_applied:
            entry["effective_weight"] = _round(ew / total_eff if total_eff else 0.0, 3)
        comp_out.append(entry)

    return PoolResult(
        method=str(method).lower(),
        probability=final,
        components=comp_out,
        extremize_factor=factor,
        pre_extremize_probability=pre if factor != 1.0 else None,
        effective_independent_sources=n_eff,
        correlation_applied=correlation_applied,
        notes=notes,
    )


def correlation_adjusted_pool(
    components: Sequence[Mapping[str, Any]],
    correlation_matrix: Any = "estimate",
    *,
    method: str = "log_odds_pool",
    extremize: float = 1.0,
) -> PoolResult:
    """Pool sources while discounting correlated (double-counted) signal."""

    return combine_forecasts(
        components, method=method, extremize=extremize, correlation_matrix=correlation_matrix
    )


def _probs_and_weights(
    probabilities: Sequence[float], weights: Sequence[float] | None
) -> tuple[list[float], list[float]]:
    probs = [_clamp_prob(p) for p in probabilities]
    if not probs:
        raise ValidationError("at least one probability is required")
    if weights is None:
        ws = [1.0] * len(probs)
    else:
        ws = [_finite(w, "weight") for w in weights]
        if len(ws) != len(probs):
            raise ValidationError("weights must match probabilities in length")
        if any(w < 0 for w in ws):
            raise ValidationError("weights must be non-negative")
    if sum(ws) <= 0:
        raise ValidationError("weights must sum to a positive value")
    return probs, ws


def _normalize_components(components: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, comp in enumerate(components):
        if not isinstance(comp, Mapping):
            raise ValidationError("each component must be an object")
        raw_p = comp.get("p", comp.get("probability"))
        if raw_p is None:
            raise ValidationError("each component needs a probability ('p')")
        rows.append(
            {
                "name": str(comp.get("name") or f"component_{index + 1}"),
                "probability": _clamp_prob(raw_p),
                "weight": _finite(comp.get("weight", 1.0), "weight"),
            }
        )
    if any(r["weight"] < 0 for r in rows):
        raise ValidationError("component weights must be non-negative")
    if sum(r["weight"] for r in rows) <= 0:
        raise ValidationError("component weights must sum to a positive value")
    return rows


def _resolve_correlation(correlation_matrix: Any, probs: Sequence[float]) -> Any:
    if correlation_matrix is None:
        return None
    n = len(probs)
    if isinstance(correlation_matrix, str):
        if correlation_matrix.strip().lower() not in {"estimate", "auto", "estimated", "infer"}:
            raise ValidationError(
                "correlation_matrix string must be 'estimate' (or pass an NxN matrix)"
            )
        # Estimate a mild shared correlation from how tightly sources agree:
        # tightly-clustered logits ⇒ likely a shared underlying signal.
        logits = [logit(p) for p in probs]
        if n < 2:
            return _identity(1)
        spread = _stdev(logits)
        # spread small (≈0) ⇒ rho≈0.6; spread large (≥2) ⇒ rho≈0.1.
        rho = max(0.05, min(0.6, 0.6 - 0.25 * spread))
        return _constant_corr(n, rho)
    # Explicit matrix.
    matrix = [[_finite(v, "correlation") for v in row] for row in correlation_matrix]
    if len(matrix) != n or any(len(row) != n for row in matrix):
        raise ValidationError("correlation_matrix must be NxN matching components")
    return matrix


def _identity(n: int) -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]


def _constant_corr(n: int, rho: float) -> list[list[float]]:
    return [[1.0 if i == j else rho for j in range(n)] for i in range(n)]


def _correlation_adjust_weights(
    weights: Sequence[float], corr: Sequence[Sequence[float]]
) -> tuple[list[float], float]:
    """Down-weight correlated sources and report effective independent count.

    Effective number of independent sources uses the standard
    ``n_eff = (Σw)² / (wᵀ R w)`` ratio (Kish-style), and per-source effective
    weights are scaled by their average correlation with the rest.
    """

    n = len(weights)
    w = list(weights)
    if _np is not None:
        wv = _np.asarray(w, dtype=float)
        R = _np.asarray(corr, dtype=float)
        denom = float(wv @ R @ wv)
        n_eff = (float(wv.sum()) ** 2) / denom if denom > 0 else float(n)
        row_corr = (R.sum(axis=1) - 1.0) / max(n - 1, 1)
        eff = wv / (1.0 + _np.clip(row_corr, 0.0, None) * (n - 1))
        return [float(x) for x in eff], float(n_eff)
    # Pure-Python fallback.
    total = sum(w)
    quad = sum(w[i] * corr[i][j] * w[j] for i in range(n) for j in range(n))
    n_eff = (total ** 2) / quad if quad > 0 else float(n)
    eff = []
    for i in range(n):
        avg_corr = (sum(corr[i][j] for j in range(n)) - 1.0) / max(n - 1, 1)
        eff.append(w[i] / (1.0 + max(0.0, avg_corr) * (n - 1)))
    return eff, n_eff


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


# ── 2. Evidence-weighted likelihood-ratio builder ───────────────────────────

_STRENGTH_LOG_ODDS = {
    "negligible": 0.0,
    "weak": 0.4,
    "low": 0.4,
    "modest": 0.7,
    "medium": 1.1,
    "moderate": 1.1,
    "strong": 1.8,
    "high": 1.8,
    "very_strong": 2.5,
    "decisive": 3.2,
}
_DIRECTION_SIGN = {
    "for": 1.0, "favors": 1.0, "supports": 1.0, "up": 1.0, "increase": 1.0,
    "against": -1.0, "disfavors": -1.0, "down": -1.0, "decrease": -1.0,
    "neutral": 0.0, "mixed": 0.0,
}


@dataclass
class EvidenceWeight:
    name: str
    direction_sign: float
    suggested_lr: float
    log_odds_contribution: float
    effective_weight: float
    quality_score: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "direction_sign": self.direction_sign,
            "suggested_lr": _round(self.suggested_lr, 4),
            "log_odds_contribution": _round(self.log_odds_contribution, 4),
            "effective_weight": _round(self.effective_weight, 3),
            "quality_score": _round(self.quality_score, 3),
            "notes": self.notes,
        }

    def to_text(self) -> str:
        arrow = "↑" if self.direction_sign > 0 else "↓" if self.direction_sign < 0 else "·"
        lines = [
            f"{self.name}: suggested LR={self.suggested_lr:.3f} ({arrow}),"
            f" effective weight={self.effective_weight:.2f}"
            f" (quality {self.quality_score:.2f})"
        ]
        lines.extend(f"  - {note}" for note in self.notes)
        return "\n".join(lines)


def _coerce_quality(value: Any, name: str, default: float = 0.5) -> float:
    """Map qualitative labels or 0-1 numbers to a quality fraction."""

    if value is None:
        return default
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(1.0, max(0.0, float(value)))
    label = str(value).strip().lower()
    mapping = {
        "none": 0.0, "very_low": 0.1, "low": 0.25, "medium": 0.5, "moderate": 0.5,
        "high": 0.8, "very_high": 0.95, "max": 1.0,
    }
    if label not in mapping:
        raise ValidationError(f"{name} must be a 0-1 number or a level (low/medium/high)")
    return mapping[label]


def evidence_weight(
    *,
    reliability: Any,
    relevance: Any = None,
    independence: Any = 1.0,
    recency: Any = "high",
    bias_risk: Any = "low",
    direction: str = "for",
    strength: str = "medium",
    name: str = "evidence",
) -> EvidenceWeight:
    """Translate qualitative evidence into a likelihood ratio + effective weight.

    Separates *reliability* (is the source accurate?) from *relevance* (does it
    bear on this question?), discounts non-independent and stale/biased
    evidence, and keeps direction separate from magnitude.
    """

    rel = _coerce_quality(reliability, "reliability")
    relv = _coerce_quality(relevance, "relevance", default=rel)
    indep = _coerce_quality(independence, "independence", default=1.0)
    rec = _coerce_quality(recency, "recency", default=0.8)
    bias = _coerce_quality(bias_risk, "bias_risk", default=0.25)

    sign = _DIRECTION_SIGN.get(str(direction).strip().lower())
    if sign is None:
        raise ValidationError(
            "direction must be one of for/against/neutral (or favors/disfavors)"
        )

    base_lo = _STRENGTH_LOG_ODDS.get(str(strength).strip().lower())
    if base_lo is None:
        raise ValidationError(
            "strength must be one of weak/modest/medium/strong/very_strong/decisive"
        )

    # Quality discounts the raw strength. Bias risk subtracts directly.
    quality = rel * relv * indep * rec * (1.0 - bias)
    effective_weight = indep * rel * relv  # weight for pooling (excludes magnitude)
    log_odds = sign * base_lo * quality
    lr = math.exp(log_odds)

    notes: list[str] = []
    if indep < 0.6:
        notes.append("low independence — likely shares signal with other evidence (downweighted)")
    if bias >= 0.5:
        notes.append("elevated bias risk — partisan/nonprobability source downweighted")
    if relv < 0.4:
        notes.append("low relevance to this exact question despite source reliability")
    if rec < 0.4:
        notes.append("stale — recency discount applied")
    if sign == 0.0:
        notes.append("neutral/mixed direction — contributes ~no net update")

    return EvidenceWeight(
        name=name,
        direction_sign=sign,
        suggested_lr=lr,
        log_odds_contribution=log_odds,
        effective_weight=effective_weight,
        quality_score=quality,
        notes=notes,
    )


# ── 7. Correlation / double-counting checker ────────────────────────────────


@dataclass
class EvidenceCluster:
    name: str
    items: list[str]
    raw_count: int
    effective_independent_weight: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "items": self.items,
            "raw_count": self.raw_count,
            "effective_independent_weight": _round(self.effective_independent_weight, 3),
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            f"Evidence cluster '{self.name}': {self.raw_count} item(s) →"
            f" effective independent weight {self.effective_independent_weight:.2f}"
        ]
        lines.extend(f"  - {item}" for item in self.items)
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def evidence_cluster(
    items: Sequence[Any],
    *,
    name: str = "cluster",
    shared_signal: Any = "high",
) -> EvidenceCluster:
    """Collapse items that reflect one underlying signal into one effective weight.

    Prevents over-updating when markets, ratings, and articles all trace back
    to the same poll. ``shared_signal`` is how correlated the items are.
    """

    labels = [str(item.get("name") if isinstance(item, Mapping) else item) for item in items]
    raw = len(labels)
    if raw == 0:
        raise ValidationError("evidence_cluster needs at least one item")
    rho = _coerce_quality(shared_signal, "shared_signal", default=0.8)
    # Constant-correlation effective sample size with unit weights.
    denom = raw * (1.0 + (raw - 1) * rho)
    n_eff = (raw ** 2) / denom if denom > 0 else 1.0
    notes = []
    if raw > 1 and rho >= 0.5:
        notes.append(
            f"{raw} items share substantial signal (ρ≈{rho:.2f});"
            f" count them as ≈{n_eff:.2f} independent, not {raw}"
        )
    return EvidenceCluster(
        name=name,
        items=labels,
        raw_count=raw,
        effective_independent_weight=n_eff,
        notes=notes,
    )


# ── 4. Base-rate / reference-class calculator ───────────────────────────────


@dataclass
class BaseRateBlend:
    blended_base_rate: float
    uncertainty_sd: float
    classes: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blended_base_rate": _round(self.blended_base_rate),
            "uncertainty_sd": _round(self.uncertainty_sd, 4),
            "classes": self.classes,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            f"Blended base rate: {self.blended_base_rate:.3f} (±{self.uncertainty_sd:.3f} sd)"
        ]
        for cls in self.classes:
            lines.append(
                f"  - {cls['name']}: base_rate={cls['base_rate']:.3f}"
                f"  applicability={cls['applicability']:.2f}"
            )
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def blend_base_rates(reference_classes: Sequence[Mapping[str, Any]]) -> BaseRateBlend:
    """Blend candidate reference classes weighted by applicability.

    Each class: ``{"name", "base_rate", "applicability"?, "uncertainty"?}``.
    Blends in log-odds space (applicability weights) and propagates uncertainty
    from both within-class uncertainty and between-class disagreement.
    """

    rows: list[dict[str, Any]] = []
    for index, cls in enumerate(reference_classes):
        if not isinstance(cls, Mapping):
            raise ValidationError("each reference class must be an object")
        base = _clamp_prob(cls.get("base_rate", cls.get("base_rate_dem")), "base_rate")
        applic = _coerce_quality(cls.get("applicability"), "applicability", default=0.5)
        unc = cls.get("uncertainty")
        rows.append(
            {
                "name": str(cls.get("name") or f"class_{index + 1}"),
                "base_rate": base,
                "applicability": applic,
                "uncertainty": None if unc is None else _finite(unc, "uncertainty"),
            }
        )
    if not rows:
        raise ValidationError("blend_base_rates needs at least one reference class")
    total_w = sum(r["applicability"] for r in rows)
    if total_w <= 0:
        raise ValidationError("at least one reference class must have positive applicability")

    pooled_logit = sum(r["applicability"] * logit(r["base_rate"]) for r in rows) / total_w
    blended = inv_logit(pooled_logit)

    # Between-class disagreement (applicability-weighted) on the probability scale.
    between_var = sum(
        r["applicability"] * (r["base_rate"] - blended) ** 2 for r in rows
    ) / total_w
    within_var = sum(
        r["applicability"] * (r["uncertainty"] or 0.0) ** 2 for r in rows
    ) / total_w
    uncertainty = math.sqrt(between_var + within_var)

    notes: list[str] = []
    spread = max(r["base_rate"] for r in rows) - min(r["base_rate"] for r in rows)
    if spread > 0.25:
        notes.append(
            "reference classes disagree materially — base rate is class-sensitive,"
            " lean on the most applicable class"
        )
    best = max(rows, key=lambda r: r["applicability"])
    notes.append(f"most applicable class: {best['name']} (applicability {best['applicability']:.2f})")

    return BaseRateBlend(
        blended_base_rate=blended,
        uncertainty_sd=uncertainty,
        classes=[
            {
                "name": r["name"],
                "base_rate": _round(r["base_rate"]),
                "applicability": _round(r["applicability"], 2),
            }
            for r in rows
        ],
        notes=notes,
    )


# ── 5. Poll-to-probability model helper ─────────────────────────────────────


def poll_margin_to_win_prob(
    margin: float,
    margin_sd: float,
    *,
    fundamentals_margin: float | None = None,
    shrinkage: float = 0.5,
) -> float:
    """Convert a (signed) polling margin to a win probability.

    ``margin`` is the candidate's lead in points (positive = ahead). When
    ``fundamentals_margin`` is supplied the polling margin is shrunk toward it
    by ``shrinkage`` (0 = pure polls, 1 = pure fundamentals). The win
    probability is ``P(margin > 0)`` under a normal with the given sd.
    """

    margin = _finite(margin, "margin")
    sd = _finite(margin_sd, "margin_sd")
    if sd <= 0:
        raise ValidationError("margin_sd must be positive")
    if fundamentals_margin is not None:
        s = _finite(shrinkage, "shrinkage")
        if not (0.0 <= s <= 1.0):
            raise ValidationError("shrinkage must be between 0 and 1")
        margin = (1.0 - s) * margin + s * _finite(fundamentals_margin, "fundamentals_margin")
    return normal_cdf(margin, mean=0.0, sd=sd)


@dataclass
class PollModel:
    polling_average_margin: float
    adjusted_margin: float
    uncertainty_sd: float
    win_probability: float
    polls_used: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "polling_average_margin": _round(self.polling_average_margin, 2),
            "adjusted_margin": _round(self.adjusted_margin, 2),
            "uncertainty_sd": _round(self.uncertainty_sd, 2),
            "win_probability": _round(self.win_probability),
            "polls_used": self.polls_used,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            f"Polling average margin: {self.polling_average_margin:+.1f}",
            f"Adjusted margin (fundamentals/house): {self.adjusted_margin:+.1f}",
            f"Uncertainty sd: {self.uncertainty_sd:.1f} pts",
            f"Win probability: {self.win_probability:.3f}  ({self.polls_used} poll(s))",
        ]
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def polls_to_win_probability(
    polls: Sequence[Mapping[str, Any]],
    *,
    fundamentals_margin: float | None = None,
    fundamentals_shrinkage: float = 0.4,
    days_to_election: float | None = None,
    recency_half_life_days: float = 21.0,
    base_sd: float = 3.0,
) -> PollModel:
    """End-to-end polls → win probability with industry-standard adjustments.

    Applies sample-size weighting, recency decay, sponsor/house-effect
    adjustment, fundamentals shrinkage, and time-to-election uncertainty, then
    converts the adjusted margin to a probability via the normal CDF.

    Each poll: ``{"margin", "sample_size"?, "days_old"?, "sponsor_bias"?,
    "house_effect"?, "pollster_quality"?, "mode"?}``. ``margin`` is the
    candidate's lead in points.
    """

    if not polls:
        raise ValidationError("polls_to_win_probability needs at least one poll")
    weighted_sum = 0.0
    total_w = 0.0
    margins: list[float] = []
    notes: list[str] = []
    for index, poll in enumerate(polls):
        if not isinstance(poll, Mapping):
            raise ValidationError("each poll must be an object")
        margin = _finite(poll.get("margin", poll.get("margin_dem")), "margin")
        n = _finite(poll.get("sample_size", 600), "sample_size")
        if n <= 0:
            raise ValidationError("sample_size must be positive")
        days_old = _finite(poll.get("days_old", 0), "days_old")
        if days_old < 0:
            raise ValidationError("days_old must be non-negative")
        # Sample-size weight ~ sqrt(n) (sampling error ~ 1/sqrt(n)).
        w = math.sqrt(n)
        # Recency decay (exponential half-life).
        w *= 0.5 ** (days_old / max(recency_half_life_days, _EPS))
        # Pollster quality multiplier.
        w *= _coerce_quality(poll.get("pollster_quality"), "pollster_quality", default=0.6) + 0.25
        # Nonprobability / online-panel modes downweighted.
        if str(poll.get("mode", "")).strip().lower() in {"nonprobability", "online_panel", "panel"}:
            w *= 0.5
            notes.append(f"poll {index + 1}: nonprobability mode downweighted")
        # Sponsor/house-effect adjustment (shift the margin, don't drop it).
        adj_margin = margin - _finite(poll.get("house_effect", 0.0), "house_effect")
        sponsor = str(poll.get("sponsor_bias", "")).strip().upper()
        if sponsor in {"D", "DEM", "DEMOCRAT"}:
            adj_margin -= 1.5
            notes.append(f"poll {index + 1}: D-sponsor bias adjustment (-1.5)")
        elif sponsor in {"R", "GOP", "REPUBLICAN"}:
            adj_margin += 1.5
            notes.append(f"poll {index + 1}: R-sponsor bias adjustment (+1.5)")
        weighted_sum += adj_margin * w
        total_w += w
        margins.append(adj_margin)
    if total_w <= 0:
        raise ValidationError("poll weights collapsed to zero (check recency / sample sizes)")

    polling_avg = weighted_sum / total_w
    adjusted = polling_avg
    if fundamentals_margin is not None:
        s = _finite(fundamentals_shrinkage, "fundamentals_shrinkage")
        if not (0.0 <= s <= 1.0):
            raise ValidationError("fundamentals_shrinkage must be between 0 and 1")
        adjusted = (1.0 - s) * polling_avg + s * _finite(fundamentals_margin, "fundamentals_margin")

    # Uncertainty: base polling error + between-poll spread + time-to-election drift.
    spread = _stdev(margins)
    drift = 0.0
    if days_to_election is not None:
        d = _finite(days_to_election, "days_to_election")
        if d < 0:
            raise ValidationError("days_to_election must be non-negative")
        drift = 2.0 * math.sqrt(d / 30.0)  # ~2 pts per month of horizon
    uncertainty = math.sqrt(base_sd ** 2 + spread ** 2 + drift ** 2)

    win_p = normal_cdf(adjusted, mean=0.0, sd=uncertainty)
    if len(polls) == 1:
        notes.append("single poll — uncertainty is dominated by sampling + horizon")
    return PollModel(
        polling_average_margin=polling_avg,
        adjusted_margin=adjusted,
        uncertainty_sd=uncertainty,
        win_probability=win_p,
        polls_used=len(polls),
        notes=notes,
    )


# ── 6. Market de-vig and liquidity adjustment ───────────────────────────────


def devig_binary_market(
    bid_yes: float,
    ask_yes: float,
    bid_no: float | None = None,
    ask_no: float | None = None,
) -> float:
    """Fair YES probability from a binary market, removing the vig.

    Uses the YES mid; when NO quotes are present the two mids are normalised so
    the implied probabilities sum to 1 (removes the overround / vig).
    """

    yes_mid = (_clamp_prob(bid_yes, "bid_yes") + _clamp_prob(ask_yes, "ask_yes")) / 2.0
    if bid_no is None and ask_no is None:
        return yes_mid
    no_b = _clamp_prob(bid_no, "bid_no") if bid_no is not None else 1.0 - yes_mid
    no_a = _clamp_prob(ask_no, "ask_no") if ask_no is not None else 1.0 - yes_mid
    no_mid = (no_b + no_a) / 2.0
    total = yes_mid + no_mid
    if total <= 0:
        raise ValidationError("market quotes are degenerate")
    return yes_mid / total


def normalize_categorical_market(prices: Mapping[str, float]) -> dict[str, Any]:
    """Normalise mutually-exclusive contract prices to remove the overround."""

    rows = {str(k): _clamp_prob(v, f"price[{k}]") for k, v in prices.items()}
    if not rows:
        raise ValidationError("normalize_categorical_market needs at least one contract")
    total = sum(rows.values())
    if total <= 0:
        raise ValidationError("contract prices must sum to a positive value")
    normalized = {k: _round(v / total) for k, v in rows.items()}
    return {
        "normalized": normalized,
        "overround": _round(total - 1.0, 4),
    }


@dataclass
class MarketModel:
    implied_probability: float
    uncertainty: float
    markets: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "implied_probability": _round(self.implied_probability),
            "uncertainty": _round(self.uncertainty, 4),
            "markets": self.markets,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            f"Market-implied probability: {self.implied_probability:.3f} (±{self.uncertainty:.3f})"
        ]
        for m in self.markets:
            lines.append(f"  - {m['source']}: fair={m['fair_probability']:.3f} weight={m['weight']:.2f}")
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def combine_markets(markets: Sequence[Mapping[str, Any]]) -> MarketModel:
    """De-vig each market, downweight illiquid ones, and report consensus.

    Each market may supply ``bid_yes``/``ask_yes`` (+ optional NO quotes), or a
    ``mid``/``yes_mid`` price, plus optional ``volume`` for liquidity weighting.
    """

    fairs: list[float] = []
    weights: list[float] = []
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    for index, m in enumerate(markets):
        if not isinstance(m, Mapping):
            raise ValidationError("each market must be an object")
        source = str(m.get("source") or f"market_{index + 1}")
        if "bid_yes" in m and "ask_yes" in m:
            fair = devig_binary_market(
                m["bid_yes"], m["ask_yes"], m.get("bid_no"), m.get("ask_no")
            )
            spread = abs(_clamp_prob(m["ask_yes"], "ask_yes") - _clamp_prob(m["bid_yes"], "bid_yes"))
        else:
            raw_mid = m.get("yes_mid", m.get("mid", m.get("republican_mid", m.get("probability"))))
            if raw_mid is None:
                raise ValidationError(f"market '{source}' needs bid/ask or a mid price")
            fair = _clamp_prob(raw_mid, "mid")
            spread = 0.0
        volume = _finite(m.get("volume", 1.0), "volume") if m.get("volume") is not None else 1.0
        liquidity_w = math.log10(max(10.0, volume))  # diminishing returns on size
        spread_penalty = 1.0 / (1.0 + 10.0 * spread)
        weight = max(_EPS, liquidity_w * spread_penalty)
        if spread > 0.04:
            notes.append(f"{source}: wide spread ({spread:.2f}) — downweighted as illiquid")
        fairs.append(fair)
        weights.append(weight)
        out.append({"source": source, "fair_probability": _round(fair), "weight": _round(weight, 3)})

    consensus = log_odds_pool(fairs, weights)
    disagreement = _stdev(fairs)
    # Normalise reported weights for readability.
    total_w = sum(weights)
    for entry, w in zip(out, weights):
        entry["weight"] = _round(w / total_w if total_w else 0.0, 3)
    if disagreement > 0.03:
        notes.append(f"markets disagree by ~{disagreement * 100:.1f} pts")
    return MarketModel(
        implied_probability=consensus,
        uncertainty=max(0.01, disagreement),
        markets=out,
        notes=notes,
    )


# ── 8. Sensitivity / robustness analyzer ─────────────────────────────────────


@dataclass
class SensitivityResult:
    base_probability: float
    method: str
    tornado: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_probability": _round(self.base_probability),
            "method": self.method,
            "tornado": self.tornado,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [f"Base probability: {self.base_probability:.3f}  (method: {self.method})"]
        lines.append("Tornado (most decision-relevant first):")
        for row in self.tornado:
            lines.append(
                f"  - {row['parameter']}: {row['low_probability']:.3f} … {row['high_probability']:.3f}"
                f"  (swing {row['swing'] * 100:.1f} pts)"
            )
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def sensitivity_grid(
    components: Sequence[Mapping[str, Any]],
    parameter_ranges: Mapping[str, Sequence[float]],
    *,
    method: str = "log_odds_pool",
    extremize: float = 1.0,
) -> SensitivityResult:
    """One-way sensitivity / tornado analysis over component probabilities.

    Holds all components at their base values, then sweeps each named
    component's probability over the supplied range, recording the resulting
    pooled forecast. ``parameter_ranges`` maps component name → list of
    probabilities to try (e.g. ``{"polling": [0.45, 0.55]}``); use the special
    key ``"__drop__"`` mapped to a list of names to also test dropping sources.
    """

    base_rows = _normalize_components(components)
    base_p = combine_forecasts(components, method=method, extremize=extremize).probability
    by_name = {r["name"]: r for r in base_rows}

    tornado: list[dict[str, Any]] = []
    notes: list[str] = []
    for param, values in parameter_ranges.items():
        if param == "__drop__":
            for drop_name in values:
                remaining = [r for r in base_rows if r["name"] != str(drop_name)]
                if not remaining:
                    continue
                dropped_p = combine_forecasts(remaining, method=method, extremize=extremize).probability
                tornado.append({
                    "parameter": f"drop {drop_name}",
                    "low_probability": _round(min(base_p, dropped_p)),
                    "high_probability": _round(max(base_p, dropped_p)),
                    "swing": _round(abs(dropped_p - base_p), 4),
                })
            continue
        if param not in by_name:
            raise ValidationError(f"sensitivity parameter '{param}' is not a component name")
        results = []
        for value in values:
            trial = [dict(r) for r in base_rows]
            for r in trial:
                if r["name"] == param:
                    r["probability"] = _clamp_prob(value)
            results.append(combine_forecasts(trial, method=method, extremize=extremize).probability)
        low, high = min(results), max(results)
        tornado.append({
            "parameter": param,
            "low_probability": _round(low),
            "high_probability": _round(high),
            "swing": _round(high - low, 4),
        })

    tornado.sort(key=lambda row: row["swing"], reverse=True)
    if tornado:
        notes.append(
            f"most decision-relevant uncertainty: {tornado[0]['parameter']}"
            f" (swing {tornado[0]['swing'] * 100:.1f} pts)"
        )
    return SensitivityResult(
        base_probability=base_p, method=str(method).lower(), tornado=tornado, notes=notes
    )


# ── 10. Forecast-diff explainer ─────────────────────────────────────────────


@dataclass
class ForecastDiff:
    previous_probability: float
    current_probability: float
    net_change: float
    drivers: list[dict[str, Any]]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_probability": _round(self.previous_probability),
            "current_probability": _round(self.current_probability),
            "net_change": _round(self.net_change, 4),
            "drivers": self.drivers,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [
            f"Forecast moved {self.previous_probability:.3f} → {self.current_probability:.3f}"
            f"  (net {self.net_change * 100:+.1f} pts)"
        ]
        lines.append("Drivers:")
        for d in self.drivers:
            lines.append(f"  - {d['name']}: {d['contribution_pts']:+.1f} pts")
        lines.extend(f"  note: {note}" for note in self.notes)
        return "\n".join(lines)


def forecast_diff(
    previous: float,
    current: float,
    components: Sequence[Mapping[str, Any]] | None = None,
) -> ForecastDiff:
    """Decompose a probability change into per-driver contributions (in pts).

    ``components`` may be supplied two ways:

    * As explicit drivers ``[{"name", "delta_pts"}]`` (contributions sum to the
      net change, rescaled if needed), or
    * As ``[{"name", "previous_p", "current_p", "weight"?}]`` — the function
      then attributes the log-odds pool change to each source and maps it back
      to probability points that sum to the net move.
    """

    prev = _clamp_prob(previous, "previous")
    curr = _clamp_prob(current, "current")
    net_pts = curr - prev
    drivers: list[dict[str, Any]] = []
    notes: list[str] = []

    if components:
        rows = list(components)
        if all("delta_pts" in r for r in rows):
            raw = [(str(r.get("name") or f"driver_{i+1}"), _finite(r["delta_pts"], "delta_pts"))
                   for i, r in enumerate(rows)]
            total_raw = sum(d for _, d in raw)
            # Rescale so attributed deltas sum exactly to the net move.
            scale = (net_pts) / total_raw if abs(total_raw) > _EPS else 0.0
            for name, d in raw:
                drivers.append({"name": name, "contribution_pts": _round((d * scale) * 100, 2)})
            if abs(total_raw - net_pts) > 1e-4 and abs(total_raw) > _EPS:
                notes.append("driver deltas rescaled to reconcile with the net move")
        else:
            # Attribute via log-odds pool change.
            contribs = []
            weights = [_finite(r.get("weight", 1.0), "weight") for r in rows]
            total_w = sum(weights) or 1.0
            for r, w in zip(rows, weights):
                pp = _clamp_prob(r.get("previous_p", r.get("prev_p", prev)), "previous_p")
                cp = _clamp_prob(r.get("current_p", r.get("curr_p", pp)), "current_p")
                contribs.append((str(r.get("name") or "driver"), (w / total_w) * (logit(cp) - logit(pp))))
            total_logit_shift = sum(c for _, c in contribs)
            for name, shift in contribs:
                share = (shift / total_logit_shift) if abs(total_logit_shift) > _EPS else (1.0 / len(contribs))
                drivers.append({"name": name, "contribution_pts": _round(share * net_pts * 100, 2)})

    if not drivers:
        drivers.append({"name": "net", "contribution_pts": _round(net_pts * 100, 2)})

    direction = "up" if net_pts > 0 else "down" if net_pts < 0 else "flat"
    notes.append(f"net move is {direction} {abs(net_pts) * 100:.1f} pts")
    return ForecastDiff(
        previous_probability=prev,
        current_probability=curr,
        net_change=net_pts,
        drivers=drivers,
        notes=notes,
    )


@dataclass
class ConditionalChain:
    """Result of multiplying a conditional-probability chain.

    A conditional chain decomposes a rare event P(C) into causal links
    ``P(A) · P(B|A) · P(C|A,B)``. The structured form prevents narrative
    collapse: each link is elicited separately, the chain product is
    compared to a directly-elicited unconditional estimate, and the two
    are flagged when they diverge beyond ``tolerance``.
    """

    target_name: str
    links: list[dict[str, Any]]
    chain_product: float
    unconditional_estimate: float
    divergence_abs: float
    divergence_ratio: float | None
    divergence_log: float | None
    tolerance: float
    flagged: bool
    flag_reason: str | None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_name": self.target_name,
            "links": self.links,
            "chain_product": _round(self.chain_product, 6),
            "log_chain_product": _round(math.log(max(self.chain_product, _EPS)), 4),
            "unconditional_estimate": _round(self.unconditional_estimate, 6),
            "divergence_abs": _round(self.divergence_abs, 6),
            "divergence_ratio": (
                None if self.divergence_ratio is None else _round(self.divergence_ratio, 4)
            ),
            "divergence_log": (
                None if self.divergence_log is None else _round(self.divergence_log, 4)
            ),
            "tolerance": _round(self.tolerance, 4),
            "flagged": self.flagged,
            "flag_reason": self.flag_reason,
            "notes": self.notes,
        }

    def to_text(self) -> str:
        lines = [f"Target: {self.target_name or 'P(C)'}"]
        for link in self.links:
            cond = link.get("condition") or link.get("name") or "link"
            lines.append(f"  {cond}: {float(link['probability']):.4f}")
        lines.append(f"Chain product: {self.chain_product:.4f}")
        lines.append(f"Unconditional sanity-check: {self.unconditional_estimate:.4f}")
        if self.divergence_ratio is not None:
            lines.append(
                f"Divergence: |Δ|={self.divergence_abs:.4f} "
                f"ratio={self.divergence_ratio:.2f}x"
            )
        if self.flagged:
            lines.append(f"⚠ FLAGGED: {self.flag_reason}")
        else:
            lines.append("Within tolerance — sanity check passes.")
        for note in self.notes:
            lines.append(f"  note: {note}")
        return "\n".join(lines)


def conditional_chain(
    links: Sequence[Mapping[str, Any]],
    *,
    unconditional_estimate: float,
    target_name: str = "",
    tolerance: float = 2.0,
    absolute_floor: float = 1e-4,
) -> ConditionalChain:
    """Multiply a conditional-probability chain and compare to an unconditional estimate.

    ``links`` is a list of ``{"name"|"condition", "probability"}`` items
    representing ``P(A), P(B|A), P(C|A,B), ...``. The unconditional sanity-check
    is **required** — that's the design enforcement: a conditional chain without
    a directly-elicited gut estimate is the failure mode this routine catches.

    The result is flagged when:

    * either probability is < ``absolute_floor`` and they disagree by more than
      ``absolute_floor``, or
    * the ratio of the two (chain ÷ unconditional or its reciprocal, whichever
      is larger) exceeds ``tolerance`` (default 2× — i.e. a 0.5-to-2.0 band).

    ``tolerance`` matches Samotsvety-style discipline: small ratio gaps are
    "model says X, gut says ~X, the chain is plausible"; large ones are "the
    decomposition disagrees with the outside view — go re-examine your
    conditional probabilities."
    """

    if not links:
        raise ValidationError("conditional_chain requires at least one link")
    if tolerance <= 1.0:
        raise ValidationError("tolerance must be > 1.0")

    if unconditional_estimate is None:  # pragma: no cover - normalized upstream
        raise ValidationError(
            "conditional_chain requires unconditional_estimate (the gut/outside-view check)"
        )
    unconditional = _clamp_prob(unconditional_estimate, "unconditional_estimate")

    cleaned_links: list[dict[str, Any]] = []
    chain = 1.0
    for index, raw in enumerate(links):
        if not isinstance(raw, Mapping):
            raise ValidationError(
                f"conditional_chain links[{index}] must be an object with a probability"
            )
        probability = raw.get("probability")
        if probability is None:
            for alt in ("p", "prob", "value"):
                if raw.get(alt) is not None:
                    probability = raw[alt]
                    break
        if probability is None:
            raise ValidationError(
                f"conditional_chain links[{index}] requires 'probability'"
            )
        probability = _clamp_prob(probability, f"links[{index}].probability")
        name = str(raw.get("name") or f"link_{index + 1}").strip() or f"link_{index + 1}"
        condition = str(raw.get("condition") or "").strip() or None
        entry: dict[str, Any] = {"name": name, "probability": _round(probability, 6)}
        if condition:
            entry["condition"] = condition
        if raw.get("rationale"):
            entry["rationale"] = str(raw["rationale"]).strip()
        cleaned_links.append(entry)
        chain *= probability

    divergence_abs = abs(chain - unconditional)
    if chain <= _EPS or unconditional <= _EPS:
        divergence_ratio: float | None = None
        divergence_log: float | None = None
    else:
        ratio = chain / unconditional
        # Normalize so >1 always means "chain bigger than unconditional"
        divergence_ratio = ratio
        divergence_log = math.log(ratio)

    flag_reason: str | None = None
    flagged = False
    if (chain < absolute_floor or unconditional < absolute_floor) and divergence_abs > absolute_floor:
        flagged = True
        flag_reason = (
            f"near-zero divergence: chain={chain:.2e}, unconditional={unconditional:.2e}, "
            f"|Δ|={divergence_abs:.2e}"
        )
    elif divergence_ratio is not None:
        signed = max(divergence_ratio, 1.0 / divergence_ratio)
        # Small epsilon avoids FP-noise flips right at the boundary (e.g.
        # 0.05·0.4·0.1 returns 0.002000000…001 not 0.002).
        if signed > tolerance * (1.0 + 1e-6):
            flagged = True
            direction = "above" if divergence_ratio > 1 else "below"
            flag_reason = (
                f"chain is {signed:.2f}x {direction} the unconditional estimate "
                f"(tolerance {tolerance:g}x). Re-examine the conditional probabilities or "
                f"the unconditional gut estimate."
            )

    notes = [
        f"product of {len(cleaned_links)} conditional probabilities",
        (
            "chain and unconditional agree" if not flagged
            else "chain disagrees with the outside view — DO NOT ship the forecast without reconciling"
        ),
    ]

    return ConditionalChain(
        target_name=target_name.strip(),
        links=cleaned_links,
        chain_product=chain,
        unconditional_estimate=unconditional,
        divergence_abs=divergence_abs,
        divergence_ratio=divergence_ratio,
        divergence_log=divergence_log,
        tolerance=tolerance,
        flagged=flagged,
        flag_reason=flag_reason,
        notes=notes,
    )


# ── Unified dispatch (shared by the CLI and the agent tool) ─────────────────

# Action name → set of accepted payload keys, documented for the agent tool.
BAYES_ACTIONS: dict[str, str] = {
    "lr_update": "Apply likelihood ratios to a prior. payload: prior_p, lrs[] (or log_lrs[]).",
    "decompose_update": "Infer the implied LR of a move. payload: prior_p, posterior_p.",
    "combine": "Pool probability sources. payload: components[], method, extremize, correlation_matrix.",
    "evidence_weight": "Score one piece of evidence into an LR + weight. payload: reliability, relevance, independence, recency, bias_risk, direction, strength, name.",
    "evidence_cluster": "Collapse double-counted items. payload: items[], shared_signal, name.",
    "blend_base_rates": "Blend reference classes by applicability. payload: reference_classes[].",
    "poll_to_prob": "Margin → win probability. payload: margin, margin_sd, fundamentals_margin, shrinkage.",
    "polls": "Polls → win probability pipeline. payload: polls[], fundamentals_margin, fundamentals_shrinkage, days_to_election.",
    "devig": "Fair probability from a binary market. payload: bid_yes, ask_yes, bid_no, ask_no.",
    "normalize_market": "Remove overround from categorical contracts. payload: prices{}.",
    "combine_markets": "De-vig + liquidity-weight multiple markets. payload: markets[].",
    "sensitivity": "One-way / tornado sensitivity. payload: components[], parameter_ranges{}, method, extremize.",
    "forecast_diff": "Decompose a probability move into drivers. payload: previous, current, components[].",
    "conditional_chain": (
        "Multiply a causal chain P(A)·P(B|A)·P(C|A,B)... and compare to a "
        "directly-elicited unconditional sanity-check. payload: links[], "
        "unconditional_estimate (required), target_name, tolerance."
    ),
}


def run_bayes_action(action: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run one toolkit action and return ``{action, result, rationale}``.

    ``result`` is machine-readable JSON for the ledger; ``rationale`` is a
    human-readable explanation for forecast notes. Used by both
    ``forecast bayes`` (CLI) and the ``forecast_ledger`` agent tool.
    """

    action = str(action or "").strip().lower()

    class _Payload(dict):
        """Surface missing required fields as a clean ValidationError."""

        def __missing__(self, key: str) -> Any:
            raise ValidationError(f"bayes action '{action}' requires field '{key}'")

    payload = _Payload(payload or {})

    def _packaged(result: Any) -> dict[str, Any]:
        if hasattr(result, "to_dict") and hasattr(result, "to_text"):
            return {"action": action, "result": result.to_dict(), "rationale": result.to_text()}
        return {"action": action, "result": result, "rationale": _scalar_rationale(action, result)}

    if action == "lr_update":
        prior = payload["prior_p"]
        if "log_lrs" in payload:
            posterior = log_odds_update(prior, payload["log_lrs"])
            lrs_text = ", ".join(f"{math.exp(w):.3f}" for w in payload["log_lrs"])
        else:
            posterior = apply_lrs(prior, payload.get("lrs", []))
            lrs_text = ", ".join(f"{float(lr):.3f}" for lr in payload.get("lrs", []))
        decomposition = decompose_update(prior, posterior)
        result = {
            "prior_p": _round(_clamp_prob(prior)),
            "posterior_p": _round(posterior),
            **decomposition,
        }
        rationale = (
            f"Prior {result['prior_p']:.3f} × LRs [{lrs_text}] → posterior {result['posterior_p']:.3f}"
            f" (implied LR {decomposition['implied_lr']:.3f},"
            f" {decomposition['prob_delta'] * 100:+.1f} pts)"
        )
        return {"action": action, "result": result, "rationale": rationale}

    if action == "decompose_update":
        result = decompose_update(payload["prior_p"], payload["posterior_p"])
        rationale = (
            f"Move {float(payload['prior_p']):.3f} → {float(payload['posterior_p']):.3f}"
            f" implies LR {result['implied_lr']:.3f} ({result['prob_delta'] * 100:+.1f} pts)"
        )
        return {"action": action, "result": result, "rationale": rationale}

    if action in {"combine", "pool", "combine_forecasts"}:
        return _packaged(combine_forecasts(
            payload["components"],
            method=payload.get("method", "log_odds_pool"),
            extremize=payload.get("extremize", 1.0),
            correlation_matrix=payload.get("correlation_matrix"),
        ))

    if action == "evidence_weight":
        return _packaged(evidence_weight(
            reliability=payload.get("reliability"),
            relevance=payload.get("relevance"),
            independence=payload.get("independence", 1.0),
            recency=payload.get("recency", "high"),
            bias_risk=payload.get("bias_risk", "low"),
            direction=payload.get("direction", "for"),
            strength=payload.get("strength", "medium"),
            name=payload.get("name", "evidence"),
        ))

    if action == "evidence_cluster":
        return _packaged(evidence_cluster(
            payload["items"],
            name=payload.get("name", "cluster"),
            shared_signal=payload.get("shared_signal", "high"),
        ))

    if action in {"blend_base_rates", "base_rate"}:
        return _packaged(blend_base_rates(payload["reference_classes"]))

    if action == "poll_to_prob":
        result = poll_margin_to_win_prob(
            payload["margin"], payload["margin_sd"],
            fundamentals_margin=payload.get("fundamentals_margin"),
            shrinkage=payload.get("shrinkage", 0.5),
        )
        return _packaged(result)

    if action == "polls":
        return _packaged(polls_to_win_probability(
            payload["polls"],
            fundamentals_margin=payload.get("fundamentals_margin"),
            fundamentals_shrinkage=payload.get("fundamentals_shrinkage", 0.4),
            days_to_election=payload.get("days_to_election"),
            recency_half_life_days=payload.get("recency_half_life_days", 21.0),
            base_sd=payload.get("base_sd", 3.0),
        ))

    if action == "devig":
        result = devig_binary_market(
            payload["bid_yes"], payload["ask_yes"],
            payload.get("bid_no"), payload.get("ask_no"),
        )
        return _packaged(result)

    if action in {"normalize_market", "normalize_categorical_market"}:
        return _packaged(normalize_categorical_market(payload["prices"]))

    if action == "combine_markets":
        return _packaged(combine_markets(payload["markets"]))

    if action == "sensitivity":
        return _packaged(sensitivity_grid(
            payload["components"], payload["parameter_ranges"],
            method=payload.get("method", "log_odds_pool"),
            extremize=payload.get("extremize", 1.0),
        ))

    if action in {"forecast_diff", "diff"}:
        return _packaged(forecast_diff(
            payload["previous"], payload["current"], payload.get("components"),
        ))

    if action in {"conditional_chain", "chain"}:
        unconditional = payload.get("unconditional_estimate")
        if unconditional is None:
            for alt in ("unconditional", "unconditional_p", "sanity_check"):
                if payload.get(alt) is not None:
                    unconditional = payload[alt]
                    break
        if unconditional is None:
            raise ValidationError(
                "conditional_chain requires 'unconditional_estimate' — a separately "
                "elicited gut/outside-view probability to compare against the chain product"
            )
        return _packaged(conditional_chain(
            payload["links"],
            unconditional_estimate=unconditional,
            target_name=str(payload.get("target_name") or ""),
            tolerance=float(payload.get("tolerance", 2.0)),
            absolute_floor=float(payload.get("absolute_floor", 1e-4)),
        ))

    raise ValidationError(
        f"unknown bayes action '{action}'. Available: {', '.join(sorted(BAYES_ACTIONS))}"
    )


def _scalar_rationale(action: str, result: Any) -> str:
    if isinstance(result, (int, float)):
        return f"{action}: {float(result):.4f}"
    return f"{action}: {result}"


__all__ = [
    "using_industry_libraries",
    "ensure_industry_backends",
    "BAYES_ACTIONS",
    "run_bayes_action",
    "prob_to_odds", "odds_to_prob", "logit", "inv_logit",
    "apply_lr", "apply_lrs", "log_odds_update", "decompose_update",
    "normal_cdf", "normal_ppf",
    "linear_pool", "mean_probability", "log_pool", "log_odds_pool", "geometric_pool_odds",
    "platt_scale", "platt_scale_anchored", "extremize", "de_extremize", "combine_forecasts",
    "correlation_adjusted_pool",
    "PoolResult",
    "evidence_weight", "EvidenceWeight",
    "evidence_cluster", "EvidenceCluster",
    "blend_base_rates", "BaseRateBlend",
    "poll_margin_to_win_prob", "polls_to_win_probability", "PollModel",
    "devig_binary_market", "normalize_categorical_market", "combine_markets", "MarketModel",
    "sensitivity_grid", "SensitivityResult",
    "forecast_diff", "ForecastDiff",
    "conditional_chain", "ConditionalChain",
]
