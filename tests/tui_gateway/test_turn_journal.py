"""Failure injection observes the committed receipt at every emitted frame."""
import threading
import pytest
from superforecasting_agent.storage.session import SessionDB
from tui_gateway import turn_journal


@pytest.mark.parametrize('failure', ['authentication expired (401)', 'rate limit (429)', 'stream connection reset'])
def test_provider_failure_is_durable_before_notification(tmp_path, monkeypatch, failure):
    from tui_gateway import server
    db=SessionDB(tmp_path/'state.db')
    sid='runtime-session'; key='durable-session'
    tid=turn_journal.start(db,key,'Forecast with the saved evidence')
    monkeypatch.setattr(server,'_get_db',lambda:db)
    monkeypatch.setattr(server._host, 'sessions',{sid:{'session_key':key,'turn_id':tid}})
    observed=[]
    def notify(frame):
        payload=frame['params']['payload']
        receipt=turn_journal.latest(db,key)
        assert receipt['status']==payload['durable_status']
        observed.append((frame['params']['type'],receipt))
    monkeypatch.setattr(server,'write_json',notify)
    # Fake provider emits a prefix then fails. The same gateway seam handles
    # raised auth/rate-limit/transport errors independently of vendor SDKs.
    def provider():
        yield 'Initial analysis'
        raise RuntimeError(failure)
    server._emit('message.start',sid)
    try:
        for chunk in provider():
            server._emit('message.delta',sid,{'text':chunk,'turn_id':tid})
    except RuntimeError as exc:
        server._emit('error',sid,{'message':str(exc),'turn_id':tid})
    assert [r['status'] for _,r in observed]==['running','running','error']
    db.close()
    reopened=SessionDB(tmp_path/'state.db')
    receipt=turn_journal.latest(reopened,key,recover=True)
    assert receipt['status']=='error' and receipt['partial_text']=='Initial analysis'
    assert receipt['error']==failure
    reopened.close()


def test_cancel_remains_pending_until_worker_exit_and_late_events_cannot_reopen(tmp_path):
    db=SessionDB(tmp_path/'state.db')
    tid=turn_journal.start(db,'s','request')
    turn_journal.transition(db,tid,'running',delta='partial')
    assert turn_journal.transition(db,tid,'cancelling')['status']=='cancelling'
    assert turn_journal.transition(db,tid,'running',delta=' late prefix')['status']=='cancelling'
    final=turn_journal.transition(db,tid,'interrupted')
    assert final['partial_text']=='partial late prefix'
    assert turn_journal.transition(db,tid,'complete',text='stale result')==final
    db.close()


def test_restart_retains_partial_and_repeated_reconnect_is_idempotent(tmp_path, monkeypatch):
    path=tmp_path/'state.db'; db=SessionDB(path)
    tid=turn_journal.start(db,'s','unfinished prompt')
    turn_journal.transition(db,tid,'running',delta='retained partial')
    db.close()
    db=SessionDB(path)
    assert turn_journal.latest(db,'s',recover=True)['owner_active'] is True
    monkeypatch.setattr(turn_journal, '_owner_alive', lambda row: False)
    first=turn_journal.latest(db,'s',recover=True)
    assert first['status']=='interrupted' and first['prompt']=='unfinished prompt'
    assert first['partial_text']=='retained partial'
    for _ in range(5):
        assert turn_journal.latest(db,'s',recover=True)==first
    new=turn_journal.start(db,'s','explicit retry')
    turn_journal.transition(db,tid,'complete',text='old callback')
    assert turn_journal.latest(db,'s')['id']==new
    db.close()


def test_persistence_failure_is_never_announced_as_durably_saved(tmp_path, monkeypatch):
    from tui_gateway import server
    db=SessionDB(tmp_path/'state.db')
    tid=turn_journal.start(db,'s','request')
    monkeypatch.setattr(server,'_get_db',lambda:db)
    monkeypatch.setattr(server._host, 'sessions',{'runtime':{'session_key':'s','turn_id':tid}})
    frames=[]; monkeypatch.setattr(server,'write_json',frames.append)
    def fail(*args,**kwargs):
        raise OSError('injected disk failure')
    # Inject at the actual store boundary, independent of module reloads.
    with monkeypatch.context() as fault:
        fault.setattr(db, '_execute_write', fail)
        server._emit('message.complete','runtime',{'text':'visible answer','status':'complete','usage':{}})
    assert frames[-1]['params']['payload']['durable_status']=='unavailable'
    assert frames[-1]['params']['payload']['warning']
    assert turn_journal.latest(db,'s')['status']=='starting'
    db.close()


def test_deleting_session_erases_saved_turn_prompt(tmp_path):
    db = SessionDB(tmp_path / 'state.db')
    db.create_session('saved-session', source='tui')
    turn_journal.start(db, 'saved-session', 'private request')
    assert db.delete_session('saved-session')
    assert turn_journal.latest(db, 'saved-session') is None
    db.close()


@pytest.mark.parametrize('failure', ['authentication expired (401)', 'rate limit (429)', 'stream reset'])
def test_worker_failure_preserves_partial_output(tmp_path, monkeypatch, failure):
    from tui_gateway import server
    from types import SimpleNamespace
    db = SessionDB(tmp_path / 'worker.db')
    sid = 'worker'
    def run_conversation(message, **kwargs):
        kwargs['stream_callback']('saved prefix')
        raise RuntimeError(failure)
    session = dict(session_key=sid, history_lock=threading.RLock(), history=[],
                   running=True, agent=SimpleNamespace(run_conversation=run_conversation))
    monkeypatch.setattr(server, '_get_db', lambda: db)
    monkeypatch.setattr(server._host, 'sessions', {sid: session})
    monkeypatch.setattr(server, '_CRASH_LOG', str(tmp_path / 'crash.log'))
    monkeypatch.setattr(server, '_set_session_context', lambda key: [])
    frames = []
    finished = threading.Event()
    def notify(frame):
        frames.append(frame)
        payload = frame['params'].get('payload', {})
        if frame['params']['type'] == 'error':
            receipt = turn_journal.latest(db, sid)
            assert receipt['status'] == payload['durable_status'] == 'error'
            finished.set()
    monkeypatch.setattr(server, 'write_json', notify)
    server._run_prompt_submit(1, sid, session, 'request')
    assert finished.wait(5)
    receipt = turn_journal.latest(db, sid)
    assert receipt['partial_text'] == 'saved prefix'
    assert receipt['error'] == failure
    # The worker owns shutdown; avoid closing its shared DB from this callback.


def test_compression_continuation_keeps_inflight_receipt(tmp_path, monkeypatch):
    from tui_gateway import server
    from types import SimpleNamespace
    db = SessionDB(tmp_path / 'compression.db')
    tid = turn_journal.start(db, 'parent', 'request')
    turn_journal.transition(db, tid, 'running', delta='prefix')
    session = dict(session_key='parent', turn_id=tid, agent=SimpleNamespace(session_id='child'))
    monkeypatch.setattr(server, '_get_db', lambda: db)
    server._sync_session_key_after_compress('runtime', session, restart_slash_worker=False)
    assert turn_journal.latest(db, 'parent') is None
    assert turn_journal.latest(db, 'child')['partial_text'] == 'prefix'
    db.close()
