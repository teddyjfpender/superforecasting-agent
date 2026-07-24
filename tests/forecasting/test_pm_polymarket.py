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


def test_text_query_uses_full_catalog_search():
    """A query hits Gamma's /public-search (full catalog), not a filter over
    the one top-volume page — with fail-open fallback to the page filter."""
    from tests.forecasting.pm_helpers import RecordedFetch, load_fixture
    from forecasting.pm.polymarket import PolymarketClient

    ev = load_fixture("polymarket_event_categorical.json")
    fetch = RecordedFetch({
        "/public-search?": {"events": [ev], "pagination": {}},
        "/events?": [],  # the page path would return NOTHING for this query
    })
    client = PolymarketClient(fetch=fetch)
    found = client.list_events(query="israel", limit=10)
    assert len(found) == 1, "search must come from the search endpoint"
    assert any("/public-search?" in url for url in fetch.calls)

    # Fail-open: search endpoint erroring falls back to the page filter.
    def _failing(url, **kw):
        if "/public-search" in url:
            raise OSError("search down")
        return [ev]

    client2 = PolymarketClient(fetch=_failing)
    found2 = client2.list_events(query=ev["title"][:8].lower(), limit=10)
    assert len(found2) == 1


def test_catalog_keyset_paginates_and_indexes_child_markets():
    event = load_fixture("polymarket_event_categorical.json")
    second = {**event, "id": "second", "slug": "second-event", "title": "Second event"}
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return (
            {"events": [second], "next_cursor": ""}
            if "after_cursor=next" in url
            else {"events": [event], "next_cursor": "next"}
        )

    client = poly.PolymarketClient(fetch=fetch)
    rows = client.catalog_events()
    assert [row["event_id"] for row in rows] == [str(event["id"]), "second"]
    assert len(calls) == 2 and all("/events/keyset?" in url for url in calls)
    assert all("closed=false" in url for url in calls)
    assert rows[0]["market_count"] == len(event["markets"])
    assert event["markets"][0]["question"].casefold() in rows[0]["search"]


def test_dead_placeholder_market_yields_no_estimate():
    """The RFK dead-twin RAW shape, straight through the parser: no bid, a lone
    98c ask, placeholder outcomePrices [0.49, 0.51], zero volume. Without the
    volume gate the outcomePrices fallback resurrects a fabricated ~49%."""
    from forecasting.pm.polymarket import parse_market

    dead = parse_market({
        "conditionId": "0xdead",
        "groupItemTitle": "Robert F. Kennedy Jr.",
        "question": "Will RFK Jr. win?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.49", "0.51"]',
        "bestBid": None,
        "bestAsk": 0.98,
        "lastTradePrice": None,
        "volumeNum": 0,
    })
    assert dead.last_price is None
    assert dead.yes_mid is None, f"dead market must have NO estimate, got {dead.yes_mid}"

    # The same shape WITH real volume keeps the outcomePrices last-trade proxy.
    traded = parse_market({
        "conditionId": "0xlive",
        "groupItemTitle": "X",
        "question": "q",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0.0085", "0.9915"]',
        "bestBid": None,
        "bestAsk": None,
        "lastTradePrice": None,
        "volumeNum": 250000,
    })
    assert traded.yes_mid == 0.0085


def test_closed_child_market_uses_terminal_outcome_price_never_last_trade():
    """The Peru case, raw: a CLOSED child (eliminated -> resolved NO) with
    outcomePrices ["0","1"] but lastTradePrice=1 (the NO-side redemption print)
    and a junk leftover 0.1c ask. YES must read 0 — never 100%."""
    from forecasting.pm.polymarket import parse_market

    peru = parse_market({
        "conditionId": "0xperu",
        "groupItemTitle": "Peru",
        "question": "Will Peru win the 2026 FIFA World Cup?",
        "outcomes": '["Yes", "No"]',
        "outcomePrices": '["0", "1"]',
        "bestBid": None,
        "bestAsk": 0.001,
        "lastTradePrice": 1,
        "volumeNum": 264589.5,
        "closed": True,
    })
    assert peru.yes_mid == 0.0, f"resolved-NO must read 0, got {peru.yes_mid}"
    assert peru.yes_bid is None and peru.yes_ask is None, "closed books are void"

    # The mirror: a closed resolved-YES child reads 1.0.
    winner = parse_market({
        "conditionId": "0xwin", "groupItemTitle": "Winner", "question": "q",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["1", "0"]',
        "bestBid": None, "bestAsk": None, "lastTradePrice": 0,
        "volumeNum": 1000.0, "closed": True,
    })
    assert winner.yes_mid == 1.0

    # OPEN markets: the YES-oriented outcome price beats lastTradePrice.
    putin = parse_market({
        "conditionId": "0xputin", "groupItemTitle": "Yes", "question": "q",
        "outcomes": '["Yes", "No"]', "outcomePrices": '["0.115", "0.885"]',
        "bestBid": 0.11, "bestAsk": 0.12, "lastTradePrice": 0.12,
        "volumeNum": 14558380.0, "closed": False,
    })
    assert putin.yes_mid is not None and abs(putin.yes_mid - 0.115) < 1e-9
