"""Polymarket watched-source ↔ PM-data-plane unification.

The watched-source adapter (``forecasting/source_adapters.load_polymarket_market``)
used a MARKET-only importer: a bare EVENT slug, a numeric EVENT id, or a
``polymarket.com/event/{slug}`` page URL all resolved to ``/markets?slug=`` /
``/markets?id=`` — which return EMPTY for events — so structured Polymarket
watches logged validation misses (``missing:polymarket:…:ValidationError``) even
though the very same markets resolve through the PM data plane / ``pm_query``.

The fix routes both paths through ONE id-form router in the data plane
(``forecasting.pm.polymarket.market_endpoint_candidates``): market forms first
(so a source that already resolved keeps hitting the SAME endpoint first — its
watch signature is byte-stable), then the EVENT ``/events/slug/{slug}`` /
``/events/{id}`` fallbacks. These tests pin the routing, the fallback resolution,
the signature stability, and the conditionId guard. One bounded live probe
(``integration`` marker, skipped by default) exercises the real Gamma endpoint.
"""

from __future__ import annotations

import json

import pytest

import forecasting.source_adapters as sa
from forecasting.ledger import ForecastLedger
from forecasting.pm import polymarket as pmp

BASE = "https://gamma-api.polymarket.com"
HEX64 = "0x" + "a" * 64

# The two watches that are GREEN on the live ledger today (their stored
# signatures must never move under this refactor — see the live probe below).
LIVE_GREEN = {
    "https://gamma-api.polymarket.com/events/slug/may-inflation-us-annual":
        "polymarket:1:1f73143e39eaec93c58c35237a3ca07e69fb8c6c7e746929821932b84f3bfa3d",
    "https://gamma-api.polymarket.com/events/slug/texas-senate-election-winner":
        "polymarket:1:46c1625ed262b0ae6dc566dffcd0d93224a922024b37bc616bf28c69321d5ced",
}


# ── pure id-form routing (no network) ────────────────────────────────────────
def test_bare_event_slug_tries_market_then_event_slug():
    cands = pmp.market_endpoint_candidates("texas-senate-election-winner", gamma_base=BASE)
    assert cands == [
        f"{BASE}/markets?slug=texas-senate-election-winner",
        f"{BASE}/events/slug/texas-senate-election-winner",
    ]


def test_numeric_id_tries_market_id_then_event_id():
    cands = pmp.market_endpoint_candidates("677008", gamma_base=BASE)
    assert cands == [f"{BASE}/markets?id=677008", f"{BASE}/events/677008"]


def test_prefixed_numeric_id_matches_bare():
    assert pmp.market_endpoint_candidates("id:677008", gamma_base=BASE) == \
        pmp.market_endpoint_candidates("677008", gamma_base=BASE)


def test_condition_id_has_no_event_fallback():
    # A 0x conditionId is NEVER an event — it must resolve ONLY through the
    # condition_ids filter (guarding the resolution reader's conditionId path).
    cands = pmp.market_endpoint_candidates(HEX64, gamma_base=BASE)
    assert cands == [f"{BASE}/markets?condition_ids={HEX64}"]
    assert not any("/events" in c for c in cands)


def test_gamma_api_url_passes_through_unchanged():
    url = f"{BASE}/events/slug/texas-senate-election-winner"
    assert pmp.market_endpoint_candidates(url, gamma_base=BASE) == [url]


def test_event_page_url_resolves_event_slug():
    cands = pmp.market_endpoint_candidates(
        "https://polymarket.com/event/new-hampshire-senate-election-winner", gamma_base=BASE
    )
    assert cands == [
        f"{BASE}/markets?slug=new-hampshire-senate-election-winner",
        f"{BASE}/events/slug/new-hampshire-senate-election-winner",
    ]


def test_market_detail_url_tries_market_slug_and_event_slug():
    cands = pmp.market_endpoint_candidates(
        "https://polymarket.com/event/texas-senate-election-winner/will-person-b-win",
        gamma_base=BASE,
    )
    assert cands == [
        f"{BASE}/markets?slug=will-person-b-win",
        f"{BASE}/events/slug/texas-senate-election-winner",
        f"{BASE}/events/slug/will-person-b-win",
    ]


def test_empty_source_raises():
    with pytest.raises(ValueError):
        pmp.market_endpoint_candidates("id:  ", gamma_base=BASE)
    with pytest.raises(sa.ValidationError):
        sa._polymarket_endpoint_candidates("slug:  ", api_base_url=BASE)


def test_endpoint_for_source_is_primary_candidate():
    # Back-compat: the singular helper returns the FIRST candidate.
    for src in ("id:512724", f"id:{HEX64}", HEX64, "texas-senate-election-winner"):
        assert sa._polymarket_endpoint_for_source(src, api_base_url=BASE) == \
            sa._polymarket_endpoint_candidates(src, api_base_url=BASE)[0]


# ── load_polymarket_market: event fallbacks + market-first stability ──────────
def _market(**over):
    row = {
        "question": "Will the Democrats win the New Hampshire Senate race in 2026?",
        "id": "630844",
        "slug": "will-the-democrats-win-the-new-hampshire-senate-race-in-2026",
        "outcomes": json.dumps(["Yes", "No"]),
        "outcomePrices": json.dumps(["0.62", "0.38"]),
        "closed": False,
        "volumeNum": 12345.0,
        "endDate": "2026-11-03T00:00:00Z",
    }
    row.update(over)
    return row


