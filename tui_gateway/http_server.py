"""HTTP + SSE transport for the tui_gateway JSON-RPC server.

Serves the SAME method registry and event pipeline as ``tui_gateway.entry``
(stdio) and ``tui_gateway.ws`` (WebSocket), over plain HTTP:

    POST /rpc     one JSON-RPC request per call -> one JSON-RPC response.
    GET  /events  Server-Sent-Events stream of the event frames the stdio
                  pipe carries (``{"method": "event", ...}``), heartbeat
                  comment every 15s.
    GET  /health  ``{"protocol_version": N, "uptime": seconds}`` liveness.

Transport / dependency choice
-----------------------------
Uses the standard library :class:`http.server.ThreadingHTTPServer` — a
per-connection thread server — deliberately, not aiohttp/starlette/uvicorn.
Those are all *optional* extras in ``pyproject.toml`` (``web``/``messaging``/
``slack``), never core deps; adding one to the base install would widen the
supply-chain blast radius the project is explicit about minimising. A
thread-per-connection model is a poor fit for thousands of idle sockets, but
this is a *single-operator* desk tool: a handful of connections at most (one
SSE stream + bursty POSTs). ThreadingHTTPServer gives each connection its own
thread, so a long-lived ``GET /events`` never blocks concurrent ``POST /rpc``
calls — exactly the property we need — with zero new dependencies.

Event fanout
------------
The gateway already routes events through a pluggable :class:`Transport`
(``server.write_json`` -> session transport -> contextvar -> module
``_stdio_transport``). Fanning events to a *new* sink is therefore a small
seam, not a refactor — the PTY sidecar already does it via
:class:`~tui_gateway.transport.TeeTransport`. Here we install a
:class:`_HubTransport` as the module-level ``_stdio_transport`` (HTTP-only
mode) or Tee it on top of the existing one (``alongside_stdio=True``). Every
``_emit`` / async event then lands in the :class:`BroadcastHub`, which
fans out to every connected SSE subscriber. Per-request ``POST /rpc`` uses a
:class:`_RpcSink` that captures the direct response and forwards any events
it sees to the same hub.

Auth
----
Binds ``127.0.0.1`` by default (loopback, no token required — single local
operator). A bearer token is REQUIRED for any non-loopback bind: pass one via
``--http-token`` / the ``*_TUI_HTTP_TOKEN`` env, or ``--http-gen-token`` to
generate + print one. Binding a non-loopback host with neither refuses to
start, loudly. When a token is set it is enforced on ``/rpc`` and ``/events``
with a constant-time compare; ``/health`` stays open as a liveness probe.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from tui_gateway import server
from tui_gateway.event_log import _EID_KEY, EventLog
from tui_gateway.transport import TeeTransport, Transport

logger = logging.getLogger(__name__)

# Heartbeat cadence for idle SSE streams. Comment frames (": ...") keep the
# connection (and any intermediary proxy) from reaping an idle socket.
_SSE_HEARTBEAT_S = 15.0

# Per-subscriber queue depth. A stalled SSE client drops the OLDEST frames
# rather than growing memory without bound — the desk stays live for
# everyone else. Matches the sidecar publisher's best-effort stance.
_SUB_QUEUE_MAX = 1000

# Default ceiling on how long POST /rpc waits for a pool-dispatched
# (``_LONG_HANDLERS``) response before returning a timeout error. Inline
# handlers ignore this entirely (they return synchronously).
_DEFAULT_RPC_TIMEOUT_S = 120.0

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "0:0:0:0:0:0:0:1"})

# Sentinel pushed to every subscriber queue on shutdown so SSE loops wake up
# and exit promptly instead of blocking a full heartbeat interval.
_STOP = object()


def _tui_env(name: str) -> str:
    for key in (
        f"SUPERFORECASTING_AGENT_TUI_{name}",
        f"FORECAST_TUI_{name}",
        f"HERMES_TUI_{name}",
    ):
        value = (os.environ.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_loopback(host: str) -> bool:
    return (host or "").strip().lower() in _LOOPBACK_HOSTS


def _event_log_enabled() -> bool:
    """The per-session event log is on by default; opt out with *_TUI_EVENT_LOG=0."""
    return _tui_env("EVENT_LOG").strip().lower() not in {"0", "false", "off", "no"}


# ── Event fanout ──────────────────────────────────────────────────────────


class BroadcastHub:
    """Fan a JSON frame out to every connected SSE subscriber.

    Thread-safe. Subscribers each own a bounded queue; a slow reader drops
    its oldest frames instead of back-pressuring the agent loop.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: set["queue.Queue[object]"] = set()
        self._closed = False
        self._seq = 0
        self._seq_lock = threading.Lock()
        # The append-only event log. When attached it is the id AUTHORITY (it
        # stamps the canonical monotonic id on each frame, which the SSE sender
        # emits as `id:` and `Last-Event-ID` resume resolves against) AND the
        # resume buffer (recent_since). Left None, the hub falls back to its own
        # `next_id` counter and offers no resume — matching the pre-log HTTP slice.
        self._log: Optional[EventLog] = None

    def attach_log(self, log: Optional[EventLog]) -> None:
        self._log = log

    @property
    def log(self) -> Optional[EventLog]:
        return self._log

    def subscribe(self) -> "queue.Queue[object]":
        q: "queue.Queue[object]" = queue.Queue(maxsize=_SUB_QUEUE_MAX)
        with self._lock:
            if self._closed:
                q.put_nowait(_STOP)
            else:
                self._subs.add(q)
        return q

    def unsubscribe(self, q: "queue.Queue[object]") -> None:
        with self._lock:
            self._subs.discard(q)

    def next_id(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def publish(self, frame: dict) -> None:
        # Assign + stamp the canonical event id BEFORE fan-out so every
        # subscriber (and the `id:` line each emits) shares one authority. The
        # log both stamps the frame (via record) and persists/rings it; without
        # a log we stamp our own counter so the SSE `id:` line still increments.
        if isinstance(frame, dict) and frame.get(_EID_KEY) is None:
            if self._log is not None:
                self._log.record(frame)
            else:
                frame[_EID_KEY] = self.next_id()
        with self._lock:
            if self._closed:
                return
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(frame)
            except queue.Full:
                # Drop the oldest frame to make room — best-effort delivery,
                # never block the emitting (agent) thread.
                try:
                    q.get_nowait()
                    q.put_nowait(frame)
                except (queue.Empty, queue.Full):
                    pass

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            subs = list(self._subs)
            self._subs.clear()
        for q in subs:
            try:
                q.put_nowait(_STOP)
            except queue.Full:
                pass


class _HubTransport:
    """A :class:`Transport` that publishes EVENT frames to a :class:`BroadcastHub`.

    Installed as (or Tee'd onto) ``server._stdio_transport`` so every async /
    session event the gateway emits reaches the SSE subscribers. Non-event
    frames (RPC responses that reach the fallback sink without a bound
    contextvar) are ignored — SSE carries events only, matching the stdio
    ``/events`` contract. Always reports success: a broadcast to zero-or-more
    subscribers is never "peer gone".
    """

    __slots__ = ("_hub",)

    def __init__(self, hub: BroadcastHub) -> None:
        self._hub = hub

    def write(self, obj: dict) -> bool:
        if isinstance(obj, dict) and obj.get("method") == "event":
            self._hub.publish(obj)
        return True

    def close(self) -> None:
        return None


class _RpcSink:
    """Per-request :class:`Transport` for one ``POST /rpc`` call.

    Captures the single JSON-RPC *response* frame (so the HTTP handler can
    return it in the body, including responses written by a pool worker for
    ``_LONG_HANDLERS``) and forwards any *event* frames emitted during the
    request to the shared hub. Bound on the dispatch contextvar, so it also
    becomes the ``session["transport"]`` for a session created by this
    request — meaning that session's later async events keep flowing to the
    hub through this object for its lifetime.
    """

    __slots__ = ("_hub", "_response", "_ready")

    def __init__(self, hub: BroadcastHub) -> None:
        self._hub = hub
        self._response: Optional[dict] = None
        self._ready = threading.Event()

    def write(self, obj: dict) -> bool:
        if isinstance(obj, dict) and obj.get("method") == "event":
            self._hub.publish(obj)
            return True
        # Non-event -> the direct JSON-RPC response for this request.
        if self._response is None:
            self._response = obj
            self._ready.set()
        return True

    def wait(self, timeout: float) -> bool:
        return self._ready.wait(timeout=timeout)

    @property
    def response(self) -> Optional[dict]:
        return self._response

    def close(self) -> None:
        return None


# ── Auth ──────────────────────────────────────────────────────────────────


def _resolve_token(host: str, token: Optional[str], generate_token: bool) -> Optional[str]:
    """Resolve the bearer token, enforcing the non-loopback policy.

    Precedence: explicit ``token`` arg > ``*_TUI_HTTP_TOKEN`` env > None.
    A non-loopback bind with no token either generates one (``generate_token``)
    or refuses to start, loudly.
    """
    token = (token or "").strip() or _tui_env("HTTP_TOKEN") or None

    if _is_loopback(host):
        return token

    if token:
        return token

    if generate_token:
        token = secrets.token_urlsafe(32)
        print(
            "\n"
            "  ============================================================\n"
            f"  Superforecasting gateway HTTP server bound to {host} (non-loopback).\n"
            "  A bearer token is REQUIRED. One was generated for this run:\n"
            "\n"
            f"      {token}\n"
            "\n"
            "  Send it as:  Authorization: Bearer <token>\n"
            "  ============================================================\n",
            flush=True,
        )
        return token

    raise RuntimeError(
        f"refusing to bind non-loopback host {host!r} without a bearer token. "
        "Set SUPERFORECASTING_AGENT_TUI_HTTP_TOKEN (or FORECAST_TUI_HTTP_TOKEN / "
        "HERMES_TUI_HTTP_TOKEN), pass --http-token <token>, or pass "
        "--http-gen-token to generate one. Loopback (127.0.0.1) needs no token."
    )


# ── HTTP server ───────────────────────────────────────────────────────────


class GatewayHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying gateway state + the event hub."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address,
        hub: BroadcastHub,
        token: Optional[str],
        rpc_timeout: float,
        prev_stdio: Optional[Transport],
    ) -> None:
        super().__init__(server_address, _GatewayHandler)
        self.hub = hub
        self.token = token
        self.rpc_timeout = rpc_timeout
        self.start_time = time.monotonic()
        self._prev_stdio = prev_stdio

    def restore_transport(self) -> None:
        """Put back whatever ``_stdio_transport`` was before we installed the hub."""
        if self._prev_stdio is not None:
            server._stdio_transport = self._prev_stdio
        self.hub.shutdown()

    def handle_error(self, request, client_address) -> None:
        """Swallow the routine peer-gone resets a browser/keep-alive client
        produces when it closes a connection between requests; surface
        anything else via the logger instead of a stderr traceback."""
        import sys as _sys

        exc = _sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        logger.debug("http request error from %s", client_address, exc_info=True)


