"""Unit tests for :mod:`forecasting.calibration_bias` — the SIGNED calibration
bias metric and its anti-over-biasing safeguards.

The module is pure math (no DB/IO). These tests assert the safeguards as hard
invariants: thin/noisy data emits nothing; a perfectly-calibrated forecaster
(including honest near-0.5 forecasts) reads ~0 with no direction; a planted
under-confidence is detected with the correct sign and shrunk magnitude;
``|SCE| <= ECE`` always; the mechanical nudge is empty unless opted-in and is a
base-rate-neutral ``logit_scale``; Benjamini-Hochberg controls the family error
rate; and the trajectory guard suppresses a diverging bias.
"""

from __future__ import annotations

import math

import pytest

from forecasting.calibration_bias import (
    Observation,
    assess_bias,
    benjamini_hochberg,
    decide_disposition,
    effective_sample_size,
    signed_calibration_error,
)


# ── helpers ──────────────────────────────────────────────────────────────────


def _obs(p, outcome, weight=1.0, lesson_active=False, horizon_days=None):
    return Observation(
        p_yes=p,
        outcome=float(outcome),
        weight=weight,
        lesson_active=lesson_active,
        horizon_days=horizon_days,
    )


def _calibrated_set(p, n):
    """n forecasts all at P(yes)=p, with outcomes realising exactly p (rounded).

    Deterministic: ``round(p*n)`` of them resolve yes. This is the calibrated
    reference — SCE should be ~0.
    """

    yes = round(p * n)
    return [_obs(p, 1.0 if i < yes else 0.0) for i in range(n)]


def _underconfident_set(p_stated, p_true, n):
    """n forecasts stated at ``p_stated`` but realising at the (more extreme,
    same-side) ``p_true``. With p_true>p_stated>0.5 this is under-confidence."""

    yes = round(p_true * n)
    return [_obs(p_stated, 1.0 if i < yes else 0.0) for i in range(n)]


# ── effective sample size ────────────────────────────────────────────────────


def test_ess_uniform_equals_count():
    assert effective_sample_size([1.0] * 10) == pytest.approx(10.0)


def test_ess_decayed_below_count():
    weights = [0.5**k for k in range(20)]  # heavy recency decay
    ess = effective_sample_size(weights)
    assert ess < 20.0
    assert ess == pytest.approx((sum(weights) ** 2) / sum(w * w for w in weights))


def test_ess_zero_for_no_weight():
    assert effective_sample_size([]) == 0.0
    assert effective_sample_size([0.0, 0.0]) == 0.0


# ── core metric sign + neutral band ──────────────────────────────────────────


def test_calibrated_reads_near_zero():
    sce = signed_calibration_error(_calibrated_set(0.70, 100))
    assert sce is not None
    assert abs(sce) < 0.02


def test_underconfident_is_negative():
    sce = signed_calibration_error(_underconfident_set(0.70, 0.90, 100))
    assert sce is not None
    assert sce < 0  # under-confident
    # magnitude tracks the reliability gap (0.70 vs 0.90 ~ -0.20)
    assert sce == pytest.approx(-0.20, abs=0.02)


def test_overconfident_is_positive():
    # stated 0.90 but only 0.70 realised → over-confident
    sce = signed_calibration_error(_underconfident_set(0.90, 0.70, 100))
    assert sce is not None
    assert sce > 0


def test_no_leaning_below_50_handled():
    # stated 0.30 (leans NO), realised 0.10 yes → "no" happened more than stated
    # → under-confident → negative.
    sce = signed_calibration_error(_underconfident_set(0.30, 0.10, 100))
    assert sce is not None
    assert sce < 0


def test_neutral_band_forecasts_excluded():
    # All forecasts at exactly 0.50 (and 0.52, inside the 0.05 band) contribute
    # nothing — the max(p,1-p) fold would have fabricated a bias here.
    rows = [_obs(0.50, i % 2) for i in range(40)] + [_obs(0.52, 0) for _ in range(40)]
    assert signed_calibration_error(rows) is None


