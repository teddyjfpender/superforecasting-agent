"""Websocket streaming for prediction markets — ONE connection per venue.

Two venues, one shared shape:

* **Polymarket** — public market channel
  ``wss://ws-subscriptions-clob.polymarket.com/ws/market``. Subscribe with
  ``{"type": "market", "assets_ids": [...]}`` (CLOB token ids); the server
  pushes ``book`` / ``price_change`` / ``tick_size_change`` frames. No auth.
* **Kalshi** — ``wss://api.elections.kalshi.com/trade-api/ws/v2``. The
  *handshake* needs the RSA-signed headers (see :mod:`forecasting.pm.kalshi`);
  public ``ticker`` / ``trade`` channels then need no per-channel auth. Absent a
  key → no stream (the desk falls back to REST polling).

Design invariants (per the integration plan):

* one long-lived connection per venue, subscriptions multiplexed onto it;
* auto-reconnect with bounded exponential backoff, re-sending the live
  subscription set on every reconnect;
* a callback bus — ``on_tick(venue, market_id, kind, payload)`` — so the gateway
  can re-emit ``pm.tick`` frames without this module importing the gateway;
* polite degradation: no ``websockets`` lib, or no Kalshi key, → ``start``
  returns ``{"streaming": False, "reason": ...}`` and nobody raises.

The websocket library is imported LAZILY, and the transport is injectable so
tests drive a fake in-memory socket (never the network).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

from forecasting.pm.kalshi import (
    KALSHI_WS_PATH,
    KalshiSignerUnavailable,
    kalshi_auth_headers,
)
from forecasting.pm.stream_wire import (
    KALSHI_SPEC,
    KALSHI_WS,
    POLYMARKET_SPEC,
    POLYMARKET_WS,
    Tick,
    VenueSpec,
    parse_kalshi,
    parse_polymarket,
    spec_for as _spec_for,
)

logger = logging.getLogger(__name__)

# Bounded exponential backoff (seconds) between reconnect attempts.
_BACKOFF = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
_RECV_TIMEOUT = 30.0

OnTick = Callable[[str, str, str, dict], None]
Sleeper = Callable[[float], None]
KalshiCreds = Callable[[], "tuple[str, str] | None"]
# Produces the per-handshake auth headers. Called ANEW on every (re)connect so a
# time-sensitive signature (Kalshi RSA-PSS over `timestamp+GET+path`) is fresh
# each time — a static dict computed once at start() would age out and the
# reconnect handshake would be rejected.
HeadersFactory = Callable[[], "dict[str, str] | None"]


class WsConnection(Protocol):
    """Minimal duplex text socket the venue drivers rely on."""

    def send(self, message: str) -> None: ...
    def recv(self, timeout: float | None = None) -> str: ...
    def close(self) -> None: ...


# Transport factory: (url, headers) -> connection. Injected in tests.
ConnectFn = Callable[[str, "dict[str, str] | None"], WsConnection]


class WsTimeout(Exception):
    """recv() timed out with the socket still healthy — keep looping."""


def websocket_available() -> bool:
    """True when a usable websocket client library is importable."""
    try:  # pragma: no cover - trivial import probe
        import websockets.sync.client  # noqa: F401

        return True
    except Exception:
        return False


def default_connect(url: str, headers: "dict[str, str] | None") -> WsConnection:
    """Real transport: a blocking ``websockets`` sync client, lazily imported."""
    from websockets.sync.client import connect  # lazy — optional dep

    conn = connect(url, additional_headers=headers or {}, open_timeout=10.0)
    return _WebsocketsAdapter(conn)


class _WebsocketsAdapter:
    """Adapt ``websockets.sync`` to :class:`WsConnection` (timeout → WsTimeout)."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def send(self, message: str) -> None:
        self._conn.send(message)

    def recv(self, timeout: float | None = None) -> str:
        try:
            data = self._conn.recv(timeout=timeout)
        except TimeoutError as exc:  # pragma: no cover - timing dependent
            raise WsTimeout() from exc
        return data if isinstance(data, str) else data.decode("utf-8")

    def close(self) -> None:
        try:  # pragma: no cover - best effort
            self._conn.close()
        except Exception:
            pass


