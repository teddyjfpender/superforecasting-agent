"""Snapshot boundaries reject unsafe paths before modifying live state."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from superforecasting_agent.storage import snapshots as backup


@pytest.fixture
def home(tmp_path):
    path = tmp_path / "profile"
    path.mkdir()
    (path / "config.yaml").write_text("original", encoding="utf-8")
    return path


def test_same_instant_concurrent_snapshots_are_distinct(home, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(backup, "datetime", SimpleNamespace(now=lambda zone: now))
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: backup.create_quick_snapshot(label="same", hermes_home=home), range(8)))
    assert len(set(ids)) == 8
    assert len(backup.list_quick_snapshots(hermes_home=home)) == 8
    for name in ids:
        assert (home / "state-snapshots" / name / "config.yaml").read_text(encoding="utf-8") == "original"


@pytest.mark.parametrize("name", ["../outside", "x/../../outside", "x\\outside", "", ".", "..", "x\x00"])
def test_invalid_names_never_create_or_restore(home, name):
    with pytest.raises(ValueError):
        backup.create_quick_snapshot(label=name, hermes_home=home)
    with pytest.raises(ValueError):
        backup.restore_quick_snapshot(name, hermes_home=home)
    assert not (home / "state-snapshots").exists()


@pytest.mark.parametrize("member", ["../outside", "/outside", "pairing/../../outside", "other.txt", "cron//jobs.json"])
def test_invalid_later_manifest_member_prevents_all_restore_writes(home, member):
    sid = backup.create_quick_snapshot(hermes_home=home)
    manifest = home / "state-snapshots" / sid / "manifest.json"
    manifest.write_text(json.dumps({"files": {"config.yaml": 8, member: 1}}), encoding="utf-8")
    (home / "config.yaml").write_text("current", encoding="utf-8")
    with pytest.raises(ValueError):
        backup.restore_quick_snapshot(sid, hermes_home=home)
    assert (home / "config.yaml").read_text(encoding="utf-8") == "current"


@pytest.mark.parametrize("side", ["source", "destination"])
def test_restore_rejects_symlink_members(home, tmp_path, side):
    sid = backup.create_quick_snapshot(hermes_home=home)
    external = tmp_path / "external"
    external.write_text("untouched", encoding="utf-8")
    target = home / "config.yaml" if side == "destination" else home / "state-snapshots" / sid / "config.yaml"
    target.unlink()
    target.symlink_to(external)
    with pytest.raises(ValueError, match="symbolic"):
        backup.restore_quick_snapshot(sid, hermes_home=home)
    assert external.read_text(encoding="utf-8") == "untouched"


def test_failed_replacement_preserves_live_file_and_retains_recovery(home, monkeypatch):
    sid = backup.create_quick_snapshot(hermes_home=home)
    (home / "config.yaml").write_text("current", encoding="utf-8")
    def fail(*args):
        raise OSError("injected replacement failure")
    monkeypatch.setattr(backup, "atomic_replace", fail)
    with pytest.raises(OSError, match="restoration incomplete"):
        backup.restore_quick_snapshot(sid, hermes_home=home)
    assert (home / "config.yaml").read_text(encoding="utf-8") == "current"
    assert list(home.glob(".*.snap_restore-*"))
    assert (home / ".snapshot-restore.json").is_file()
    assert not list(home.glob(".*.restore_publish-*"))


@pytest.mark.parametrize("keep", [-1, True, 1.5, "2"])
def test_invalid_retention_cannot_delete_snapshots(home, keep):
    sid = backup.create_quick_snapshot(hermes_home=home)
    with pytest.raises(ValueError):
        backup.prune_quick_snapshots(keep=keep, hermes_home=home)
    assert (home / "state-snapshots" / sid).is_dir()


def test_pruning_ignores_unpublished_snapshots(home):
    root = home / "state-snapshots"
    pending = root / "unfinished"
    pending.mkdir(parents=True)
    backup.create_quick_snapshot(hermes_home=home)
    assert backup.prune_quick_snapshots(keep=0, hermes_home=home) == 1
    assert pending.is_dir()


def test_database_copy_failure_preserves_destination_without_raw_fallback(tmp_path, monkeypatch):
    source, destination = tmp_path / "broken.db", tmp_path / "existing.db"
    source.write_bytes(b"not a SQLite database")
    destination.write_bytes(b"existing destination")
    def raw_copy(*args, **kwargs):
        pytest.fail("SQLite failure fell back to an unsafe raw copy")
    monkeypatch.setattr(backup.shutil, "copy2", raw_copy)
    assert backup._safe_copy_db(source, destination) is False
    assert destination.read_bytes() == b"existing destination"
    assert not list(tmp_path.glob(".*.backup-*"))


def test_database_uri_escapes_filename_characters(tmp_path):
    import sqlite3
    from contextlib import closing

    source, destination = tmp_path / "source?#%.db", tmp_path / "copy.db"
    with closing(sqlite3.connect(source)) as db:
        db.execute("CREATE TABLE records (value INTEGER)")
        db.execute("INSERT INTO records VALUES (42)")
        db.commit()
    assert backup._safe_copy_db(source, destination)
    with closing(sqlite3.connect(destination)) as db:
        assert db.execute("SELECT value FROM records").fetchall() == [(42,)]


def test_failed_later_copy_does_not_publish_partial_snapshot(home, monkeypatch):
    previous = backup.create_quick_snapshot(hermes_home=home)
    (home / "auth.json").write_text("{}", encoding="utf-8")
    original = backup.shutil.copy2
    def copy(source, target):
        if source.name == "auth.json":
            raise OSError("injected auth copy failure")
        return original(source, target)
    monkeypatch.setattr(backup.shutil, "copy2", copy)
    with pytest.raises(OSError, match="auth copy"):
        backup.create_quick_snapshot(hermes_home=home)
    assert [s["id"] for s in backup.list_quick_snapshots(hermes_home=home)] == [previous]
    assert not list((home / "state-snapshots").glob(".pending-*"))


def test_failed_database_aborts_snapshot_publication(home):
    (home / "state.db").write_bytes(b"not SQLite")
    with pytest.raises(OSError, match="Could not snapshot database"):
        backup.create_quick_snapshot(hermes_home=home)
    assert backup.list_quick_snapshots(hermes_home=home) == []
    assert list((home / "state-snapshots").iterdir()) == []


def test_manifest_is_not_visible_until_directory_publication(home, monkeypatch):
    original = backup.atomic_json_write
    def write(path, data):
        original(path, data)
        assert backup.list_quick_snapshots(hermes_home=home) == []
        assert backup.prune_quick_snapshots(keep=0, hermes_home=home) == 0
        assert path.is_file()
    monkeypatch.setattr(backup, "atomic_json_write", write)
    snapshot = backup.create_quick_snapshot(hermes_home=home)
    assert [s["id"] for s in backup.list_quick_snapshots(hermes_home=home)] == [snapshot]


def test_manifest_failure_does_not_publish_snapshot(home, monkeypatch):
    def fail(*args):
        raise OSError("injected manifest failure")
    monkeypatch.setattr(backup, "atomic_json_write", fail)
    with pytest.raises(OSError, match="manifest failure"):
        backup.create_quick_snapshot(hermes_home=home)
    assert backup.list_quick_snapshots(hermes_home=home) == []
    assert not list((home / "state-snapshots").glob(".pending-*"))


def test_late_copy_failure_cannot_partially_restore_profile(home, monkeypatch):
    (home / 'auth.json').write_text('snapshot auth', encoding='utf-8')
    sid = backup.create_quick_snapshot(hermes_home=home)
    (home / 'config.yaml').write_text('current config', encoding='utf-8')
    (home / 'auth.json').write_text('current auth', encoding='utf-8')
    copy = backup.shutil.copy2
    def fail_auth(source, destination):
        if source.name == 'auth.json':
            raise OSError('injected staging failure')
        return copy(source, destination)
    monkeypatch.setattr(backup.shutil, 'copy2', fail_auth)
    with pytest.raises(OSError, match='injected staging failure'):
        backup.restore_quick_snapshot(sid, hermes_home=home)
    assert (home / 'config.yaml').read_text(encoding='utf-8') == 'current config'
    assert (home / 'auth.json').read_text(encoding='utf-8') == 'current auth'
    assert not list(home.glob('.*.snap_restore-*'))


def test_partial_publication_is_never_reported_as_success(home, monkeypatch):
    (home / 'auth.json').write_text('snapshot auth', encoding='utf-8')
    sid = backup.create_quick_snapshot(hermes_home=home)
    (home / 'config.yaml').write_text('current config', encoding='utf-8')
    (home / 'auth.json').write_text('current auth', encoding='utf-8')
    replace = backup.atomic_replace
    def fail_auth(source, destination):
        if destination.name == 'auth.json':
            raise OSError('injected publication failure')
        return replace(source, destination)
    monkeypatch.setattr(backup, 'atomic_replace', fail_auth)
    with pytest.raises(OSError, match='incomplete.*auth.json'):
        backup.restore_quick_snapshot(sid, hermes_home=home)
    assert (home / 'config.yaml').read_text(encoding='utf-8') == 'original'
    assert (home / 'auth.json').read_text(encoding='utf-8') == 'current auth'
    assert list(home.glob('.*.snap_restore-*'))
    monkeypatch.setattr(backup, 'atomic_replace', replace)
    assert backup.recover_quick_snapshot_restore(home)
    assert (home / 'auth.json').read_text(encoding='utf-8') == 'snapshot auth'
    assert not list(home.glob('.*.snap_restore-*'))
    assert not (home / '.snapshot-restore.json').exists()
    assert backup.recover_quick_snapshot_restore(home) is False
