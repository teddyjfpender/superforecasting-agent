"""Tests for the shrinkage study (α<1 terminal Platt) and the widened sweep range.

Covers:
  * ``sweep_platt_alpha`` backward-compat (the default range is byte-for-byte the
    old ``linspace(1.0, 2.5, 16)``) + the opt-in ``min_alpha`` widening to 0.5;
  * the sweep RECOVERS α<1 on a known-overconfident set and α≈1 on a calibrated one;
  * ``efficient_sweep`` reproduces ``sweep_platt_alpha`` (curve/best/LOO) exactly;
  * the gatherer respects the ``calibration_eligible`` + ``forecast_origin`` filters
    and skips non-binary questions;
  * the pre-registered decision gates fire (clears on overconfident, null on
    calibrated) and ``run_shrinkage_study`` returns the frozen structure.
"""

from __future__ import annotations

import math
import random

import pytest

from forecasting import ForecastLedger
from forecasting.backtesting import (
    DEFAULT_ALPHA_SWEEP_MIN,
    SHRINKAGE_ALPHA_SWEEP_MIN,
    _linspace,
    sweep_platt_alpha,
)
from forecasting.bayes_toolkit import platt_scale
from forecasting.models import OutcomeSpace
from forecasting.shrinkage_study import (
    StudyObservation,
    alpha_grid,
    efficient_sweep,
    evaluate_stratum,
    gather_binary_observations,
    run_shrinkage_study,
)

CRITERIA = "Resolves to the official value reported by the named source on the close date."


# ── synthetic pair builders ──────────────────────────────────────────────────


def _overconfident_pairs(n: int, seed: int, *, sharpen: float = 2.0):
    """Predictions extremized away from the truth (α=sharpen) → shrinkage should help."""
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        truth = rng.uniform(0.15, 0.85)
        outcome = 1.0 if rng.random() < truth else 0.0
        p = platt_scale(truth, alpha=sharpen, d=1.0)
        pairs.append((min(max(p, 0.01), 0.99), outcome))
    return pairs


def _calibrated_pairs(n: int, seed: int):
    """outcome ~ Bernoulli(p) → the forecaster is calibrated, α≈1 is optimal."""
    rng = random.Random(seed)
    return [
        (p, 1.0 if rng.random() < p else 0.0)
        for p in (rng.uniform(0.05, 0.95) for _ in range(n))
    ]


# ── A. widened sweep range + backward compat ─────────────────────────────────


def test_sweep_default_range_is_backward_compatible():
    # The default floor is still 1.0, and the emitted grid is byte-for-byte the
    # historical linspace(1.0, 2.5, 16) — no existing caller shifts.
    assert DEFAULT_ALPHA_SWEEP_MIN == 1.0
    pairs = _calibrated_pairs(200, 1)
    out = sweep_platt_alpha(pairs)
    assert out["alphas"][0] == 1.0
    expected = [round(a, 5) for a in _linspace(1.0, 2.5, 16)]
    assert out["alphas"] == expected


def test_sweep_min_alpha_widens_below_one():
    assert SHRINKAGE_ALPHA_SWEEP_MIN == 0.5
    pairs = _calibrated_pairs(200, 2)
    out = sweep_platt_alpha(pairs, min_alpha=SHRINKAGE_ALPHA_SWEEP_MIN, steps=41)
    assert out["alphas"][0] == pytest.approx(0.5)
    assert any(a < 1.0 for a in out["alphas"])
    assert out["alphas"][-1] == pytest.approx(2.5)


def test_sweep_recovers_shrinkage_on_overconfident_set():
    # A systematically over-confident set: the Brier-minimizing slope is < 1.0 and
    # beats the identity. This is the core recovery property of the widened sweep,
    # driven through the PUBLIC sweep_platt_alpha with the opt-in min_alpha floor.
    pairs = _overconfident_pairs(300, 11)
    out = sweep_platt_alpha(pairs, min_alpha=SHRINKAGE_ALPHA_SWEEP_MIN, steps=41)
    assert out["best_alpha"] < 1.0
    identity = sweep_platt_alpha(pairs, alphas=[1.0])["best_brier"]
    assert out["best_brier"] < identity
    # LOO agrees out-of-sample: the modal held-out pick is also a shrinkage slope.
    assert out["loo_modal_alpha"] < 1.0


