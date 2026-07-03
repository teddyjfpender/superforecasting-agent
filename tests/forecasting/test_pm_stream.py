"""PMStreamHub over a FAKE ws transport — subscribe/multiplex/reconnect/stop +
tick dispatch + polite degradation. Never touches the network.
"""

from __future__ import annotations

import json
import threading

import pytest

from forecasting.pm.stream import (
    PMStreamHub,
    Tick,
    WsTimeout,
    parse_kalshi,
    parse_polymarket,
)


class FakeConn:
    """Scripted in-memory socket. ``script`` is a list of outbound frames to
    yield from recv(); a ``"__close__"`` sentinel raises to simulate a drop."""

    def __init__(self, script: list, *, on_send=None) -> None:
        self._script = list(script)
        self.sent: list[dict] = []
        self._on_send = on_send
        self.closed = False
        self._done = threading.Event()

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))
        if self._on_send is not None:
            self._on_send(json.loads(message))

    def recv(self, timeout: float | None = None) -> str:
        if not self._script:
            self._done.set()
            raise WsTimeout()  # idle — keep the pump alive without spinning hot
        item = self._script.pop(0)
        if item == "__close__":
            raise ConnectionError("simulated drop")
        return json.dumps(item)

    def close(self) -> None:
        self.closed = True
        self._done.set()


def _collect(ticks: list, done: threading.Event, expected: int):
    def on_tick(venue, market_id, kind, payload):
        ticks.append((venue, market_id, kind))
        if len(ticks) >= expected:
            done.set()

    return on_tick


# ── parsing ──────────────────────────────────────────────────────────────────


def test_parse_polymarket_book_and_price():
    ticks = parse_polymarket(
        [
            {"event_type": "book", "asset_id": "tok1", "bids": [], "asks": []},
            {"event_type": "price_change", "asset_id": "tok2", "changes": []},
            {"event_type": "book"},  # no asset → dropped
        ]
    )
    assert [(t.market_id, t.kind) for t in ticks] == [("tok1", "book"), ("tok2", "price")]


def test_parse_kalshi_ticker():
    ticks = parse_kalshi({"type": "ticker", "msg": {"market_ticker": "ABC-24", "yes_bid": 40}})
    assert ticks == [Tick(market_id="ABC-24", kind="price", payload={"type": "ticker", "msg": {"market_ticker": "ABC-24", "yes_bid": 40}})]


# ── hub: subscribe + tick dispatch ───────────────────────────────────────────


def test_start_subscribes_and_emits_ticks():
    done = threading.Event()
    ticks: list = []
    conn = FakeConn(
        [
            {"event_type": "book", "asset_id": "tok1"},
            {"event_type": "price_change", "asset_id": "tok1"},
        ]
    )

    def connect(url, headers):
        return conn

    hub = PMStreamHub(connect=connect, max_reconnects=0)
    res = hub.start("polymarket", ["tok1"], _collect(ticks, done, 2))
    assert res.streaming is True and res.subscribed == ("tok1",)
    assert done.wait(2.0), "expected two ticks"
    hub.shutdown()

    # exactly one subscribe frame carrying the asset (Polymarket shape)
    subs = [f for f in conn.sent if f.get("type") == "market"]
    assert subs and subs[0]["assets_ids"] == ["tok1"]
    assert ("polymarket", "tok1", "book") in ticks


def test_multiplex_adds_incremental_subscribe_on_live_connection():
    sent_event = threading.Event()
    seen: list[list[str]] = []

    def on_send(frame):
        if frame.get("type") == "market":
            seen.append(frame["assets_ids"])
            if len(seen) >= 2:
                sent_event.set()

    # idle script → connection stays open so the second .add() multiplexes on it
    conn = FakeConn([], on_send=on_send)
    hub = PMStreamHub(connect=lambda u, h: conn, max_reconnects=0)
    hub.start("polymarket", ["tok1"], lambda *a: None)
    # let the worker connect + send the first subscribe
    assert _wait(lambda: len(seen) >= 1)
    hub.start("polymarket", ["tok2"], lambda *a: None)
    assert sent_event.wait(2.0), "second subscribe not multiplexed"
    hub.shutdown()
    assert seen[0] == ["tok1"] and seen[1] == ["tok2"]


