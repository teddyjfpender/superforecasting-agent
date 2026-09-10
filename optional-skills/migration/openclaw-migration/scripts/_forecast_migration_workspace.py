"""Workspace documents, memory import, backups, and non-destructive file copying."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, List, Optional, Sequence

from _forecast_migration_files import (
    backup_existing, ensure_parent, read_text, relative_label, sha256_file,
)
from _forecast_migration_options import ENTRY_DELIMITER, WORKSPACE_INSTRUCTIONS_FILENAME
from _forecast_migration_text import (
    extract_markdown_entries, merge_entries, parse_existing_memory_entries, rebrand_text,
)


def source_candidate(self, *relative_paths: str) -> Optional[Path]:
    for rel in relative_paths:
        candidate = self.source_root / rel
        if candidate.exists():
            return candidate
        # OpenClaw renamed workspace/ to workspace-main/ (and workspace-{agentId}
        # for multi-agent).  Try the new path as a fallback.
        if rel.startswith("workspace/"):
            suffix = rel[len("workspace/"):]
            for variant in ("workspace-main", "workspace-assistant"):
                alt = self.source_root / variant / suffix
                if alt.exists():
                    return alt
        elif rel.startswith("workspace.default/"):
            suffix = rel[len("workspace.default/"):]
            alt = self.source_root / "workspace-main" / suffix
            if alt.exists():
                return alt

    # Final fallback: check the configured workspace directory from
    # agents.defaults.workspace in openclaw.json.  Users who started
    # before the OpenClaw rebrand (when the project was named clawd /
    # clawdbot) often have a custom workspace path outside ~/.openclaw/.
    if self._custom_workspace:
        for rel in relative_paths:
            # Strip the leading "workspace/" or "workspace.default/"
            # prefix to get the bare filename/subpath.
            for prefix in ("workspace/", "workspace.default/"):
                if rel.startswith(prefix):
                    suffix = rel[len(prefix):]
                    alt = self._custom_workspace / suffix
                    if alt.exists():
                        return alt
                    break

    return None


def maybe_backup(self, path: Path) -> Optional[Path]:
    if not self.execute or not self.backup_dir or not path.exists():
        return None
    return backup_existing(path, self.backup_dir)


def write_overflow_entries(self, kind: str, entries: Sequence[str]) -> Optional[Path]:
    if not entries or not self.overflow_dir:
        return None
    self.overflow_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{kind.replace('-', '_')}_overflow.txt"
    path = self.overflow_dir / filename
    path.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return path


def copy_file(self, source: Path, destination: Path, kind: str,
              transform: Optional[Any] = None) -> None:
    if not source or not source.exists():
        return

    if destination.exists():
        if not transform and sha256_file(source) == sha256_file(destination):
            self.record(kind, source, destination, "skipped", "Target already matches source")
            return
        if not self.overwrite:
            self.record(kind, source, destination, "conflict", "Target exists and overwrite is disabled")
            return

    if self.execute:
        backup_path = self.maybe_backup(destination)
        ensure_parent(destination)
        if transform:
            content = read_text(source)
            content = transform(content)
            destination.write_text(content, encoding="utf-8")
            shutil.copystat(source, destination)
        else:
            shutil.copy2(source, destination)
        self.record(kind, source, destination, "migrated", backup=str(backup_path) if backup_path else None)
    else:
        self.record(kind, source, destination, "migrated", "Would copy")


def migrate_soul(self) -> None:
    source = self.source_candidate("workspace/SOUL.md", "workspace.default/SOUL.md")
    if not source:
        self.record("soul", None, self.target_root / "SOUL.md", "skipped", "No OpenClaw SOUL.md found")
        return
    self.copy_file(source, self.target_root / "SOUL.md", kind="soul", transform=rebrand_text)


def migrate_workspace_agents(self) -> None:
    source = self.source_candidate(
        f"workspace/{WORKSPACE_INSTRUCTIONS_FILENAME}",
        f"workspace.default/{WORKSPACE_INSTRUCTIONS_FILENAME}",
    )
    if source is None:
        self.record("workspace-agents", "workspace/AGENTS.md", "", "skipped", "Source file not found")
        return
    if not self.workspace_target:
        self.record("workspace-agents", source, None, "skipped", "No workspace target was provided")
        return
    destination = self.workspace_target / WORKSPACE_INSTRUCTIONS_FILENAME
    self.copy_file(source, destination, kind="workspace-agents", transform=rebrand_text)


def migrate_memory(self, source: Optional[Path], destination: Path, limit: int, kind: str) -> None:
    if not source or not source.exists():
        self.record(kind, None, destination, "skipped", "Source file not found")
        return

    incoming = extract_markdown_entries(read_text(source))
    if not incoming:
        self.record(kind, source, destination, "skipped", "No importable entries found")
        return
    incoming = [rebrand_text(entry) for entry in incoming]

    existing = parse_existing_memory_entries(destination)
    merged, stats, overflowed = merge_entries(existing, incoming, limit)
    details = {
        "existing_entries": stats["existing"],
        "added_entries": stats["added"],
        "duplicate_entries": stats["duplicates"],
        "overflowed_entries": stats["overflowed"],
        "char_limit": limit,
        "final_char_count": len(ENTRY_DELIMITER.join(merged)) if merged else 0,
    }
    overflow_file = self.write_overflow_entries(kind, overflowed)
    if overflow_file is not None:
        details["overflow_file"] = str(overflow_file)

    if self.execute:
        if stats["added"] == 0 and not overflowed:
            self.record(kind, source, destination, "skipped", "No new entries to import", **details)
            return
        backup_path = self.maybe_backup(destination)
        ensure_parent(destination)
        destination.write_text(ENTRY_DELIMITER.join(merged) + ("\n" if merged else ""), encoding="utf-8")
        self.record(
            kind,
            source,
            destination,
            "migrated",
            backup=str(backup_path) if backup_path else "",
            overflow_preview=overflowed[:5],
            **details,
        )
    else:
        self.record(kind, source, destination, "migrated", "Would merge entries", overflow_preview=overflowed[:5], **details)


def migrate_daily_memory(self) -> None:
    source_dir = self.source_candidate("workspace/memory")
    destination = self.target_root / "memories" / "MEMORY.md"
    if not source_dir or not source_dir.is_dir():
        self.record("daily-memory", None, destination, "skipped", "No workspace/memory/ directory found")
        return

    md_files = sorted(p for p in source_dir.iterdir() if p.is_file() and p.suffix == ".md")
    if not md_files:
        self.record("daily-memory", source_dir, destination, "skipped", "No .md files found in workspace/memory/")
        return

    all_incoming: List[str] = []
    for md_file in md_files:
        entries = extract_markdown_entries(read_text(md_file))
        all_incoming.extend(entries)

    if not all_incoming:
        self.record("daily-memory", source_dir, destination, "skipped", "No importable entries found in daily memory files")
        return
    all_incoming = [rebrand_text(entry) for entry in all_incoming]

    existing = parse_existing_memory_entries(destination)
    merged, stats, overflowed = merge_entries(existing, all_incoming, self.memory_limit)
    details = {
        "source_files": len(md_files),
        "existing_entries": stats["existing"],
        "added_entries": stats["added"],
        "duplicate_entries": stats["duplicates"],
        "overflowed_entries": stats["overflowed"],
        "char_limit": self.memory_limit,
        "final_char_count": len(ENTRY_DELIMITER.join(merged)) if merged else 0,
    }
    overflow_file = self.write_overflow_entries("daily-memory", overflowed)
    if overflow_file is not None:
        details["overflow_file"] = str(overflow_file)

    if self.execute:
        if stats["added"] == 0 and not overflowed:
            self.record("daily-memory", source_dir, destination, "skipped", "No new entries to import", **details)
            return
        backup_path = self.maybe_backup(destination)
        ensure_parent(destination)
        destination.write_text(ENTRY_DELIMITER.join(merged) + ("\n" if merged else ""), encoding="utf-8")
        self.record(
            "daily-memory",
            source_dir,
            destination,
            "migrated",
            backup=str(backup_path) if backup_path else "",
            overflow_preview=overflowed[:5],
            **details,
        )
    else:
        self.record("daily-memory", source_dir, destination, "migrated", "Would merge daily memory entries", overflow_preview=overflowed[:5], **details)


def copy_tree_non_destructive(
    self,
    source_root: Optional[Path],
    destination_root: Path,
    kind: str,
    ignore_dir_names: Optional[set[str]] = None,
) -> None:
    if not source_root or not source_root.exists():
        self.record(kind, None, destination_root, "skipped", "Source directory not found")
        return

    ignore_dir_names = ignore_dir_names or set()
    files = [
        p
        for p in source_root.rglob("*")
        if p.is_file() and not any(part in ignore_dir_names for part in p.relative_to(source_root).parts[:-1])
    ]
    if not files:
        self.record(kind, source_root, destination_root, "skipped", "No files found")
        return

    copied = 0
    skipped = 0
    conflicts = 0

    for source in files:
        rel = source.relative_to(source_root)
        destination = destination_root / rel
        if destination.exists():
            if sha256_file(source) == sha256_file(destination):
                skipped += 1
                continue
            if not self.overwrite:
                conflicts += 1
                self.record(kind, source, destination, "conflict", "Destination file already exists")
                continue

        if self.execute:
            self.maybe_backup(destination)
            ensure_parent(destination)
            shutil.copy2(source, destination)
        copied += 1

    status = "migrated" if copied else "skipped"
    reason = ""
    if not copied and conflicts:
        status = "conflict"
        reason = "All candidate files conflicted with existing destination files"
    elif not copied:
        reason = "No new files to copy"

    self.record(kind, source_root, destination_root, status, reason, copied_files=copied, unchanged_files=skipped, conflicts=conflicts)


def archive_docs(self) -> None:
    candidates = [
        self.source_candidate("workspace/IDENTITY.md", "workspace.default/IDENTITY.md"),
        self.source_candidate("workspace/TOOLS.md", "workspace.default/TOOLS.md"),
        self.source_candidate("workspace/HEARTBEAT.md", "workspace.default/HEARTBEAT.md"),
        self.source_candidate("workspace/BOOTSTRAP.md", "workspace.default/BOOTSTRAP.md"),
    ]
    for candidate in candidates:
        if candidate:
            self.archive_path(candidate, reason="No direct Superforecasting Agent destination; archived for manual review")

    for rel in ("workspace/.learnings", "workspace/memory"):
        candidate = self.source_root / rel
        if candidate.exists():
            self.archive_path(candidate, reason="No direct Superforecasting Agent destination; archived for manual review")

    partially_extracted = [
        ("openclaw.json", "Selected Superforecasting Agent-compatible values were extracted; raw OpenClaw config was not copied."),
        ("credentials/telegram-default-allowFrom.json", "Selected Superforecasting Agent-compatible values were extracted; raw credentials file was not copied."),
    ]
    for rel, reason in partially_extracted:
        candidate = self.source_root / rel
        if candidate.exists():
            self.record("raw-config-skip", candidate, None, "skipped", reason)

    skipped_sensitive = [
        "memory/main.sqlite",
        "credentials",
        "devices",
        "identity",
        "workspace.zip",
    ]
    for rel in skipped_sensitive:
        candidate = self.source_root / rel
        if candidate.exists():
            self.record("sensitive-skip", candidate, None, "skipped", "Contains secrets, binary state, or product-specific runtime data")


def archive_path(self, source: Path, reason: str) -> None:
    destination = self.archive_dir / relative_label(source, self.source_root) if self.archive_dir else None
    if self.execute and destination is not None:
        ensure_parent(destination)
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
        else:
            shutil.copy2(source, destination)
        self.record("archive", source, destination, "archived", reason)
    else:
        self.record("archive", source, destination, "archived", reason)


def migrate_workspace_cwd(self, workspace: str) -> None:
    """Import the gateway workspace without replacing unrelated configuration."""
    from _forecast_migration_files import yaml, dump_yaml_file

    source = self.source_root / "openclaw.json"
    destination = self.target_root / "config.yaml"
    if yaml is None:
        self.record("messaging-settings", source, destination, "error", "PyYAML is not available")
        return
    try:
        config = yaml.safe_load(read_text(destination)) if destination.exists() else {}
    except (OSError, yaml.YAMLError) as exc:
        self.record("messaging-settings", source, destination, "error", f"Cannot read target configuration: {exc}")
        return
    if config is None:
        config = {}
    if not isinstance(config, dict) or not isinstance(config.get("terminal", {}), dict):
        self.record("messaging-settings", source, destination, "error", "Target configuration and terminal settings must be mappings")
        return
    terminal = config.setdefault("terminal", {})
    current = terminal.get("cwd")
    if current == workspace:
        self.record("messaging-settings", source, destination, "skipped", "Workspace already set to the same value")
        return
    if current and not self.overwrite:
        self.record("messaging-settings", source, destination, "conflict", "Workspace already set and overwrite is disabled")
        return
    backup_path = None
    if self.execute:
        backup_path = self.maybe_backup(destination)
        terminal["cwd"] = workspace
        dump_yaml_file(destination, config)
    self.record("messaging-settings", source, destination, "migrated",
                "Workspace imported" if self.execute else "Would set terminal.cwd",
                backup=str(backup_path) if backup_path else "", workspace=workspace)
