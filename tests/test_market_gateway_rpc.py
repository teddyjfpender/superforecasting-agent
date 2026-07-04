"""Gateway ``market.quotes`` RPC over a stubbed MarketDataService (no network).

Asserts the request/response contract, the SeriesRef parsing, and per-provider
isolation surfacing through the wire.
"""

from __future__ import annotations

from forecasting.marketdata.model import Quote
from forecasting.marketdata.providers.yahoo import SearchResult
from tui_gateway import market_rpc, server


class StubService:
    def __init__(self):
        self.calls = []
        self.search_calls = []

    def search(self, query):
        self.search_calls.append(query)
        return [SearchResult(symbol="AAPL", provider="yahoo", name="Apple Inc.", category="Stocks")]

    def quotes(self, refs):
        self.calls.append(list(refs))
        return [
            Quote(
                symbol=r.symbol,
                provider=r.provider,
                name=r.name,
                category=r.category,
                value=1.2345 if r.provider == "frankfurter" else None,
                change=0.01 if r.provider == "frankfurter" else None,
                changePct=0.8 if r.provider == "frankfurter" else None,
                prevClose=1.2245 if r.provider == "frankfurter" else None,
                asOf=1_700_000_000_000,
                unit=r.unit,
                history=[1.22, 1.23, 1.2345] if r.provider == "frankfurter" else [],
            )
            for r in refs
        ]


def _wire(monkeypatch):
    svc = StubService()
    market_rpc.set_service(svc)
    return svc


def _call(method, params):
    return server.handle_request({"id": "1", "method": method, "params": params})


def test_market_quotes_returns_quotes(monkeypatch):
    svc = _wire(monkeypatch)
    try:
        res = _call(
            "market.quotes",
            {"series": [{"provider": "frankfurter", "symbol": "EUR", "name": "EUR per USD"}]},
        )["result"]
        assert res["quotes"][0]["symbol"] == "EUR"
        assert res["quotes"][0]["value"] == 1.2345
        assert res["quotes"][0]["history"] == [1.22, 1.23, 1.2345]
        # the handler parsed one SeriesRef through to the service
        assert len(svc.calls[0]) == 1 and svc.calls[0][0].provider == "frankfurter"
    finally:
        market_rpc.set_service(None)


def test_market_quotes_null_never_zero_on_the_wire(monkeypatch):
    _wire(monkeypatch)
    try:
        res = _call("market.quotes", {"series": [{"provider": "bea", "symbol": "T20305"}]})["result"]
        q = res["quotes"][0]
        assert q["value"] is None  # THE LAW survives the wire: null, not 0
        assert q["change"] is None and q["prevClose"] is None
    finally:
        market_rpc.set_service(None)


def test_market_quotes_missing_series_is_field_error(monkeypatch):
    _wire(monkeypatch)
    try:
        err = _call("market.quotes", {})["error"]
        assert err["code"] == -32602
        assert "series" in err["message"]
    finally:
        market_rpc.set_service(None)


def test_market_quotes_bad_ref_missing_provider_rejected(monkeypatch):
    _wire(monkeypatch)
    try:
        err = _call("market.quotes", {"series": [{"symbol": "EUR"}]})["error"]
        assert err["code"] == -32602
    finally:
        market_rpc.set_service(None)


def test_market_service_error_becomes_rpc_error(monkeypatch):
    svc = _wire(monkeypatch)

    def boom(refs):
        raise RuntimeError("provider network down")

    svc.quotes = boom
    try:
        err = _call("market.quotes", {"series": [{"provider": "frankfurter", "symbol": "EUR"}]})["error"]
        assert err["code"] == -32000 and "provider network down" in err["message"]
    finally:
        market_rpc.set_service(None)


def test_market_search_returns_results(monkeypatch):
    svc = _wire(monkeypatch)
    try:
        res = _call("market.search", {"query": "apple"})["result"]
        assert res["results"] == [
            {"category": "Stocks", "name": "Apple Inc.", "provider": "yahoo", "symbol": "AAPL"}
        ]
        assert svc.search_calls == ["apple"]
    finally:
        market_rpc.set_service(None)


def test_market_search_missing_query_is_field_error(monkeypatch):
    _wire(monkeypatch)
    try:
        err = _call("market.search", {})["error"]
        assert err["code"] == -32602
        assert "query" in err["message"]
    finally:
        market_rpc.set_service(None)
