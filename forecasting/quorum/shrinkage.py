"""Quorum James–Stein shrinkage + final-probability + market anchor (carved from ``quorum.py``).

The Wave-4 §W3.a ``shrinkage`` leaf: the one shrinkage philosophy at both BLF
layers — per-seat trial pooling (``_shrunk_logit_mean`` / ``_pool_seat_trials``,
A2) and cross-model pool shrinkage (``shrink_pool_toward_anchor``, A3) — plus the
confidence-gated ``resolve_final_probability`` override rule and the
``apply_market_anchor_discipline`` deviation guard. Imported back into
:mod:`forecasting.quorum.core` for ``run_quorum`` and the ``__all__`` surface,
and re-exported by the package façade unchanged.
"""
from __future__ import annotations

from typing import Any, Sequence

from forecasting.models import ValidationError
from forecasting.quorum.core import (
    JudgeSynthesis,
    ModelForecast,
    _POOL_SHRINK_C,
    _POOL_SHRINK_CALM_VAR,
    _POOL_SHRINK_FLOOR,
    _TRIAL_SHRINK_C,
    _TRIAL_SHRINK_FLOOR,
)

def _shrunk_logit_mean(
    probabilities: Sequence[float],
    *,
    target: float | None,
    floor: float = _TRIAL_SHRINK_FLOOR,
    c: float = _TRIAL_SHRINK_C,
) -> tuple[float, float, float]:
    """Pool trial probabilities as a James–Stein shrunken logit mean (BLF A2).

    Computes ``ℓ̂ = α·ℓ̄ + (1−α)·logit(target)`` with ``α = max(floor, 1 − c·s²)``
    clamped to [0, 1], where ``ℓ̄`` is the mean of the trial logits and ``s²`` their
    (population) variance: the noisier the trials, the smaller α, the harder the pool
    shrinks toward the anchor. ``target=None`` shrinks toward the trials' OWN logit
    mean — a strict no-op (pooled == mean), used for the market-INDEPENDENT blind
    pool so the orthogonality signal is never contaminated by the anchor. Returns
    ``(pooled_probability, alpha, var_logit)``; a single trial has ``s²=0 → α=1`` so
    the pool is exactly that trial (K=1 identity)."""

    from forecasting.bayes_toolkit import inv_logit, logit

    logits = [logit(float(p)) for p in probabilities]
    n = len(logits)
    if n == 0:
        raise ValidationError("_shrunk_logit_mean requires at least one probability")
    mean = sum(logits) / n
    var = sum((x - mean) ** 2 for x in logits) / n if n > 1 else 0.0
    target_logit = logit(float(target)) if target is not None else mean
    alpha = max(float(floor), 1.0 - float(c) * var)
    alpha = min(1.0, max(0.0, alpha))
    pooled = inv_logit(alpha * mean + (1.0 - alpha) * target_logit)
    return float(pooled), float(alpha), float(var)


