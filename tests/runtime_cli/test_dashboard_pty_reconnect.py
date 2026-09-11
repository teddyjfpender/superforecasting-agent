"""Reconnect the real PTY transport without replacing the running child."""

import sys
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from superforecasting_agent.runtime import web_server


@pytest.fixture
def desk_client(monkeypatch):
    monkeypatch.setattr(web_server, "_DASHBOARD_FORECAST_DESK_ENABLED", True)
    monkeypatch.setattr(web_server, "_SESSION_TOKEN", "reconnect-fixture")
    program = "import sys\nprint('READY', flush=True)\nfor n,line in enumerate(sys.stdin,1): print(f'{n}:{line.strip()}', flush=True)"
    monkeypatch.setattr(web_server, "_resolve_chat_argv", lambda **kw: ([sys.executable, "-u", "-c", program], None, None))
    bridges = []
    original = web_server.PtyBridge.spawn

    def spawn(*args, **kwargs):
        bridge = original(*args, **kwargs)
        bridges.append(bridge)
        return bridge

    monkeypatch.setattr(web_server.PtyBridge, "spawn", spawn)
    with TestClient(web_server.app) as client:
        yield client, bridges
    for bridge in bridges:
        bridge.close()


def _url(cursor=0):
    return "/api/pty?" + urlencode({"token": "reconnect-fixture", "channel": "reconnect-test", "cursor": cursor})


def _receive_until(ws, expected):
    output = b""
    while expected not in output:
        output += ws.receive_bytes()
    return output


@pytest.mark.timeout(15)
def test_transient_disconnect_preserves_child_and_output_cursor(desk_client):
    client, bridges = desk_client
    with client.websocket_connect(_url()) as ws:
        output = _receive_until(ws, b"READY")
        ws.send_text("first\n")
        output += _receive_until(ws, b"1:first")
        ws.close(code=1006)
    assert bridges[0].is_alive(), "transport loss must not terminate the forecast TUI"
    with client.websocket_connect(_url(len(output))) as ws:
        ws.send_text("second\n")
        resumed = _receive_until(ws, b"2:second")
        assert b"READY" not in resumed
        assert b"1:first" not in resumed
        assert len(bridges) == 1
        ws.close(code=1000)
    assert not bridges[0].is_alive()


@pytest.mark.timeout(60)
def test_repeated_unicode_reconnects_keep_one_child_and_byte_cursor(desk_client):
    client, bridges = desk_client
    cursor = 0
    previous = None
    for turn in range(20):
        with client.websocket_connect(_url(cursor)) as ws:
            received = _receive_until(ws, b"READY") if turn == 0 else b""
            ws.send_text(f"\x1b[RESIZE:{80 + turn};{30 + turn}]")
            value = f"turn-{turn}: café 東京"
            marker = f"{turn + 1}:{value}".encode()
            ws.send_text(value + "\n")
            received += _receive_until(ws, marker)
            assert previous is None or previous not in received
            cursor += len(received)  # UTF-8 byte count, never character count.
            previous = marker
            ws.close(code=1000 if turn == 19 else 1006)
        assert len(bridges) == 1
        assert bridges[0].is_alive() == (turn != 19)
