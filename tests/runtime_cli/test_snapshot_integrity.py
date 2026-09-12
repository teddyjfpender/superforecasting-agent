"""Snapshot boundaries reject unsafe paths before modifying live state."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from superforecasting_agent.runtime import backup


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


def test_failed_replacement_preserves_live_file_and_cleans_temporary(home, monkeypatch):
    sid = backup.create_quick_snapshot(hermes_home=home)
    (home / "config.yaml").write_text("current", encoding="utf-8")
    def fail(*args):
        raise OSError("injected replacement failure")
    monkeypatch.setattr(backup, "atomic_replace", fail)
    assert backup.restore_quick_snapshot(sid, hermes_home=home) is False
    assert (home / "config.yaml").read_text(encoding="utf-8") == "current"
    assert not list(home.glob(".*.snap_restore-*"))


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