# ── per-venue stream worker ──────────────────────────────────────────────────


class _VenueStream:
    """One reconnecting connection for a venue, with a mutable subscription set."""

    def __init__(
        self,
        spec: VenueSpec,
        *,
        connect: ConnectFn,
        headers_factory: HeadersFactory,
        on_tick: OnTick,
        sleeper: Sleeper,
        max_reconnects: int | None,
    ) -> None:
        self._spec = spec
        self._connect = connect
        self._headers_factory = headers_factory
        self._on_tick = on_tick
        self._sleeper = sleeper
        self._max_reconnects = max_reconnects
        self._subs: set[str] = set()
        self._lock = threading.Lock()
        self._conn: WsConnection | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- public control (called from the gateway thread) --

    def add(self, market_ids: Iterable[str]) -> None:
        with self._lock:
            new = {str(m) for m in market_ids if m} - self._subs
            self._subs |= new
            conn = self._conn
        if conn is not None and new:
            self._safe_subscribe(conn, new)
        self._ensure_thread()

    def remove(self, market_ids: Iterable[str]) -> None:
        with self._lock:
            self._subs -= {str(m) for m in market_ids}

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            conn = self._conn
        if conn is not None:
            conn.close()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)

    @property
    def subscriptions(self) -> set[str]:
        with self._lock:
            return set(self._subs)

    # -- internals --

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"pm-stream-{self._spec.venue}", daemon=True
            )
            self._thread.start()

    def _safe_subscribe(self, conn: WsConnection, market_ids: set[str]) -> None:
        try:
            conn.send(json.dumps(self._spec.subscribe(sorted(market_ids))))
        except Exception:  # pragma: no cover - resent on reconnect
            logger.debug("pm-stream %s subscribe send failed", self._spec.venue)

    def _run(self) -> None:
        attempt = 0
        while not self._stop.is_set():
            try:
                headers = self._headers_factory()
                conn = self._connect(self._spec.url, headers)
            except Exception:
                attempt += 1
                if not self._backoff(attempt):
                    break
                continue
            with self._lock:
                self._conn = conn
            attempt = 0
            self._safe_subscribe(conn, self.subscriptions)
            try:
                self._pump(conn)
            except Exception:
                pass
            finally:
                with self._lock:
                    self._conn = None
                conn.close()
            if self._stop.is_set():
                break
            attempt += 1
            if not self._backoff(attempt):
                break

    def _pump(self, conn: WsConnection) -> None:
        while not self._stop.is_set():
            try:
                message = conn.recv(timeout=_RECV_TIMEOUT)
            except WsTimeout:
                continue
            if message is None or message == "":
                continue
            try:
                raw = json.loads(message)
            except (json.JSONDecodeError, TypeError):
                continue
            for tick in self._spec.parse(raw):
                self._dispatch(tick)

    def _dispatch(self, tick: Tick) -> None:
        try:
            self._on_tick(self._spec.venue, tick.market_id, tick.kind, tick.payload)
        except Exception:  # pragma: no cover - a bad callback never kills the pump
            logger.debug("pm-stream %s on_tick raised", self._spec.venue)

    def _backoff(self, attempt: int) -> bool:
        """Sleep before a reconnect. Return False when retries are exhausted."""
        if self._max_reconnects is not None and attempt > self._max_reconnects:
            return False
        delay = _BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)]
        self._sleeper(delay)
        return not self._stop.is_set()


# ── hub: the one object the gateway holds ────────────────────────────────────


@dataclass
class StreamStart:
    streaming: bool
    reason: str | None = None
    subscribed: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"streaming": self.streaming}
        if self.reason:
            out["reason"] = self.reason
        if self.subscribed:
            out["subscribed"] = list(self.subscribed)
        return out