def test_honest_coinflips_do_not_read_as_overconfident():
    # The classic failure mode: a forecaster who honestly reports ~0.5 must NOT
    # be flagged over-confident. Just outside the band, balanced outcomes.
    rows = [_obs(0.56, 1.0) for _ in range(28)] + [_obs(0.56, 0.0) for _ in range(22)]
    rep = assess_bias(rows, scope_ref="markets")
    # 0.56 stated, 28/50=0.56 realised → calibrated.
    assert rep.status == "calibrated"
    assert rep.direction is None


# ── |SCE| <= ECE invariant ───────────────────────────────────────────────────


@pytest.mark.parametrize("p_stated,p_true,n", [(0.70, 0.90, 80), (0.80, 0.60, 80), (0.30, 0.15, 80)])
def test_sce_bounded_by_ece(p_stated, p_true, n):
    rep = assess_bias(_underconfident_set(p_stated, p_true, n), scope_ref="x")
    assert rep.sce_raw is not None and rep.ece is not None
    assert abs(rep.sce_raw) <= rep.ece + 1e-9


# ── fail-safe gates ──────────────────────────────────────────────────────────


def test_empty_is_insufficient():
    rep = assess_bias([], scope_ref="politics")
    assert rep.status == "insufficient_evidence"
    assert rep.sce_raw is None
    assert rep.recommended_adjustment == {}


def test_below_ess_floor_is_insufficient():
    # 8 clear under-confident points — well under the domain floor of 12.
    rep = assess_bias(_underconfident_set(0.70, 0.95, 8), scope_ref="politics")
    assert rep.status == "insufficient_evidence"
    assert not rep.has_detectable_bias


def test_noise_with_wide_ci_is_calibrated_not_biased():
    # A small, noisy sample whose CI includes zero must NOT emit a direction.
    rows = _underconfident_set(0.70, 0.78, 15)  # mild, n small → CI wide
    rep = assess_bias(rows, scope_ref="politics")
    assert rep.status in {"calibrated", "insufficient_evidence"}
    assert rep.direction is None


def test_clear_large_sample_bias_detected_with_direction():
    rep = assess_bias(_underconfident_set(0.70, 0.90, 120), scope_ref="politics")
    assert rep.status == "underconfident"
    assert rep.direction == "under"
    assert rep.sce_shrunk is not None and rep.sce_shrunk < 0
    assert rep.advisory_text and "under-confident" in rep.advisory_text
    assert "politics" in rep.advisory_text


def test_shrinkage_pulls_toward_zero():
    rows = _underconfident_set(0.70, 0.90, 60)
    rep = assess_bias(rows, scope_ref="politics")
    assert rep.sce_raw is not None and rep.sce_shrunk is not None
    # shrunk estimate is strictly smaller in magnitude than the raw estimate
    assert abs(rep.sce_shrunk) < abs(rep.sce_raw)


# ── advisory-by-default / mechanical opt-in ──────────────────────────────────


def test_mechanical_off_by_default_means_empty_adjustment():
    rep = assess_bias(_underconfident_set(0.70, 0.92, 120), scope_ref="politics")
    assert rep.has_detectable_bias
    assert rep.recommended_adjustment == {}  # advisory only


def test_mechanical_on_emits_base_rate_neutral_logit_scale():
    rows = _underconfident_set(0.70, 0.92, 120)  # large ESS, big bias
    rep = assess_bias(rows, scope_ref="politics", enable_mechanical=True)
    adj = rep.recommended_adjustment
    assert adj, "mechanical path should emit an adjustment at high ESS + big bias"
    assert "logit_scale" in adj
    assert "logit_shift" not in adj and "probability_delta" not in adj  # never base-rate
    # under-confident ⇒ sharpen ⇒ scale > 1, bounded by the cap.
    assert 1.0 < adj["logit_scale"] <= 1.0 + adj["cap"] + 1e-9


def test_mechanical_silent_below_high_ess():
    # detectable bias but ESS in [domain floor, mech floor) ⇒ no numeric nudge.
    rows = _underconfident_set(0.70, 0.92, 30)
    rep = assess_bias(rows, scope_ref="politics", enable_mechanical=True)
    assert rep.has_detectable_bias
    assert rep.recommended_adjustment == {}


