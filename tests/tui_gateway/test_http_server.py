"""Tests for the HTTP + SSE transport (``tui_gateway.http_server``).

Every test spins a real :class:`~tui_gateway.http_server.GatewayHTTPServer` on
an ephemeral port and drives it over real sockets — no mocked HTTP layer — so
the JSON-RPC round-trip, the SSE event fanout, the bearer-token gate, and the
concurrency behaviour are all exercised end-to-end against the actual gateway
dispatcher and event pipeline.
"""

from __future__ import annotations

import http.client
import json
import socket
import threading
import time

import pytest

from tui_gateway import http_server as H
from tui_gateway import server
from tui_gateway.entry import _parse_http_args, _split_host_port


# ── harness ────────────────────────────────────────────────────────────────


class _Handle:
    def __init__(self, srv, host, port, token):
        self.srv = srv
        self.host = host
        self.port = port
        self.token = token


@pytest.fixture
def http_factory():
    """Factory that builds + starts real servers and cleans them all up.

    Restores ``server._stdio_transport`` after the test, since ``make_server``
    swaps it to install the event hub.
    """
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
        return _Handle(srv, host, port, srv.token)

    try:
        yield make
    finally:
        for srv, t in started:
            srv.shutdown()
            srv.restore_transport()
            srv.server_close()
            t.join(timeout=5)
        server._stdio_transport = original_stdio


