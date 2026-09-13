"""Request-scoped cooperative cancellation for synchronous Skills Hub callers."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx

_stop: ContextVar[threading.Event | None] = ContextVar("hub_stop", default=None)


class HubCancelled(RuntimeError):
    pass


def checkpoint() -> None:
    stop = _stop.get()
    if stop is not None and stop.is_set():
        raise HubCancelled("Skills operation cancelled")


@contextmanager
def cancellation_scope(stop: threading.Event) -> Iterator[None]:
    token = _stop.set(stop)
    try:
        checkpoint()
        yield
        checkpoint()
    finally:
        _stop.reset(token)


def request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Cancel pending headers/body and await transport teardown before returning."""
    checkpoint()
    stop = _stop.get()
    if stop is None:
        return getattr(httpx, method.lower())(url, **kwargs)

    async def perform() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            task = asyncio.create_task(client.request(method, url, **kwargs))
            try:
                while not task.done():
                    if stop.is_set():
                        raise HubCancelled("Skills operation cancelled during I/O")
                    await asyncio.wait({task}, timeout=0.05)
                checkpoint()
                return await task
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    return asyncio.run(perform())


def get(url: str, **kwargs: Any) -> httpx.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs: Any) -> httpx.Response:
    return request("POST", url, **kwargs)


def put(url: str, **kwargs: Any) -> httpx.Response:
    return request("PUT", url, **kwargs)
