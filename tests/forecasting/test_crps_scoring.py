"""CRPS scoring for the distribution / numeric class.

Pins the CRPS math against known distributions, checks the score_snapshot
integration end-to-end, and proves the binary Brier path is unchanged.
"""

from __future__ import annotations

import math

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.ledger.scoring import (
    _crps_cdf_points,
    _crps_discrete,
    _crps_integral,
    _crps_normal,
    _crps_pmf_points,
    _crps_score,
)
from forecasting.models import OutcomeSpace


# ── math pins ────────────────────────────────────────────────────────────────


def test_normal_crps_standard_at_mean():
    # CRPS(N(0,1), 0) = 2·φ(0) − 1/√π ≈ 0.233695.
    value = _crps_normal(0.0, 1.0, 0.0)
    assert value == pytest.approx(2 / math.sqrt(2 * math.pi) - 1 / math.sqrt(math.pi))
    assert value == pytest.approx(0.2336949, abs=1e-6)


def test_normal_crps_scales_with_sigma():
    # CRPS is homogeneous of degree 1: CRPS(N(μ,kσ), μ) = k·CRPS(N(μ,σ), μ).
    base = _crps_normal(5.0, 1.0, 5.0)
    assert _crps_normal(5.0, 3.0, 5.0) == pytest.approx(3.0 * base)


def test_normal_crps_worsens_as_outcome_leaves_mean():
    near = _crps_normal(0.0, 1.0, 0.5)
    far = _crps_normal(0.0, 1.0, 3.0)
    assert far > near > _crps_normal(0.0, 1.0, 0.0)


def test_discrete_cdf_crps_pin():
    # F(0)=0.1, F(1)=0.5, F(2)=0.9; outcome 1.5 → steps 0,0,1.
    points = [(0.0, 0.1), (1.0, 0.5), (2.0, 0.9)]
    crps = _crps_discrete(points, 1.5)
    assert crps == pytest.approx(0.01 + 0.5 * 0.25 + 0.5 * 0.25)


def test_discrete_cdf_crps_perfect_step():
    # A degenerate CDF that jumps exactly at the outcome scores ~0.
    points = [(0.0, 0.0), (1.0, 0.0), (2.0, 1.0)]
    assert _crps_discrete(points, 2.0) == pytest.approx(0.0)


# ── point extraction from real snapshot shapes ───────────────────────────────


def test_cdf_points_from_p_below_thresholds():
    payload = {"mean": 3.9, "sd": 0.35, "p_below_3_0": 0.0051, "p_below_3_5": 0.1265, "p_below_4_0": 0.6125, "p_below_4_5": 0.9568}
    points = _crps_cdf_points(payload)
    assert points == [(3.0, 0.0051), (3.5, 0.1265), (4.0, 0.6125), (4.5, 0.9568)]


def test_cdf_points_from_q_quantiles():
    payload = {"mean": 0.36, "q05": 0.05, "q25": 0.22, "q50": 0.35, "q75": 0.48, "q95": 0.75}
    points = dict(_crps_cdf_points(payload))
    assert points[0.05] == pytest.approx(0.05)
    assert points[0.35] == pytest.approx(0.5)
    assert points[0.75] == pytest.approx(0.95)


def test_cdf_points_from_intervals_and_median():
    payload = {"mean": 57.0, "median": 57.0, "interval_50_low": 52.0, "interval_50_high": 62.0, "interval_90_low": 45.0, "interval_90_high": 72.0}
    points = dict(_crps_cdf_points(payload))
    assert points[45.0] == pytest.approx(0.05)
    assert points[52.0] == pytest.approx(0.25)
    assert points[57.0] == pytest.approx(0.5)
    assert points[62.0] == pytest.approx(0.75)
    assert points[72.0] == pytest.approx(0.95)


def test_bare_pNN_not_read_as_quantiles():
    # Bare pNN collide with count-PMF mass labels; only explicit q-/CDF keys count.
    payload = {"mean": 3.9, "p05": 3.324, "p95": 4.476}
    assert _crps_cdf_points(payload) == []


def test_pmf_points_from_count_labels():
    payload = {"p0": 0.2, "p1": 0.5, "p2": 0.3}
    points = _crps_pmf_points(payload)
    assert points == [(0.0, pytest.approx(0.2)), (1.0, pytest.approx(0.7)), (2.0, pytest.approx(1.0))]


def test_pmf_points_reject_non_mass():
    assert _crps_pmf_points({"p0": 0.2, "p1": 0.1}) is None  # sums to 0.3, not a PMF


