"""World Bank directory discovery, separate from observation acquisition.

Directory matches are display identities, not proof of an available observation
or a settlement contract. Empty source units remain explicitly unknown.
"""

from __future__ import annotations

import re

from pydantic import JsonValue

from forecasting.marketdata.provider import ProviderFailure
from protocol.rpc.markets import MarketDiscoveryHit


def directory(payload: JsonValue) -> list[dict[str, JsonValue]]:
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or not isinstance(payload[0], dict)
        or not isinstance(payload[1], list)
    ):
        raise ProviderFailure("invalid_response", "Invalid World Bank directory")
    # Never silently present one page as a complete directory.
    if payload[0].get("pages") != 1:
        raise ProviderFailure(
            "invalid_response",
            "World Bank directory exceeded the supported page budget",
        )
    return [item for item in payload[1] if isinstance(item, dict)]


def text(row: dict[str, JsonValue], key: str) -> str:
    value = row.get(key)
    return value.strip() if isinstance(value, str) else ""


def search_directory(
    query: str,
    countries: list[dict[str, JsonValue]],
    indicators: list[dict[str, JsonValue]],
) -> list[MarketDiscoveryHit]:
    from forecasting.marketdata.discovery import rank

    query = query.strip()
    exact = query.upper().split("/", 1)
    matched: list[tuple[dict[str, JsonValue], str]] = []
    for country in countries:
        region = country.get("region")
        if not isinstance(region, dict) or region.get("id") == "NA":
            continue  # Exclude aggregates; country IDs must mean an exact entity.
        name, code = text(country, "name"), text(country, "id")
        if len(code) != 3:
            continue
        if len(exact) == 2 and code == exact[0]:
            matched.append((country, exact[1]))
            continue
        # Remove a recognized country phrase, leaving indicator intent to rank.
        aliases: list[str] = [name, code]
        aliases += {
            "USA": ["US", "United States", "America"],
            "GBR": ["UK", "Britain"],
            "ARE": ["UAE"],
            "KOR": ["South Korea"],
            "TUR": ["Turkey"],
        }.get(code, [])
        for alias in sorted(aliases, key=lambda item: len(item), reverse=True):
            pattern = r"(?<!\w)" + re.escape(alias) + r"(?!\w)"
            remainder, count = re.subn(pattern, "", query, count=1, flags=re.I)
            if count:
                # A selected filter may prefix ISO while the user types its name.
                for other in aliases:
                    remainder = re.sub(
                        r"(?<!\w)" + re.escape(other) + r"(?!\w)",
                        "",
                        remainder,
                        flags=re.I,
                    )
                matched.append((country, remainder.strip()))
                break
    results: list[tuple[int, MarketDiscoveryHit]] = []
    for country, intent in matched[:3]:
        code, name = text(country, "id"), text(country, "name")
        for indicator in indicators:
            symbol, label = text(indicator, "id"), text(indicator, "name")
            score = rank(intent, f"{symbol} {label}", symbol)
            if not score or not symbol or not label:
                continue
            if label.casefold().startswith(intent.casefold()) and intent:
                score += 200
            if symbol in {
                "NY.GDP.MKTP.KD.ZG",
                "SP.POP.TOTL",
                "FP.CPI.TOTL.ZG",
                "SL.UEM.TOTL.ZS",
                "IT.NET.USER.ZS",
            }:
                score += 20
            identity = code + "/" + symbol
            results.append((
                score,
                MarketDiscoveryHit(
                    id="custom:worldbank:" + identity,
                    provider="worldbank",
                    symbol=identity,
                    name=f"{name} · {label}",
                    category="economy",
                    country=code,
                    kind="observation",
                    frequency="annual",
                    unit=text(indicator, "unit"),
                    source_url=f"https://data.worldbank.org/indicator/{symbol}?locations={code}",
                    description="World Bank WDI directory · data availability varies; latest vintage. "
                    + text(indicator, "sourceNote")[:240],
                ),
            ))
    return [hit for _, hit in sorted(results, key=lambda pair: -pair[0])[:80]]