class _GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SuperforecastingGateway/1"
    protocol_version = "HTTP/1.1"

    # ── plumbing ──────────────────────────────────────────────────────────

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        logger.debug("http %s - %s", self.address_string(), fmt % args)

    @property
    def _hub(self) -> BroadcastHub:
        return self.server.hub  # type: ignore[attr-defined]

    def _authorized(self) -> bool:
        token = self.server.token  # type: ignore[attr-defined]
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not header.startswith(prefix):
            return False
        return secrets.compare_digest(header[len(prefix):].strip(), token)

    def _send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _unauthorized(self) -> None:
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Bearer realm="gateway"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ── routes ────────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/health":
            self._handle_health()
        elif path == "/events":
            if not self._authorized():
                self._unauthorized()
                return
            self._handle_events()
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path != "/rpc":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._unauthorized()
            return
        self._handle_rpc()

    def _handle_health(self) -> None:
        from protocol.version import PROTOCOL_VERSION

        uptime = time.monotonic() - self.server.start_time  # type: ignore[attr-defined]
        self._send_json(
            200,
            {
                "protocol_version": PROTOCOL_VERSION,
                "uptime": round(uptime, 3),
                "subscribers": self._hub.subscriber_count,
            },
        )

    def _read_body(self) -> Optional[bytes]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            return None
        if length < 0:
            return None
        if length == 0:
            return b""
        return self.rfile.read(length)

    def _handle_rpc(self) -> None:
        raw = self._read_body()
        if raw is None:
            self._send_json(400, {"error": "invalid Content-Length"})
            return
        try:
            req = json.loads(raw.decode("utf-8")) if raw else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Mirror the stdio parse-error frame; HTTP 200 is standard for a
            # well-formed request carrying a JSON-RPC-level error.
            self._send_json(
                200,
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None},
            )
            return

        if not isinstance(req, dict):
            self._send_json(
                200,
                {
                    "jsonrpc": "2.0",
                    "error": {"code": -32600, "message": "invalid request: expected an object"},
                    "id": None,
                },
            )
            return

        sink = _RpcSink(self._hub)
        resp = server.dispatch(req, sink)
        if resp is None:
            # Pool-dispatched (_LONG_HANDLERS): the worker writes the response
            # via the bound sink. Block this connection thread until it lands.
            timeout = self.server.rpc_timeout  # type: ignore[attr-defined]
            if sink.wait(timeout):
                resp = sink.response
            if resp is None:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "error": {"code": -32000, "message": "handler timed out"},
                }
        self._send_json(200, resp)

    def _handle_events(self) -> None:
        # Subscribe FIRST so no live frame is lost between the resume replay and
        # the live loop; the sent_max dedup below drops any overlap.
        q = self._hub.subscribe()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Connection", "keep-alive")
            # Defeat proxy buffering (nginx) so events flush immediately.
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            # Prime the stream: retry hint + a comment so the client's
            # onopen fires and any buffering proxy flushes.
            self._sse_raw("retry: 3000\n\n")
            self._sse_raw(": connected\n\n")

            # ── resume ──────────────────────────────────────────────────────
            # Honour Last-Event-ID (the EventSource reconnect header; also
            # accepted as a `?lastEventId=`/`?last_event_id=` query param). Replay
            # the frames the client missed straight from the log's resume ring,
            # then fall through to the live loop. THIS is the event-log payoff:
            # the HTTP slice emitted monotonic ids but had nothing to resolve a
            # resume against; now it does.
            sent_max = self._resume_since_id()
            log = self._hub.log
            if sent_max > 0 and log is not None:
                for eid, frame in log.recent_since(sent_max):
                    if not self._sse_send(eid, frame):
                        return
                    if eid > sent_max:
                        sent_max = eid

            # ── live ────────────────────────────────────────────────────────
            while True:
                try:
                    item = q.get(timeout=_SSE_HEARTBEAT_S)
                except queue.Empty:
                    if not self._sse_raw(": ping\n\n"):
                        break
                    continue
                if item is _STOP:
                    break
                if not isinstance(item, dict):
                    continue
                eid = item.get(_EID_KEY)
                if not isinstance(eid, int):
                    eid = self._hub.next_id()
                # Drop any frame already handed out during the resume replay.
                if eid <= sent_max:
                    continue
                if not self._sse_send(eid, item):
                    break
                sent_max = eid
        finally:
            self._hub.unsubscribe(q)

    def _resume_since_id(self) -> int:
        """The client's last-seen event id from the `Last-Event-ID` header or a
        `lastEventId` / `last_event_id` query param; 0 (no resume) if absent."""
        raw = (self.headers.get("Last-Event-ID") or "").strip()
        if not raw:
            from urllib.parse import parse_qs, urlsplit

            qs = parse_qs(urlsplit(self.path).query)
            raw = (qs.get("lastEventId") or qs.get("last_event_id") or [""])[0].strip()
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return 0

    def _sse_send(self, eid: int, frame: dict) -> bool:
        """Write one SSE event, stripping the private id annotation from `data:`
        (it rides the `id:` line instead, keeping the wire frame pristine)."""
        payload = {k: v for k, v in frame.items() if k != _EID_KEY} if _EID_KEY in frame else frame
        data = json.dumps(payload, ensure_ascii=False)
        return self._sse_raw(f"id: {eid}\ndata: {data}\n\n")

    def _sse_raw(self, text: str) -> bool:
        """Write raw SSE bytes; return False when the client is gone."""
        try:
            self.wfile.write(text.encode("utf-8"))
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
            return False


