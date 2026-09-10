"""PMService — one facade over both venues with TTL caches.

Caches: list 30s, detail 15s, history 5m (books are always fetched fresh —
they move too fast to cache). Stale-while-revalidate: a stale hit returns the
old value immediately and refreshes in the background, so the desk never blocks
on a slow venue. Clock and background-spawn are injectable for deterministic
tests.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import json
import logging
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from forecasting.pm.aggregate import build_distribution
from forecasting.pm.history import downsample
from forecasting.pm.kalshi import KalshiClient
from forecasting.pm.model import PMDistribution, PMEvent, PMHistoryPoint, PMOrderBook
from forecasting.pm.polymarket import PolymarketClient

LIST_TTL = 30.0
DETAIL_TTL = 15.0
HISTORY_TTL = 300.0
CATALOG_TTL = 3600.0
CATALOG_VERSION = 2

# Disk-persisted "tape" cache: the last-rendered browse rows are written to
# ``{home}/pm_cache.json`` (atomic) so a cold gateway start paints INSTANTLY
# from disk (marked stale) and revalidates live in the background — the same
# paint-then-refresh the operator already gets from markets.json's pmSaved,
# instead of a ~0.6s blank on every restart. Only browse tapes (no query/tag)
# are persisted; searches are never cached to disk (they'd go stale wrong).
PM_CACHE_FILE = "pm_cache.json"
PM_CATALOG_FILE = "pm_catalog.json"
_DISK_CACHE_VERSION = 1
_DISK_MAX_KEYS = 8  # tape keys are few (all/poly/kalshi × a couple limits)
BROWSE_OUTCOME_CAP = 25

Clock = Callable[[], float]
Spawn = Callable[[Callable[[], None]], None]
logger = logging.getLogger(__name__)

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

    def has(self, key: str) -> bool:
        """Whether an entry (fresh OR stale-revalidatable) is in memory. Lets the
        service decide to serve a disk-cached tape on a COLD miss instead of
        blocking on the synchronous loader ``get`` would run."""
        with self._lock:
            return key in self._entries

    def set(self, key: str, value: Any) -> None:
        """Publish a value produced by an out-of-band loader."""
        with self._lock:
            self._entries[key] = _Entry(value=value, ts=self._clock())

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


def _disambiguate_events(events: list[PMEvent]) -> list[PMEvent]:
    """Make same-title venue events visibly distinct without dropping them.

    Kalshi legitimately publishes separate dated games and party-specific
    margin ladders under the same headline. Treating those as duplicates loses
    markets; rendering the bare headline repeatedly looks broken. Add the
    smallest useful qualifier only when a result set actually collides.
    """
    groups: dict[str, list[PMEvent]] = {}
    for event in events:
        groups.setdefault(event.title.strip().casefold(), []).append(event)

    result: list[PMEvent] = []
    for event in events:
        group = groups.get(event.title.strip().casefold(), [])
        if len(group) < 2:
            result.append(event)
            continue

        dates = {item.close_time[:10] for item in group if item.close_time}
        qualifier = event.close_time[:10] if event.close_time and len(dates) > 1 else ""
        if not qualifier and event.markets:
            labels = {
                market.label.split(",", 1)[0].strip()
                for market in event.markets
                if market.label.strip()
            }
            if len(labels) == 1:
                label = next(iter(labels))
                if label.casefold() not in event.title.casefold():
                    qualifier = label
        qualifier = qualifier or event.event_id
        result.append(replace(event, title=f"{event.title} — {qualifier}"))
    return result


def _disambiguate_catalog_rows(rows: list[dict]) -> list[dict]:
    """Catalog equivalent of :func:`_disambiguate_events` for instant previews."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(row.get("title") or "").strip().casefold(), []).append(row)

    result: list[dict] = []
    for row in rows:
        copied = dict(row)
        title = str(row.get("title") or "").strip()
        group = groups.get(title.casefold(), [])
        if title and len(group) > 1:
            subtitle = str(row.get("sub_title") or "").strip()
            qualifier = subtitle if subtitle and subtitle.casefold() not in title.casefold() else ""
            copied["title"] = f"{title} — {qualifier or row.get('event_id') or 'market'}"
        result.append(copied)
    return result


