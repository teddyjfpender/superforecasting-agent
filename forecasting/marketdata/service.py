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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from forecasting.marketdata.keys import resolve_key as _resolve_key
from forecasting.marketdata.model import Quote, SeriesRef
from forecasting.marketdata.provider import Provider
from forecasting.marketdata.providers.bea import BeaProvider
from forecasting.marketdata.providers.bls import BlsProvider
from forecasting.marketdata.providers.coingecko import CoingeckoProvider
from forecasting.marketdata.providers.frankfurter import FrankfurterProvider
from forecasting.marketdata.providers.fred import FredProvider
from forecasting.marketdata.providers.stooq import StooqProvider

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


class TTLCache:
    """TTL cache with stale-while-revalidate (thread-safe; deterministic when
    ``clock`` / ``spawn`` are injected)."""

    def __init__(self, *, clock: Clock, spawn: Spawn) -> None:
        self._clock = clock
        self._spawn = spawn
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: str, ttl: float, loader: Callable[[], object]) -> tuple[object, str]:
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            value = loader()
            with self._lock:
                self._entries[key] = _Entry(value=value, ts=self._clock())
            return value, "miss"
        if now - entry.ts < ttl:
            return entry.value, "hit"
        self._revalidate(key, loader, entry)
        return entry.value, "stale"

    def _revalidate(self, key: str, loader: Callable[[], object], entry: _Entry) -> None:
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


def _default_providers() -> dict[str, Provider]:
    return {
        "frankfurter": FrankfurterProvider(),
        "bea": BeaProvider(),
        "coingecko": CoingeckoProvider(),
        "fred": FredProvider(),
        "bls": BlsProvider(),
        "stooq": StooqProvider(),
    }


class MarketDataService:
    def __init__(
        self,
        *,
        providers: dict[str, Provider] | None = None,
        key_resolver: KeyResolver | None = None,
        clock: Clock | None = None,
        spawn: Spawn | None = None,
        ttl: float = QUOTES_TTL,
    ) -> None:
        self._providers = providers if providers is not None else _default_providers()
        self._resolve_key = key_resolver or _resolve_key
        self._clock = clock or time.monotonic
        self._ttl = ttl
        self._cache = TTLCache(clock=self._clock, spawn=spawn or _default_spawn)

    def _group(self, refs: list[SeriesRef]) -> dict[str, list[SeriesRef]]:
        grouped: dict[str, list[SeriesRef]] = {}
        for ref in refs:
            grouped.setdefault(ref.provider, []).append(ref)
        return grouped

    def _cache_key(self, provider: str, refs: list[SeriesRef]) -> str:
        parts = sorted(f"{r.symbol}#{r.line or ''}" for r in refs)
        return f"{provider}:{','.join(parts)}"

    def quotes(self, refs: list[SeriesRef]) -> list[Quote]:
        """Resolve every series, isolating a failing provider from the rest."""

        grouped = self._group(refs)

        def _run(provider_name: str, group: list[SeriesRef]) -> list[Quote]:
            provider = self._providers.get(provider_name)
            if provider is None:
                return []
            # Resolve the key for EVERY provider: required-key providers (bea) are
            # gated below, but optionally-keyed ones (fred JSON path, bls
            # registrationkey) must receive the key when present — client parity.
            api_key = self._resolve_key(provider_name)
            if provider.needs_key and not api_key:
                return []  # required-key provider without a key → skipped

            def _load() -> list[Quote]:
                return provider.fetch(group, api_key=api_key)

            try:
                value, _ = self._cache.get(self._cache_key(provider_name, group), self._ttl, _load)
                return list(value or [])
            except Exception:  # one provider down never blanks the tape
                logger.debug("marketdata provider %s failed", provider_name, exc_info=True)
                return []

        out: list[Quote] = []
        if len(grouped) <= 1:
            for name, group in grouped.items():
                out.extend(_run(name, group))
            return out
        with ThreadPoolExecutor(max_workers=len(grouped)) as pool:
            futures = {pool.submit(_run, name, group): name for name, group in grouped.items()}
            for fut in futures:
                out.extend(fut.result())
        return out


__all__ = ["MarketDataService", "TTLCache", "QUOTES_TTL"]
