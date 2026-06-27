"""AIA P1.4 — convexity-backed simple-mean baseline + ensemble-size analysis.

Covers four things:
  * the new ``'mean'`` panel-aggregation method (== arithmetic mean, then Platt),
  * a HARD GUARD that the LIVE default method + the default quorum preset/count
    are byte-identical to history (the un-configured path must not change),
  * ``bootstrap_ensemble_curve`` determinism, CI-narrowing with k, and the
    Jensen inequality (Brier-of-mean <= mean-of-Briers),
  * the opt-in ``'wide'`` quorum preset existing while the default is untouched.
"""

from __future__ import annotations

import math
from statistics import mean

import pytest

from forecasting.bayes_toolkit import mean_probability, platt_scale
from forecasting.panel import (
    DEFAULT_PANEL_AGGREGATION_METHOD,
    PANEL_AGGREGATION_METHODS,
    aggregate_panel_estimates,
)
from forecasting.quorum import QUORUM_PRESETS, resolve_models
from forecasting.quorum_analysis import (
    bootstrap_ensemble_curve,
    variance_decomposition,
)


def _estimates(*probs: float):
    return [{"probability": p} for p in probs]


# ── 1. 'mean' method correctness ─────────────────────────────────────────────


def test_mean_method_is_arithmetic_mean():
    probs = [0.2, 0.5, 0.9]
    # trim=0 so we average all three.
    result = aggregate_panel_estimates(_estimates(*probs), method="mean", trim=0)
    assert result.method == "mean"
    assert result.aggregate_probability == pytest.approx(mean(probs))
    # At the identity alpha, no terminal calibration runs (byte-identical to bare pool).
    assert result.pre_extremize_probability is None
    assert result.applied_alpha == 1.0


def test_mean_method_then_platt_applies_identically():
    probs = [0.2, 0.5, 0.9]
    alpha = 1.7
    result = aggregate_panel_estimates(
        _estimates(*probs), method="mean", trim=0, alpha_extremize=alpha
    )
    bare = mean_probability(probs)
    assert result.pre_extremize_probability == pytest.approx(bare)
    assert result.aggregate_probability == pytest.approx(
        platt_scale(bare, alpha=alpha, d=1.0)
    )


def test_mean_is_selectable_in_methods():
    assert "mean" in PANEL_AGGREGATION_METHODS


# ── 2. HARD GUARD: live default is unchanged ─────────────────────────────────


def test_default_panel_aggregation_method_unchanged():
    # The pinned live default must stay trimmed_geomean_odds.
    assert DEFAULT_PANEL_AGGREGATION_METHOD == "trimmed_geomean_odds"


def test_unconfigured_panel_is_byte_identical_to_geomean_odds():
    # An un-configured aggregate (no method, no alpha) must equal the historical
    # trimmed_geomean_odds path exactly — adding 'mean' must not perturb it.
    probs = [0.2, 0.5, 0.9, 0.55, 0.6]
    default = aggregate_panel_estimates(_estimates(*probs))
    explicit = aggregate_panel_estimates(
        _estimates(*probs), method="trimmed_geomean_odds", trim=1, alpha_extremize=1.0
    )
    assert default.method == "trimmed_geomean_odds"
    assert default.trim == 1
    assert default.applied_alpha == 1.0
    assert default.pre_extremize_probability is None
    assert default.aggregate_probability == explicit.aggregate_probability
    # And the mean baseline genuinely differs (it is a real alternative, not a noop).
    as_mean = aggregate_panel_estimates(_estimates(*probs), method="mean", trim=0)
    assert as_mean.aggregate_probability != pytest.approx(default.aggregate_probability)


def test_quorum_default_preset_and_self_sample_count_unchanged():
    # The live default preset (frontier) and the self-fusion default sample count
    # (3) are the un-configured live behaviour and must not move.
    models, _judge = resolve_models(None, None)
    assert models == list(QUORUM_PRESETS["frontier"]["models"])
    assert QUORUM_PRESETS["self"]["samples"] == 3
    self_models, _ = resolve_models("self", None, active_model="openai/gpt-5.5")
    assert len(self_models) == 3