# ── construction / lifecycle ──────────────────────────────────────────────


def make_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: Optional[str] = None,
    generate_token: bool = False,
    alongside_stdio: bool = False,
    rpc_timeout: float = _DEFAULT_RPC_TIMEOUT_S,
) -> GatewayHTTPServer:
    """Build (but do not start) the HTTP gateway server.

    Installs the event hub as the gateway's event sink. With
    ``alongside_stdio=True`` the existing ``_stdio_transport`` is preserved
    and the hub is Tee'd on top (events reach BOTH stdio and SSE — the small
    fanout seam); otherwise the hub REPLACES it (HTTP-only serve mode).

    Raises ``RuntimeError`` for a non-loopback bind with no token (unless
    ``generate_token``).
    """
    resolved_token = _resolve_token(host, token, generate_token)

    hub = BroadcastHub()
    # Attach the append-only per-session event log. The hub is the convergence
    # point for the HTTP path (sessionless events via _HubTransport, per-session
    # async events via each _RpcSink), so hooking the log here captures every
    # frame the SSE stream carries — the resume ring stays in lockstep with the
    # ids clients see. Fail-open (see EventLog); disable via *_TUI_EVENT_LOG=0.
    if _event_log_enabled():
        hub.attach_log(EventLog())
    hub_transport = _HubTransport(hub)
    prev = server._stdio_transport
    if alongside_stdio:
        server._stdio_transport = TeeTransport(prev, hub_transport)
    else:
        server._stdio_transport = hub_transport

    try:
        httpd = GatewayHTTPServer(
            (host, port),
            hub=hub,
            token=resolved_token,
            rpc_timeout=rpc_timeout,
            prev_stdio=prev,
        )
    except Exception:
        # Bind failed — undo the transport swap so we don't strand the gateway.
        server._stdio_transport = prev
        hub.shutdown()
        raise
    return httpd


def serve(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    token: Optional[str] = None,
    generate_token: bool = False,
    alongside_stdio: bool = False,
    rpc_timeout: float = _DEFAULT_RPC_TIMEOUT_S,
) -> None:
    """Build + run the HTTP gateway server until interrupted (blocking)."""
    httpd = make_server(
        host,
        port,
        token=token,
        generate_token=generate_token,
        alongside_stdio=alongside_stdio,
        rpc_timeout=rpc_timeout,
    )
    bound_host, bound_port = httpd.server_address[0], httpd.server_address[1]
    auth = "token-protected" if httpd.token else "loopback, no token"
    print(
        f"[gateway-http] serving on http://{bound_host}:{bound_port} ({auth})  "
        f"POST /rpc · GET /events · GET /health",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[gateway-http] shutting down", flush=True)
    finally:
        httpd.shutdown()
        httpd.restore_transport()
        httpd.server_close()
