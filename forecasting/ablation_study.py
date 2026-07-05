"""Panel-vs-solo ablation — does the panel machinery earn its cost?

The desk spends real compute on 5-role panels + judge synthesis (soon Delphi)
on the *belief* they beat a lone forecaster, with zero measured confirmation on
this ledger (``quorum-and-panels.md:43`` names the mean as "the floor any
pool/judge must beat" — never shown beaten here). This runner settles it on the
real book: over resolved, Brier-scoreable questions that carry a panel, it pairs

    panel_brier — the panel's committed/aggregate probability vs the outcome
    solo_brier  — the EXPECTED single-panelist Brier (mean over panelists of
                  each individual's Brier vs the outcome)

so the contrast is the classic wisdom-of-crowds one: does pooling + judging beat
a typical lone panelist? The per-question edge (``solo − panel``, POSITIVE =
panel better) is tested with the SAME seeded recenter-at-zero paired bootstrap
the AIA edge test uses (P0.2, B=10k), so the p-value + CI reproduce byte-for-byte.

Honesty first: ``n`` is reported plainly and the verdict is ``insufficient_sample``
until a floor accrues — a tiny or empty ``n`` is a finding, not something to
paper over. Read-only; safe to run on the live ledger. A weekly cron can call
:func:`run_panel_vs_solo_ablation` and persist/surface the verdict.
"""

from __future__ import annotations

from typing import Any

# Below this many paired observations the bootstrap cannot say anything
# trustworthy — we report the honest n and withhold a verdict.
ABLATION_MIN_PAIRS = 8

# Brier-scoreable outcome types (the panel aggregate is a single probability, so
# the pairing is only proper for a yes/no-mappable resolution).
_SCOREABLE_TYPES = {"binary", "categorical"}


def _numeric_probability(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    p = float(value)
    return p if 0.0 <= p <= 1.0 else None


def _panel_final_probability(ledger, run: dict[str, Any]) -> float | None:
    """The panel's headline probability: the attached snapshot's committed
    number when present + numeric, else the persisted aggregate."""
    snapshot_id = run.get("snapshot_id")
    if snapshot_id:
        try:
            snapshot = ledger.get_snapshot(snapshot_id)
        except Exception:  # noqa: BLE001 — a detached/missing snapshot falls back
            snapshot = None
        if snapshot is not None:
            committed = _numeric_probability(snapshot.probability_or_distribution)
            if committed is not None:
                return committed
    return _numeric_probability(run.get("aggregate_probability"))


def _panel_solo_pair(ledger, run: dict[str, Any], observed: float) -> tuple[float, float] | None:
    """(panel_brier, solo_brier) for one panel run against a 1.0/0.0 outcome, or
    None when either side is not computable. solo_brier is the MEAN individual
    panelist Brier — the expected lone-forecaster score."""
    panel_p = _panel_final_probability(ledger, run)
    if panel_p is None:
        return None
    panelist_briers: list[float] = []
    for estimate in run.get("estimates", []) or []:
        p = _numeric_probability(estimate.get("probability"))
        if p is not None:
            panelist_briers.append((p - observed) ** 2)
    if not panelist_briers:
        return None
    panel_brier = (panel_p - observed) ** 2
    solo_brier = sum(panelist_briers) / len(panelist_briers)
    return panel_brier, solo_brier


def collect_panel_solo_pairs(ledger) -> list[dict[str, Any]]:
    """One (panel_brier, solo_brier) row per resolved, Brier-scoreable question
    that carries a panel with panelist estimates. Read-only. The latest panel run
    on the question supplies the pair."""
    pairs: list[dict[str, Any]] = []
    for question in ledger.list_questions():
        if question.outcome_space.type not in _SCOREABLE_TYPES:
            continue
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            continue
        observed = ledger._operator_binary_observed(resolution.outcome, question.outcome_space)
        if observed is None:
            continue
        runs = ledger.list_panel_runs(question.id, limit=1)
        if not runs:
            continue
        result = _panel_solo_pair(ledger, runs[0], observed)
        if result is None:
            continue
        panel_brier, solo_brier = result
        pairs.append(
            {
                "question_id": question.id,
                "panel_brier": panel_brier,
                "solo_brier": solo_brier,
                "delta": solo_brier - panel_brier,  # POSITIVE = panel better
                "panelist_count": len(runs[0].get("estimates", []) or []),
            }
        )
    return pairs


def run_panel_vs_solo_ablation(ledger) -> dict[str, Any]:
    """Paired panel-vs-solo Brier verdict over the resolved book.

    Returns ``{n, panel_mean_brier, solo_mean_brier, panel_edge_mean_brier,
    ci95, p_value, verdict, pairs}``. ``verdict``:

    * ``insufficient_sample`` — n < :data:`ABLATION_MIN_PAIRS` (report n, no claim);
    * ``panel_better`` / ``solo_better`` — the 95% CI excludes 0 on that side;
    * ``inconclusive`` — enough n but the CI straddles 0.
    """
    pairs = collect_panel_solo_pairs(ledger)
    deltas = [pair["delta"] for pair in pairs]
    n = len(deltas)
    panel_mean = ledger._mean([pair["panel_brier"] for pair in pairs])
    solo_mean = ledger._mean([pair["solo_brier"] for pair in pairs])
    edge = ledger._mean(deltas)
    bootstrap = ledger._paired_bootstrap(deltas, edge)
    ci_low, ci_high = bootstrap["ci_low"], bootstrap["ci_high"]

    if n < ABLATION_MIN_PAIRS:
        verdict = "insufficient_sample"
    elif ci_low is not None and ci_low > 0:
        verdict = "panel_better"
    elif ci_high is not None and ci_high < 0:
        verdict = "solo_better"
    else:
        verdict = "inconclusive"

    return {
        "n": n,
        "min_pairs": ABLATION_MIN_PAIRS,
        "panel_mean_brier": panel_mean,
        "solo_mean_brier": solo_mean,
        "panel_edge_mean_brier": edge,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "p_value": bootstrap["p_value"],
        "verdict": verdict,
        "pairs": pairs,
    }


def format_ablation_line(report: dict[str, Any]) -> str:
    """One-line doctor summary of the ablation verdict."""
    n = report.get("n", 0)
    if not n:
        return "panel_vs_solo: n=0 resolved Brier-scoreable panels — no verdict (need panels on resolved binaries)"
    edge = report.get("panel_edge_mean_brier")
    edge_txt = f"{edge:+.4f}" if isinstance(edge, (int, float)) else "-"
    panel = report.get("panel_mean_brier")
    solo = report.get("solo_mean_brier")
    panel_txt = f"{panel:.4f}" if isinstance(panel, (int, float)) else "-"
    solo_txt = f"{solo:.4f}" if isinstance(solo, (int, float)) else "-"
    return (
        f"panel_vs_solo: n={n}; panel Brier {panel_txt} vs solo {solo_txt}; "
        f"edge {edge_txt} (p={report.get('p_value')}); verdict {report.get('verdict')}"
    )
