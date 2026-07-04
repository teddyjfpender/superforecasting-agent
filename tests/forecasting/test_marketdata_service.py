"""MarketDataService: TTL + stale-while-revalidate cache and per-provider
failure isolation (Arc C1). No network — providers are stubs, clock/spawn
injected for determinism."""

from __future__ import annotations

import pytest

from forecasting.marketdata.model import Quote, SeriesRef
from forecasting.marketdata.service import MarketDataService


class _StubProvider:
    def __init__(self, name: str, *, needs_key: bool = False, raises: bool = False):
        self.name = name
        self.needs_key = needs_key
        self._raises = raises
        self.calls = 0
        self.last_key: str | None = None

    def fetch(self, series, *, api_key=None):
        self.calls += 1
        self.last_key = api_key
        if self._raises:
            raise RuntimeError(f"{self.name} down")
        return [
            Quote(
                symbol=s.symbol,
                provider=self.name,
                name=s.name,
                category=s.category,
                value=float(self.calls),  # value tracks fetch count → observe caching
                change=None,
                changePct=None,
                prevClose=None,
                asOf=0,
                unit=s.unit,
                history=[],
            )
            for s in series
        ]


def _ref(provider: str, symbol: str) -> SeriesRef:
    return SeriesRef(provider=provider, symbol=symbol, name=symbol)


def test_quotes_returns_one_per_series_across_providers():
    fx = _StubProvider("frankfurter")
    bea = _StubProvider("bea", needs_key=True)
    svc = MarketDataService(
        providers={"frankfurter": fx, "bea": bea},
        key_resolver=lambda name: "KEY" if name == "bea" else None,
        clock=lambda: 0.0,
    )
    quotes = svc.quotes([_ref("frankfurter", "EUR"), _ref("bea", "T20305")])
    by_provider = {q.provider for q in quotes}
    assert by_provider == {"frankfurter", "bea"}
    assert bea.last_key == "KEY"  # keyed provider got its key


def test_ttl_cache_serves_a_hit_without_refetching():
    now = {"t": 0.0}
    fx = _StubProvider("frankfurter")
    svc = MarketDataService(
        providers={"frankfurter": fx}, clock=lambda: now["t"], ttl=60.0, spawn=lambda fn: None
    )
    refs = [_ref("frankfurter", "EUR")]
    (q1,) = svc.quotes(refs)
    (q2,) = svc.quotes(refs)  # within TTL → cache hit, no second fetch
    assert fx.calls == 1
    assert q1.value == q2.value == 1.0


def test_stale_while_revalidate_serves_old_value_and_refreshes_in_band():
    now = {"t": 0.0}
    fx = _StubProvider("frankfurter")
    spawned: list = []
    svc = MarketDataService(
        providers={"frankfurter": fx},
        clock=lambda: now["t"],
        ttl=60.0,
        spawn=lambda fn: spawned.append(fn),  # capture, don't run
    )
    refs = [_ref("frankfurter", "EUR")]
    (first,) = svc.quotes(refs)
    assert first.value == 1.0
    now["t"] = 120.0  # past the TTL → stale
    (stale,) = svc.quotes(refs)
    assert stale.value == 1.0  # old value served immediately
    assert len(spawned) == 1  # a background refresh was scheduled
    spawned[0]()  # run it
    (fresh,) = svc.quotes(refs)
    assert fresh.value == 2.0  # refreshed value now served


def test_one_provider_down_never_blanks_the_tape():
    good = _StubProvider("frankfurter")
    bad = _StubProvider("bea", needs_key=True, raises=True)
    svc = MarketDataService(
        providers={"frankfurter": good, "bea": bad},
        key_resolver=lambda name: "KEY",
        clock=lambda: 0.0,
    )
    quotes = svc.quotes([_ref("frankfurter", "EUR"), _ref("bea", "T20305")])
    # The failing provider drops only ITS series; the healthy one still paints.
    assert [q.provider for q in quotes] == ["frankfurter"]


def test_keyed_provider_without_key_is_skipped_not_errored():
    bea = _StubProvider("bea", needs_key=True)
    svc = MarketDataService(
        providers={"bea": bea}, key_resolver=lambda name: None, clock=lambda: 0.0
    )
    assert svc.quotes([_ref("bea", "T20305")]) == []
    assert bea.calls == 0  # never even called without a key


def test_unknown_provider_yields_no_quotes():
    svc = MarketDataService(providers={}, clock=lambda: 0.0)
    assert svc.quotes([_ref("nope", "X")]) == []


# ── C2 service integration: the four new providers wired end-to-end ───────────


def test_default_providers_include_all_seven():
    from forecasting.marketdata.service import _default_providers

    assert set(_default_providers()) == {
        "frankfurter",
        "bea",
        "coingecko",
        "fred",
        "bls",
        "stooq",
        "yahoo",
    }


