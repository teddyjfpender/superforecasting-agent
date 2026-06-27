"""Disagreement → error learning loop for quorum forecasts.

The quorum's disagreement scalar is persisted on every quorum panel run (inside
``spread_summary``; see :func:`forecasting.panel.disagreement_signal`). Once a
question resolves and is scored, we can ask the question that makes disagreement
*learnable* rather than decorative:

    when the model panel disagreed this much, how wrong was the aggregate?

This module joins quorum panel runs to their resolved score records by question
and summarises the relationship — a correlation plus mean Brier per disagreement
band. A positive correlation says wide model-disagreement predicts larger error,
which is exactly the signal a calibration lesson would encode ("in this domain,
when quorum disagreement is high, widen the band / shrink toward base rate").

The statistics are pure functions (unit-tested without a ledger); the ledger
join is a thin wrapper. For prospective validation, the same disagreement scalar
can be produced at an information-frontier cutoff via the agent-protocol backtest
replay (``forecasting.agent_protocol``) and fed through the same summary — the
simulation harness for the relationship before it is trusted live.
"""

from __future__ import annotations

import math
import random
from typing import Any, Mapping, Sequence

from forecasting.bayes_toolkit import mean_probability
from forecasting.panel import _disagreement_band


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation, or None when undefined (n<2 or zero variance)."""

    n = len(xs)
    if n < 2 or len(ys) != n:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def disagreement_error_relationship(
    pairs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarise (disagreement_index, brier) pairs into a learnable readout.

    Each pair needs ``disagreement_index`` and ``brier``. Returns the sample
    size, the Pearson correlation between disagreement and Brier error, mean
    Brier per disagreement band, and a one-line interpretation.
    """

    clean = [
        (float(p["disagreement_index"]), float(p["brier"]))
        for p in pairs
        if p.get("disagreement_index") is not None and p.get("brier") is not None
    ]
    if not clean:
        return {"n": 0, "correlation": None, "bands": {}, "interpretation": "no scored quorum forecasts yet"}

    xs = [c[0] for c in clean]
    ys = [c[1] for c in clean]
    corr = pearson(xs, ys)

    bands: dict[str, dict[str, Any]] = {}
    for di, brier in clean:
        band = _disagreement_band(di)
        bucket = bands.setdefault(band, {"count": 0, "_sum": 0.0})
        bucket["count"] += 1
        bucket["_sum"] += brier
    for bucket in bands.values():
        bucket["mean_brier"] = round(bucket.pop("_sum") / bucket["count"], 6)

    if corr is None:
        interp = "not enough variation to relate disagreement to error yet"
    elif corr > 0.2:
        interp = (
            "higher model-disagreement predicts larger error — widen the band / "
            "shrink toward base rate when the quorum splits"
        )
    elif corr < -0.2:
        interp = (
            "higher disagreement tracks *lower* error here — the panel may be "
            "overconfident when it agrees; treat consensus with more suspicion"
        )
    else:
        interp = "no strong relationship between disagreement and error so far"

    return {
        "n": len(clean),
        "correlation": None if corr is None else round(corr, 4),
        "bands": bands,
        "interpretation": interp,
    }


def collect_disagreement_error_pairs(ledger: Any) -> list[dict[str, Any]]:
    """Join quorum panel runs to their resolved score records by question."""

    scores_by_q: dict[str, Any] = {}
    for score in ledger.list_scores():
        if score.brier_score is None:
            continue
        # Keep the first (most recent — list_scores orders by scored_at DESC).
        scores_by_q.setdefault(score.question_id, score)

    pairs: list[dict[str, Any]] = []
    for panel in ledger.list_panel_runs():
        if (panel.get("triggered_by") or "") != "quorum":
            continue
        score = scores_by_q.get(panel.get("question_id"))
        if score is None:
            continue
        di = (panel.get("spread_summary") or {}).get("disagreement_index")
        if di is None:
            continue
        pairs.append(
            {
                "question_id": panel.get("question_id"),
                "panel_run_id": panel.get("id"),
                "disagreement_index": di,
                "disagreement_band": _disagreement_band(float(di)),
                "brier": score.brier_score,
                "log": score.log_score,
                "domain": score.domain,
            }
        )
    return pairs


def disagreement_calibration(ledger: Any) -> dict[str, Any]:
    """Full report: the joined pairs plus the learnable relationship."""

    pairs = collect_disagreement_error_pairs(ledger)
    report = disagreement_error_relationship(pairs)
    report["pairs"] = pairs
    return report


# ── AIA P1.4: ensemble-size variance-reduction analysis ──────────────────────
#
# How many model draws does a quorum actually need? Brier of the MEAN-pooled
# ensemble has a variance that falls as you add independent draws. The curve has
# a characteristic shape: a sharp drop from k=1 to roughly k~=5, then a plateau —
# extra draws past the knee buy diminishing variance reduction. These are PURE
# functions: resample, mean-pool, Brier-score, and report the curve + a variance
# decomposition. They are read-only analysis surfaced in the bench/backtest
# output; they never touch the committed forecast or the live default counts.