def _catalog_preview_event(row: dict) -> PMEvent:
    volume = row.get("volume")
    try:
        parsed_volume = None if volume in (None, "") else float(volume)
    except (TypeError, ValueError):
        parsed_volume = None
    return PMEvent(
        venue=str(row.get("venue") or ""),
        event_id=str(row.get("event_id") or ""),
        title=str(row.get("title") or ""),
        slug=str(row.get("slug") or "") or None,
        category=str(row.get("category") or "") or None,
        close_time=str(row.get("close_time") or "") or None,
        volume=parsed_volume,
        url=str(row.get("url") or "") or None,
    )


def _serialize_pairs(
    pairs: list[tuple[PMEvent, PMDistribution]],
) -> list[dict]:
    """The pm.list wire shape: one ``{event, distribution}`` row per pair."""
    rows: list[dict] = []
    for event, distribution in pairs:
        event_payload = event.to_dict()
        distribution_payload = distribution.to_dict()
        outcomes = distribution_payload.get("outcomes") or []
        if len(outcomes) > BROWSE_OUTCOME_CAP:
            outcomes = outcomes[:BROWSE_OUTCOME_CAP]
            keep = {str(outcome.get("market_id") or "") for outcome in outcomes}
            event_payload["markets"] = [
                market
                for market in event_payload.get("markets", [])
                if str(market.get("market_id") or "") in keep
            ]
            distribution_payload["outcomes"] = outcomes
            distribution_payload["normalized"] = False
            distribution_payload.setdefault("notes", []).append(
                f"browse preview shows {BROWSE_OUTCOME_CAP} of {len(distribution.outcomes)} outcomes; open the event for full detail"
            )
        rows.append({"event": event_payload, "distribution": distribution_payload})
    return rows

