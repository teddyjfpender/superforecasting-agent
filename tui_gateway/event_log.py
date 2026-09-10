"""Per-session append-only event log at the transport seam (Task #230(c)).

The rider on architecture-review item #5: make re-attach generic and sessions
forensically replayable by teeing every event frame the gateway emits into an
append-only per-session JSONL log — at the SAME transport seam the HTTP slice's
:class:`~tui_gateway.http_server.BroadcastHub` proved.

Where it plugs in
-----------------
The gateway routes every event through a pluggable :class:`Transport`
(``server.write_json`` → session transport / contextvar / module
``_stdio_transport``). :class:`EventLog` is a Transport-compatible sink, so it
Tees alongside stdio (``entry.py``, the pure-stdio TUI path) and is driven by the
``BroadcastHub`` (``http_server.py``, the HTTP/SSE path — the hub is the single
convergence point where BOTH sessionless events (via ``_HubTransport``) and
per-session async events (via each request's ``_RpcSink``) land before fan-out).

What it does
------------
Every EVENT frame gets a process-global **monotonic id** + wall-clock **ts**. The
id is the canonical event id: it is stamped onto the frame (:data:`_EID_KEY`) so
the SSE sender can emit ``id: <n>`` for that exact frame, which is what finally
makes SSE ``Last-Event-ID`` resume honourable (the HTTP slice emitted ids but had
no log to resolve a resume against — this is the payoff). Session-scoped frames
are persisted to ``{home}/sessions/{session_id}/events.jsonl`` (one JSON object
per line); non-denied frames are also held in a bounded in-memory ring so a
reconnecting SSE client can be handed exactly the frames it missed.

Bounds & honesty
----------------
* **Per-session file cap** — ``events.jsonl`` is rotated ONCE at
  :data:`_DEFAULT_MAX_BYTES` (→ ``events.jsonl.1``, overwriting any prior ``.1``).
  Only one backup is kept; the second rotation drops the oldest window. Bounded,
  single-operator forensics — not an audit vault.
* **Denylist** — :data:`_DEFAULT_DENYLIST` (``pm.tick``) is NOT persisted and NOT
  held for resume. ``pm.tick`` is sessionless market data at websocket stream
  rates, unrelated to the agent turn a session log exists to reconstruct; logging
  it would dominate the file with self-refreshing noise and blow the cap. It still
  gets a monotonic id and streams live. (message/thinking/reasoning deltas are the
  WHOLE POINT of forensic replay, so they are kept — only ``pm.tick`` is denied.)
* **Resume ring** — a global, bounded (:data:`_DEFAULT_RING_MAX`) deque. A
  reconnect gap wider than the ring falls back to live-only (documented).
* **Fail-open** — a frame with no session id (no per-session home), an
  unresolvable home, or any I/O error NEVER raises into the transport. A broken
  log must never crash the gateway's event pipe.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Per-session persisted-file cap. On crossing, rotate ONCE (see module docstring).
_DEFAULT_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# Event types never persisted / never held for resume — see module docstring.
_DEFAULT_DENYLIST = frozenset({"pm.tick"})

# Bound on the global in-memory resume ring (frames, across all sessions).
_DEFAULT_RING_MAX = 4096

# Private, additive frame annotation carrying the canonical event id from
# record() to the SSE sender. Stripped before a frame is persisted or written to
# an SSE ``data:`` line, so neither the forensic record nor the wire carries it.
_EID_KEY = "_eid"

# events.replay result caps.
_DEFAULT_LIMIT = 500
_MAX_LIMIT = 5000


def _hermes_sessions_root() -> Optional[Path]:
    """``{home}/sessions`` resolved fresh (get_agent_home reads env each call),
    or ``None`` when the home can't be resolved (fail-open)."""
    try:
        from superforecasting_agent.constants import get_agent_home

        return Path(get_agent_home()) / "sessions"
    except Exception:  # pragma: no cover - defensive
        logger.debug("event_log: could not resolve hermes home", exc_info=True)
        return None


def _event_type(frame: dict) -> str:
    params = frame.get("params")
    return str(params.get("type") or "") if isinstance(params, dict) else ""


def _event_session_id(frame: dict) -> str:
    params = frame.get("params")
    return str(params.get("session_id") or "") if isinstance(params, dict) else ""


