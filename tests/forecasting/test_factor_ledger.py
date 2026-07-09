"""Factor layer integration: a factor (thesis with aggregation='factor') folds a
weighted basket of constituent return distributions into a portfolio return +
volatility + downside. Pure portfolio math is covered in test_factor_aggregate.py."""

from __future__ import annotations

from forecasting import ForecastLedger
from forecasting.dashboard import build_workspace_payload
from forecasting.models import OutcomeSpace

CRITERIA = "Resolves to the official value reported by the named source on the close date."
FACTOR_CRITERIA = "Portfolio return of the weighted constituent basket; reviewed as constituents update."


def _return_q(ledger, title, mean, sd):
    q = ledger.create_question(
        title=title, resolution_criteria=CRITERIA, domain="markets",
        outcome_space=OutcomeSpace(type="distribution", units="return_frac"),
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution={"mean": mean, "sd": sd, "q05": mean - 1.645 * sd, "q50": mean, "q95": mean + 1.645 * sd},
        rationale="seed",
    )
    return q


def _factor(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    nbis = _return_q(ledger, "NBIS 12m total return?", 0.35, 0.45)
    be = _return_q(ledger, "BE 12m total return?", 0.20, 0.55)
    factor = ledger.create_question(
        title="AI Infrastructure Factor (12m)", resolution_criteria=FACTOR_CRITERIA, domain="markets",
        outcome_space=OutcomeSpace(type="thesis", units="return_frac"), metadata={"aggregation": "factor"},
    )
    return ledger, factor, nbis, be


def test_factor_is_thesis_but_distinct(tmp_path):
    ledger, factor, *_ = _factor(tmp_path)
    assert ledger.is_thesis(factor) is True
    assert ledger.is_factor(factor) is True
    assert ledger.is_factor(factor.id) is True


def test_factor_aggregates_basket_return(tmp_path):
    ledger, factor, nbis, be = _factor(tmp_path)
    ledger.add_thesis_member(factor.id, nbis.id, direction="support", weight=0.6)
    ledger.add_thesis_member(factor.id, be.id, direction="support", weight=0.4)
    result = ledger.aggregate_thesis(factor.id)
    assert result["is_factor"] is True
    payload = result["payload"]
    # mean = 0.6*0.35 + 0.4*0.20 = 0.29
    assert abs(payload["factor_mean"] - 0.29) < 1e-6
    assert payload["factor_sd"] > 0
    assert payload["q05"] < payload["factor_mean"] < payload["q95"]
    assert payload["cvar"] <= payload["downside"] <= payload["factor_mean"]
    snap = ledger.get_current_snapshot(factor.id)
    assert snap.method == "factor_aggregate"
    assert snap.calibration_eligible is False


def test_factor_lint_does_not_require_thesis_event(tmp_path):
    from forecasting.hooks import lint_forecast

    ledger, factor, nbis, be = _factor(tmp_path)
    ledger.add_thesis_member(factor.id, nbis.id, direction="support", weight=0.6)
    ledger.add_thesis_member(factor.id, be.id, direction="support", weight=0.4)
    ledger.aggregate_thesis(factor.id)

    report = lint_forecast(ledger, factor.id)
    assert report is not None
    assert "event_band_earned" not in {v.rule_id for v in report.verdicts}


def test_short_constituent_flips_sign(tmp_path):
    ledger, factor, nbis, be = _factor(tmp_path)
    ledger.add_thesis_member(factor.id, nbis.id, direction="support", weight=1.0)  # long +0.35
    ledger.add_thesis_member(factor.id, be.id, direction="inverted", weight=1.0)   # short -0.20
    payload = ledger.aggregate_thesis(factor.id, commit=False)["payload"]
    # mean = 0.5*0.35 + 0.5*(-0.20) = 0.075
    assert abs(payload["factor_mean"] - 0.075) < 1e-6


def test_factor_surfaces_in_workspace_payload(tmp_path):
    ledger, factor, nbis, be = _factor(tmp_path)
    ledger.add_thesis_member(factor.id, nbis.id, direction="support", weight=0.6)
    ledger.add_thesis_member(factor.id, be.id, direction="support", weight=0.4)
    ledger.aggregate_thesis(factor.id)
    payload = build_workspace_payload(ledger=ledger)
    assert payload["factor_count"] == 1
    assert payload["thesis_count"] == 0  # a factor is not counted as a health thesis
    fac = payload["factors"][0]
    assert fac["id"] == factor.id
    assert abs(fac["mean"] - 0.29) < 1e-6
    assert len(fac["constituents"]) == 2
    assert {c["direction"] for c in fac["constituents"]} == {"long"}


def test_cron_aggregate_all_includes_factors(tmp_path):
    ledger, factor, nbis, be = _factor(tmp_path)
    ledger.add_thesis_member(factor.id, nbis.id, direction="support", weight=1.0)
    assert ledger.get_current_snapshot(factor.id) is None
    summary = ledger.aggregate_all_theses()
    assert summary["count"] == 1
    assert ledger.get_current_snapshot(factor.id) is not None  # the daily sweep aggregates factors too


def test_factor_with_missing_constituents_is_withheld(tmp_path):
    ledger, factor, *_ = _factor(tmp_path)
    empty = ledger.create_question(
        title="Unforecast return?", resolution_criteria=CRITERIA, domain="markets",
        outcome_space=OutcomeSpace(type="distribution", units="return_frac"),
    )
    ledger.add_thesis_member(factor.id, empty.id, direction="support", weight=1.0)
    result = ledger.aggregate_thesis(factor.id)
    assert result["payload"].get("factor_mean") is None
    assert result["snapshot_id"] is None
