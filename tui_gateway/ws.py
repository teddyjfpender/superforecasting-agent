"""WebSocket transport for the tui_gateway JSON-RPC server.

Reuses :func:`tui_gateway.server.dispatch` verbatim so every RPC method, every
slash command, every approval/clarify/sudo flow, and every agent event flows
through the same handlers whether the client is Ink over stdio or an iOS /
web client over WebSocket.

Wire protocol
-------------
Identical to stdio: newline-delimited JSON-RPC in both directions. The server
emits a ``gateway.ready`` event immediately after connection accept, then
echoes responses/events for inbound requests. No framing differences.

Mounting
--------
    from fastapi import WebSocket
    from tui_gateway.ws import handle_ws

    @app.websocket("/api/ws")
    async def ws(ws: WebSocket):
        await handle_ws(ws)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from tui_gateway import server

_log = logging.getLogger(__name__)

# Max seconds a pool-dispatched handler will block waiting for the event loop
# to flush a WS frame before we mark the transport dead. Protects handler
# threads from a wedged socket.
_WS_WRITE_TIMEOUT_S = 10.0

# Keep starlette optional at import time; handle_ws uses the real class when
# it's available and falls back to a generic Exception sentinel otherwise.
try:
    from starlette.websockets import WebSocketDisconnect as _WebSocketDisconnect
except ImportError:  # pragma: no cover - starlette is a required install path
    _WebSocketDisconnect = Exception  # type: ignore[assignment]


class WSTransport:
    """Per-connection WS transport.

    ``write`` is safe to call from any thread *other than* the event loop
    thread that owns the socket. Pool workers (the only real caller) run in
    their own threads, so marshalling onto the loop via
    :func:`asyncio.run_coroutine_threadsafe` + ``future.result()`` is correct
    and deadlock-free there.

    When called from the loop thread itself (e.g. by ``handle_ws`` for an
    inline response) the same call would deadlock: we'd schedule work onto
    the loop we're currently blocking. We detect that case and schedule a
    connection-owned send instead. Callers that need wire completion
    should use :meth:`write_async` from the loop thread.
    """

    def __init__(self, ws: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._ws = ws
        self._loop = loop
        self._closed = False
        self._send_lock = asyncio.Lock()
        self._pending: set[asyncio.Task] = set()

    def write(self, obj: dict) -> bool:
        if self._closed:
            return False

        line = json.dumps(obj, ensure_ascii=False)

        try:
            on_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            on_loop = False

        if on_loop:
            # Schedule without blocking this loop; close owns pending sends.
            task = self._loop.create_task(self._safe_send(line))
            self._pending.add(task)
            task.add_done_callback(self._pending.discard)
            return True

        fut = None
        try:
            from agent.async_utils import safe_schedule_threadsafe
            fut = safe_schedule_threadsafe(self._safe_send(line), self._loop)
            if fut is None:
                self.close()
                return False
            fut.result(timeout=_WS_WRITE_TIMEOUT_S)
            return not self._closed
        except Exception as exc:
            if fut is not None:
                fut.cancel()
            self.close()
            _log.debug("ws write failed: %s", exc)
            return False

    async def write_async(self, obj: dict) -> bool:
        """Send from the owning event loop. Awaits until the frame is on the wire."""
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("WebSocket writes must use the owning event loop")
        if self._closed:
            return False
        await self._safe_send(json.dumps(obj, ensure_ascii=False))
        return not self._closed

    async def _safe_send(self, line: str) -> None:
        if self._closed:
            return
        task = asyncio.current_task()
        if task is not None:
            self._pending.add(task)
        try:
            async with self._send_lock:
                if not self._closed:
                    await self._ws.send_text(line)
        except asyncio.CancelledError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            _log.debug("ws send failed: %s", exc)
        finally:
            if task is not None:
                self._pending.discard(task)

    def _cancel_pending(self) -> None:
        current = asyncio.current_task()
        for task in tuple(self._pending):
            if task is not current:
                task.cancel()

    def close(self) -> None:
        self._closed = True
        try:
            on_loop = asyncio.get_running_loop() is self._loop
        except RuntimeError:
            on_loop = False
        if on_loop:
            self._cancel_pending()
        else:
            try:
                self._loop.call_soon_threadsafe(self._cancel_pending)
            except RuntimeError:
                # The owning loop is already closed; never touch another loop.
                pass

    async def aclose(self) -> None:
        """Cancel and drain this connection's sends on the owning event loop."""
        if asyncio.get_running_loop() is not self._loop:
            raise RuntimeError("WebSocket cleanup must use the owning event loop")
        self.close()
        current = asyncio.current_task()
        pending = [task for task in self._pending if task is not current]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def handle_ws(ws: Any) -> None:
    """Run one WebSocket session. Wire-compatible with ``tui_gateway.entry``."""
    await ws.accept()
    server.start_build_check()

    transport = WSTransport(ws, asyncio.get_running_loop())

    try:
        from tui_gateway.host_rpc import descriptor

        ready = await transport.write_async(
            {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": "gateway.ready",
                    "payload": {
                        "skin": server.resolve_skin(),
                        **descriptor(server),
                        # Same non-blocking build identity the stdio entry advertises,
                        # so a websocket-attached TUI shows the same version banner.
                        "build": server.build_info(),
                    },
                },
            }
        )

        if not ready:
            return

        while True:
            try:
                raw = await ws.receive_text()
            except _WebSocketDisconnect:
                break

            line = raw.strip()
            if not line:
                continue

            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                ok = await transport.write_async(
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "parse error"},
                        "id": None,
                    }
                )
                if not ok:
                    break
                continue

            # dispatch() may schedule long handlers on the pool; it returns
            # None in that case and the worker writes the response itself via
            # the transport we pass in (a separate thread, so transport.write
            # is the safe path there). For inline handlers it returns the
            # response dict, which we write here from the loop.
            resp = await asyncio.to_thread(server.dispatch, req, transport)
            if resp is not None and not await transport.write_async(resp):
                break
    finally:
        await transport.aclose()

        # Detach the transport from any sessions it owned so later emits
        # fall back to stdio instead of crashing into a closed socket.
        for _, sess in list(server._sessions.items()):
            if sess.get("transport") is transport:
                sess["transport"] = server._stdio_transport

        try:
            await ws.close()
        except Exception:
            pass
