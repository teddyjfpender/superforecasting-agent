"""PMService cache behaviour: TTL hit/miss + stale-while-revalidate (fake clock)."""

from __future__ import annotations

from dataclasses import replace

from forecasting.pm.service import BROWSE_OUTCOME_CAP, DETAIL_TTL, LIST_TTL, PMService, TTLCache, _serialize_pairs
from forecasting.pm import kalshi as kal
from forecasting.pm import polymarket as poly
from tests.forecasting.pm_helpers import RecordedFetch, load_fixture


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _inline_spawn(fn):
    fn()  # run refresh synchronously for deterministic tests


def test_ttlcache_miss_hit_stale_revalidate():
    clock = FakeClock()
    cache = TTLCache(clock=clock, spawn=_inline_spawn)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return f"v{calls['n']}"

    value, status = cache.get("k", 10.0, loader)
    assert value == "v1" and status == "miss" and calls["n"] == 1

    clock.advance(5.0)
    value, status = cache.get("k", 10.0, loader)
    assert value == "v1" and status == "hit" and calls["n"] == 1  # no reload

    clock.advance(6.0)  # now age 11 > ttl 10
    value, status = cache.get("k", 10.0, loader)
    assert status == "stale" and value == "v1"  # stale value served immediately
    assert calls["n"] == 2  # inline revalidate ran

    value, status = cache.get("k", 10.0, loader)
    assert value == "v2" and status == "hit"  # refreshed value now cached


def test_ttlcache_invalidate():
    clock = FakeClock()
    cache = TTLCache(clock=clock, spawn=_inline_spawn)
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    cache.get("k", 100.0, loader)
    cache.invalidate("k")
    cache.get("k", 100.0, loader)
    assert calls["n"] == 2


def _service_with_fixtures(clock):
    poly_fetch = RecordedFetch({"/events?": [load_fixture("polymarket_event_categorical.json")]})
    kal_fetch = RecordedFetch({"/events?": {"events": [load_fixture("kalshi_event_categorical.json")]}})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        kalshi=kal.KalshiClient(fetch=kal_fetch),
        clock=clock,
        spawn=_inline_spawn,
    )
    return svc, poly_fetch, kal_fetch


def test_service_list_merges_and_caches():
    clock = FakeClock()
    svc, poly_fetch, kal_fetch = _service_with_fixtures(clock)
    rows = svc.list_events(limit=10)
    venues = {ev.venue for ev, _ in rows}
    assert venues == {"polymarket", "kalshi"}
    assert all(dist for _, dist in rows)
    n_poly = len(poly_fetch.calls)

    # within TTL → cache hit, no new fetches
    clock.advance(LIST_TTL / 2)
    svc.list_events(limit=10)
    assert len(poly_fetch.calls) == n_poly

    # past TTL → stale-while-revalidate triggers exactly one refresh
    clock.advance(LIST_TTL + 1)
    svc.list_events(limit=10)
    assert len(poly_fetch.calls) == n_poly + 1


def _payload_service(clock, home, *, spawn=_inline_spawn):
    poly_fetch = RecordedFetch({"/events?": [load_fixture("polymarket_event_categorical.json")]})
    kal_fetch = RecordedFetch({"/events?": {"events": [load_fixture("kalshi_event_categorical.json")]}})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        kalshi=kal.KalshiClient(fetch=kal_fetch),
        clock=clock,
        spawn=spawn,
        home=home,
        disk_cache=True,
    )
    return svc, poly_fetch, kal_fetch


def test_list_events_payload_persists_tape_and_marks_fresh(tmp_path):
    """A cold browse fetch is a real network round-trip (stale=False) and its
    rendered rows land on disk for the next cold start."""
    clock = FakeClock()
    svc, poly_fetch, _ = _payload_service(clock, tmp_path)

    rows, stale = svc.list_events_payload(limit=10)
    assert rows and stale is False
    assert (tmp_path / "pm_cache.json").exists()

    # A warm hit re-serves from memory: not stale, no new fetch.
    n = len(poly_fetch.calls)
    _rows2, stale2 = svc.list_events_payload(limit=10)
    assert stale2 is False and len(poly_fetch.calls) == n


def test_cold_start_serves_disk_then_revalidates(tmp_path):
    """The core paint-then-refresh: a fresh gateway (empty memory) serves the
    persisted tape INSTANTLY marked stale, without a live fetch on the request
    path, and queues exactly one background revalidate that refreshes it live."""
    clock = FakeClock()

    # 1. Warm a service so the tape is persisted to disk.
    warm, _, _ = _payload_service(clock, tmp_path)
    warm.list_events_payload(limit=10)
    assert (tmp_path / "pm_cache.json").exists()

    # 2. A brand-new service (cold memory) with a CAPTURED spawn — so the
    #    revalidate is queued, not run — serves disk immediately.
    queued: list = []
    cold, poly_fetch, kal_fetch = _payload_service(clock, tmp_path, spawn=queued.append)
    rows, stale = cold.list_events_payload(limit=10)
    assert stale is True and rows, "painted from the disk cache, never blank"
    assert poly_fetch.calls == [] and kal_fetch.calls == [], "no live fetch on the request path"
    assert len(queued) == 1, "exactly one background revalidate queued"

    # 3. Run the queued revalidate: it fetches live, refreshing memory + disk.
    queued[0]()
    assert poly_fetch.calls, "the revalidate fetched live, off the request path"
    _rows2, stale2 = cold.list_events_payload(limit=10)
    assert stale2 is False, "now served fresh from memory"


