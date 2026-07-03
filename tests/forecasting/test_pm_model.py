"""Model-layer tests: to_dict contracts and derived quote logic."""

from __future__ import annotations

import pytest

from forecasting.pm.model import (
    PMDistribution,
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
    PMOutcome,
)


def test_history_point_to_dict_rounds():
    assert PMHistoryPoint(ts=1700000000, p=0.123456).to_dict() == {
        "ts": 1700000000,
        "p": 0.1235,
    }


def test_market_yes_mid_prefers_quote_then_last():
    both = PMMarket(venue="x", market_id="m", label="Yes", question="q", yes_bid=0.4, yes_ask=0.6)
    assert both.yes_mid == 0.5
    # ONE-SIDED books are offers, not probabilities (the RFK 98%-vs-<1% catch):
    # bid-only / ask-only markets fall through to last trade, else None.
    bid_only = PMMarket(venue="x", market_id="m", label="Yes", question="q", yes_bid=0.4)
    assert bid_only.yes_mid is None
    ask_only = PMMarket(venue="x", market_id="m", label="Yes", question="q", yes_ask=0.98)
    assert ask_only.yes_mid is None
    ask_with_trade = PMMarket(
        venue="x", market_id="m", label="Yes", question="q", yes_ask=0.98, last_price=0.01
    )
    assert ask_with_trade.yes_mid == 0.01
    last = PMMarket(venue="x", market_id="m", label="Yes", question="q", last_price=0.7)
    assert last.yes_mid == 0.7
    empty = PMMarket(venue="x", market_id="m", label="Yes", question="q")
    assert empty.yes_mid is None


def test_orderbook_best_and_mid():
    book = PMOrderBook(
        venue="x",
        market_id="m",
        bids=(PMOrderLevel(0.40, 10), PMOrderLevel(0.39, 5)),
        asks=(PMOrderLevel(0.42, 8), PMOrderLevel(0.43, 3)),
        tick_size=0.01,
    )
    assert book.best_bid == 0.40
    assert book.best_ask == 0.42
    assert book.mid == pytest.approx(0.41)
    payload = book.to_dict()
    assert payload["best_bid"] == 0.4 and payload["mid"] == 0.41
    assert len(payload["bids"]) == 2


def test_event_is_binary_and_to_dict():
    m = PMMarket(venue="x", market_id="m", label="Yes", question="q", yes_bid=0.5, yes_ask=0.5)
    ev = PMEvent(venue="x", event_id="e", title="t", markets=(m,))
    assert ev.is_binary is True
    two = PMEvent(venue="x", event_id="e", title="t", markets=(m, m))
    assert two.is_binary is False
    d = ev.to_dict()
    assert d["is_binary"] is True and len(d["markets"]) == 1


def test_distribution_headline():
    outs = (
        PMOutcome(label="A", prob=0.6, raw_prob=0.55, market_id="a"),
        PMOutcome(label="B", prob=0.4, raw_prob=0.35, market_id="b"),
    )
    dist = PMDistribution(
        venue="x", event_id="e", title="t", outcomes=outs, total_volume=1234.5
    )
    head = dist.headline
    assert head["top_label"] == "A" and head["top_prob"] == 0.6 and head["n"] == 2
    assert dist.to_dict()["total_volume"] == 1234.5
