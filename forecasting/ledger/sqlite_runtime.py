"""Preserve Python callback failures across SQLite's lossy authorizer boundary."""
import sqlite3


def _call(conn, method, *args, **kwargs):
    conn._authorization_error = None
    try:
        return method(*args, **kwargs)
    except sqlite3.DatabaseError as exc:
        original = conn._authorization_error
        if original is not None:
            raise original.with_traceback(original.__traceback__) from exc
        raise
    finally:
        conn._authorization_error = None


class LedgerCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        return _call(self.connection, super().execute, *args, **kwargs)

    def executemany(self, *args, **kwargs):
        return _call(self.connection, super().executemany, *args, **kwargs)

    def executescript(self, *args, **kwargs):
        return _call(self.connection, super().executescript, *args, **kwargs)


class LedgerConnection(sqlite3.Connection):
    _authorization_error = None

    def set_authorizer(self, callback):
        if callback is None:
            return super().set_authorizer(None)

        def authorize(*args):
            try:
                return callback(*args)
            except BaseException as exc:
                self._authorization_error = exc
                return sqlite3.SQLITE_DENY

        return super().set_authorizer(authorize)

    def cursor(self, factory=LedgerCursor):
        return super().cursor(factory)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        return self.cursor().executescript(*args, **kwargs)

    def commit(self):
        return _call(self, super().commit)

    def rollback(self):
        return _call(self, super().rollback)

    def __exit__(self, *args):
        return _call(self, super().__exit__, *args)
