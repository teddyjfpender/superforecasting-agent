"""Import OpenClaw skills with explicit conflict and backup handling."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

from _forecast_migration_options import SKILL_CATEGORY_DIRNAME, SKILL_CATEGORY_DESCRIPTION


def resolve_skill_destination(self, destination: Path) -> Path:
    if self.skill_conflict_mode != "rename" or not destination.exists():
        return destination

    suffix = "-imported"
    candidate = destination.with_name(destination.name + suffix)
    counter = 2
    while candidate.exists():
        candidate = destination.with_name(f"{destination.name}{suffix}-{counter}")
        counter += 1
    return candidate


def migrate_shared_skills(self) -> None:
    # Check all OpenClaw skill sources: managed, personal, project-level
    skill_sources = [
        (self.source_root / "skills", "shared-skills", "managed skills"),
        (Path.home() / ".agents" / "skills", "personal-skills", "personal cross-project skills"),
        (self.source_root / "workspace" / ".agents" / "skills", "project-skills", "project-level shared skills"),
        (self.source_root / "workspace.default" / ".agents" / "skills", "project-skills", "project-level shared skills"),
    ]
    found_any = False
    for source_root, kind_label, desc in skill_sources:
        if source_root.exists():
            found_any = True
            self._import_skill_directory(source_root, kind_label, desc)
    if not found_any:
        destination_root = self.target_root / "skills" / SKILL_CATEGORY_DIRNAME
        self.record("shared-skills", None, destination_root, "skipped", "No shared OpenClaw skills directories found")


def _import_skill_directory(self, source_root: Path, kind_label: str, desc: str) -> None:
    """Import skills from a single source directory into openclaw-imports."""
    destination_root = self.target_root / "skills" / SKILL_CATEGORY_DIRNAME

    skill_dirs = [p for p in sorted(source_root.iterdir()) if p.is_dir() and (p / "SKILL.md").exists()]
    if not skill_dirs:
        self.record(kind_label, source_root, destination_root, "skipped", f"No skills with SKILL.md found in {desc}")
        return

    for skill_dir in skill_dirs:
        _copy_skill_directory(self, skill_dir, destination_root, kind_label, desc)

    desc_path = destination_root / "DESCRIPTION.md"
    if self.execute:
        desc_path.parent.mkdir(parents=True, exist_ok=True)
        if not desc_path.exists():
            desc_path.write_text(SKILL_CATEGORY_DESCRIPTION + "\n", encoding="utf-8")
    elif not desc_path.exists():
        self.record("shared-skill-category", None, desc_path, "migrated", "Would create category description")


def migrate_skills(self) -> None:
    source_root = self.source_candidate("workspace/skills")
    destination_root = self.target_root / "skills" / SKILL_CATEGORY_DIRNAME
    if not source_root or not source_root.exists():
        self.record("skills", None, destination_root, "skipped", "No OpenClaw skills directory found")
        return

    skill_dirs = [p for p in sorted(source_root.iterdir()) if p.is_dir() and (p / "SKILL.md").exists()]
    if not skill_dirs:
        self.record("skills", source_root, destination_root, "skipped", "No skills with SKILL.md found")
        return

    for skill_dir in skill_dirs:
        _copy_skill_directory(self, skill_dir, destination_root, "skill", "skill")

    desc_path = destination_root / "DESCRIPTION.md"
    if self.execute:
        desc_path.parent.mkdir(parents=True, exist_ok=True)
        if not desc_path.exists():
            desc_path.write_text(SKILL_CATEGORY_DESCRIPTION + "\n", encoding="utf-8")
    elif not desc_path.exists():
        self.record("skill-category", None, desc_path, "migrated", "Would create category description")


def _copy_skill_directory(self, skill_dir: Path, destination_root: Path, kind_label: str, desc: str) -> None:
    destination = destination_root / skill_dir.name
    final_destination = destination
    if destination.exists():
        if self.skill_conflict_mode == "skip":
            self.record(kind_label, skill_dir, destination, "conflict", "Destination skill already exists")
            return
        if self.skill_conflict_mode == "rename":
            final_destination = self.resolve_skill_destination(destination)
    if self.execute:
        backup_path = None
        if final_destination == destination and destination.exists():
            backup_path = self.maybe_backup(destination)
        final_destination.parent.mkdir(parents=True, exist_ok=True)
        if final_destination == destination and destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(skill_dir, final_destination)
        details: Dict[str, Any] = {"backup": str(backup_path) if backup_path else ""}
        if final_destination != destination:
            details["renamed_from"] = str(destination)
        self.record(kind_label, skill_dir, final_destination, "migrated", **details)
    else:
        if final_destination != destination:
            self.record(
                kind_label,
                skill_dir,
                final_destination,
                "migrated",
                f"Would copy {desc} directory under a renamed folder",
                renamed_from=str(destination),
            )
        else:
            self.record(kind_label, skill_dir, final_destination, "migrated", f"Would copy {desc} directory")
