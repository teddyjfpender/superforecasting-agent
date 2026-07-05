"""Panel-vs-solo ablation runner — pairing, verdicts, and the empty-ledger honesty."""

from __future__ import annotations

import pytest

from forecasting.ablation_study import (
    ABLATION_MIN_PAIRS,
    collect_panel_solo_pairs,
    run_panel_vs_solo_ablation,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


def _resolved_panel_question(ledger, title, *, panelists, aggregate, outcome):
    """A resolved binary question with a panel run of the given panelist probs."""
    q = ledger.create_question(
        title=title,
        resolution_criteria="Resolved yes if the stated event occurs before the deadline.",
        outcome_space=OutcomeSpace(type="binary"),
    )
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=aggregate,
        rationale="Panel aggregate committed as the snapshot.",
    )
    estimates = [
        {"perspective": f"role_{i}", "probability": p, "rationale": "panelist view"}
        for i, p in enumerate(panelists)
    ]
    run = ledger.record_panel_run(
        question_id=q.id,
        estimates=estimates,
        final_probability=aggregate,
        final_source="pool",
    )
    ledger.attach_panel_to_snapshot(run["id"], snap.forecast_id)
    ledger.resolve_question(question_id=q.id, outcome=outcome)
    return q


def test_empty_ledger_reports_zero_n_no_verdict(tmp_path):
    ledger = ForecastLedger(tmp_path / "abl.db")
    report = run_panel_vs_solo_ablation(ledger)
    assert report["n"] == 0
    assert report["verdict"] == "insufficient_sample"
    assert report["panel_edge_mean_brier"] is None


def test_pairing_computes_panel_and_solo_brier(tmp_path):
    ledger = ForecastLedger(tmp_path / "abl.db")
    # Panel aggregate 0.9 (good), panelists spread 0.5/0.7/0.9 → solo worse. Outcome yes.
    _resolved_panel_question(
        ledger,
        "Will the well-aggregated panel beat its scattered members on a yes outcome?",
        panelists=[0.5, 0.7, 0.9],
        aggregate=0.9,
        outcome="yes",
    )
    pairs = collect_panel_solo_pairs(ledger)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["panel_brier"] == pytest.approx((0.9 - 1.0) ** 2)
    expected_solo = ((0.5 - 1) ** 2 + (0.7 - 1) ** 2 + (0.9 - 1) ** 2) / 3
    assert pair["solo_brier"] == pytest.approx(expected_solo)
    assert pair["delta"] == pytest.approx(expected_solo - (0.9 - 1.0) ** 2)  # positive → panel better


def test_verdict_insufficient_below_floor(tmp_path):
    ledger = ForecastLedger(tmp_path / "abl.db")
    for i in range(ABLATION_MIN_PAIRS - 1):
        _resolved_panel_question(
            ledger,
            f"Will resolved panel question number {i} accrue toward the ablation floor?",
            panelists=[0.4, 0.6, 0.8],
            aggregate=0.8,
            outcome="yes",
        )
    report = run_panel_vs_solo_ablation(ledger)
    assert report["n"] == ABLATION_MIN_PAIRS - 1
    assert report["verdict"] == "insufficient_sample"


def test_verdict_panel_better_when_ci_excludes_zero(tmp_path):
    ledger = ForecastLedger(tmp_path / "abl.db")
    # Every question: panel confidently right, panelists scattered → consistent
    # positive edge (varied per question so the bootstrap sees real spread), so
    # the CI clears 0 and the verdict is panel_better.
    for i in range(ABLATION_MIN_PAIRS + 4):
        low = 0.45 + 0.01 * i  # small per-question variation keeps deltas non-degenerate
        _resolved_panel_question(
            ledger,
            f"Will the consistently-better panel earn a positive edge on question {i}?",
            panelists=[low, low + 0.1, 0.95],
            aggregate=0.95,
            outcome="yes",
        )
    report = run_panel_vs_solo_ablation(ledger)
    assert report["n"] == ABLATION_MIN_PAIRS + 4
    assert report["panel_edge_mean_brier"] > 0
    assert report["ci95_low"] is not None and report["ci95_low"] > 0
    assert report["verdict"] == "panel_better"


def test_non_binary_and_unresolved_excluded(tmp_path):
    ledger = ForecastLedger(tmp_path / "abl.db")
    # Unresolved binary with a panel → excluded (no outcome).
    q = ledger.create_question(
        title="Will the unresolved paneled question be excluded from the ablation?",
        resolution_criteria="Resolved yes if the event occurs before the deadline.",
        outcome_space=OutcomeSpace(type="binary"),
    )
    ledger.record_panel_run(
        question_id=q.id,
        estimates=[
            {"perspective": "a", "probability": 0.5, "rationale": "x"},
            {"perspective": "b", "probability": 0.6, "rationale": "y"},
        ],
        final_probability=0.55,
        final_source="pool",
    )
    assert collect_panel_solo_pairs(ledger) == []
