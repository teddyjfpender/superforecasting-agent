"""The forecasting-uncertainty invariant: a distribution forecast's expected value
MUST lie inside its own confidence band. A point outside its band (the
disconnected-band bug) is never valid and must block at commit — previously this was
uncaught (assess_distribution checked ordering/nesting/range but not central-in-band)."""

from __future__ import annotations

import pytest

from forecasting.hooks.distribution import assess_distribution
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

NCRIT = "Resolves to the official reported numeric value at the close date."


def test_central_outside_band_is_flagged_not_well_formed():
    a = assess_distribution({"mean": 80, "q05": 10, "q95": 30}, outcome_type="distribution", bounds=[0, 100], units="pct")
    assert a.central_within is False and a.well_formed is False
    assert any("OUTSIDE its band" in i for i in a.issues)


def test_central_inside_band_is_well_formed():
    a = assess_distribution({"mean": 50, "q05": 35, "q95": 65}, outcome_type="distribution", bounds=[0, 100], units="pct")
    assert a.central_within is True and a.well_formed is True


def _ledger(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "bi.db"))
    lg.initialize_schema()
    return lg


def _num_q(lg):
    return lg.create_question(
        title="What value will the metric reach at the close date per the source?",
        resolution_criteria=NCRIT, domain="econ",
        outcome_space=OutcomeSpace(type="distribution", choices=[], units="pct", bounds=[0, 100]),
    )


def test_mean_outside_band_blocks_live_commit(tmp_path):
    lg = _ledger(tmp_path)
    q = _num_q(lg)
    with pytest.raises(Exception):  # SaturationBlocked — point outside its band
        lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 80, "q05": 10, "q95": 30}, rationale="point outside band", forecast_origin="live")


def test_valid_distribution_commits_live(tmp_path):
    lg = _ledger(tmp_path)
    q = _num_q(lg)
    assert lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 50, "q05": 35, "q95": 65}, rationale="valid band", forecast_origin="live") is not None


def test_exploratory_bypasses_the_invariant(tmp_path):
    # The invariant is a LIVE gate; exploratory remains the relief valve.
    lg = _ledger(tmp_path)
    q = _num_q(lg)
    assert lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": 80, "q05": 10, "q95": 30}, rationale="exploratory", forecast_origin="exploratory") is not None
