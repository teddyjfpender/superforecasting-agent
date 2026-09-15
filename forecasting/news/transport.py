"""Bounded public news requests, validating every redirect before sending it."""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

MAX_BYTES = 2 * 1024 * 1024


def fetch_public_text(
    url: str, *, is_safe_url: Callable[[str], bool]
) -> tuple[str, str]:

    def check(request: httpx.Request) -> None:
        parts = urlsplit(str(request.url))
        if (
            parts.scheme not in {"http", "https"}
            or parts.username
            or parts.password
            or not is_safe_url(str(request.url))
        ):
            raise ValueError(
                "News requests require a public HTTP(S) URL without credentials"
            )

    started = time.monotonic()
    with httpx.Client(
        timeout=12,
        follow_redirects=True,
        max_redirects=4,
        event_hooks={"request": [check]},
        headers={
            "User-Agent": "Superforecasting-Agent/1.0",
            "Accept-Encoding": "identity",
        },
    ) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            if response.headers.get("content-encoding", "identity").lower() not in {
                "identity",
                "",
            }:
                raise ValueError("News source ignored the uncompressed response limit")
            body = bytearray()
            for chunk in response.iter_raw(chunk_size=32_768):
                if (
                    len(body) + len(chunk) > MAX_BYTES
                    or time.monotonic() - started > 15
                ):
                    raise ValueError("News response exceeded its size or time budget")
                body.extend(chunk)
            return bytes(body).decode(
                response.encoding or "utf-8", errors="replace"
            ), str(response.url)
