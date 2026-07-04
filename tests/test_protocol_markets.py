"""Conformance for the ``market.*`` protocol models (Arc C on Arc A).

* the registered RPC round-trips a valid request and rejects an invalid one with
  the offending FIELD NAMED;
* a real ``Quote.to_dict`` frame (the server's actual emission) parses through
  the response model AND ``model_dump`` reproduces it byte-for-byte — the wire
  never changes shape, and THE LAW (value/change/prevClose stay null) survives
  the round trip.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forecasting.marketdata.model import Quote
from protocol import RPC_BY_METHOD


def _fx_quote() -> dict:
    return Quote(
        symbol="EUR",
        provider="frankfurter",
        name="EUR per USD",
        category="FX",
        value=0.8735,
        change=0.0025,
        changePct=0.287,
        prevClose=0.871,
        asOf=1_781_654_400_000,
        unit="",
        history=[0.86, 0.865, 0.871, 0.8735],
    ).to_dict()


def _bea_null_quote() -> dict:
    # An error/empty payload: every measurement null (THE LAW).
    return Quote(
        symbol="T20305",
        provider="bea",
        name="BEA NIPA: PCE",
        category="US Macro",
        value=None,
        change=None,
        changePct=None,
        prevClose=None,
        asOf=0,
        unit="$B",
        history=[],
    ).to_dict()


def _yahoo_rich_quote() -> dict:
    # Yahoo carries the richer columns; they must survive the wire round-trip.
    return Quote(
        symbol="AAPL",
        provider="yahoo",
        name="Apple Inc.",
        category="Stocks",
        value=189.5,
        change=1.5,
        changePct=0.8,
        prevClose=188.0,
        asOf=1_781_729_434_000,
        unit="",
        history=[186.0, 188.0, 189.5],
        currency="USD",
        exchange="NasdaqGS",
        dayHigh=190.1,
        dayLow=187.2,
        volume=53_000_000,
        week52High=199.0,
        week52Low=164.0,
    ).to_dict()


@pytest.mark.parametrize("frame", [_fx_quote(), _bea_null_quote(), _yahoo_rich_quote()])
def test_quote_frame_is_wire_identical(frame):
    spec = RPC_BY_METHOD["market.quotes"]
    result = {"quotes": [frame]}
    model = spec.response.model_validate(result)
    dumped = model.model_dump(mode="json", exclude_none=spec.exclude_none)
    assert dumped == result


def test_registry_has_market_quotes():
    spec = RPC_BY_METHOD["market.quotes"]
    assert spec.request is not None and spec.response is not None


@pytest.mark.parametrize(
    "payload",
    [
        {"series": []},
        {"series": [{"provider": "frankfurter", "symbol": "EUR"}]},
        {"series": [{"provider": "bea", "symbol": "T20305", "line": "1", "unit": "$B"}]},
    ],
)
def test_valid_requests_accepted(payload):
    RPC_BY_METHOD["market.quotes"].request.model_validate(payload)  # must not raise


def test_invalid_request_missing_series_names_field():
    with pytest.raises(ValidationError) as excinfo:
        RPC_BY_METHOD["market.quotes"].request.model_validate({})
    locs = {str(part) for err in excinfo.value.errors() for part in err["loc"]}
    assert "series" in locs


def test_invalid_ref_missing_provider_names_field():
    with pytest.raises(ValidationError) as excinfo:
        RPC_BY_METHOD["market.quotes"].request.model_validate({"series": [{"symbol": "EUR"}]})
    locs = {str(part) for err in excinfo.value.errors() for part in err["loc"]}
    assert "provider" in locs


def test_gateway_wrapper_names_field_on_invalid_payload():
    from tui_gateway import server

    resp = server.handle_request({"id": "1", "method": "market.quotes", "params": {}})
    assert resp["error"]["code"] == -32602
    assert "series" in resp["error"]["message"]


# ── market.search conformance ─────────────────────────────────────────────────


def test_market_search_registered_and_round_trips():
    spec = RPC_BY_METHOD["market.search"]
    spec.request.model_validate({"query": "apple"})  # must not raise
    result = {"results": [{"symbol": "AAPL", "provider": "yahoo", "name": "Apple Inc.", "category": "Stocks"}]}
    model = spec.response.model_validate(result)
    assert model.model_dump(mode="json", exclude_none=spec.exclude_none) == result


def test_market_search_invalid_request_names_query_field():
    with pytest.raises(ValidationError) as excinfo:
        RPC_BY_METHOD["market.search"].request.model_validate({})
    locs = {str(part) for err in excinfo.value.errors() for part in err["loc"]}
    assert "query" in locs