class EventLog:
    """Append-only per-session JSONL sink + global resume ring (fail-open).

    Transport-compatible (``write`` / ``close``) so it Tees alongside stdio and is
    driven by the HTTP hub. ``record`` is the single id authority — call it
    directly (the hub does, to get the id it must stamp on the SSE stream) or via
    ``write`` (the stdio Tee). Construct with an explicit ``root`` in tests;
    leaving it ``None`` resolves ``{home}/sessions`` lazily on every write so an
    env/home change (or a per-test HERMES_HOME) is honoured.
    """

    def __init__(
        self,
        root=None,
        *,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        denylist=_DEFAULT_DENYLIST,
        ring_max: int = _DEFAULT_RING_MAX,
    ) -> None:
        self._root = Path(root) if root is not None else None
        self._resolve_lazily = root is None
        self._max_bytes = int(max_bytes)
        self._denylist = frozenset(denylist)
        self._id_lock = threading.Lock()
        self._next = 0
        self._file_lock = threading.Lock()
        self._sizes: dict[str, int] = {}  # session_id -> current events.jsonl byte size
        self._ring_lock = threading.Lock()
        self._ring: "deque[tuple[int, str, str, dict]]" = deque(maxlen=int(ring_max))

    # ── id authority ────────────────────────────────────────────────────────

    def _new_id(self) -> int:
        with self._id_lock:
            self._next += 1
            return self._next

    # ── Transport interface ─────────────────────────────────────────────────

    def write(self, obj: dict) -> bool:
        """Tee sink entrypoint. Records event frames; ignores everything else.

        ALWAYS returns ``True`` — a log is a best-effort secondary, never the
        signal the dispatcher reads for "peer gone". Every failure is swallowed
        so a broken log can't crash the gateway's event pipe."""
        try:
            if isinstance(obj, dict) and obj.get("method") == "event":
                self.record(obj)
        except Exception:  # pragma: no cover - fail-open guard
            logger.debug("event_log.write swallowed", exc_info=True)
        return True

    def close(self) -> None:
        return None

    # ── core record ─────────────────────────────────────────────────────────

    def record(self, frame: dict) -> int:
        """Assign the canonical id (+ ts), stamp the frame, ring + persist it.

        Returns the assigned id. Fail-open: persistence errors never raise. A
        denylisted type gets an id and is stamped (so it still streams live) but
        is neither ringed nor persisted."""
        eid = self._new_id()
        # Stamp BEFORE the denylist check so denied frames still carry an id for
        # the live SSE `id:` line.
        try:
            frame[_EID_KEY] = eid
        except Exception:  # pragma: no cover - frame is always a dict here
            return eid

        etype = _event_type(frame)
        if etype in self._denylist:
            return eid  # streamed live only — never ringed, never persisted

        ts = time.time()
        sid = _event_session_id(frame)
        clean_frame = {k: v for k, v in frame.items() if k != _EID_KEY}
        record = {"id": eid, "ts": ts, "session_id": sid, "type": etype, "frame": clean_frame}

        # Resume ring (global — sessionless events resume too).
        with self._ring_lock:
            self._ring.append((eid, sid, etype, clean_frame))

        # Persist ONLY when the frame names a session (per-session home). A
        # sessionless frame has no per-session path — skip the write, fail-open.
        if sid:
            self._persist(sid, record)
        return eid

    def _persist(self, sid: str, record: dict) -> None:
        root = self._current_root()
        if root is None:
            return  # no home resolvable -> no logging (fail-open)
        try:
            line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        except Exception:  # pragma: no cover - record is JSON-safe by construction
            logger.debug("event_log serialize failed", exc_info=True)
            return
        path = root / sid / "events.jsonl"
        with self._file_lock:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                size = self._sizes.get(sid)
                if size is None:
                    size = path.stat().st_size if path.exists() else 0
                if size + len(line) > self._max_bytes:
                    self._rotate(path)
                    size = 0
                with open(path, "ab") as fh:
                    fh.write(line)
                self._sizes[sid] = size + len(line)
            except Exception:
                logger.debug("event_log persist failed for session %s", sid, exc_info=True)

    @staticmethod
    def _rotate(path: Path) -> None:
        """Rotate ONCE: events.jsonl -> events.jsonl.1 (overwriting any prior .1)."""
        backup = path.with_name(path.name + ".1")
        try:
            if backup.exists():
                backup.unlink()
            if path.exists():
                path.rename(backup)
        except Exception:  # pragma: no cover - best-effort rotation
            logger.debug("event_log rotate failed", exc_info=True)

    def _current_root(self) -> Optional[Path]:
        return _hermes_sessions_root() if self._resolve_lazily else self._root

    # ── SSE resume ──────────────────────────────────────────────────────────

    def recent_since(self, since_id: int, types=None) -> "list[tuple[int, dict]]":
        """Ring frames with id > ``since_id`` (oldest-first) for SSE resume.

        Returns ``(id, frame)`` pairs. ``types`` optionally filters by event type.
        A gap wider than the ring simply returns fewer frames — honest, bounded."""
        allow = frozenset(types) if types else None
        with self._ring_lock:
            snapshot = list(self._ring)
        out: "list[tuple[int, dict]]" = []
        for eid, _sid, etype, frame in snapshot:
            if eid <= since_id:
                continue
            if allow is not None and etype not in allow:
                continue
            out.append((eid, frame))
        return out


