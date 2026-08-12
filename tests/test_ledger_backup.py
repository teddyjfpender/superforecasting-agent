"""Durability spine on the ForecastLedger: the online backup, deterministic
retention, and the integrity check (the ledger IS the asset — months of judgment).

Every test runs against a SCRATCH ledger under ``tmp_path`` — never the operator's
live home.
"""

from __future__ import annotations

import sqlite3
import stat
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import OutcomeSpace


# ── helpers ──────────────────────────────────────────────────────────────────


def _ledger(tmp_path: Path) -> ForecastLedger:
    return ForecastLedger(tmp_path / "ledger.db")


def _seed_questions(ledger: ForecastLedger, n: int, *, start: int = 0) -> None:
    with allow_ledger_writes(reason="forecast_cli"):
        for i in range(start, start + n):
            ledger.create_question(
                title=f"Will metric M exceed 100 by 2030 (case {i})?",
                description="scenario description",
                resolution_criteria=(
                    "Resolves YES if the official published metric M is at least 100 "
                    "on or before 2030-01-01, per the source agency report."
                ),
                resolution_source="https://example.gov/report",
                outcome_space=OutcomeSpace(type="binary", choices=["yes", "no"]),
                close_time="2030-01-01T00:00:00Z",
                resolution_time="2030-01-02T00:00:00Z",
            )


def _fold_wal_into_main(db_path: Path) -> None:
    """Checkpoint the WAL into the main file and drop the sidecars, so a subsequent
    corruption of the main file is actually read back (not masked by WAL frames)."""

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    for side in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + side)
        if sidecar.exists():
            sidecar.unlink()


# ── backup produces a readable db with matching rows ─────────────────────────


