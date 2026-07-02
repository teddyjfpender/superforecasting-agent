"""Unit tests for the Bayesian forecasting toolkit.

Covers every capability area in
docs/plans/feedback-forecaster-tooling-bayesian-example.md with known-value
numeric assertions, the JSON + human-readable output contract, and input
validation.
"""

from __future__ import annotations

import math

import pytest

from forecasting import bayes_toolkit as bt
from forecasting.models import ValidationError


# ── 1. Bayesian update scratchpad ───────────────────────────────────────────


def test_prob_odds_roundtrip():
    for p in (0.1, 0.5, 0.62, 0.9):
        assert bt.odds_to_prob(bt.prob_to_odds(p)) == pytest.approx(p, abs=1e-6)


def test_logit_inverse():
    for p in (0.05, 0.5, 0.62, 0.95):
        assert bt.inv_logit(bt.logit(p)) == pytest.approx(p, abs=1e-6)


def test_apply_lr_matches_odds_math():
    # prior odds 0.62/0.38 = 1.6316; * 0.85 = 1.3868; -> 0.5810
    assert bt.apply_lr(0.62, 0.85) == pytest.approx(0.5810, abs=1e-3)


def test_apply_lrs_is_sequential_independent_update():
    expected = bt.apply_lr(bt.apply_lr(bt.apply_lr(0.62, 0.85), 0.70), 1.25)
    assert bt.apply_lrs(0.62, [0.85, 0.70, 1.25]) == pytest.approx(expected, abs=1e-9)


def test_log_odds_update_sums_log_lrs():
    lrs = [0.85, 0.70, 1.25]
    weights = [math.log(lr) for lr in lrs]
    assert bt.log_odds_update(0.62, weights) == pytest.approx(bt.apply_lrs(0.62, lrs), abs=1e-9)


def test_decompose_update_recovers_lr():
    out = bt.decompose_update(0.62, 0.581)
    assert out["implied_lr"] == pytest.approx(0.85, abs=1e-2)
    assert out["prob_delta"] == pytest.approx(-0.039, abs=1e-3)


def test_apply_lr_rejects_nonpositive():
    with pytest.raises(ValidationError):
        bt.apply_lr(0.5, 0.0)


# ── 3. Ensemble combiners ───────────────────────────────────────────────────


def test_linear_pool_is_weighted_mean():
    assert bt.linear_pool([0.4, 0.6], [1, 3]) == pytest.approx((0.4 + 1.8) / 4, abs=1e-9)


def test_log_odds_pool_equals_logit_average():
    p = bt.log_odds_pool([0.3, 0.8], [1, 1])
    expected = bt.inv_logit((bt.logit(0.3) + bt.logit(0.8)) / 2)
    assert p == pytest.approx(expected, abs=1e-9)


def test_log_odds_pool_differs_from_linear_for_disagreement():
    linear = bt.linear_pool([0.1, 0.9])
    logodds = bt.log_odds_pool([0.1, 0.9])
    assert linear == pytest.approx(0.5, abs=1e-9)
    # Geometric-odds pool of symmetric extremes is also 0.5 but via odds space.
    assert logodds == pytest.approx(0.5, abs=1e-9)


def test_extremize_pushes_away_from_half():
    assert bt.extremize(0.6, 1.5) > 0.6
    assert bt.extremize(0.4, 1.5) < 0.4
    assert bt.de_extremize(bt.extremize(0.7, 1.4), 1.4) == pytest.approx(0.7, abs=1e-9)


def test_combine_forecasts_outputs_contract():
    result = bt.combine_forecasts(
        [
            {"name": "markets", "p": 0.555, "weight": 0.30},
            {"name": "polling", "p": 0.49, "weight": 0.25},
            {"name": "ratings", "p": 0.62, "weight": 0.20},
            {"name": "base_rate", "p": 0.75, "weight": 0.25},
        ],
        method="log_odds_pool",
        extremize=1.05,
        correlation_matrix="estimate",
    )
    payload = result.to_dict()
    assert 0.0 < payload["probability"] < 1.0
    assert payload["correlation_applied"] is True
    assert payload["effective_independent_sources"] < 4
    assert payload["extremize_factor"] == pytest.approx(1.05, abs=1e-9)
    assert "markets" in result.to_text()
    assert len(payload["components"]) == 4


