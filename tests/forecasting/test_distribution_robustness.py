from __future__ import annotations

import pytest

from forecasting import ForecastLedger
from forecasting.dashboard import _distribution_view
from forecasting.models import ValidationError

CRITERIA = "Resolves to the official value reported by the named source on the close date."


# ── Display: quantile distributions must render as intervals ──────────────────

def test_distribution_view_maps_quantiles_to_intervals():
    # The shape the agent actually produced for BTC etc. (q05..q95) — must surface
    # median + 50%/90% intervals + a derived sd, not just a bare mean.
    view = _distribution_view(
        {"mean": 73000, "q05": 50000, "q10": 58000, "q25": 65000, "q50": 71500,
         "q75": 80000, "q90": 90000, "q95": 105000}
    )
    assert view is not None
    assert view["median"] == 71500
    assert view["ci50"] == [65000.0, 75000.0] or view["ci50"] == [65000, 80000]
    assert view["ci90"][0] == 50000 and view["ci90"][1] == 105000
    assert view["sd"] is not None and view["sd"] > 0


def test_distribution_view_quantiles_in_unit_interval_are_not_pmf():
    # CPI-style percent quantiles all land in [0,1]; they must NOT be mistaken for
    # a probability-mass function.
    view = _distribution_view({"mean": 0.36, "q05": 0.05, "q25": 0.2, "q50": 0.35, "q75": 0.5, "q95": 0.75})
    assert view is not None
    assert view["pmf"] is None
    assert view["ci90"] == [0.05, 0.75]
    assert view["median"] == 0.35


def test_distribution_view_partial_quantiles_derive_sd_and_interval():
    # Starship: q10..q90 (no q05/q95) — sd is derived and the 90% interval falls
    # back to mean +/- z*sd.
    view = _distribution_view({"mean": 70, "q10": 25, "q25": 36, "q50": 58, "q75": 88, "q90": 130})
    assert view is not None
    assert view["ci50"] == [36, 88]
    assert view["sd"] is not None
    assert view["ci90"] is not None and view["ci90"][0] < view["ci90"][1]


def test_distribution_view_count_pmf_derives_interval_from_cdf():
    # Storms: p0..p6_plus is a count PMF. It must render as a PMF AND yield a
    # median / 90% interval / sd from the discrete CDF, so the chart band is a
    # real count spread (e.g. [0,3]) instead of a degenerate confidence band.
    view = _distribution_view(
        {"mean": 1.2, "p0": 0.3, "p1": 0.36, "p2": 0.22, "p3": 0.09, "p4": 0.025, "p5": 0.004, "p6_plus": 0.001}
    )
    assert view is not None
    assert view["pmf"] is not None and len(view["pmf"]) >= 2
    assert view["median"] == 1.0
    assert view["ci90"] == [0.0, 3.0]
    assert view["sd"] is not None and view["sd"] > 0.5


def test_categorical_pmf_is_not_treated_as_a_count(tmp_path):
    # A categorical PMF (party names) must NOT get a count interval derived.
    view = _distribution_view({"Republican candidate": 0.59, "Democratic candidate": 0.4, "Other": 0.01})
    # No mean recoverable from a pure categorical PMF, but if a view is produced
    # it must not invent a numeric count interval.
    if view is not None:
        assert view["ci90"] is None


# ── Input: the validator must be tolerant + give actionable errors ────────────

def test_distribution_validator_coerces_quoted_numbers(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    q = ledger.create_question(title="CPI MoM?", resolution_criteria=CRITERIA, domain="macro", topics=["cpi"])
    snap = ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution={"mean": "0.36", "q05": "0.05", "q50": "0.35", "q95": "0.75"},
        rationale="r",
    )
    assert snap.probability_or_distribution == {"mean": 0.36, "q05": 0.05, "q50": 0.35, "q95": 0.75}


def test_distribution_validator_drops_null_entries(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    q = ledger.create_question(title="X?", resolution_criteria=CRITERIA, domain="macro", topics=["x"])
    snap = ledger.create_snapshot(
        question_id=q.id, probability_or_distribution={"mean": 0.5, "q10": None, "q90": 0.8}, rationale="r"
    )
    assert "q10" not in snap.probability_or_distribution
    assert snap.probability_or_distribution == {"mean": 0.5, "q90": 0.8}


def test_distribution_validator_names_the_offending_key(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    q = ledger.create_question(title="X?", resolution_criteria=CRITERIA, domain="macro", topics=["x"])
    with pytest.raises(ValidationError) as exc:
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution={"mean": 0.5, "note": "high vol"}, rationale="r"
        )
    assert "note" in str(exc.value)


def test_distribution_validator_rejects_all_null(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    q = ledger.create_question(title="X?", resolution_criteria=CRITERIA, domain="macro", topics=["x"])
    with pytest.raises(ValidationError):
        ledger.create_snapshot(question_id=q.id, probability_or_distribution={"q05": None}, rationale="r")
