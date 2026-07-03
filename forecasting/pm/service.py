"""PMService — one facade over both venues with TTL caches.

Caches: list 30s, detail 15s, history 5m (books are always fetched fresh —
they move too fast to cache). Stale-while-revalidate: a stale hit returns the
old value immediately and refreshes in the background, so the desk never blocks
on a slow venue. Clock and background-spawn are injectable for deterministic
tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from forecasting.pm.aggregate import build_distribution
from forecasting.pm.history import downsample
from forecasting.pm.kalshi import KalshiClient
from forecasting.pm.model import PMDistribution, PMEvent, PMHistoryPoint, PMOrderBook
from forecasting.pm.polymarket import PolymarketClient

LIST_TTL = 30.0
DETAIL_TTL = 15.0
HISTORY_TTL = 300.0

Clock = Callable[[], float]
Spawn = Callable[[Callable[[], None]], None]

# ── history range → venue-native query parameters ────────────────────────────
# The TUI/agent speak a single lookback vocabulary ("1d"/"1w"/"1m"/"all"); each
# venue has its own enum, so translate here (one place) rather than leak a raw
# range string into a venue URL that would 400.

# Polymarket CLOB /prices-history `interval` ∈ {1m,1w,1d,6h,1h,max}. "all" is
# NOT a valid value — it must become "max".
_POLY_INTERVALS = frozenset({"1m", "1w", "1d", "6h", "1h", "max"})

# Kalshi /candlesticks REQUIRES start_ts + end_ts + period_interval; a request
# missing the window returns HTTP 400. Map the range to a sane (candle
# granularity in minutes, lookback window in seconds) pair so "1d" and "1w"
# actually fetch different data.
_KALSHI_RANGE: dict[str, tuple[int, int]] = {
    "1d": (60, 86_400),
    "1w": (60, 7 * 86_400),
    "1m": (1440, 31 * 86_400),
    "all": (1440, 366 * 86_400),
}


def _poly_interval(interval: str) -> str:
    v = (interval or "").strip().lower()
    if v == "all":
        return "max"
    return v if v in _POLY_INTERVALS else "1w"


def _kalshi_window(interval: str, period_interval: int | None) -> tuple[int, int, int]:
    """Resolve a range → (period_interval, start_ts, end_ts) for Kalshi.

    An explicit, valid ``period_interval`` wins for granularity; otherwise it is
    derived from the range so a long "all" window uses daily candles (staying
    under Kalshi's per-request candle cap). start/end are always supplied.
    """
    default_pi, window = _KALSHI_RANGE.get((interval or "").strip().lower(), (60, 7 * 86_400))
    pi = period_interval if period_interval in (1, 60, 1440) else default_pi
    end_ts = int(time.time())
    start_ts = end_ts - window
    return pi, start_ts, end_ts


def _default_spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


@dataclass
class _Entry:
    value: Any
    ts: float
    refreshing: bool = False


class TTLCache:
    """TTL cache with stale-while-revalidate. Thread-safe for real use;
    deterministic when ``clock``/``spawn`` are injected."""

    def __init__(self, *, clock: Clock, spawn: Spawn) -> None:
        self._clock = clock
        self._spawn = spawn
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float, loader: Callable[[], Any]) -> tuple[Any, str]:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            value = loader()
            with self._lock:
                self._entries[key] = _Entry(value=value, ts=self._clock())
            return value, "miss"
        age = now - entry.ts
        if age < ttl:
            return entry.value, "hit"
        # Stale: serve the old value, revalidate out of band.
        self._revalidate(key, loader, entry)
        return entry.value, "stale"

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def _revalidate(self, key: str, loader: Callable[[], Any], entry: _Entry) -> None:
        with self._lock:
            if entry.refreshing:
                return
            entry.refreshing = True

        def _run() -> None:
            try:
                value = loader()
            except Exception:  # pragma: no cover - refresh failures keep stale value
                with self._lock:
                    entry.refreshing = False
                return
            with self._lock:
                self._entries[key] = _Entry(value=value, ts=self._clock())

        self._spawn(_run)



def _event_volume(event: PMEvent) -> float:
    """Event liquidity for ranking: the event-level volume when the venue
    provides one, else the sum of its markets' volumes."""
    if event.volume is not None:
        return float(event.volume)
    return float(sum((m.volume or 0.0) for m in event.markets))

class PMService:
    """Search/list/detail/book/history across Polymarket + Kalshi."""

    def __init__(
        self,
        *,
        polymarket: PolymarketClient | None = None,
        kalshi: KalshiClient | None = None,
        clock: Clock | None = None,
        spawn: Spawn | None = None,
    ) -> None:
        self._poly = polymarket or PolymarketClient()
        self._kalshi = kalshi or KalshiClient()
        self._clock = clock or time.monotonic
        self._cache = TTLCache(clock=self._clock, spawn=spawn or _default_spawn)

    def _client(self, venue: str):
        v = venue.lower()
        if v in ("polymarket", "poly", "pm"):
            return self._poly
        if v in ("kalshi",):
            return self._kalshi
        raise ValueError(f"unknown venue {venue!r}")

    # ── list / search ────────────────────────────────────────────────────────

    def list_events(
        self,
        *,
        venue: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 40,
    ) -> list[tuple[PMEvent, PMDistribution]]:
        key = f"list:{venue or 'all'}:{query or ''}:{tag or ''}:{limit}"

        def _load() -> list[PMEvent]:
            # Venues fetch in PARALLEL: serial fetches doubled cold latency and
            # a text query costs seconds per venue (measured 4-5s serial).
            tasks: list = []
            if venue is None or venue.lower() != "kalshi":
                tasks.append(lambda: self._poly.list_events(query=query, tag=tag, limit=limit))
            if venue is None or venue.lower() in ("kalshi",):
                tasks.append(lambda: self._kalshi.list_events(query=query, limit=limit))
            per_venue: list[list[PMEvent]] = []
            if len(tasks) == 1:
                per_venue.append(tasks[0]())
            else:
                with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
                    futures = [pool.submit(t) for t in tasks]
                    for fut in futures:
                        try:
                            per_venue.append(fut.result())
                        except Exception:
                            per_venue.append([])  # one venue down never blanks the tape
            # Liquidity ranking WITHIN each venue (volume is the honest relevance
            # proxy — raw API order surfaces whatever a venue promotes), then
            # rank-INTERLEAVE across venues. Raw volumes are not comparable
            # across venues (Polymarket lifetime $ dwarfs Kalshi contract
            # volume), so a raw merge silently evicts one venue entirely;
            # interleaving keeps both represented at every list prefix.
            for lane in per_venue:
                lane.sort(key=lambda e: (-_event_volume(e), e.close_time or "9999"))
            merged: list[PMEvent] = []
            depth = max((len(lane) for lane in per_venue), default=0)
            for i in range(depth):
                for lane in per_venue:
                    if i < len(lane):
                        merged.append(lane[i])
            return merged[:limit]

        events, _ = self._cache.get(key, LIST_TTL, _load)
        return [(e, build_distribution(e)) for e in events]

    def search(self, query: str, *, limit: int = 40) -> list[tuple[PMEvent, PMDistribution]]:
        return self.list_events(query=query, limit=limit)

    # ── detail ───────────────────────────────────────────────────────────────

    def event_detail(self, venue: str, event_id: str) -> tuple[PMEvent, PMDistribution]:
        key = f"detail:{venue}:{event_id}"

        def _load() -> PMEvent:
            return self._client(venue).event(event_id)

        event, _ = self._cache.get(key, DETAIL_TTL, _load)
        return event, build_distribution(event)

    # ── book (always fresh) ──────────────────────────────────────────────────

    def orderbook(self, venue: str, market_id: str) -> PMOrderBook:
        client = self._client(venue)
        if isinstance(client, PolymarketClient):
            return client.book(market_id)
        return client.orderbook(market_id)

    # ── history ──────────────────────────────────────────────────────────────

    def history(
        self,
        venue: str,
        market_id: str,
        *,
        series_ticker: str | None = None,
        interval: str = "1w",
        period_interval: int | None = None,
        max_points: int = 200,
    ) -> list[PMHistoryPoint]:
        key = f"history:{venue}:{market_id}:{interval}:{period_interval}"

        def _load() -> list[PMHistoryPoint]:
            client = self._client(venue)
            if isinstance(client, PolymarketClient):
                return client.prices_history(market_id, interval=_poly_interval(interval))
            if series_ticker is None:
                raise ValueError("kalshi history requires series_ticker")
            pi, start_ts, end_ts = _kalshi_window(interval, period_interval)
            return client.candlesticks(
                series_ticker,
                market_id,
                period_interval=pi,
                start_ts=start_ts,
                end_ts=end_ts,
            )

        points, _ = self._cache.get(key, HISTORY_TTL, _load)
        return downsample(points, max_points=max_points)

    # ── stream hook (S2): invalidate touched entries on a tick ───────────────

    def invalidate_market(self, venue: str, event_id: str) -> None:
        self._cache.invalidate(f"detail:{venue}:{event_id}")


__all__ = ["PMService", "TTLCache", "LIST_TTL", "DETAIL_TTL", "HISTORY_TTL"]