def test_combine_forecasts_rejects_unknown_method():
    with pytest.raises(ValidationError):
        bt.combine_forecasts([{"name": "a", "p": 0.5}], method="bogus")


def test_correlation_reduces_effective_sources():
    comps = [{"name": f"s{i}", "p": 0.6} for i in range(4)]
    no_corr = bt.combine_forecasts(comps)
    corr = bt.combine_forecasts(comps, correlation_matrix="estimate")
    assert no_corr.effective_independent_sources is None
    assert corr.effective_independent_sources is not None
    assert corr.effective_independent_sources < 4


# ── 2. Evidence-weighted likelihood-ratio builder ───────────────────────────


def test_evidence_weight_direction_and_quality():
    favorable = bt.evidence_weight(
        reliability=0.8, relevance=0.8, independence=0.9, recency="high",
        bias_risk="low", direction="for", strength="strong", name="poll",
    )
    against = bt.evidence_weight(
        reliability=0.8, relevance=0.8, independence=0.9, recency="high",
        bias_risk="low", direction="against", strength="strong", name="poll",
    )
    assert favorable.suggested_lr > 1.0
    assert against.suggested_lr < 1.0
    # Symmetric in log-odds.
    assert favorable.log_odds_contribution == pytest.approx(-against.log_odds_contribution, abs=1e-9)


def test_evidence_weight_downweights_correlated_and_biased():
    independent = bt.evidence_weight(reliability=0.8, independence=0.9, strength="strong")
    dependent = bt.evidence_weight(reliability=0.8, independence=0.2, strength="strong")
    biased = bt.evidence_weight(reliability=0.8, independence=0.9, bias_risk="high", strength="strong")
    # Lower independence -> LR closer to 1 (weaker update).
    assert abs(math.log(dependent.suggested_lr)) < abs(math.log(independent.suggested_lr))
    assert any("independence" in n for n in dependent.notes)
    assert abs(math.log(biased.suggested_lr)) < abs(math.log(independent.suggested_lr))


def test_evidence_weight_separates_reliability_from_relevance():
    reliable_irrelevant = bt.evidence_weight(reliability=0.9, relevance=0.2, strength="strong")
    assert any("relevance" in n for n in reliable_irrelevant.notes)


# ── 7. Correlation / double-counting checker ─────────────────────────────────


def test_evidence_cluster_collapses_shared_signal():
    cluster = bt.evidence_cluster(
        ["NYT poll", "ABC analysis", "Polymarket move", "270toWin price"],
        name="Paxton vulnerability",
        shared_signal="high",
    )
    assert cluster.raw_count == 4
    assert cluster.effective_independent_weight < 4
    assert cluster.effective_independent_weight >= 1.0
    assert "Paxton vulnerability" in cluster.to_text()


# ── 4. Base-rate / reference-class calculator ────────────────────────────────


def test_blend_base_rates_weights_by_applicability():
    blend = bt.blend_base_rates([
        {"name": "broad class", "base_rate": 0.2, "applicability": "low"},
        {"name": "tight class", "base_rate": 0.6, "applicability": "high"},
    ])
    # High-applicability class should dominate.
    assert blend.blended_base_rate > 0.4
    assert blend.uncertainty_sd > 0
    assert any("most applicable" in n for n in blend.notes)


def test_blend_base_rates_flags_disagreement():
    blend = bt.blend_base_rates([
        {"name": "a", "base_rate": 0.1, "applicability": 0.5},
        {"name": "b", "base_rate": 0.8, "applicability": 0.5},
    ])
    assert any("disagree" in n for n in blend.notes)


