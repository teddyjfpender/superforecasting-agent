"""Real Ink -> stdio gateway -> SQLite, through the dashboard WebSocket/PTY.

Prerequisite: npm ci && npm run build in ui-tui. The dedicated engineering
workflow supplies that prerequisite; no provider credentials are required.
"""
from contextlib import closing
import json
import os
import signal
import re
from pathlib import Path
import shutil
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from superforecasting_agent.runtime import web_server

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [pytest.mark.skipif(sys.platform == 'win32', reason='dashboard PTY requires POSIX/WSL'), pytest.mark.timeout(60)]


def receipt(home):
    path = home / 'state.db'
    if not path.exists():
        return None
    with closing(sqlite3.connect(path)) as db:
        db.row_factory = sqlite3.Row
        try:
            row = db.execute('SELECT * FROM tui_turns ORDER BY created_at DESC LIMIT 1').fetchone()
            return dict(row) if row else None
        except sqlite3.OperationalError:
            return None


@pytest.fixture
def local_desk(tmp_path, monkeypatch):
    if not shutil.which('node') or not (ROOT / 'ui-tui/dist/entry.js').exists():
        pytest.skip('build ui-tui to run the real desk integration')
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            prompt = parse_qs(urlparse(self.path).query)['prompt'][0]
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(json.dumps({'delta': 'durable fixture prefix'}).encode() + b'\n')
                self.wfile.flush()
                if 'hold' in prompt:
                    for _ in range(300):
                        self.wfile.write(b'{}\n')
                        self.wfile.flush()
                        time.sleep(.05)
                elif 'failure' in prompt:
                    self.wfile.write(b'{"error":"fixture authentication expired 401"}\n')
                elif 'quota' in prompt:
                    self.wfile.write(b'{"error":"fixture quota exceeded 429"}\n')
                elif 'disconnect' in prompt:
                    return
                else:
                    self.wfile.write(b'{"done":true}\n')
            except (BrokenPipeError, ConnectionResetError):
                pass
    provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    wrapper = tmp_path / 'python-fixture'
    wrapper.write_text(f'#!{sys.executable}\nimport runpy\nrunpy.run_path({str(ROOT / "tests/fixtures/runtime/local_desk_gateway.py")!r}, run_name="__main__")\n')
    wrapper.chmod(0o700)
    for prefix in ('SUPERFORECASTING_AGENT', 'FORECAST', 'HERMES'):
        monkeypatch.setenv(prefix + '_HOME', str(tmp_path))
        monkeypatch.setenv(prefix + '_PYTHON', str(wrapper))
        monkeypatch.setenv(prefix + '_TUI_CRON_TICKER', '0')
    monkeypatch.setenv('FORECAST_TEST_PROVIDER_URL', f'http://127.0.0.1:{provider.server_port}/')
    monkeypatch.setenv('FORECAST_TEST_GATEWAY_PID', str(tmp_path / 'gateway-child.pid'))
    monkeypatch.setenv('SUPERFORECASTING_AGENT_PYTHON_SRC_ROOT', str(ROOT))
    (tmp_path / 'config.yaml').write_text('model: local-fixture\ndisplay:\n  skin: forecast\n')
    monkeypatch.setattr(web_server, '_DASHBOARD_FORECAST_DESK_ENABLED', True)
    monkeypatch.setattr(web_server, '_SESSION_TOKEN', 'local-engineering')
    monkeypatch.setattr(web_server, '_resolve_chat_argv', lambda **kw: (['node', str(ROOT / 'ui-tui/dist/entry.js')], str(ROOT), None))
    bridges = []
    original = web_server.PtyBridge.spawn
    def spawn(*args, **kwargs):
        bridge = original(*args, **kwargs)
        bridges.append(bridge)
        return bridge
    monkeypatch.setattr(web_server.PtyBridge, 'spawn', spawn)
    try:
        with TestClient(web_server.app) as client:
            yield client, tmp_path, bridges
    finally:
        for bridge in bridges:
            bridge.close()
        provider.shutdown()
        provider.server_close()
        thread.join(3)


def until(ws, predicate, *, screen=None):
    output = b''
    try:
        for _ in range(300):
            frame = ws.receive()
            assert "bytes" in frame, f"Forecast Desk transport failed before expected output: {frame}"
            output += frame["bytes"]
            if screen is None:
                plain = re.sub(rb'\x1b\[[0-?]*[ -/]*[@-~]', b'', output)
            else:
                screen.feed(frame["bytes"])
                plain = screen.text().encode("utf-8")
            if predicate(plain):
                return output
        pytest.fail('desk never reached expected state')
    finally:
        print('TERMINAL:', repr(output[-5000:]))
        if screen is not None:
            print('SCREEN:', screen.text())


