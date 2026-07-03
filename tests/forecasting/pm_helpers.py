"""Shared helpers for the prediction-market (forecasting/pm) test suite.

Fixtures are recorded live once (public endpoints) into tests/fixtures/pm/ and
replayed here — the tests NEVER touch the network.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "pm"


def load_fixture(name: str) -> object:
    with (FIXTURE_DIR / name).open() as handle:
        return json.load(handle)


class RecordedFetch:
    """A ``fetch(url)`` stub that maps URL substrings → fixture payloads and
    records the calls, so client tests assert both parsing and call counts."""

    def __init__(self, routes: dict[str, object]) -> None:
        self._routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str) -> object:
        self.calls.append(url)
        for needle, payload in self._routes.items():
            if needle in url:
                return payload
        raise AssertionError(f"no recorded route for {url!r}")
