"""Field-aware Kalshi quote conversion shared by display and evidence imports."""

from __future__ import annotations

import math
from collections.abc import Mapping

from forecasting.models import ValidationError


def kalshi_price(payload: Mapping[str, object], field: str) -> float | None:
    """Read dollars first, then legacy cents; never infer units from magnitude.

    Fixed-point dollar fields are authoritative when present. Legacy snapshots
    may contain cents under either the unsuffixed or explicit ``_cents`` name.
    Missing/null/empty fields are unavailable. A malformed selected field is an
    error, not permission to fall back to a different measurement.
    """
    for key, scale in ((f"{field}_dollars", 1), (field, 100), (f"{field}_cents", 100)):
        value = payload.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            raise ValidationError(f"invalid Kalshi price: {key}")
        try:
            number = float(value)
        except (ValueError, OverflowError):
            raise ValidationError(f"invalid Kalshi price: {key}") from None
        if not math.isfinite(number) or not 0 <= number <= scale:
            raise ValidationError(f"Kalshi price outside permitted range: {key}")
        return number / scale
    return None
