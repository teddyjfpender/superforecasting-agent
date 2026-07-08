"""BLF A4 — hierarchical Platt calibration (per-cohort intercept offsets).

Covers the whole seam:

  * fit recovery on synthetic skewed cohorts — a per-cohort intercept beats the
    single global Platt map on HELD-OUT Brier exactly where base-rate skew exists;
  * the small-cohort fallback (below the stated n a cohort shares the global map);
  * provenance — every calibrated output records which ``delta_s`` applied, at the
    model level AND on the panel commit;
  * the P2.3 extremization guards apply UNCHANGED to the fitted slope;
  * the read-only validation verb (global vs hierarchical held-out Brier);
  * activation is DEFAULT-OFF (identity no-op) behind the same flag pattern as
    the sqrt(3) slope.
"""

from __future__ import annotations

import math
import random

import pytest

from forecasting import ForecastLedger
from forecasting.bayes_toolkit import inv_logit, logit, platt_scale
from forecasting.calibration_bias import Observation, extremization_alpha_gate
from forecasting.hierarchical_calibration import (
    DEFAULT_MIN_COHORT_N,
    CohortObservation,
    HierarchicalPlattModel,
    fit_hierarchical_platt,
    validate_hierarchical_calibration,
)
from forecasting.models import OutcomeSpace
from forecasting.panel import aggregate_panel_estimates


# ── synthetic generators ─────────────────────────────────────────────────────


def _skewed_rows(cohort: str, delta: float, n: int, *, seed: int) -> list[CohortObservation]:
    """Rows drawn from the true model ``q = sigma(logit(p) + delta)`` — a cohort
    whose base rate is shifted by ``delta`` from the raw forecast."""

    rng = random.Random(seed)
    rows: list[CohortObservation] = []
    for _ in range(n):
        p = rng.uniform(0.06, 0.94)
        q = inv_logit(logit(p) + delta)
        y = 1.0 if rng.random() < q else 0.0
        rows.append(CohortObservation(raw_p=p, outcome=y, cohort=cohort))
    return rows


# ── fit recovery ─────────────────────────────────────────────────────────────


def test_fit_recovers_opposite_signed_offsets():
    rows = _skewed_rows("live_calibration_eligible", 1.3, 300, seed=1) + _skewed_rows(
        "imported_baseline", -1.2, 300, seed=2
    )
    model = fit_hierarchical_platt(rows)
    assert model.converged
    # The two cohorts pull in opposite directions, matching the injected skew.
    assert model.deltas["live_calibration_eligible"] > 0.4
    assert model.deltas["imported_baseline"] < -0.4
    # Global slope stays sane (near the identity 1.0 the data was generated with).
    assert 0.6 < model.a < 1.6


def test_hierarchical_beats_global_on_held_out_where_skew_exists():
    rows = _skewed_rows("live_calibration_eligible", 1.3, 300, seed=3) + _skewed_rows(
        "imported_baseline", -1.2, 300, seed=4
    )
    report = validate_hierarchical_calibration(rows, folds=5)
    assert report["recommendation"] == "flip_on"
    # Hierarchical lowers the pooled held-out Brier.
    assert report["overall"]["brier_hierarchical"] < report["overall"]["brier_global"]
    # And it helps on BOTH offset-carrying cohorts.
    for name in ("live_calibration_eligible", "imported_baseline"):
        assert report["cohorts"][name]["hierarchical_helps"] is True
        assert report["cohorts"][name]["has_offset"] is True


def test_no_skew_does_not_recommend_flip():
    # Two cohorts with the SAME (zero) skew — a per-cohort intercept cannot help
    # out-of-sample, so the held-out gain is inside the noise and the verdict is
    # NEVER flip_on (marginal or keep_global). CV pins lambda at the grid ceiling.
    rows = _skewed_rows("live_calibration_eligible", 0.0, 300, seed=5) + _skewed_rows(
        "imported_baseline", 0.0, 300, seed=6
    )
    report = validate_hierarchical_calibration(rows, folds=5)
    assert report["recommendation"] in {"keep_global", "marginal"}
    assert report["recommendation"] != "flip_on"
    assert abs(report["overall"]["delta_brier_global_minus_hier"]) < 0.01
    # A sub-material positive gain is reported as marginal, never a flip.
    if report["overall"]["delta_brier_global_minus_hier"] > 0:
        assert report["recommendation"] == "marginal"
    # Zero skew ⇒ CV wants maximal shrinkage.
    assert report["lambda_at_ceiling"] is True