def test_overconfident_mechanical_flattens():
    rows = _underconfident_set(0.92, 0.70, 120)  # stated bold, realised tame
    rep = assess_bias(rows, scope_ref="politics", enable_mechanical=True)
    assert rep.status == "overconfident"
    if rep.recommended_adjustment:
        assert rep.recommended_adjustment["logit_scale"] < 1.0


# ── contamination stratification ─────────────────────────────────────────────


def test_lesson_active_forecasts_excluded_from_derivation():
    clean = _underconfident_set(0.70, 0.90, 60)
    # add lots of lesson-active points with the OPPOSITE bias; they must be
    # ignored when lesson_free_only=True, leaving the clean signal intact.
    contaminated = [
        _obs(0.90, 0.0, lesson_active=True) for _ in range(60)
    ]
    rep = assess_bias(clean + contaminated, scope_ref="politics", lesson_free_only=True)
    assert rep.status == "underconfident"
    assert any("lesson-active" in note for note in rep.notes)
    # the contaminated set alone would have flipped the sign:
    rep_all = assess_bias(clean + contaminated, scope_ref="politics", lesson_free_only=False)
    assert rep_all.sce_raw is not None and rep.sce_raw is not None
    assert rep_all.sce_raw > rep.sce_raw  # contamination pushes it toward over-confident


# ── Benjamini-Hochberg FDR ───────────────────────────────────────────────────


def test_bh_all_null_survives_none():
    # twelve domains, all p~uniform-ish high → none should survive at q=0.10
    pvals = [0.4, 0.6, 0.8, 0.55, 0.7, 0.9, 0.33, 0.5, 0.66, 0.77, 0.88, 0.99]
    assert benjamini_hochberg(pvals, q=0.10) == [False] * 12


def test_bh_one_strong_survives():
    pvals = [0.0001] + [0.5] * 11
    survived = benjamini_hochberg(pvals, q=0.10)
    assert survived[0] is True
    assert sum(survived) == 1


def test_bh_none_pvalues_never_survive():
    assert benjamini_hochberg([None, None], q=0.10) == [False, False]


# ── disposition: activation gates + trajectory guard ─────────────────────────


def test_disposition_none_when_no_bias():
    rep = assess_bias(_calibrated_set(0.70, 60), scope_ref="politics")
    out = decide_disposition(rep, bh_survived=True)
    assert out["lesson_status"] == "none"


def test_disposition_none_when_bh_fails():
    rep = assess_bias(_underconfident_set(0.70, 0.90, 120), scope_ref="politics")
    out = decide_disposition(rep, bh_survived=False)
    assert out["lesson_status"] == "none"


def test_disposition_tentative_when_below_strong_ess():
    # Clear, significant bias but ESS=25 < strong floor of 30 ⇒ tentative, NOT
    # auto-activated. This is the human-promotion-gate path.
    rep = assess_bias(_underconfident_set(0.70, 0.95, 25), scope_ref="politics")
    assert rep.status == "underconfident", rep.notes
    assert rep.ess < 30
    out = decide_disposition(rep, bh_survived=True)
    assert out["lesson_status"] == "tentative"


def test_disposition_active_when_strong():
    rep = assess_bias(_underconfident_set(0.70, 0.90, 120), scope_ref="politics")
    out = decide_disposition(rep, bh_survived=True)
    assert out["lesson_status"] == "active"


def test_trajectory_guard_suppresses_divergence():
    rep = assess_bias(_underconfident_set(0.70, 0.92, 120), scope_ref="politics")
    mag = abs(rep.sce_shrunk)
    # prior history rising toward this cycle (two consecutive increases) ⇒ suppress
    out = decide_disposition(rep, bh_survived=True, trajectory=[mag - 0.06, mag - 0.03])
    assert out["lesson_status"] == "suppressed"


def test_trajectory_ok_when_decreasing():
    rep = assess_bias(_underconfident_set(0.70, 0.90, 120), scope_ref="politics")
    mag = abs(rep.sce_shrunk)
    out = decide_disposition(rep, bh_survived=True, trajectory=[mag + 0.10, mag + 0.05])
    assert out["lesson_status"] == "active"
