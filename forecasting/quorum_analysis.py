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
from typing import Any, Mapping, Sequence

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


__all__ = [
    "pearson",
    "disagreement_error_relationship",
    "collect_disagreement_error_pairs",
    "disagreement_calibration",
]
