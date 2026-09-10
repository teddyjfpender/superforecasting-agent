"""Normalize optional values from heterogeneous evidence sources."""

from __future__ import annotations

import math


def _first_present(*values: object) -> object | None:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _optional_float(value: object) -> float | None:
    """Parse finite numbers; invalid or overflowing input is unavailable."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _optional_int(value: object) -> int | None:
    number = _optional_float(value)
    if number is None:
        return None
    try:
        return int(number)
    except (ValueError, OverflowError):
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _collapse_ws(value: str) -> str:
    return " ".join(value.split())


def _collapse_optional(value: object) -> str | None:
    text = _optional_str(value)
    return _collapse_ws(text) if text else None


def _list_get(values: list, index: int) -> object:
    return values[index] if 0 <= index < len(values) else None
