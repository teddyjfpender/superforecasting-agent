"""Bounded stdlib HTTP GET → parsed JSON. No third-party deps, no trading.

Shared by the Polymarket and Kalshi read-only clients so neither imports the
other. Timeouts are always bounded; the read is capped so a hostile/huge
response cannot exhaust memory.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_DEFAULT_TIMEOUT = 12.0
_READ_CAP = 32 * 1024 * 1024  # 32 MiB — a full nested /events page is a few MiB
_UA = "hermes-pm/1.0 (+prediction-markets)"


class PMHTTPError(RuntimeError):
    """A read-only market-data fetch failed (network, HTTP, or bad JSON)."""


def http_timeout(default: float = _DEFAULT_TIMEOUT) -> float:
    """Per-request timeout (seconds), env-tunable, always > 0 and bounded."""
    for name in ("HERMES_PM_TIMEOUT", "SUPERFORECASTING_AGENT_PM_TIMEOUT"):
        raw = os.environ.get(name)
        if not raw or not raw.strip():
            continue
        try:
            value = float(raw.strip())
        except (TypeError, ValueError):
            continue
        if 0 < value <= 120:
            return value
    return default


def http_get_json(
    url: str,
    *,
    label: str = "prediction-market",
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> object:
    """GET ``url`` with a bounded timeout and return decoded JSON.

    Raises :class:`PMHTTPError` on any network/HTTP/decode failure — callers
    degrade politely rather than crashing the desk.
    """
    json_headers = {"Accept": "application/json"}
    if headers:
        json_headers.update(headers)
    data = http_get_bytes(url, label=label, timeout=timeout, headers=json_headers)
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PMHTTPError(f"{label} response was not valid JSON") from exc


def http_get_bytes(
    url: str,
    *,
    label: str = "prediction-market",
    timeout: float | None = None,
    headers: dict[str, str] | None = None,
) -> bytes:
    """GET ``url`` with the same bounds as :func:`http_get_json`."""
    request_headers = {"User-Agent": _UA, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    request = Request(url, headers=request_headers)
    try:
        with urlopen(request, timeout=timeout or http_timeout()) as response:
            return response.read(_READ_CAP)
    except HTTPError as exc:  # pragma: no cover - network path
        raise PMHTTPError(f"{label} fetch failed: HTTP {exc.code} for {url}") from exc
    except (URLError, OSError) as exc:  # pragma: no cover - network path
        raise PMHTTPError(f"{label} fetch failed: {exc} for {url}") from exc


__all__ = ["PMHTTPError", "http_get_bytes", "http_get_json", "http_timeout"]