def _pool_seat_trials(
    model: str,
    trials: Sequence[ModelForecast],
    *,
    market_anchor: float | None,
    floor: float = _TRIAL_SHRINK_FLOOR,
    c: float = _TRIAL_SHRINK_C,
) -> ModelForecast:
    """Pool a seat's K trials (BLF A2) into ONE representative ModelForecast.

    The COMMITTED (reconciled) numbers shrink toward the outside-view anchor — the
    market price when present, else the trials' own mean (a no-op) — via
    :func:`_shrunk_logit_mean`; the BLIND numbers pool market-INDEPENDENTLY (target
    ``None``) so ``blind_pool`` orthogonality is never contaminated by the anchor.
    The trial NEAREST the pooled number carries the seat's qualitative headline
    (rationale / reasons / crux / belief_trajectory — the pool itself is not a new
    argument), every trial (survivor and error) is recorded in ``.trials`` so a
    divergent lone-skeptic trial stays discoverable, and the pool summary lands in
    ``.trial_shrinkage``. A seat where ALL trials errored returns the first errored
    trial, labeled — excluded from the cross-model pool exactly as a single failed
    panelist is."""

    survivors = [f for f in trials if f.error is None]
    n = len(trials)
    if not survivors:
        rep = trials[0]
        rep.trial_shrinkage = {
            "n_trials": n,
            "survivors": 0,
            "alpha": None,
            "var_logit": None,
            "target": None,
            "degraded": True,
        }
        return rep

    pooled_p, alpha, var = _shrunk_logit_mean(
        [f.probability for f in survivors], target=market_anchor, floor=floor, c=c
    )
    blind = [f.blind_probability for f in survivors if f.blind_probability is not None]
    blind_pooled = (
        _shrunk_logit_mean(blind, target=None, floor=floor, c=c)[0] if blind else None
    )
    rep = min(survivors, key=lambda f: abs(f.probability - pooled_p))
    seat = ModelForecast(
        model=model,
        probability=pooled_p,
        confidence_low=rep.confidence_low,
        confidence_high=rep.confidence_high,
        rationale=rep.rationale,
        reasons_up=list(rep.reasons_up),
        reasons_down=list(rep.reasons_down),
        change_my_mind=list(rep.change_my_mind),
        crux=rep.crux,
        weight=rep.weight,
        reconcile_reason=rep.reconcile_reason,
        revision_reason=rep.revision_reason,
        belief_trajectory=list(rep.belief_trajectory),
    )
    # Mirror _run_trial's contract: blind == committed on the single-phase
    # (non-market) path, distinct on a market question.
    seat.blind_probability = blind_pooled if market_anchor is not None else pooled_p
    seat.reconciled_probability = pooled_p
    seat.trials = [
        {
            "trial": i + 1,
            "probability": round(f.probability, 6) if f.error is None else None,
            "blind_probability": (
                round(f.blind_probability, 6)
                if f.blind_probability is not None
                else None
            ),
            "crux": f.crux,
            "moved_by": (
                f.belief_trajectory[-1].get("moved_by") if f.belief_trajectory else None
            ),
            "error": f.error,
        }
        for i, f in enumerate(trials)
    ]
    seat.trial_shrinkage = {
        "n_trials": n,
        "survivors": len(survivors),
        "alpha": round(alpha, 6),
        "var_logit": round(var, 6),
        "target": (
            round(float(market_anchor), 6)
            if market_anchor is not None
            else "trial_mean"
        ),
        "degraded": len(survivors) < n,
    }
    return seat


def shrink_pool_toward_anchor(
    pool_probability: float,
    *,
    anchor: float | None,
    var_logit: float,
    floor: float = _POOL_SHRINK_FLOOR,
    c: float = _POOL_SHRINK_C,
    calm_var: float = _POOL_SHRINK_CALM_VAR,
) -> dict[str, Any]:
    """Variance-adaptively shrink the CROSS-MODEL pool toward the outside view (BLF A3).

    Mirrors A2's per-panelist James–Stein shrink (:func:`_shrunk_logit_mean`) one
    layer up: ``ℓ_shrunk = α·logit(pool) + (1−α)·logit(anchor)`` with
    ``α = max(floor, 1 − c·max(0, var_logit − calm_var))``, where ``var_logit`` is
    the CROSS-PANELIST logit variance (``disagreement.sd_logit²``). The noisier the
    panel, the smaller α, the harder the pool leans on the anchor — but α never falls
    below ``floor`` (the pool always keeps at least that much of its own signal).

    Two STRICT no-ops, each returning the pool value UNCHANGED with ``alpha=1.0`` (so
    the committed number is bit-identical to the pre-A3 pool):

      * ``anchor is None`` — nothing to shrink toward (no market link, no recorded
        prior); the default for a non-market question.
      * ``var_logit <= calm_var`` — the panel is CALM (disagreement at/below the
        calm/moderate band edge). The WHOLE calm band is a no-op, and because the
        hinge is continuous, shrinkage grows smoothly from zero just past it — no
        cliff. This is the default-ON safety case.

    Returns ``{"probability", "alpha", "var_logit", "anchor", "floor", "c",
    "calm_var", "shrunk"}`` — the pooled number plus the full provenance so every
    shrunk commit records its α and inputs.
    """

    base = {
        "probability": float(pool_probability),
        "alpha": 1.0,
        "var_logit": float(var_logit),
        "anchor": (float(anchor) if anchor is not None else None),
        "floor": float(floor),
        "c": float(c),
        "calm_var": float(calm_var),
        "shrunk": False,
    }
    if anchor is None or float(var_logit) <= float(calm_var):
        return base
    excess = float(var_logit) - float(calm_var)
    alpha = max(float(floor), 1.0 - float(c) * excess)
    alpha = min(1.0, max(0.0, alpha))
    if alpha >= 1.0:
        # Defensive: a vanishing excess lands α at the identity — keep bit-identity
        # (never round-trip the pool through logit/inv_logit for nothing).
        return base
    from forecasting.bayes_toolkit import inv_logit, logit

    pooled = inv_logit(
        alpha * logit(float(pool_probability)) + (1.0 - alpha) * logit(float(anchor))
    )
    return {**base, "probability": float(pooled), "alpha": float(alpha), "shrunk": True}


