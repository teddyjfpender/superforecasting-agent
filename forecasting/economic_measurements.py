"""Pure lexical and uniqueness validation for economic source measurements."""

from __future__ import annotations

import math
import re
from typing import Any

from forecasting.models import ValidationError

_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def unique_numeric_observation(rows: Any) -> float:
    """Duplicate rows do not establish which release/revision is authoritative."""
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValidationError("missing measurement or conflicting/duplicate revisions")
    raw = rows[0].get("value")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        raise ValidationError("economic measurement must be numeric")
    if isinstance(raw, str) and not _NUMBER.fullmatch(raw):
        raise ValidationError("economic measurement missing or nonnumeric")
    try:
        value = float(raw)
    except (ValueError, OverflowError) as exc:
        raise ValidationError("economic measurement must be finite") from exc
    if not math.isfinite(value):
        raise ValidationError("economic measurement must be finite")
    return value
