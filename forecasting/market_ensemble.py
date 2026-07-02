"""AIA P1.3 — simplex-constrained market+LLM Brier-minimizing ensemble.

The paper finding: a convex blend of the LLM forecast and the de-vigged market
price beats BOTH inputs on Brier (LLM 0.126 / market 0.111 / ensemble 0.106),
because the LLM carries orthogonal signal even when it loses head-to-head. This
module fits the convex weight and, crucially, proves the *additive* value with a
leave-one-out (LOO) ensemble Brier and a seeded bootstrap CI on the weights.

Pure math, no behaviour change. It is an ANALYSIS/REPORTING surface plus an
OPTIONAL fitted advisory weight: the live forecast number and the static
:mod:`forecasting.market_quality` advisory weight are untouched unless a strict,
significance-backed gate fires (see :func:`fitted_market_advisory_weight`).

We deliberately do NOT extremize/Platt the blend — the paper warns that stacking
recalibration on top of the convex blend (a different method) erases its edge.

Numpy-optional, mirroring :mod:`forecasting.market_compute`: the math is plain
stdlib by default; numpy only accelerates if already importable. For the 2-source
{market, llm} case the simplex is the interval ``w_market in [0, 1]`` and a fine
1-D grid finds the Brier minimiser exactly enough — no heavy deps.
"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence

try:  # pragma: no cover - import guard (numpy is optional, never required)
    import numpy as _np
except Exception:  # pragma: no cover - numpy optional
    _np = None


# ── tunables (all seeded / deterministic) ────────────────────────────────────

# Grid resolution for the 2-source simplex search (w_market in [0, 1]). 1001
# points => a 0.001 step, finer than any advisory weight we would ship.
GRID_STEPS = 1001
# Bootstrap for the weight CI: a fixed stream so the CI reproduces byte-for-byte.
BOOTSTRAP_SEED = 0x1A1A03
BOOTSTRAP_DRAWS = 2000
# Minimum resolved pairs before we will fit weights at all. Below this the
# fitted weight is noise; we return None and callers keep the static weight.
DEFAULT_MIN_SAMPLE = 30
# Source-name conventions for the 2-source case.
MARKET_SOURCE = "market"
LLM_SOURCE = "llm"


# ── numeric helpers ───────────────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _coerce_prob(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return _clamp01(f)


def _coerce_outcome(value: Any) -> float | None:
    """Outcomes must be in {0, 1}. Anything else is dropped (unknown/ambiguous)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f == 0.0:
        return 0.0
    if f == 1.0:
        return 1.0
    return None


def brier(predictions: Sequence[float], outcomes: Sequence[float]) -> float | None:
    """Mean squared error between predicted P(yes) and the {0,1} outcome."""
    n = min(len(predictions), len(outcomes))
    if n == 0:
        return None
    total = 0.0
    for i in range(n):
        diff = float(predictions[i]) - float(outcomes[i])
        total += diff * diff
    return total / n


def _blend(market: Sequence[float], llm: Sequence[float], w_market: float) -> list[float]:
    return [w_market * market[i] + (1.0 - w_market) * llm[i] for i in range(len(market))]


# ── the 2-source simplex solve ────────────────────────────────────────────────


def _best_w_market(
    market: Sequence[float],
    llm: Sequence[float],
    outcomes: Sequence[float],
) -> float:
    """Grid-minimise mean (w*market + (1-w)*llm - y)^2 over w in [0, 1].

    The Brier objective is a convex parabola in ``w`` (the diff is affine in w),
    so the grid minimiser is at (or one step from) the analytic vertex. We use
    the analytic vertex when the parabola is non-degenerate, clamped to [0, 1],
    and fall back to the grid otherwise — both deterministic.
    """
    n = len(outcomes)
    if n == 0:
        return 0.0
    # f(w) = mean((w*d_i + (llm_i - y_i))^2) where d_i = market_i - llm_i.
    # f'(w) = 0 => w* = -sum(d_i * (llm_i - y_i)) / sum(d_i^2).
    sdd = 0.0
    sdr = 0.0
    for i in range(n):
        d = market[i] - llm[i]
        r = llm[i] - outcomes[i]
        sdd += d * d
        sdr += d * r
    if sdd > 1e-12:
        w_star = _clamp01(-sdr / sdd)
        # Snap to the grid so the reported weight is round/reproducible.
        snapped = round(w_star * (GRID_STEPS - 1)) / (GRID_STEPS - 1)
        return snapped
    # Degenerate: market == llm everywhere. Weight is irrelevant; pick the market.
    return 1.0


