"""Shared SQLite filesystem fallback and session initialization diagnostics."""

import logging
import sqlite3
import threading
from typing import Optional

from superforecasting_agent.storage.sqlite_filesystem import cross_vm_filesystem


class UnsafeWalFilesystemError(sqlite3.OperationalError):
    """Existing WAL state must be relocated offline, never downgraded live."""


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# WAL-compatibility fallback
# ---------------------------------------------------------------------------
# SQLite's WAL mode requires shared-memory (mmap) coordination and fcntl
# byte-range locks that don't reliably work on network filesystems (NFS,
# SMB/CIFS, some FUSE mounts, WSL1).  Upstream documents this explicitly:
# https://www.sqlite.org/wal.html#sometimes_queries_return_sqlite_busy_in_wal_mode
#
# On those filesystems ``PRAGMA journal_mode=WAL`` raises
# ``sqlite3.OperationalError: locking protocol`` (SQLITE_PROTOCOL).  If we
# propagate that, every feature backed by state.db / kanban.db breaks
# silently — /resume, /title, /history, /branch, kanban dispatcher, etc.
#
# Instead, fall back to ``journal_mode=DELETE`` (the pre-WAL default) which
# works on NFS.  Concurrency drops — concurrent readers are blocked during
# a write — but the feature works.
_WAL_INCOMPAT_MARKERS = (
    "locking protocol",  # SQLITE_PROTOCOL on NFS/SMB
    "not authorized",  # Some FUSE mounts block WAL pragma outright
    "disk i/o error",  # Flaky network FS during WAL setup
)

# Last SessionDB() init error, per-process.  Surfaced in /resume and
# related slash-command error strings so users know WHY the DB is
# unavailable instead of getting a bare "Session database not available."
# Only SessionDB.__init__ writes to this; kanban_db.connect() failures
# do not update it (by design — kanban failures are reported via their
# own caller's error handling, not via /resume-style slash commands).
_last_init_error: Optional[str] = None
_last_init_error_lock = threading.Lock()

# Paths for which we've already logged a WAL-fallback WARNING.  Without
# this, kanban_db.connect() (called on every kanban operation — see
# superforecasting_agent/runtime/kanban_db.py for ~30 call sites) would re-log the same
# filesystem-incompat warning on every connection, filling errors.log.
_wal_fallback_warned_paths: set[str] = set()
_wal_fallback_warned_lock = threading.Lock()


def _set_last_init_error(msg: Optional[str]) -> None:
    """Record (or clear) the most recent state.db init failure.

    Thread-safe via _last_init_error_lock.  Callers pass a message to
    record a failure or None to clear.  SessionDB.__init__ only calls
    this to SET on failure — it deliberately does NOT clear on success,
    because in a multi-threaded caller (e.g. gateway / web_server per-
    request SessionDB() instantiation), a concurrent successful open
    racing past a different thread's failure would erase the cause
    string that thread's /resume handler is about to format.  Explicit
    clears (e.g. test fixtures) are still supported by passing None.
    """
    global _last_init_error
    with _last_init_error_lock:
        _last_init_error = msg


def get_last_init_error() -> Optional[str]:
    """Return the most recent state.db init failure, if any.

    Slash-command handlers (``/resume``, ``/title``, ``/history``, ``/branch``)
    call this to surface the underlying cause in their error messages when
    ``_session_db is None``.  Returns ``None`` if SessionDB initialized
    successfully (or hasn't been attempted).
    """
    return _last_init_error


