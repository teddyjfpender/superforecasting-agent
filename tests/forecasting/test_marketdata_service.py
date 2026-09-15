"""MarketDataService: TTL + stale-while-revalidate cache and per-provider
failure isolation (Arc C1). No network — providers are stubs, clock/spawn
injected for determinism."""

from __future__ import annotations

from dataclasses import replace

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


def test_default_providers_cover_legacy_and_catalog_measurements():
    from forecasting.marketdata.service import _default_providers

    assert set(_default_providers()) >= {
        "frankfurter",
        "bea",
        "coingecko",
        "fred",
        "bls",
        "stooq",
        "yahoo",
    }

    from forecasting.marketdata.catalog import load_catalog
    assert {entry.provider for entry in load_catalog().series if entry.kind != "event"} <= set(_default_providers())


def test_service_routes_the_four_new_providers_with_real_parsers_no_network(monkeypatch):
    """The service groups by provider and runs each REAL provider's parser off an
    injected getter — no network — proving the C2 wiring end-to-end."""

    from forecasting.marketdata.providers.bls import BlsProvider
    from forecasting.marketdata.providers.coingecko import CoingeckoProvider
    from forecasting.marketdata.providers.fred import FredProvider
    from forecasting.marketdata.providers.stooq import StooqProvider

    # This parser-routing fixture describes July 2026, not the wall-clock date.
    from datetime import date
    from unittest.mock import Mock
    reference_date = Mock(wraps=date)
    reference_date.today.return_value = date(2026, 7, 2)
    monkeypatch.setattr("forecasting.marketdata.providers.fred.date", reference_date)

    cg = CoingeckoProvider(get_json=lambda url, **kw: {"bitcoin": {"usd": 64239, "usd_24h_change": -1.05}})
    # No key resolved → FRED takes the keyless CSV path (get_text).
    fred = FredProvider(
        get_json=lambda url, **kw: {"observations": []},
        get_text=lambda url, **kwargs: "DATE,X\n2026-05-01,5.10\n2026-06-01,4.90\n",
    )
    bls = BlsProvider(
        get_json=lambda url, **kw: {"Results": {"series": [{"seriesID": "CUUR0000SA0", "data": [{"period": "M05", "value": "320.1", "year": "2026"}]}]}}
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


def test_independent_series_failure_preserves_successes_and_cache():
    from forecasting.marketdata.provider import IndependentSeries, ProviderFailure

    class Partial(IndependentSeries, _StubProvider):
        def fetch(self, series, *, api_key=None):
            if series[0].symbol == 'broken':
                raise ProviderFailure('authentication', 'Provider rejected access')
            return super().fetch(series,api_key=api_key)

    provider=Partial('example')
    svc=MarketDataService(providers={'example':provider},key_resolver=lambda _:None)
    refs=[_ref('example','working'),_ref('example','broken')]
    values,statuses=svc.quote_result(refs)
    assert [q.symbol for q in values]==['working']
    assert statuses[0]['status']=='partial'
    assert '1 series available' in statuses[0]['message']
    assert svc.quotes([refs[0]])==values
    assert provider.calls==1


def test_search_failure_is_not_cached_as_no_matches():
    from forecasting.marketdata.provider import ProviderFailure

    class Search(_StubProvider):
        def search(self,query):
            raise RuntimeError('secret URL must not escape')

    svc=MarketDataService(providers={'yahoo':Search('yahoo')})
    with pytest.raises(ProviderFailure,match='Live ticker search is unavailable'):
        svc.search('example')


def test_fresh_retrieval_does_not_hide_an_outdated_observation():
    from datetime import datetime, timezone

    from forecasting.marketdata.catalog import load_catalog
    from forecasting.marketdata.model import DatedValue

    entry = next(s for s in load_catalog().series if s.provider == "eurostat")
    boundary = datetime(2026, 8, 31, tzinfo=timezone.utc).timestamp()
    now = [boundary + 30 * 86400]

    class Source(_StubProvider):
        def fetch(self, series, *, api_key=None):
            values = super().fetch(series, api_key=api_key)
            values[0] = replace(values[0], dated_history=[DatedValue(
                period_start="2026-08-01", period_end="2026-08-31", value=2.1
            )])
            return values

    source = Source("eurostat")
    service = MarketDataService(
        providers={"eurostat": source}, clock=lambda: 0, wall_clock=lambda: now[0]
    )
    ref = SeriesRef(provider=entry.provider, symbol=entry.symbol, catalog_id=entry.id)
    quotes, statuses = service.quote_result([ref])
    assert statuses[0]["status"] == "ready"
    now[0] = boundary + (entry.expected_lag_seconds or 0) + 1
    cached, statuses = service.quote_result([ref])
    assert source.calls == 1  # freshness is evaluated even on a cache hit
    assert cached == quotes  # retain useful history and original retrieval time
    assert statuses[0]["status"] == "stale"
    assert "Source retrieved" in statuses[0]["message"]


def test_provider_cannot_return_an_unrequested_identity():
    class WrongSource(_StubProvider):
        def fetch(self, series, *, api_key=None):
            values = super().fetch(series, api_key=api_key)
            values[0] = replace(values[0], symbol="WRONG")
            return values

    service = MarketDataService(providers={"yahoo": WrongSource("yahoo")})
    quotes, statuses = service.quote_result([_ref("yahoo", "AAPL")])
    assert quotes == []
    assert statuses[0]["status"] == "invalid_response"
