"""Load yahoo market observations as forecasting evidence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlencode, urlparse
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .economic_records import YahooFinancePriceObservation
from .values import _first_present, _list_get, _optional_float, _optional_str

def load_yahoo_finance_prices(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    range_value: str = "1mo",
    interval: str = "1d",
    api_base_url: str = "https://query1.finance.yahoo.com/v8/finance/chart",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[YahooFinancePriceObservation]:
    """Load Yahoo Finance chart observations as timestamped market evidence."""

    symbol = _yahoo_symbol(source)
    if limit <= 0:
        raise ValidationError("yahoo import --limit must be positive")
    normalized_interval = _yahoo_interval(interval)
    normalized_range = _yahoo_range(range_value)
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _yahoo_chart_endpoint(
        symbol,
        range_value=normalized_range,
        interval=normalized_interval,
        api_base_url=api_base_url,
    )
    payload = _read_json_endpoint(endpoint, "yahoo finance chart")
    return _yahoo_prices_from_payload(payload, symbol=symbol, interval=normalized_interval,
                                      range_value=normalized_range, endpoint=endpoint,
                                      since_dt=since_dt, limit=limit)


def _yahoo_prices_from_payload(payload, *, symbol, interval, range_value, endpoint, since_dt=None, limit=10):
    """Parse the requested instrument; chart bar times are not publication times."""
    result = _yahoo_chart_result(payload)
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    timestamps = result.get("timestamp") if isinstance(result.get("timestamp"), list) else []
    indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
    quote_rows = indicators.get("quote") if isinstance(indicators.get("quote"), list) else []
    quote_row = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
    closes = _yahoo_series(quote_row.get("close"))
    opens = _yahoo_series(quote_row.get("open"))
    highs = _yahoo_series(quote_row.get("high"))
    lows = _yahoo_series(quote_row.get("low"))
    volumes = _yahoo_series(quote_row.get("volume"))
    if not timestamps or not closes:
        raise ValidationError("yahoo finance chart response contains no price observations")

    effective_symbol = _optional_str(meta.get("symbol"))
    if effective_symbol is None or effective_symbol.upper() != symbol.upper():
        raise ValidationError("yahoo finance returned a missing or different symbol")
    if len(closes) != len(timestamps) or any(values and len(values) != len(timestamps)
                                           for values in (opens, highs, lows, volumes)):
        raise ValidationError("yahoo finance price arrays do not match timestamps")
    currency = _optional_str(meta.get("currency"))
    exchange_name = _optional_str(_first_present(meta.get("exchangeName"), meta.get("fullExchangeName")))
    observations: list[YahooFinancePriceObservation] = []
    for index, raw_timestamp in enumerate(timestamps):
        observation_time = _yahoo_timestamp(raw_timestamp)
        if observation_time is None:
            continue
        observation_dt = timestamp_to_datetime(observation_time)
        if since_dt is not None and observation_dt is not None and observation_dt < since_dt:
            continue
        close_price = _yahoo_optional_number(_list_get(closes, index))
        if close_price is None:
            continue
        observations.append(
            YahooFinancePriceObservation(
                symbol=effective_symbol,
                interval=interval,
                observation_time=observation_time,
                open_price=_yahoo_optional_number(_list_get(opens, index)),
                high_price=_yahoo_optional_number(_list_get(highs, index)),
                low_price=_yahoo_optional_number(_list_get(lows, index)),
                close_price=close_price,
                volume=_yahoo_optional_number(_list_get(volumes, index)),
                published_at=None,
                currency=currency,
                exchange_name=exchange_name,
                source_url=f"https://finance.yahoo.com/quote/{quote(effective_symbol, safe='=^.-')}",
                source_name="Yahoo Finance",
                entry_id=f"{effective_symbol}:{interval}:{observation_time}",
                raw={
                    "endpoint": endpoint,
                    "timestamp": raw_timestamp,
                    "symbol": effective_symbol,
                    "range": range_value,
                    "interval": interval,
                    "meta": dict(meta),
                },
            )
        )
    observations.sort(key=lambda item: item.observation_time)
    return observations[-limit:]


def _yahoo_symbol(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if "quote" in parts:
            index = parts.index("quote")
            value = parts[index + 1] if index + 1 < len(parts) else ""
        elif parts:
            value = parts[-1]
    symbol = value.strip().upper()
    if not symbol:
        raise ValidationError("yahoo source must be a symbol, yahoo:<symbol>, or Yahoo Finance quote URL")
    if any(character.isspace() for character in symbol) or "/" in symbol:
        raise ValidationError("yahoo symbols cannot contain whitespace or slashes")
    return symbol


def _yahoo_interval(value: str | None) -> str:
    interval = (value or "1d").strip().lower()
    allowed = {"1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo"}
    if interval not in allowed:
        raise ValidationError("yahoo import --interval must be a Yahoo Finance chart interval")
    return interval


def _yahoo_range(value: str | None) -> str:
    range_value = (value or "1mo").strip().lower()
    allowed = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
    if range_value not in allowed:
        raise ValidationError("yahoo import --range must be a Yahoo Finance chart range")
    return range_value


def _yahoo_chart_endpoint(symbol: str, *, range_value: str, interval: str, api_base_url: str) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("yahoo import --api-base-url cannot be empty")
    if "{symbol}" in base:
        endpoint = base.replace("{symbol}", quote(symbol, safe="=^.-"))
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{urlencode({'range': range_value, 'interval': interval})}"
    endpoint = f"{base.rstrip('/')}/{quote(symbol, safe='=^.-')}"
    return f"{endpoint}?{urlencode({'range': range_value, 'interval': interval})}"


def _yahoo_chart_result(payload: object) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("yahoo finance chart response must be a JSON object")
    chart = payload.get("chart") if isinstance(payload.get("chart"), dict) else {}
    error = chart.get("error")
    if error:
        raise ValidationError(f"yahoo finance chart request failed: {error}")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise ValidationError("yahoo finance chart response must include chart.result")
    return results[0]


def _yahoo_series(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _yahoo_timestamp(value: object) -> str | None:
    number = None if isinstance(value, bool) else _optional_float(value)
    if number is None:
        return None
    try:
        return datetime.fromtimestamp(number, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _yahoo_optional_number(value: object) -> float | int | str | None:
    if value is None:
        return None
    number = None if isinstance(value, bool) else _optional_float(value)
    if number is None:
        raise ValidationError("yahoo price must be finite numeric data")
    return int(number) if number.is_integer() else number
