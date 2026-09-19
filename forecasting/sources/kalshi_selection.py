"""Select one identified Kalshi market without relying on response ordering."""

from __future__ import annotations

from typing import TypeGuard
from urllib.parse import parse_qs, unquote, urlparse

from forecasting.models import ValidationError


def kalshi_requested_ticker(endpoint: str) -> str | None:
    """Validate a single-market selector before acquisition starts."""
    parsed = urlparse(endpoint)
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    identifiers = []
    if len(parts) >= 2 and parts[-2].lower() == "markets":
        identifiers.append(parts[-1])
    query = parse_qs(parsed.query, keep_blank_values=True)
    for key in ("ticker", "tickers"):
        for value in query.get(key, []):
            identifiers.extend(value.split(","))
    expected = {value.strip().upper() for value in identifiers}
    if "" in expected or len(expected) > 1:
        raise ValidationError("kalshi single-market import requires one ticker")

    return next(iter(expected), None)


def select_kalshi_market(
    payload: object, *, expected_ticker: str | None
) -> dict[str, object]:
    """Bind responses to a ticker; reject ambiguous catalogs and mirror results.

    Custom mirror URLs without a ticker may supply one identified market. A
    collection never means its first row: explicit ticker filters must select
    exactly one matching record, even when a server ignores its query filter.
    """
    if not _is_record(payload):
        raise ValidationError("kalshi market response must be a JSON object")
    if "market" in payload:
        rows = [payload["market"]]
    elif "markets" in payload:
        rows = payload["markets"]
        if not isinstance(rows, list):
            raise ValidationError("kalshi markets must be a list")
    else:
        rows = [payload]
    markets: list[dict[str, object]] = []
    for row in rows:
        if not _is_record(row):
            raise ValidationError("kalshi market entry must be an object")
        ticker = row.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValidationError("kalshi market response is missing ticker identity")
        if expected_ticker is None or ticker.strip().upper() == expected_ticker:
            markets.append(row)
    if len(markets) != 1:
        raise ValidationError(
            "kalshi response must contain exactly one matching market"
        )
    return markets[0]


def _is_record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)