def _event(markets):
    return {"id": "57661", "slug": "new-hampshire-senate-election-winner", "markets": markets}


def test_bare_event_slug_resolves_via_event_fallback(monkeypatch):
    calls: list[str] = []

    def fake_read(url, label, **kw):
        calls.append(url)
        if "/events/slug/" in url:
            return _event([_market()])
        return []  # /markets?slug= is empty for an EVENT slug

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    m = sa.load_polymarket_market("new-hampshire-senate-election-winner")
    assert m.probability == pytest.approx(0.62)
    assert m.question.startswith("Will the Democrats")
    assert any("/markets?slug=" in u for u in calls)  # tried market first
    assert any("/events/slug/" in u for u in calls)  # then the event fallback


def test_numeric_event_id_resolves_via_events_id(monkeypatch):
    def fake_read(url, label, **kw):
        if url.endswith("/events/677008"):
            return _event([_market()])
        return []

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    assert sa.load_polymarket_market("677008").probability == pytest.approx(0.62)


def test_event_page_url_resolves(monkeypatch):
    def fake_read(url, label, **kw):
        return _event([_market()]) if "/events/slug/" in url else []

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    m = sa.load_polymarket_market("https://polymarket.com/event/new-hampshire-senate-election-winner")
    assert m.question.startswith("Will the Democrats")


def test_market_slug_resolves_on_first_candidate_without_event_fetch(monkeypatch):
    """A genuine MARKET slug resolves on the FIRST candidate — no event endpoint is
    ever hit, so working watches keep their exact signature (no drift)."""
    calls: list[str] = []

    def fake_read(url, label, **kw):
        calls.append(url)
        return [_market(slug="a-real-market-slug")]  # /markets?slug= answers immediately

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    m = sa.load_polymarket_market("a-real-market-slug")
    assert m.slug == "a-real-market-slug"
    assert len(calls) == 1 and "/markets?slug=" in calls[0]
    assert not any("/events" in u for u in calls)  # event fallback never fired


def test_condition_id_never_hits_an_event_endpoint(monkeypatch):
    """The conditionId path keeps its condition_ids + closed=true fallback and must
    NEVER reach an /events endpoint (regression guard for the resolution reader)."""
    calls: list[str] = []

    def fake_read(url, label, **kw):
        calls.append(url)
        if "condition_ids=" in url and "closed=true" in url:
            row = _market(conditionId=HEX64, closed=True, outcomePrices=json.dumps(["0", "1"]))
            return [row]
        return []  # open-only default is empty for a settled market

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    m = sa.load_polymarket_market(f"id:{HEX64}")
    assert m.probability == 0.0
    assert not any("/events" in u for u in calls)
    assert any("condition_ids=" in u and "closed=true" not in u for u in calls)
    assert any("closed=true" in u for u in calls)


def test_unresolvable_source_raises(monkeypatch):
    # free-text phrase (a search query, not a structured id) misses everywhere
    monkeypatch.setattr(sa, "_read_json_endpoint", lambda url, label, **kw: [])
    with pytest.raises(sa.ValidationError):
        sa.load_polymarket_market("next labour leader")


# ── watch-signature stability (the CRITICAL invariant) ───────────────────────
def test_signature_format_unchanged(tmp_path, monkeypatch):
    lg = ForecastLedger(db_path=str(tmp_path / "sig.db"))
    lg.initialize_schema()
    monkeypatch.setattr(sa, "_read_json_endpoint",
                        lambda url, label, **kw: _event([_market()]) if "/events/slug/" in url else [])
    sig = lg._polymarket_source_signature("new-hampshire-senate-election-winner")
    assert sig.startswith("polymarket:1:")
    assert len(sig.split(":")[2]) == 64  # sha256 hex digest, format unchanged


def test_bare_slug_and_gamma_url_yield_identical_signature(tmp_path, monkeypatch):
    """The same event entered as a bare slug OR as the gamma /events/slug/ URL (the
    green form) resolves to the SAME market → the SAME signature. Proves the
    unified router leaves the green gamma-URL form byte-identical."""
    lg = ForecastLedger(db_path=str(tmp_path / "sig2.db"))
    lg.initialize_schema()
    event = _event([_market()])

    def fake_read(url, label, **kw):
        return event if "/events/slug/" in url else []

    monkeypatch.setattr(sa, "_read_json_endpoint", fake_read)
    bare = lg._polymarket_source_signature("new-hampshire-senate-election-winner")
    gamma = lg._polymarket_source_signature(f"{BASE}/events/slug/new-hampshire-senate-election-winner")
    assert bare == gamma
    assert not bare.startswith("missing:")


# ── one bounded live probe (skipped by default; run with -m integration) ─────
@pytest.mark.integration
def test_live_green_signatures_stable_and_failing_form_recovers():
    lg = ForecastLedger(db_path=":memory:")
    lg.initialize_schema()
    # 1) the two GREEN watches reproduce their EXACT stored signatures (stability)
    for source, stored in LIVE_GREEN.items():
        assert lg._polymarket_source_signature(source) == stored
    # 2) a failing STRUCTURED form (bare event slug) now yields a real signature
    sig = lg._polymarket_source_signature("texas-senate-election-winner")
    assert sig.startswith("polymarket:1:") and not sig.startswith("missing:")