def test_search_results_are_never_persisted_to_disk(tmp_path):
    """Only browse tapes seed the cold-start cache — a text query must never
    write a (soon-wrong) search result to disk."""
    clock = FakeClock()
    svc, _, _ = _payload_service(clock, tmp_path)
    svc.list_events_payload(venue="polymarket", query="zzz-no-such-market", limit=10)
    assert not (tmp_path / "pm_cache.json").exists()


def test_disk_cache_disabled_never_touches_home(tmp_path):
    """``disk_cache=False`` (the injectable escape hatch) neither reads nor
    writes the cache file."""
    clock = FakeClock()
    poly_fetch = RecordedFetch({"/events?": [load_fixture("polymarket_event_categorical.json")]})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        kalshi=kal.KalshiClient(fetch=RecordedFetch({"/events?": {"events": []}})),
        clock=clock,
        spawn=_inline_spawn,
        home=tmp_path,
        disk_cache=False,
    )
    rows, stale = svc.list_events_payload(limit=10)
    assert rows and stale is False
    assert not (tmp_path / "pm_cache.json").exists()


def test_kalshi_history_supplies_required_window_and_range_drives_fetch():
    clock = FakeClock()
    kal_fetch = RecordedFetch({"/candlesticks?": load_fixture("kalshi_candlesticks.json")})
    svc = PMService(
        kalshi=kal.KalshiClient(fetch=kal_fetch),
        clock=clock,
        spawn=_inline_spawn,
    )
    svc.history("kalshi", "TICK", series_ticker="SER", interval="1d")
    url = kal_fetch.calls[-1]
    # Kalshi 400s without start_ts/end_ts — both must be present alongside period_interval.
    assert "start_ts=" in url and "end_ts=" in url and "period_interval=" in url

    # "all" must actually change the fetch (different window + daily candles),
    # not merely the cache key.
    clock.advance(1.0)
    svc.history("kalshi", "TICK", series_ticker="SER", interval="all")
    all_url = kal_fetch.calls[-1]
    assert "period_interval=1440" in all_url
    assert url != all_url


def test_polymarket_history_maps_all_range_to_max_interval():
    clock = FakeClock()
    poly_fetch = RecordedFetch({"/prices-history?": load_fixture("polymarket_prices_history.json")})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        clock=clock,
        spawn=_inline_spawn,
    )
    svc.history("polymarket", "tok-1", interval="all")
    # Polymarket has no "all" interval — it must be translated to "max".
    assert "interval=max" in poly_fetch.calls[-1]
    assert "interval=all" not in poly_fetch.calls[-1]


def test_service_detail_builds_distribution():
    clock = FakeClock()
    poly_fetch = RecordedFetch({"/events/": load_fixture("polymarket_event_categorical.json")})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        clock=clock,
        spawn=_inline_spawn,
    )
    ev, dist = svc.event_detail("polymarket", "evt-1")
    assert ev.venue == "polymarket" and len(dist.outcomes) >= 3
    assert any("/events/evt-1" in c for c in poly_fetch.calls)


def test_list_events_rank_interleaves_venues():
    """Cross-venue volumes are NOT comparable (Polymarket lifetime $ dwarfs
    Kalshi): ranking is per-venue, then rank-interleaved, so the second venue
    survives every list prefix instead of being volume-evicted."""
    clock = FakeClock()
    poly_big = dict(load_fixture("polymarket_event_categorical.json"))
    poly_big["volume"] = 9_000_000.0
    poly_small = dict(load_fixture("polymarket_event_binary.json"))
    poly_small["volume"] = 8_000_000.0
    kal_tiny = dict(load_fixture("kalshi_event_categorical.json"))
    kal_tiny["volume"] = 500.0  # tiny in raw terms — must still make the page
    poly_fetch = RecordedFetch({"/events?": [poly_small, poly_big]})
    kal_fetch = RecordedFetch({"/events?": {"events": [kal_tiny]}})
    svc = PMService(
        polymarket=poly.PolymarketClient(fetch=poly_fetch),
        kalshi=kal.KalshiClient(fetch=kal_fetch),
        clock=clock,
        spawn=_inline_spawn,
    )
    rows = svc.list_events(limit=2)
    assert len(rows) == 2
    assert rows[0][0].volume == 9_000_000.0, "each venue's top event leads its lane"
    assert rows[1][0].venue == "kalshi", "rank-interleave: kalshi present at prefix 2"
    # And within a venue, higher volume outranks lower.
    rows3 = svc.list_events(limit=3)
    # Venue pattern is the contract (kalshi derives event volume from its
    # nested markets, so the exact number is the fixture's, not ours).
    assert [e.venue for e, _ in rows3] == ["polymarket", "kalshi", "polymarket"]
    assert rows3[0][0].volume == 9_000_000.0 and rows3[2][0].volume == 8_000_000.0


