"""Known unsafe mounts never enable WAL or downgrade another live WAL connection."""

import sqlite3

import pytest

from forecasting import ForecastLedger
from forecasting.models import ForecastingError
from superforecasting_agent.storage import sqlite as storage
from superforecasting_agent.storage.sqlite_filesystem import filesystem_type


def test_mount_selection_handles_nested_native_mounts_and_escaped_names():
    mounts = "1 0 0:1 / / rw - ext4 root rw\n2 1 0:2 / /shared\\040files rw - virtiofs host rw\n3 2 0:3 / /shared\\040files/native rw - ext4 disk rw\n"
    assert filesystem_type("/shared files/profile", mounts) == "virtiofs"
    assert filesystem_type("/shared files/native/profile", mounts) == "ext4"
    assert filesystem_type("/shared files-other/profile", mounts) == "ext4"
    assert filesystem_type("/tmp", "malformed") == ""


def test_new_ledger_on_cross_vm_mount_uses_rollback_journaling(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "cross_vm_filesystem", lambda _: True)
    ledger = ForecastLedger(tmp_path / "ledger.db")
    with ledger._connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_existing_live_wal_is_refused_without_mode_change_or_data_loss(
    tmp_path, monkeypatch
):
    path = tmp_path / "existing.db"
    writer = sqlite3.connect(path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE preserved(value TEXT)")
        writer.execute("INSERT INTO preserved VALUES ('evidence')")
        writer.commit()
        monkeypatch.setattr(storage, "cross_vm_filesystem", lambda _: True)
        reader = sqlite3.connect(path)
        try:
            with pytest.raises(storage.UnsafeWalFilesystemError, match="relocate"):
                storage.apply_wal_with_fallback(reader)
            assert reader.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
            assert (
                reader.execute("SELECT value FROM preserved").fetchone()[0]
                == "evidence"
            )
        finally:
            reader.close()
        with pytest.raises(ForecastingError, match="relocate") as failure:
            ForecastLedger(path)
        assert isinstance(failure.value.__cause__, storage.UnsafeWalFilesystemError)
        assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        writer.close()


def test_cross_vm_admission_never_attempts_wal(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "cross_vm_filesystem", lambda _: True)
    conn = sqlite3.connect(tmp_path / "trace.db")
    statements = []
    conn.set_trace_callback(statements.append)
    try:
        assert storage.apply_wal_with_fallback(conn) == "delete"
        assert not any(
            "journal_mode=wal" in sql.lower().replace(" ", "") for sql in statements
        )
    finally:
        conn.close()


def test_cross_vm_session_and_kanban_use_shared_admission(tmp_path, monkeypatch):
    from superforecasting_agent.storage.session import SessionDB
    from superforecasting_agent.runtime import kanban_db

    monkeypatch.setattr(storage, "cross_vm_filesystem", lambda _: True)
    db = SessionDB(db_path=tmp_path / "session.db")
    try:
        db.create_session("safe", source="cli")
        db.append_message("safe", "user", "retained")
        assert db.get_messages_as_conversation("safe")[0]["content"] == "retained"
        assert db._conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        db.close()
    conn = kanban_db.connect(db_path=tmp_path / "kanban.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()


def test_mount_detection_refreshes_after_remount(monkeypatch, tmp_path):
    from superforecasting_agent.storage import sqlite_filesystem as mounts

    monkeypatch.setattr(mounts.sys, "platform", "linux")
    values = iter([
        "1 0 0:1 / / rw - virtiofs host rw",
        "1 0 0:1 / / rw - ext4 disk rw",
    ])
    monkeypatch.setattr(mounts.Path, "read_text", lambda *args, **kwargs: next(values))
    assert mounts.cross_vm_filesystem(str(tmp_path / "db")) is True
    assert mounts.cross_vm_filesystem(str(tmp_path / "db")) is False


def test_in_memory_journal_mode_is_reported_truthfully():
    conn = sqlite3.connect(":memory:")
    try:
        assert storage.apply_wal_with_fallback(conn) == "memory"
    finally:
        conn.close()
