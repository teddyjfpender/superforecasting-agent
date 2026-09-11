"""Load stooq market observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
import csv
from pathlib import Path
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse
from forecasting.models import ValidationError
from .economic_records import StooqPriceObservation
from .dates import _fred_date
from .values import _optional_float

def load_stooq_prices(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    interval: str = "d",
    api_base_url: str = "https://stooq.com/q/d/l/",
    _read_text_endpoint: Callable[[str, str], str],
) -> list[StooqPriceObservation]:
    """Load Stooq historical price CSV rows as timestamped evidence."""

    normalized_source = source.strip()
    if not normalized_source:
        raise ValidationError("stooq import symbol or CSV URL is required")
    if limit <= 0:
        raise ValidationError("stooq import --limit must be positive")
    normalized_interval = _stooq_interval(interval)
    since_date = _fred_date(since, field_name="since") if since else None
    symbol, effective_interval, endpoint = _stooq_endpoint(
        normalized_source,
        interval=normalized_interval,
        api_base_url=api_base_url,
    )
    text = _read_text_endpoint(endpoint, "stooq prices")
    return _stooq_prices_from_text(text, symbol=symbol, interval=effective_interval,
                                   endpoint=endpoint, since_date=since_date, limit=limit)


def _stooq_prices_from_text(text, *, symbol, interval, endpoint, since_date=None, limit=10):
    """Parse price rows without fetching or assigning publication provenance."""
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValidationError("stooq prices CSV has no header row")
    if len({name.strip().lower() for name in reader.fieldnames}) != len(reader.fieldnames):
        raise ValidationError("stooq prices CSV has duplicate columns")
    date_key = _stooq_column(reader.fieldnames, "date")
    close_key = _stooq_column(reader.fieldnames, "close")
    open_key = _stooq_column(reader.fieldnames, "open", required=False)
    high_key = _stooq_column(reader.fieldnames, "high", required=False)
    low_key = _stooq_column(reader.fieldnames, "low", required=False)
    volume_key = _stooq_column(reader.fieldnames, "volume", required=False)

    observations: list[StooqPriceObservation] = []
    for index, row in enumerate(reader):
        if None in row or any(value is None for value in row.values()):
            raise ValidationError("stooq prices CSV row does not match its columns")
        raw_date = str(row.get(date_key) or "").strip()
        observation_date = _fred_date(raw_date, field_name="stooq observation date")
        if observation_date is None:
            continue
        if since_date is not None and observation_date < since_date:
            continue
        close_price = _stooq_optional_number(row.get(close_key))
        if close_price is None:
            continue
        observations.append(
            StooqPriceObservation(
                symbol=symbol,
                interval=interval,
                observation_date=observation_date.isoformat(),
                open_price=_stooq_optional_number(row.get(open_key)) if open_key else None,
                high_price=_stooq_optional_number(row.get(high_key)) if high_key else None,
                low_price=_stooq_optional_number(row.get(low_key)) if low_key else None,
                close_price=close_price,
                volume=_stooq_optional_number(row.get(volume_key)) if volume_key else None,
                published_at=None,
                source_url=endpoint,
                source_name="Stooq",
                entry_id=f"{symbol}:{interval}:{observation_date.isoformat()}",
                raw={"row_index": index, **dict(row)},
            )
        )
    observations.sort(key=lambda item: item.observation_date)
    return observations[-limit:]


def _stooq_interval(value: str | None) -> str:
    interval = (value or "d").strip().lower()
    if interval not in {"d", "w", "m"}:
        raise ValidationError("stooq import --interval must be one of d, w, or m")
    return interval


def _stooq_endpoint(source: str, *, interval: str, api_base_url: str) -> tuple[str, str, str]:
    raw = source.strip()
    if raw.startswith("stooq:"):
        raw = raw.split(":", 1)[1].strip()
    if raw.startswith(("http://", "https://")):
        parsed = urlparse(raw)
        params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        symbol = str(params.get("s") or Path(unquote(parsed.path)).stem or raw).strip()
        effective_interval = _stooq_interval(str(params.get("i") or interval))
        return symbol or raw, effective_interval, raw
    symbol = raw
    base = api_base_url.strip()
    if not base:
        raise ValidationError("stooq import --api-base-url cannot be empty")
    if "{symbol}" in base or "{interval}" in base:
        endpoint = base.replace("{symbol}", quote(symbol, safe="")).replace("{interval}", quote(interval, safe=""))
        return symbol, interval, endpoint
    endpoint_base = base.rstrip("?&")
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode({'s': symbol.lower(), 'i': interval})}"
    return symbol, interval, endpoint


def _stooq_column(fieldnames: list[str], name: str, *, required: bool = True) -> str | None:
    for field in fieldnames:
        if field.strip().lower() == name:
            return field
    if required:
        raise ValidationError(f"stooq prices CSV has no {name} column")
    return None


def _stooq_optional_number(value: object) -> float | int | str | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw in {"", "-", "."}:
        return None
    number = _optional_float(raw)
    if number is None:
        raise ValidationError("stooq price must be finite numeric data")
    if number.is_integer():
        return int(number)
    return number
