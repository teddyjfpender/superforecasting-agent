"""The Shrinkage Study — does an α<1 terminal Platt slope help in the evidence-thin stratum?

READ-ONLY measurement (the GATE-1 pattern; see ``docs/research/shrinkage-study.md``).
Nothing here mutates a forecast, a default, or the ledger. It measures whether the
UNMEASURED HALF of the Platt slope — SHRINKAGE toward 0.5 (``α < 1``) — lowers Brier on
any resolved-binary stratum of the real ledger, and applies the pre-registered decision
rule frozen in the design doc.

Design invariants this module honours:

* **Non-pooling discipline.** Strata are gathered per ``forecast_origin`` with
  :meth:`ForecastLedger.list_scores` exactly as ``build_forecasting_evidence_status``
  does — ``live`` / ``backtest`` / ``imported_baseline`` are never summed into one
  calibration set. Only an explicitly-labelled ``global (agent, pooled)`` diagnostic
  pools origins, and it is NOT an activation basis.
* **Contamination control.** Each observation uses the RAW pre-adjustment probability
  when a lesson previously moved the committed number (mirrors
  ``forecasting/ledger/scoring.py:_bias_observations``).
* **Reuse the machinery.** The recalibration kernel is
  :func:`forecasting.bayes_toolkit.platt_scale`; the significance test is the existing
  seeded AIA-P0.2 paired recenter-at-zero bootstrap
  (``ForecastLedger._paired_bootstrap``). No new bootstrap is written.

Run it read-only against the default (or ``FORECAST_LEDGER_DB``) ledger:

    python -m forecasting.shrinkage_study            # human summary
    python -m forecasting.shrinkage_study --json     # full machine payload
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from forecasting.bayes_toolkit import platt_scale
from forecasting.models import LedgerNotFoundError

# ── Frozen study parameters (see docs/research/shrinkage-study.md §2–§4) ──────

#: Widened sweep floor: below 1.0 the Platt slope SHRINKS toward 0.5.
SHRINKAGE_ALPHA_MIN = 0.5
#: Sweep ceiling (unchanged from the extremization sweep).
SHRINKAGE_ALPHA_MAX = 2.5
#: Grid step; 1.0 lands exactly on the grid so ``identity_brier`` aligns to a node.
SHRINKAGE_ALPHA_STEP = 0.05
#: Mechanical evidence-thin threshold: ``len(evidence_refs) ≤ 1`` (the median agent
#: evidence-ref count on this ledger). Justified in the doc.
THIN_EVIDENCE_REF_MAX = 1
#: Minimum resolved-binary sample for a stratum to be decision-eligible (D4).
MIN_STRATUM_N = 50


def alpha_grid(
    min_alpha: float = SHRINKAGE_ALPHA_MIN,
    max_alpha: float = SHRINKAGE_ALPHA_MAX,
    step: float = SHRINKAGE_ALPHA_STEP,
) -> list[float]:
    """The α grid over ``[min_alpha, max_alpha]`` inclusive, rounded to 5 places.

    ``step`` divides the range so that 1.0 is a node when ``min_alpha`` and ``step``
    are commensurate (0.5 / 0.05 → 1.0 is the 10th node)."""

    n = int(round((max_alpha - min_alpha) / step)) + 1
    grid = [round(min_alpha + step * i, 5) for i in range(n)]
    return [a for a in grid if a > 0.0]


@dataclass(frozen=True)
class StudyObservation:
    """A single resolved-binary observation reduced for the sweep."""

    p_yes: float
    outcome: float  # 1.0 yes / 0.0 no
    evidence_ref_count: int
    domain: str | None


def gather_binary_observations(
    ledger,
    *,
    forecast_origin: str | None,
    calibration_eligible: bool | None = None,
) -> list[StudyObservation]:
    """Reduce one origin's scored binary forecasts to :class:`StudyObservation` rows.

    Respects the ``forecast_origin`` + ``calibration_eligible`` filters EXACTLY as the
    existing scoring code does (``list_scores`` — the same reader
    ``build_forecasting_evidence_status`` uses per-origin). Binary questions only; uses
    the RAW pre-adjustment probability when a lesson moved the committed number
    (contamination control). Never pools across origins — the caller passes one origin.
    """

    scores = ledger.list_scores(
        forecast_origin=forecast_origin,
        calibration_eligible=calibration_eligible,
    )
    observations: list[StudyObservation] = []
    for score in scores:
        if score.brier_score is None:
            continue
        try:
            question = ledger.get_question(score.question_id)
        except LedgerNotFoundError:
            continue
        if question.outcome_space.type != "binary":
            continue
        try:
            snapshot = ledger.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            continue
        adjustment = snapshot.calibration_adjustment or {}
        raw = adjustment.get("raw_probability")
        committed = snapshot.probability_or_distribution
        probability = (
            raw
            if isinstance(raw, (int, float)) and not isinstance(raw, bool)
            else committed
        )
        if not isinstance(probability, (int, float)) or isinstance(probability, bool):
            continue
        prob = float(probability)
        if not (0.0 <= prob <= 1.0):
            continue
        observed = ledger._binary_outcome_value(score, question.outcome_space)
        if observed is None:
            continue
        observations.append(
            StudyObservation(
                p_yes=prob,
                outcome=float(observed),
                evidence_ref_count=len(snapshot.evidence_refs or []),
                domain=score.domain or question.domain,
            )
        )
    return observations


# ── Sweep + LOO (O(n·grid), identical estimator to sweep_platt_alpha) ─────────


def _brier(p: float, outcome: float, alpha: float) -> float:
    return (platt_scale(p, alpha=alpha, d=1.0) - outcome) ** 2


def efficient_sweep(
    pairs: Sequence[tuple[float, float]],
    grid: Sequence[float],
) -> dict[str, Any]:
    """The same in-sample curve + leave-one-out estimator as
    :func:`forecasting.backtesting.sweep_platt_alpha`, computed in ``O(n·grid)`` via the
    incremental identity ``mean_brier(rest) ∝ S[a] − B[i][a]`` so it scales to n≈1,700.

    Returns ``curve`` (per-α mean Brier), ``best_alpha`` / ``best_brier`` (over the whole
    grid), ``identity_brier`` (α=1.0), ``best_alpha_below_1`` / ``best_brier_below_1``,
    and the honest out-of-sample ``loo_brier`` / ``loo_modal_alpha`` at a data-chosen α.
    """

    grid = [float(a) for a in grid if float(a) > 0.0]
    n = len(pairs)
    if n == 0 or not grid:
        return {
            "n": n,
            "curve": [],
            "best_alpha": None,
            "best_brier": None,
            "identity_brier": None,
            "best_alpha_below_1": None,
            "best_brier_below_1": None,
            "loo_brier": None,
            "loo_modal_alpha": None,
        }

    # B[i][j] = Brier of point i at grid[j]; S[j] = column sum over points.
    b_rows: list[list[float]] = []
    col_sums = [0.0] * len(grid)
    for p, outcome in pairs:
        row = [_brier(p, outcome, a) for a in grid]
        for j, val in enumerate(row):
            col_sums[j] += val
        b_rows.append(row)

    curve = [{"alpha": round(a, 5), "mean_brier": col_sums[j] / n} for j, a in enumerate(grid)]
    best_j = min(range(len(grid)), key=lambda j: col_sums[j])
    identity_brier = sum((p - outcome) ** 2 for p, outcome in pairs) / n

    below = [(j, a) for j, a in enumerate(grid) if a < 1.0]
    best_below_j = min((j for j, _ in below), key=lambda j: col_sums[j]) if below else None

    # Leave-one-out: for each held-out i, pick the grid α minimizing Brier on the REST
    # (= col_sum − B[i]) with a first-min tie-break, then score i with it out-of-sample.
    loo_brier: float | None = None
    loo_modal_alpha: float | None = None
    if n >= 3:
        picks: list[float] = []
        held: list[float] = []
        for i in range(n):
            row = b_rows[i]
            best = 0
            best_val = col_sums[0] - row[0]
            for j in range(1, len(grid)):
                val = col_sums[j] - row[j]
                if val < best_val:
                    best_val = val
                    best = j
            picks.append(round(grid[best], 5))
            held.append(row[best])
        loo_brier = sum(held) / n
        loo_modal_alpha = Counter(picks).most_common(1)[0][0]

    return {
        "n": n,
        "curve": curve,
        "best_alpha": round(grid[best_j], 5),
        "best_brier": col_sums[best_j] / n,
        "identity_brier": identity_brier,
        "best_alpha_below_1": round(grid[best_below_j], 5) if best_below_j is not None else None,
        "best_brier_below_1": (col_sums[best_below_j] / n) if best_below_j is not None else None,
        "loo_brier": loo_brier,
        "loo_modal_alpha": loo_modal_alpha,
    }


# ── Per-stratum evaluation + the pre-registered decision gates ────────────────


def evaluate_stratum(
    ledger,
    label: str,
    observations: Sequence[StudyObservation],
    *,
    grid: Sequence[float],
    min_stratum_n: int = MIN_STRATUM_N,
    activation_basis: bool = True,
) -> dict[str, Any]:
    """Sweep one stratum, run the paired bootstrap vs α=1.0, and apply gates D1–D4.

    ``activation_basis=False`` marks a diagnostic stratum (e.g. the pooled global row)
    whose gates are computed but which is excluded from the study-level trigger.
    """

    pairs = [(o.p_yes, o.outcome) for o in observations]
    n = len(pairs)
    sweep = efficient_sweep(pairs, grid)

    identity = sweep["identity_brier"]
    best_below_alpha = sweep["best_alpha_below_1"]
    best_below_brier = sweep["best_brier_below_1"]

    # Significance vs α=1.0 at the best α<1: reuse the seeded AIA-P0.2 paired bootstrap.
    # δ_i = brier_i(α=1) − brier_i(α<1); δ>0 ⇒ shrinkage better.
    paired: dict[str, Any] | None = None
    if best_below_alpha is not None and n >= 2:
        deltas = [
            (p - outcome) ** 2 - _brier(p, outcome, best_below_alpha)
            for p, outcome in pairs
        ]
        mean_delta = sum(deltas) / n
        boot = ledger._paired_bootstrap(deltas, mean_delta)
        paired = {
            "alpha": best_below_alpha,
            "mean_delta": mean_delta,
            "p_value": boot["p_value"],
            "ci_low": boot["ci_low"],
            "ci_high": boot["ci_high"],
        }

    # Decision gates (frozen; docs/research/shrinkage-study.md §4).
    d1 = (
        best_below_brier is not None
        and identity is not None
        and best_below_brier < identity
    )
    d2 = bool(
        paired
        and paired["mean_delta"] is not None
        and paired["mean_delta"] > 0
        and paired["p_value"] is not None
        and paired["p_value"] < 0.05
        and paired["ci_low"] is not None
        and paired["ci_low"] > 0
    )
    d3 = (
        sweep["loo_modal_alpha"] is not None
        and sweep["loo_modal_alpha"] < 1.0
        and sweep["loo_brier"] is not None
        and identity is not None
        and sweep["loo_brier"] <= identity
    )
    d4 = n >= min_stratum_n
    clears = bool(d1 and d2 and d3 and d4)

    return {
        "label": label,
        "n": n,
        "activation_basis": activation_basis,
        "identity_brier": identity,
        "best_alpha": sweep["best_alpha"],
        "best_brier": sweep["best_brier"],
        "best_alpha_below_1": best_below_alpha,
        "best_brier_below_1": best_below_brier,
        "loo_brier": sweep["loo_brier"],
        "loo_modal_alpha": sweep["loo_modal_alpha"],
        "paired_vs_identity": paired,
        "gates": {"D1": bool(d1), "D2": d2, "D3": bool(d3), "D4": bool(d4), "clears": clears},
        "curve": sweep["curve"],
    }


def run_shrinkage_study(
    ledger,
    *,
    grid: Sequence[float] | None = None,
    min_stratum_n: int = MIN_STRATUM_N,
    thin_ref_max: int = THIN_EVIDENCE_REF_MAX,
) -> dict[str, Any]:
    """Run every frozen stratum read-only and apply the pre-registered decision rule."""

    grid = list(grid) if grid is not None else alpha_grid()

    # Per-origin gathers (never pooled for the decision).
    live_obs = gather_binary_observations(
        ledger, forecast_origin="live", calibration_eligible=True
    )
    backtest_obs = gather_binary_observations(
        ledger, forecast_origin="backtest", calibration_eligible=None
    )
    imported_obs = gather_binary_observations(
        ledger, forecast_origin="imported_baseline", calibration_eligible=None
    )

    agent_obs = list(backtest_obs) + list(live_obs)
    thin_obs = [o for o in agent_obs if o.evidence_ref_count <= thin_ref_max]
    rich_obs = [o for o in agent_obs if o.evidence_ref_count >= thin_ref_max + 1]

    strata: list[dict[str, Any]] = []

    def _add(label, obs, *, basis=True):
        strata.append(
            evaluate_stratum(
                ledger, label, obs, grid=grid, min_stratum_n=min_stratum_n, activation_basis=basis
            )
        )

    _add("live", live_obs)
    _add("backtest", backtest_obs)
    _add("evidence_thin", thin_obs)
    _add("evidence_rich", rich_obs)
    _add("imported_baseline", imported_obs)

    # Optional domain resolution inside the powered backtest stratum (n ≥ 50 only).
    by_domain: dict[str, list[StudyObservation]] = {}
    for o in backtest_obs:
        by_domain.setdefault(o.domain or "unknown", []).append(o)
    skipped_domains: list[dict[str, Any]] = []
    for domain, obs in sorted(by_domain.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(obs) >= min_stratum_n:
            _add(f"backtest:domain={domain}", obs)
        else:
            skipped_domains.append({"domain": domain, "n": len(obs)})

    # Diagnostic-only pooled global row (NOT an activation basis).
    _add("global_agent_pooled", agent_obs, basis=False)

    # ── Study-level decision (frozen rule) ──────────────────────────────────
    clearing = [s["label"] for s in strata if s["activation_basis"] and s["gates"]["clears"]]
    live_row = next((s for s in strata if s["label"] == "live"), None)
    live_clears = bool(live_row and live_row["gates"]["clears"])

    if not clearing:
        verdict = "null_shrinkage_hypothesis_failed_on_this_ledger"
        recommendation = "change_nothing_live"
    elif live_clears:
        verdict = "live_stratum_clears"
        recommendation = "wire_trigger_ship_off_recommend_live_activation"
    else:
        verdict = "backtest_only_clears_hypothesis_generating"
        recommendation = "wire_trigger_ship_off_gather_live_binary_evidence"

    return {
        "study": "shrinkage",
        "ledger_path": str(getattr(ledger, "db_path", "")),
        "grid": {
            "min_alpha": grid[0],
            "max_alpha": grid[-1],
            "step": SHRINKAGE_ALPHA_STEP,
            "n_alphas": len(grid),
        },
        "thresholds": {"thin_evidence_ref_max": thin_ref_max, "min_stratum_n": min_stratum_n},
        "strata": strata,
        "skipped_domains": skipped_domains,
        "decision": {
            "clearing_strata": clearing,
            "live_clears": live_clears,
            "verdict": verdict,
            "recommendation": recommendation,
            "activation_surface": "alpha_extremize (forecasting/panel.py, forecasting/quorum.py)",
            "shipped": "OFF",
        },
    }


# ── Human-readable summary + CLI-less entry point ─────────────────────────────


def _fmt(value: Any, places: int = 4) -> str:
    if value is None:
        return "  n/a "
    if isinstance(value, float):
        if math.isnan(value):
            return "  nan "
        return f"{value:.{places}f}"
    return str(value)


def format_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    grid = report["grid"]
    lines.append("The Shrinkage Study — α<1 terminal Platt on the resolved binary set (READ-ONLY)")
    lines.append(f"ledger: {report['ledger_path']}")
    lines.append(
        f"grid: α ∈ [{grid['min_alpha']}, {grid['max_alpha']}] step {grid['step']} "
        f"({grid['n_alphas']} nodes) · thin ≤ {report['thresholds']['thin_evidence_ref_max']} refs "
        f"· min-n {report['thresholds']['min_stratum_n']}"
    )
    header = (
        f"{'stratum':<28} {'n':>5} {'identity':>9} {'best_a':>7} {'best_a<1':>9} "
        f"{'B(a<1)':>8} {'Δmean':>9} {'p':>8} {'loo_a':>6} {'clears':>7}"
    )
    lines.append("")
    lines.append(header)
    lines.append("-" * len(header))
    for s in report["strata"]:
        paired = s["paired_vs_identity"] or {}
        clears = "YES" if s["gates"]["clears"] else ("diag" if not s["activation_basis"] else "no")
        lines.append(
            f"{s['label']:<28} {s['n']:>5} {_fmt(s['identity_brier']):>9} "
            f"{_fmt(s['best_alpha'],2):>7} {_fmt(s['best_alpha_below_1'],2):>9} "
            f"{_fmt(s['best_brier_below_1']):>8} {_fmt(paired.get('mean_delta'),5):>9} "
            f"{_fmt(paired.get('p_value'),4):>8} {_fmt(s['loo_modal_alpha'],2):>6} {clears:>7}"
        )
    if report["skipped_domains"]:
        skipped = ", ".join(f"{d['domain']}({d['n']})" for d in report["skipped_domains"])
        lines.append("")
        lines.append(f"domains skipped (n<{report['thresholds']['min_stratum_n']}): {skipped}")
    d = report["decision"]
    lines.append("")
    lines.append(f"clearing strata (activation basis): {d['clearing_strata'] or 'NONE'}")
    lines.append(f"live stratum clears: {d['live_clears']}")
    lines.append(f"verdict: {d['verdict']}")
    lines.append(f"recommendation: {d['recommendation']} · shipped: {d['shipped']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json

    from forecasting.ledger import ForecastLedger

    parser = argparse.ArgumentParser(
        prog="python -m forecasting.shrinkage_study",
        description="READ-ONLY α<1 terminal-Platt shrinkage study on the forecast ledger.",
    )
    parser.add_argument("--db", default=None, help="ledger path (else FORECAST_LEDGER_DB / default)")
    parser.add_argument("--json", action="store_true", help="emit the full machine payload")
    args = parser.parse_args(argv)

    ledger = ForecastLedger(args.db)
    report = run_shrinkage_study(ledger)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(format_summary(report))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
