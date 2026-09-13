"""Cross-process profile admission using SQLite's portable file locks.

Runtime users hold read transactions; restore/recovery holds an exclusive one.
The lock database contains no application data and must never be replaced or
exported. Closing a connection or process exit releases its lease.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, OperationalError, connect
from typing import Any
from weakref import finalize

LEASE_FILE = ".profile-use.lock"


class ProfileLease:
    """Own one profile admission lease until explicitly closed."""

    def __init__(self, home: Path, *, exclusive: bool = False) -> None:
        self.home = home.resolve()
        self._connection: Connection | None = None
        self._root_lease: ProfileLease | None = None
        self._finalizer: finalize | None = None
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.home / LEASE_FILE
        if path.is_symlink():
            raise OSError("Profile admission lock must not be a symbolic link")
        # Full-home imports can also replace named profiles. Their users retain
        # the enclosing home before their own lease, in a fixed outer-first order.
        if self.home.parent.name == "profiles":
            self._root_lease = ProfileLease(self.home.parent.parent)
        try:
            self._open(path, exclusive=exclusive)
        except BaseException:
            if self._root_lease is not None:
                self._root_lease.close()
            raise

    def _open(self, path: Path, *, exclusive: bool) -> None:
        connection = connect(
            str(path), isolation_level=None, timeout=0, check_same_thread=False
        )
        try:
            # WAL permits simultaneous readers and writers; it cannot implement
            # an exclusive restoration barrier. Never silently accept that mode.
            if connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise OSError("Profile admission lock must use rollback-journal mode")
            connection.execute("BEGIN EXCLUSIVE" if exclusive else "BEGIN")
            if not exclusive:
                connection.execute("SELECT name FROM sqlite_master LIMIT 1").fetchall()
                journal = self.home / ".snapshot-restore.json"
                if journal.exists() or journal.is_symlink():
                    raise OSError(
                        "Snapshot restoration is pending; run snapshot recover before using this profile"
                    )
        except OperationalError as exc:
            connection.close()
            raise OSError(
                "Profile is in use; stop its running commands and hosts before restoring, or wait for restoration to finish"
            ) from exc
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        # Session fixtures and embedding callers may abandon their owner. Close
        # the dedicated connection explicitly at collection too; sqlite3 warns
        # on implicit disposal, and the enclosing home must outlive its child.
        self._finalizer = finalize(self, self._release, connection, self._root_lease)

    @staticmethod
    def _release(connection: Connection, root: ProfileLease | None) -> None:
        connection.close()
        if root is not None:
            root.close()

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None
        if self._root_lease is not None:
            self._root_lease.close()
            self._root_lease = None
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None

    def __enter__(self) -> ProfileLease:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