def test_full_catalog_persists_and_searches_locally(tmp_path):
    """Catalog search hydrates local index hits, never venue search APIs."""
    event = poly.parse_event(load_fixture("polymarket_event_binary.json"))

    class CatalogClient:
        def __init__(self, venue, title):
            self.venue = venue
            self.title = title
            self.search_calls = 0

        def catalog_events(self):
            return [{
                "venue": self.venue,
                "event_id": event.event_id,
                "title": self.title,
                "search": self.title.casefold(),
                "market_count": len(event.markets),
            }]

        def catalog_event(self, event_ref):
            assert event_ref == event.event_id
            return replace(event, venue=self.venue)

        def list_events(self, **kwargs):
            self.search_calls += 1
            raise AssertionError("remote search must not run after catalog warm")

    poly_client = CatalogClient("polymarket", "June CPI macro report")
    kalshi_client = CatalogClient("kalshi", "July jobs macro report")
    svc = PMService(
        polymarket=poly_client,
        kalshi=kalshi_client,
        clock=FakeClock(),
        spawn=_inline_spawn,
        home=tmp_path,
    )
    assert svc.refresh_catalog_async(force=True) is True
    status = svc.catalog_status()
    assert status["ready"] is True and status["events"] == 2
    assert (tmp_path / "pm_catalog.json").exists()

    rows = svc.list_events(query="june cpi", limit=10)
    assert len(rows) == 1 and rows[0][0].event_id == event.event_id
    both = svc.list_events(query="macro report", limit=2)
    assert [row[0].venue for row in both] == ["polymarket", "kalshi"]
    assert poly_client.search_calls == kalshi_client.search_calls == 0

    cold = PMService(
        polymarket=poly_client,
        kalshi=kalshi_client,
        clock=FakeClock(),
        spawn=_inline_spawn,
        home=tmp_path,
    )
    assert cold.catalog_status()["events"] == 2


def test_catalog_payload_paints_before_hydration_and_disambiguates(tmp_path):
    """RPC payload search is local-first: no venue call before first paint."""
    event = poly.parse_event(load_fixture("polymarket_event_binary.json"))
    queued: list = []

    class CatalogClient:
        def __init__(self):
            self.hydrated: list[str] = []

        def catalog_event(self, event_ref):
            self.hydrated.append(event_ref)
            return replace(event, event_id=event_ref)

        def list_events(self, **kwargs):
            raise AssertionError("catalog-backed payload search must not call remote search")

    client = CatalogClient()
    svc = PMService(
        polymarket=client,
        kalshi=client,
        clock=FakeClock(),
        spawn=queued.append,
        home=tmp_path,
    )
    svc._catalog = {
        "polymarket": [
            {
                "venue": "polymarket",
                "event_id": "game-14",
                "title": "Team A vs Team B",
                "sub_title": "Jul 14",
                "search": "team a team b",
            },
            {
                "venue": "polymarket",
                "event_id": "game-15",
                "title": "Team A vs Team B",
                "sub_title": "Jul 15",
                "search": "team a team b",
            },
        ]
    }

    rows, stale = svc.list_events_payload(query="team", limit=10)
    assert stale is True and client.hydrated == []
    assert [row["event"]["title"] for row in rows] == [
        "Team A vs Team B — Jul 14",
        "Team A vs Team B — Jul 15",
    ]
    assert all(row["event"]["markets"] == [] for row in rows)
    assert len(queued) == 1

    queued.pop()()
    hydrated, stale = svc.list_events_payload(query="team", limit=10)
    assert stale is False and len(client.hydrated) == 2
    assert all(row["event"]["markets"] for row in hydrated)


def test_browse_payload_caps_oversized_events_but_detail_stays_full():
    event = poly.parse_event(load_fixture("polymarket_event_binary.json"))
    market = event.markets[0]
    from forecasting.pm.aggregate import build_distribution

    oversized = replace(
        event,
        markets=tuple(replace(market, market_id=f"m{i}", label=f"Outcome {i}") for i in range(BROWSE_OUTCOME_CAP + 5)),
    )
    distribution = build_distribution(oversized)
    row = _serialize_pairs([(oversized, distribution)])[0]
    assert len(row["event"]["markets"]) == BROWSE_OUTCOME_CAP
    assert len(row["distribution"]["outcomes"]) == BROWSE_OUTCOME_CAP
    assert row["distribution"]["normalized"] is False
    assert len(oversized.markets) == BROWSE_OUTCOME_CAP + 5, "typed detail remains complete"