# ── _crps_score dispatch + refusals ──────────────────────────────────────────


def _ledger(tmp_path):
    return ForecastLedger(tmp_path / "crps.db")


def test_crps_score_prefers_cdf_thresholds(tmp_path):
    ledger = _ledger(tmp_path)
    payload = {"mean": 3.9, "sd": 0.35, "p_below_3_0": 0.0051, "p_below_3_5": 0.1265, "p_below_4_0": 0.6125, "p_below_4_5": 0.9568}
    result = ledger._crps_score(payload, "4.24", OutcomeSpace(type="distribution"))
    assert result["score_rule"] == "crps_piecewise_linear_cdf_v2"
    assert result["brier_score"] is None
    assert result["proper_score"] == pytest.approx(_crps_integral(_crps_cdf_points(payload), 4.24, linear=True))
    # Gaussian mean+sd present → log score stays populated.
    assert result["log_score"] is not None


def test_crps_score_gaussian_fallback(tmp_path):
    ledger = _ledger(tmp_path)
    payload = {"mean": 5.0, "sd": 2.0}
    result = ledger._crps_score(payload, "5.0", OutcomeSpace(type="numeric"))
    assert result["score_rule"] == "crps_gaussian"
    assert result["proper_score"] == pytest.approx(_crps_normal(5.0, 2.0, 5.0))


def test_crps_refuses_vote_share_dict(tmp_path):
    ledger = _ledger(tmp_path)
    payload = {"Brad Lander": 66.0, "Dan Goldman": 34.0}
    # Non-scalar outcome → CRPS refuses (None), never fabricates a number.
    assert ledger._crps_score(payload, {"Brad Lander": 65.8, "Dan Goldman": 34.0}, OutcomeSpace(type="distribution")) is None


def test_crps_refuses_bare_mean(tmp_path):
    ledger = _ledger(tmp_path)
    # A bare mean has no distributional shape → the point squared-error path owns it.
    assert ledger._crps_score({"mean": 4.0}, "4.2", OutcomeSpace(type="numeric")) is None


# ── score_snapshot integration ───────────────────────────────────────────────


def test_score_snapshot_uses_crps_for_distribution(tmp_path):
    ledger = _ledger(tmp_path)
    question = ledger.create_question(
        title="What will the CPI year-over-year rate be at the next print?",
        resolution_criteria="Resolved to the published CPI YoY percentage rate.",
        outcome_space=OutcomeSpace(type="distribution", units="percent"),
    )
    snap = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution={"mean": 3.9, "sd": 0.35, "q05": 3.32, "q25": 3.66, "q50": 3.9, "q75": 4.14, "q95": 4.48},
        rationale="Distribution forecast for CPI YoY.",
    )
    ledger.resolve_question(question_id=question.id, outcome="4.24")
    score = ledger.get_current_score(question.id)
    assert score is not None
    assert score.score_rule == "crps_piecewise_linear_cdf_v2"
    assert score.brier_score is None
    assert score.proper_score is not None and score.proper_score >= 0.0


