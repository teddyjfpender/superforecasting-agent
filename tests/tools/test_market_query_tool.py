"""The forecasting tool's ``market_query`` action over a stubbed service.

No network: a fake MarketDataService is injected via the module seam. Asserts
the ref-building shorthands and the honest-null pass-through.
"""

from __future__ import annotations

import json

import pytest

import tools.forecasting_tool as ft
from forecasting.marketdata.model import Quote


class _StubMDS:
    def __init__(self):
        self.calls = []

    def quotes(self, refs):
        self.calls.append(list(refs))
        return [
            Quote(
                symbol=r.symbol,
                provider=r.provider,
                name=r.name,
                category=r.category,
                value=None if r.provider == "bea" else 1.0,
                change=None,
                changePct=None,
                prevClose=None,
                asOf=0,
                unit=r.unit,
                history=[],
            )
            for r in refs
        ]


@pytest.fixture
def stub():
    svc = _StubMDS()
    ft.set_market_data_service(svc)
    yield svc
    ft.set_market_data_service(None)


def _run(args):
    return json.loads(ft.forecast_ledger_tool(args))


def test_market_query_explicit_market_series(stub):
    out = _run({"action": "market_query", "market_series": [{"provider": "frankfurter", "symbol": "EUR"}]})
    assert out["success"] is True
    assert out["count"] == 1
    assert out["quotes"][0]["symbol"] == "EUR" and out["quotes"][0]["value"] == 1.0
    assert stub.calls[0][0].provider == "frankfurter"


def test_market_query_symbols_plus_single_provider_shorthand(stub):
    out = _run({"action": "market_query", "providers": ["frankfurter"], "symbols": ["EUR", "JPY"]})
    assert out["count"] == 2
    assert {q["symbol"] for q in out["quotes"]} == {"EUR", "JPY"}
    assert all(r.provider == "frankfurter" for r in stub.calls[0])


def test_market_query_zips_multiple_providers_with_symbols(stub):
    out = _run(
        {"action": "market_query", "providers": ["frankfurter", "bea"], "symbols": ["EUR", "T20305"]}
    )
    pairs = {(r.provider, r.symbol) for r in stub.calls[0]}
    assert pairs == {("frankfurter", "EUR"), ("bea", "T20305")}
    # honest null survives for the bea reading
    bea = next(q for q in out["quotes"] if q["provider"] == "bea")
    assert bea["value"] is None
    assert out["count"] == 2


def test_market_query_requires_series_or_symbols(stub):
    out = _run({"action": "market_query"})
    assert out["success"] is False
    assert "market_series" in out["error"] or "symbols" in out["error"]
