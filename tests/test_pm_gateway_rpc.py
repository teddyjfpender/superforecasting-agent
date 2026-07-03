"""Gateway pm.* RPCs over a stubbed PMService + a fake stream hub.

Asserts the request/response contracts and the sessionless ``pm.tick`` event
frame, without any venue client or network.
"""

from __future__ import annotations

import pytest

from tui_gateway import pm_rpc, server


# ── stub service returning to_dict()-able objects ────────────────────────────


class _Dictable:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class StubService:
    def __init__(self):
        self.calls = []

    def list_events(self, *, venue=None, query=None, tag=None, limit=40):
        self.calls.append(("list", venue, query, tag, limit))
        return [(_Dictable({"event_id": "E1", "title": "Test"}), _Dictable({"outcomes": [1]}))]

    def event_detail(self, venue, event_id):
        self.calls.append(("detail", venue, event_id))
        return _Dictable({"event_id": event_id}), _Dictable({"outcomes": []})

    def orderbook(self, venue, market_id):
        self.calls.append(("book", venue, market_id))
        return _Dictable({"market_id": market_id, "bids": [], "asks": []})

    def history(self, venue, market_id, *, series_ticker=None, interval="1w", period_interval=60, max_points=200):
        self.calls.append(("history", venue, market_id, interval, series_ticker, period_interval))
        return [_Dictable({"ts": 1, "p": 0.5}), _Dictable({"ts": 2, "p": 0.6})]


class StubHub:
    def __init__(self):
        self.started = []
        self.stopped = []
        self._on_tick = None

    def start(self, venue, market_ids, on_tick):
        self.started.append((venue, list(market_ids)))
        self._on_tick = on_tick
        from forecasting.pm.stream import StreamStart

        return StreamStart(True, subscribed=tuple(market_ids))

    def stop(self, venue, market_ids=None):
        self.stopped.append((venue, market_ids))
        return {"stopped": True, "venue": venue, "closed": market_ids is None}


@pytest.fixture
def wired():
    svc = StubService()
    hub = StubHub()
    pm_rpc.set_service(svc)
    pm_rpc.set_hub(hub)
    yield svc, hub
    pm_rpc.set_service(None)
    pm_rpc.set_hub(None)


def _call(method, params):
    return server.handle_request({"id": "1", "method": method, "params": params})


def test_pm_list_shapes_event_plus_distribution(wired):
    svc, _ = wired
    res = _call("pm.list", {"venue": "polymarket", "query": "cpi", "limit": 5})["result"]
    assert res["count"] == 1
    row = res["events"][0]
    assert row["event"]["event_id"] == "E1"
    assert row["distribution"]["outcomes"] == [1]
    assert svc.calls[0] == ("list", "polymarket", "cpi", None, 5)


def test_pm_list_clamps_and_defaults_limit(wired):
    svc, _ = wired
    _call("pm.list", {"limit": 9999})
    assert svc.calls[0][4] == 200  # clamped
    svc.calls.clear()
    _call("pm.list", {"limit": "not-an-int"})
    assert svc.calls[0][4] == 40  # default


def test_pm_detail_requires_args(wired):
    err = _call("pm.detail", {"venue": "kalshi"})["error"]
    assert err["code"] == -32602


def test_pm_detail_returns_event_and_distribution(wired):
    res = _call("pm.detail", {"venue": "kalshi", "event_id": "EV-9"})["result"]
    assert res["event"]["event_id"] == "EV-9"
    assert "outcomes" in res["distribution"]


def test_pm_book_returns_normalised_book(wired):
    res = _call("pm.book", {"venue": "polymarket", "market_id": "tok1"})["result"]
    assert res["book"]["market_id"] == "tok1"


def test_pm_history_passes_kalshi_params(wired):
    svc, _ = wired
    res = _call(
        "pm.history",
        {"venue": "kalshi", "market_id": "ABC", "range": "1m", "series_ticker": "SER", "period_interval": 1440},
    )["result"]
    assert res["count"] == 2
    assert svc.calls[0] == ("history", "kalshi", "ABC", "1m", "SER", 1440)


def test_pm_service_error_becomes_rpc_error(wired):
    svc, _ = wired

    def boom(**kw):
        raise RuntimeError("venue down")

    svc.list_events = boom
    err = _call("pm.list", {})["error"]
    assert err["code"] == -32000 and "venue down" in err["message"]


def test_pm_stream_start_and_stop(wired):
    _, hub = wired
    res = _call("pm.stream.start", {"venue": "polymarket", "market_ids": ["tok1", "tok2"]})["result"]
    assert res["streaming"] is True and res["subscribed"] == ["tok1", "tok2"]
    assert hub.started == [("polymarket", ["tok1", "tok2"])]
    out = _call("pm.stream.stop", {"venue": "polymarket"})["result"]
    assert out["closed"] is True


def test_pm_stream_start_validates_market_ids(wired):
    err = _call("pm.stream.start", {"venue": "polymarket", "market_ids": "nope"})["error"]
    assert err["code"] == -32602


def test_pm_tick_emits_sessionless_event(wired, monkeypatch):
    _, hub = wired
    frames = []
    monkeypatch.setattr(server, "write_json", lambda obj: frames.append(obj) or True)
    _call("pm.stream.start", {"venue": "polymarket", "market_ids": ["tok1"]})
    # drive a tick through the captured callback
    hub._on_tick("polymarket", "tok1", "book", {"bids": []})
    tick = [f for f in frames if f.get("params", {}).get("type") == "pm.tick"]
    assert tick, "no pm.tick frame emitted"
    payload = tick[0]["params"]["payload"]
    assert payload["venue"] == "polymarket" and payload["market_id"] == "tok1"
    assert payload["kind"] == "book" and "session_id" not in tick[0]["params"]
