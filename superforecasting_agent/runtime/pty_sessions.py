"""Bounded PTY retention and byte replay across dashboard transport loss."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

RECONNECT_GRACE_SECONDS = 30.0
MAX_REPLAY_BYTES = 1024 * 1024
MAX_SESSIONS = 16


class PtyReplayUnavailable(RuntimeError):
    """The client must explicitly resume instead of silently losing output."""


class RetainedPty:
    def __init__(self, bridge: Any, resume: str | None):
        self.bridge = bridge
        self.resume = resume
        self.buffer = bytearray()
        self.offset = 0
        self.attached = False
        self.closed = False
        self.ended = False
        self.changed = asyncio.Condition()
        self.expiry: asyncio.Task | None = None
        self.reader = asyncio.create_task(self._read())

    def attach(self, cursor: int) -> None:
        if self.closed or self.attached:
            raise PtyReplayUnavailable("Terminal is closed or already attached.")
        self._check_cursor(cursor)
        self.attached = True
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None

    def _check_cursor(self, cursor: int) -> None:
        if not self.offset - len(self.buffer) <= cursor <= self.offset:
            raise PtyReplayUnavailable("Terminal output is no longer available for replay.")

    async def _read(self) -> None:
        try:
            while not self.closed:
                chunk = await asyncio.to_thread(self.bridge.read, 0.2)
                async with self.changed:
                    if chunk is None:
                        break
                    if chunk:
                        self.buffer.extend(chunk)
                        self.offset += len(chunk)
                        if len(self.buffer) > MAX_REPLAY_BYTES:
                            del self.buffer[:-MAX_REPLAY_BYTES]
                        self.changed.notify_all()
        finally:
            async with self.changed:
                self.ended = True
                self.changed.notify_all()

    async def read_after(self, cursor: int) -> bytes | None:
        async with self.changed:
            await self.changed.wait_for(lambda: self.closed or self.ended or cursor < self.offset)
            self._check_cursor(cursor)
            if cursor < self.offset:
                return bytes(self.buffer[cursor - (self.offset - len(self.buffer)):])
            return None

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.expiry and self.expiry is not asyncio.current_task():
            self.expiry.cancel()
        # Finish the bounded read before closing its fd, avoiding fd-reuse races.
        try:
            await self.reader
        except Exception:
            pass
        finally:
            await asyncio.to_thread(self.bridge.close)


class PtySessions:
    def __init__(self):
        self.sessions: dict[str, RetainedPty] = {}

    def attach(self, channel: str, resume: str | None, cursor: int, spawn: Callable[[], Any]) -> RetainedPty:
        session = self.sessions.get(channel)
        if session is None:
            if cursor:
                raise PtyReplayUnavailable("Terminal session expired. Resume it from Forecast Sessions.")
            if len(self.sessions) >= MAX_SESSIONS:
                raise PtyReplayUnavailable("Too many terminal sessions. Close another desk and retry.")
            session = RetainedPty(spawn(), resume)
            self.sessions[channel] = session
        elif session.resume != resume:
            raise PtyReplayUnavailable("Terminal resume target changed.")
        session.attach(cursor)
        return session

    async def detach(self, channel: str, session: RetainedPty, *, retain: bool) -> None:
        session.attached = False
        if not retain or session.ended:
            await self._remove(channel, session)
            return

        async def expire() -> None:
            await asyncio.sleep(RECONNECT_GRACE_SECONDS)
            await self._remove(channel, session)

        session.expiry = asyncio.create_task(expire())

    async def _remove(self, channel: str, session: RetainedPty) -> None:
        await session.close()
        if self.sessions.get(channel) is session:
            self.sessions.pop(channel, None)

    async def close_all(self) -> None:
        await asyncio.gather(*(session.close() for session in self.sessions.values()))
        self.sessions.clear()
