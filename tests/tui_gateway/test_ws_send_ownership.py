"""Connection teardown owns queued and in-flight WebSocket sends."""

import asyncio
from unittest.mock import AsyncMock

from tui_gateway import ws


def test_queued_send_cannot_run_after_close():
    async def run():
        peer = AsyncMock()
        transport = ws.WSTransport(peer, asyncio.get_running_loop())
        assert transport.write({'queued': True})
        await transport.aclose()
        await asyncio.sleep(0)
        peer.send_text.assert_not_called()
        assert not transport.write({'late': True})
    asyncio.run(run())


def test_close_cancels_and_drains_active_and_waiting_sends():
    async def run():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def send(_):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        peer = AsyncMock()
        peer.send_text.side_effect = send
        transport = ws.WSTransport(peer, asyncio.get_running_loop())
        transport.write({'first': True})
        await started.wait()
        transport.write({'second': True})
        await asyncio.sleep(0)
        await transport.aclose()
        assert stopped.is_set()
        assert not transport._pending
        peer.send_text.assert_called_once()
        await transport.aclose()
    asyncio.run(run())


def test_worker_timeout_cancels_its_send(monkeypatch):
    monkeypatch.setattr(ws, '_WS_WRITE_TIMEOUT_S', 0.02)
    async def run():
        stopped = asyncio.Event()
        async def send(_):
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        peer = AsyncMock()
        peer.send_text.side_effect = send
        transport = ws.WSTransport(peer, asyncio.get_running_loop())
        assert not await asyncio.to_thread(transport.write, {'timeout': True})
        await asyncio.wait_for(stopped.wait(), timeout=1)
        await transport.aclose()
        assert not transport._pending
    asyncio.run(run())


def test_handshake_failure_closes_socket_without_receiving(monkeypatch):
    monkeypatch.setattr(ws.server, 'start_build_check', lambda: None)
    monkeypatch.setattr(ws.server, 'resolve_skin', lambda: {})
    monkeypatch.setattr(ws.server, 'build_info', lambda: {})
    async def run():
        peer = AsyncMock()
        peer.send_text.side_effect = ConnectionResetError('gone during hello')
        await ws.handle_ws(peer)
        peer.receive_text.assert_not_called()
        peer.close.assert_awaited_once()
    asyncio.run(run())


def test_cancelled_handshake_still_closes_socket(monkeypatch):
    monkeypatch.setattr(ws.server, 'start_build_check', lambda: None)
    monkeypatch.setattr(ws.server, 'resolve_skin', lambda: {})
    monkeypatch.setattr(ws.server, 'build_info', lambda: {})
    async def run():
        started = asyncio.Event()
        async def send(_):
            started.set()
            await asyncio.Future()
        peer = AsyncMock()
        peer.send_text.side_effect = send
        task = asyncio.create_task(ws.handle_ws(peer))
        await started.wait()
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task
        peer.close.assert_awaited_once()
    asyncio.run(run())


def test_foreign_loop_cannot_send_or_drain_connection():
    import pytest
    owner = asyncio.new_event_loop()
    peer = AsyncMock()
    transport = ws.WSTransport(peer, owner)
    async def run():
        with pytest.raises(RuntimeError, match='owning event loop'):
            await transport.write_async({'wrong': 'loop'})
        with pytest.raises(RuntimeError, match='owning event loop'):
            await transport.aclose()
        peer.send_text.assert_not_called()
    try:
        asyncio.run(run())
    finally:
        owner.close()
