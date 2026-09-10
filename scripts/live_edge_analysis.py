"""Live-Edge Study analysis — orthogonality + (on resolved markets) scored agent-vs-market.

Reads the market-nightly records from the forecast ledger and computes the
pre-registered metrics of docs/research/live-edge-study.md §3.3:

  - Orthogonality (all records, no resolution needed): mean |Δ logit|, Pearson r of
    agent vs market, and the fraction of markets where the agent moves >0.05 from the
    price. The market-VISIBLE ForecastBench agent had ~zero divergence (it echoed); a
    search-informed market-HIDDEN agent that also echoes would falsify the premise.
  - Scored (resolved subset): agent Brier vs market Brier, the paired difference with a
    bootstrap 95% CI, simplex {market, agent} ensemble weights + beats_both, and ECE.

Read-only. Usage: python scripts/live_edge_analysis.py --db <ledger.db> [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics


def _logit(p: float, eps: float = 1e-6) -> float:
    p = min(1 - eps, max(eps, float(p)))
    return math.log(p / (1 - p))


def load_records(db: str) -> list[dict]:
    from forecasting.evaluation import market_evaluation_records

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return market_evaluation_records(con)
    finally:
        con.close()


def orthogonality(recs: list[dict]) -> dict:
    recs = [r for r in recs if r["agent_p"] is not None and r["market_p"] is not None]
    if not recs:
        return {"n": 0}
    da = [r["agent_p"] for r in recs]
    dm = [r["market_p"] for r in recs]
    dlog = [abs(_logit(a) - _logit(m)) for a, m in zip(da, dm)]
    dp = [abs(a - m) for a, m in zip(da, dm)]
    n = len(recs)
    # Pearson r of agent vs market probabilities
    try:
        r = statistics.correlation(da, dm) if n >= 2 and len(set(da)) > 1 and len(set(dm)) > 1 else float("nan")
    except statistics.StatisticsError:
        r = float("nan")
    return {
        "n": n,
        "mean_abs_logit_gap": statistics.fmean(dlog),
        "median_abs_logit_gap": statistics.median(dlog),
        "mean_abs_prob_gap": statistics.fmean(dp),
        "pearson_r_agent_vs_market": r,
        "frac_diverge_gt_0.05": sum(1 for x in dp if x > 0.05) / n,
        "frac_diverge_gt_0.10": sum(1 for x in dp if x > 0.10) / n,
    }


def _brier(ps: list[float], os_: list[float]) -> float:
    return statistics.fmean((p - o) ** 2 for p, o in zip(ps, os_))


def _ece(ps: list[float], os_: list[float], bins: int = 10) -> float:
    buckets: dict[int, list[tuple[float, float]]] = {}
    for p, o in zip(ps, os_):
        b = min(bins - 1, int(p * bins))
        buckets.setdefault(b, []).append((p, o))
    n = len(ps)
    return sum(
        (len(v) / n) * abs(statistics.fmean([p for p, _ in v]) - statistics.fmean([o for _, o in v]))
        for v in buckets.values()
    )


def scored(recs: list[dict]) -> dict:
    res = [r for r in recs if r["outcome"] is not None]
    out: dict = {"n_resolved": len(res)}
    if len(res) < 2:
        return out
    ap = [r["agent_p"] for r in res]
    mp = [r["market_p"] for r in res]
    oc = [r["outcome"] for r in res]
    ab, mb = _brier(ap, oc), _brier(mp, oc)
    out.update(
        agent_brier=ab,
        market_brier=mb,
        edge_market_minus_agent=mb - ab,
        agent_ece=_ece(ap, oc),
        base_rate=statistics.fmean(oc),
    )
    # paired bootstrap of (market_brier - agent_brier); positive => agent better
    try:
        import random

        rng = random.Random(0xA1A02)
        diffs = []
        idx = list(range(len(res)))
        for _ in range(10000):
            s = [idx[rng.randrange(len(idx))] for _ in idx]
            ab_s = statistics.fmean((ap[i] - oc[i]) ** 2 for i in s)
            mb_s = statistics.fmean((mp[i] - oc[i]) ** 2 for i in s)
            diffs.append(mb_s - ab_s)
        diffs.sort()
        out["paired_edge_ci95"] = [diffs[250], diffs[9750]]
        out["paired_edge_mean"] = statistics.fmean(diffs)
    except Exception as e:  # noqa: BLE001
        out["paired_edge_error"] = str(e)
    try:
        from forecasting.market_ensemble import simplex_brier_weights

        ens = simplex_brier_weights(oc, {"market": mp, "llm": ap})
        out["ensemble"] = {
            "weight_market": ens["weights"]["market"],
            "weight_agent": ens["weights"]["llm"],
            "loo_brier": ens["loo_ensemble_brier"],
            "beats_both": ens["beats_both"],
            "agent_weight_ci95": ens["bootstrap_ci_95"]["llm"],
        }
    except Exception as e:  # noqa: BLE001
        out["ensemble_error"] = str(e)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    recs = load_records(args.db)
    report = {
        "n_total": len(recs), "orthogonality": orthogonality(recs),
        "scored": scored([r for r in recs if r["contemporaneous"]]),
        "frozen_diagnostic": scored([r for r in recs if not r["contemporaneous"]]),
        "exclusions": {reason: sum(r["exclusion_reason"] == reason for r in recs)
                       for reason in sorted({r["exclusion_reason"] for r in recs if r["exclusion_reason"]})},
    }
    print(json.dumps(report, indent=2, default=str))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"records": recs, "report": report}, fh, indent=2, default=str)


if __name__ == "__main__":
    main()
