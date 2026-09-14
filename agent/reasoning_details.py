"""Accumulate provider replay metadata without displaying or discarding opaque blocks."""

from collections.abc import Mapping
from typing import cast

_TEXT_KEYS = {"reasoning.text": "text", "reasoning.summary": "summary"}


def append_reasoning_detail(details: list[dict[str, object]], value: object) -> None:
    """Join fragments of the same block; retain distinct identities and opaque data."""
    if not isinstance(value, Mapping):
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            value = dump()
        elif hasattr(value, "__dict__"):
            value = vars(value)
    if not isinstance(value, Mapping):
        return
    detail = dict(cast(Mapping[str, object], value))
    kind = detail.get("type")
    key = _TEXT_KEYS.get(kind) if isinstance(kind, str) else None
    previous = details[-1] if details else None
    if (
        previous is not None
        and key is not None
        and previous.get("type") == kind
        and isinstance(previous.get(key), str)
        and isinstance(detail.get(key), str)
        and all(
            previous.get(k) in (None, "")
            or detail.get(k) in (None, "")
            or previous[k] == detail[k]
            for k in detail.keys() | previous.keys()
            if k != key
        )
    ):
        previous[key] = cast(str, previous[key]) + cast(str, detail[key])
        for field, field_value in detail.items():
            if previous.get(field) in (None, ""):
                previous[field] = field_value
        return
    details.append(detail)
