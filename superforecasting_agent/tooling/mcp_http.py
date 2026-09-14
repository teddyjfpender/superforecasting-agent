"""Bound MCP wire bodies before SDK buffering, including long-lived SSE streams."""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

BODY_LIMIT = 10 * 1024 * 1024
_NEWLINE = re.compile(rb"\r\n|\r|\n")


class BodyLimitStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, *, sse: bool, limit: int):
        self.stream = stream
        self.sse = sse
        self.limit = limit
        self.size = 0
        self.line_size = 0
        self.trailing_cr = False

    def count(self, chunk: bytes) -> None:
        if not self.sse:
            self.size += len(chunk)
            self.check()
            return
        # A CRLF split across chunks is one newline, never an empty SSE line.
        start = 1 if self.trailing_cr and chunk.startswith(b"\n") else 0
        self.trailing_cr = bool(chunk) and chunk.endswith(b"\r")
        for match in _NEWLINE.finditer(chunk, start):
            self.size += match.start() - start
            self.line_size += match.start() - start
            self.check()
            if self.line_size == 0:
                self.size = 0
            else:
                self.size += 1
                self.check()
            self.line_size = 0
            start = match.end()
        self.size += len(chunk) - start
        self.line_size += len(chunk) - start
        self.check()

    def check(self) -> None:
        if self.size > self.limit:
            raise httpx.ReadError(
                f"MCP response exceeds {self.limit}-byte body/event limit"
            )

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for chunk in self.stream:
                if chunk:
                    self.count(chunk)
                yield chunk
        except BaseException:
            await self.stream.aclose()
            raise

    async def aclose(self) -> None:
        await self.stream.aclose()


async def identity_encoding(request: httpx.Request) -> None:
    # Decoding happens above the wire stream. Refuse compressed responses so an
    # expansion bomb cannot bypass this bound after the hook returns.
    request.headers["accept-encoding"] = "identity"


async def bound_response(response: httpx.Response, *, limit: int = BODY_LIMIT) -> None:
    """Response hooks run before AsyncClient/SDK buffers or parses the body."""
    try:
        if response.headers.get("content-encoding", "identity").strip().lower() not in {
            "",
            "identity",
        }:
            raise httpx.ReadError(
                "MCP compressed response refused; identity encoding required"
            )
        sse = (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            == "text/event-stream"
        )
        length = response.headers.get("content-length")
        if (
            not sse
            and length is not None
            and length.isdecimal()
            and int(length) > limit
        ):
            raise httpx.ReadError(f"MCP response exceeds {limit}-byte body/event limit")
        if not isinstance(response.stream, httpx.AsyncByteStream):
            raise httpx.ReadError("MCP requires an asynchronous response stream")
        response.stream = BodyLimitStream(response.stream, sse=sse, limit=limit)
    except BaseException:
        await response.aclose()
        raise


def client(**kwargs: Any) -> httpx.AsyncClient:
    """Retain HTTPX TLS/proxy ownership and SDK defaults; cap before body reads."""
    hooks = kwargs.pop("event_hooks", None) or {}
    kwargs.setdefault("follow_redirects", True)
    kwargs.setdefault("timeout", httpx.Timeout(30, read=300))
    kwargs["event_hooks"] = {
        "request": [*hooks.get("request", []), identity_encoding],
        "response": [bound_response, *hooks.get("response", [])],
    }
    return httpx.AsyncClient(**kwargs)
