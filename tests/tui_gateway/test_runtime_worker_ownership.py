"""Shutdown drains owned work before touching agents or durable storage."""
import threading
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.usefixtures("isolated_runtime_host")

from superforecasting_agent.hosting.workers import HostStopping, RuntimeWorkers


def test_stop_cancels_queued_work_and_allows_drain_retry():
    workers = RuntimeWorkers(max_workers=1)
    entered, release = threading.Event(), threading.Event()
    def running():
        entered.set()
        assert release.wait(3)
    first = workers.submit(running)
    assert entered.wait(1)
    queued = workers.submit(lambda: pytest.fail('queued task ran after stop'))
    try:
        workers.stop()
        assert queued.cancelled()
        assert not workers.drain(0)
        with pytest.raises(HostStopping):
            workers.submit(lambda: None)
        with pytest.raises(HostStopping):
            workers.start(lambda: None, name='rejected')
        with pytest.raises(HostStopping), workers.operation():
            pytest.fail('inline request admitted after stop')
    finally:
        release.set()
        first.result(timeout=3)
    assert workers.drain(1)
    workers.stop()
    assert workers.drain(0)


def test_dedicated_thread_exception_releases_ownership(monkeypatch):
    errors = []
    monkeypatch.setattr(threading, 'excepthook', errors.append)
    workers = RuntimeWorkers()
    def fail():
        raise ValueError('injected')
    thread = workers.start(fail, name='failed-worker')
    thread.join(1)
    workers.stop()
    assert workers.drain(0)
    assert errors[0].exc_type is ValueError


def test_host_timeout_preserves_resources_until_worker_finishes(monkeypatch):
    from tui_gateway import server
    workers = RuntimeWorkers()
    release, entered = threading.Event(), threading.Event()
    calls = []
    session = {'session_key': 'durable', 'agent': SimpleNamespace(
        interrupt=lambda: calls.append('interrupt'),
        close=lambda: calls.append('agent.close'))}
    monkeypatch.setattr(server, '_pool', workers)
    server._sessions['runtime'] = session
    monkeypatch.setattr(server._session_store, '_connection', SimpleNamespace(close=lambda: calls.append('db.close')))
    monkeypatch.setattr(server, '_clear_pending', lambda sid: None)
    monkeypatch.setattr(server, '_stop_cron_ticker', lambda: None)
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    def active():
        entered.set()
        assert release.wait(3)
        calls.append('worker.finished')
    thread = workers.start(active, name='active-session')
    assert entered.wait(1)
    try:
        assert not server.shutdown_runtime(0)
        assert 'agent.close' not in calls and 'db.close' not in calls
        assert server._sessions['runtime'] is session
        response = server.dispatch({'id': 1, 'method': 'session.list', 'params': {}})
        assert response['error']['code'] == 5030
        with pytest.raises(RuntimeError, match='incomplete'):
            server.start_runtime()
    finally:
        release.set()
        thread.join(2)
    assert server.shutdown_runtime(1)
    assert calls.index('worker.finished') < calls.index('agent.close') < calls.index('db.close')
    assert server._sessions == {}
    assert server._session_store._connection is None
    assert server.shutdown_runtime(0)
    assert calls.count('agent.close') == calls.count('db.close') == 1
    server.start_runtime()
    assert not server._pool.stopping


def test_shutdown_preserves_last_worker_write_and_resumable_session(tmp_path, monkeypatch):
    from superforecasting_agent.storage.session import SessionDB
    from tui_gateway import server, turn_journal
    path = tmp_path / 'sessions.db'
    db = SessionDB(db_path=path)
    db.create_session(session_id='durable', source='tui', model='fixture')
    receipt = turn_journal.start(db, 'durable', 'preserve my work')
    release, entered = threading.Event(), threading.Event()
    monkeypatch.setattr(server._session_store, '_connection', db)
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    server._sessions['runtime'] = {
        'session_key': 'durable', 'turn_id': receipt, 'history': [],
        'agent': SimpleNamespace(session_id='durable', interrupt=release.set, close=lambda: None),
    }
    def finish_write():
        entered.set()
        assert release.wait(3)
        db.append_message('durable', role='assistant', content='saved during shutdown')
        turn_journal.transition(db, receipt, 'running', delta='partial evidence')
    thread = server._pool.start(finish_write, name='durable-writer')
    assert entered.wait(1)
    try:
        assert server.shutdown_runtime(2)
    finally:
        release.set()
        thread.join(2)
    reopened = SessionDB(db_path=path)
    try:
        assert reopened.get_session('durable')['ended_at'] is None
        assert reopened.get_messages('durable')[-1]['content'] == 'saved during shutdown'
        durable = turn_journal.latest(reopened, 'durable')
        assert durable['status'] == 'interrupted'
        assert durable['partial_text'] == 'partial evidence'
    finally:
        reopened.close()


def test_thread_construction_failure_does_not_leak_admission(monkeypatch):
    workers = RuntimeWorkers()
    def failed_thread(**kwargs):
        raise RuntimeError('thread construction failed')
    monkeypatch.setattr(threading, 'Thread', failed_thread)
    with pytest.raises(RuntimeError, match='construction failed'):
        workers.start(lambda: None, name='cannot-start')
    workers.stop()
    assert workers.drain(0)


def test_shutdown_disposal_failure_retains_registry_and_database_for_retry(monkeypatch):
    from tui_gateway import server
    calls = []
    def close_agent():
        calls.append('agent')
        if calls.count('agent') == 1:
            raise OSError('injected close failure')
    server._sessions['runtime'] = {
        'session_key': 'durable', 'agent': SimpleNamespace(close=close_agent),
        'slash_worker': SimpleNamespace(close=lambda: calls.append('worker')),
    }
    monkeypatch.setattr(server._session_store, '_connection', SimpleNamespace(close=lambda: calls.append('db')))
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    assert not server.shutdown_runtime(1)
    assert 'runtime' in server._sessions
    assert calls == ['agent', 'worker']
    with pytest.raises(RuntimeError, match='incomplete'):
        server.start_runtime()
    assert server.shutdown_runtime(1)
    assert calls == ['agent', 'worker', 'agent', 'db']
    assert not server._sessions