@pytest.mark.parametrize('prompt,visible', [('failure', b'expired'), ('quota', b'exceeded'), ('disconnect', b'ended')])
def test_real_desk_failure_and_reconnect(local_desk, prompt, visible):
    client, home, bridges = local_desk
    url = '/api/pty?token=local-engineering&channel=local-fixture'
    with client.websocket_connect(url) as ws:
        data = until(ws, lambda out: b'local-fixture' in out)
        ws.send_text(prompt + '\r')
        data += until(ws, lambda out: visible in out)
        saved = receipt(home)
        assert saved['status'] == 'error'
        assert saved['partial_text'] == 'durable fixture prefix'
        ws.close(code=1006)
    assert bridges[0].is_alive()
    with client.websocket_connect(url + f'&cursor={len(data)}') as ws:
        ws.send_text('\x1b[RESIZE:100;35]')
        ws.send_text('complete\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete')
        assert len(bridges) == 1
        ws.close(code=1000)


@pytest.mark.parametrize('terminate', [False, True], ids=['cancel', 'gateway-death'])
def test_real_desk_interruption_preserves_work(local_desk, terminate):
    client, home, bridges = local_desk
    url = '/api/pty?token=local-engineering&channel=local-interruption'
    with client.websocket_connect(url) as ws:
        until(ws, lambda out: b'local-fixture' in out)
        ws.send_text('hold\r')
        until(ws, lambda out: receipt(home) and receipt(home)['partial_text'] == 'durable fixture prefix')
        before = receipt(home)
        assert before['status'] == 'running'
        if terminate:
            pid = int((home / 'gateway-child.pid').read_text())
            os.kill(pid, signal.SIGKILL)
        else:
            ws.send_text('\x03')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'interrupted' and (not terminate or b'Previous' in out))
        saved = receipt(home)
        assert saved['id'] == before['id']
        assert saved['partial_text'] == before['partial_text']
        assert saved['status'] == 'interrupted'
        ws.close(code=1000)


def test_real_desk_shared_forecast_operations(local_desk):
    from functools import partial
    from tests.tui_pty.vt import VTScreen
    from forecasting.ledger import ForecastLedger

    client, home, _ = local_desk
    ledger = ForecastLedger()
    question = ledger.create_question(
        title="Will the fixture finish?",
        resolution_criteria="Resolves YES if the official fixture completion record confirms completion by 2026-09-11; otherwise NO.",
    )
    ledger.create_snapshot(question_id=question.id, probability_or_distribution=0.7, rationale="Baseline.")
    with client.websocket_connect('/api/pty?token=local-engineering&channel=forecast-operations') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        observe = partial(until, ws, screen=VTScreen(rows=45, cols=160))
        observe(lambda out: b'local-fixture' in out)
        ws.send_text('/review --last 7d\r')
        observe(lambda out: question.id.encode() in out)
        ws.send_text('q')
        observe(lambda out: b'TODAY' in out and b'Esc close' not in out)
        ws.send_text(f'/resolve {question.id} --outcome true --source fixture\r')
        observe(lambda out: b'auto_score:' in out)
        resolution = ledger.get_latest_resolution(question.id)
        assert resolution is not None
        assert ledger.get_question(question.id).status == 'resolved'
        ws.send_text('q')
        observe(lambda out: b'TODAY' in out and b'Esc close' not in out)
        ws.send_text(f'/forecast resolve {question.id} --outcome true --source fixture\r')
        observe(lambda out: b'auto_score:' in out)
        assert ledger.get_latest_resolution(question.id).id == resolution.id
        score = ledger.get_current_score(question.id)
        ws.send_text('q')
        observe(lambda out: b'TODAY' in out and b'Esc close' not in out)
        ws.send_text(f'/score {question.id} --baselines\r')
        observe(lambda out: b'baseline_scores: none' in out)
        assert ledger.get_current_score(question.id).id == score.id
        ws.close(code=1000)


def test_real_desk_unavailable_history_does_not_start_replacement(local_desk, monkeypatch):
    client, home, _ = local_desk
    monkeypatch.setenv('FORECAST_TEST_STORE_FAILURE', '1')
    (home / 'config.yaml').write_text('model: local-fixture\ndisplay:\n  skin: forecast\n  tui_auto_resume_recent: true\n', encoding='utf-8')
    with client.websocket_connect('/api/pty?token=local-engineering&channel=history-unavailable') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'session startup unavailable' in out)
        assert receipt(home) is None
        state = home / 'state.db'
        if state.exists():
            with closing(sqlite3.connect(state)) as db:
                assert db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
        ws.close(code=1000)


def test_desk_screen_observation_retains_unchanged_rows():
    from tests.tui_pty.vt import VTScreen

    class Frames:
        def __init__(self):
            self.frames = iter([
                b"\x1b[HTODAY\x1b[2;1Hloading",
                b"\x1b[2;1H\x1b[2Kresolved",
            ])

        def receive(self):
            return {"bytes": next(self.frames)}

    ws = Frames()
    screen = VTScreen(rows=3, cols=20)
    until(ws, lambda out: b"loading" in out, screen=screen)
    delta = until(ws, lambda out: b"TODAY" in out and b"resolved" in out, screen=screen)
    assert b"TODAY" not in delta
    assert b"loading" not in screen.text().encode()
