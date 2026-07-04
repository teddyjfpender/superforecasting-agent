"""Conformance for the ``pm.*`` protocol models (Arc A1).

Three guarantees:
* every registered RPC round-trips a valid request, and rejects an invalid one
  with the offending FIELD NAMED;
* a captured REAL server frame (built from ``forecasting/pm`` ``to_dict`` — the
  actual emission) parses through the response model AND ``model_dump`` reproduces
  it byte-for-byte (the wire never changes shape);
* the gateway wrapper surfaces a bad payload through the -32602 path, naming the
  field.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forecasting.pm.model import (
    PMDistribution,
    PMEvent,
    PMHistoryPoint,
    PMMarket,
    PMOrderBook,
    PMOrderLevel,
    PMOutcome,
)
from forecasting.pm.stream import StreamStart
from protocol import RPC_BY_METHOD, RPC_SPECS
from protocol.events.pm import PmTick


# ── real frames: the SERVER's actual to_dict emission ─────────────────────────


def _event() -> PMEvent:
    market = PMMarket(
        venue="polymarket",
        market_id="cond-a",
        label="Alpha",
        question="Who wins?",
        event_id="evt-1",
        yes_bid=0.55,
        yes_ask=0.58,
        last_price=0.56,
        volume=1000.0,
        open_interest=None,
        close_time="2099-01-01T00:00:00Z",
        status="open",
        url="https://polymarket.com/event/alpha",
        token_ids=("tok-yes", "tok-no"),
    )
    return PMEvent(
        venue="polymarket",
        event_id="evt-1",
        title="Alpha Cup",
        markets=(market,),
        slug="alpha",
        category="Sports",
        close_time="2099-01-01T00:00:00Z",
        volume=1000.0,
        url="https://polymarket.com/event/alpha",
    )


def _distribution() -> PMDistribution:
    outcome = PMOutcome(
        label="Alpha",
        prob=0.5,
        raw_prob=0.48,
        market_id="cond-a",
        yes_bid=0.55,
        yes_ask=0.58,
        volume=1000.0,
        liquid=True,
    )
    return PMDistribution(
        venue="polymarket",
        event_id="evt-1",
        title="Alpha Cup",
        outcomes=(outcome,),
        binary=False,
        overround=0.03,
        total_volume=30000.0,
        close_time="2099-01-01T00:00:00Z",
        url="https://polymarket.com/event/alpha",
    )


def _book() -> PMOrderBook:
    return PMOrderBook(
        venue="polymarket",
        market_id="tok-yes",
        bids=(PMOrderLevel(0.55, 120.0),),
        asks=(PMOrderLevel(0.58, 90.0),),
        tick_size=0.01,
        timestamp=1,
    )


REAL_RESULTS: dict[str, dict] = {
    "pm.list": {
        "events": [{"event": _event().to_dict(), "distribution": _distribution().to_dict()}],
        "count": 1,
    },
    "pm.detail": {"event": _event().to_dict(), "distribution": _distribution().to_dict()},
    "pm.book": {"book": _book().to_dict()},
    "pm.history": {
        "points": [PMHistoryPoint(1, 0.5).to_dict(), PMHistoryPoint(2, 0.6).to_dict()],
        "count": 2,
    },
    "pm.stream.start": StreamStart(True, subscribed=("tok1", "tok2")).to_dict(),
    "pm.stream.stop": {"stopped": True, "venue": "polymarket", "closed": True},
}


def test_registry_covers_every_pm_rpc():
    # The registry also carries non-pm families (jobs.* — Arc B); this suite owns
    # the pm.* contract, so scope the coverage check to pm.* methods.
    pm_methods = {s.method for s in RPC_SPECS if s.method.startswith("pm.")}
    assert pm_methods == set(REAL_RESULTS)
    for spec in RPC_SPECS:
        assert spec.request is not None and spec.response is not None


@pytest.mark.parametrize("method", sorted(REAL_RESULTS))
def test_real_response_frame_is_wire_identical(method):
    """A real to_dict frame parses through the model and ``model_dump``
    reproduces it EXACTLY — proving the server wrapper never mutates the wire."""

    spec = RPC_BY_METHOD[method]
    frame = REAL_RESULTS[method]
    model = spec.response.model_validate(frame)  # (manual TS check: matches ../protocol/generated.ts)
    dumped = model.model_dump(mode="json", exclude_none=spec.exclude_none)
    assert dumped == frame


@pytest.mark.parametrize(
    "frame",
    [
        StreamStart(True).to_dict(),  # empty subscribed -> key omitted
        StreamStart(True, subscribed=("a", "b")).to_dict(),
        StreamStart(False, "websocket library not installed").to_dict(),
    ],
)
def test_stream_start_conditional_fields_roundtrip(frame):
    spec = RPC_BY_METHOD["pm.stream.start"]
    dumped = spec.response.model_validate(frame).model_dump(mode="json", exclude_none=True)
    assert dumped == frame


@pytest.mark.parametrize(
    "frame",
    [
        {"stopped": False, "venue": "polymarket"},
        {"stopped": True, "venue": "polymarket", "closed": True},
        {"stopped": True, "venue": "polymarket", "remaining": ["a", "b"]},
    ],
)
def test_stream_stop_conditional_fields_roundtrip(frame):
    spec = RPC_BY_METHOD["pm.stream.stop"]
    dumped = spec.response.model_validate(frame).model_dump(mode="json", exclude_none=True)
    assert dumped == frame


# ── request validation ────────────────────────────────────────────────────────


VALID_REQUESTS: dict[str, list[dict]] = {
    "pm.list": [{}, {"venue": "kalshi", "query": "cpi", "limit": 5}, {"limit": 9999}, {"limit": "not-an-int"}],
    "pm.detail": [{"venue": "kalshi", "event_id": "EV-9"}],
    "pm.book": [{"venue": "polymarket", "market_id": "tok1"}],
    "pm.history": [
        {"venue": "kalshi", "market_id": "ABC", "range": "1m", "series_ticker": "SER", "period_interval": 1440},
        {"venue": "kalshi", "market_id": "ABC", "max_points": "bad"},
    ],
    "pm.stream.start": [
        {"venue": "polymarket", "market_ids": ["a", "b"]},
        {"venue": "polymarket"},
        {"venue": "polymarket", "market_ids": None},
    ],
    "pm.stream.stop": [{"venue": "polymarket"}, {"venue": "polymarket", "market_ids": ["a"]}],
}


@pytest.mark.parametrize("method", sorted(VALID_REQUESTS))
def test_valid_requests_accepted(method):
    spec = RPC_BY_METHOD[method]
    for payload in VALID_REQUESTS[method]:
        spec.request.model_validate(payload)  # must not raise


INVALID_REQUESTS: list[tuple[str, dict, str]] = [
    ("pm.detail", {}, "venue"),
    ("pm.detail", {"venue": "kalshi"}, "event_id"),
    ("pm.book", {"venue": "polymarket"}, "market_id"),
    ("pm.book", {"market_id": "x"}, "venue"),
    ("pm.history", {"venue": "x"}, "market_id"),
    ("pm.stream.start", {"market_ids": ["a"]}, "venue"),
    ("pm.stream.start", {"venue": "x", "market_ids": "nope"}, "market_ids"),
    ("pm.stream.stop", {}, "venue"),
]


@pytest.mark.parametrize("method,payload,field", INVALID_REQUESTS)
def test_invalid_requests_rejected_naming_field(method, payload, field):
    spec = RPC_BY_METHOD[method]
    with pytest.raises(ValidationError) as excinfo:
        spec.request.model_validate(payload)
    locs = {str(part) for err in excinfo.value.errors() for part in err["loc"]}
    assert field in locs


# ── pm.tick event ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("estimate", [0.565, None])
def test_pm_tick_event_roundtrips(estimate):
    frame = {
        "venue": "polymarket",
        "market_id": "tok1",
        "kind": "book",
        "estimate": estimate,
        "payload": {"bids": []},
    }
    assert PmTick.model_validate(frame).model_dump(mode="json") == frame


# ── gateway wrapper surfaces the field on the wire ────────────────────────────


def test_gateway_wrapper_names_field_on_invalid_payload():
    # Import here so registration (server.py imports + registers pm_rpc) has run.
    from tui_gateway import server

    resp = server.handle_request({"id": "1", "method": "pm.detail", "params": {"venue": "kalshi"}})
    assert resp["error"]["code"] == -32602
    assert "event_id" in resp["error"]["message"]
