"""Bind Gamma responses to a single market, never an event's arbitrary first child."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeGuard
from urllib.parse import parse_qs, unquote, urlparse

from forecasting.models import ValidationError


def _record(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _rows(value: object) -> list[dict[str, object]]:
    if _record(value):
        return [value]
    if not isinstance(value, list) or any(not _record(row) for row in value):
        raise ValidationError("polymarket response must contain market/event objects")
    return [row for row in value if _record(row)]


def _identity(row: dict[str, object], key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip().lower() if key == "conditionId" else value.strip()
    if key == "id" and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


@dataclass(frozen=True)
class PolymarketSelector:
    event: bool
    filters: tuple[tuple[str, str], ...]
    child_slug: str | None = None

    @classmethod
    def from_endpoint(cls, endpoint: str, *, source: str) -> PolymarketSelector:
        parsed = urlparse(endpoint)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        event = "events" in parts
        filters: list[tuple[str, str]] = []
        query = parse_qs(parsed.query, keep_blank_values=True)
        for parameter, field in (
            ("id", "id"),
            ("slug", "slug"),
            ("condition_ids", "conditionId"),
        ):
            values = query.get(parameter, [])
            if len(values) > 1 or any(
                not value.strip() or (parameter != "slug" and "," in value)
                for value in values
            ):
                raise ValidationError(
                    "polymarket import requires one market/event selector"
                )
            if values:
                value = values[0].strip()
                filters.append((
                    field,
                    value.lower() if field == "conditionId" else value,
                ))
        owner = "events" if event else "markets"
        if owner in parts:
            suffix = parts[parts.index(owner) + 1 :]
            if suffix:
                if len(suffix) == 2 and suffix[0] == "slug":
                    filters.append(("slug", suffix[1]))
                elif len(suffix) == 1:
                    filters.append(("id", suffix[0]))
                else:
                    raise ValidationError(
                        "unsupported polymarket single-market endpoint"
                    )
        for key, value in filters:
            if any(
                other_key == key and other_value != value
                for other_key, other_value in filters
            ):
                raise ValidationError("conflicting polymarket identity selectors")
        public = urlparse(source)
        path = [unquote(part) for part in public.path.split("/") if part]
        child = None
        if public.hostname == "polymarket.com" or (public.hostname or "").endswith(
            ".polymarket.com"
        ):
            if len(path) == 3 and path[0] == "event":
                child = path[2]
        return cls(event, tuple(filters), child)

    def select(self, payload: object) -> dict[str, object] | None:
        # Empty collections permit the documented market -> event and closed
        # market fallbacks. Nonempty identity mismatches are errors, not misses.
        if (
            not self.event
            and _record(payload)
            and "markets" in payload
            and any(_identity(payload, key) is not None for key in ("id", "slug"))
        ):
            raise ValidationError("polymarket market endpoint returned an event")
        envelope = "events" if self.event else "markets"
        if _record(payload) and envelope in payload:
            rows = _rows(payload[envelope])
        else:
            rows = _rows(payload)
        if not rows:
            return None
        matches = [
            row
            for row in rows
            if all(_identity(row, key) == value for key, value in self.filters)
        ]
        if len(matches) != 1:
            raise ValidationError(
                "polymarket response must contain exactly one matching market/event"
            )
        selected = matches[0]
        if self.event:
            children = _rows(selected.get("markets"))
            if self.child_slug is not None:
                children = [
                    row for row in children if _identity(row, "slug") == self.child_slug
                ]
            if len(children) != 1:
                raise ValidationError(
                    "polymarket event requires an explicit single market; use its market ID or child URL"
                )
            selected = children[0]
        elif "markets" in selected:
            raise ValidationError("polymarket market endpoint returned an event")
        if not any(
            _identity(selected, key) is not None
            for key in ("id", "slug", "conditionId")
        ):
            raise ValidationError("polymarket response is missing market identity")
        if (
            self.child_slug is not None
            and _identity(selected, "slug") != self.child_slug
        ):
            raise ValidationError(
                "polymarket response does not match requested child market"
            )
        return selected
