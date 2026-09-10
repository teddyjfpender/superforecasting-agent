"""Shared ISO date conversion for evidence sources."""

from __future__ import annotations

from datetime import datetime, timezone
from .values import _optional_str
from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime

def _fred_date(value: str | None, *, field_name: str):
    if value in (None, ""):
        return None
    from datetime import date

    raw = str(value).strip()
    if not raw:
        return None
    try:
        if "T" not in raw and len(raw) == 10:
            return date.fromisoformat(raw)
        timestamp = parse_timestamp(raw, field_name=field_name)
        parsed = timestamp_to_datetime(timestamp)
        return parsed.date() if parsed is not None else None
    except (ValueError, ValidationError) as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 date or timestamp") from exc


def _fred_date_to_iso(value) -> str:
    from datetime import datetime

    return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _optional_epoch_or_iso_timestamp(value: object, *, field_name: str) -> str | None:
    if isinstance(value, (int, float)) and value > 0:
        try:
            number = float(value)
            if number > 10_000_000_000:
                number = number / 1000
            return datetime.fromtimestamp(number, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError, OSError):
            return None
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name=field_name)
    except ValidationError:
        return None

def _optional_iso_timestamp(value: object, *, field_name: str) -> str | None:
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name=field_name)
    except ValidationError:
        return None


def _optional_prediction_timestamp(value: object, *, field_name: str) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        from datetime import datetime

        try:
            seconds = float(value) / 1000 if float(value) > 10_000_000_000 else float(value)
            return (
                datetime.fromtimestamp(seconds, tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z")
            )
        except (ValueError, OverflowError, OSError):
            return None
    try:
        return parse_timestamp(str(value), field_name=field_name)
    except ValidationError:
        return None