class PMService:
    """Search/list/detail/book/history across Polymarket + Kalshi."""

    def __init__(
        self,
        *,
        polymarket: PolymarketClient | None = None,
        kalshi: KalshiClient | None = None,
        clock: Clock | None = None,
        spawn: Spawn | None = None,
        home: str | Path | None = None,
        disk_cache: bool = True,
    ) -> None:
        self._poly = polymarket or PolymarketClient()
        self._kalshi = kalshi or KalshiClient()
        self._clock = clock or time.monotonic
        self._spawn = spawn or _default_spawn
        self._cache = TTLCache(clock=self._clock, spawn=self._spawn)
        # Disk-persisted tape cache (see PM_CACHE_FILE). ``_disk`` is lazily
        # loaded from ``{home}/pm_cache.json`` on first use; ``_revalidating``
        # de-dupes the background revalidate a cold disk-serve kicks off.
        self._home = home
        self._disk_cache = disk_cache
        self._disk: dict[str, dict] | None = None
        self._disk_lock = threading.Lock()
        self._revalidating: set[str] = set()
        self._catalog: dict[str, list[dict]] | None = None
        self._catalog_updated_at = 0.0
        self._catalog_refreshing = False
        self._catalog_lock = threading.Lock()

    def _client(self, venue: str):
        v = venue.lower()
        if v in ("polymarket", "poly", "pm"):
            return self._poly
        if v in ("kalshi",):
            return self._kalshi
        raise ValueError(f"unknown venue {venue!r}")

    # ── list / search ────────────────────────────────────────────────────────

    def _list_key(
        self, venue: str | None, query: str | None, tag: str | None, limit: int
    ) -> str:
        return f"list:{venue or 'all'}:{query or ''}:{tag or ''}:{limit}"

    def _load_events(
        self, venue: str | None, query: str | None, tag: str | None, limit: int
    ) -> list[PMEvent]:
        if query and not tag:
            indexed = self._catalog_search(venue, query, limit)
            if indexed is not None:
                hydrated = self._hydrate_catalog(indexed)
                if hydrated or not indexed:
                    return hydrated
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
        return _disambiguate_events(merged[:limit])

    def _catalog_search(
        self, venue: str | None, query: str, limit: int
    ) -> list[dict] | None:
        self._ensure_catalog_loaded()
        catalog = self._catalog or {}
        wanted = (venue or "").strip().lower()
        venues = (
            ["polymarket"] if wanted in {"polymarket", "poly", "pm"}
            else ["kalshi"] if wanted == "kalshi"
            else ["polymarket", "kalshi"]
        )
        if not any(name in catalog for name in venues):
            return None
        terms = [part.casefold() for part in query.split() if part]
        lanes = [
            _disambiguate_catalog_rows([
                row
                for row in catalog.get(name, [])
                if all(term in str(row.get("search") or "") for term in terms)
            ])
            for name in venues
        ]
        needle = " ".join(query.casefold().split())
        for lane in lanes:
            lane.sort(
                key=lambda row: (
                    0 if str(row.get("title") or "").casefold() == needle else
                    1 if needle in str(row.get("title") or "").casefold() else
                    2 if needle in str(row.get("search") or "") else 3,
                    -(float(row.get("volume") or 0.0)),
                    str(row.get("title") or ""),
                )
            )
        matches: list[dict] = []
        for index in range(max((len(lane) for lane in lanes), default=0)):
            for lane in lanes:
                if index < len(lane):
                    matches.append(lane[index])
                    if len(matches) >= limit:
                        return matches
        return matches

    def _hydrate_catalog(self, rows: list[dict]) -> list[PMEvent]:
        def load(row: dict) -> PMEvent:
            client = self._client(str(row.get("venue") or ""))
            loader = getattr(client, "catalog_event", None)
            event = loader(str(row.get("event_id") or "")) if callable(loader) else client.event(
                str(row.get("event_id") or "")
            )
            title = str(row.get("title") or "").strip()
            return replace(event, title=title) if title and title != event.title else event

        if not rows:
            return []
        with ThreadPoolExecutor(max_workers=min(8, len(rows))) as pool:
            futures = [pool.submit(load, row) for row in rows]
            return [event for event in (self._future_value(f) for f in futures) if event is not None]

    @staticmethod
    def _future_value(future) -> PMEvent | None:
        try:
            return future.result()
        except Exception:
            return None

    def _list_with_status(
        self,
        *,
        venue: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 40,
    ) -> tuple[list[tuple[PMEvent, PMDistribution]], str]:
        key = self._list_key(venue, query, tag, limit)
        events, status = self._cache.get(
            key, LIST_TTL, lambda: self._load_events(venue, query, tag, limit)
        )
        return [(e, build_distribution(e)) for e in events], status

    def list_events(
        self,
        *,
        venue: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 40,
    ) -> list[tuple[PMEvent, PMDistribution]]:
        pairs, _ = self._list_with_status(venue=venue, query=query, tag=tag, limit=limit)
        return pairs

    def list_events_payload(
        self,
        *,
        venue: str | None = None,
        query: str | None = None,
        tag: str | None = None,
        limit: int = 40,
    ) -> tuple[list[dict], bool]:
        """The serialised ``[{event, distribution}]`` rows the pm.list RPC emits,
        plus a ``stale`` flag.

        On a COLD gateway start the in-memory cache is empty; rather than block
        the first paint on the ~0.6s live fetch, a persisted browse tape is
        served IMMEDIATELY from disk (``stale=True``) and a single background
        revalidate refreshes the live rows + rewrites disk. Rows always carry
        their ORIGINAL honest estimates — the stale marker is the only thing the
        UI needs to show, subtly, that a live refresh is in flight.
        """
        key = self._list_key(venue, query, tag, limit)
        is_tape = not (query or tag)

        # A catalog query is a local index lookup, so its first useful paint must
        # never wait for 30 per-event venue requests. Return lightweight rows
        # immediately and hydrate the probabilities in the background. A repeat
        # call sees the hydrated value through the normal in-memory cache.
        if query and not tag and not self._cache.has(key):
            indexed = self._catalog_search(venue, query, limit)
            if indexed is not None:
                previews = [_catalog_preview_event(row) for row in indexed]
                if indexed:
                    self._spawn_catalog_hydrate(key, indexed)
                return _serialize_pairs([(event, build_distribution(event)) for event in previews]), bool(indexed)

        if is_tape and self._disk_cache and not self._cache.has(key):
            disk_rows = self._disk_get(key)
            if disk_rows is not None:
                self._spawn_tape_revalidate(key, venue, query, tag, limit)
                return disk_rows, True

        pairs, status = self._list_with_status(venue=venue, query=query, tag=tag, limit=limit)
        rows = _serialize_pairs(pairs)
        # Persist ONLY on a real network fetch (miss) — hits/stales are already on
        # disk from the miss that created them, so this keeps the file fresh for
        # the next cold start without rewriting it on every 30s warm poll.
        if is_tape and self._disk_cache and status == "miss":
            self._disk_put(key, rows)
        return rows, status == "stale"

    def search(self, query: str, *, limit: int = 40) -> list[tuple[PMEvent, PMDistribution]]:
        return self.list_events(query=query, limit=limit)

    # ── disk-persisted tape cache ────────────────────────────────────────────

    def _cache_path(self) -> Path:
        base = self._home
        if base is None:
            from superforecasting_agent.constants import get_agent_home

            base = get_agent_home()
        return Path(base) / PM_CACHE_FILE

    def _catalog_path(self) -> Path:
        base = self._home
        if base is None:
            from superforecasting_agent.constants import get_agent_home

            base = get_agent_home()
        return Path(base) / PM_CATALOG_FILE

    def _ensure_catalog_loaded(self) -> None:
        if self._catalog is not None:
            return
        with self._catalog_lock:
            if self._catalog is not None:
                return
            catalog: dict[str, list[dict]] = {}
            updated_at = 0.0
            if self._disk_cache:
                try:
                    raw = json.loads(self._catalog_path().read_text(encoding="utf-8"))
                    venues = raw.get("venues") if isinstance(raw, dict) else None
                    if isinstance(venues, dict):
                        catalog = {
                            name: [row for row in rows if isinstance(row, dict)]
                            for name, rows in venues.items()
                            if isinstance(rows, list)
                        }
                    updated_at = (
                        float(raw.get("updated_at") or 0.0)
                        if isinstance(raw, dict) and raw.get("version") == CATALOG_VERSION
                        else 0.0
                    )
                except (OSError, ValueError, TypeError):
                    pass
            self._catalog = catalog
            self._catalog_updated_at = updated_at

    def refresh_catalog_async(self, *, force: bool = False) -> bool:
        """Refresh the complete venue index off the request path."""
        self._ensure_catalog_loaded()
        with self._catalog_lock:
            if self._catalog_refreshing:
                return False
            if not force and self._catalog_updated_at and time.time() - self._catalog_updated_at < CATALOG_TTL:
                return False
            self._catalog_refreshing = True

        def run() -> None:
            started = time.monotonic()
            current = dict(self._catalog or {})
            refreshed: dict[str, list[dict]] = {}
            try:
                logger.info("prediction-market catalog refresh started")
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = {
                        "polymarket": pool.submit(self._poly.catalog_events),
                        "kalshi": pool.submit(self._kalshi.catalog_events),
                    }
                    for name, future in futures.items():
                        try:
                            refreshed[name] = future.result()
                        except Exception as exc:
                            logger.warning("%s catalog refresh failed: %s", name, exc)
                if refreshed:
                    current.update(refreshed)
                    updated_at = time.time()
                    with self._catalog_lock:
                        self._catalog = current
                        self._catalog_updated_at = updated_at
                    if self._disk_cache:
                        try:
                            from superforecasting_agent.storage.files import atomic_json_write

                            atomic_json_write(
                                self._catalog_path(),
                                {"version": CATALOG_VERSION, "updated_at": updated_at, "venues": current},
                            )
                        except Exception as exc:
                            logger.warning("prediction-market catalog cache write failed: %s", exc)
                    logger.info(
                        "prediction-market catalog refresh complete events=%d elapsed=%.1fs",
                        sum(len(rows) for rows in current.values()),
                        time.monotonic() - started,
                    )
            finally:
                with self._catalog_lock:
                    self._catalog_refreshing = False

        self._spawn(run)
        return True

    def catalog_status(self) -> dict[str, Any]:
        self._ensure_catalog_loaded()
        if self._catalog_updated_at and time.time() - self._catalog_updated_at >= CATALOG_TTL:
            self.refresh_catalog_async()
        catalog = self._catalog or {}
        venue_counts = {name: len(rows) for name, rows in catalog.items()}
        return {
            "ready": bool(venue_counts),
            "refreshing": self._catalog_refreshing,
            "updated_at": self._catalog_updated_at or None,
            "events": sum(venue_counts.values()),
            "markets": sum(
                int(row.get("market_count") or 0)
                for rows in catalog.values()
                for row in rows
            ),
            "venues": venue_counts,
        }

    def _ensure_disk_loaded(self) -> None:
        if self._disk is not None:
            return
        with self._disk_lock:
            if self._disk is not None:
                return
            data: dict[str, dict] = {}
            try:
                raw = json.loads(self._cache_path().read_text(encoding="utf-8"))
                keys = raw.get("keys") if isinstance(raw, dict) else None
                if isinstance(keys, dict):
                    data = {k: v for k, v in keys.items() if isinstance(v, dict)}
            except (OSError, ValueError):
                data = {}
            self._disk = data

    def _disk_get(self, key: str) -> list[dict] | None:
        self._ensure_disk_loaded()
        entry = (self._disk or {}).get(key)
        rows = entry.get("rows") if isinstance(entry, dict) else None
        return rows if isinstance(rows, list) and rows else None

    def _disk_put(self, key: str, rows: list[dict]) -> None:
        self._ensure_disk_loaded()
        with self._disk_lock:
            disk = self._disk if self._disk is not None else {}
            disk[key] = {"ts": time.time(), "rows": rows}
            # Bound the file: keep the most-recently-written tape keys only.
            if len(disk) > _DISK_MAX_KEYS:
                for stale_key in sorted(
                    disk, key=lambda k: disk[k].get("ts", 0.0)
                )[: len(disk) - _DISK_MAX_KEYS]:
                    disk.pop(stale_key, None)
            self._disk = disk
            snapshot = {"version": _DISK_CACHE_VERSION, "keys": dict(disk)}
        try:
            from superforecasting_agent.storage.files import atomic_json_write

            atomic_json_write(self._cache_path(), snapshot)
        except Exception:  # pragma: no cover - a cache write must never crash a fetch
            pass

    def _spawn_tape_revalidate(
        self, key: str, venue: str | None, query: str | None, tag: str | None, limit: int
    ) -> None:
        with self._disk_lock:
            if key in self._revalidating:
                return
            self._revalidating.add(key)

        def _run() -> None:
            try:
                pairs, status = self._list_with_status(
                    venue=venue, query=query, tag=tag, limit=limit
                )
                if status == "miss":
                    self._disk_put(key, _serialize_pairs(pairs))
            except Exception:  # pragma: no cover - a failed revalidate keeps disk rows
                pass
            finally:
                with self._disk_lock:
                    self._revalidating.discard(key)

        self._spawn(_run)

    def _spawn_catalog_hydrate(self, key: str, rows: list[dict]) -> None:
        """Hydrate local catalog hits once, outside the RPC critical path."""
        with self._disk_lock:
            if key in self._revalidating:
                return
            self._revalidating.add(key)

        def _run() -> None:
            events = [_catalog_preview_event(row) for row in rows]
            try:
                hydrated = self._hydrate_catalog(rows[:30])
                if hydrated:
                    by_id = {(event.venue, event.event_id): event for event in hydrated}
                    events = [by_id.get((event.venue, event.event_id), event) for event in events]
            except Exception:  # a venue outage keeps the useful local previews
                pass
            finally:
                self._cache.set(key, events)
                with self._disk_lock:
                    self._revalidating.discard(key)

        self._spawn(_run)

    def prewarm(self) -> None:
        """Best-effort background warm at gateway boot: fetch the default browse
        tape (so even the FIRST-ever run — no disk cache yet — pays the cold
        fetch off the request path) and prime the Kalshi series catalog (so the
        first '/' search doesn't pay the ~1.8s scan). Safe to call repeatedly."""
        try:
            self.list_events_payload(limit=40)
        except Exception:  # pragma: no cover - warm never crashes boot
            pass
        warm = getattr(self._kalshi, "warm_catalog", None)
        if callable(warm):
            try:
                warm()
            except Exception:  # pragma: no cover
                pass
        self.refresh_catalog_async()

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


__all__ = [
    "PMService",
    "TTLCache",
    "LIST_TTL",
    "DETAIL_TTL",
    "HISTORY_TTL",
    "CATALOG_TTL",
    "CATALOG_VERSION",
    "PM_CACHE_FILE",
    "PM_CATALOG_FILE",
    "BROWSE_OUTCOME_CAP",
]