def test_reconnect_resends_full_subscription_set():
    conns: list[FakeConn] = []

    def connect(url, headers):
        # first connection drops after one tick; second stays idle
        script = [{"event_type": "book", "asset_id": "tok1"}, "__close__"] if not conns else []
        c = FakeConn(script)
        conns.append(c)
        return c

    sleeps: list[float] = []
    hub = PMStreamHub(
        connect=connect, sleeper=lambda s: sleeps.append(s), max_reconnects=3
    )
    hub.start("polymarket", ["tok1"], lambda *a: None)
    assert _wait(lambda: len(conns) >= 2, timeout=3.0), "did not reconnect"
    hub.shutdown()
    # backoff was applied and the reconnect re-sent the subscription
    assert sleeps and sleeps[0] == 1.0
    resub = [f for f in conns[1].sent if f.get("type") == "market"]
    assert resub and resub[0]["assets_ids"] == ["tok1"]


def test_stop_closes_connection_and_clears_subscription():
    conn = FakeConn([])
    hub = PMStreamHub(connect=lambda u, h: conn, max_reconnects=0)
    hub.start("polymarket", ["tok1"], lambda *a: None)
    assert _wait(lambda: conn.sent, timeout=2.0)
    out = hub.stop("polymarket")
    assert out["closed"] is True
    assert conn.closed is True
    assert hub.active() == {}


def test_partial_stop_keeps_remaining_subscriptions():
    conn = FakeConn([])
    hub = PMStreamHub(connect=lambda u, h: conn, max_reconnects=0)
    hub.start("polymarket", ["tok1", "tok2"], lambda *a: None)
    assert _wait(lambda: conn.sent, timeout=2.0)
    out = hub.stop("polymarket", ["tok1"])
    assert out["stopped"] is True and out.get("closed") is not True
    assert out["remaining"] == ["tok2"]
    hub.shutdown()


# ── degradation ──────────────────────────────────────────────────────────────


def test_no_websocket_lib_degrades_politely():
    hub = PMStreamHub(websocket_probe=lambda: False)
    res = hub.start("polymarket", ["tok1"], lambda *a: None)
    assert res.streaming is False
    assert "websocket" in res.reason.lower()


def test_kalshi_without_key_degrades_politely():
    hub = PMStreamHub(
        connect=lambda u, h: FakeConn([]),
        websocket_probe=lambda: True,
        kalshi_credentials=lambda: None,
    )
    res = hub.start("kalshi", ["ABC-24"], lambda *a: None)
    assert res.streaming is False and "kalshi" in res.reason.lower()


def test_kalshi_with_key_signs_handshake_headers():
    captured: dict = {}

    def connect(url, headers):
        captured["url"] = url
        captured["headers"] = headers
        return FakeConn([])

    # a stub signer path: real cryptography signs; fake creds are a throwaway PEM
    key_pem = _throwaway_pem()
    hub = PMStreamHub(
        connect=connect,
        websocket_probe=lambda: True,
        kalshi_credentials=lambda: ("key-123", key_pem),
        max_reconnects=0,
    )
    res = hub.start("kalshi", ["ABC-24"], lambda *a: None)
    assert res.streaming is True
    assert _wait(lambda: "headers" in captured, timeout=2.0)
    hub.shutdown()
    assert captured["headers"]["KALSHI-ACCESS-KEY"] == "key-123"
    assert "KALSHI-ACCESS-SIGNATURE" in captured["headers"]


def test_unknown_venue_raises():
    hub = PMStreamHub(websocket_probe=lambda: True)
    with pytest.raises(ValueError):
        hub.start("betfair", ["x"], lambda *a: None)


# ── helpers ──────────────────────────────────────────────────────────────────


def _wait(predicate, timeout: float = 2.0) -> bool:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def _throwaway_pem() -> str:
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
