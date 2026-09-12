"""Real SQLite admission excludes restores without relying on process IDs."""

import subprocess
import sys
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.storage import snapshots
from superforecasting_agent.storage.profile_lease import ProfileLease
from superforecasting_agent.storage.session import SessionDB


def test_multiple_users_exclude_restore_and_repeated_close_preserves_other_owner(tmp_path):
    first = ProfileLease(tmp_path)
    second = ProfileLease(tmp_path)
    try:
        first.close()
        first.close()
        with pytest.raises(OSError, match="in use"):
            ProfileLease(tmp_path, exclusive=True)
    finally:
        first.close()
        second.close()
    with ProfileLease(tmp_path, exclusive=True):
        with pytest.raises(OSError, match="in use"):
            ProfileLease(tmp_path)


def test_process_death_releases_admission(tmp_path):
    code = (
        "import sys; from pathlib import Path; "
        "from superforecasting_agent.storage.profile_lease import ProfileLease; "
        "lease=ProfileLease(Path(sys.argv[1])); print('ready', flush=True); "
        "sys.stdin.read()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(OSError, match="in use"):
            ProfileLease(tmp_path, exclusive=True)
        process.kill()
        process.communicate(timeout=10)
        with ProfileLease(tmp_path, exclusive=True):
            pass
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


@pytest.mark.parametrize("symlink", [False, True])
def test_pending_restore_blocks_users_but_admits_recovery(tmp_path, symlink):
    journal = tmp_path / ".snapshot-restore.json"
    if symlink:
        journal.symlink_to(tmp_path / "missing")
    else:
        journal.write_text("{}", encoding="utf-8")
    with pytest.raises(OSError, match="pending"):
        ProfileLease(tmp_path)
    with ProfileLease(tmp_path, exclusive=True):
        pass


def test_live_database_blocks_restore_before_staging_or_publication(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("before", encoding="utf-8")
    sid = snapshots.create_quick_snapshot(hermes_home=tmp_path)
    config.write_text("after", encoding="utf-8")
    db = SessionDB(tmp_path / "state.db")
    try:
        with pytest.raises(OSError, match="in use"):
            snapshots.restore_quick_snapshot(sid, tmp_path)
        assert config.read_text(encoding="utf-8") == "after"
        assert not (tmp_path / ".snapshot-restore.json").exists()
    finally:
        db.close()
    assert snapshots.restore_quick_snapshot(sid, tmp_path)
    assert config.read_text(encoding="utf-8") == "before"


def test_failed_host_shutdown_and_restart_retain_profile_admission(tmp_path):
    host = RuntimeHost(home=tmp_path)
    callbacks = dict(
        stop_services=Mock(side_effect=OSError("still running")),
        release_prompts=Mock(), interrupt_delegations=Mock(), close_session=Mock(),
    )
    assert not host.shutdown(0, **callbacks)
    with pytest.raises(OSError, match="in use"):
        ProfileLease(tmp_path, exclusive=True)
    callbacks["stop_services"].side_effect = None
    assert host.shutdown(0, **callbacks)
    with ProfileLease(tmp_path, exclusive=True):
        with pytest.raises(OSError, match="in use"):
            host.start(reset_services=Mock())
    with pytest.raises(OSError, match="reset failed"):
        host.start(reset_services=Mock(side_effect=OSError("reset failed")))
    with pytest.raises(OSError, match="in use"):
        ProfileLease(tmp_path, exclusive=True)
    assert host.shutdown(0, **callbacks)
    with ProfileLease(tmp_path, exclusive=True):
        pass


def test_restore_removes_crashed_database_wal_before_replacement(tmp_path):
    import sqlite3
    from contextlib import closing

    database = tmp_path / "state.db"
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("CREATE TABLE receipt (value TEXT)")
        conn.execute("INSERT INTO receipt VALUES ('snapshot')")
        conn.commit()
    sid = snapshots.create_quick_snapshot(hermes_home=tmp_path)
    code = (
        "import sqlite3, sys, os; "
        "db=sqlite3.connect(sys.argv[1]); "
        "db.execute('PRAGMA journal_mode=WAL'); "
        "db.execute('PRAGMA wal_autocheckpoint=0'); "
        "db.execute(\"UPDATE receipt SET value='crashed'\"); db.commit(); os._exit(0)"
    )
    subprocess.run([sys.executable, "-c", code, str(database)], check=True, timeout=10)
    assert (tmp_path / "state.db-wal").stat().st_size > 0
    assert snapshots.restore_quick_snapshot(sid, tmp_path)
    assert not (tmp_path / "state.db-wal").exists()
    with closing(sqlite3.connect(database)) as conn:
        assert conn.execute("SELECT value FROM receipt").fetchall() == [("snapshot",)]


@pytest.mark.parametrize("filename", ["config.yaml", ".env", "auth.json"])
def test_configuration_writers_cannot_enter_during_restore(tmp_path, filename):
    from superforecasting_agent.storage.files import yaml_update_lock

    with ProfileLease(tmp_path, exclusive=True):
        with pytest.raises(OSError, match="in use"):
            with yaml_update_lock(tmp_path / filename):
                pytest.fail("writer admitted during restore")


def test_auth_storage_cannot_bypass_restore_admission(tmp_path):
    from superforecasting_agent.storage.auth import save_auth_store

    with ProfileLease(tmp_path, exclusive=True):
        with pytest.raises(OSError, match="in use"):
            save_auth_store(tmp_path / "auth.json", {"providers": {}})
    assert not (tmp_path / "auth.json").exists()


def test_offline_cli_restores_without_constructing_a_runtime(tmp_path, monkeypatch, capsys):
    from superforecasting_agent import cli

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_run_inherited_runtime", Mock(side_effect=AssertionError("runtime constructed")))
    config = tmp_path / "config.yaml"
    config.write_text("model: original\n", encoding="utf-8")
    sid = snapshots.create_quick_snapshot(hermes_home=tmp_path)
    config.write_text("model: changed\n", encoding="utf-8")
    cli.main(["snapshot", "restore", sid])
    assert "Restored state" in capsys.readouterr().out
    assert config.read_text(encoding="utf-8") == "model: original\n"
    cli.main(["snapshot", "recover"])
    assert "No snapshot restoration is pending" in capsys.readouterr().out
    with ProfileLease(tmp_path):
        with pytest.raises(SystemExit) as failure:
            cli.main(["snapshot", "restore", sid])
        assert failure.value.code == 1
    assert "Profile is in use" in capsys.readouterr().err


def test_snapshot_capture_cannot_read_partially_restored_state(tmp_path):
    with ProfileLease(tmp_path, exclusive=True):
        with pytest.raises(OSError, match="in use"):
            snapshots.create_quick_snapshot(hermes_home=tmp_path)
    assert not (tmp_path / "state-snapshots").exists()
