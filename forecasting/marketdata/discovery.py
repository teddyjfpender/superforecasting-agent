"""Ranked catalog discovery plus bounded, independently failing live lookups.

Discovery is not a settlement binding. Remote identities stay custom selections;
only catalog entries carry reviewed dimensions and revision policies.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable
from urllib.parse import quote, urlencode

from pydantic import JsonValue

from forecasting.marketdata.discovery_worldbank import directory, search_directory
from forecasting.marketdata.model import SeriesRef
from forecasting.marketdata.provider import (
    JsonGetter,
    Provider,
    ProviderFailure,
    default_get_json,
)
from forecasting.marketdata.providers.yahoo import YahooProvider
from protocol.data_desk import DataCatalog
from protocol.rpc.markets import (
    MarketDiscoverRequest,
    MarketDiscoverResponse,
    MarketDiscoveryHit,
    MarketProviderStatus,
)

# Explicit language expansion, not an opaque model call or embedding dependency.
ALIASES = {
    "sterling": "british pound gbp",
    "yen": "japanese jpy",
    "us": "united states usa american",
    "uk": "united kingdom gbr british",
    "uae": "united arab emirates are",
    "korea": "south korea kor",
    "jobs": "employment payrolls unemployment labor labour",
    "prices": "inflation cpi hicp consumer",
    "growth": "gdp output",
    "housing": "housing home house mortgage residential",
    "rates": "rates interest yield policy sofr fedfunds dff",
    "oil": "oil petroleum crude brent wti",
    "food": "food agriculture grain wheat corn",
    "weather": "temperature precipitation wind rain",
    "rain": "precipitation rain",
    "bonds": "bonds credit yield treasury",
    "tech": "technology semiconductors computing",
    "population": "population demographics",
    "currency": "currency fx exchange",
}


COUNTRY_ALIASES = {
    "us": ["united states", "usa", "american"],
    "uk": ["united kingdom", "gbr", "british"],
    "uae": ["united arab emirates", "are"],
}


def terms(query: str) -> list[list[str]]:
    return [
        [word, *COUNTRY_ALIASES.get(word, ALIASES.get(word, "").split())]
        for word in query.casefold().split()
    ]


def _matches(group: list[str], text: str) -> bool:
    if group[0] in COUNTRY_ALIASES:
        return any(
            re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text) for term in group
        )
    return any(term in text for term in group)


def rank(query: str, text: str, symbol: str = "") -> int:
    """Every query term must match; exact identifiers outrank semantic matches."""
    query = query.strip().casefold()
    text = text.casefold()
    if not query:
        return 1
    if query == symbol.casefold():
        return 1000
    groups = terms(query)
    if not all(_matches(group, text) for group in groups):
        return 0
    return (
        100 + (100 if query in text else 0) + sum(group[0] in text for group in groups)
    )


def accepts(
    hit: MarketDiscoveryHit, request: MarketDiscoverRequest, catalog: DataCatalog
) -> bool:
    region = next((r for r in catalog.regions if r.id == request.region), None)
    return (
        (not request.provider or hit.provider == request.provider)
        and (not request.category or hit.category == request.category)
        and (not request.country or hit.country == request.country)
        and (not request.kind or hit.kind == request.kind)
        and (
            not request.region
            or hit.region == request.region
            or bool(region and hit.region in region.members)
        )
    )


def catalog_hits(
    catalog: DataCatalog, request: MarketDiscoverRequest
) -> list[MarketDiscoveryHit]:
    countries = {c.id: c.name for c in catalog.countries}
    categories = {c.id: f"{c.name} {' '.join(c.aliases)}" for c in catalog.categories}
    providers = {p.id: p.name for p in catalog.providers}
    scored: list[tuple[int, MarketDiscoveryHit]] = []
    for item in catalog.series:
        text = f"{item.id} {item.name} {countries.get(item.country or '', '')} {item.region} {categories.get(item.category, '')} {providers[item.provider]} {' '.join(item.tags)}"
        score = rank(request.query, text, item.symbol)
        hit = MarketDiscoveryHit(
            id=item.id,
            catalog_id=item.id,
            provider=item.provider,
            symbol=item.symbol,
            name=item.name,
            category=item.category,
            country=item.country,
            region=item.region,
            kind=item.kind,
            unit=item.unit,
            frequency=item.frequency,
            source_url=item.source_url,
            description=f"Catalog binding · revisions: {item.revision_policy}",
        )
        if score and accepts(hit, request, catalog):
            scored.append((score, hit))
    return [hit for _, hit in sorted(scored, key=lambda pair: -pair[0])]


def _rows(payload: JsonValue, key: str) -> list[dict[str, JsonValue]]:
    rows = payload.get(key) if isinstance(payload, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _text(row: dict[str, JsonValue], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def _hit(
    provider: str, symbol: str, name: str, category: str, **kwargs: str
) -> MarketDiscoveryHit:
    return MarketDiscoveryHit(
        id=f"custom:{provider}:{symbol}",
        provider=provider,
        symbol=symbol,
        name=name,
        category=category,
        **kwargs,
    )


class Discovery:
    """Service-owned, bounded search cache and request concurrency.

    A busy source never starts an unbounded queue. Successful results cache for
    ten minutes; failures are retried. Credential changes do not cache failures.
    """

    def __init__(
        self,
        providers: dict[str, Provider],
        resolve_key: Callable[[str], str | None],
        get_json: JsonGetter = default_get_json,
    ) -> None:
        self.providers = providers
        self.resolve_key = resolve_key
        self.get_json = get_json
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(5)
        self._directory_lock = threading.Lock()
        self._directories: (
            tuple[float, list[dict[str, JsonValue]], list[dict[str, JsonValue]]] | None
        ) = None
        self._cache: OrderedDict[
            tuple[str, str, bool], tuple[float, list[MarketDiscoveryHit]]
        ] = OrderedDict()

    def _live(self, provider: str, query: str) -> list[MarketDiscoveryHit]:
        if provider == "yahoo":
            source = self.providers.get(provider)
            if not isinstance(source, YahooProvider):
                return []
            return [
                _hit(
                    provider,
                    r.symbol,
                    r.name,
                    r.category.lower(),
                    source_url=f"https://finance.yahoo.com/quote/{quote(r.symbol, safe='')}",
                    description="Live symbol lookup · display only",
                )
                for r in source.search(query)
            ]
        if provider == "coingecko":
            payload = self.get_json(
                "https://api.coingecko.com/api/v3/search?" + urlencode({"query": query})
            )
            return [
                _hit(
                    provider,
                    _text(r, "id"),
                    _text(r, "name"),
                    "crypto",
                    unit="USD",
                    description=f"CoinGecko ID · ticker {_text(r, 'symbol')}",
                )
                for r in _rows(payload, "coins")[:30]
                if _text(r, "id") and _text(r, "name")
            ]
        if provider == "fred":
            key = self.resolve_key("fred")
            if key:
                payload = self.get_json(
                    "https://api.stlouisfed.org/fred/series/search?"
                    + urlencode({
                        "search_text": query,
                        "api_key": key,
                        "file_type": "json",
                        "limit": 40,
                        "order_by": "search_rank",
                        "sort_order": "desc",
                    })
                )
                return [
                    _hit(
                        provider,
                        _text(r, "id"),
                        _text(r, "title"),
                        "economy",
                        unit=_text(r, "units"),
                        kind="observation",
                        frequency=_text(r, "frequency").lower(),
                        source_url=f"https://fred.stlouisfed.org/series/{quote(_text(r, 'id'), safe='')}",
                        description="Live FRED search · latest vintage, not first release",
                    )
                    for r in _rows(payload, "seriess")
                    if _text(r, "id") and _text(r, "title")
                ]
            # The public CSV resolves an exact series ID without an API key.
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", query):
                source = self.providers.get("fred")
                rows = (
                    source.fetch([SeriesRef(provider="fred", symbol=query)])
                    if source
                    else []
                )
                if rows and rows[0].value is not None:
                    return [
                        _hit(
                            provider,
                            query,
                            query,
                            "economy",
                            kind="observation",
                            source_url=f"https://fred.stlouisfed.org/series/{query}",
                            description="Verified exact FRED ID · unit unknown; inspect source before use",
                        )
                    ]
                return []
            raise ProviderFailure(
                "credentials_required",
                "FRED keyword search needs a free API key; exact IDs work without one.",
            )
        if provider == "worldbank":
            with self._directory_lock:
                snapshot = self._directories
                if snapshot is None or time.monotonic() - snapshot[0] > 86400:
                    countries = directory(
                        self.get_json(
                            "https://api.worldbank.org/v2/country?format=json&per_page=400"
                        )
                    )
                    indicators = directory(
                        self.get_json(
                            "https://api.worldbank.org/v2/indicator?source=2&format=json&per_page=20000"
                        )
                    )
                    snapshot = (time.monotonic(), countries, indicators)
                    self._directories = snapshot
            return search_directory(query, snapshot[1], snapshot[2])
        if provider == "frankfurter":
            payload = self.get_json("https://api.frankfurter.app/currencies")
            if not isinstance(payload, dict):
                raise ProviderFailure("invalid_response", "Invalid currency directory")
            return [
                _hit(
                    provider,
                    code,
                    f"{name} per US dollar",
                    "fx",
                    unit=f"{code} per USD",
                    kind="observation",
                    frequency="daily",
                    description="ECB reference currency; USD base",
                )
                for code, name in payload.items()
                if code != "USD"
                and isinstance(name, str)
                and rank(query, f"{code} {name} currency fx", code)
            ]
        return []

    def _search(
        self, provider: str, query: str
    ) -> tuple[list[MarketDiscoveryHit], MarketProviderStatus]:
        cache_key = (provider, query, bool(self.resolve_key(provider)))
        with self._lock:
            cached = self._cache.get(cache_key)
            if cached and time.monotonic() - cached[0] < 600:
                self._cache.move_to_end(cache_key)
                return cached[1], MarketProviderStatus(
                    provider=provider, status="cached"
                )
        if not self._slots.acquire(blocking=False):
            return [], MarketProviderStatus(
                provider=provider, status="busy", message="Search busy; retry shortly."
            )
        try:
            results = self._live(provider, query)
            with self._lock:
                self._cache[cache_key] = (time.monotonic(), results)
                self._cache.move_to_end(cache_key)
                while len(self._cache) > 128:
                    self._cache.popitem(last=False)
            return results, MarketProviderStatus(provider=provider, status="ok")
        except ProviderFailure as exc:
            return [], MarketProviderStatus(
                provider=provider,
                status=exc.status,
                message=str(exc),
                retry_after=exc.retry_after,
            )
        except Exception:
            return [], MarketProviderStatus(
                provider=provider,
                status="unavailable",
                message="Live search unavailable; catalog results remain available.",
            )
        finally:
            self._slots.release()

    def discover(
        self, request: MarketDiscoverRequest, catalog: DataCatalog
    ) -> MarketDiscoverResponse:
        query = request.query.strip()
        results = catalog_hits(catalog, request)
        statuses = []
        live = ("yahoo", "fred", "coingecko", "frankfurter", "worldbank")
        selected = [
            p
            for p in live
            if p in self.providers and (not request.provider or request.provider == p)
        ]
        if len(query) >= 2:
            with ThreadPoolExecutor(
                max_workers=5, thread_name_prefix="market-discovery"
            ) as pool:
                for hits, status in pool.map(
                    lambda p: self._search(
                        p,
                        (request.country + " " + query)
                        if p == "worldbank"
                        and request.country
                        and request.country.casefold() not in query.casefold()
                        else query,
                    ),
                    selected,
                ):
                    statuses.append(status)
                    for hit in hits:
                        country = next(
                            (c for c in catalog.countries if c.id == hit.country), None
                        )
                        if country:
                            hit = hit.model_copy(update={"region": country.region})
                        if accepts(hit, request, catalog):
                            results.append(hit)
        # Explicitly report catalog-only coverage rather than suggesting that
        # an unsupported source's entire upstream directory has been searched.
        statuses.extend(
            MarketProviderStatus(
                provider=p.id,
                status="catalog_only",
                message="Reviewed catalog entries; live directory search is not available.",
            )
            for p in catalog.providers
            if p.id not in live and (not request.provider or p.id == request.provider)
        )
        unique: dict[tuple[str, str], MarketDiscoveryHit] = {}
        for hit in results:
            unique.setdefault((hit.provider, hit.symbol), hit)
        return MarketDiscoverResponse(
            results=list(unique.values())[:200], statuses=statuses
        )
