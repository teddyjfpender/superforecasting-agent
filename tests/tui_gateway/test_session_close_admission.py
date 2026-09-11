"""Session close cannot dispose of resources held by an admitted operation."""
import threading
from types import SimpleNamespace

import pytest

from superforecasting_agent.hosting.sessions import SessionBusy, use_session

pytestmark = pytest.mark.usefixtures('isolated_runtime_host')


def register_session(server, monkeypatch, **fields):
    closed = []
    session = {
        'session_key': 'durable', 'history': [], 'history_lock': threading.Lock(),
        'agent': SimpleNamespace(close=lambda: closed.append('agent')),
        **fields,
    }
    server._host.sessions['runtime'] = session
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    monkeypatch.setattr(server, '_get_db', lambda: SimpleNamespace(end_session=lambda *args: None))
    return session, closed


def request(server, method):
    return server.handle_request({'id': 1, 'method': method, 'params': {'session_id': 'runtime'}})


def test_close_rejects_inflight_rpc_then_closes_once(monkeypatch):
    from tui_gateway import server
    session, closed = register_session(server, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def command(rid, params):
        entered.set()
        assert release.wait(3)
        assert closed == []
        return {'result': {}}
    monkeypatch.setitem(server._methods, 'test.hold_session', command)
    thread = threading.Thread(target=lambda: request(server, 'test.hold_session'))
    thread.start()
    assert entered.wait(1)
    try:
        assert request(server, 'session.close')['error']['code'] == 4009
        assert server._host.sessions['runtime'] is session
        assert not closed
    finally:
        release.set()
        thread.join(2)
    assert request(server, 'session.close')['result']['closed'] is True
    assert request(server, 'session.close')['result']['closed'] is False
    assert closed == ['agent']
    with pytest.raises(SessionBusy), use_session(session):
        pytest.fail('stale reference admitted after close')


@pytest.mark.parametrize('fields', [
    {'running': True},
    {'_background_jobs': 1},
    {'agent_build_started': True, 'agent_ready': threading.Event()},
])
def test_close_preserves_busy_session_for_retry(monkeypatch, fields):
    from tui_gateway import server
    session, closed = register_session(server, monkeypatch, **fields)
    assert request(server, 'session.close')['error']['code'] == 4009
    assert server._host.sessions['runtime'] is session
    assert not closed
    session['running'] = False
    session['_background_jobs'] = 0
    if session.get('agent_ready') is not None:
        session['agent_ready'].set()
    assert request(server, 'session.close')['result']['closed'] is True
    assert closed == ['agent']


def test_failed_durable_close_retains_session_and_resources(monkeypatch):
    from tui_gateway import server
    session, closed = register_session(server, monkeypatch)
    attempts = []
    def end(*args):
        attempts.append(args)
        if len(attempts) == 1:
            raise OSError('injected durable write failure')
    monkeypatch.setattr(server, '_get_db', lambda: SimpleNamespace(end_session=end))
    first = request(server, 'session.close')
    assert 'error' in first
    assert server._host.sessions['runtime'] is session
    assert not session.get('_finalized') and not session.get('_closing')
    assert closed == []
    assert request(server, 'session.close')['result']['closed'] is True
    assert len(attempts) == 2 and closed == ['agent']


def test_finalizer_retries_durable_failure_without_early_hooks():
    from superforecasting_agent.hosting.sessions import finalize_session
    events = []
    session = {'session_key': 'old-key', 'history': [{'role': 'user', 'content': 'note'}],
        'agent': SimpleNamespace(session_id='continuation', commit_memory_session=lambda history: events.append('memory'))}
    def fail(*args):
        raise OSError('durable failure')
    with pytest.raises(OSError):
        finalize_session(session, end_session=fail, notify=lambda *args: events.append('hook'), end_reason='close', mark_ended=True)
    assert not session.get('_finalized') and not session.get('_durable_ended')
    assert events == []
    def end(session_id, reason):
        assert session_id == 'continuation'
        events.append('ended')
    for _ in range(2):
        finalize_session(session, end_session=end, notify=lambda *args: events.append('hook'), end_reason='close', mark_ended=True)
    assert events == ['ended', 'memory', 'hook']


def test_partial_disposal_blocks_use_and_retries_only_failed_resource(monkeypatch):
    from tui_gateway import server
    calls = []
    def close_agent():
        calls.append('agent')
        if calls.count('agent') == 1:
            raise OSError('injected client close failure')
    session, _ = register_session(server, monkeypatch,
        agent=SimpleNamespace(close=close_agent),
        slash_worker=SimpleNamespace(close=lambda: calls.append('worker')))
    result = request(server, 'session.close')
    assert 'client close failure' in result['error']['message']
    assert server._host.sessions['runtime'] is session
    assert session['_cleanup_pending'] and session['_finalized']
    with pytest.raises(SessionBusy, match='cleanup is pending'), use_session(session):
        pytest.fail('partially disposed session accepted work')
    assert request(server, 'session.close')['result']['closed'] is True
    assert calls == ['agent', 'worker', 'agent']