def _brier(probability: float, outcome: float) -> float:
    """Binary Brier score: ``(p - y)^2`` for outcome ``y in {0, 1}``."""

    return (float(probability) - float(outcome)) ** 2


def bootstrap_ensemble_curve(
    probabilities: Sequence[float],
    outcome: float,
    *,
    seed: int = 0,
    draws: int = 500,
    max_k: int | None = None,
) -> dict[str, Any]:
    """Bootstrap the Brier-vs-ensemble-size curve for one resolved question.

    For each ensemble size ``k = 1..M`` (``M = len(probabilities)`` or ``max_k``),
    draw ``draws`` bootstrap subsets of size ``k`` (sampling the per-draw
    forecasts WITH replacement, seeded), MEAN-pool each subset into a single
    probability, Brier-score it against ``outcome``, and report the mean Brier and
    a 95% bootstrap CI (2.5/97.5 percentiles) per ``k``. Deterministic given
    ``seed``.

    The expected shape is a sharp drop from ``k=1`` toward ``k~=5`` then a
    plateau: the mean Brier converges to the Brier of the full-panel mean and the
    CI narrows monotonically (in expectation) as ``k`` grows. PURE — no I/O.
    """

    probs = [float(p) for p in probabilities]
    if not probs:
        raise ValueError("bootstrap_ensemble_curve requires at least one probability")
    y = float(outcome)
    m = len(probs)
    upper = m if max_k is None else max(1, min(int(max_k), m))
    draws = max(1, int(draws))
    rng = random.Random(seed)

    curve: list[dict[str, Any]] = []
    for k in range(1, upper + 1):
        briers: list[float] = []
        for _ in range(draws):
            subset = [probs[rng.randrange(m)] for _ in range(k)]
            pooled = mean_probability(subset)
            briers.append(_brier(pooled, y))
        briers.sort()
        n = len(briers)
        mean_b = sum(briers) / n
        lo = briers[max(0, int(math.floor(0.025 * (n - 1))))]
        hi = briers[min(n - 1, int(math.ceil(0.975 * (n - 1))))]
        curve.append(
            {
                "k": k,
                "mean_brier": round(mean_b, 6),
                "ci95_low": round(lo, 6),
                "ci95_high": round(hi, 6),
                "ci95_width": round(hi - lo, 6),
            }
        )

    full_brier = _brier(mean_probability(probs), y)
    return {
        "ensemble_size": m,
        "draws": draws,
        "seed": seed,
        "outcome": y,
        "full_panel_mean_brier": round(full_brier, 6),
        "curve": curve,
    }


def variance_decomposition(
    run_forecasts: Sequence[Sequence[float]],
    outcomes: Sequence[float],
) -> dict[str, Any]:
    """Split forecast Brier variance into SAMPLING vs QUESTION components.

    ``run_forecasts[i]`` is the list of per-draw probabilities for question ``i``
    (the LLM stochasticity across resampled draws of one brief), and
    ``outcomes[i]`` its resolved 0/1 outcome. For each run we record BOTH:

      * ``brier_of_mean`` — Brier of the mean-pooled forecast, and
      * ``mean_of_brier`` — the mean of the individual draws' Briers,

    so the Jensen gap (``mean_of_brier - brier_of_mean >= 0``) is visible per run
    and in aggregate — that non-negative gap is exactly the accuracy the simple
    mean buys by averaging away SAMPLING noise.

    SAMPLING variance is the within-question variance of the per-draw forecasts
    (LLM stochasticity); QUESTION variance is the between-question variance of the
    mean-pooled forecasts (genuine question-to-question signal). PURE — for the
    backtest/quorum analysis readout, NEVER the committed forecast.
    """

    if len(run_forecasts) != len(outcomes):
        raise ValueError("run_forecasts and outcomes must align")
    if not run_forecasts:
        return {
            "n_runs": 0,
            "sampling_variance": None,
            "question_variance": None,
            "mean_brier_of_mean": None,
            "mean_mean_of_brier": None,
            "jensen_gap": None,
            "runs": [],
        }

    runs: list[dict[str, Any]] = []
    within_vars: list[float] = []
    pooled_means: list[float] = []
    for draws, outcome in zip(run_forecasts, outcomes):
        ps = [float(p) for p in draws]
        if not ps:
            raise ValueError("each run needs at least one draw forecast")
        y = float(outcome)
        pooled = mean_probability(ps)
        pooled_means.append(pooled)
        brier_of_mean = _brier(pooled, y)
        mean_of_brier = sum(_brier(p, y) for p in ps) / len(ps)
        # Population within-run variance of the draws (LLM sampling noise).
        if len(ps) == 1:
            within = 0.0
        else:
            mu = sum(ps) / len(ps)
            within = sum((p - mu) ** 2 for p in ps) / len(ps)
        within_vars.append(within)
        runs.append(
            {
                "n_draws": len(ps),
                "pooled_probability": round(pooled, 6),
                "outcome": y,
                "brier_of_mean": round(brier_of_mean, 6),
                "mean_of_brier": round(mean_of_brier, 6),
                "jensen_gap": round(mean_of_brier - brier_of_mean, 6),
                "sampling_variance": round(within, 6),
            }
        )

    sampling_variance = sum(within_vars) / len(within_vars)
    if len(pooled_means) == 1:
        question_variance = 0.0
    else:
        gm = sum(pooled_means) / len(pooled_means)
        question_variance = sum((p - gm) ** 2 for p in pooled_means) / len(pooled_means)
    mean_brier_of_mean = sum(r["brier_of_mean"] for r in runs) / len(runs)
    mean_mean_of_brier = sum(r["mean_of_brier"] for r in runs) / len(runs)
    return {
        "n_runs": len(runs),
        "sampling_variance": round(sampling_variance, 6),
        "question_variance": round(question_variance, 6),
        "mean_brier_of_mean": round(mean_brier_of_mean, 6),
        "mean_mean_of_brier": round(mean_mean_of_brier, 6),
        "jensen_gap": round(mean_mean_of_brier - mean_brier_of_mean, 6),
        "runs": runs,
    }


