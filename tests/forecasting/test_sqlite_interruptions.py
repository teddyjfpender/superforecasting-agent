"""Actual signal interruption of an authorizer, including transaction recovery."""
import signal
import sqlite3
import pytest
from forecasting.ledger.sqlite_runtime import LedgerConnection


@pytest.mark.skipif(not hasattr(signal, 'SIGALRM'), reason='POSIX signal injection')
@pytest.mark.parametrize('method', ['execute', 'executemany', 'executescript', 'cursor'])
def test_signal_preserves_deadline_and_rolls_back(method):
    conn = sqlite3.connect(':memory:', factory=LedgerConnection, cached_statements=0)
    conn.execute('CREATE TABLE work(value INTEGER)')
    class Deadline(BaseException):
        pass
    def deadline(*_):
        raise Deadline('test deadline')
    previous = signal.signal(signal.SIGALRM, deadline)
    def interrupted(*_):
        signal.raise_signal(signal.SIGALRM)
        return sqlite3.SQLITE_OK
    try:
        with pytest.raises(Deadline, match='test deadline'):
            with conn:
                conn.execute('INSERT INTO work VALUES (1)')
                conn.set_authorizer(interrupted)
                try:
                    if method == 'cursor':
                        conn.cursor().execute('SELECT value FROM work')
                    elif method == 'executemany':
                        conn.executemany('INSERT INTO work VALUES (?)', [(2,)])
                    elif method == 'executescript':
                        conn.executescript('SELECT value FROM work;')
                    else:
                        conn.execute('SELECT value FROM work')
                finally:
                    conn.set_authorizer(None)
        assert conn.execute('SELECT value FROM work').fetchall() == []
        conn.execute('INSERT INTO work VALUES (3)')
        assert conn.execute('SELECT value FROM work').fetchone() == (3,)
        assert conn._authorization_error is None
    finally:
        signal.signal(signal.SIGALRM, previous)
        conn.close()


def test_commit_callback_failure_preserves_original_and_rolls_back():
    conn=sqlite3.connect(':memory:',factory=LedgerConnection)
    conn.execute('CREATE TABLE work(value)')
    def fail_commit(action, arg1, *rest):
        if action == sqlite3.SQLITE_TRANSACTION and arg1 == 'COMMIT':
            raise TimeoutError('commit deadline')
        return sqlite3.SQLITE_OK
    conn.set_authorizer(fail_commit)
    with pytest.raises(TimeoutError,match='commit deadline'):
        with conn:
            conn.execute('INSERT INTO work VALUES (1)')
    conn.set_authorizer(None)
    assert conn.execute('SELECT * FROM work').fetchall()==[]
    conn.close()
