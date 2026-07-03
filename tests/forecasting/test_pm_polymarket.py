"""Polymarket client + parser tests (recorded fixtures, no network)."""

from __future__ import annotations

from forecasting.pm import polymarket as poly
from tests.forecasting.pm_helpers import RecordedFetch, load_fixture


def test_parse_categorical_event_nested_markets():
    ev = poly.parse_event(load_fixture("polymarket_event_categorical.json"))
    assert ev.venue == "polymarket"
    assert ev.mutually_exclusive is True  # negRisk categorical
    assert not ev.is_binary and len(ev.markets) >= 3
    first = ev.markets[0]
    # groupItemTitle becomes the outcome label; clobTokenIds parsed from the
    # JSON-*string* Polymarket serialises.
    assert first.label and first.token_ids and len(first.token_ids) == 2
    assert first.yes_bid is not None and first.yes_ask is not None
    assert ev.url and ev.url.startswith("https://polymarket.com/event/")


def test_parse_binary_event_single_market():
    ev = poly.parse_event(load_fixture("polymarket_event_binary.json"))
    assert ev.is_binary and len(ev.markets) == 1
    m = ev.markets[0]
    assert 0.0 <= (m.yes_mid or 0.0) <= 1.0


def test_parse_book_sorts_and_derives_best():
    book = poly.parse_book(load_fixture("polymarket_book.json"), market_id="tok")
    assert book.market_id == "tok"
    # bids high→low, asks low→high
    assert all(book.bids[i].price >= book.bids[i + 1].price for i in range(len(book.bids) - 1))
    assert all(book.asks[i].price <= book.asks[i + 1].price for i in range(len(book.asks) - 1))
    assert book.best_bid is not None and book.best_ask is not None
    assert book.best_bid <= book.best_ask


def test_parse_midpoint_and_history():
    assert poly.parse_midpoint(load_fixture("polymarket_midpoint.json")) == 0.1285
    hist = poly.parse_prices_history(load_fixture("polymarket_prices_history.json"))
    assert hist and all(0.0 <= p.p <= 1.0 for p in hist)
    assert all(hist[i].ts <= hist[i + 1].ts for i in range(len(hist) - 1))


def test_client_builds_urls_and_parses():
    fetch = RecordedFetch(
        {
            "/events?": load_fixture("polymarket_event_categorical.json"),
            "/book?": load_fixture("polymarket_book.json"),
            "/midpoint?": load_fixture("polymarket_midpoint.json"),
            "/prices-history?": load_fixture("polymarket_prices_history.json"),
        }
    )
    # parse_events accepts a single event object wrapped as list by the fetch;
    # here the list endpoint returns the raw categorical event dict, which
    # parse_events ignores unless it's a list — so feed a list.
    fetch._routes["/events?"] = [load_fixture("polymarket_event_categorical.json")]
    client = poly.PolymarketClient(fetch=fetch)
    events = client.list_events(limit=10)
    assert len(events) == 1 and events[0].venue == "polymarket"
    book = client.book("tok123")
    assert book.best_bid is not None
    assert client.midpoint("tok123") == 0.1285
    assert client.prices_history("tok123")
    # one call per endpoint — no hidden fan-out
    assert sum("/events?" in c for c in fetch.calls) == 1
    assert any("token_id=tok123" in c for c in fetch.calls)
