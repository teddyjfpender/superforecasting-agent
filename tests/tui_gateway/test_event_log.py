"""Tests for the per-session append-only event log + replay (Task #230(c)).

Covers, per the build spec:
  * append + monotonic ids
  * rotation cap (rotate-once, one backup, honest data loss)
  * events.replay filtering (since_id / types / limit)
  * SSE Last-Event-ID resume end-to-end (drop a connection, reconnect, receive
    EXACTLY the missed frames — no gaps, no dupes) over real sockets
  * the denylist choice (pm.tick still gets an id, is streamed live, but is
    never persisted and never held for resume)
  * fail-open: a sessionless frame / an unwritable home never writes and never
    raises into the transport
"""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from tui_gateway import event_log as EL
from tui_gateway import http_server as H
from tui_gateway import server


# ── helpers ──────────────────────────────────────────────────────────────────


def _frame(event_type: str, session_id: str = "", **payload) -> dict:
    params = {"type": event_type}
    if session_id:
        params["session_id"] = session_id
    if payload:
        params["payload"] = payload
    return {"jsonrpc": "2.0", "method": "event", "params": params}


def _read_lines(path):
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ── append + monotonic ids ───────────────────────────────────────────────────


def test_append_assigns_monotonic_ids_and_ts(tmp_path):
    log = EL.EventLog(root=tmp_path)
    ids = [log.record(_frame("message.delta", "sess", n=i)) for i in range(3)]
    assert ids == [1, 2, 3]  # dense, monotonic, from 1

    recs = _read_lines(tmp_path / "sess" / "events.jsonl")
    assert [r["id"] for r in recs] == [1, 2, 3]
    assert all(isinstance(r["ts"], (int, float)) and r["ts"] > 0 for r in recs)
    # The stored frame is the pristine event frame, WITHOUT the private id stamp.
    assert recs[0]["frame"]["params"]["type"] == "message.delta"
    assert EL._EID_KEY not in recs[0]["frame"]
    # one JSON object per line, one line per non-denied frame
    assert len(recs) == 3


def test_write_transport_entrypoint_ignores_non_events_and_never_raises(tmp_path):
    log = EL.EventLog(root=tmp_path)
    # A JSON-RPC response frame (no method=="event") is ignored, returns True.
    assert log.write({"jsonrpc": "2.0", "id": 1, "result": {}}) is True
    assert log.write(_frame("status.update", "sess", text="hi")) is True
    assert (tmp_path / "sess" / "events.jsonl").exists()
    # The response frame produced no session dir of its own.
    assert not (tmp_path / "1").exists()


# ── rotation cap ─────────────────────────────────────────────────────────────


def test_rotation_keeps_exactly_one_backup_and_drops_oldest(tmp_path):
    # Size each line at ~1KB and cap at 1.5KB so one record fits alone but two
    # don't -> every subsequent record rotates.
    pad = "x" * 900
    log = EL.EventLog(root=tmp_path, max_bytes=1500)
    for i in range(1, 5):
        log.record(_frame("message.delta", "sess", i=i, pad=pad))

    live = tmp_path / "sess" / "events.jsonl"
    backup = tmp_path / "sess" / "events.jsonl.1"
    assert live.exists() and backup.exists()

    live_recs = _read_lines(live)
    backup_recs = _read_lines(backup)
    # Rotate-once: exactly one backup, each holding a single window.
    assert [r["id"] for r in live_recs] == [4]
    assert [r["id"] for r in backup_recs] == [3]
    # Ids 1 and 2 were dropped on the later rotations — honest, bounded loss.
    assert not (tmp_path / "sess" / "events.jsonl.2").exists()

    # read_events spans the rotation (.1 then live), ascending, tail only.
    got = EL.read_events("sess", root=tmp_path)
    assert [r["id"] for r in got] == [3, 4]


# ── replay filtering ─────────────────────────────────────────────────────────


