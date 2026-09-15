"""Provider interface and bounded HTTP transport for the data desk.

Parsers reject ambiguous measurements; the service reports classified failures
while retaining prior successful data. Credentials never appear in diagnostics.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue

from forecasting.marketdata.model import Quote, SeriesRef

# Injectable fetch seam for deterministic parser and transport tests.
JsonGetter = Callable[..., JsonValue]
# A text getter: (url) -> body text; injected fixtures may return None
# (mirrors the client's ``getText`` — the keyless FRED CSV + Stooq daily CSV).
TextGetter = Callable[[str], "str | None"]

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
# Conservative per-host spacing shared by simultaneous gateway requests. This
# does not promise quota availability: explicit 429 cooldowns take precedence.
_HOST_INTERVALS = {"tablebuilder.singstat.gov.sg": 0.65, "api.coingecko.com": 2.1}
_rate_lock = threading.Lock()
_next_request: dict[str, float] = {}
_cooldown: dict[str, float] = {}


def _pace(host: str) -> None:
    with _rate_lock:
        now = time.monotonic()
        cooldown = _cooldown.get(host, 0) - now
        if cooldown > 0:
            raise ProviderFailure(
                "rate_limited",
                "Provider is cooling down after a quota response",
                retry_after=cooldown,
            )
        delay = max(0.0, _next_request.get(host, 0) - now)
        # Do not accumulate an unbounded queue behind a saturated source.
        if delay > 10:
            raise ProviderFailure(
                "rate_limited",
                "Provider request queue is full; retry shortly",
                retry_after=delay,
            )
        _next_request[host] = now + delay + _HOST_INTERVALS.get(host, 0.25)
    if delay:
        time.sleep(delay)


def _retry_delay(value: str | None) -> float:
    from forecasting.marketdata.model import num

    seconds = num(value)
    if seconds is not None:
        return max(0, seconds)
    if value:
        try:
            stamp = parsedate_to_datetime(value)
            if stamp.tzinfo is not None:
                return max(0, (stamp - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            pass
    return 60.0


class ProviderFailure(RuntimeError):
    """Safe provider diagnostic, without request URLs or credential values."""

    def __init__(
        self, status: str, message: str, *, retry_after: float | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _read_response(
    url: str, *, data: bytes | None, headers: dict[str, str] | None, timeout: float
) -> bytes:
    request_headers = {
        "User-Agent": "Superforecasting-Agent/1.0",
        "Accept-Encoding": "identity",
    }
    request_headers.update(headers or {})
    host = urlsplit(url).hostname or ""
    _pace(host)
    started = time.monotonic()
    try:
        # httpx uses the shipped CA bundle and honors SSL_CERT_FILE/SSL_CERT_DIR.
        # Own and close each stream here; never disable certificate verification.
        with httpx.stream(
            "POST" if data is not None else "GET",
            url,
            content=data,
            headers=request_headers,
            timeout=timeout,
            follow_redirects=True,
        ) as response:
            code = response.status_code
            if code in {401, 403}:
                raise ProviderFailure(
                    "authentication", "Provider rejected access or credentials"
                )
            if code == 429:
                retry_after = _retry_delay(response.headers.get("Retry-After"))
                with _rate_lock:
                    _cooldown[host] = max(
                        _cooldown.get(host, 0), time.monotonic() + retry_after
                    )
                raise ProviderFailure(
                    "rate_limited",
                    "Provider request quota exceeded",
                    retry_after=retry_after,
                )
            if code >= 400:
                raise ProviderFailure("unavailable", f"Provider returned HTTP {code}")
            if response.headers.get("Content-Encoding", "identity").lower() not in {
                "",
                "identity",
            }:
                raise ProviderFailure(
                    "invalid_response",
                    "Provider ignored the uncompressed response requirement",
                )
            raw = bytearray()
            for chunk in response.iter_raw(chunk_size=64 * 1024):
                if time.monotonic() - started > timeout:
                    raise ProviderFailure(
                        "unavailable", "Provider response exceeded its read budget"
                    )
                if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ProviderFailure(
                        "invalid_response", "Provider response exceeds the 4 MiB limit"
                    )
                raw.extend(chunk)
            return bytes(raw)
    except httpx.TimeoutException:
        raise ProviderFailure("unavailable", "Provider request timed out") from None
    except (httpx.HTTPError, OSError, ValueError):
        raise ProviderFailure(
            "unavailable", "Unable to retrieve provider data"
        ) from None


def default_get_json(
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 12.0,
) -> JsonValue:
    """Fetch bounded JSON, raising a safe, classified failure on transport errors.

    Supplying data makes a POST request (used by BLS). Parsers still accept
    injected malformed payloads independently of HTTP behavior.
    """

    raw = _read_response(url, data=data, headers=headers, timeout=timeout)
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ProviderFailure(
            "invalid_response", "Provider returned invalid JSON"
        ) from None


def default_get_text(
    url: str, *, timeout: float = 12.0, headers: dict[str, str] | None = None
) -> str | None:
    """Fetch bounded UTF-8 text, preserving authentication and quota failures."""

    raw = _read_response(url, data=None, headers=headers, timeout=timeout)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ProviderFailure(
            "invalid_response", "Provider returned invalid text encoding"
        ) from None


@runtime_checkable
class BatchPartitioner(Protocol):
    """Optional provider-owned partitioning for cache and failure isolation."""

    def batch_key(self, ref: SeriesRef) -> str: ...


class IndependentSeries:
    """Sources with one request per series can succeed and refresh independently."""

    def batch_key(self, ref: SeriesRef) -> str:
        return ref.symbol


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
