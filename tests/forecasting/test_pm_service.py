"""PMService cache behaviour: TTL hit/miss + stale-while-revalidate (fake clock)."""

from __future__ import annotations

from forecasting.pm.service import DETAIL_TTL, LIST_TTL, PMService, TTLCache
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