def test_read_events_filters_since_id_types_and_limit(tmp_path):
    log = EL.EventLog(root=tmp_path)
    log.record(_frame("message.delta", "sess", n=1))   # id 1
    log.record(_frame("tool.start", "sess", n=2))       # id 2
    log.record(_frame("message.delta", "sess", n=3))    # id 3
    log.record(_frame("tool.complete", "sess", n=4))    # id 4

    # since_id: only ids > 2
    got = EL.read_events("sess", since_id=2, root=tmp_path)
    assert [r["id"] for r in got] == [3, 4]

    # types: only message.delta
    got = EL.read_events("sess", types=["message.delta"], root=tmp_path)
    assert [r["id"] for r in got] == [1, 3]

    # limit: oldest-first, capped
    got = EL.read_events("sess", limit=2, root=tmp_path)
    assert [r["id"] for r in got] == [1, 2]

    # since_id + types together
    got = EL.read_events("sess", since_id=1, types=["tool.start", "tool.complete"], root=tmp_path)
    assert [r["id"] for r in got] == [2, 4]

    # unknown session -> empty, never raises
    assert EL.read_events("nope", root=tmp_path) == []


def test_events_replay_rpc_end_to_end(monkeypatch):
    # EventLog() with default root resolves get_hermes_home()/sessions, which the
    # autouse hermetic fixture points at a per-test tempdir. Record there, then
    # replay through the real dispatcher.
    log = EL.EventLog()  # default (lazily-resolved) root
    for i in range(1, 4):
        log.record(_frame("message.delta", "s1", n=i))
    log.record(_frame("tool.start", "s1", n=99))  # id 4

    resp = server.dispatch(
        {"jsonrpc": "2.0", "id": "r1", "method": "events.replay",
         "params": {"session_id": "s1", "since_id": 2}}
    )
    result = resp["result"]
    assert result["session_id"] == "s1"
    assert result["count"] == 2
    assert result["last_id"] == 4
    assert [f["params"]["type"] for f in result["frames"]] == ["message.delta", "tool.start"]
    # records carry forensic metadata (id + ts) alongside the frame.
    assert [r["id"] for r in result["records"]] == [3, 4]

    # missing session_id -> -32602
    err = server.dispatch({"jsonrpc": "2.0", "id": "r2", "method": "events.replay", "params": {}})
    assert err["error"]["code"] == -32602


# ── denylist (pm.tick) ───────────────────────────────────────────────────────


def test_pm_tick_gets_an_id_but_is_never_persisted_or_ringed(tmp_path):
    log = EL.EventLog(root=tmp_path)
    tick_id = log.record(_frame("pm.tick", venue="kalshi"))  # sessionless, denied
    live_id = log.record(_frame("message.delta", "sess", n=1))

    # It DID consume a monotonic id (so the live SSE `id:` stays dense)...
    assert tick_id == 1 and live_id == 2
    # ...but nothing was persisted for it (no sessionless file, and the message
    # log has only the one real frame with id 2)...
    assert list(tmp_path.glob("**/events.jsonl")) == [tmp_path / "sess" / "events.jsonl"]
    assert [r["id"] for r in _read_lines(tmp_path / "sess" / "events.jsonl")] == [2]
    # ...and it is NOT held for resume.
    ring = log.recent_since(0)
    assert all(f["params"]["type"] != "pm.tick" for _eid, f in ring)
    assert [eid for eid, _f in ring] == [2]


# ── fail-open: no home / unwritable ──────────────────────────────────────────


def test_sessionless_frame_writes_nothing_and_returns_true(tmp_path):
    log = EL.EventLog(root=tmp_path)
    # A frame with no session_id has no per-session home -> no file, no crash.
    assert log.write(_frame("gateway.ready")) is True
    assert list(tmp_path.rglob("events.jsonl")) == []
    # ...but it is still ringed for SSE resume (sessionless events resume too).
    assert [f["params"]["type"] for _e, f in log.recent_since(0)] == ["gateway.ready"]


def test_persist_io_error_is_swallowed(tmp_path):
    # Point the root at a FILE so mkdir(root/sess) raises NotADirectoryError.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    log = EL.EventLog(root=blocker)
    # A session frame would try to write under the file -> I/O error, swallowed.
    assert log.write(_frame("message.delta", "sess", n=1)) is True  # never raises
    # No file materialised, transport stayed alive.
    assert blocker.is_file()


# ── SSE Last-Event-ID resume, end-to-end over real sockets ───────────────────


@pytest.fixture
def http_factory():
    original_stdio = server._stdio_transport
    started: list = []

    def make(**kwargs):
        kwargs.setdefault("port", 0)
        kwargs.setdefault("host", "127.0.0.1")
        srv = H.make_server(**kwargs)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        started.append((srv, t))
        host, port = srv.server_address[0], srv.server_address[1]
        return srv, host, port

    try:
        yield make
    finally:
        for srv, t in started:
            srv.shutdown()
            srv.server_close()
            t.join(timeout=5)
        server._stdio_transport = original_stdio