def test_backup_produces_readable_db_with_matching_rows(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_questions(ledger, 4)
    backup_dir = ledger.default_backup_dir()
    backup_dir.mkdir(mode=0o755)
    old_backup = backup_dir / "forecast-20260101-000000.db"
    old_backup.write_text("old")
    old_backup.chmod(0o644)

    result = ledger.backup()
    backup_path = Path(result["path"])
    assert backup_path.exists()
    assert result["bytes"] > 0
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(old_backup.stat().st_mode) == 0o600
    # created_at parses as an aware UTC timestamp.
    assert datetime.fromisoformat(result["created_at"]).tzinfo is not None

    # The backup is a standalone, openable SQLite db whose row count matches live.
    live = ledger.row_counts()["questions"]
    conn = sqlite3.connect(result["path"])
    try:
        backed_up = conn.execute("SELECT COUNT(*) FROM forecast_questions").fetchone()[0]
    finally:
        conn.close()
    assert backed_up == live == 4


def test_default_backup_dir_is_colocated_with_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.default_backup_dir() == tmp_path / "backups"
    ledger.backup()
    assert (tmp_path / "backups").is_dir()
    # And a custom dest_dir is honoured.
    other = tmp_path / "elsewhere"
    ledger.backup(other)
    assert list(other.glob("forecast-*.db"))


# ── online backup is safe under a concurrent writer ──────────────────────────


def test_online_backup_under_concurrent_writer(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_questions(ledger, 3)
    baseline = ledger.row_counts()["questions"]

    stop = threading.Event()
    errors: list[Exception] = []

    def writer() -> None:
        i = 1000
        with allow_ledger_writes(reason="forecast_cli"):
            while not stop.is_set() and i < 1000 + 60:
                try:
                    _seed_questions(ledger, 1, start=i)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    break
                i += 1

    thread = threading.Thread(target=writer)
    thread.start()
    try:
        # The online backup API copies at the page level and restarts if a writer
        # commits mid-copy — it must never raise or produce a torn image.
        result = ledger.backup()
    finally:
        stop.set()
        thread.join(timeout=10)

    # The captured image opens cleanly and is internally consistent...
    restored = ForecastLedger(result["path"])
    integ = restored.integrity_check()
    assert integ["ok"] is True
    # ...with a count somewhere between the baseline and baseline+writes (a valid
    # committed snapshot, never fewer than what existed when the copy began).
    assert integ["counts"]["questions"] >= baseline


# ── retention: deterministic keep-14 + one-per-week-for-8-weeks ──────────────


def test_retention_prunes_deterministically(tmp_path):
    ledger = _ledger(tmp_path)
    backup_dir = ledger.default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 60 daily snapshots (≈ 9 weeks) as empty placeholder files.
    base = datetime(2026, 5, 1, 8, 0, 0, tzinfo=timezone.utc)
    from datetime import timedelta

    for i in range(60):
        stamp = (base + timedelta(days=i)).strftime("%Y%m%d-%H%M%S")
        (backup_dir / f"forecast-{stamp}.db").write_text("x")

    result = ledger._prune_backups(backup_dir, keep_recent=14, weekly_weeks=8)
    remaining = sorted(p.name for p in backup_dir.glob("forecast-*.db"))

    # Newest 14 always kept; plus the newest in each of 8 recent ISO weeks. The two
    # sets overlap (the recent weeks are covered by the 14), so the total is bounded
    # well under 60 and stable.
    assert len(remaining) == result["kept"]
    assert result["pruned_count"] == 60 - len(remaining)
    assert 14 <= len(remaining) <= 22
    # The 14 most-recent files are always present.
    newest = sorted(
        (backup_dir / f"forecast-{(base + timedelta(days=i)).strftime('%Y%m%d-%H%M%S')}.db").name
        for i in range(46, 60)
    )
    for name in newest:
        assert name in remaining

    # Deterministic + idempotent: re-running prunes nothing further.
    again = ledger._prune_backups(backup_dir, keep_recent=14, weekly_weeks=8)
    assert again["pruned_count"] == 0


def test_backup_applies_retention_and_lists_newest_first(tmp_path):
    ledger = _ledger(tmp_path)
    backup_dir = ledger.default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    from datetime import timedelta

    # 20 pre-existing daily snapshots, then a real backup with keep_recent=5.
    base = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    for i in range(20):
        stamp = (base + timedelta(days=i)).strftime("%Y%m%d-%H%M%S")
        (backup_dir / f"forecast-{stamp}.db").write_text("x")

    result = ledger.backup(keep_recent=5, weekly_weeks=0)
    assert result["retention"]["pruned_count"] > 0

    rows = ledger.list_backups()
    # Exactly the 5 kept (the fresh real backup is the newest of them).
    assert len(rows) == 5
    created = [r["created_at"] for r in rows]
    assert created == sorted(created, reverse=True)  # newest first
    assert rows[0]["path"] == result["path"]


def test_latest_backup_reports_age(tmp_path):
    ledger = _ledger(tmp_path)
    assert ledger.latest_backup() is None  # nothing yet

    backup_dir = ledger.default_backup_dir()
    backup_dir.mkdir(parents=True, exist_ok=True)
    # A backup stamped 3 days ago.
    old = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    (backup_dir / f"forecast-{old.strftime('%Y%m%d-%H%M%S')}.db").write_text("x")
    now = datetime(2026, 6, 4, 0, 0, 0, tzinfo=timezone.utc)
    latest = ledger.latest_backup(now=now)
    assert latest is not None
    assert latest["count"] == 1
    assert latest["age_hours"] == pytest.approx(72.0, abs=0.1)


# ── integrity check: clean + corruption detection ────────────────────────────


def test_integrity_check_ok_on_healthy_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_questions(ledger, 2)
    report = ledger.integrity_check()
    assert report["ok"] is True
    assert report["integrity_check"] == ["ok"]
    assert report["quick_check"] == ["ok"]
    assert report["violations"] == []
    assert report["counts"]["questions"] == 2
    assert report["db_path"] == str(ledger.db_path)


def test_integrity_check_detects_corruption(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_questions(ledger, 3)

    # Fold the WAL into the main file so corrupting it is actually observed, then
    # overwrite the file with garbage — a severely corrupt image.
    _fold_wal_into_main(ledger.db_path)
    size = ledger.db_path.stat().st_size
    with open(ledger.db_path, "r+b") as handle:
        handle.seek(0)
        handle.write(b"\x00\xff\xde\xad" * (size // 4))

    report = ledger.integrity_check()
    assert report["ok"] is False
    assert report["violations"]  # at least one violation recorded
