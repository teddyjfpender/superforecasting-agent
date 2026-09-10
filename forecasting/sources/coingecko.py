"""Load coingecko market observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .market_records import CoinGeckoMarketSnapshot
from .values import _collapse_optional, _optional_float, _optional_int, _optional_str
from forecasting.sources.dates import _optional_iso_timestamp

def load_coingecko_market_snapshots(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    vs_currency: str = "usd",
    api_base_url: str = "https://api.coingecko.com/api/v3/coins/markets",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CoinGeckoMarketSnapshot]:
    """Load CoinGecko market snapshots as timestamped crypto market evidence."""

    coin_ids = _coingecko_coin_ids(source)
    if limit <= 0:
        raise ValidationError("coingecko import --limit must be positive")
    normalized_currency = vs_currency.strip().lower()
    if not normalized_currency:
        raise ValidationError("coingecko import --vs-currency cannot be empty")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _coingecko_markets_endpoint(
        coin_ids,
        vs_currency=normalized_currency,
        limit=limit,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "coingecko markets")
    if not isinstance(payload, list):
        raise ValidationError("coingecko markets response must be an array")

    snapshots: list[CoinGeckoMarketSnapshot] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        coin_id = _optional_str(row.get("id"))
        if not coin_id:
            continue
        last_updated = _coingecko_timestamp(row.get("last_updated"))
        last_updated_dt = timestamp_to_datetime(last_updated) if last_updated else None
        if since_dt is not None and last_updated_dt is not None and last_updated_dt < since_dt:
            continue
        snapshots.append(
            CoinGeckoMarketSnapshot(
                coin_id=coin_id,
                symbol=_optional_str(row.get("symbol")),
                name=_collapse_optional(row.get("name")),
                vs_currency=normalized_currency,
                current_price=_coingecko_optional_number(row.get("current_price")),
                market_cap=_coingecko_optional_number(row.get("market_cap")),
                market_cap_rank=_optional_int(row.get("market_cap_rank")),
                total_volume=_coingecko_optional_number(row.get("total_volume")),
                price_change_percentage_24h=_coingecko_optional_number(
                    row.get("price_change_percentage_24h")
                ),
                last_updated=last_updated,
                source_url=f"https://www.coingecko.com/en/coins/{quote(coin_id, safe='')}",
                source_name="CoinGecko",
                entry_id=f"{coin_id}:{normalized_currency}:{last_updated or 'latest'}",
                raw={"endpoint": endpoint, "vs_currency": normalized_currency, **dict(row)},
            )
        )
        if len(snapshots) >= limit:
            break
    return snapshots


def _coingecko_coin_ids(source: str) -> list[str]:
    value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        host = parsed.netloc.lower()
        if host.endswith("coingecko.com"):
            if host.startswith("api.") and parsed.query:
                params = dict(parse_qsl(parsed.query, keep_blank_values=True))
                value = params.get("ids") or ""
            else:
                parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
                if "coins" in parts:
                    index = parts.index("coins")
                    value = parts[index + 1] if index + 1 < len(parts) else ""
                else:
                    value = ""
        else:
            raise ValidationError("coingecko source URL must be a CoinGecko coin page or markets API URL")
    normalized = [item.strip().lower() for item in re.split(r"[\s,]+", value) if item.strip()]
    if not normalized:
        raise ValidationError(
            "coingecko source must be a coin id, comma-separated ids, coingecko:<coin-id>, "
            "or a CoinGecko coin URL"
        )
    if any("/" in item for item in normalized):
        raise ValidationError("coingecko coin ids cannot contain slashes")
    return normalized


def _coingecko_markets_endpoint(
    coin_ids: list[str],
    *,
    vs_currency: str,
    limit: int,
    api_base_url: str,
) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("coingecko import --api-base-url cannot be empty")
    ids = ",".join(coin_ids)
    if "{ids}" in base or "{vs_currency}" in base:
        return base.replace("{ids}", quote(ids, safe=",")).replace("{vs_currency}", quote(vs_currency, safe=""))
    endpoint_base = base.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    params = {
        "vs_currency": vs_currency,
        "ids": ids,
        "order": "market_cap_desc",
        "per_page": min(max(limit, len(coin_ids)), 250),
        "page": 1,
        "price_change_percentage": "24h",
    }
    return f"{endpoint_base}{separator}{urlencode(params)}"


def _coingecko_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='coingecko timestamp')


def _coingecko_optional_number(value: object) -> float | int | str | None:
    number = _optional_float(value)
    if number is not None:
        if number.is_integer():
            return int(number)
        return number
    return _optional_str(value)
