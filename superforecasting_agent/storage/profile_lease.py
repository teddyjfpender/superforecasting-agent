"""Cross-process profile admission using SQLite's portable file locks.

Runtime users hold read transactions; restore/recovery holds an exclusive one.
The lock database contains no application data and must never be replaced or
exported. Closing a connection or process exit releases its lease.
"""

from __future__ import annotations

from pathlib import Path
from sqlite3 import Connection, OperationalError, connect
from typing import Any

LEASE_FILE = ".profile-use.lock"


class ProfileLease:
    """Own one profile admission lease until explicitly closed."""

    def __init__(self, home: Path, *, exclusive: bool = False) -> None:
        self.home = home.resolve()
        self._connection: Connection | None = None
        self.home.mkdir(parents=True, exist_ok=True)
        path = self.home / LEASE_FILE
        if path.is_symlink():
            raise OSError("Profile admission lock must not be a symbolic link")
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

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> ProfileLease:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