def collect_ensemble_runs(ledger: Any) -> list[dict[str, Any]]:
    """Join quorum panel runs to resolved binary outcomes for ensemble analysis.

    Each returned run carries the per-panelist ``probabilities`` (the draws of one
    brief), the binary ``outcome`` (1.0 yes / 0.0 no), and identifiers. Read-only:
    only quorum-triggered, binary, resolved runs with >=2 non-trimmed draws are
    kept — exactly the inputs :func:`bootstrap_ensemble_curve` and
    :func:`variance_decomposition` expect.
    """

    scores_by_q: dict[str, Any] = {}
    for score in ledger.list_scores():
        if score.brier_score is None:
            continue
        scores_by_q.setdefault(score.question_id, score)

    runs: list[dict[str, Any]] = []
    for panel in ledger.list_panel_runs():
        if (panel.get("triggered_by") or "") != "quorum":
            continue
        qid = panel.get("question_id")
        score = scores_by_q.get(qid)
        if score is None:
            continue
        try:
            outcome_space = ledger.get_question(qid).outcome_space
        except Exception:  # noqa: BLE001 — skip questions we cannot resolve
            continue
        if getattr(outcome_space, "type", None) != "binary":
            continue
        outcome = ledger._binary_outcome_value(score, outcome_space)
        if outcome is None:
            continue
        probs = [
            float(e["probability"])
            for e in panel.get("estimates", [])
            if e.get("probability") is not None and not e.get("trimmed")
        ]
        if len(probs) < 2:
            continue
        runs.append(
            {
                "question_id": qid,
                "panel_run_id": panel.get("id"),
                "probabilities": probs,
                "outcome": outcome,
                "brier": score.brier_score,
                "domain": score.domain,
            }
        )
    return runs


def ensemble_bench(
    ledger: Any,
    *,
    seed: int = 0,
    draws: int = 500,
) -> dict[str, Any]:
    """Read-only ensemble-size + variance-reduction readout over resolved quorums.

    Computes a PER-QUESTION Brier-vs-ensemble-size curve (each question's draws
    scored against its OWN realized 0/1 outcome — a proper Brier score) and then
    AVERAGES the per-k mean Brier across questions for the headline curve. (Pooling
    draws across questions against a fractional cross-question resolution rate would
    be an improper score, so we never do that.) Analysis ONLY — it never alters a
    committed forecast and never changes the live default ensemble size.
    """

    runs = collect_ensemble_runs(ledger)
    if not runs:
        return {"n_runs": 0, "curve": None, "variance": None}

    # Cap k at the smallest ensemble so EVERY question contributes to every k.
    max_k = min(len(r["probabilities"]) for r in runs)
    per_run = [
        bootstrap_ensemble_curve(
            r["probabilities"], r["outcome"], seed=seed, draws=draws, max_k=max_k
        )
        for r in runs
    ]
    curve: list[dict[str, Any]] = []
    for idx, k in enumerate(range(1, max_k + 1)):
        mbs = [pr["curve"][idx]["mean_brier"] for pr in per_run]
        widths = [pr["curve"][idx]["ci95_width"] for pr in per_run]
        curve.append(
            {
                "k": k,
                "mean_brier": round(sum(mbs) / len(mbs), 6),  # averaged across questions
                "mean_ci95_width": round(sum(widths) / len(widths), 6),
                "n_questions": len(mbs),
            }
        )
    full = sum(pr["full_panel_mean_brier"] for pr in per_run) / len(per_run)
    variance = variance_decomposition(
        [r["probabilities"] for r in runs],
        [r["outcome"] for r in runs],
    )
    return {
        "n_runs": len(runs),
        "seed": seed,
        "draws": draws,
        "max_k": max_k,
        "full_panel_mean_brier": round(full, 6),
        "curve": curve,
        "variance": variance,
    }


__all__ = [
    "pearson",
    "disagreement_error_relationship",
    "collect_disagreement_error_pairs",
    "disagreement_calibration",
    "bootstrap_ensemble_curve",
    "variance_decomposition",
    "collect_ensemble_runs",
    "ensemble_bench",
]