def _post_rpc(handle: _Handle, body: dict, token=None):
    conn = http.client.HTTPConnection(handle.host, handle.port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("POST", "/rpc", json.dumps(body), headers)
    resp = conn.getresponse()
    data = resp.read()
    status = resp.status
    conn.close()
    return status, data


def _get(handle: _Handle, path: str, token=None):
    conn = http.client.HTTPConnection(handle.host, handle.port, timeout=10)
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request("GET", path, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    status = resp.status
    conn.close()
    return status, data


def _open_sse(handle: _Handle, token=None, timeout=6.0) -> socket.socket:
    """Open an /events stream and block until the subscription is live."""
    s = socket.create_connection((handle.host, handle.port), timeout=timeout)
    s.settimeout(timeout)
    req = f"GET /events HTTP/1.1\r\nHost: {handle.host}:{handle.port}\r\n"
    if token:
        req += f"Authorization: Bearer {token}\r\n"
    req += "Connection: keep-alive\r\n\r\n"
    s.sendall(req.encode())
    # The handler writes ": connected" right after subscribing to the hub, so
    # once we've seen it the subscription is guaranteed registered.
    _recv_until(s, b": connected", timeout)
    return s


def _recv_until(sock: socket.socket, needle: bytes, timeout: float) -> bytes:
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


# ── health ────────────────────────────────────────────────────────────────


def test_health_open_and_reports_protocol(http_factory):
    from protocol.version import PROTOCOL_VERSION

    h = http_factory()
    status, data = _get(h, "/health")
    assert status == 200
    payload = json.loads(data)
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["uptime"] >= 0.0


# ── RPC round-trip ─────────────────────────────────────────────────────────


def test_rpc_roundtrip_real_method(http_factory):
    h = http_factory()
    status, data = _post_rpc(
        h, {"jsonrpc": "2.0", "id": "r1", "method": "config.get", "params": {"key": "profile"}}
    )
    assert status == 200
    resp = json.loads(data)
    assert resp["id"] == "r1"
    assert "result" in resp
    assert "home" in resp["result"]


def test_rpc_unknown_method_returns_jsonrpc_error(http_factory):
    h = http_factory()
    status, data = _post_rpc(h, {"jsonrpc": "2.0", "id": 7, "method": "does.not.exist"})
    assert status == 200
    resp = json.loads(data)
    assert resp["error"]["code"] == -32601


def test_rpc_parse_error(http_factory):
    h = http_factory()
    conn = http.client.HTTPConnection(h.host, h.port, timeout=10)
    conn.request("POST", "/rpc", "{not json", {"Content-Type": "application/json"})
    resp = conn.getresponse()
    data = json.loads(resp.read())
    conn.close()
    assert resp.status == 200
    assert data["error"]["code"] == -32700


# ── SSE fanout ─────────────────────────────────────────────────────────────


def test_sse_receives_emitted_event(http_factory):
    h = http_factory()
    s = _open_sse(h)
    try:
        # Emit through the REAL pipeline: _emit -> write_json -> _stdio_transport
        # (now the hub) -> broadcast to subscribers.
        server._emit("live.test", "", {"hello": "sse-world"})
        buf = _recv_until(s, b"sse-world", 6.0)
        assert b'"live.test"' in buf
        assert b"data:" in buf
    finally:
        s.close()


# ── auth ───────────────────────────────────────────────────────────────────


def test_loopback_default_needs_no_token(http_factory):
    h = http_factory()  # 127.0.0.1, no token
    assert h.token is None
    status, data = _post_rpc(
        h, {"jsonrpc": "2.0", "id": 1, "method": "config.get", "params": {"key": "profile"}}
    )
    assert status == 200
    assert "result" in json.loads(data)


def test_token_enforced_when_set(http_factory):
    h = http_factory(token="s3cret-token")
    body = {"jsonrpc": "2.0", "id": 1, "method": "config.get", "params": {"key": "profile"}}

    # Missing token -> 401
    status, _ = _post_rpc(h, body)
    assert status == 401

    # Wrong token -> 401
    status, _ = _post_rpc(h, body, token="nope")
    assert status == 401

    # Correct token -> 200
    status, data = _post_rpc(h, body, token="s3cret-token")
    assert status == 200
    assert "result" in json.loads(data)

    # /events also gated
    status, _ = _get(h, "/events")
    assert status == 401

    # HARDENED: /health now requires the token too (not public by default).
    status, _ = _get(h, "/health")
    assert status == 401

    # ...and it opens with the correct token, returning the enriched payload.
    status, data = _get(h, "/health", token="s3cret-token")
    assert status == 200
    assert "version" in json.loads(data)


# ── token-file auth (the hardened default) ──────────────────────────────────


def test_token_file_minted_and_required(http_factory, tmp_path):
    tok_path = tmp_path / "gateway.token"
    h = http_factory(token_file=str(tok_path))
    # a token was minted into the file, 0600, and adopted by the server
    assert tok_path.exists()
    assert oct(tok_path.stat().st_mode & 0o777) == "0o600"
    minted = tok_path.read_text().strip()
    assert minted and h.token == minted

    body = {"jsonrpc": "2.0", "id": 1, "method": "config.get", "params": {"key": "profile"}}
    # loopback but token REQUIRED now (the network-trust hole is closed)
    assert _post_rpc(h, body)[0] == 401
    assert _post_rpc(h, body, token="wrong")[0] == 401
    assert _post_rpc(h, body, token=minted)[0] == 200
    # /health also gated by default
    assert _get(h, "/health")[0] == 401
    assert _get(h, "/health", token=minted)[0] == 200


def test_token_file_reused_across_restarts(http_factory, tmp_path):
    tok_path = tmp_path / "gateway.token"
    tok_path.write_text("preexisting-token\n", encoding="utf-8")
    h = http_factory(token_file=str(tok_path))
    assert h.token == "preexisting-token"  # read, not re-minted
    assert tok_path.read_text().strip() == "preexisting-token"


def test_read_token_file_helper(tmp_path):
    assert H.read_token_file(tmp_path) is None  # absent
    (tmp_path / "gateway.token").write_text("  abc123  \n", encoding="utf-8")
    assert H.read_token_file(tmp_path) == "abc123"  # local client reads it


def test_malformed_auth_header_is_401(http_factory, tmp_path):
    h = http_factory(token_file=str(tmp_path / "gateway.token"))
    conn = http.client.HTTPConnection(h.host, h.port, timeout=10)
    # no "Bearer " prefix
    conn.request("GET", "/status", headers={"Authorization": h.token})
    assert conn.getresponse().status == 401
    conn.close()
    # right scheme, empty token
    conn = http.client.HTTPConnection(h.host, h.port, timeout=10)
    conn.request("GET", "/status", headers={"Authorization": "Bearer "})
    assert conn.getresponse().status == 401
    conn.close()


# ── /status + enriched /health observability ────────────────────────────────


def test_status_requires_token_and_is_enriched(http_factory, tmp_path):
    h = http_factory(token_file=str(tmp_path / "gateway.token"))
    assert _get(h, "/status")[0] == 401  # gated
    status, data = _get(h, "/status", token=h.token)
    assert status == 200
    payload = json.loads(data)
    # the operator's when-something-feels-wrong fields
    for field in ("status", "version", "uptime", "ledger_ok", "cron", "jobs_active", "spend"):
        assert field in payload


def test_health_public_exempts_health_liveness_only(http_factory, tmp_path):
    h = http_factory(token_file=str(tmp_path / "gateway.token"), health_public=True)
    # /health open WITHOUT a token, but liveness subset only (no sensitive fields)
    status, data = _get(h, "/health")
    assert status == 200
    payload = json.loads(data)
    assert payload["status"] == "ok"
    assert "protocol_version" in payload and "version" in payload
    assert "spend" not in payload and "ledger_ok" not in payload
    # /rpc + /status still gated even in health-public mode
    assert _get(h, "/status")[0] == 401
    body = {"jsonrpc": "2.0", "id": 1, "method": "config.get", "params": {"key": "profile"}}
    assert _post_rpc(h, body)[0] == 401


def test_access_log_line_emitted(http_factory, tmp_path, caplog):
    import logging

    h = http_factory(token_file=str(tmp_path / "gateway.token"))
    with caplog.at_level(logging.INFO, logger="tui_gateway.http_server"):
        _get(h, "/health", token=h.token)
        # do_GET flushes the response (_handle_health) BEFORE it emits the
        # access log, and it runs on the server's handler THREAD — so _get()
        # can return before the INFO record is emitted. Wait for it WITHIN the
        # caplog context: once at_level exits it restores the logger level and
        # a late record would be filtered out, dropping it on slower CI runners
        # (the cross-thread race behind the "expected a structured access-log
        # line" flake).
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if any("route=/health" in r.getMessage() for r in caplog.records):
                break
            time.sleep(0.02)
    lines = [r.getMessage() for r in caplog.records if "route=/health" in r.getMessage()]
    assert lines, "expected a structured access-log line"
    assert "method=GET" in lines[0] and "status=200" in lines[0] and "ms=" in lines[0]


def test_default_make_server_binds_loopback(http_factory):
    """Bind verification pinned: the default make_server host is 127.0.0.1."""
    h = http_factory()  # no host kwarg
    assert h.host in ("127.0.0.1", "::1", "localhost")


def test_non_loopback_without_token_refuses_loudly():
    original = server._stdio_transport
    with pytest.raises(RuntimeError, match="non-loopback"):
        H.make_server("0.0.0.0", 0)
    # Refusal happens before the transport swap — the gateway sink is intact.
    assert server._stdio_transport is original


def test_non_loopback_generate_token_binds(http_factory, capsys):
    h = http_factory(host="0.0.0.0", generate_token=True)
    assert h.token  # a token was generated
    out = capsys.readouterr().out
    assert h.token in out  # ...and printed loudly
    h.srv.shutdown()  # release the wildcard bind promptly


# ── concurrency smoke ──────────────────────────────────────────────────────


def test_concurrent_rpcs_with_open_sse(http_factory):
    h = http_factory()
    s = _open_sse(h)
    results: dict[int, int] = {}
    lock = threading.Lock()

    def hit(n: int):
        status, data = _post_rpc(
            h,
            {"jsonrpc": "2.0", "id": n, "method": "config.get", "params": {"key": "profile"}},
        )
        with lock:
            results[n] = status

    try:
        threads = [threading.Thread(target=hit, args=(n,)) for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert results == {1: 200, 2: 200}

        # The SSE stream is still live and still delivers a freshly emitted event.
        server._emit("concurrent.ok", "", {"n": 99})
        buf = _recv_until(s, b"concurrent.ok", 6.0)
        assert b"concurrent.ok" in buf
    finally:
        s.close()


# ── alongside-stdio fanout seam ────────────────────────────────────────────


def test_alongside_stdio_tees_to_both_sinks():
    """alongside_stdio Tees events onto the prior stdio sink AND the hub."""
    captured: list[dict] = []

    class _Fake:
        def write(self, obj):
            captured.append(obj)
            return True

        def close(self):
            pass

    original = server._stdio_transport
    server._stdio_transport = _Fake()
    srv = H.make_server("127.0.0.1", 0, alongside_stdio=True)
    try:
        q = srv.hub.subscribe()
        server._emit("tee.test", "", {"x": 1})
        frame = q.get(timeout=3)
        assert frame["params"]["type"] == "tee.test"  # hub saw it
        assert any(
            f.get("params", {}).get("type") == "tee.test" for f in captured
        )  # prior stdio sink saw it too
    finally:
        # NOTE: serve_forever() was never started for this server, so we must
        # NOT call srv.shutdown() (it would block forever waiting on a loop
        # that isn't running). Just close the socket + restore the sink.
        srv.server_close()
        srv.restore_transport()
        server._stdio_transport = original


# ── entry.py arg parsing ───────────────────────────────────────────────────


def test_parse_http_args_absent():
    assert _parse_http_args(["--foo", "bar"]) is None


def test_parse_http_args_defaults():
    cfg = _parse_http_args(["--http"])
    assert cfg == {
        "host": "127.0.0.1",
        "port": 8765,
        "token": None,
        "generate_token": False,
        "token_file": True,  # hardened default: mint/read {home}/gateway.token
        "health_public": False,
        "alongside_stdio": False,
    }


def test_parse_http_args_default_bind_is_loopback():
    """Bind verification: the entry default host is loopback (127.0.0.1). A public
    bind requires an explicit host on --http, never a silent default."""
    assert _parse_http_args(["--http"])["host"] == "127.0.0.1"
    assert _parse_http_args(["--http", ":9000"])["host"] == "127.0.0.1"
    assert _parse_http_args(["--http", "0.0.0.0:9000"])["host"] == "0.0.0.0"


def test_parse_http_args_token_file_and_health_flags():
    cfg = _parse_http_args(["--http", "--http-no-token-file", "--http-health-public"])
    assert cfg["token_file"] is False
    assert cfg["health_public"] is True
    cfg2 = _parse_http_args(["--http", "--http-token-file", "/tmp/tok"])
    assert cfg2["token_file"] == "/tmp/tok"


def test_parse_http_args_full():
    cfg = _parse_http_args(
        ["--http", "0.0.0.0:9100", "--http-token", "abc", "--http-alongside-stdio"]
    )
    assert cfg["host"] == "0.0.0.0"
    assert cfg["port"] == 9100
    assert cfg["token"] == "abc"
    assert cfg["alongside_stdio"] is True


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("127.0.0.1:8000", ("127.0.0.1", 8000)),
        (":9000", ("127.0.0.1", 9000)),
        ("9001", ("127.0.0.1", 9001)),
        ("192.168.1.5", ("192.168.1.5", 8765)),
    ],
)
def test_split_host_port(spec, expected):
    assert _split_host_port(spec, "127.0.0.1", 8765) == expected
