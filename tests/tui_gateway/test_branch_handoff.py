"""Branch copying and runtime replacement preserve the complete transcript."""
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from superforecasting_agent.application.sessions import branch_session
from superforecasting_agent.storage.session import SessionDB

pytestmark = pytest.mark.usefixtures('isolated_runtime_host')


@pytest.fixture
def db(tmp_path, monkeypatch):
    from tui_gateway import server
    store = SessionDB(db_path=tmp_path / 'sessions.db')
    store.create_session('parent', source='tui')
    monkeypatch.setattr(server, '_db', store)
    return store


def test_branch_copy_preserves_tool_and_reasoning_metadata(db):
    history = [
        {'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'call1', 'type': 'function', 'function': {'name': 'research', 'arguments': '{}'}}], 'reasoning': 'check the source', 'reasoning_details': [{'type': 'text', 'text': 'reason'}], 'codex_reasoning_items': [{'id': 'r1'}]},
        {'role': 'tool', 'name': 'research', 'tool_call_id': 'call1', 'content': 'evidence'},
    ]
    branch_session(db, session_id='child', parent_session_id='parent', history=history, source='tui', name='Alternative')
    rows = db.get_messages_as_conversation('child')
    assert rows[0]['tool_calls'] == history[0]['tool_calls']
    assert rows[0]['reasoning'] == 'check the source'
    assert rows[0]['reasoning_details'] == history[0]['reasoning_details']
    assert rows[0]['codex_reasoning_items'] == history[0]['codex_reasoning_items']
    assert rows[1]['tool_call_id'] == 'call1'
    assert db.get_messages('child')[1]['tool_name'] == 'research'


def test_failed_transcript_copy_rolls_back_branch_and_parent_end(db):
    with pytest.raises(sqlite3.IntegrityError):
        branch_session(db, session_id='failed', parent_session_id='parent', source='cli',
            history=[{'role': 'user', 'content': 'first'}, {'role': None, 'content': 'invalid'}], end_parent=True)
    assert db.get_session('failed') is None
    assert db.get_messages('failed') == []
    assert db.get_session('parent')['ended_at'] is None


@pytest.mark.parametrize('fail', [False, True])
def test_branch_handoff_admits_only_ready_replacement(db, monkeypatch, fail):
    from tui_gateway import server
    closed = []
    old = {'session_key': 'parent', 'history': [{'role': 'user', 'content': 'forecast note'}],
           'history_lock': threading.Lock(), 'agent': SimpleNamespace(close=lambda: closed.append('old'))}
    server._sessions['old'] = old
    monkeypatch.setattr(server, '_resolve_model', lambda: 'fixture')
    monkeypatch.setattr(server, '_notify_session_boundary', lambda *args: None)
    def make_agent(sid, key, **kwargs):
        assert not closed
        busy = server.handle_request({'id': 2, 'method': 'session.close', 'params': {'session_id': 'old'}})
        assert busy['error']['code'] == 4009
        busy = server.handle_request({'id': 3, 'method': 'prompt.submit', 'params': {'session_id': 'old', 'text': 'racing'}})
        assert busy['error']['code'] == 4009
        if fail:
            raise RuntimeError('injected agent construction failure')
        return SimpleNamespace(close=lambda: closed.append('new'))
    def init(sid, key, agent, history, cols, pending_handoff):
        assert pending_handoff
        server._sessions[sid] = {'session_key': key, 'agent': agent, 'history': history,
            'history_lock': threading.Lock(), 'running': True, '_replacing': True}
    monkeypatch.setattr(server, '_make_agent', make_agent)
    monkeypatch.setattr(server, '_init_session', init)
    response = server.handle_request({'id': 1, 'method': 'session.branch_replace', 'params': {'session_id': 'old', 'name': 'Alternative'}})
    if fail:
        assert 'injected' in response['error']['message']
        assert server._sessions['old'] is old
        assert not old['running'] and not old['_replacing']
        assert db.get_session_by_title('Alternative') is None
        assert db.get_session('parent')['ended_at'] is None
        assert not closed
    else:
        sid = response['result']['session_id']
        assert 'old' not in server._sessions
        assert closed == ['old']
        assert not server._sessions[sid]['running']
        assert not server._sessions[sid]['_replacing']
        assert db.get_messages(server._sessions[sid]['session_key'])[0]['content'] == 'forecast note'