# ── disk-reading replay (independent of any live instance) ──────────────────


def session_events_path(session_id: str, root=None) -> Optional[Path]:
    base = Path(root) if root is not None else _hermes_sessions_root()
    if base is None or not session_id:
        return None
    return base / session_id / "events.jsonl"


def read_events(
    session_id: str,
    *,
    since_id: int = 0,
    types=None,
    limit: int = _DEFAULT_LIMIT,
    root=None,
) -> "list[dict]":
    """Persisted records for a session, oldest-first, filtered + capped.

    Spans a single rotation: reads ``events.jsonl.1`` (older) then ``events.jsonl``
    (newer) so ids stay ascending. Returns records with ``id > since_id`` and
    ``type in types``, sorted by id, capped at ``limit``. Fail-open: a missing or
    corrupt file yields ``[]`` (unparseable lines are skipped)."""
    path = session_events_path(session_id, root=root)
    if path is None:
        return []
    allow = frozenset(types) if types else None
    out: "list[dict]" = []
    for candidate in (path.with_name(path.name + ".1"), path):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        rec = json.loads(raw)
                    except Exception:
                        continue  # skip a torn/half-written line, fail-open
                    if not isinstance(rec, dict):
                        continue
                    try:
                        rid = int(rec.get("id", 0))
                    except (TypeError, ValueError):
                        continue
                    if rid <= since_id:
                        continue
                    if allow is not None and str(rec.get("type") or "") not in allow:
                        continue
                    out.append(rec)
        except Exception:
            logger.debug("event_log read failed for %s", candidate, exc_info=True)
    out.sort(key=lambda r: int(r.get("id", 0)))
    if limit and limit > 0:
        out = out[:limit]
    return out


# ── RPC registration (pm_rpc-style) ─────────────────────────────────────────


def register(server) -> None:
    """Register ``events.replay`` into the gateway dispatch table.

    ``events.replay {session_id, since_id?, types?, limit?}`` → the logged frames
    for that session (``id > since_id``, ``type in types``), oldest-first, capped.
    Reads the persisted per-session log directly, so it works regardless of which
    transport (stdio/HTTP) is live and needs no reference to the live sink."""

    def events_replay(rid, params):
        params = params or {}
        session_id = str(params.get("session_id") or "").strip()
        if not session_id:
            return server._err(rid, -32602, "events.replay: session_id is required")

        try:
            since_id = int(params.get("since_id") or 0)
        except (TypeError, ValueError):
            since_id = 0

        types = params.get("types")
        if isinstance(types, str):
            types = [types]
        if types is not None and not isinstance(types, list):
            return server._err(rid, -32602, "events.replay: types must be a list or omitted")

        try:
            limit = int(params.get("limit") or _DEFAULT_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_LIMIT
        limit = max(1, min(limit, _MAX_LIMIT))

        try:
            records = read_events(session_id, since_id=since_id, types=types, limit=limit)
        except Exception as exc:  # pragma: no cover - read_events is itself fail-open
            return server._err(rid, -32000, f"events.replay failed: {exc}")

        frames = [rec.get("frame") for rec in records]
        last_id = int(records[-1]["id"]) if records else since_id
        return server._ok(
            rid,
            {
                "session_id": session_id,
                "frames": frames,
                "records": records,  # id + ts + type + frame, for forensics/paging
                "count": len(frames),
                "since_id": since_id,
                "last_id": last_id,
            },
        )

    server.register_method("events.replay", events_replay)


__all__ = [
    "EventLog",
    "read_events",
    "session_events_path",
    "register",
    "_EID_KEY",
]
