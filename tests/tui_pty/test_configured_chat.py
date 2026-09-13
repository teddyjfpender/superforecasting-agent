"""Exercise the real composer, gateway, agent and streamed transcript together."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from .pty_session import PtySession
from .conftest import REPO_ROOT

REPLY = "LOCAL FIXTURE RESPONSE: Forecast desk transport verified."
PROMPT = "Reply with the fixture response."


@pytest.fixture()
def local_provider():
    requests = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def json_response(self, value):
            data = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.json_response({"object": "list", "data": [{"id": "fixture-local"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/api/show":
                self.json_response({"model_info": {}, "capabilities": ["completion"]})
                return
            requests.append((self.path, body))
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                holding = any(message.get("role") == "user" and message.get("content") == "HOLD STREAM FOR CANCELLATION"
                              for message in body.get("messages", [])[-1:])
                last_user = next((str(message.get("content", "")) for message in reversed(body.get("messages", [])) if message.get("role") == "user"), "")
                reply = "PARTIAL BEFORE CANCELLATION" if holding else REPLY + " " + last_user
                for delta, finish in [({"role": "assistant", "content": reply}, None), ({}, "stop")]:
                    event = {
                        "id": "fixture", "object": "chat.completion.chunk",
                        "created": 1, "model": "fixture-local",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    }
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
                    if holding:
                        release.wait(15)
                        return
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self.json_response({
                    "id": "fixture", "object": "chat.completion", "created": 1,
                    "model": "fixture-local",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": REPLY}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                })

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", requests
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(90)
@pytest.mark.parametrize("typing_mode", ["chunk", "rapid", "rapid-submit"])
def test_configured_prompt_streams_through_local_provider(tui_bundle, tui_env, tui_home, local_provider, typing_mode):
    endpoint, requests = local_provider
    config = {
        "model": {"default": "fixture-local", "provider": "custom", "base_url": endpoint},
        "display": {"skin": "forecast"},
    }
    (tui_home / ".superforecasting-agent" / "config.yaml").write_text(json.dumps(config))
    env = dict(tui_env, OPENAI_BASE_URL=endpoint, OPENAI_API_KEY="fixture-local-only")
    env["SUPERFORECASTING_AGENT_TUI_TOOLSETS"] = "forecasting"
    with PtySession(["node", str(tui_bundle)], cwd=str(REPO_ROOT), env=env, rows=44, cols=120) as session:
        session.wait_for(lambda screen: "fixture-local" in screen.text(), timeout=20, what="configured home")
        session.settle()
        if typing_mode.startswith("rapid"):
            import time
            for char in PROMPT:
                session.send(char.encode())
                time.sleep(0.001)
        else:
            session.send(PROMPT.encode())
        if typing_mode == "rapid-submit":
            time.sleep(0.01)  # Separate key event, before the 50ms paste debounce.
        else:
            session.wait_for(lambda screen: PROMPT in screen.text(), timeout=5, what="composer input")
            # These modes wait for echo; rapid-submit exercises a coalesced read.
            session.settle(quiet=0.1, max_wait=0.5)
        session.send(b"\r")
        session.wait_for(lambda screen: REPLY in screen.text(), timeout=40, what="streamed provider reply")
        assert any(
            path == "/v1/chat/completions" and body.get("stream")
            and any(message.get("role") == "user" and PROMPT in str(message.get("content"))
                    for message in body.get("messages", []))
            for path, body in requests
        ), "The rendered reply must come from a streamed request carrying the typed prompt"
        session.wait_for(lambda s: "─ ready" in s.text(), timeout=20, what="completed turn")
        session.send(b"\x03")
        assert session.wait_exit(timeout=15, sweep=False) == 0


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
def test_cancel_stalled_stream_then_resume_saved_session(tui_bundle, tui_env, tui_home, local_provider):
    import sqlite3
    from contextlib import closing

    endpoint, requests = local_provider
    home = tui_home / ".superforecasting-agent"
    (home / "config.yaml").write_text(json.dumps({"model": {"default": "fixture-local", "provider": "custom", "base_url": endpoint}}))
    env = dict(tui_env, OPENAI_BASE_URL=endpoint, OPENAI_API_KEY="fixture-local-only",
               SUPERFORECASTING_AGENT_TUI_TOOLSETS="forecasting")

    def submit(session, text):
        session.send(text.encode())
        session.settle(quiet=0.1, max_wait=0.5)
        session.send(b"\r")

    with PtySession(["node", str(tui_bundle)], cwd=str(REPO_ROOT), env=env, rows=44, cols=120) as session:
        session.wait_for(lambda s: "fixture-local" in s.text(), timeout=20, what="configured desk")
        session.settle()
        submit(session, "HOLD STREAM FOR CANCELLATION")
        session.wait_for(lambda s: "PARTIAL BEFORE CANCELLATION" in s.text(), timeout=30, what="partial stream")
        session.send(b"\x03")
        session.wait_for(lambda s: "interrupt" in s.text().lower(), timeout=5, what="cancellation notice")
        session.resize(rows=35, cols=100)
        session.settle()
        submit(session, PROMPT)
        session.wait_for(lambda s: REPLY in s.text(), timeout=30, what="successful turn after cancellation")
        session.wait_for(lambda s: "─ ready" in s.text(), timeout=20, what="completed follow-up")
        session.send(b"\x03")
        assert session.wait_exit(timeout=15, sweep=False) == 0
    with closing(sqlite3.connect(home / "state.db")) as conn:
        saved = conn.execute("SELECT session_id FROM messages WHERE role='user' AND content=?", (PROMPT,)).fetchall()
        assert len(saved) == 1, "the completed follow-up must be durable exactly once"
        sid = saved[0][0]
    resumed_env = dict(env, SUPERFORECASTING_AGENT_TUI_RESUME=sid)
    with PtySession(["node", str(tui_bundle)], cwd=str(REPO_ROOT), env=resumed_env, rows=44, cols=120) as session:
        session.wait_for(lambda s: REPLY in s.text(), timeout=25, what="durable transcript after restart")
        assert PROMPT in session.screen.text()
        session.send(b"\x03")
        assert session.wait_exit(timeout=15, sweep=False) == 0


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(240)
def test_repeated_unicode_turns_resize_and_restart(tui_bundle, tui_env, tui_home, local_provider):
    """Sustained real transport exercise: exact-once Unicode history across restarts."""
    import sqlite3
    import os
    from contextlib import closing

    cycles = int(os.environ.get("FORECAST_TUI_SOAK_CYCLES", "3"))
    turns = int(os.environ.get("FORECAST_TUI_SOAK_TURNS", "6"))
    assert 1 <= cycles <= 20 and 1 <= turns <= 20
    endpoint, _ = local_provider
    home = tui_home / ".superforecasting-agent"
    (home / "config.yaml").write_text(json.dumps({"model": {"default": "fixture-local", "provider": "custom", "base_url": endpoint}}))
    env = dict(tui_env, OPENAI_BASE_URL=endpoint, OPENAI_API_KEY="fixture-local-only",
               SUPERFORECASTING_AGENT_TUI_TOOLSETS="forecasting")
    prompts = []
    sid = None
    for cycle in range(cycles):
        current_env = dict(env, **({"SUPERFORECASTING_AGENT_TUI_RESUME": sid} if sid else {}))
        with PtySession(["node", str(tui_bundle)], cwd=str(REPO_ROOT), env=current_env, rows=44, cols=120) as session:
            session.wait_for(lambda s: (REPLY if sid else "fixture-local") in s.text(), timeout=25, what="ready or resumed desk")
            session.settle()
            for turn in range(turns):
                marker = f"CYCLE{cycle}TURN{turn}"
                prompt = f"{marker} café 東京 — probability 50%"
                prompts.append(prompt)
                session.resize(rows=35 + turn, cols=80 if turn % 2 else 120)
                session.settle()
                session.send(prompt.encode("utf-8"))
                session.settle(quiet=.1, max_wait=.5)
                session.send(b"\r")
                session.wait_for(lambda s: any(marker in line and "verified." in line for line in s.text().splitlines()),
                                 timeout=30, what="unique streamed reply")
            # A streamed final token can precede message.complete. Wait for
            # the desk's idle status so Ctrl+C requests exit, not cancellation.
            session.wait_for(lambda s: "─ ready" in s.text(), timeout=20, what="completed turn")
            session.send(b"\x03")
            assert session.wait_exit(timeout=15, sweep=False) == 0
        with closing(sqlite3.connect(home / "state.db")) as conn:
            rows = conn.execute("SELECT session_id,content FROM messages WHERE role='user'").fetchall()
            for prompt in prompts:
                matches = [row for row in rows if row[1] == prompt]
                assert len(matches) == 1, "every Unicode prompt survives exactly once"
                sid = matches[0][0]


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(120)
@pytest.mark.parametrize("recovery", ["cancel", "gateway-death"])
def test_native_command_watch_cancel_then_continue(tui_bundle, tui_env, tui_home, local_provider, recovery):
    """Real Ctrl+C cancels native work without exiting or starting a model turn."""
    import sqlite3
    from contextlib import closing

    endpoint, requests = local_provider
    home = tui_home / ".superforecasting-agent"
    (home / "config.yaml").write_text(json.dumps({
        "model": {"default": "fixture-local", "provider": "custom", "base_url": endpoint},
        "display": {"skin": "forecast"},
    }), encoding="utf-8")
    board = home / "native-command-test.db"
    env = dict(tui_env, OPENAI_BASE_URL=endpoint, OPENAI_API_KEY="fixture-local-only",
               SUPERFORECASTING_AGENT_KANBAN_DB=str(board))

    def submit(session, text):
        session.send(text.encode())
        session.settle(quiet=0.1, max_wait=0.5)
        session.send(b"\r")

    with PtySession(["node", str(tui_bundle)], cwd=str(REPO_ROOT), env=env, rows=44, cols=120) as session:
        session.wait_for(lambda s: "fixture-local" in s.text(), timeout=20, what="configured desk")
        session.settle()
        submit(session, "/kanban watch --interval 3600")
        session.wait_for(lambda s: "Running /kanban" in s.text(), timeout=15, what="native command activity")
        session.resize(rows=35, cols=100)
        session.wait_for(lambda s: "Ctrl+C to cancel" in s.text(), timeout=5, what="command cancellation hint after resize")
        if recovery == "cancel":
            session.send(b"\x03")
            session.wait_for(lambda s: "(stopped)" in s.text(), timeout=10, what="native watch cancellation result")
        else:
            import signal
            from .test_gateway_respawn import gateway_processes, shows_reconnect_notice
            psutil = pytest.importorskip("psutil")
            children = gateway_processes(psutil, session._pgid)
            assert len(children) == 1
            original_pid = children[0].pid
            children[0].send_signal(signal.SIGKILL)
            session.wait_for(shows_reconnect_notice, timeout=15, what="gateway loss notice during command")
            session.wait_for(lambda _: any(p.pid != original_pid for p in gateway_processes(psutil, session._pgid)),
                             timeout=30, what="replacement gateway process")
            session.wait_for(lambda s: "ready" in s.text() and "Running /kanban" not in s.text(),
                             timeout=30, what="ready desk without stale command activity")
        assert "Running /kanban" not in session.screen.text()
        assert "Cancelling /kanban" not in session.screen.text()
        submit(session, '/kanban create "after native cancellation"')
        session.wait_for(lambda s: "Created" in s.text() and "Running /kanban" not in s.text()
                         and "Cancelling /kanban" not in s.text(), timeout=15,
                         what="completed command after cancellation")
        with closing(sqlite3.connect(board)) as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks WHERE title=?", ("after native cancellation",)).fetchone()[0] == 1
        assert not requests, "native commands must not make model calls"
        session.send(b"\x03")
        assert session.wait_exit(timeout=15, sweep=False) == 0
