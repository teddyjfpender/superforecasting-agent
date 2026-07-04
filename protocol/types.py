"""Shared primitives and the base model for every wire-crossing schema.

Every request, response, and event model inherits :class:`WireModel`. Plain
type aliases (``Probability = float`` …) document intent while resolving to their
underlying scalar so both pydantic and the TS codegen see a concrete type.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

# ── shared primitives (documentation aliases; resolve to raw scalars) ─────────
Probability = float  # a [0, 1] probability / price
IsoInstant = str  # an ISO-8601 timestamp string
UnixSeconds = int  # a unix-epoch-seconds timestamp
Venue = str  # a prediction-market venue ("kalshi" / "polymarket")
MarketId = str  # a venue market / token identifier
EventId = str  # a venue event identifier


class WireModel(BaseModel):
    """Base for every model that crosses the gateway wire.

    ``extra='ignore'`` mirrors the current handlers exactly — unknown request
    keys are dropped, never rejected, so adding validation changes no wire
    behaviour. ``TS_NAME`` sets the generated TypeScript interface name and
    defaults to the class name.
    """

    model_config = ConfigDict(extra="ignore")

    TS_NAME: ClassVar[str] = ""


def wire_optional(*, nullable: bool = False, **kwargs: Any) -> Any:
    """A field the server emits CONDITIONALLY — absent (not ``null``) when empty.

    Codegen renders it ``name?: T`` and the server serialises the response with
    ``exclude_none=True`` so the key is dropped rather than sent as ``null``,
    matching the venue models' ``to_dict`` (e.g. ``StreamStart`` omits an empty
    ``subscribed``).

    ``nullable=True`` marks a field that is BOTH optional (may be absent) AND, when
    present, may be ``null`` — codegen renders it ``name?: null | T``. This mirrors
    the many forecast-family fields the hand-written mirrors typed ``field?: null |
    string`` (a key the server sometimes omits and sometimes emits as ``null``). It
    is additive: plain ``wire_optional()`` keeps the ``name?: T`` shape unchanged.
    """

    extra = dict(kwargs.pop("json_schema_extra", None) or {})
    extra["wireOptional"] = True
    if nullable:
        extra["wireNullable"] = True
    return Field(default=None, json_schema_extra=extra, **kwargs)


__all__ = [
    "WireModel",
    "wire_optional",
    "Probability",
    "IsoInstant",
    "UnixSeconds",
    "Venue",
    "MarketId",
    "EventId",
]
