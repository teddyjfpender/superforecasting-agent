"""The ``Provider`` protocol + a shared HTTP getter for market-data providers.

Every provider (``providers/*.py``) is a small class that declares its batching
and key semantics and turns a list of :class:`SeriesRef` into a list of
:class:`Quote`. Pure PARSERS (``parse_*``) are separated from the network call
so they are unit-testable with captured fixtures — the discipline the client had
(``marketFetch.ts``) and the reason the honesty tests port cleanly.

``fetch`` NEVER raises for a data-shape problem: a bad/empty/error payload yields
quotes whose measurements are ``None`` (THE LAW), so one flaky provider degrades
to "—" rather than blanking the tape. It MAY raise on a transport failure; the
service isolates that per provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from forecasting.marketdata.model import Quote, SeriesRef

# A JSON getter: (url) -> parsed JSON, or ``None`` on any HTTP / parse failure
# (mirrors the client's ``getJson`` — a non-OK response or timeout is null, and
# the parser turns null into honest "—" quotes).
JsonGetter = Callable[[str], object]


def default_get_json(url: str, *, timeout: float = 12.0) -> object:
    """Fetch + parse JSON, returning ``None`` on ANY failure (never raising).

    Matches the client contract: a non-2xx status, a network error, or invalid
    JSON all collapse to ``None`` so the caller's parser produces null-valued
    (honest) quotes instead of throwing.
    """

    req = urllib.request.Request(url, headers={"User-Agent": "Outrider/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - https only
            if resp.status and resp.status >= 400:
                return None
            raw = resp.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


@runtime_checkable
class Provider(Protocol):
    """One market-data source behind one interface.

    * ``name`` — the provider slug (``"frankfurter"``, ``"bea"``…).
    * ``needs_key`` — whether the provider is skipped without an API key.
    * ``fetch(series, api_key=None)`` — resolve every series (the provider owns
      its own batching: FX is a single ranged call for all symbols; BEA is one
      call per table). Returns a :class:`Quote` per input series, honest nulls
      for anything the payload did not carry.
    """

    name: str
    needs_key: bool

    def fetch(
        self, series: list[SeriesRef], *, api_key: str | None = None
    ) -> list[Quote]: ...


__all__ = ["Provider", "JsonGetter", "default_get_json"]
