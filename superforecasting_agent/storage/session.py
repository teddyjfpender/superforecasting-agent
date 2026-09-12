#!/usr/bin/env python3
"""Thread-safe session store; domain operations live in storage modules."""

import logging
import random
import re
import sqlite3
import threading
import time
from pathlib import Path

from superforecasting_agent.storage import search as _search
from superforecasting_agent.storage import retention as _retention
from superforecasting_agent.storage import telegram_schema as _telegram_schema
from superforecasting_agent.storage import telegram as _telegram
from superforecasting_agent.storage import messages as _messages
from superforecasting_agent.storage import transcript as _transcript
from superforecasting_agent.storage import listing as _listing
from superforecasting_agent.storage import replay as _replay
from superforecasting_agent.storage import sessions as _sessions
from superforecasting_agent.storage import handoff as _handoff
from superforecasting_agent.storage import text as _text
from superforecasting_agent.storage import schema as _schema
from superforecasting_agent.storage.sqlite import (
    _WAL_INCOMPAT_MARKERS,
    _set_last_init_error,
    _wal_fallback_warned_paths,
    apply_wal_with_fallback,
    format_session_db_unavailable,
    get_last_init_error,
)
from superforecasting_agent.storage.schema import (
    SCHEMA_VERSION, SCHEMA_SQL, FTS_SQL, FTS_TRIGRAM_SQL,
)
from superforecasting_agent.constants import get_agent_home
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_DB_PATH = get_agent_home() / "state.db"
_INITIAL_DEFAULT_DB_PATH = DEFAULT_DB_PATH


def _default_db_path() -> Path:
    """Resolve the active profile path at call time.

    Preserve explicit DEFAULT_DB_PATH overrides while avoiding stale import-time
    paths when the active home changes.
    """
    patched = DEFAULT_DB_PATH
    if str(patched) != str(_INITIAL_DEFAULT_DB_PATH):
        # The constant has been deliberately overridden (e.g. by a test
        # monkeypatch). Honour it rather than re-resolving from env.
        return patched
    return get_agent_home() / "state.db"


