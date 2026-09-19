"""Display and ledger acquisition must agree on Kalshi price units."""

import pytest

from forecasting.models import ValidationError
from forecasting.pm.kalshi import parse_market
from forecasting.sources.kalshi_parsing import (
    _kalshi_market_from_payload,
    _kalshi_previous_yes_probability,
)
from forecasting.sources.kalshi_prices import kalshi_price


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("yes_bid", 1, 0.01),
        ("yes_bid_cents", "1", 0.01),
        ("yes_bid_dollars", "1.0000", 1.0),
        ("yes_bid", 100, 1.0),
        ("yes_bid", 0, 0.0),
        ("yes_bid_dollars", "0.0050", 0.005),
    ],
)
def test_display_and_evidence_use_declared_units(field, value, expected):
    raw = {"ticker": "TEST", "title": "Will it happen?", field: value}
    assert parse_market(raw).yes_bid == expected
    assert _kalshi_market_from_payload(raw).probability == expected


@pytest.mark.parametrize(
    "value", [True, False, -1, 2, float("nan"), float("inf"), "garbage", [], {}]
)
def test_invalid_authoritative_dollars_never_fall_back(value):
    raw = {
        "ticker": "TEST",
        "title": "Question?",
        "yes_bid_dollars": value,
        "yes_bid": 50,
    }
    for parser in (parse_market, _kalshi_market_from_payload):
        with pytest.raises(ValidationError, match="Kalshi price"):
            parser(raw)


@pytest.mark.parametrize("value", [-1, 101, True, "Infinity", "NaN", 10**400])
def test_invalid_cents_are_not_clamped(value):
    with pytest.raises(ValidationError, match="Kalshi price"):
        kalshi_price({"last_price": value}, "last_price")


def test_fixed_point_dollars_take_precedence_over_legacy_rounding():
    assert kalshi_price({"yes_bid_dollars": "0.0150", "yes_bid": 1}, "yes_bid") == 0.015


@pytest.mark.parametrize("payload", [{}, {"yes_bid": None}, {"yes_bid_dollars": ""}])
def test_absent_quote_remains_unavailable(payload):
    assert kalshi_price(payload, "yes_bid") is None


def test_historical_baseline_uses_the_same_units():
    assert _kalshi_previous_yes_probability({"previous_price": 1}) == 0.01
    assert (
        _kalshi_previous_yes_probability({"previous_yes_bid": 0, "previous_yes_ask": 2})
        == 0.01
    )
    with pytest.raises(ValidationError, match="Kalshi price"):
        _kalshi_previous_yes_probability({
            "previous_price_dollars": "2",
            "previous_yes_bid": 50,
        })