class PMStreamHub:
    """Owns one :class:`_VenueStream` per venue and the polite-degradation gate."""

    def __init__(
        self,
        *,
        connect: ConnectFn | None = None,
        kalshi_credentials: KalshiCreds | None = None,
        sleeper: Sleeper | None = None,
        max_reconnects: int | None = None,
        websocket_probe: Callable[[], bool] | None = None,
    ) -> None:
        self._connect = connect or default_connect
        self._kalshi_creds = kalshi_credentials
        self._sleeper = sleeper or _real_sleep
        self._max_reconnects = max_reconnects
        self._ws_probe = websocket_probe or websocket_available
        self._streams: dict[str, _VenueStream] = {}
        self._lock = threading.Lock()

    def start(self, venue: str, market_ids: Iterable[str], on_tick: OnTick) -> StreamStart:
        spec = _spec_for(venue)
        ids = tuple(str(m) for m in market_ids if m)
        if not self._ws_probe():
            return StreamStart(False, "websocket library not installed; using REST polling")

        headers_factory: HeadersFactory = lambda: None
        if spec.venue == "kalshi":
            creds = self._kalshi_creds() if self._kalshi_creds else None
            if not creds:
                return StreamStart(
                    False,
                    "kalshi streaming needs a key — run `forecast api-key set kalshi`",
                )
            key_id, pem = creds
            # Fail fast with an honest reason if the key can't be signed at all,
            # but recompute the signature on EVERY (re)connect so the timestamp
            # never ages out mid-stream (see HeadersFactory).
            try:
                kalshi_auth_headers(key_id, pem, "GET", KALSHI_WS_PATH)
            except KalshiSignerUnavailable:
                return StreamStart(
                    False, "install 'cryptography' to sign the Kalshi handshake"
                )
            except Exception:
                return StreamStart(False, "kalshi key could not be loaded")

            def headers_factory(_key_id: str = key_id, _pem: str = pem) -> "dict[str, str] | None":
                return kalshi_auth_headers(_key_id, _pem, "GET", KALSHI_WS_PATH)

        with self._lock:
            stream = self._streams.get(spec.venue)
            if stream is None:
                stream = _VenueStream(
                    spec,
                    connect=self._connect,
                    headers_factory=headers_factory,
                    on_tick=on_tick,
                    sleeper=self._sleeper,
                    max_reconnects=self._max_reconnects,
                )
                self._streams[spec.venue] = stream
        stream.add(ids)
        return StreamStart(True, subscribed=ids)

    def stop(self, venue: str, market_ids: Iterable[str] | None = None) -> dict[str, Any]:
        spec = _spec_for(venue)
        with self._lock:
            stream = self._streams.get(spec.venue)
        if stream is None:
            return {"stopped": False, "venue": spec.venue}
        if market_ids is None:
            stream.stop()
            with self._lock:
                self._streams.pop(spec.venue, None)
            return {"stopped": True, "venue": spec.venue, "closed": True}
        stream.remove(market_ids)
        remaining = stream.subscriptions
        if not remaining:
            stream.stop()
            with self._lock:
                self._streams.pop(spec.venue, None)
            return {"stopped": True, "venue": spec.venue, "closed": True}
        return {"stopped": True, "venue": spec.venue, "remaining": sorted(remaining)}

    def active(self) -> dict[str, list[str]]:
        with self._lock:
            return {v: sorted(s.subscriptions) for v, s in self._streams.items()}

    def shutdown(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.stop()


def _real_sleep(seconds: float) -> None:  # pragma: no cover - wall-clock
    import time

    time.sleep(seconds)


__all__ = [
    "PMStreamHub",
    "StreamStart",
    "Tick",
    "VenueSpec",
    "POLYMARKET_SPEC",
    "KALSHI_SPEC",
    "POLYMARKET_WS",
    "KALSHI_WS",
    "parse_polymarket",
    "parse_kalshi",
    "websocket_available",
    "default_connect",
    "WsTimeout",
]
