"""CoinGecko spot quotes, preserving source time and exact change arithmetic.

The simple-price endpoint supplies percentage change, not an absolute delta.
Recover the previous value as price / (1 + return), then subtract. Unknown source
timestamps stay unknown; retrieval time is attached separately by the service.
"""

from __future__ import annotations

from urllib.parse import urlencode

from forecasting.marketdata.model import Quote, SeriesRef, num
from forecasting.marketdata.provider import JsonGetter, default_get_json


def parse_coingecko(
    payload: object, series_list: list[SeriesRef], *, now_ms: int | None = None
) -> list[Quote]:
    """Parse a CoinGecko ``simple/price`` response into one :class:`Quote` per series."""

    data = payload if isinstance(payload, dict) else {}

    quotes: list[Quote] = []
    for s in series_list:
        row = data.get(s.symbol)
        row = row if isinstance(row, dict) else {}
        value = num(row.get("usd"))
        pct = num(row.get("usd_24h_change"))
        previous = (
            value / (1 + pct / 100.0)
            if value is not None and pct is not None and pct > -100
            else None
        )
        change = (
            value - previous if value is not None and previous is not None else None
        )
        timestamp = num(row.get("last_updated_at"))
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
                asOf=int(timestamp * 1000)
                if timestamp is not None and timestamp > 0
                else 0,
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
        return "https://api.coingecko.com/api/v3/simple/price?" + urlencode({
            "ids": ",".join(ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_last_updated_at": "true",
        })

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]:
        if not series:
            return []
        payload = self._get_json(self._url([s.symbol for s in series]))
        return parse_coingecko(payload, series)


__all__ = ["CoingeckoProvider", "parse_coingecko"]
