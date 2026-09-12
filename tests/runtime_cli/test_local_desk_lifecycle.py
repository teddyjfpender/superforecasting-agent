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


@pytest.mark.parametrize('fail_reset', [False, True], ids=['reset', 'failed-reset-new-session'])
def test_real_desk_tool_reset_owns_agents_and_preserves_receipt(local_desk, monkeypatch, fail_reset):
    import yaml
    from tests.tui_pty.vt import VTScreen

    client, home, _ = local_desk
    monkeypatch.setenv('SUPERFORECASTING_AGENT_TUI_NO_CONFIRM', '1')
    screen = VTScreen(rows=45, cols=160)
    with client.websocket_connect('/api/pty?token=local-engineering&channel=tool-reset') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('complete before reset\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        before = receipt(home)
        if fail_reset:
            (home / 'fail-next-agent-build').write_text('fail once', encoding='utf-8')
        ws.send_text('/tools disable web\r')
        expected = b'session reset failed' if fail_reset else b'new tool configuration is active'
        until(ws, lambda out: expected in out, screen=screen)
        assert receipt(home)['id'] == before['id']
        assert receipt(home)['status'] == 'complete'
        config = yaml.safe_load((home / 'config.yaml').read_text(encoding='utf-8'))
        assert 'web' not in config['platform_toolsets']['cli']
        events = [json.loads(line) for line in (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8').splitlines()]
        first = next(event['agent'] for event in events if event['event'] == 'created')
        assert [event for event in events if event == {'event': 'closed', 'agent': first}] == [{'event': 'closed', 'agent': first}]
        if fail_reset:
            assert 'fixture rebuild unavailable' in ' '.join(screen.text().split())
            ws.send_text('/new\r')
            until(ws, lambda out: b'new forecast session started' in out, screen=screen)
        ws.send_text('complete after reset\r')
        until(ws, lambda out: receipt(home) and receipt(home)['id'] != before['id'] and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['partial_text'] == 'durable fixture prefix'
        ws.close(code=1000)


def test_real_desk_native_background_stop_preserves_session(local_desk, monkeypatch):
    from tests.tui_pty.vt import VTScreen

    client, home, _ = local_desk
    monkeypatch.setenv('FORECAST_TEST_FORBID_CLASSIC_WORKER', '1')
    screen = VTScreen(rows=45, cols=160)
    with client.websocket_connect('/api/pty?token=local-engineering&channel=background-commands') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('complete before background commands\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        before = receipt(home)
        lifetime = (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8')
        for command, expected in [('/stop', b'No running background processes.')]:
            ws.send_text(command + '\r')
            until(ws, lambda out: expected in out, screen=screen)
            assert receipt(home)['id'] == before['id']
            assert receipt(home)['status'] == 'complete'
        assert (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8') == lifetime
        ws.send_text('complete after background commands\r')
        until(ws, lambda out: receipt(home) and receipt(home)['id'] != before['id'] and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['session_id'] == before['session_id']
        ws.close(code=1000)


def test_real_desk_delegation_pause_isolated_after_new_session(local_desk, monkeypatch):
    from tests.tui_pty.vt import VTScreen

    client, home, _ = local_desk
    monkeypatch.setenv('FORECAST_TEST_FORBID_CLASSIC_WORKER', '1')
    monkeypatch.setenv('FORECAST_TEST_DELEGATION_AUDIT', '1')
    monkeypatch.setenv('SUPERFORECASTING_AGENT_TUI_NO_CONFIRM', '1')
    screen = VTScreen(rows=45, cols=160)
    with client.websocket_connect('/api/pty?token=local-engineering&channel=delegation-pause') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('/agents pause\r')
        until(ws, lambda out: b'delegation' in out and b'paused' in out, screen=screen)
        ws.send_text('/new\r')
        until(ws, lambda out: b'new forecast session started' in out, screen=screen)
        ws.send_text('/agents status\r')
        until(ws, lambda out: b'delegation' in out and b'active' in out, screen=screen)
        ws.send_text('/agents pause\r')
        until(ws, lambda out: b'delegation' in out and b'paused' in out, screen=screen)
        ws.send_text('/agents resume\r')
        until(ws, lambda out: b'delegation' in out and b'resumed' in out, screen=screen)
        events = [json.loads(line) for line in (home / 'delegation-pause.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(events) == 3
        first, second, resumed = events
        assert first['owner'] and second['owner'] and first['owner'] != second['owner']
        assert first['paused_sessions'] == [first['owner']]
        assert second['paused_sessions'] == sorted([first['owner'], second['owner']])
        assert resumed['owner'] == second['owner']
        assert resumed['paused_sessions'] == [first['owner']]
        ws.send_text('complete after scoped pause\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['partial_text'] == 'durable fixture prefix'
        ws.close(code=1000)


def test_real_desk_native_skills_preserves_session(local_desk, monkeypatch):
    from tests.tui_pty.vt import VTScreen

    client, home, _ = local_desk
    monkeypatch.setenv('FORECAST_TEST_FORBID_CLASSIC_WORKER', '1')
    screen = VTScreen(rows=45, cols=160)
    with client.websocket_connect('/api/pty?token=local-engineering&channel=skills-commands') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('complete before skills command\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        before = receipt(home)
        lifetime = (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8')
        ws.send_text('/skills audit\r')
        until(ws, lambda out: b'No hub-installed skills to audit.' in out, screen=screen)
        assert receipt(home)['id'] == before['id']
        assert receipt(home)['status'] == 'complete'
        assert (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8') == lifetime
        ws.send_text('complete after skills command\r')
        until(ws, lambda out: receipt(home) and receipt(home)['id'] != before['id'] and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['session_id'] == before['session_id']
        ws.close(code=1000)


def test_real_desk_native_handoff_preserves_agent_and_receipt(local_desk, monkeypatch):
    from tests.tui_pty.vt import VTScreen

    client, home, _ = local_desk
    monkeypatch.setenv('FORECAST_TEST_FORBID_CLASSIC_WORKER', '1')
    monkeypatch.setenv('FORECAST_TEST_HANDOFF', '1')
    monkeypatch.setenv('SUPERFORECASTING_AGENT_TUI_NO_CONFIRM', '1')
    screen = VTScreen(rows=45, cols=160)
    with client.websocket_connect('/api/pty?token=local-engineering&channel=handoff-command') as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('complete before handoff\r')
        until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        before = receipt(home)
        lifetime = (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8')
        ws.send_text('/handoff telegram\r')
        until(ws, lambda out: b'Handoff complete to telegram' in out or b'error:' in out, screen=screen)
        assert 'Handoff complete to telegram' in screen.text()
        assert (home / 'agent-lifetime.jsonl').read_text(encoding='utf-8') == lifetime
        assert receipt(home)['id'] == before['id']
        with closing(sqlite3.connect(home / 'state.db')) as db:
            rows = db.execute("SELECT id, handoff_state, handoff_attempt_id FROM sessions WHERE handoff_state IS NOT NULL").fetchall()
        assert len(rows) == 1 and rows[0][1] == 'completed' and rows[0][2]
        ws.send_text('/new\r')
        until(ws, lambda out: b'new forecast session started' in out, screen=screen)
        ws.send_text('complete after native handoff\r')
        until(ws, lambda out: receipt(home) and receipt(home)['id'] != before['id'] and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['session_id'] != rows[0][0]
        ws.close(code=1000)


def test_real_desk_handoff_cancel_and_dashboard_reconnect(local_desk, monkeypatch):
    from tests.tui_pty.vt import VTScreen

    client, home, bridges = local_desk
    monkeypatch.setenv('FORECAST_TEST_FORBID_CLASSIC_WORKER', '1')
    monkeypatch.setenv('FORECAST_TEST_HANDOFF', 'running')
    monkeypatch.setenv('SUPERFORECASTING_AGENT_TUI_NO_CONFIRM', '1')
    screen = VTScreen(rows=45, cols=160)
    url = '/api/pty?token=local-engineering&channel=handoff-cancel'

    def transfer_state():
        with closing(sqlite3.connect(home / 'state.db')) as db:
            return db.execute("SELECT id, handoff_state, handoff_attempt_id FROM sessions WHERE handoff_state IS NOT NULL").fetchone()

    with client.websocket_connect(url) as ws:
        ws.send_text('\x1b[RESIZE:160;45]')
        data = until(ws, lambda out: b'local-fixture' in out, screen=screen)
        ws.send_text('complete before cancelled handoff\r')
        data += until(ws, lambda out: receipt(home) and receipt(home)['status'] == 'complete', screen=screen)
        before = receipt(home)
        ws.send_text('/handoff telegram\r')
        data += until(ws, lambda out: b'Queued handoff' in out and transfer_state() and transfer_state()[1] == 'running', screen=screen)
        transferred = transfer_state()
        ws.send_text('\x03')
        data += until(ws, lambda out: b'Gateway transfer is still running' in out, screen=screen)
        assert transfer_state() == transferred
        assert receipt(home)['id'] == before['id']
        ws.close(code=1006)
    assert bridges[0].is_alive()
    with client.websocket_connect(url + f'&cursor={len(data)}') as ws:
        # ForecastDeskPage.onReady resends terminal dimensions on every connection.
        ws.send_text('\x1b[RESIZE:160;45]')
        ws.send_text('blocked after reconnect\r')
        until(ws, lambda out: b'handoff is in progress' in out, screen=screen)
        assert transfer_state() == transferred
        assert receipt(home)['id'] == before['id']
        ws.send_text('/new\r')
        until(ws, lambda out: b'new forecast session started' in out, screen=screen)
        ws.send_text('complete in independent session\r')
        until(ws, lambda out: receipt(home) and receipt(home)['id'] != before['id'] and receipt(home)['status'] == 'complete', screen=screen)
        assert receipt(home)['session_id'] != transferred[0]
        assert len(bridges) == 1
        ws.close(code=1000)