def test_service_routes_the_four_new_providers_with_real_parsers_no_network():
    """The service groups by provider and runs each REAL provider's parser off an
    injected getter — no network — proving the C2 wiring end-to-end."""

    from forecasting.marketdata.providers.bls import BlsProvider
    from forecasting.marketdata.providers.coingecko import CoingeckoProvider
    from forecasting.marketdata.providers.fred import FredProvider
    from forecasting.marketdata.providers.stooq import StooqProvider

    cg = CoingeckoProvider(get_json=lambda url, **kw: {"bitcoin": {"usd": 64239, "usd_24h_change": -1.05}})
    # No key resolved → FRED takes the keyless CSV path (get_text).
    fred = FredProvider(
        get_json=lambda url, **kw: {"observations": []},
        get_text=lambda url: "DATE,X\n2026-05-01,5.10\n2026-06-01,4.90\n",
    )
    bls = BlsProvider(
        get_json=lambda url, **kw: {"Results": {"series": [{"data": [{"period": "M05", "value": "320.1", "year": "2026"}]}]}}
    )
    stooq = StooqProvider(get_text=lambda url: "Date,Open,High,Low,Close,Volume\n2026-07-01,1,1,1,10.4,5\n2026-07-02,1,1,1,10.8,5\n")

    svc = MarketDataService(
        providers={"coingecko": cg, "fred": fred, "bls": bls, "stooq": stooq},
        key_resolver=lambda name: None,
        clock=lambda: 0.0,
    )
    quotes = svc.quotes(
        [_ref("coingecko", "bitcoin"), _ref("fred", "FEDFUNDS"), _ref("bls", "CUUR0000SA0"), _ref("stooq", "aapl.us")]
    )
    by = {q.provider: q for q in quotes}
    assert set(by) == {"coingecko", "fred", "bls", "stooq"}
    assert by["coingecko"].value == pytest.approx(64239)
    assert by["fred"].value == pytest.approx(4.90)  # keyless CSV path taken
    assert by["bls"].value == pytest.approx(320.1)
    assert by["stooq"].value == pytest.approx(10.8)


def test_service_isolates_a_new_provider_error_payload_as_null_never_zero():
    """An error/empty payload from a new provider is honest-null (THE LAW), and a
    healthy provider still paints — the tape never blanks."""

    from forecasting.marketdata.providers.coingecko import CoingeckoProvider
    from forecasting.marketdata.providers.stooq import StooqProvider

    cg = CoingeckoProvider(get_json=lambda url, **kw: {"status": {"error_code": 429}})  # error payload
    stooq = StooqProvider(get_text=lambda url: "Date,Open,High,Low,Close,Volume\n2026-07-02,1,1,1,10.8,5\n")
    svc = MarketDataService(
        providers={"coingecko": cg, "stooq": stooq}, key_resolver=lambda name: None, clock=lambda: 0.0
    )
    by = {q.provider: q for q in svc.quotes([_ref("coingecko", "bitcoin"), _ref("stooq", "aapl.us")])}
    assert by["coingecko"].value is None  # NEVER a fabricated 0
    assert by["stooq"].value == pytest.approx(10.8)  # healthy provider still paints


# ── C3 service: yahoo quotes + search wired end-to-end ────────────────────────


def test_service_routes_yahoo_quotes_off_the_chart_getter_no_network():
    from forecasting.marketdata.providers.yahoo import YahooProvider

    yahoo = YahooProvider(
        get_json=lambda url, **kw: {"chart": {"result": [{"meta": {"regularMarketPrice": 189.5}}]}}
    )
    svc = MarketDataService(providers={"yahoo": yahoo}, key_resolver=lambda name: None, clock=lambda: 0.0)
    (q,) = svc.quotes([_ref("yahoo", "AAPL")])
    assert q.provider == "yahoo" and q.value == pytest.approx(189.5)


def test_service_search_round_trips_through_yahoo_and_caches():
    from forecasting.marketdata.providers.yahoo import YahooProvider

    calls = {"n": 0}

    def _get(url, **kw):
        calls["n"] += 1
        return {"quotes": [{"quoteType": "EQUITY", "shortname": "Apple Inc.", "symbol": "AAPL"}]}

    svc = MarketDataService(
        providers={"yahoo": YahooProvider(get_json=_get)},
        key_resolver=lambda name: None,
        clock=lambda: 0.0,
        spawn=lambda fn: None,
    )
    out = svc.search("apple")
    assert [r.to_dict() for r in out] == [
        {"category": "Stocks", "name": "Apple Inc.", "provider": "yahoo", "symbol": "AAPL"}
    ]
    svc.search("apple")  # within TTL → served from cache, no second fetch
    assert calls["n"] == 1


def test_service_search_empty_query_is_empty_and_never_fetches():
    from forecasting.marketdata.providers.yahoo import YahooProvider

    called = {"hit": False}

    def _get(url, **kw):
        called["hit"] = True
        return {"quotes": []}

    svc = MarketDataService(providers={"yahoo": YahooProvider(get_json=_get)}, clock=lambda: 0.0)
    assert svc.search("   ") == []
    assert called["hit"] is False