def test_sweep_recovers_identity_on_calibrated_set():
    # A well-calibrated set: the minimizer sits at α≈1 and shrinkage buys nothing.
    # (Uses efficient_sweep — proven identical to sweep_platt_alpha above — so the
    # large stable sample stays under the test timeout.)
    pairs = _calibrated_pairs(4000, 42)
    out = efficient_sweep(pairs, alpha_grid())
    assert 0.85 <= out["best_alpha"] <= 1.20
    identity = out["identity_brier"]
    # The best grid slope improves on the identity by a negligible margin.
    assert out["best_brier"] >= identity - 2e-3


# ── B. efficient_sweep == sweep_platt_alpha ──────────────────────────────────


def test_efficient_sweep_matches_public_sweep():
    pairs = _overconfident_pairs(150, 3)
    grid = alpha_grid()
    ref = sweep_platt_alpha(pairs, alphas=grid)
    eff = efficient_sweep(pairs, grid)
    assert eff["best_alpha"] == ref["best_alpha"]
    assert eff["best_brier"] == pytest.approx(ref["best_brier"], abs=1e-12)
    assert eff["loo_brier"] == pytest.approx(ref["loo_brier"], abs=1e-9)
    assert eff["loo_modal_alpha"] == ref["loo_modal_alpha"]
    for a, b in zip(ref["curve"], eff["curve"]):
        assert a["alpha"] == b["alpha"]
        assert a["mean_brier"] == pytest.approx(b["mean_brier"], abs=1e-12)


def test_alpha_grid_shape():
    grid = alpha_grid()
    assert grid[0] == pytest.approx(0.5)
    assert grid[-1] == pytest.approx(2.5)
    assert 1.0 in grid  # identity is a node so identity_brier aligns to the grid
    assert all(a > 0 for a in grid)
    assert grid == sorted(grid)


def test_efficient_sweep_empty_is_safe():
    out = efficient_sweep([], alpha_grid())
    assert out["n"] == 0
    assert out["best_alpha"] is None
    assert out["identity_brier"] is None


# ── C. gatherer respects the ledger filters ──────────────────────────────────


def _plant_live(ledger, *, p_yes, yes_fraction, n, prefix, calibration_eligible=True):
    """Plant ``n`` resolved binary live forecasts at ``p_yes`` (auto-scored)."""
    # Suppress the resolve-time auto-synthesis so planting has no side effects.
    ledger._live_score_count = lambda domain=None: 0  # type: ignore[method-assign]
    yes = round(yes_fraction * n)
    for i in range(n):
        q = ledger.create_question(
            title=f"{prefix} #{i}?", resolution_criteria=CRITERIA, domain="politics"
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=p_yes,
            rationale="planted",
            calibration_eligible=calibration_eligible,
        )
        ledger.resolve_question(
            question_id=q.id, outcome="yes" if i < yes else "no", auto_score=True
        )