def test_material_bar_gates_the_flip_recommendation():
    # A gain that is positive but below the material bar must NOT flip; a clearly
    # material gain (strong skew) must. This is the discipline that kept the LIVE
    # ledger's +0.0003 held-out gain from being mis-sold as a flip.
    marginal = validate_hierarchical_calibration(
        _skewed_rows("a", 0.0, 250, seed=40) + _skewed_rows("b", 0.05, 250, seed=41),
        folds=5,
    )
    assert marginal["recommendation"] != "flip_on"
    material = validate_hierarchical_calibration(
        _skewed_rows("a", 1.4, 250, seed=42) + _skewed_rows("b", -1.3, 250, seed=43),
        folds=5,
    )
    assert material["recommendation"] == "flip_on"
    assert material["overall"]["delta_brier_global_minus_hier"] >= material["material_brier_delta"]


# ── small-cohort fallback ────────────────────────────────────────────────────


def test_small_cohort_gets_no_offset_and_falls_back():
    rows = (
        _skewed_rows("live_calibration_eligible", 1.2, 200, seed=7)
        + _skewed_rows("market_nightly", 1.2, DEFAULT_MIN_COHORT_N - 5, seed=8)
    )
    model = fit_hierarchical_platt(rows, min_cohort_n=DEFAULT_MIN_COHORT_N)
    assert "market_nightly" in model.small_cohorts
    assert "market_nightly" not in model.deltas
    delta, fell_back = model.delta_for("market_nightly")
    assert delta == 0.0 and fell_back is True
    # An unseen cohort at predict time also falls back to the global map.
    _, unseen_fallback = model.delta_for("never_seen")
    assert unseen_fallback is True


def test_min_cohort_n_threshold_is_configurable():
    rows = _skewed_rows("a", 1.0, 30, seed=9) + _skewed_rows("b", -1.0, 30, seed=10)
    # With a low floor both cohorts earn an offset...
    low = fit_hierarchical_platt(rows, min_cohort_n=20)
    assert set(low.deltas) == {"a", "b"}
    # ...with a high floor neither does (model reduces to a plain global Platt).
    high = fit_hierarchical_platt(rows, min_cohort_n=100)
    assert high.deltas == {}
    assert set(high.small_cohorts) == {"a", "b"}


# ── provenance ───────────────────────────────────────────────────────────────


def test_predict_records_which_delta_applied():
    rows = _skewed_rows("live_calibration_eligible", 1.3, 250, seed=11) + _skewed_rows(
        "imported_baseline", -1.2, 250, seed=12
    )
    model = fit_hierarchical_platt(rows)
    prov = model.predict(0.5, "imported_baseline")
    assert prov["cohort"] == "imported_baseline"
    assert prov["delta_s"] == model.deltas["imported_baseline"]
    assert prov["small_cohort_fallback"] is False
    # The calibrated number is exactly platt_scale with d = exp(b + delta_s).
    expected = platt_scale(0.5, alpha=model.a, d=math.exp(model.b + model.deltas["imported_baseline"]))
    assert prov["probability"] == pytest.approx(expected)


def test_panel_records_cohort_provenance_when_intercept_applies():
    est = [{"probability": p} for p in (0.2, 0.4, 0.5, 0.6, 0.8)]
    prov = {
        "cohort": "imported_baseline",
        "delta_s": -1.1,
        "intercept_b": 0.05,
        "slope_a": 1.1,
        "small_cohort_fallback": False,
    }
    agg = aggregate_panel_estimates(
        est,
        method="log_odds_pool",
        trim=0,
        alpha_extremize=1.1,
        platt_d=math.exp(0.05 - 1.1),
        calibration_provenance=prov,
    )
    assert agg.spread["calibration_cohort"] == "imported_baseline"
    assert agg.spread["calibration_delta_s"] == -1.1
    assert agg.spread["hierarchical_calibration_applied"] is True
    payload = agg.to_dict()
    assert payload["calibration_provenance"]["cohort"] == "imported_baseline"
    assert "applied_platt_d" in payload


# ── byte-identical / activation default-OFF ──────────────────────────────────


def test_panel_default_is_byte_identical_with_new_params():
    # The new platt_d / provenance params default to the identity: an un-configured
    # panel is byte-for-byte the prior bare pool, with no new markers.
    est = [{"probability": p} for p in (0.2, 0.4, 0.5, 0.6, 0.8)]
    from forecasting.bayes_toolkit import log_odds_pool

    agg = aggregate_panel_estimates(est, method="log_odds_pool", trim=0)
    assert agg.aggregate_probability == log_odds_pool([e["probability"] for e in est], [1.0] * 5)
    assert agg.pre_extremize_probability is None
    assert agg.applied_platt_d == 1.0
    assert agg.calibration_provenance is None
    assert agg.spread["terminal_calibration_applied"] is False
    payload = agg.to_dict()
    assert "applied_platt_d" not in payload
    assert "calibration_provenance" not in payload


def test_activation_flag_defaults_off_in_registry():
    from forecasting.appconfig import get_config

    key = get_config().registry["FORECAST_HIERARCHICAL_CALIBRATION"]
    assert key.type == "bool"
    assert key.default is False


