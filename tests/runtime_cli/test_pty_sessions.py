"""Bounded retention must either replay completely or explicitly reject resume."""

import asyncio
import queue

import pytest

from superforecasting_agent.runtime import pty_sessions as ps


class Bridge:
    def __init__(self):
        self.output = queue.Queue()
        self.closed = False

    def read(self, timeout):
        try:
            return self.output.get(timeout=timeout)
        except queue.Empty:
            return b""

    def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_replay_bounds_and_single_owner(monkeypatch):
    monkeypatch.setattr(ps, "MAX_REPLAY_BYTES", 4)
    manager = ps.PtySessions()
    bridge = Bridge()
    session = manager.attach("desk", "saved", 0, lambda: bridge)
    try:
        with pytest.raises(ps.PtyReplayUnavailable, match="already attached"):
            manager.attach("desk", "saved", 0, lambda: pytest.fail("duplicate child"))
        bridge.output.put(b"abcdef")
        async with session.changed:
            await asyncio.wait_for(session.changed.wait_for(lambda: session.offset == 6), 2)
        with pytest.raises(ps.PtyReplayUnavailable, match="no longer available"):
            await session.read_after(0)
        assert await session.read_after(2) == b"cdef"
        await manager.detach("desk", session, retain=True)
        with pytest.raises(ps.PtyReplayUnavailable, match="target changed"):
            manager.attach("desk", "other", 6, lambda: bridge)
        with pytest.raises(ps.PtyReplayUnavailable, match="no longer available"):
            manager.attach("desk", "saved", 7, lambda: bridge)
        assert manager.attach("desk", "saved", 6, lambda: bridge) is session
    finally:
        await manager.close_all()
    assert bridge.closed
    assert not manager.sessions


@pytest.mark.asyncio
async def test_expiry_reaps_child_and_requires_explicit_resume(monkeypatch):
    monkeypatch.setattr(ps, "RECONNECT_GRACE_SECONDS", 0.01)
    manager = ps.PtySessions()
    bridge = Bridge()
    session = manager.attach("desk", None, 0, lambda: bridge)
    await manager.detach("desk", session, retain=True)
    await asyncio.wait_for(session.expiry, 2)
    assert bridge.closed and not manager.sessions
    with pytest.raises(ps.PtyReplayUnavailable, match="expired"):
        manager.attach("desk", None, 1, lambda: pytest.fail("silent replacement"))


@pytest.mark.asyncio
async def test_capacity_and_eof_cleanup(monkeypatch):
    monkeypatch.setattr(ps, "MAX_SESSIONS", 1)
    manager = ps.PtySessions()
    bridge = Bridge()
    session = manager.attach("desk", None, 0, lambda: bridge)
    try:
        with pytest.raises(ps.PtyReplayUnavailable, match="Too many"):
            manager.attach("second", None, 0, lambda: pytest.fail("unbounded child"))
        bridge.output.put(None)
        assert await asyncio.wait_for(session.read_after(0), 2) is None
        await manager.detach("desk", session, retain=True)
        assert bridge.closed and not manager.sessions
    finally:
        await manager.close_all()
