"""Atomic market selection edits, preserving unrelated and future profile fields."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from pydantic import JsonValue

from .files import atomic_json_write, yaml_update_lock
from .profile_lease import ProfileLease


class SelectionConflict(ValueError):
    """The desk changed after the user previewed an edit."""


class MarketSelectionStore:
    """One backend-owned profile file; readers never see partial writes.

    An absent file means setup has not happened. Invalid existing data is an
    error, never permission to overwrite the user's collection with defaults.
    """

    def __init__(self, home: Path) -> None:
        self.home = home
        self.path = home / "markets.json"

    def _read(self) -> dict[str, JsonValue] | None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except UnicodeError as exc:
            raise ValueError(
                "markets.json is not valid UTF-8; repair it before editing"
            ) from exc
        try:

            def reject_constant(value: str) -> None:
                raise ValueError("Non-finite JSON value")

            def unique_keys(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
                result: dict[str, JsonValue] = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("Duplicate JSON property")
                    result[key] = value
                return result

            data = json.loads(
                text, parse_constant=reject_constant, object_pairs_hook=unique_keys
            )
        except (ValueError, UnicodeError) as exc:
            raise ValueError(
                "markets.json is invalid; restore or repair it before editing"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError("markets.json must contain an object")
        return data

    @staticmethod
    def revision(data: dict[str, JsonValue] | None) -> str:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def read(self) -> tuple[dict[str, JsonValue] | None, str]:
        with ProfileLease(self.home):
            data = self._read()
            return data, self.revision(data)

    def update(
        self,
        mutate: Callable[[dict[str, JsonValue] | None], dict[str, JsonValue]],
        *,
        expected_revision: str | None,
    ) -> tuple[dict[str, JsonValue], str]:
        with ProfileLease(self.home), yaml_update_lock(self.path):
            current = self._read()
            updated = mutate(current)
            if (
                expected_revision is not None
                and self.revision(current) != expected_revision
                and updated != current
            ):
                raise SelectionConflict(
                    "The data desk changed. Refresh the preview before applying."
                )
            revision = self.revision(updated)
            if updated != current:
                atomic_json_write(self.path, updated, allow_nan=False)
            return updated, revision
