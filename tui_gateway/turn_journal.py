"""Durable turn receipt; transport delivery is downstream of committed state."""
import os
import time
import uuid

TERMINAL = ('complete', 'error', 'interrupted')


def _schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS tui_turns (
        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
        prompt TEXT NOT NULL, partial_text TEXT NOT NULL DEFAULT '',
        error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        owner_pid INTEGER NOT NULL, owner_started REAL NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS tui_turns_session ON tui_turns(session_id, created_at)')
    # Session deletion and retention must erase the associated saved prompts.
    conn.execute('''CREATE TRIGGER IF NOT EXISTS delete_tui_turns
        AFTER DELETE ON sessions BEGIN
        DELETE FROM tui_turns WHERE session_id=OLD.id; END''')


def start(db, session_id, prompt):
    turn_id = uuid.uuid4().hex
    def write(conn):
        _schema(conn)
        conn.execute('INSERT INTO tui_turns(id,session_id,status,prompt,created_at,updated_at,owner_pid,owner_started) VALUES (?,?,?,?,?,?,?,?)',
                     (turn_id,session_id,'starting',str(prompt),time.time(),time.time(),os.getpid(),_process_started(os.getpid())))
    db._execute_write(write)
    return turn_id


def transition(db, turn_id, status, *, delta=None, text=None, error=None):
    allowed = {'starting', 'running', 'cancelling', *TERMINAL}
    if status not in allowed:
        raise ValueError('invalid durable turn state')
    def write(conn):
        row = conn.execute('SELECT * FROM tui_turns WHERE id=?',(turn_id,)).fetchone()
        if row is None:
            raise ValueError('unknown durable turn')
        if row['status'] in TERMINAL:
            return dict(row)  # late events cannot reopen or rewrite the turn
        # Cancellation remains pending until the worker actually exits.
        next_status = row['status'] if row['status']=='cancelling' and status=='running' else status
        partial = text if text is not None else row['partial_text'] + (delta or '')
        conn.execute('UPDATE tui_turns SET status=?,partial_text=?,error=?,updated_at=? WHERE id=?',
                     (next_status,partial,error,time.time(),turn_id))
        return dict(conn.execute('SELECT * FROM tui_turns WHERE id=?',(turn_id,)).fetchone())
    return db._execute_write(write)


def latest(db, session_id, *, recover=False):
    def write(conn):
        _schema(conn)
        row=conn.execute('SELECT * FROM tui_turns WHERE session_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(session_id,)).fetchone()
        if row is None:
            return None
        if recover and row['status'] not in TERMINAL:
            if _owner_alive(row):
                return {**dict(row), 'owner_active': True}
            conn.execute("UPDATE tui_turns SET status='interrupted',error='Gateway stopped before turn completion',updated_at=? WHERE id=?", (time.time(),row['id']))
            row=conn.execute('SELECT * FROM tui_turns WHERE id=?',(row['id'],)).fetchone()
        return dict(row)
    return db._execute_write(write)


def _process_started(pid):
    import psutil
    return psutil.Process(pid).create_time()


def _owner_alive(row):
    import psutil
    try:
        return _process_started(row['owner_pid']) == row['owner_started']
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True  # uncertain ownership cannot authorize stealing a live turn


def reanchor(db, turn_id, session_id):
    """Follow a compression continuation without losing the in-flight receipt."""
    def write(conn):
        conn.execute('UPDATE tui_turns SET session_id=?,updated_at=? WHERE id=? AND status NOT IN (?,?,?)',
                     (session_id, time.time(), turn_id, *TERMINAL))
    db._execute_write(write)
