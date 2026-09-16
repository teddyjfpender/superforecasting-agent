"""Comparison policies are about source periods, not chart length or nonzero bias."""

from datetime import date, timedelta

import pytest

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.model import DatedValue, SeriesRef
from forecasting.marketdata.parsing import observation_quote
from forecasting.marketdata.provider import ProviderFailure
from forecasting.marketdata.providers.bcb import BcbProvider


def points(values):
    start = date(2020, 1, 1)
    return [
        DatedValue(
            period_start=(start + timedelta(days=i)).isoformat(),
            period_end=(start + timedelta(days=i)).isoformat(),
            value=value,
        )
        for i, value in enumerate(values)
    ]


REF = SeriesRef(provider="test", symbol="sparse")


def test_sparse_comparison_is_independent_of_chart_window():
    q = observation_quote(REF, points([10] + [None] * 400 + [12]))
    assert q.change == 2
    assert q.comparison.previous_value == 10
    assert q.comparison.current_value == 12
    assert len(q.history) <= 36


def test_flat_releases_remain_flat_and_expose_last_movement_separately():
    q = observation_quote(REF, points([10, 12, 12, 12]))
    assert q.change == 0
    assert q.comparison.previous_period == "2020-01-03"
    assert q.last_movement.previous_value == 10
    assert q.last_movement.current_period == "2020-01-02"


def test_policy_transition_uses_first_new_rate_not_latest_repeated_stamp():
    q = observation_quote(REF, points([10, 12] + [12] * 400), basis="last_transition")
    assert q.change == 2
    assert q.comparison.basis == "last_transition"
    assert q.comparison.current_period == "2020-01-02"
    assert len(q.dated_history) <= 36


def test_no_transition_is_unavailable_and_zero_baseline_never_divides():
    assert (
        observation_quote(REF, points([12] * 50), basis="last_transition").change
        is None
    )
    q = observation_quote(REF, points([0, 2]))
    assert q.change == 2
    assert q.changePct is None


def test_conflicting_periods_cannot_supply_a_comparison():
    with pytest.raises(ProviderFailure):
        observation_quote(REF, points([1]) + points([2]))


def test_bcb_expands_history_only_when_prior_transition_is_missing():
    entry = next(e for e in load_catalog().series if e.id == "bcb:432")
    calls = []

    def fetch(url):
        calls.append(url)
        return ([{"data": "01/01/2020", "valor": "10"}] if len(calls) == 2 else []) + [
            {"data": "02/01/2020", "valor": "12"},
            {"data": "03/01/2020", "valor": "12"},
        ]

    q = BcbProvider(get_json=fetch, clock=lambda: date(2026, 9, 15)).fetch([
        SeriesRef(provider="bcb", symbol="432", catalog_id=entry.id)
    ])[0]
    assert "ultimos/20?" in calls[0]
    assert "dataInicial=" in calls[1]
    assert q.change == 2
    assert q.comparison.current_period == "2020-01-02"


def test_fred_keyed_backfills_missing_observations_beyond_display_window():
    from forecasting.marketdata.providers.fred import FredProvider

    today = date.today()
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        rows = [{"date": today.isoformat(), "value": "12"}]
        if len(calls) == 1:
            rows += [
                {"date": (today - timedelta(days=i)).isoformat(), "value": "."}
                for i in range(1, 30)
            ]
        else:
            rows += [{"date": (today - timedelta(days=300)).isoformat(), "value": "10"}]
        return {"observations": rows}

    q = FredProvider(get_json=fetch).fetch(
        [SeriesRef(provider="fred", symbol="SPARSE")], api_key="test-key"
    )[0]
    assert q.change == 2
    assert "limit=30" in calls[0]
    assert "limit=366" in calls[1]
    assert q.comparison.previous_period == (today - timedelta(days=300)).isoformat()


@pytest.mark.parametrize("failure", ["unavailable", "stale"])
def test_bcb_backfill_cannot_discard_or_replace_latest_measurement(failure):
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) > 1:
            if failure == "unavailable":
                raise ProviderFailure("unavailable", "history unavailable")
            return [{"data": "01/01/2020", "valor": "10"}]
        return [{"data": "02/01/2020", "valor": "12"}]

    q = BcbProvider(get_json=fetch).fetch([
        SeriesRef(provider="bcb", symbol="432", catalog_id="bcb:432")
    ])[0]
    assert q.value == 12
    assert q.change is None


def test_fred_backfill_failure_preserves_current_quote():
    from forecasting.marketdata.providers.fred import FredProvider

    today = date.today()
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        if len(calls) > 1:
            raise ProviderFailure("unavailable", "history unavailable")
        return {
            "observations": [
                {"date": (today - timedelta(days=i)).isoformat(), "value": "12"}
                for i in range(30)
            ]
        }

    q = FredProvider(get_json=fetch).fetch(
        [SeriesRef(provider="fred", symbol="FLAT")], api_key="test-key"
    )[0]
    assert q.value == 12
    assert q.change == 0


def test_monthly_fred_lag_uses_period_end_not_first_day():
    from forecasting.marketdata.providers.fred import _finalize
    q = _finalize(
        [('2026-04-01', 100), ('2026-05-01', 101), ('2026-06-01', 102)],
        SeriesRef(provider='fred', symbol='CSUSHPINSA', catalog_id='fred:CSUSHPINSA'),
        as_of_reference=date(2026, 9, 16),
    )
    assert q.value == 102 and q.change == 1
    assert q.dated_history[-1].period_end == '2026-06-30'
    stale = _finalize(
        [('2025-04-01', 100), ('2025-05-01', 101), ('2025-06-01', 102)],
        SeriesRef(provider='fred', symbol='CSUSHPINSA', catalog_id='fred:CSUSHPINSA'),
        as_of_reference=date(2026, 9, 16),
    )
    assert stale.value is None and stale.change is None