def _fit_two_source(
    market: Sequence[float],
    llm: Sequence[float],
    outcomes: Sequence[float],
) -> dict[str, float]:
    w_market = _best_w_market(market, llm, outcomes)
    blended = _blend(market, llm, w_market)
    return {
        MARKET_SOURCE: w_market,
        LLM_SOURCE: 1.0 - w_market,
        "_ensemble_brier": brier(blended, outcomes) or 0.0,
    }


# ── leave-one-out (the honest additive-value number) ──────────────────────────


def _loo_ensemble_brier(
    market: Sequence[float],
    llm: Sequence[float],
    outcomes: Sequence[float],
) -> float | None:
    """Refit the weight on n-1 points, score the held-out point, average.

    This removes the in-sample optimism of scoring the ensemble at weights that
    were themselves chosen to minimise that same sample's Brier.
    """
    n = len(outcomes)
    if n < 3:
        return None
    total = 0.0
    for k in range(n):
        m_train = [market[i] for i in range(n) if i != k]
        l_train = [llm[i] for i in range(n) if i != k]
        y_train = [outcomes[i] for i in range(n) if i != k]
        w = _best_w_market(m_train, l_train, y_train)
        pred = w * market[k] + (1.0 - w) * llm[k]
        diff = pred - outcomes[k]
        total += diff * diff
    return total / n


# ── seeded bootstrap CI on the weights ────────────────────────────────────────


def _bootstrap_weight_ci(
    market: Sequence[float],
    llm: Sequence[float],
    outcomes: Sequence[float],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, list[float]]:
    """Percentile 95% CI for [w_market, w_llm] from a seeded paired bootstrap."""
    n = len(outcomes)
    rng = random.Random(seed)
    w_market_draws: list[float] = []
    for _ in range(draws):
        idx = [rng.randrange(n) for _ in range(n)]
        m = [market[i] for i in idx]
        l = [llm[i] for i in idx]
        y = [outcomes[i] for i in idx]
        w_market_draws.append(_best_w_market(m, l, y))
    w_market_draws.sort()

    def _pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        rank = (p / 100.0) * (len(values) - 1)
        lo = int(math.floor(rank))
        hi = int(math.ceil(rank))
        if lo == hi:
            return values[lo]
        return values[lo] + (values[hi] - values[lo]) * (rank - lo)

    m_lo, m_hi = _pct(w_market_draws, 2.5), _pct(w_market_draws, 97.5)
    # w_llm = 1 - w_market, so its CI is the mirror of the market CI.
    return {
        MARKET_SOURCE: [m_lo, m_hi],
        LLM_SOURCE: [1.0 - m_hi, 1.0 - m_lo],
    }


# ── public entry point ─────────────────────────────────────────────────────────