def format_session_db_unavailable(
    prefix: str = "Session database not available",
) -> str:
    """Format a user-facing 'session DB unavailable' message with cause.

    When ``SessionDB()`` init fails, callers set ``_session_db = None`` and
    several slash commands (/resume, /title, /history, /branch) previously
    responded with a bare ``"Session database not available."`` — no
    indication of WHY.  This helper includes the captured cause (typically
    ``"locking protocol"`` from NFS/SMB) and points users at the known
    culprit so they can fix it themselves.

    Example output:
        Session database not available: locking protocol (state.db may be
        on NFS/SMB — see https://www.sqlite.org/wal.html).
    """
    cause = get_last_init_error()
    if not cause:
        return f"{prefix}."
    hint = ""
    if any(marker in cause.lower() for marker in _WAL_INCOMPAT_MARKERS):
        hint = (
            " (state.db may be on NFS/SMB/FUSE — see https://www.sqlite.org/wal.html)"
        )
    return f"{prefix}: {cause}{hint}."


def apply_wal_with_fallback(
    conn: sqlite3.Connection,
    *,
    db_label: str = "state.db",
) -> str:
    """Set ``journal_mode=WAL`` on ``conn``, falling back to DELETE on failure.

    Returns the actual journal mode, including ``memory`` for in-memory databases.
    Known cross-VM mounts use rollback journaling; existing WAL files on those
    mounts are refused without attempting a live journal-mode conversion.

    On WAL-incompatible filesystems (NFS, SMB, some FUSE), SQLite raises
    ``OperationalError("locking protocol")`` when setting WAL.  We fall
    back to DELETE mode — the pre-WAL default, which works on NFS — and
    log one WARNING explaining why.

    The WARNING is deduplicated per ``db_label``: repeated connections
    to the same underlying DB (e.g. kanban_db.connect() which is called
    on every kanban operation) log once per process, not once per call.
    Different db_labels log independently, so state.db and kanban.db
    each get one warning on the same NFS mount.

    Shared by :class:`SessionDB` and ``superforecasting_agent.runtime.kanban_db.connect`` so
    both databases get identical fallback behavior.
    """
    database = conn.execute("PRAGMA database_list").fetchone()
    if database and database[2] and cross_vm_filesystem(str(database[2])):
        current = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if current == "wal":
            raise UnsafeWalFilesystemError(
                "Existing WAL database is on a cross-VM filesystem (virtiofs/9p). "
                "Close all database users and relocate the profile onto a native volume; "
                "no journal-mode change was attempted."
            )
        _log_wal_fallback_once(
            db_label,
            RuntimeError("cross-VM filesystem (virtiofs/9p)"),
            mode=current if current in {"delete", "truncate", "persist"} else "delete",
        )
        if current in {"delete", "truncate", "persist"}:
            return current
        actual = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
        if not actual or str(actual[0]).lower() != "delete":
            raise UnsafeWalFilesystemError(
                "Could not establish safe rollback journaling on cross-VM filesystem"
            )
        return "delete"
    try:
        actual = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        if not actual:
            raise sqlite3.OperationalError("SQLite did not report its journal mode")
        return str(actual[0]).lower()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if not any(marker in msg for marker in _WAL_INCOMPAT_MARKERS):
            # Unrelated OperationalError — don't silently swallow.
            raise
        _log_wal_fallback_once(db_label, exc)
        conn.execute("PRAGMA journal_mode=DELETE")
        return "delete"


def _log_wal_fallback_once(
    db_label: str, exc: Exception, *, mode: str = "delete"
) -> None:
    """Log a single WARNING per (process, db_label) about WAL fallback.

    Without this dedup, NFS users running kanban (which opens a fresh
    connection on every operation — see superforecasting_agent/runtime/kanban_db.py) would
    fill errors.log with hundreds of identical warnings per hour.
    """
    with _wal_fallback_warned_lock:
        if db_label in _wal_fallback_warned_paths:
            return
        _wal_fallback_warned_paths.add(db_label)
    logger.warning(
        "%s: WAL journal_mode unsupported on this filesystem (%s) — "
        "using journal_mode=%s (slower rollback-journal "
        "mode; reduces concurrency but works on NFS/SMB/FUSE). See "
        "https://www.sqlite.org/wal.html for details. This warning "
        "fires once per process per database.",
        db_label,
        exc,
        mode.upper(),
    )