def _open_sse(host, port, *, last_event_id=None, timeout=6.0):
    """Open /events; return (sock, leftover_bytes) — leftover is everything the
    priming read already pulled PAST `: connected` (e.g. resume frames that
    arrive in the same TCP segment), so the caller never loses them."""
    s = socket.create_connection((host, port), timeout=timeout)
    s.settimeout(timeout)
    req = f"GET /events HTTP/1.1\r\nHost: {host}:{port}\r\n"
    if last_event_id is not None:
        req += f"Last-Event-ID: {last_event_id}\r\n"
    req += "Connection: keep-alive\r\n\r\n"
    s.sendall(req.encode())
    buf = _recv_until(s, b": connected", timeout)
    # Hand back whatever followed the priming comment so it isn't discarded.
    leftover = buf.split(b": connected\n\n", 1)[1] if b": connected\n\n" in buf else b""
    return s, leftover


def _recv_until(sock, needle, timeout):
    deadline = time.time() + timeout
    buf = b""
    while needle not in buf and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
    if needle not in buf:
        raise AssertionError(f"never saw {needle!r}; got {buf!r}")
    return buf


def _read_events(sock, count, initial=b"", timeout=6.0):
    """Parse `count` SSE data-events, returning [(id, data_dict), ...].

    `initial` seeds the parse buffer with any bytes already read past the priming
    comment (see _open_sse) so frames delivered in the priming segment aren't lost.
    """
    deadline = time.time() + timeout
    buf = initial
    out = []

    def _drain():
        nonlocal buf
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            eid = None
            data = None
            for line in block.split(b"\n"):
                if line.startswith(b"id:"):
                    eid = int(line[3:].strip())
                elif line.startswith(b"data:"):
                    data = json.loads(line[5:].strip())
            if data is not None:
                out.append((eid, data))

    _drain()  # consume anything already in `initial`
    while len(out) < count and time.time() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        _drain()
    return out


def test_sse_resume_replays_exactly_the_missed_frames(http_factory):
    srv, host, port = http_factory()

    # Connection A: receive two events, remember the last id.
    a, a_left = _open_sse(host, port)
    try:
        server._emit("resume.test", "", {"seq": 1})
        server._emit("resume.test", "", {"seq": 2})
        got_a = _read_events(a, 2, initial=a_left)
    finally:
        a.close()
    ids_a = [eid for eid, _ in got_a]
    seqs_a = [d["params"]["payload"]["seq"] for _, d in got_a]
    assert seqs_a == [1, 2]
    last_id = ids_a[-1]

    # While A is gone, two more events are emitted (buffered only in the log ring).
    server._emit("resume.test", "", {"seq": 3})
    server._emit("resume.test", "", {"seq": 4})

    # Connection B reconnects with Last-Event-ID -> gets EXACTLY the missed frames.
    b, b_left = _open_sse(host, port, last_event_id=last_id)
    try:
        got_b = _read_events(b, 2, initial=b_left)
    finally:
        b.close()

    ids_b = [eid for eid, _ in got_b]
    seqs_b = [d["params"]["payload"]["seq"] for _, d in got_b]
    assert seqs_b == [3, 4]                 # exactly the missed frames
    assert ids_b == [last_id + 1, last_id + 2]  # contiguous ids, no gap
    assert all(sid > last_id for sid in ids_b)  # nothing already-seen replayed
    # The private id stamp never leaks onto the wire frame.
    assert all(EL._EID_KEY not in d for _, d in got_b)


def test_sse_without_resume_header_gets_no_backlog(http_factory):
    srv, host, port = http_factory()
    # Emit before anyone connects: these populate the ring but a fresh client
    # (no Last-Event-ID) must NOT receive them — only live frames from now on.
    server._emit("resume.test", "", {"seq": 1})

    c, c_left = _open_sse(host, port)  # no Last-Event-ID
    try:
        server._emit("resume.test", "", {"seq": 2})
        got = _read_events(c, 1, initial=c_left)
    finally:
        c.close()
    assert [d["params"]["payload"]["seq"] for _, d in got] == [2]
