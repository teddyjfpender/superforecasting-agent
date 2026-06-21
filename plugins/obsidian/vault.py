"""Vault-level primitives for the obsidian plugin.

Everything here is filesystem-only and dependency-free: path resolution,
traversal-safe note paths, minimal frontmatter emission, and the managed-block
splice that lets re-syncs rewrite agent-generated content without clobbering
human edits around it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

MANAGED_BEGIN = "<!-- superforecasting:begin -->"
MANAGED_END = "<!-- superforecasting:end -->"


def managed_vault_path() -> Path:
    """The managed workspace vault: ``<hermes-home>/docs/vault``.

    Honors the home override (SUPERFORECASTING_AGENT_HOME / FORECAST_HOME /
    HERMES_HOME) via the canonical home helper, so the Python side stays in
    lockstep with the TUI's ``vaultDir()``. This is the single place the agent
    keeps its notes — we never auto-select the user's personal vault elsewhere
    on the machine.
    """
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "docs" / "vault"


def resolve_vault_path() -> Path | None:
    """Resolve the vault root.

    ``OBSIDIAN_VAULT_PATH`` wins when set (returns None if it points at a
    non-directory — a user error to surface). Otherwise the managed workspace
    vault ``<hermes-home>/docs/vault`` is used, created on first use so the
    agent always has a vault. The personal ``~/Documents/Obsidian Vault`` is
    never auto-selected.
    """
    configured = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        return path if path.is_dir() else None

    managed = managed_vault_path()
    try:
        managed.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return managed if managed.is_dir() else None


def safe_note_path(vault: Path, relative: str) -> Path:
    """Map a vault-relative note path to an absolute one, refusing escapes.

    Adds ``.md`` when no suffix is given. Raises ValueError on absolute paths
    or anything that resolves outside the vault.
    """
    rel = (relative or "").strip()
    if not rel:
        raise ValueError("note path is required")
    if Path(rel).is_absolute() or rel.startswith("~"):
        raise ValueError("note path must be relative to the vault root")
    candidate = (vault / rel).resolve()
    vault_resolved = vault.resolve()
    if not candidate.is_relative_to(vault_resolved):
        raise ValueError(f"note path escapes the vault: {relative!r}")
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".md")
    return candidate


def slugify(text: str, *, max_len: int = 80) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:max_len].rstrip("-") or "untitled"


def _frontmatter_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_frontmatter_value(v) for v in value) + "]"
    text = str(value)
    # json.dumps gives safe quoting/escaping that YAML also accepts.
    if re.fullmatch(r"[A-Za-z0-9 _./+-]*", text) and text == text.strip():
        return text
    return json.dumps(text, ensure_ascii=False)


def render_frontmatter(meta: dict[str, Any]) -> str:
    if not meta:
        return ""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        lines.append(f"{key}: {_frontmatter_value(value)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def splice_managed_block(existing: str | None, generated: str) -> str:
    """Replace the managed block inside *existing* with *generated*.

    The generated content is always wrapped in the managed markers. When the
    note doesn't exist or has no markers yet, the whole note becomes one
    managed block (plus any prior human content preserved below it).
    """
    block = f"{MANAGED_BEGIN}\n{generated.rstrip()}\n{MANAGED_END}"
    if not existing:
        return block + "\n"
    begin = existing.find(MANAGED_BEGIN)
    end = existing.find(MANAGED_END)
    if begin != -1 and end != -1 and end >= begin:
        return existing[:begin] + block + existing[end + len(MANAGED_END):]
    # No markers: keep human content, put the managed block on top.
    return block + "\n\n" + existing.lstrip("\n")


def write_note(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