def resolve_final_probability(
    pool_probability: float,
    judge: JudgeSynthesis | None,
) -> tuple[float, str]:
    """The whole AIA P0.3 decision rule — confidence-gated supervisor override.

    Returns ``(judge.probability, 'judge_high')`` IFF the judge exists, reported
    a usable probability, AND self-declared ``directional_confidence == 'high'``;
    otherwise ``(pool_probability, 'pool')``.

    This is a PURE function (no I/O, no calibration) and is the entire override
    logic: a low/medium-confidence judge can NEVER drag the committed number off
    a sound pool. Bounded downside, gated upside.

    Composition note (terminal Platt, AIA P0.1): the caller is responsible for
    feeding the ALREADY-CALIBRATED pool here (so the ``'pool'`` branch is Platt'd
    exactly once, inside aggregation) and for Platt-scaling the RAW judge number
    on the ``'judge_high'`` branch (so the winning override is also calibrated
    exactly once). This function neither knows nor applies alpha.
    """

    if (
        judge is not None
        and judge.probability is not None
        and judge.directional_confidence == "high"
    ):
        return float(judge.probability), "judge_high"
    return float(pool_probability), "pool"


def apply_market_anchor_discipline(
    committed: float,
    *,
    market_anchor: float | None,
    justification: str | None,
    threshold_pp: float = 10.0,
) -> dict[str, Any]:
    """FIX B — enforce the market-as-prior doctrine on the committed verdict.

    The market price is the OUTSIDE-VIEW anchor. When the verdict deviates more than
    ``threshold_pp`` (default 10pp) from it WITHOUT a named edge (``justification``),
    the deviation is unjustified and the verdict is PULLED back toward the market —
    via the same honest weighted machinery :mod:`forecasting.market_ensemble` uses to
    pool a forecast with a de-vigged market: the equal-weight LOG-ODDS pool
    (:func:`forecasting.bayes_toolkit.log_odds_pool`), the KL-optimal, externally-
    Bayesian pooling operator. A justified deviation (a non-empty named edge) is
    LEFT ALONE — the discipline requires a reason, it does not forbid an edge.

    Returns ``{"probability", "deviation_pp", "justification", "pull_applied"}``.
    With no anchor the committed number passes through untouched.
    """

    if market_anchor is None:
        return {
            "probability": float(committed),
            "deviation_pp": None,
            "justification": None,
            "pull_applied": False,
        }
    anchor = float(market_anchor)
    deviation_pp = abs(float(committed) - anchor) * 100.0
    named_edge = bool((justification or "").strip())
    if deviation_pp <= float(threshold_pp) or named_edge:
        # Within discipline, or a genuine named edge justifies the deviation.
        return {
            "probability": float(committed),
            "deviation_pp": deviation_pp,
            "justification": (justification or "").strip() or None,
            "pull_applied": False,
        }
    # Unjustified over-deviation: pull toward the market in log-odds space.
    from forecasting.bayes_toolkit import log_odds_pool

    pulled = float(log_odds_pool([anchor, float(committed)]))
    return {
        "probability": pulled,
        "deviation_pp": abs(pulled - anchor) * 100.0,
        "justification": "insufficient justification — verdict pulled toward market",
        "pull_applied": True,
    }
