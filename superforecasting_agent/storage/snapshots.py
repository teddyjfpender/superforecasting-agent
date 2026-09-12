"""Profile state snapshots independent of CLI administration and presentation."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.storage.files import (
    atomic_json_write,
    atomic_replace,
    yaml_update_lock,
)

logger = logging.getLogger(__name__)


def _safe_copy_db(src: Path, dst: Path) -> bool:
    """Use SQLite backup only; failed copies never replace the destination."""
    staged: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=f".{dst.name}.backup-", dir=dst.parent)
        os.close(fd)
        staged = Path(name)
        with closing(
            sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
        ) as conn:
            with closing(sqlite3.connect(str(staged))) as backup_conn:
                conn.backup(backup_conn)
        with staged.open("rb") as stream:
            os.fsync(stream.fileno())
        atomic_replace(staged, dst)
        return True
    except Exception as exc:
        logger.warning("SQLite safe copy failed for %s: %s", src, exc)
        return False
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


_QUICK_STATE_FILES = (
    "state.db",
    "config.yaml",
    ".env",
    "auth.json",
    "cron/jobs.json",
    "gateway_state.json",
    "channel_directory.json",
    "processes.json",
    # Pairing stores (generic + per-platform JSONs outside state.db)
    "pairing",  # legacy location (gateway/pairing.py)
    "platforms/pairing",  # new location (gateway/pairing.py)
    "feishu_comment_pairing.json",  # Feishu comment subscription pairings
)

_QUICK_SNAPSHOTS_DIR = "state-snapshots"
_QUICK_DEFAULT_KEEP = 20


def _quick_snapshot_root(hermes_home: Optional[Path] = None) -> Path:
    home = hermes_home or get_agent_home()
    return home / _QUICK_SNAPSHOTS_DIR


def _snapshot_name(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or any(char in value for char in ("/", "\\", "\x00"))
    ):
        raise ValueError("Snapshot name must be a single nonempty path component")
    return value


def _snapshot_member(base: Path, relative: str) -> Path:
    """Validate every manifest member before any restore writes occur."""
    if not isinstance(relative, str) or "\\" in relative or "\x00" in relative:
        raise ValueError("Invalid snapshot member path")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("Invalid snapshot member path")
    if relative not in _QUICK_STATE_FILES and not relative.startswith((
        "pairing/",
        "platforms/pairing/",
    )):
        raise ValueError("Snapshot member is not a supported state file")
    candidate = base
    for part in parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("Snapshot members must not traverse symbolic links")
    return candidate


def create_quick_snapshot(
    label: Optional[str] = None,
    hermes_home: Optional[Path] = None,
) -> Optional[str]:
    """Create a quick state snapshot of critical files.

    Capture existing state files privately and publish only after all copies
    succeed. Missing optional files are skipped; copy failures abort publication.
    Auto-prunes old snapshots beyond the keep limit.

    Returns:
        Snapshot ID (timestamp-based), or None if no files found.
    """
    home = hermes_home or get_agent_home()
    root = _quick_snapshot_root(home)
    if root.is_symlink():
        raise ValueError("Snapshot directory must not be a symbolic link")

    if label is not None:
        _snapshot_name(label)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    unique = f"{ts}-{uuid.uuid4().hex[:12]}"
    snap_id = f"{unique}-{label}" if label else unique
    root.mkdir(parents=True, exist_ok=True)
    staged = Path(tempfile.mkdtemp(prefix=".pending-", dir=root))
    manifest: Dict[str, int] = {}
    try:
        for rel in _QUICK_STATE_FILES:
            src = home / rel
            if not src.exists():
                continue
            candidates = src.rglob("*") if src.is_dir() else (src,)
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                relative = candidate.relative_to(home).as_posix()
                dst = staged / relative
                dst.parent.mkdir(parents=True, exist_ok=True)
                if candidate.suffix == ".db":
                    if not _safe_copy_db(candidate, dst):
                        raise OSError(f"Could not snapshot database: {relative}")
                else:
                    shutil.copy2(candidate, dst)
                    with dst.open("rb") as stream:
                        os.fsync(stream.fileno())
                manifest[relative] = dst.stat().st_size
        if not manifest:
            return None
        meta = {
            "id": snap_id,
            "timestamp": ts,
            "label": label,
            "file_count": len(manifest),
            "total_size": sum(manifest.values()),
            "files": manifest,
        }
        atomic_json_write(staged / "manifest.json", meta)
        os.replace(staged, root / snap_id)
    finally:
        if staged.exists():
            shutil.rmtree(staged)

    # Auto-prune
    _prune_quick_snapshots(root, keep=_QUICK_DEFAULT_KEEP)

    logger.info("State snapshot created: %s (%d files)", snap_id, len(manifest))
    return snap_id


def list_quick_snapshots(
    limit: int = 20,
    hermes_home: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """List existing quick state snapshots, most recent first."""
    root = _quick_snapshot_root(hermes_home)
    if not root.exists():
        return []

    results = []
    for d in sorted(root.iterdir(), reverse=True):
        if not d.is_dir() or d.is_symlink() or d.name.startswith("."):
            continue
        manifest_path = d / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    results.append(json.load(f))
            except (json.JSONDecodeError, OSError):
                results.append({"id": d.name, "file_count": 0, "total_size": 0})
        if len(results) >= limit:
            break

    return results


def _restore_quick_snapshot(
    snapshot_id: str,
    hermes_home: Optional[Path] = None,
) -> bool:
    """Restore state from a quick snapshot.

    Stage every copy before publishing any destination. Return True only when
    every member is published. Publication errors propagate with progress details;
    multi-file publication is not yet a crash-atomic transaction.
    """
    home = hermes_home or get_agent_home()
    root = _quick_snapshot_root(home)
    snap_dir = root / _snapshot_name(snapshot_id)
    if root.is_symlink() or snap_dir.is_symlink():
        raise ValueError("Snapshot directories must not be symbolic links")

    if not snap_dir.is_dir():
        return False

    manifest_path = snap_dir / "manifest.json"
    if not manifest_path.exists():
        return False

    if manifest_path.is_symlink():
        raise ValueError("Snapshot manifest must not be a symbolic link")
    with open(manifest_path, encoding="utf-8") as f:
        meta = json.load(f)
    if not isinstance(meta, dict) or not isinstance(meta.get("files"), dict):
        raise ValueError("Snapshot manifest must contain a file mapping")
    members = []
    for rel in meta["files"]:
        src = _snapshot_member(snap_dir, rel)
        dst = _snapshot_member(home, rel)
        if not src.is_file() or (dst.exists() and not dst.is_file()):
            raise ValueError("Snapshot member must be a regular file")
        members.append((rel, src, dst))

    staged: list[tuple[str, Path, Path]] = []
    journal = home / ".snapshot-restore.json"
    recorded = False
    try:
        for rel, src, dst in members:
            dst.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(
                prefix=f".{dst.name}.snap_restore-", dir=dst.parent
            )
            os.close(fd)
            tmp = Path(name)
            staged.append((rel, tmp, dst))
            shutil.copy2(src, tmp)
            with tmp.open("rb") as stream:
                os.fsync(stream.fileno())
        if not staged:
            return False
        record = {
            "version": 1,
            "snapshot_id": snapshot_id,
            "state": "publishing",
            "members": [
                {"path": rel, "staged": tmp.name, "sha256": _restore_digest(tmp)}
                for rel, tmp, _ in staged
            ],
        }
        # Retain copies if journal publication changed the target before
        # raising: a caller must never lose the bytes needed for retry.
        _sync_restore_directories(home, [tmp.parent for _, tmp, _ in staged])
        atomic_json_write(journal, record)
        _sync_restore_directories(home, [home])
        recorded = True
        return _recover_quick_snapshot_restore(home)
    finally:
        if not recorded and not journal.exists():
            for _, tmp, _ in staged:
                tmp.unlink(missing_ok=True)


def _sync_restore_directories(home: Path, directories: list[Path]) -> None:
    """Persist directory entries on POSIX; Windows supports process retry only."""
    if os.name == "nt":
        return
    pending = {home}
    for directory in directories:
        while directory != home:
            pending.add(directory)
            directory = directory.parent
    for directory in sorted(pending, key=lambda path: len(path.parts), reverse=True):
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _restore_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _restore_journal_members(home: Path, record: Any) -> list[tuple[str, Path, Path]]:
    if (
        not isinstance(record, dict)
        or type(record.get("version")) is not int
        or record["version"] != 1
        or record.get("state") not in ("publishing", "complete")
        or not isinstance(record.get("members"), list)
        or not record["members"]
    ):
        raise ValueError("Invalid snapshot restore journal")
    _snapshot_name(record.get("snapshot_id"))
    members: list[tuple[str, Path, Path]] = []
    seen: set[str] = set()
    for member in record["members"]:
        if not isinstance(member, dict):
            raise ValueError("Invalid snapshot restore member")
        rel = member.get("path")
        dst = _snapshot_member(home, rel)
        name = _snapshot_name(member.get("staged"))
        if not name.startswith(f".{dst.name}.snap_restore-") or rel in seen:
            raise ValueError("Invalid or duplicate snapshot restore member")
        seen.add(rel)
        tmp = dst.parent / name
        if (
            tmp.is_symlink()
            or tmp.with_name(tmp.name + ".publish").is_symlink()
            or (dst.exists() and not dst.is_file())
        ):
            raise ValueError("Snapshot restore members must be regular files")
        if record["state"] == "publishing":
            digest = member.get("sha256")
            if (
                not tmp.is_file()
                or not isinstance(digest, str)
                or _restore_digest(tmp) != digest
            ):
                raise ValueError(f"Snapshot restore copy is missing or changed: {rel}")
        members.append((rel, tmp, dst))
    return members


def _recover_quick_snapshot_restore(home: Path) -> bool:
    journal = home / ".snapshot-restore.json"
    if journal.is_symlink():
        raise ValueError("Snapshot restore journal must not be a symbolic link")
    if not journal.exists():
        return False
    record = json.loads(journal.read_text(encoding="utf-8"))
    members = _restore_journal_members(home, record)
    published: list[str] = []
    if record["state"] == "publishing":
        for rel, staged, dst in members:
            # Derive the disposable publication copy from the journal-owned
            # staged name so a retry can reclaim it after abrupt process death.
            tmp = staged.with_name(staged.name + ".publish")
            if tmp.is_symlink():
                raise ValueError(
                    "Snapshot publication copy must not be a symbolic link"
                )
            tmp.unlink(missing_ok=True)
            try:
                with tmp.open("xb"):
                    pass
                shutil.copy2(staged, tmp)
                with tmp.open("rb") as stream:
                    os.fsync(stream.fileno())
                atomic_replace(tmp, dst)
            except OSError as exc:
                raise OSError(
                    f"Snapshot restoration incomplete while publishing {rel}; "
                    f"confirmed published files: {', '.join(published) or '(none)'}. "
                    "The failed target may also have changed. Staged copies are "
                    f"retained for recovery. Original error: {exc}"
                ) from exc
            finally:
                tmp.unlink(missing_ok=True)
            published.append(rel)
        # Mark completion durably before deleting the copies. A crash during
        # cleanup must not make recovery try to republish deleted staged files.
        _sync_restore_directories(home, [dst.parent for _, _, dst in members])
        record["state"] = "complete"
        atomic_json_write(journal, record)
        _sync_restore_directories(home, [home])
    for _, staged, _ in members:
        staged.with_name(staged.name + ".publish").unlink(missing_ok=True)
        staged.unlink(missing_ok=True)
    journal.unlink()
    _sync_restore_directories(home, [staged.parent for _, staged, _ in members])
    logger.info("Completed snapshot restoration: %s", record["snapshot_id"])
    return True


def recover_quick_snapshot_restore(hermes_home: Optional[Path] = None) -> bool:
    """Finish an interrupted restore under exclusive restore admission.

    Callers must quiesce other profile writers first. Copies are verified before
    writes; retries republish identical bytes and cannot select a new snapshot.
    """
    home = hermes_home or get_agent_home()
    if (home / ".snapshot-restore.json").is_symlink():
        raise ValueError("Snapshot restore journal must not be a symbolic link")
    with yaml_update_lock(home / ".snapshot-restore.json"):
        return _recover_quick_snapshot_restore(home)


def restore_quick_snapshot(
    snapshot_id: str, hermes_home: Optional[Path] = None
) -> bool:
    """Stage and journal a restore; refuse to overwrite pending recovery state."""
    _snapshot_name(snapshot_id)
    home = hermes_home or get_agent_home()
    journal = home / ".snapshot-restore.json"
    if journal.is_symlink():
        raise ValueError("Snapshot restore journal must not be a symbolic link")
    with yaml_update_lock(journal):
        if journal.exists() or journal.is_symlink():
            raise OSError(
                "Snapshot restoration pending; recover it before starting another"
            )
        return _restore_quick_snapshot(snapshot_id, home)


def _prune_quick_snapshots(root: Path, keep: int = _QUICK_DEFAULT_KEEP) -> int:
    """Remove oldest quick snapshots beyond the keep limit. Returns count deleted."""
    if type(keep) is not int or keep < 0:
        raise ValueError("Snapshot keep count must be a nonnegative integer")
    if not root.exists():
        return 0

    dirs = sorted(
        (
            d
            for d in root.iterdir()
            if d.is_dir()
            and not d.is_symlink()
            and not d.name.startswith(".")
            and (d / "manifest.json").is_file()
        ),
        key=lambda d: d.name,
        reverse=True,
    )

    deleted = 0
    for d in dirs[keep:]:
        try:
            shutil.rmtree(d)
            deleted += 1
        except OSError as exc:
            logger.warning("Failed to prune snapshot %s: %s", d.name, exc)

    return deleted


def prune_quick_snapshots(
    keep: int = _QUICK_DEFAULT_KEEP,
    hermes_home: Optional[Path] = None,
) -> int:
    """Manually prune quick snapshots. Returns count deleted."""
    return _prune_quick_snapshots(_quick_snapshot_root(hermes_home), keep=keep)