# ── 3. bootstrap_ensemble_curve ──────────────────────────────────────────────


def test_bootstrap_ensemble_curve_is_deterministic():
    probs = [0.1, 0.3, 0.4, 0.6, 0.7, 0.9]
    a = bootstrap_ensemble_curve(probs, 1.0, seed=42, draws=200)
    b = bootstrap_ensemble_curve(probs, 1.0, seed=42, draws=200)
    assert a == b
    # Different seed → different bootstrap realisation.
    c = bootstrap_ensemble_curve(probs, 1.0, seed=7, draws=200)
    assert c != a


def test_bootstrap_ci_narrows_with_k():
    probs = [0.1, 0.3, 0.4, 0.6, 0.7, 0.9]
    curve = bootstrap_ensemble_curve(probs, 1.0, seed=0, draws=1000)["curve"]
    widths = [point["ci95_width"] for point in curve]
    # The CI at the largest ensemble size is narrower than at k=1 (variance
    # reduction): the sharp-drop-then-plateau shape.
    assert widths[-1] < widths[0]
    # Endpoint: a full-size resample with replacement still beats a single draw.
    assert curve[-1]["k"] == len(probs)


def test_bootstrap_curve_mean_brier_converges_toward_full_panel():
    probs = [0.2, 0.4, 0.5, 0.6, 0.8]
    report = bootstrap_ensemble_curve(probs, 1.0, seed=3, draws=2000)
    full = report["full_panel_mean_brier"]
    # The largest-k bootstrap mean Brier sits close to the full-panel mean Brier.
    assert report["curve"][-1]["mean_brier"] == pytest.approx(full, abs=0.02)


def test_jensen_brier_of_mean_le_mean_of_brier():
    # Brier is convex in the forecast, so for a fixed outcome the simple mean's
    # Brier is no worse than the mean of the components' Briers.
    probs = [0.1, 0.35, 0.5, 0.75, 0.95]
    for outcome in (0.0, 1.0):
        pooled = mean_probability(probs)
        brier_of_mean = (pooled - outcome) ** 2
        mean_of_brier = mean((p - outcome) ** 2 for p in probs)
        assert brier_of_mean <= mean_of_brier + 1e-12


def test_variance_decomposition_records_both_briers_and_jensen_gap():
    # Two runs, each with several resampled draws of one brief.
    run_forecasts = [
        [0.2, 0.3, 0.25, 0.35],  # question 1
        [0.7, 0.8, 0.75, 0.65],  # question 2
    ]
    outcomes = [0.0, 1.0]
    report = variance_decomposition(run_forecasts, outcomes)
    assert report["n_runs"] == 2
    # Both scorings are present and the aggregate Jensen gap is non-negative.
    assert report["mean_brier_of_mean"] <= report["mean_mean_of_brier"] + 1e-12
    assert report["jensen_gap"] >= 0.0
    # Sampling (within-run LLM noise) and question (between-run) variance both reported.
    assert report["sampling_variance"] >= 0.0
    assert report["question_variance"] >= 0.0
    for run in report["runs"]:
        assert run["jensen_gap"] >= -1e-9
        assert "brier_of_mean" in run and "mean_of_brier" in run


# ── 4. 'wide' opt-in preset ──────────────────────────────────────────────────


def test_wide_preset_exists_and_is_opt_in():
    assert "wide" in QUORUM_PRESETS
    wide = QUORUM_PRESETS["wide"]
    assert len(wide["models"]) >= 9  # ~10 mixed-model draws
    # It is never the default: resolving with no preset stays on frontier.
    default_models, _ = resolve_models(None, None)
    assert default_models != list(wide["models"])
    # And it is reachable explicitly.
    wide_models, judge = resolve_models("wide", None)
    assert wide_models == list(wide["models"])
    assert judge == wide["judge"]