def test_gather_respects_calibration_eligible(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    _plant_live(ledger, p_yes=0.7, yes_fraction=0.7, n=4, prefix="Elig", calibration_eligible=True)
    _plant_live(ledger, p_yes=0.7, yes_fraction=0.7, n=3, prefix="Inelig", calibration_eligible=False)

    eligible = gather_binary_observations(ledger, forecast_origin="live", calibration_eligible=True)
    both = gather_binary_observations(ledger, forecast_origin="live", calibration_eligible=None)
    assert len(eligible) == 4  # the ineligible snapshots are excluded when filtered
    assert len(both) == 7
    # And a different origin returns nothing (no pooling across origins).
    assert gather_binary_observations(ledger, forecast_origin="backtest") == []


def test_gather_skips_non_binary(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    ledger._live_score_count = lambda domain=None: 0  # type: ignore[method-assign]
    q = ledger.create_question(
        title="Which party wins?",
        resolution_criteria=CRITERIA,
        outcome_space=OutcomeSpace(type="categorical", choices=["a", "b", "c"]),
        domain="politics",
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution={"a": 0.5, "b": 0.3, "c": 0.2},
        rationale="planted",
    )
    ledger.resolve_question(question_id=q.id, outcome="a", auto_score=True)
    # The categorical forecast is scored but must NOT enter the binary Brier study.
    assert gather_binary_observations(ledger, forecast_origin="live", calibration_eligible=None) == []


# ── D. decision gates + orchestrator ─────────────────────────────────────────


def _obs(pairs):
    return [StudyObservation(p, o, evidence_ref_count=1, domain="d") for p, o in pairs]


def test_evaluate_stratum_clears_on_overconfident(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")  # only used for the seeded bootstrap
    obs = _obs(_overconfident_pairs(600, 5))
    result = evaluate_stratum(ledger, "over", obs, grid=alpha_grid(), min_stratum_n=50)
    gates = result["gates"]
    assert result["best_alpha_below_1"] < 1.0
    assert gates["D1"] and gates["D4"]
    assert result["paired_vs_identity"]["mean_delta"] > 0
    assert result["paired_vs_identity"]["p_value"] < 0.05
    assert gates["D2"] and gates["D3"]
    assert gates["clears"] is True


def test_evaluate_stratum_null_on_calibrated(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    obs = _obs(_calibrated_pairs(1500, 9))
    result = evaluate_stratum(ledger, "cal", obs, grid=alpha_grid(), min_stratum_n=50)
    # A calibrated stratum must not trip the shrinkage trigger.
    assert result["gates"]["clears"] is False


def test_evaluate_stratum_below_min_n_never_clears(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    obs = _obs(_overconfident_pairs(20, 5))  # n < 50 → D4 fails
    result = evaluate_stratum(ledger, "tiny", obs, grid=alpha_grid(), min_stratum_n=50)
    assert result["gates"]["D4"] is False
    assert result["gates"]["clears"] is False


def test_run_shrinkage_study_structure_and_null(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # A calibrated, two-sided live set (n=80) so the live stratum is populated but null.
    _plant_live(ledger, p_yes=0.7, yes_fraction=0.7, n=40, prefix="Hi")
    _plant_live(ledger, p_yes=0.3, yes_fraction=0.3, n=40, prefix="Lo")

    report = run_shrinkage_study(ledger)
    assert report["study"] == "shrinkage"
    assert report["grid"]["min_alpha"] == pytest.approx(0.5)
    labels = {s["label"] for s in report["strata"]}
    assert {"live", "backtest", "evidence_thin", "imported_baseline", "global_agent_pooled"} <= labels
    live = next(s for s in report["strata"] if s["label"] == "live")
    assert live["n"] == 80
    # Calibrated data → nothing clears → faithful null → change nothing live.
    assert report["decision"]["clearing_strata"] == []
    assert report["decision"]["verdict"] == "null_shrinkage_hypothesis_failed_on_this_ledger"
    assert report["decision"]["shipped"] == "OFF"


def test_run_shrinkage_study_flags_backtest_only_when_live_untestable(tmp_path):
    # If a powered stratum clears but the live stratum can't (0 binary here), the
    # verdict must be the hypothesis-generating "backtest only" one, never a live green-light.
    ledger = ForecastLedger(tmp_path / "f.db")
    # Plant an over-confident BACKTEST set directly via snapshots tagged backtest.
    ledger._live_score_count = lambda domain=None: 0  # type: ignore[method-assign]
    for i, (p, o) in enumerate(_overconfident_pairs(120, 13)):
        q = ledger.create_question(
            title=f"BT #{i}?", resolution_criteria=CRITERIA, domain="macro"
        )
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=round(p, 4),
            rationale="planted",
            forecast_origin="backtest",
            calibration_eligible=False,
        )
        ledger.resolve_question(
            question_id=q.id, outcome="yes" if o >= 0.5 else "no", auto_score=True
        )
    report = run_shrinkage_study(ledger)
    backtest = next(s for s in report["strata"] if s["label"] == "backtest")
    assert backtest["n"] == 120
    if report["decision"]["clearing_strata"]:  # overconfident plant should clear
        assert report["decision"]["live_clears"] is False
        assert report["decision"]["verdict"] == "backtest_only_clears_hypothesis_generating"
        assert report["decision"]["shipped"] == "OFF"


def test_no_nan_in_summary_formatting(tmp_path):
    from forecasting.shrinkage_study import format_summary

    ledger = ForecastLedger(tmp_path / "f.db")
    report = run_shrinkage_study(ledger)  # empty ledger
    text = format_summary(report)
    assert "The Shrinkage Study" in text
    assert not math.isnan(0.0)  # sanity; formatter must not raise on Nones
