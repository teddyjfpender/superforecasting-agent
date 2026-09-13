"""Native ConPTY/POSIX terminal -> real host -> durable session recovery."""
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from scripts.terminal_session import TerminalSession
from tests.tui_pty.vt import VTScreen

ROOT = Path(__file__).resolve().parents[1]


def receipt(home):
    if not (home / "state.db").exists():
        return None
    with closing(sqlite3.connect(home / "state.db")) as db:
        db.row_factory = sqlite3.Row
        try:
            row = db.execute("SELECT * FROM tui_turns ORDER BY created_at DESC LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            return None
        return dict(row) if row else None


@pytest.mark.timeout(90)
def test_native_terminal_cancel_and_reconnect(tmp_path):
    node = shutil.which("node")
    assert node and (ROOT / "ui-tui/dist/entry.js").is_file(), "build the TUI before qualification"

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(b'{"delta":"durable native prefix"}\n')
                self.wfile.flush()
                while not stop.is_set():
                    self.wfile.write(b'{}\n')
                    self.wfile.flush()
                    stop.wait(.05)
            except (BrokenPipeError, ConnectionResetError):
                pass

    stop = threading.Event()
    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "host.token"
    token.write_text("native-fixture")
    (tmp_path / "config.yaml").write_text("model: local-fixture\ndisplay:\n  skin: forecast\n  tui_auto_resume_recent: true\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color",
           "FORECAST_TEST_HEADLESS": "1", "FORECAST_TEST_PROVIDER_URL": f"http://127.0.0.1:{provider.server_port}/",
           "FORECAST_TEST_GATEWAY_PID": str(tmp_path / "host.pid")}
    for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES"):
        env[prefix + "_HOME"] = str(tmp_path)
        env[prefix + "_TUI_CRON_TICKER"] = "0"
    log_path = tmp_path / "host.log"
    host = None
    try:
        with log_path.open("w") as log:
            host = subprocess.Popen([sys.executable, str(ROOT / "tests/fixtures/runtime/local_desk_gateway.py"),
                                     "--port", "0", "--token-file", str(token)],
                                    cwd=ROOT, env=env, stdout=log, stderr=log)
        deadline = time.monotonic() + 20
        port = None
        while time.monotonic() < deadline:
            found = re.search(r"http://127\.0\.0\.1:(\d+)", log_path.read_text())
            if found:
                port = found.group(1)
                break
            assert host.poll() is None, log_path.read_text()
            time.sleep(.05)
        assert port, log_path.read_text()
        env["SUPERFORECASTING_AGENT_TUI_GATEWAY_URL"] = f"ws://127.0.0.1:{port}/api/ws?token=native-fixture"
        argv = [node, "--experimental-websocket", str(ROOT / "ui-tui/dist/entry.js")]
        saved = None
        for cycle in range(3):
            if saved:
                env["SUPERFORECASTING_AGENT_TUI_RESUME"] = saved["session_id"]
            with TerminalSession(argv, cwd=ROOT, env=env) as terminal:
                screen = VTScreen(rows=45, cols=160)
                def until(predicate):
                    deadline = time.monotonic() + 15
                    while time.monotonic() < deadline:
                        screen.feed(terminal.read())
                        if predicate(screen.text()):
                            return
                    pytest.fail(screen.text() + "\nHOST:\n" + log_path.read_text())
                until(lambda text: "local-fixture" in text)
                terminal.resize(35, 120)
                screen.resize(35, 120)
                if cycle == 0:
                    terminal.write(b"hold\r")
                    until(lambda text: receipt(tmp_path) and receipt(tmp_path)["partial_text"] == "durable native prefix")
                    saved = receipt(tmp_path)
                    assert saved["status"] == "running"
                    terminal.write(b"\x03")
                    until(lambda text: receipt(tmp_path)["status"] == "interrupted")
                else:
                    until(lambda text: "durable native prefix" in text)
                row = receipt(tmp_path)
                assert row["id"] == saved["id"]
                assert row["partial_text"] == saved["partial_text"]
                assert row["status"] == "interrupted"
                terminal.write(b"/quit\r")
                assert terminal.wait() == 0
    finally:
        stop.set()
        if host is not None:
            host.terminate()
            try:
                host.wait(timeout=10)
            except subprocess.TimeoutExpired:
                host.kill()
                host.wait(timeout=5)
        provider.shutdown()
        provider.server_close()
        thread.join(3)
