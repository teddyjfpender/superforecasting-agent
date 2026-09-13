"""Restore journals survive process death and validate every copy before retry."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from superforecasting_agent.storage import snapshots


@pytest.fixture
def pending(tmp_path, monkeypatch):
    home = tmp_path / "profile"
    home.mkdir()
    for name in ("config.yaml", "auth.json"):
        (home / name).write_text("snapshot " + name, encoding="utf-8")
    sid = snapshots.create_quick_snapshot(hermes_home=home)
    for name in ("config.yaml", "auth.json"):
        (home / name).write_text("current " + name, encoding="utf-8")

    def fail(*args):
        raise OSError("injected failure")

    with monkeypatch.context() as patch:
        patch.setattr(snapshots, "atomic_replace", fail)
        with pytest.raises(OSError, match="incomplete"):
            snapshots.restore_quick_snapshot(sid, home)
    return home, sid


def test_pending_restore_cannot_be_overwritten(pending):
    home, sid = pending
    before = (home / ".snapshot-restore.json").read_bytes()
    with pytest.raises(OSError, match="pending"):
        snapshots.restore_quick_snapshot(sid, home)
    assert (home / ".snapshot-restore.json").read_bytes() == before


@pytest.mark.parametrize("damage", ["missing", "changed", "symlink"])
def test_late_damaged_copy_prevents_all_recovery_writes(pending, damage):
    home, _ = pending
    record = json.loads((home / ".snapshot-restore.json").read_text(encoding="utf-8"))
    copy = home / record["members"][-1]["staged"]
    if damage == "missing":
        copy.unlink()
    elif damage == "changed":
        copy.write_bytes(b"corrupt")
    else:
        copy.unlink()
        copy.symlink_to(home / "auth.json")
    with pytest.raises(ValueError):
        snapshots.recover_quick_snapshot_restore(home)
    for name in ("config.yaml", "auth.json"):
        assert (home / name).read_text(encoding="utf-8") == "current " + name
    assert (home / ".snapshot-restore.json").is_file()


@pytest.mark.parametrize("damage", ["version", "state", "path", "staged", "duplicate"])
def test_invalid_journal_prevents_all_recovery_writes(pending, damage):
    home, _ = pending
    journal = home / ".snapshot-restore.json"
    record = json.loads(journal.read_text(encoding="utf-8"))
    if damage == "version":
        record["version"] = True
    elif damage == "state":
        record["state"] = "unknown"
    elif damage in ("path", "staged"):
        record["members"][-1][damage] = "../outside"
    else:
        record["members"].append(record["members"][0])
    journal.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        snapshots.recover_quick_snapshot_restore(home)
    assert (home / "config.yaml").read_text(encoding="utf-8") == "current config.yaml"


@pytest.mark.parametrize(
    "phase", ["before_replace", "after_replace", "before_complete", "after_complete"]
)
def test_process_death_recovery_uses_frozen_copies(tmp_path, phase):
    home = tmp_path / "profile"
    home.mkdir()
    for name in ("config.yaml", "auth.json"):
        (home / name).write_text("snapshot " + name, encoding="utf-8")
    sid = snapshots.create_quick_snapshot(hermes_home=home)
    for name in ("config.yaml", "auth.json"):
        (home / name).write_text("current " + name, encoding="utf-8")
    program = r"""
import os, sys
from pathlib import Path
from superforecasting_agent.storage import snapshots as s
home, sid, phase = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
replace, write = s.atomic_replace, s.atomic_json_write
def crash_replace(src, dst):
    if phase == 'before_replace':
        os._exit(73)
    result = replace(src, dst)
    if phase == 'after_replace':
        os._exit(73)
    return result
def crash_write(path, record):
    if record.get('state') == 'complete' and phase == 'before_complete':
        os._exit(73)
    result = write(path, record)
    if record.get('state') == 'complete' and phase == 'after_complete':
        os._exit(73)
    return result
s.atomic_replace, s.atomic_json_write = crash_replace, crash_write
s.restore_quick_snapshot(sid, home)
"""
    root = Path(__file__).resolve().parents[2]
    env = dict(os.environ, PYTHONPATH=str(root))
    died = subprocess.run(
        [sys.executable, "-c", program, str(home), sid, phase],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert died.returncode == 73, died.stderr.decode()
    # Retry must not depend on a mutable or retained source snapshot.
    shutil.rmtree(home / "state-snapshots")
    recovered = subprocess.run(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import sys; "
            "from superforecasting_agent.storage.snapshots import recover_quick_snapshot_restore as recover; "
            "assert recover(Path(sys.argv[1])); assert not recover(Path(sys.argv[1]))",
            str(home),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=20,
    )
    assert recovered.returncode == 0, recovered.stderr.decode()
    for name in ("config.yaml", "auth.json"):
        assert (home / name).read_text(encoding="utf-8") == "snapshot " + name
    assert not (home / ".snapshot-restore.json").exists()
    assert not list(home.glob(".*.snap_restore-*"))


def test_completed_journal_can_finish_interrupted_cleanup(pending, monkeypatch):
    home, _ = pending
    unlink = Path.unlink
    removed = []

    def interrupt_cleanup(path, *args, **kwargs):
        if ".snap_restore-" in path.name and not path.name.endswith(".publish"):
            if removed:
                raise OSError("injected cleanup failure")
            removed.append(path)
        return unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", interrupt_cleanup)
        with pytest.raises(OSError, match="cleanup failure"):
            snapshots.recover_quick_snapshot_restore(home)
    record = json.loads((home / ".snapshot-restore.json").read_text(encoding="utf-8"))
    assert record["state"] == "complete"
    assert not removed[0].exists()
    # Completed recovery must clean up only, preserving subsequent profile writes.
    (home / "config.yaml").write_text("after completion", encoding="utf-8")
    assert snapshots.recover_quick_snapshot_restore(home)
    assert (home / "config.yaml").read_text(encoding="utf-8") == "after completion"
    assert not list(home.glob(".*.snap_restore-*"))


@pytest.mark.parametrize("operation", ["restore", "recover"])
def test_journal_symlink_rejected_before_external_lock_creation(tmp_path, operation):
    home = tmp_path / "profile"
    home.mkdir()
    external = tmp_path / "external"
    external.write_text("{}", encoding="utf-8")
    (home / ".snapshot-restore.json").symlink_to(external)
    with pytest.raises(ValueError, match="symbolic link"):
        if operation == "restore":
            snapshots.restore_quick_snapshot("snapshot", home)
        else:
            snapshots.recover_quick_snapshot_restore(home)
    assert not (tmp_path / "external.lock").exists()
    assert external.read_text(encoding="utf-8") == "{}"
