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

# A JSON getter: (url, *, data?, headers?) -> parsed JSON, or ``None`` on any
# HTTP / parse failure (mirrors the client's ``getJson`` — a non-OK response or
# timeout is null, and the parser turns null into honest "—" quotes). ``data``
# present makes it a POST (the BLS timeseries endpoint); GET otherwise.
JsonGetter = Callable[..., object]
# A text getter: (url) -> body text, or ``None`` on any HTTP / parse failure
# (mirrors the client's ``getText`` — the keyless FRED CSV + Stooq daily CSV).
TextGetter = Callable[[str], "str | None"]


def default_get_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 12.0,
) -> object:
    """Fetch + parse JSON, returning ``None`` on ANY failure (never raising).

    Matches the client contract: a non-2xx status, a network error, or invalid
    JSON all collapse to ``None`` so the caller's parser produces null-valued
    (honest) quotes instead of throwing. When ``data`` is supplied the request
    is a POST with that body (mirrors the client's ``getJson(url, init)`` for the
    BLS POST); otherwise a GET.
    """

    req_headers = {"User-Agent": "Outrider/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers)
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


def default_get_text(url: str, *, timeout: float = 12.0) -> str | None:
    """Fetch + decode a text body, returning ``None`` on ANY failure.

    The keyless FRED CSV (``fredgraph.csv``) and the Stooq daily CSV are plain
    text; this mirrors the client's ``getText`` — a non-2xx status, a network
    error, or a decode failure collapse to ``None`` so the parser yields honest
    "—" quotes instead of throwing.
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
        return raw.decode("utf-8")
    except UnicodeDecodeError:
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


__all__ = [
    "Provider",
    "JsonGetter",
    "TextGetter",
    "default_get_json",
    "default_get_text",
]
