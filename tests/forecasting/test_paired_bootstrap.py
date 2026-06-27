"""AIA P0.2 — seeded paired bootstrap significance + win-rate-vs-best.

These exercise the pure-function statistics on `ForecastLedger` directly (no DB):
a recenter-at-zero paired bootstrap for the two-sided p-value, an uncentered
percentile CI, and the full-baseline win-rate. The point estimate (mean paired
Brier edge) must be byte-identical to the prior parametric implementation.
"""

from __future__ import annotations

import statistics

import pytest

from forecasting.ledger import (
    BRIER_COIN_FLIP_FLOOR,
    PAIRED_BOOTSTRAP_DRAWS,
    PAIRED_BOOTSTRAP_SEED,
    ForecastLedger,
)


def _bootstrap(deltas):
    """Run the seeded paired bootstrap on raw deltas without touching a DB."""

    ledger = ForecastLedger.__new__(ForecastLedger)
    mean_delta = statistics.fmean(deltas) if deltas else None
    return ledger, mean_delta, ledger._paired_bootstrap(deltas, mean_delta)


def test_module_constants_documented():
    # Seed + B are fixed module constants so reviewers can audit determinism.
    assert PAIRED_BOOTSTRAP_SEED == 0xA1A02
    assert PAIRED_BOOTSTRAP_DRAWS == 10000
    assert BRIER_COIN_FLIP_FLOOR == 0.25


def test_determinism_two_calls_identical():
    deltas = [0.04, -0.01, 0.10, 0.02, 0.07, -0.03, 0.09, 0.01]
    _, _, first = _bootstrap(deltas)
    _, _, second = _bootstrap(deltas)
    assert first == second
    # Re-running with a fresh ledger object is also identical (seed, not state).
    _, _, third = _bootstrap(deltas)
    assert first == third


def test_clearly_better_agent_is_significant():
    # A consistently positive edge (agent beats baseline on every question).
    deltas = [0.08, 0.11, 0.09, 0.12, 0.10, 0.07, 0.13, 0.09, 0.11, 0.08]
    _, mean_delta, result = _bootstrap(deltas)
    assert mean_delta > 0
    assert result["p_value"] is not None and result["p_value"] < 0.05
    # 95% CI excludes the no-difference point (0).
    assert result["ci_low"] is not None and result["ci_low"] > 0
    assert result["ci_high"] is not None and result["ci_high"] > result["ci_low"]


def test_identical_agent_and_baseline_is_not_significant():
    # agent == baseline on every question => all deltas zero (degenerate spread).
    _, mean_delta, result = _bootstrap([0.0, 0.0, 0.0, 0.0, 0.0])
    assert mean_delta == 0.0
    # All-equal-deltas degenerate case: no signal => p/ci undefined.
    assert result["p_value"] is None
    assert result["ci_low"] is None and result["ci_high"] is None


def test_noisy_zero_edge_is_not_significant_and_ci_spans_zero():
    # Symmetric noise around a ~zero mean edge: p near 1.0, CI brackets 0.
    deltas = [0.05, -0.05, 0.04, -0.04, 0.06, -0.06, 0.03, -0.03]
    _, mean_delta, result = _bootstrap(deltas)
    assert mean_delta == pytest.approx(0.0, abs=1e-9)
    assert result["p_value"] is not None and result["p_value"] > 0.9
    assert result["ci_low"] is not None and result["ci_low"] < 0
    assert result["ci_high"] is not None and result["ci_high"] > 0


def test_small_n_guard():
    ledger = ForecastLedger.__new__(ForecastLedger)
    # n == 0 and n == 1 both guard to all-None.
    assert ledger._paired_bootstrap([], None) == {
        "p_value": None,
        "ci_low": None,
        "ci_high": None,
    }
    assert ledger._paired_bootstrap([0.05], 0.05) == {
        "p_value": None,
        "ci_low": None,
        "ci_high": None,
    }


def test_point_estimate_unchanged_from_prior_parametric_impl():
    # The mean paired edge is the point estimate; the bootstrap must not move it.
    deltas = [0.07, 0.12]
    ledger = ForecastLedger.__new__(ForecastLedger)
    mean_delta = ledger._mean(deltas)
    assert mean_delta == pytest.approx(0.095)
    result = ledger._paired_bootstrap(deltas, mean_delta)
    # CI brackets the point estimate (within the empirical resample range).
    assert result["ci_low"] <= mean_delta <= result["ci_high"]


def test_win_rate_vs_best_three_baselines():
    ledger = ForecastLedger.__new__(ForecastLedger)
    # Three baselines per question; agent wins only when its Brier <= ALL of them.
    question_pairs = {
        # agent 0.10 beats every baseline (0.20, 0.30, 0.15) -> win.
        "q1": [(0.10, 0.20), (0.10, 0.30), (0.10, 0.15)],
        # agent 0.25 ties the best (0.25) but loses to 0.20 -> not a win.
        "q2": [(0.25, 0.20), (0.25, 0.40), (0.25, 0.25)],
        # agent equals every baseline exactly -> win (<= is inclusive).
        "q3": [(0.18, 0.18), (0.18, 0.22), (0.18, 0.30)],
        # one baseline missing a Brier; the comparable ones still decide the win.
        "q4": [(0.05, 0.10), (0.05, None), (0.05, 0.12)],
    }
    result = ledger._win_rate_vs_best(question_pairs)
    assert result["win_rate_vs_best_n"] == 4
    assert result["win_rate_vs_best_wins"] == 3
    assert result["win_rate_vs_best"] == pytest.approx(0.75)


def test_win_rate_vs_best_counts_each_forecast_separately():
    # Two forecasts of the SAME logical question (distinct agent SCORE ids) must be
    # counted as two rows, never merged — the per-forecast keying fix that stops a
    # question recurring across rolling cutoffs from collapsing to one mispaired row.
    ledger = ForecastLedger.__new__(ForecastLedger)
    score_pairs = {
        "score_a": [(0.10, 0.20), (0.10, 0.30)],  # strong forecast -> win
        "score_b": [(0.40, 0.20), (0.40, 0.30)],  # weak forecast of same q -> loss
    }
    result = ledger._win_rate_vs_best(score_pairs)
    assert result["win_rate_vs_best_n"] == 2
    assert result["win_rate_vs_best_wins"] == 1
    assert result["win_rate_vs_best"] == pytest.approx(0.5)


def test_win_rate_vs_best_excludes_incomparable_questions():
    ledger = ForecastLedger.__new__(ForecastLedger)
    # A question where the agent's own Brier is missing is excluded entirely.
    question_pairs = {
        "q1": [(None, 0.20)],
        "q2": [(0.10, 0.30)],
    }
    result = ledger._win_rate_vs_best(question_pairs)
    assert result["win_rate_vs_best_n"] == 1
    assert result["win_rate_vs_best_wins"] == 1
    assert result["win_rate_vs_best"] == pytest.approx(1.0)


def test_win_rate_vs_best_empty():
    ledger = ForecastLedger.__new__(ForecastLedger)
    result = ledger._win_rate_vs_best({})
    assert result == {
        "win_rate_vs_best": None,
        "win_rate_vs_best_wins": 0,
        "win_rate_vs_best_n": 0,
    }