# ── ledger integration: rows, validation verb, derivation ────────────────────


def _seed(ledger: ForecastLedger, origin: str, delta: float, n: int, *, seed: int) -> None:
    rng = random.Random(seed)
    for i in range(n):
        p = rng.uniform(0.06, 0.94)
        q = inv_logit(logit(p) + delta)
        outcome = "yes" if rng.random() < q else "no"
        question = ledger.create_question(
            title=f"{origin} {i}",
            resolution_criteria=(
                "Resolves YES if the stated event occurs by the deadline per the "
                "official source, else NO."
            ),
            outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
        )
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=p,
            rationale="Binary forecast.",
            forecast_origin=origin,
            calibration_eligible=True,
        )
        ledger.resolve_question(question_id=question.id, outcome=outcome)


def test_ledger_rows_are_tagged_by_scoreboard_cohort(tmp_path):
    ledger = ForecastLedger(tmp_path / "hier.db")
    _seed(ledger, "live", 1.2, 60, seed=21)
    _seed(ledger, "imported_baseline", -1.1, 60, seed=22)
    rows = ledger.hierarchical_calibration_rows()
    cohorts = {r.cohort for r in rows}
    assert cohorts == {"live_calibration_eligible", "imported_baseline"}
    assert len(rows) == 120


def test_validation_verb_reads_only_and_reports_per_cohort(tmp_path):
    ledger = ForecastLedger(tmp_path / "hier.db")
    _seed(ledger, "live", 1.3, 90, seed=23)
    _seed(ledger, "imported_baseline", -1.2, 90, seed=24)
    before = ledger.cohort_scoreboard()
    report = ledger.validate_hierarchical_calibration(folds=5)
    # Read-only: the scoreboard is untouched.
    assert ledger.cohort_scoreboard() == before
    assert report["recommendation"] == "flip_on"
    assert set(report["cohorts"]) == {"live_calibration_eligible", "imported_baseline"}
    assert report["overall"]["brier_hierarchical"] < report["overall"]["brier_global"]


def test_derivation_is_identity_when_flag_off(tmp_path):
    ledger = ForecastLedger(tmp_path / "hier.db")
    _seed(ledger, "live", 1.3, 90, seed=25)
    _seed(ledger, "imported_baseline", -1.2, 90, seed=26)

    class _Q:
        domain = None

        class outcome_space:
            type = "binary"

    res = ledger.derive_cohort_calibration(_Q())  # flag unset ⇒ default off
    assert res["active"] is False
    assert res["alpha"] == 1.0
    assert res["platt_d"] == 1.0
    assert res["delta_s"] == 0.0


def test_derivation_applies_offset_when_activated(tmp_path):
    ledger = ForecastLedger(tmp_path / "hier.db")
    _seed(ledger, "live", 1.3, 90, seed=27)
    _seed(ledger, "imported_baseline", -1.2, 90, seed=28)

    class _Q:
        domain = None

        class outcome_space:
            type = "binary"

    on = ledger.derive_cohort_calibration(_Q(), forecast_origin="imported_baseline", activated=True)
    assert on["active"] is True
    assert on["cohort"] == "imported_baseline"
    # imported_baseline was seeded with a NEGATIVE skew ⇒ negative offset ⇒ d < 1.
    assert on["delta_s"] < 0
    assert on["platt_d"] < 1.0


def test_derivation_routes_slope_through_p23_guard_unchanged(tmp_path):
    ledger = ForecastLedger(tmp_path / "hier.db")
    _seed(ledger, "live", 1.3, 120, seed=29)
    _seed(ledger, "imported_baseline", -1.2, 120, seed=30)

    class _Q:
        domain = None

        class outcome_space:
            type = "binary"

    model = ledger.fit_hierarchical_calibration()
    obs = ledger._bias_observations(domain=None, forecast_origin="live")
    expected_alpha = float(extremization_alpha_gate(model.a, obs)["allowed_alpha"])
    on = ledger.derive_cohort_calibration(_Q(), forecast_origin="live", activated=True)
    # The derivation's slope is EXACTLY the P2.3 gate's allowed slope — the guard
    # is applied unchanged (it is the same function the sqrt(3) slope uses).
    assert on["alpha"] == pytest.approx(expected_alpha)


def test_p23_guard_still_clamps_wrong_sided_extremization():
    # The guard the derivation relies on is intact: an alpha>1 on a scope that is
    # NOT under-confident on its leaned side is forced back to the identity.
    wrong_sided = [Observation(p_yes=0.8, outcome=0.0) for _ in range(40)]
    verdict = extremization_alpha_gate(math.sqrt(3.0), wrong_sided)
    assert verdict["permitted"] is False
    assert verdict["allowed_alpha"] == 1.0
