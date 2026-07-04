"""CoinGecko (crypto spot) provider — ported one-to-one from ``marketFetch.ts``.

The client parser's exact semantics carried over verbatim:
* ONE batched call — ``/simple/price?ids=a,b,c&vs_currencies=usd&include_24hr_change=true``
  resolves every coin in the group in a single request (``parseCoingecko`` mapped
  over the same list).
* ``value`` is the ``usd`` spot; ``changePct`` is the raw ``usd_24h_change``;
  ``change`` is DERIVED — ``value * (pct / 100)`` — NOT ``value - prevClose``
  (CoinGecko gives the percentage, not a prior close, so there is no ``prevClose``
  and no ``history``).
* ``asOf`` is the fetch instant (``Date.now()``): CoinGecko's simple/price has no
  observation timestamp.
* A missing / error payload yields ``value = None`` (THE LAW) — absence renders
  "—", never a fabricated ``0``.
"""

from __future__ import annotations

import time

from forecasting.marketdata.model import Quote, SeriesRef, num
from forecasting.marketdata.provider import JsonGetter, default_get_json


def parse_coingecko(
    payload: object, series_list: list[SeriesRef], *, now_ms: int | None = None
) -> list[Quote]:
    """Parse a CoinGecko ``simple/price`` response into one :class:`Quote` per series."""

    now = now_ms if now_ms is not None else int(time.time() * 1000)
    data = payload if isinstance(payload, dict) else {}

    quotes: list[Quote] = []
    for s in series_list:
        row = data.get(s.symbol)
        row = row if isinstance(row, dict) else {}
        value = num(row.get("usd"))
        pct = num(row.get("usd_24h_change"))
        change = value * (pct / 100.0) if value is not None and pct is not None else None
        quotes.append(
            Quote(
                symbol=s.symbol,
                provider="coingecko",
                name=s.name,
                category=s.category,
                value=value,
                change=change,
                changePct=pct,
                prevClose=None,
                asOf=now,
                unit=s.unit,
                history=[],
            )
        )
    return quotes


class CoingeckoProvider:
    name = "coingecko"
    needs_key = False

    def __init__(self, get_json: JsonGetter | None = None) -> None:
        self._get_json = get_json or default_get_json

    def _url(self, ids: list[str]) -> str:
        # ids are coin slugs ("bitcoin","ethereum") — joined un-encoded, exactly
        # as the client did (``crypto.map(s => s.symbol).join(',')``).
        joined = ",".join(ids)
        return (
            "https://api.coingecko.com/api/v3/simple/price"
            f"?ids={joined}&vs_currencies=usd&include_24hr_change=true"
        )

    def fetch(self, series: list[SeriesRef], *, api_key: str | None = None) -> list[Quote]:
        if not series:
            return []
        payload = self._get_json(self._url([s.symbol for s in series]))
        return parse_coingecko(payload, series)


__all__ = ["CoingeckoProvider", "parse_coingecko"]