def test_score_snapshot_vote_share_unaffected(tmp_path):
    ledger = _ledger(tmp_path)
    question = ledger.create_question(
        title="What vote share will each mayoral candidate receive in the primary?",
        resolution_criteria="Resolved to the certified candidate vote-share percentages.",
        outcome_space=OutcomeSpace(type="distribution", units="percent"),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution={"Brad Lander": 66.0, "Dan Goldman": 34.0},
        rationale="Candidate share forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome={"Brad Lander": 65.81, "Dan Goldman": 34.0})
    score = ledger.get_current_score(question.id)
    assert score is not None
    # Vote-share vector scorer still owns this — NOT CRPS.
    assert not str(score.score_rule).startswith("crps")


def test_binary_brier_path_unchanged(tmp_path):
    ledger = _ledger(tmp_path)
    question = ledger.create_question(
        title="Will the binary event resolve yes by the deadline this year?",
        resolution_criteria="Resolved yes if the event occurs before the deadline.",
        outcome_space=OutcomeSpace(type="binary"),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.7,
        rationale="Binary probability forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="yes")
    score = ledger.get_current_score(question.id)
    assert score.score_rule == "brier"
    assert score.brier_score == pytest.approx((0.7 - 1.0) ** 2)


def test_backfill_crps_dry_run_is_read_only(tmp_path):
    ledger = _ledger(tmp_path)
    question = ledger.create_question(
        title="What will the distribution outcome value be at resolution time?",
        resolution_criteria="Resolved to the published numeric value at the horizon.",
        outcome_space=OutcomeSpace(type="distribution", units="percent"),
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution={"mean": 3.9, "sd": 0.35, "p_below_3_5": 0.13, "p_below_4_5": 0.96},
        rationale="Distribution forecast.",
    )
    ledger.resolve_question(question_id=question.id, outcome="4.24", auto_score=False)
    before = ledger.get_current_score(question.id)
    report = ledger.backfill_crps_scores(dry_run=True)
    assert report["counts"]["crps_scored"] >= 1
    # Dry run wrote nothing.
    assert ledger.get_current_score(question.id) == before
    real = ledger.backfill_crps_scores(dry_run=False)
    assert real["counts"]["crps_scored"] >= 1
    scored = ledger.get_current_score(question.id)
    assert scored is not None and scored.score_rule == "crps_piecewise_linear_cdf_v2"


def test_integral_crps_uniform_has_known_value_and_scales():
    # Uniform(0, 1) at its median: integral x^2 on each half = 1/12.
    assert _crps_integral([(0, 0), (1, 1)], .5, linear=True) == pytest.approx(1/12)
    assert _crps_integral([(0, 0), (100, 1)], 50, linear=True) == pytest.approx(100/12)
    # Outcome beyond support must keep getting worse, not saturate.
    assert _crps_integral([(0, 0), (1, 1)], 3, linear=True) == pytest.approx(2+1/3)


def test_pmf_crps_matches_independent_expectation_identity():
    # CRPS = E|X-y| - .5 E|X-X'|, independent finite sum reference.
    atoms = [(0, .2), (3, .5), (10, .3)]
    points = [(0, .2), (3, .7), (10, 1)]
    for y in [-5, 0, 1.5, 8, 20]:
        reference = sum(p*abs(x-y) for x,p in atoms) - .5*sum(p*q*abs(x-z) for x,p in atoms for z,q in atoms)
        assert _crps_discrete(points, y) == pytest.approx(reference)


def test_crossed_cdf_is_rejected():
    from forecasting.models import ValidationError
    with pytest.raises(ValidationError, match='monotone'):
        _crps_integral([(0, .9), (1, .1)], .5, linear=True)


def test_standard_deviation_alias_is_scored(tmp_path):
    ledger = _ledger(tmp_path)
    result = ledger._crps_score({'mean': 1250, 'standard_deviation': 22}, 1250, OutcomeSpace(type='numeric'))
    assert result['score_rule'] == 'crps_gaussian'
    assert result['proper_score'] == pytest.approx(22*.23369497725510913)


def test_negative_cdf_threshold_retains_sign():
    assert _crps_cdf_points({'p_below_-5': .2, 'p_below_-1_5': .6}) == [(-5, .2), (-1.5, .6)]


def test_version_migration_preserves_score_and_invalidates_derived_learning(tmp_path):
    ledger = _ledger(tmp_path)
    question = ledger.create_question(title='What value will the official report publish?', resolution_criteria='Resolved to the numeric value published in the official report at the resolution time.', outcome_space=OutcomeSpace(type='distribution', units='percent'))
    ledger.create_snapshot(question_id=question.id, probability_or_distribution={'mean': 3.9, 'sd': .35, 'cdf_3': .1, 'cdf_5': .9}, rationale='Frozen predictive CDF')
    ledger.resolve_question(question_id=question.id, outcome=4.2)
    old = ledger.get_current_score(question.id)
    with ledger._connect() as conn:
        conn.execute("UPDATE score_records SET score_rule='crps_discrete_cdf',proper_score=.38 WHERE id=?", (old.id,))
    old_pm = ledger.create_postmortem(question_id=question.id, summary='Based on old scoring convention')
    report = ledger.backfill_crps_scores(dry_run=False)
    detail = next(d for d in report['details'] if d['question_id'] == question.id)
    assert detail['action'] == 'rescored'
    assert ledger.get_score(old.id).invalidated_by_correction_id == detail['correction_id']
    assert ledger.get_current_score(question.id).id != old.id
    assert detail['postmortem_id'] != old_pm['id']
    with ledger._connect() as conn:
        row = conn.execute('SELECT * FROM postmortems WHERE id=?', (old_pm['id'],)).fetchone()
        assert row['invalidated_by_correction_id'] == detail['correction_id']
    assert ledger.backfill_crps_scores(dry_run=False)['counts']['rescored'] == 0
