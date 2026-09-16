"""MarketDataService — one facade over every market-data provider.

* TTL + stale-while-revalidate cache (the ``forecasting.pm`` pattern, ported not
  imported so the data plane owns its own knob): a stale hit returns the old
  value immediately and refreshes out of band, so the desk never blocks on a
  slow provider.
* Parallel provider fan-out with PER-PROVIDER failure isolation: one provider
  raising (transport down) drops only ITS series — the rest of the tape still
  paints (the "one provider down ≠ blank tape" guarantee).
* Keys resolve through :mod:`forecasting.marketdata.keys` (the one shared store).

Clock / spawn / providers / key resolver are all injectable for deterministic,
network-free tests.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from forecasting.marketdata.catalog import load_catalog
from forecasting.marketdata.discovery import Discovery
from forecasting.marketdata.keys import resolve_key as _resolve_key
from forecasting.marketdata.model import DataEvents, Quote, SeriesRef, epoch_ms
from forecasting.marketdata.parsing import compare_observations
from forecasting.marketdata.provider import BatchPartitioner, Provider, ProviderFailure
from forecasting.marketdata.providers.bcb import BcbProvider
from forecasting.marketdata.providers.bea import BeaProvider
from forecasting.marketdata.providers.bls import BlsProvider
from forecasting.marketdata.providers.coingecko import CoingeckoProvider
from forecasting.marketdata.providers.country_indicators import (
    ImfProvider,
    WorldBankProvider,
)
from forecasting.marketdata.providers.europe import EcbProvider, EurostatProvider
from forecasting.marketdata.providers.frankfurter import FrankfurterProvider
from forecasting.marketdata.providers.fred import FredProvider
from forecasting.marketdata.providers.regional_statistics import (
    IbgeProvider,
    SingStatProvider,
)
from forecasting.marketdata.providers.sdmx import SdmxProvider
from forecasting.marketdata.providers.stooq import StooqProvider
from forecasting.marketdata.providers.weather import OpenMeteoProvider
from forecasting.marketdata.providers.yahoo import SearchResult, YahooProvider
from protocol.rpc.markets import MarketDiscoverRequest, MarketDiscoverResponse

logger = logging.getLogger(__name__)

QUOTES_TTL = 60.0  # FX + BEA move slowly (daily); 60s keeps the tape fresh & cheap

Clock = Callable[[], float]
Spawn = Callable[[Callable[[], None]], None]
KeyResolver = Callable[[str], str | None]


def _default_spawn(fn: Callable[[], None]) -> None:
    threading.Thread(target=fn, daemon=True).start()


@dataclass
class _Entry:
    value: object
    ts: float
    refreshing: bool = False
    error: Exception | None = None


class TTLCache:
    """TTL cache with stale-while-revalidate (thread-safe; deterministic when
    ``clock`` / ``spawn`` are injected)."""

    def __init__(self, *, clock: Clock, spawn: Spawn) -> None:
        self._clock = clock
        self._spawn = spawn
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._pending: dict[str, Future[object]] = {}

    def get(
        self, key: str, ttl: float, loader: Callable[[], object]
    ) -> tuple[object, str]:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                pending = self._pending.get(key)
                owner = pending is None
                if pending is None:
                    pending = Future()
                    self._pending[key] = pending
        if entry is None:
            if not owner:
                return pending.result(), "hit"
            try:
                value = loader()
                with self._lock:
                    self._entries[key] = _Entry(value=value, ts=self._clock())
                pending.set_result(value)
                return value, "miss"
            except BaseException as exc:
                pending.set_exception(exc)
                raise
            finally:
                with self._lock:
                    self._pending.pop(key, None)
        if now - entry.ts < ttl:
            return entry.value, "hit"
        self._revalidate(key, loader, entry)
        return entry.value, "stale"

    def _revalidate(
        self, key: str, loader: Callable[[], object], entry: _Entry
    ) -> None:
        with self._lock:
            if entry.refreshing:
                return
            entry.refreshing = True

        def _run() -> None:
            try:
                value = loader()
            except Exception as exc:  # refresh failures keep the last successful value
                with self._lock:
                    entry.refreshing = False
                    entry.error = exc
                return
            with self._lock:
                self._entries[key] = _Entry(value=value, ts=self._clock())

        try:
            self._spawn(_run)
        except Exception:
            with self._lock:
                entry.refreshing = False
            raise

    def error(self, key: str) -> Exception | None:
        with self._lock:
            entry = self._entries.get(key)
            return entry.error if entry else None


SEARCH_TTL = 300.0  # symbol lookups change rarely; 5-minute cache keeps them cheap


def _default_providers() -> dict[str, Provider]:
    return {
        "frankfurter": FrankfurterProvider(),
        "bea": BeaProvider(),
        "coingecko": CoingeckoProvider(),
        "fred": FredProvider(),
        "bls": BlsProvider(),
        "stooq": StooqProvider(),
        "yahoo": YahooProvider(),
        "worldbank": WorldBankProvider(),
        "imf": ImfProvider(),
        "ecb": EcbProvider(),
        "eurostat": EurostatProvider(),
        "bcb": BcbProvider(),
        "openmeteo": OpenMeteoProvider(),
        "abs": SdmxProvider("abs"),
        "bis": SdmxProvider("bis"),
        "oecd": SdmxProvider("oecd"),
        "singstat": SingStatProvider(),
        "ibge": IbgeProvider(),
    }


class MarketDataService:
    def __init__(
        self,
        *,
        providers: dict[str, Provider] | None = None,
        key_resolver: KeyResolver | None = None,
        clock: Clock | None = None,
        spawn: Spawn | None = None,
        ttl: float | None = None,
        wall_clock: Clock | None = None,
    ) -> None:
        self._providers = providers if providers is not None else _default_providers()
        self._resolve_key = key_resolver or _resolve_key
        self._discovery = Discovery(self._providers, self._resolve_key)
        self._clock = clock or time.monotonic
        self._ttl = ttl
        self._wall_clock = wall_clock or time.time
        self._cache = TTLCache(clock=self._clock, spawn=spawn or _default_spawn)

    def _group(self, refs: list[SeriesRef]) -> dict[tuple[str, str], list[SeriesRef]]:
        grouped: dict[tuple[str, str], list[SeriesRef]] = {}
        for ref in refs:
            provider = self._providers.get(ref.provider)
            batch = (
                provider.batch_key(ref)
                if isinstance(provider, BatchPartitioner)
                else ""
            )
            grouped.setdefault((ref.provider, batch), []).append(ref)
        return grouped

    def _cache_key(self, provider: str, refs: list[SeriesRef]) -> str:
        parts = sorted(f"{r.symbol}#{r.line or ''}#{r.catalog_id or ''}" for r in refs)
        return f"{provider}:{','.join(parts)}"

    def quotes(self, refs: list[SeriesRef]) -> list[Quote]:
        """Compatibility facade; consumers needing diagnostics use quote_result."""
        return self.quote_result(refs)[0]

    def quote_result(self, refs: list[SeriesRef]) -> tuple[list[Quote], list[dict]]:
        """Resolve a batch, reporting provider failures separately from no data."""
        catalog = load_catalog()
        entries = {entry.id: entry for entry in catalog.series}
        normalized = []
        for ref in refs:
            if ref.catalog_id:
                entry = entries.get(ref.catalog_id)
                if entry is None or (entry.provider, entry.symbol) != (
                    ref.provider,
                    ref.symbol,
                ):
                    raise ValueError(
                        "Catalog series identity does not match the request"
                    )
                ref = replace(
                    ref,
                    name=entry.name,
                    category=entry.category,
                    unit=entry.unit,
                    line=entry.line,
                )
            normalized.append(ref)
        grouped = self._group(normalized)

        def _run(
            provider_name: str, group: list[SeriesRef]
        ) -> tuple[list[Quote], dict]:
            status = {
                "provider": provider_name,
                "status": "ready",
                "message": None,
                "retry_after": None,
            }
            provider = self._providers.get(provider_name)
            if provider is None:
                return [], {
                    **status,
                    "status": "unsupported",
                    "message": "Provider is not available in this build",
                }
            api_key = self._resolve_key(provider_name)
            if provider.needs_key and not api_key:
                return [], {
                    **status,
                    "status": "credentials_required",
                    "message": "Connect this provider to retrieve data",
                }

            def _load() -> list[Quote]:
                values = provider.fetch(group, api_key=api_key)
                retrieved_at = datetime.fromtimestamp(
                    self._wall_clock(), timezone.utc
                ).isoformat()
                result = []
                for value in values:
                    if value.provider != provider_name or value.symbol not in {
                        r.symbol for r in group
                    }:
                        raise ProviderFailure(
                            "invalid_response",
                            "Source returned an unrequested measurement",
                        )
                    ref = next((r for r in group if r.symbol == value.symbol), None)
                    entry = (
                        entries.get(ref.catalog_id) if ref and ref.catalog_id else None
                    )
                    metadata = {"retrieved_at": retrieved_at}
                    if entry:
                        metadata.update(
                            catalog_id=entry.id,
                            source_url=entry.source_url,
                            source_family=entry.source_family,
                            kind=entry.kind,
                            revision_policy=entry.revision_policy,
                            refresh_seconds=entry.refresh_seconds,
                        )
                    bound = replace(value, **metadata)
                    if bound.comparison is None and bound.kind in {"observation", "reanalysis", "estimate"}:
                        bound = compare_observations(bound, bound.dated_history, entry.change_basis if entry else "previous_observation")
                    result.append(bound)
                return result

            ttl = (
                self._ttl
                if self._ttl is not None
                else min(
                    (
                        entries[r.catalog_id].refresh_seconds
                        if r.catalog_id
                        else QUOTES_TTL
                        for r in group
                    ),
                    default=QUOTES_TTL,
                )
            )
            key = self._cache_key(provider_name, group)
            try:
                value, cache_status = self._cache.get(key, ttl, _load)
                values = list(value or [])
                error = self._cache.error(key)
                if error is not None:
                    return values, {
                        **status,
                        "status": "stale",
                        "message": str(error)
                        if isinstance(error, ProviderFailure)
                        else "Refresh failed; showing saved data",
                    }
                if cache_status == "stale":
                    return values, {**status, "status": "refreshing"}
                if not any(q.value is not None for q in values):
                    return values, {
                        **status,
                        "status": "no_data",
                        "message": "No usable measurements returned",
                    }
                outdated = []
                now_ms = self._wall_clock() * 1000
                for quote in values:
                    entry = entries.get(quote.catalog_id)
                    if not entry or quote.value is None:
                        continue
                    if quote.kind == "forecast":
                        if quote.valid_until and epoch_ms(quote.valid_until) < now_ms:
                            outdated.append(quote.name)
                    elif entry.expected_lag_seconds is not None:
                        period_end = max(
                            (
                                epoch_ms(p.period_end)
                                for p in quote.dated_history
                                if p.value is not None
                            ),
                            default=quote.asOf,
                        )
                        if (
                            period_end
                            and now_ms - period_end > entry.expected_lag_seconds * 1000
                        ):
                            outdated.append(quote.name)
                if outdated:
                    return values, {
                        **status,
                        "status": "stale",
                        "message": "Source retrieved; observation or forecast window is older than its catalog allowance: "
                        + ", ".join(outdated),
                    }
                return values, status
            except ProviderFailure as exc:
                return [], {
                    **status,
                    "status": exc.status,
                    "message": str(exc),
                    "retry_after": exc.retry_after,
                }
            except (ValueError, TypeError, KeyError):
                return [], {
                    **status,
                    "status": "invalid_response",
                    "message": "Provider response does not match the selected measurement",
                }
            except Exception:
                # URLs can carry credentials: do not log raw HTTP exception text.
                logger.debug("marketdata provider %s failed", provider_name)
                return [], {
                    **status,
                    "status": "unavailable",
                    "message": "Unable to retrieve provider data",
                }

        if len(grouped) <= 1:
            results = [_run(name, group) for (name, _), group in grouped.items()]
        else:
            with ThreadPoolExecutor(max_workers=min(8, len(grouped))) as pool:
                futures = [
                    pool.submit(_run, name, group)
                    for (name, _), group in grouped.items()
                ]
                results = [future.result() for future in futures]
        quotes = [quote for values, _ in results for quote in values]
        by_provider: dict[str, list[dict]] = {}
        for _, status in results:
            by_provider.setdefault(status["provider"], []).append(status)
        statuses = []
        for provider_name, parts in by_provider.items():
            failures = [
                part for part in parts if part["status"] not in {"ready", "refreshing"}
            ]
            good = [
                quote
                for quote in quotes
                if quote.provider == provider_name and quote.value is not None
            ]
            if failures:
                status = dict(failures[0])
                if good and len(failures) < len(parts):
                    status.update(
                        status="partial",
                        message=f"{len(good)} series available; {failures[0]['message'] or 'some measurements are unavailable'}",
                    )
                statuses.append(status)
            else:
                statuses.append(
                    next(
                        (part for part in parts if part["status"] == "refreshing"),
                        parts[0],
                    )
                )
        return quotes, statuses

    def event_result(self, series_id: str) -> tuple[DataEvents | None, dict]:
        from forecasting.marketdata.providers.nws import fetch_nws_events

        entry = next(
            (item for item in load_catalog().series if item.id == series_id), None
        )
        if entry is None or entry.provider != "nws" or entry.kind != "event":
            raise ValueError("Unknown event-feed series")
        status = {
            "provider": entry.provider,
            "status": "ready",
            "message": None,
            "retry_after": None,
        }
        try:
            value, state = self._cache.get(
                "events:" + entry.id,
                entry.refresh_seconds,
                lambda: fetch_nws_events(entry),
            )
            if not isinstance(value, DataEvents):
                raise ValueError("Invalid event cache value")
            error = self._cache.error("events:" + entry.id)
            if error is not None:
                return value, {
                    **status,
                    "status": "stale",
                    "message": str(error)
                    if isinstance(error, ProviderFailure)
                    else "Refresh failed; showing saved events",
                }
            return value, {
                **status,
                "status": "refreshing" if state == "stale" else "ready",
            }
        except ProviderFailure as exc:
            return None, {
                **status,
                "status": exc.status,
                "message": str(exc),
                "retry_after": exc.retry_after,
            }

    def discover(self, request: MarketDiscoverRequest) -> MarketDiscoverResponse:
        return self._discovery.discover(request, load_catalog())

    def search(self, query: str) -> list[SearchResult]:
        """Cached live ticker search; an outage is distinct from no matches."""

        q = (query or "").strip()
        if not q:
            return []
        provider = self._providers.get("yahoo")
        searcher = getattr(provider, "search", None)
        if searcher is None:
            return []

        def _load() -> list[SearchResult]:
            try:
                return list(searcher(q))
            except ProviderFailure:
                raise
            except Exception:
                raise ProviderFailure(
                    "unavailable", "Live ticker search is unavailable"
                ) from None

        value, _ = self._cache.get(f"search:{q.lower()}", SEARCH_TTL, _load)
        return list(value or [])


__all__ = ["MarketDataService", "TTLCache", "QUOTES_TTL", "SEARCH_TTL"]
