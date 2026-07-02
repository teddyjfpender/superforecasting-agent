"""WAL journaling on ledger connections (P2 speed slice).

``_connect`` flips the DB into Write-Ahead Logging with ``synchronous=NORMAL`` so
a reader can run concurrently with an in-flight writer (DELETE-mode journaling
would make the reader block / SQLITE_BUSY). These tests pin:

  * the persisted journal mode is WAL and synchronous is NORMAL (1),
  * a reader on a fresh connection succeeds *while* a writer holds an open write
    transaction (this is the concurrency win; a low busy_timeout means a
    DELETE-mode lock would raise instead of silently waiting),
  * the WAL pragma degrades quietly (no exception) even on an in-memory DB where
    it is a no-op.
"""

from __future__ import annotations

import sqlite3

import pytest

from forecasting import ForecastLedger


def test_journal_mode_is_wal_and_synchronous_normal(tmp_path):
    ledger = ForecastLedger(str(tmp_path / "wal.db"))
    with ledger._connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert str(mode).lower() == "wal"
    assert sync == 1  # NORMAL


def test_foreign_keys_still_on(tmp_path):
    # WAL must not disturb the existing foreign_keys=ON invariant.
    ledger = ForecastLedger(str(tmp_path / "wal.db"))
    with ledger._connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reader_not_blocked_by_open_writer_txn(tmp_path):
    ledger = ForecastLedger(str(tmp_path / "wal.db"))
    writer = ledger._connect()
    reader = ledger._connect()
    # If a DELETE-mode write lock were held, the reader would wait then raise
    # SQLITE_BUSY. WAL lets it proceed against the last committed snapshot.
    reader.execute("PRAGMA busy_timeout = 300")
    try:
        # Scratch (non-forecast) table — DDL + non-gated INSERT are authorizer-clean.
        writer.execute("CREATE TABLE IF NOT EXISTS wal_probe (id INTEGER)")
        writer.commit()
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("INSERT INTO wal_probe VALUES (1)")
        # Writer holds an uncommitted write txn; reader must still read.
        before = reader.execute("SELECT count(*) FROM wal_probe").fetchone()[0]
        assert before == 0  # uncommitted row not visible, but the read did not block
        writer.commit()
        after = reader.execute("SELECT count(*) FROM wal_probe").fetchone()[0]
        assert after == 1
    finally:
        writer.close()
        reader.close()


def test_wal_pragma_is_noop_on_memory_db():
    # On :memory: WAL cannot apply; executing the pragma must not raise.
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() in {"memory", "wal"}  # memory DBs report "memory"
    finally:
        conn.close()