class SessionDB:
    """
    SQLite-backed session storage with FTS5 search.

    Thread-safe for the common gateway pattern (multiple reader threads,
    single writer via WAL mode). Each method opens its own cursor.
    """

    # ── Write-contention tuning ──
    # With multiple agent processes (gateway + CLI sessions + worktree agents)
    # all sharing one state.db, WAL write-lock contention causes visible TUI
    # freezes.  SQLite's built-in busy handler uses a deterministic sleep
    # schedule that causes convoy effects under high concurrency.
    #
    # Instead, we keep the SQLite timeout short (1s) and handle retries at the
    # application level with random jitter, which naturally staggers competing
    # writers and avoids the convoy.
    _WRITE_MAX_RETRIES = 15
    _WRITE_RETRY_MIN_S = 0.020   # 20ms
    _WRITE_RETRY_MAX_S = 0.150   # 150ms
    # Attempt a TRUNCATE WAL checkpoint every N successful writes.
    _CHECKPOINT_EVERY_N_WRITES = 50

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._write_count = 0
        self._conn = None
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                # Short timeout — application-level retry with random jitter
                # handles contention instead of sitting in SQLite's internal
                # busy handler for up to 30s.
                timeout=1.0,
                # Autocommit mode: Python's default isolation_level=""
                # auto-starts transactions on DML, which conflicts with our
                # explicit BEGIN IMMEDIATE.  None = we manage transactions
                # ourselves.
                isolation_level=None,
            )
            self._conn.row_factory = sqlite3.Row
            apply_wal_with_fallback(self._conn, db_label="state.db")
            self._conn.execute("PRAGMA foreign_keys=ON")

            self._init_schema()
        except Exception as exc:
            # Capture the cause so /resume and friends can surface WHY the
            # session DB is unavailable instead of a bare "Session database
            # not available."  Callers that catch this exception keep their
            # existing ``self._session_db = None`` degradation path.
            #
            # Note: we deliberately do NOT clear _last_init_error on the
            # success path (no else branch).  In multi-threaded callers
            # (gateway, web_server per-request SessionDB()), a concurrent
            # successful open racing past this failure would erase the
            # cause that another thread's /resume is about to format.
            # Tests that need to reset the state can call
            # ``superforecasting_agent.storage.session._set_last_init_error(None)`` explicitly.
            _set_last_init_error(f"{type(exc).__name__}: {exc}")
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            raise

    # ── Core write helper ──

    def _execute_write(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        """Execute a write transaction with BEGIN IMMEDIATE and jitter retry.

        *fn* receives the connection and should perform INSERT/UPDATE/DELETE
        statements.  The caller must NOT call ``commit()`` — that's handled
        here after *fn* returns.

        BEGIN IMMEDIATE acquires the WAL write lock at transaction start
        (not at commit time), so lock contention surfaces immediately.
        On ``database is locked``, we release the Python lock, sleep a
        random 20-150ms, and retry — breaking the convoy pattern that
        SQLite's built-in deterministic backoff creates.

        Returns whatever *fn* returns.
        """
        last_err: Optional[Exception] = None
        for attempt in range(self._WRITE_MAX_RETRIES):
            try:
                with self._lock:
                    if self._conn is None:
                        raise sqlite3.ProgrammingError("Cannot operate on a closed database.")
                    self._conn.execute("BEGIN IMMEDIATE")
                    try:
                        result = fn(self._conn)
                        self._conn.commit()
                    except BaseException:
                        try:
                            self._conn.rollback()
                        except Exception:
                            pass
                        raise
                # Success — periodic best-effort checkpoint.
                self._write_count += 1
                if self._write_count % self._CHECKPOINT_EVERY_N_WRITES == 0:
                    self._try_wal_checkpoint()
                return result
            except sqlite3.OperationalError as exc:
                err_msg = str(exc).lower()
                if "locked" in err_msg or "busy" in err_msg:
                    last_err = exc
                    if attempt < self._WRITE_MAX_RETRIES - 1:
                        jitter = random.uniform(
                            self._WRITE_RETRY_MIN_S,
                            self._WRITE_RETRY_MAX_S,
                        )
                        time.sleep(jitter)
                        continue
                # Non-lock error or retries exhausted — propagate.
                raise
        # Retries exhausted (shouldn't normally reach here).
        raise last_err or sqlite3.OperationalError(
            "database is locked after max retries"
        )

    def _try_wal_checkpoint(self) -> None:
        """Best-effort TRUNCATE WAL checkpoint.  Never raises.

        Flushes committed WAL frames back into the main DB file and
        truncates the WAL file to zero bytes.  Keeps the WAL from
        growing unbounded when many processes hold persistent
        connections.

        PASSIVE checkpoint was previously used here, but it never
        truncates the WAL file — the file stays at its high-water
        mark until an explicit TRUNCATE is called (which only
        happened inside the infrequent vacuum()).

        TRUNCATE may block briefly if a reader is mid-WAL, but
        _try_wal_checkpoint is called off the hot path (every
        _CHECKPOINT_EVERY_N_WRITES writes) and already runs under
        ``self._lock``, so the additional hold time is negligible.
        """
        try:
            with self._lock:
                result = self._conn.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
                if result and result[1] > 0:
                    logger.debug(
                        "WAL checkpoint: %d/%d pages checkpointed",
                        result[2], result[1],
                    )
        except Exception:
            pass  # Best effort — never fatal.

    def close(self):
        """Close the database connection.

        Attempts a TRUNCATE WAL checkpoint first so that exiting processes
        help shrink the WAL file.
        """
        with self._lock:
            if self._conn:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except Exception:
                    pass
                self._conn.close()
                self._conn = None

    _parse_schema_columns = staticmethod(_schema._parse_schema_columns)
    _reconcile_columns = _schema._reconcile_columns
    _init_schema = _schema._init_schema
    # =========================================================================
    # Session lifecycle
    # =========================================================================
    _insert_session_row = _sessions._insert_session_row
    create_session = _sessions.create_session
    create_branch = _sessions.create_branch
    end_session = _sessions.end_session
    reopen_session = _sessions.reopen_session
    update_system_prompt = _sessions.update_system_prompt
    update_token_counts = _sessions.update_token_counts
    ensure_session = _sessions.ensure_session
    prune_empty_ghost_sessions = _retention.prune_empty_ghost_sessions
    finalize_orphaned_compression_sessions = _retention.finalize_orphaned_compression_sessions
    get_session = _sessions.get_session
    resolve_session_id = _sessions.resolve_session_id
    # Maximum length for session titles
    MAX_TITLE_LENGTH = 100

    @staticmethod
    def sanitize_title(title: Optional[str]) -> Optional[str]:
        """Validate and sanitize a session title.

        - Strips leading/trailing whitespace
        - Removes ASCII control characters (0x00-0x1F, 0x7F) and problematic
          Unicode control chars (zero-width, RTL/LTR overrides, etc.)
        - Collapses internal whitespace runs to single spaces
        - Normalizes empty/whitespace-only strings to None
        - Enforces MAX_TITLE_LENGTH

        Returns the cleaned title string or None.
        Raises ValueError if the title exceeds MAX_TITLE_LENGTH after cleaning.
        """
        if not title:
            return None

        # Remove ASCII control characters (0x00-0x1F, 0x7F) but keep
        # whitespace chars (\t=0x09, \n=0x0A, \r=0x0D) so they can be
        # normalized to spaces by the whitespace collapsing step below
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', title)

        # Remove problematic Unicode control characters:
        # - Zero-width chars (U+200B-U+200F, U+FEFF)
        # - Directional overrides (U+202A-U+202E, U+2066-U+2069)
        # - Object replacement (U+FFFC), interlinear annotation (U+FFF9-U+FFFB)
        cleaned = re.sub(
            r'[\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff\ufffc\ufff9-\ufffb]',
            '', cleaned,
        )

        # Collapse internal whitespace runs and strip
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        if not cleaned:
            return None

        if len(cleaned) > SessionDB.MAX_TITLE_LENGTH:
            raise ValueError(
                f"Title too long ({len(cleaned)} chars, max {SessionDB.MAX_TITLE_LENGTH})"
            )

        return cleaned

    set_session_title = _sessions.set_session_title
    get_session_title = _sessions.get_session_title
    get_session_by_title = _sessions.get_session_by_title
    resolve_session_by_title = _sessions.resolve_session_by_title
    get_next_title_in_lineage = _sessions.get_next_title_in_lineage
    get_compression_tip = _sessions.get_compression_tip
    list_sessions_rich = _listing.list_sessions_rich
    _get_session_rich_row = _listing._get_session_rich_row
    # =========================================================================
    # Message storage
    # =========================================================================
    # Sentinel prefix used to distinguish JSON-encoded structured content
    # (multimodal messages: lists of parts like text + image_url) from plain
    # string content. The NUL byte is not legal in normal text, so this
    # cannot collide with real user content.
    _CONTENT_JSON_PREFIX = "\x00json:"
    _encode_content = classmethod(_messages._encode_content)
    _decode_content = classmethod(_messages._decode_content)
    append_message = _messages.append_message
    replace_messages = _messages.replace_messages
    get_messages = _transcript.get_messages
    get_messages_around = _transcript.get_messages_around
    get_anchored_view = _transcript.get_anchored_view
    resolve_resume_session_id = _replay.resolve_resume_session_id
    get_messages_as_conversation = _replay.get_messages_as_conversation
    _session_lineage_root_to_tip = _replay._session_lineage_root_to_tip
    _is_duplicate_replayed_user_message = staticmethod(_replay._is_duplicate_replayed_user_message)
    # =========================================================================
    # Search
    # =========================================================================
    _sanitize_fts5_query = staticmethod(_text._sanitize_fts5_query)
    _is_cjk_codepoint = staticmethod(_text._is_cjk_codepoint)
    _contains_cjk = staticmethod(_text._contains_cjk)
    _count_cjk = classmethod(_text._count_cjk)
    search_messages = _search.search_messages
    search_sessions = _search.search_sessions
    # =========================================================================
    # Utility
    # =========================================================================
    session_count = _listing.session_count
    message_count = _listing.message_count
    # =========================================================================
    # Export and cleanup
    # =========================================================================
    export_session = _listing.export_session
    export_all = _listing.export_all
    clear_messages = _retention.clear_messages
    _remove_session_files = staticmethod(_retention._remove_session_files)
    delete_session = _retention.delete_session
    prune_sessions = _retention.prune_sessions
    # ── Meta key/value (for scheduler bookkeeping) ──
    get_meta = _retention.get_meta
    set_meta = _retention.set_meta
    mutate_meta = _retention.mutate_meta
    apply_telegram_topic_migration = _telegram_schema.apply_telegram_topic_migration
    enable_telegram_topic_mode = _telegram.enable_telegram_topic_mode
    disable_telegram_topic_mode = _telegram.disable_telegram_topic_mode
    is_telegram_topic_mode_enabled = _telegram.is_telegram_topic_mode_enabled
    get_telegram_topic_binding = _telegram.get_telegram_topic_binding
    list_telegram_topic_bindings_for_chat = _telegram.list_telegram_topic_bindings_for_chat
    get_telegram_topic_binding_by_session = _telegram.get_telegram_topic_binding_by_session
    bind_telegram_topic = _telegram.bind_telegram_topic
    is_telegram_session_linked_to_topic = _telegram.is_telegram_session_linked_to_topic
    list_unlinked_telegram_sessions_for_user = _telegram.list_unlinked_telegram_sessions_for_user
    # ── Space reclamation ──
    vacuum = _retention.vacuum
    maybe_auto_prune_and_vacuum = _retention.maybe_auto_prune_and_vacuum
    # ── Handoff (cross-platform session transfer) ──────────────────────────
    #
    # State machine:
    #   None       — no handoff in flight
    #   "pending"  — CLI requested handoff, gateway hasn't picked it up yet
    #   "running"  — gateway is processing (session switch + synthetic turn)
    #   "completed"— gateway successfully delivered the synthetic turn
    #   "failed"   — gateway hit an error; reason in handoff_error
    #
    # The CLI writes "pending" then poll-waits for terminal state. The gateway
    # watcher transitions pending→running→{completed,failed}.
    request_handoff = _handoff.request_handoff
    get_handoff_state = _handoff.get_handoff_state
    list_pending_handoffs = _handoff.list_pending_handoffs
    claim_handoff = _handoff.claim_handoff
    complete_handoff = _handoff.complete_handoff
    fail_handoff = _handoff.fail_handoff
