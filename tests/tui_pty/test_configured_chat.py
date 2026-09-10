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
                for delta, finish in [({"role": "assistant", "content": REPLY}, None), ({}, "stop")]:
                    event = {
                        "id": "fixture", "object": "chat.completion.chunk",
                        "created": 1, "model": "fixture-local",
                        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    }
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                    self.wfile.flush()
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
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


@pytest.mark.live_system_guard_bypass
@pytest.mark.timeout(90)
def test_configured_prompt_streams_through_local_provider(tui_bundle, tui_env, tui_home, local_provider):
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
        session.send(PROMPT.encode())
        session.wait_for(lambda screen: PROMPT in screen.text(), timeout=5, what="composer input")
        # Enter must be a separate event; a single text+Enter write is a paste.
        session.settle(quiet=0.1, max_wait=0.5)
        session.send(b"\r")
        session.wait_for(lambda screen: REPLY in screen.text(), timeout=40, what="streamed provider reply")
        assert any(
            path == "/v1/chat/completions" and body.get("stream")
            and any(message.get("role") == "user" and PROMPT in str(message.get("content"))
                    for message in body.get("messages", []))
            for path, body in requests
        ), "The rendered reply must come from a streamed request carrying the typed prompt"
        session.send(b"\x03")
        assert session.wait_exit(timeout=15, sweep=False) == 0
