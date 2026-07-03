"""Kalshi client + parser + signer tests (recorded fixtures, no network)."""

from __future__ import annotations

import pytest

from forecasting.pm import kalshi as kal
from tests.forecasting.pm_helpers import RecordedFetch, load_fixture


def test_parse_nested_event_and_dollar_prices():
    ev = kal.parse_event(load_fixture("kalshi_event_categorical.json"))
    assert ev.venue == "kalshi"
    assert len(ev.markets) >= 3
    m = ev.markets[0]
    # yes_sub_title is the outcome label; *_dollars strings become 0-1 floats.
    assert m.label and m.yes_bid is not None and 0.0 <= m.yes_bid <= 1.0
    assert m.event_id and ev.slug  # series_ticker


def test_parse_orderbook_yes_view():
    ob = kal.parse_orderbook(load_fixture("kalshi_orderbook.json"), market_id="T")
    assert ob.market_id == "T"
    # a NO bid at price p becomes a YES ask at 1-p → asks stay in [0,1]
    assert all(0.0 <= a.price <= 1.0 for a in ob.asks)
    assert all(ob.asks[i].price <= ob.asks[i + 1].price for i in range(len(ob.asks) - 1))
    if ob.best_bid is not None and ob.best_ask is not None:
        assert ob.best_bid <= ob.best_ask


def test_parse_candlesticks_uses_mean_or_mid():
    hist = kal.parse_candlesticks(load_fixture("kalshi_candlesticks.json"))
    assert hist and all(0.0 <= p.p <= 1.0 for p in hist)
    assert all(hist[i].ts <= hist[i + 1].ts for i in range(len(hist) - 1))


def test_client_urls_and_period_interval_guard():
    fetch = RecordedFetch(
        {
            "/events?": load_fixture("kalshi_event_categorical.json"),
            "/orderbook": load_fixture("kalshi_orderbook.json"),
            "/candlesticks?": load_fixture("kalshi_candlesticks.json"),
        }
    )
    # list endpoint returns {"events":[...]} shape
    fetch._routes["/events?"] = {"events": [load_fixture("kalshi_event_categorical.json")]}
    client = kal.KalshiClient(fetch=fetch)
    assert client.list_events(limit=5)
    assert client.orderbook("TICK").market_id == "TICK"
    assert client.candlesticks("SER", "TICK", period_interval=60)
    assert any("with_nested_markets=true" in c for c in fetch.calls)
    with pytest.raises(ValueError):
        client.candlesticks("SER", "TICK", period_interval=5)


def test_signer_round_trips_with_generated_key():
    crypto = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    headers = kal.kalshi_auth_headers("keyid-1", pem, "GET", kal.KALSHI_WS_PATH, timestamp_ms=1730000000000)
    assert headers["KALSHI-ACCESS-KEY"] == "keyid-1"
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1730000000000"
    # PSS uses a random salt so bytes differ per call — assert the signature is
    # a valid RSA-PSS-SHA256 signature over the documented message instead.
    import base64

    message = "1730000000000GET" + kal.KALSHI_WS_PATH
    key.public_key().verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        message.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )


def test_signer_absent_dependency_is_polite(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("cryptography"):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(kal.KalshiSignerUnavailable):
        kal.sign_kalshi_message("-----BEGIN PRIVATE KEY-----\n", "msg")


def test_text_query_paginates_the_catalog():
    """Kalshi search scans cursor pages (bounded) instead of one top page."""
    from tests.forecasting.pm_helpers import load_fixture
    from forecasting.pm.kalshi import KalshiClient

    target = load_fixture("kalshi_event_categorical.json")
    filler = dict(target)
    filler = {**target, "title": "Something else entirely", "event_ticker": "KXFILLER-1"}
    calls: list[str] = []

    def fetch(url, **kw):
        calls.append(url)
        if "cursor=page2" in url:
            return {"events": [target], "cursor": None}
        return {"events": [filler], "cursor": "page2"}

    client = KalshiClient(fetch=fetch)
    found = client.list_events(query=target["title"][:10].lower(), limit=5)
    assert len(found) == 1 and found[0].title == target["title"]
    assert len(calls) == 2, "must have followed the cursor to page 2"