def simplex_brier_weights(
    outcomes: Sequence[float],
    sources: Mapping[str, Sequence[float]],
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
    bootstrap_draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Fit a convex Brier-minimizing blend of forecast sources.

    Parameters
    ----------
    outcomes:
        Realized binary outcomes, each in ``{0, 1}`` (others are dropped).
    sources:
        Mapping ``{source_name: predicted P(yes) per question}``. Built for the
        2-source ``{"market", "llm"}`` case (the paper). Each sequence must align
        positionally with ``outcomes``.
    min_sample:
        Below this many usable rows the fit is noise; ``weights`` is ``None``.

    Returns a dict with:
        ``weights``            — convex weights (w>=0, sum==1, one per source) or
                                 ``None`` when the sample is too small.
        ``per_source_brier``   — each source's standalone Brier.
        ``ensemble_brier``     — Brier of the blend at the fitted weights (in-sample).
        ``loo_ensemble_brier`` — leave-one-out ensemble Brier (the honest number).
        ``bootstrap_ci_95``    — seeded percentile CI per weight.
        ``n``                  — usable rows after alignment/cleaning.
        ``sources``            — the source names, in order.
        ``beats_both``         — LOO ensemble Brier < every per-source Brier.
        ``notes``              — guard/diagnostic notes.
    """
    names = list(sources.keys())
    notes: list[str] = []

    # A source that is entirely empty/absent is not a constraint on per-row
    # alignment (it triggers the degenerate single-source fallback below). Only
    # sources that carry SOME data must be present for a row to be kept.
    active = [name for name in names if any(_coerce_prob(v) is not None for v in sources.get(name) or [])]

    # Clean + align: keep only rows where the outcome and every ACTIVE source are
    # finite probabilities.
    clean_y: list[float] = []
    clean: dict[str, list[float]] = {name: [] for name in names}
    raw_n = len(outcomes)
    for i in range(raw_n):
        y = _coerce_outcome(outcomes[i])
        if y is None:
            continue
        row: dict[str, float] = {}
        ok = True
        for name in active:
            seq = sources[name]
            p = _coerce_prob(seq[i]) if i < len(seq) else None
            if p is None:
                ok = False
                break
            row[name] = p
        if not ok:
            continue
        clean_y.append(y)
        for name in active:
            clean[name].append(row[name])

    n = len(clean_y)
    per_source_brier = {
        name: brier(clean[name], clean_y) for name in names if clean[name]
    }

    # Degenerate guard: only one source actually present (or others all-empty).
    present = [name for name in names if clean.get(name)]
    if len(present) < 2:
        fallback = present[0] if present else (names[0] if names else None)
        if fallback is not None and n > 0:
            notes.append(
                f"only one source present ({fallback}); falling back to it (weight 1.0)"
            )
            weights = {name: (1.0 if name == fallback else 0.0) for name in names}
        else:
            weights = None
            notes.append("no usable source data")
        return {
            "weights": weights,
            "per_source_brier": per_source_brier,
            "ensemble_brier": per_source_brier.get(fallback) if fallback else None,
            "loo_ensemble_brier": per_source_brier.get(fallback) if fallback else None,
            "bootstrap_ci_95": None,
            "n": n,
            "sources": names,
            "beats_both": False,
            "notes": notes,
        }

    # Small-n guard: not enough to fit a weight.
    if n < max(2, int(min_sample)):
        notes.append(
            f"sample too small (n={n} < min_sample={min_sample}); weights not fitted"
        )
        return {
            "weights": None,
            "per_source_brier": per_source_brier,
            "ensemble_brier": None,
            "loo_ensemble_brier": None,
            "bootstrap_ci_95": None,
            "n": n,
            "sources": names,
            "beats_both": False,
            "notes": notes,
        }

    # 2-source simplex solve — the supported case. Reject 3+ sources rather than
    # silently fitting an order-dependent first-two subset and presenting it as a
    # full simplex point.
    if len(names) != 2:
        raise ValueError(
            "simplex_brier_weights supports exactly the 2-source {market, llm} case; "
            f"got {len(names)} sources {names!r}"
        )
    # Map to (market, llm) roles: prefer the canonical names, else positional.
    if MARKET_SOURCE in names and LLM_SOURCE in names:
        market_name, llm_name = MARKET_SOURCE, LLM_SOURCE
    else:
        market_name, llm_name = names[0], names[1]
    market = clean[market_name]
    llm = clean[llm_name]

    fit = _fit_two_source(market, llm, clean_y)
    weights = {name: 0.0 for name in names}
    weights[market_name] = fit[MARKET_SOURCE]
    weights[llm_name] = fit[LLM_SOURCE]
    ensemble_brier = fit["_ensemble_brier"]
    loo = _loo_ensemble_brier(market, llm, clean_y)

    ci_raw = _bootstrap_weight_ci(
        market, llm, clean_y, draws=int(bootstrap_draws), seed=int(seed)
    )
    bootstrap_ci_95 = {name: [0.0, 0.0] for name in names}
    bootstrap_ci_95[market_name] = ci_raw[MARKET_SOURCE]
    bootstrap_ci_95[llm_name] = ci_raw[LLM_SOURCE]

    # Honest gate: claim the blend beats both inputs ONLY against the LEAVE-ONE-OUT
    # ensemble Brier, never the optimistically-biased in-sample one. No LOO (n too
    # small) -> additive value is not proven.
    beats_both = loo is not None and all(
        per_source_brier.get(name) is not None and loo < per_source_brier[name]
        for name in names
    )

    return {
        "weights": weights,
        "per_source_brier": per_source_brier,
        "ensemble_brier": ensemble_brier,
        "loo_ensemble_brier": loo,
        "bootstrap_ci_95": bootstrap_ci_95,
        "n": n,
        "sources": names,
        "market_source": market_name,
        "llm_source": llm_name,
        "beats_both": beats_both,
        "notes": notes,
    }


# ── ledger collector: pull (market, llm, outcome) triples ─────────────────────


def collect_market_llm_triples(
    ledger: Any,
    *,
    forecast_origin: str | None = "live",
    market_baseline_types: Sequence[str] = ("market_price", "market", "imported_market"),
) -> dict[str, Any]:
    """Collect aligned (market_price, agent_forecast, outcome) triples.

    Joins resolved binary score_records (the agent/LLM forecast + realized
    outcome) to their market baseline via ``baseline_comparisons``. The stored
    baseline probability is de-vigged through
    :func:`forecasting.bayes_toolkit.devig_binary_market` when it is a raw market
    YES price (a single-price baseline de-vigs to itself; a paired YES/NO baseline
    has its overround removed).

    Returns ``{"outcomes": [...], "sources": {"market": [...], "llm": [...]},
    "n": int, "skipped": int, "notes": [...]}`` ready for
    :func:`simplex_brier_weights`.
    """
    from forecasting import bayes_toolkit
    from forecasting.models import LedgerNotFoundError

    market_types = {str(t).lower() for t in market_baseline_types}
    outcomes: list[float] = []
    market_probs: list[float] = []
    llm_probs: list[float] = []
    skipped = 0
    notes: list[str] = []

    # ONE row per question so a question with several resolved live score revisions
    # cannot duplicate the same market price + outcome (which would inflate n and
    # break the paired-bootstrap i.i.d. assumption). list_scores is scored_at-DESC,
    # so the first complete triple per question is the most recent.
    seen_questions: set[str] = set()
    scores = ledger.list_scores(forecast_origin=forecast_origin, calibration_eligible=None)
    for score in scores:
        if score.question_id in seen_questions:
            continue
        # Only resolved binary questions carry a single P(yes) + a {0,1} outcome.
        try:
            question = ledger.get_question(score.question_id)
        except LedgerNotFoundError:
            skipped += 1
            continue
        if question.outcome_space.type != "binary":
            continue
        outcome = ledger._binary_outcome_value(score, question.outcome_space)
        if outcome is None:
            skipped += 1
            continue
        try:
            snapshot = ledger.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            skipped += 1
            continue
        llm_p = _coerce_prob(snapshot.probability_or_distribution)
        if llm_p is None:
            skipped += 1
            continue

        # First market-typed baseline for this question (as_of-ascending order).
        market_p: float | None = None
        for baseline in ledger.list_baseline_comparisons(score.question_id):
            if str(baseline.get("baseline_type") or "").lower() not in market_types:
                continue
            raw = ledger._baseline_probability_value(baseline)
            market_p = _devig_market_baseline(raw, baseline, bayes_toolkit)
            if market_p is not None:
                break
        if market_p is None:
            continue

        seen_questions.add(score.question_id)
        outcomes.append(outcome)
        market_probs.append(market_p)
        llm_probs.append(llm_p)

    if skipped:
        notes.append(f"{skipped} resolved record(s) skipped (non-binary outcome / unreadable)")
    return {
        "outcomes": outcomes,
        "sources": {MARKET_SOURCE: market_probs, LLM_SOURCE: llm_probs},
        "n": len(outcomes),
        "skipped": skipped,
        "notes": notes,
    }


def _devig_market_baseline(raw: Any, baseline: Mapping[str, Any], bayes_toolkit: Any) -> float | None:
    """De-vig a stored market baseline into a fair YES probability.

    The baseline metadata may carry raw quotes (``bid_yes``/``ask_yes`` + NO),
    in which case we de-vig properly; otherwise a stored single YES probability
    de-vigs to itself.
    """
    meta = dict(baseline.get("metadata") or {})
    bid_yes = meta.get("bid_yes")
    ask_yes = meta.get("ask_yes")
    if bid_yes is not None and ask_yes is not None:
        try:
            return _clamp01(
                bayes_toolkit.devig_binary_market(
                    float(bid_yes),
                    float(ask_yes),
                    bid_no=meta.get("bid_no"),
                    ask_no=meta.get("ask_no"),
                )
            )
        except Exception:
            pass
    return _coerce_prob(raw)


# ── optional fitted advisory weight (the ONLY thing that could change a live ──
#    number — and only behind a strict, significance-backed gate) ──────────────


def fitted_market_advisory_weight(
    result: Mapping[str, Any],
    *,
    static_weight: float,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Decide whether to ship the fitted blend weight as the advisory weight.

    Returns ``{"weight": float, "fitted": bool, "reason": str}``. The fitted
    weight ships ONLY when ALL hold:
      * sample is sufficient (n >= min_sample, weights were fitted),
      * the LOO ensemble Brier beats BOTH inputs (honest additive value), and
      * the LLM weight's bootstrap 95% CI excludes 0 (the orthogonal signal is
        statistically real, not a lucky in-sample tilt).
    Otherwise the existing ``static_weight`` is returned UNCHANGED.

    The returned ``weight`` is the fitted market weight (== ``w_market``), so it
    is a drop-in for :mod:`forecasting.market_quality`'s advisory multiplier.
    """
    weights = result.get("weights")
    n = int(result.get("n") or 0)
    if not weights or n < int(min_sample):
        return {"weight": static_weight, "fitted": False, "reason": "insufficient sample / weights not fitted"}

    if not result.get("beats_both"):
        return {"weight": static_weight, "fitted": False, "reason": "LOO ensemble does not beat both inputs"}

    ci = result.get("bootstrap_ci_95") or {}
    llm_name = result.get("llm_source", LLM_SOURCE)
    llm_ci = ci.get(llm_name)
    if not llm_ci or len(llm_ci) != 2 or llm_ci[0] <= 0.0:
        return {"weight": static_weight, "fitted": False, "reason": "LLM weight CI does not exclude 0"}

    market_name = result.get("market_source", MARKET_SOURCE)
    fitted_w = float(weights.get(market_name, static_weight))
    return {
        "weight": fitted_w,
        "fitted": True,
        "reason": (
            f"fitted blend ships: n={n}, LOO Brier "
            f"{result.get('loo_ensemble_brier'):.4f} beats both inputs, "
            f"LLM weight CI {llm_ci[0]:.3f}-{llm_ci[1]:.3f} excludes 0"
        ),
    }


def complementarity_report(
    ledger: Any,
    *,
    forecast_origin: str | None = "live",
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """End-to-end read-only report: collect triples, fit, and describe the gate.

    Wraps :func:`collect_market_llm_triples` + :func:`simplex_brier_weights` +
    :func:`fitted_market_advisory_weight` (against the STATIC advisory weight, so
    the report shows whether a fitted weight WOULD ship without shipping it).
    """
    from forecasting.market_quality import _TIER_WEIGHTS  # liquid tier == 1.0 baseline

    collected = collect_market_llm_triples(ledger, forecast_origin=forecast_origin)
    fit = simplex_brier_weights(
        collected["outcomes"], collected["sources"], min_sample=min_sample
    )
    static_weight = float(_TIER_WEIGHTS["liquid"])  # 1.0 — the un-discounted advisory anchor
    decision = fitted_market_advisory_weight(
        fit, static_weight=static_weight, min_sample=min_sample
    )
    return {
        "n": collected["n"],
        "skipped": collected["skipped"],
        "weights": fit.get("weights"),
        "per_source_brier": fit.get("per_source_brier"),
        "ensemble_brier": fit.get("ensemble_brier"),
        "loo_ensemble_brier": fit.get("loo_ensemble_brier"),
        "bootstrap_ci_95": fit.get("bootstrap_ci_95"),
        "beats_both": fit.get("beats_both", False),
        "advisory_weight_decision": decision,
        "notes": [*collected.get("notes", []), *fit.get("notes", [])],
    }


# ── MARKET-HIDDEN backtest arm: collect triples from ONE backtest run ─────────
#
# The live collector above joins resolved LIVE score_records to their market
# baseline. For the market-hidden ForecastBench arm we need the SAME (market,
# agent, outcome) triples but scoped to a SINGLE backtest RUN — the arm where the
# market price was scored as a baseline yet WITHHELD from the agent's prompt. This
# reuses the identical extraction (agent snapshot probability + realized outcome +
# de-vigged market baseline); only the row source differs (run cases, not live
# scores). No statistics are reimplemented: the report below feeds these triples
# straight into :func:`simplex_brier_weights` (P1.3) and
# :func:`forecasting.bayes_toolkit.log_odds_pool`.


def collect_backtest_market_llm_triples(
    ledger: Any,
    run_id: str,
    *,
    market_baseline_types: Sequence[str] = ("market_price", "market", "imported_market"),
) -> dict[str, Any]:
    """Collect aligned (market_price, agent_forecast, outcome) triples for ONE run.

    Mirrors :func:`collect_market_llm_triples` but iterates the backtest run's
    cases: each scored case yields the agent forecast (its snapshot probability),
    the realized binary outcome, and the FIRST market-typed baseline_comparison
    (de-vigged through the same helper). Returns the same shape ready for
    :func:`simplex_brier_weights`.
    """
    from forecasting import bayes_toolkit
    from forecasting.models import LedgerNotFoundError

    market_types = {str(t).lower() for t in market_baseline_types}
    outcomes: list[float] = []
    market_probs: list[float] = []
    llm_probs: list[float] = []
    skipped = 0
    notes: list[str] = []

    for case in ledger.list_backtest_cases(run_id):
        score_id = case.get("score_record_id")
        if not score_id:
            skipped += 1
            continue
        try:
            score = ledger.get_score(score_id)
        except LedgerNotFoundError:
            skipped += 1
            continue
        try:
            question = ledger.get_question(score.question_id)
        except LedgerNotFoundError:
            skipped += 1
            continue
        # Only resolved binary questions carry a single P(yes) + a {0,1} outcome.
        if question.outcome_space.type != "binary":
            continue
        outcome = ledger._binary_outcome_value(score, question.outcome_space)
        if outcome is None:
            skipped += 1
            continue
        try:
            snapshot = ledger.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            skipped += 1
            continue
        llm_p = _coerce_prob(snapshot.probability_or_distribution)
        if llm_p is None:
            skipped += 1
            continue

        # First market-typed baseline for THIS case (via its own comparison refs,
        # so a question that recurs across cutoffs keeps each forecast paired with
        # its own baseline). De-vig is identical to the live collector.
        market_p: float | None = None
        for ref in case.get("baseline_comparison_refs") or []:
            try:
                baseline = ledger.get_baseline_comparison(ref)
            except LedgerNotFoundError:
                continue
            if str(baseline.get("baseline_type") or "").lower() not in market_types:
                continue
            if not baseline.get("score_record_id"):
                continue  # baseline was not scored -> not a usable paired row
            raw = ledger._baseline_probability_value(baseline)
            market_p = _devig_market_baseline(raw, baseline, bayes_toolkit)
            if market_p is not None:
                break
        if market_p is None:
            continue

        outcomes.append(outcome)
        market_probs.append(market_p)
        llm_probs.append(llm_p)

    if skipped:
        notes.append(f"{skipped} case(s) skipped (unscored / non-binary outcome / unreadable)")
    return {
        "outcomes": outcomes,
        "sources": {MARKET_SOURCE: market_probs, LLM_SOURCE: llm_probs},
        "n": len(outcomes),
        "skipped": skipped,
        "notes": notes,
    }


def market_hidden_pool_report(
    ledger: Any,
    run_id: str,
    *,
    min_sample: int = DEFAULT_MIN_SAMPLE,
) -> dict[str, Any]:
    """Market-hidden arm head-to-head + pool report over ONE backtest run.

    Read-only. Over the run's paired (market, agent, outcome) triples it reports:

    * ``agent_brier`` / ``market_brier`` — standalone Brier of each source.
    * ``agent_edge_vs_market`` — ``market_brier - agent_brier`` (positive == the
      agent, forecasting WITHOUT seeing the price, beat the market).
    * ``win_rate_vs_market`` — fraction of cases where the agent's per-case Brier
      is strictly lower than the market's (ties count as a half-win).
    * ``pooled_brier`` — Brier of the EQUAL-WEIGHT log-odds pool of the agent and
      market forecasts (reuses :func:`forecasting.bayes_toolkit.log_odds_pool`).
    * ``pool_beats_both`` — whether that fixed pool's Brier beats BOTH standalones.
    * ``fitted`` — the P1.3 simplex complementarity block (fitted convex weights,
      LOO ensemble Brier, ``beats_both``) via :func:`simplex_brier_weights`, the
      HONEST out-of-sample complementarity test.

    The log-odds pool + agent-vs-market comparison answer "does the agent
    manufacture signal ORTHOGONAL to the withheld price?"; the fitted simplex block
    proves whether that orthogonal signal has additive value out-of-sample.
    """
    from forecasting import bayes_toolkit

    collected = collect_backtest_market_llm_triples(ledger, run_id)
    outcomes = collected["outcomes"]
    market = collected["sources"][MARKET_SOURCE]
    agent = collected["sources"][LLM_SOURCE]
    n = collected["n"]

    agent_brier = brier(agent, outcomes)
    market_brier = brier(market, outcomes)
    agent_edge = (
        market_brier - agent_brier
        if agent_brier is not None and market_brier is not None
        else None
    )

    # Equal-weight log-odds pool per case (reuses the toolkit; interior clamp there
    # keeps p=0/1 finite). Pool over the SAME paired rows the Briers use.
    pooled = [_clamp01(bayes_toolkit.log_odds_pool([m, a])) for m, a in zip(market, agent)]
    pooled_brier = brier(pooled, outcomes)
    pool_beats_both = (
        pooled_brier is not None
        and agent_brier is not None
        and market_brier is not None
        and pooled_brier < agent_brier
        and pooled_brier < market_brier
    )

    # Per-case win-rate vs market (ties == half-win), matching the head-to-head
    # convention used elsewhere (lower Brier wins).
    wins = 0.0
    for m, a, y in zip(market, agent, outcomes):
        agent_case = (a - y) ** 2
        market_case = (m - y) ** 2
        if agent_case < market_case:
            wins += 1.0
        elif agent_case == market_case:
            wins += 0.5
    win_rate_vs_market = (wins / n) if n else None

    fit = simplex_brier_weights(outcomes, collected["sources"], min_sample=min_sample)

    return {
        "run_id": run_id,
        "n": n,
        "skipped": collected["skipped"],
        "agent_brier": agent_brier,
        "market_brier": market_brier,
        "agent_edge_vs_market": agent_edge,
        "win_rate_vs_market": win_rate_vs_market,
        "pooled_brier": pooled_brier,
        "pool_beats_both": pool_beats_both,
        "fitted": {
            "weights": fit.get("weights"),
            "ensemble_brier": fit.get("ensemble_brier"),
            "loo_ensemble_brier": fit.get("loo_ensemble_brier"),
            "beats_both": fit.get("beats_both", False),
            "bootstrap_ci_95": fit.get("bootstrap_ci_95"),
        },
        "notes": [*collected.get("notes", []), *fit.get("notes", [])],
    }