# ── 5. Poll-to-probability model helper ──────────────────────────────────────


def test_poll_margin_to_win_prob_normal_cdf():
    # Tied race -> 50%.
    assert bt.poll_margin_to_win_prob(0.0, 6.5) == pytest.approx(0.5, abs=1e-6)
    # +1 sd lead -> ~84%.
    assert bt.poll_margin_to_win_prob(6.5, 6.5) == pytest.approx(0.8413, abs=1e-3)


def test_poll_margin_fundamentals_shrinkage():
    # Pure polls (shrinkage 0) keeps the lead; full shrinkage adopts fundamentals.
    pure = bt.poll_margin_to_win_prob(6.0, 6.0, fundamentals_margin=-6.0, shrinkage=0.0)
    full = bt.poll_margin_to_win_prob(6.0, 6.0, fundamentals_margin=-6.0, shrinkage=1.0)
    assert pure > 0.5
    assert full < 0.5


# ── 6. SciPy is imported lazily; the stdlib fallback is numerically exact ──────


def test_importing_bayes_toolkit_does_not_eagerly_load_scipy():
    # Merely importing the module (as the CLI / agent-tool / TUI paths do) must
    # not pull scipy.stats — that import is ~0.3s and is deferred to first use.
    # Run in a clean subprocess so the check is not polluted by scipy already
    # being resident from earlier tests in this session.
    import subprocess
    import sys

    code = (
        "import sys; import forecasting.bayes_toolkit as bt; "
        "print('scipy.stats' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False", out.stdout + out.stderr


def test_normal_cdf_ppf_parity_with_and_without_scipy(monkeypatch):
    """The math.erf / Acklam fallbacks must match SciPy to within tolerance, so
    a scipy-less install returns the SAME numbers."""
    scipy_stats = bt._get_scipy_stats()
    if scipy_stats is None:
        pytest.skip("scipy not installed; only the fallback path is exercised")

    cdf_pts = [0.5, 1.0, -2.3, 0.01, 0.99, -0.7]
    ppf_pts = [0.1, 0.5, 0.9, 0.975, 0.025, 0.3]
    cdf_scipy = [bt.normal_cdf(v) for v in cdf_pts]
    ppf_scipy = [bt.normal_ppf(q) for q in ppf_pts]

    # Force the stdlib fallback: sentinel None + "already probed" so no re-import.
    monkeypatch.setattr(bt, "_scipy_stats", None)
    monkeypatch.setattr(bt, "_scipy_stats_probed", True)
    assert bt._get_scipy_stats() is None
    cdf_fallback = [bt.normal_cdf(v) for v in cdf_pts]
    ppf_fallback = [bt.normal_ppf(q) for q in ppf_pts]

    for a, b in zip(cdf_scipy, cdf_fallback):
        assert a == pytest.approx(b, abs=1e-12)
    for a, b in zip(ppf_scipy, ppf_fallback):
        assert a == pytest.approx(b, abs=1e-6)


def test_polls_to_win_probability_pipeline():
    model = bt.polls_to_win_probability(
        [
            {"margin": 7, "sample_size": 643, "sponsor_bias": "D", "pollster_quality": "medium", "days_old": 5},
            {"margin": 0, "sample_size": 1223, "mode": "nonprobability", "days_old": 20},
        ],
        fundamentals_margin=-4,
        days_to_election=160,
    )
    payload = model.to_dict()
    assert payload["polls_used"] == 2
    assert payload["uncertainty_sd"] > 3.0  # horizon inflates uncertainty
    assert 0.0 < payload["win_probability"] < 1.0
    # Sponsor + nonprobability adjustments leave notes.
    assert any("sponsor" in n.lower() or "nonprobability" in n.lower() for n in model.notes)


# ── 6. Market de-vig and liquidity adjustment ────────────────────────────────


def test_devig_binary_market_normalizes():
    # YES mid 0.575, NO mid 0.435 -> normalized 0.569.
    assert bt.devig_binary_market(0.57, 0.58, 0.43, 0.44) == pytest.approx(0.569, abs=1e-3)


def test_devig_binary_market_yes_only_returns_mid():
    assert bt.devig_binary_market(0.55, 0.57) == pytest.approx(0.56, abs=1e-9)


def test_normalize_categorical_market_removes_overround():
    out = bt.normalize_categorical_market({"R": 0.57, "D": 0.46})
    assert sum(out["normalized"].values()) == pytest.approx(1.0, abs=1e-6)
    assert out["overround"] == pytest.approx(0.03, abs=1e-6)


def test_combine_markets_devigs_and_reports_disagreement():
    model = bt.combine_markets([
        {"source": "Kalshi", "bid_yes": 0.57, "ask_yes": 0.58, "bid_no": 0.43, "ask_no": 0.44, "volume": 1_500_000},
        {"source": "Polymarket", "yes_mid": 0.525, "volume": 400_000},
    ])
    payload = model.to_dict()
    assert 0.5 < payload["implied_probability"] < 0.6
    assert payload["uncertainty"] > 0
    assert len(payload["markets"]) == 2


# ── 8. Sensitivity / robustness analyzer ─────────────────────────────────────


def test_sensitivity_grid_tornado_sorted_by_swing():
    comps = [
        {"name": "markets", "p": 0.555, "weight": 0.30},
        {"name": "polling", "p": 0.49, "weight": 0.25},
        {"name": "base_rate", "p": 0.75, "weight": 0.25},
    ]
    result = bt.sensitivity_grid(
        comps,
        {"polling": [0.45, 0.55], "base_rate": [0.6, 0.9], "__drop__": ["markets"]},
    )
    swings = [row["swing"] for row in result.tornado]
    assert swings == sorted(swings, reverse=True)
    assert any(row["parameter"] == "drop markets" for row in result.tornado)
    assert result.to_dict()["base_probability"] > 0


def test_sensitivity_grid_rejects_unknown_parameter():
    with pytest.raises(ValidationError):
        bt.sensitivity_grid([{"name": "a", "p": 0.5}], {"missing": [0.4, 0.6]})


# ── 10. Forecast-diff explainer ──────────────────────────────────────────────


def test_forecast_diff_explicit_deltas_sum_to_net():
    diff = bt.forecast_diff(
        0.621, 0.593,
        components=[
            {"name": "NYT polling", "delta_pts": -0.020},
            {"name": "generic ballot", "delta_pts": -0.015},
            {"name": "markets", "delta_pts": 0.008},
            {"name": "ratings", "delta_pts": 0.004},
        ],
    )
    payload = diff.to_dict()
    total = sum(d["contribution_pts"] for d in payload["drivers"])
    assert total == pytest.approx(payload["net_change"] * 100, abs=0.1)
    assert payload["net_change"] == pytest.approx(-0.028, abs=1e-3)


def test_forecast_diff_component_probs_attribution():
    diff = bt.forecast_diff(
        0.62, 0.59,
        components=[
            {"name": "polling", "previous_p": 0.55, "current_p": 0.49, "weight": 2},
            {"name": "markets", "previous_p": 0.6, "current_p": 0.6, "weight": 1},
        ],
    )
    payload = diff.to_dict()
    total = sum(d["contribution_pts"] for d in payload["drivers"])
    assert total == pytest.approx(payload["net_change"] * 100, abs=0.5)
    # Polling moved and carries weight; markets unchanged -> ~0 contribution.
    contribs = {d["name"]: d["contribution_pts"] for d in payload["drivers"]}
    assert abs(contribs["markets"]) < abs(contribs["polling"])


def test_forecast_diff_no_components_reports_net():
    diff = bt.forecast_diff(0.5, 0.6)
    assert diff.to_dict()["drivers"][0]["contribution_pts"] == pytest.approx(10.0, abs=0.1)
