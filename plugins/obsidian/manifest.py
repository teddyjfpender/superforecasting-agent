"""The vault delta manifest — the watch-signature pattern applied to pages.

The ledger's ``watched_sources`` change detection stores a
``last_seen_signature`` per source and compares on every check. This module is
the same idea for vault pages: per tracked page we keep three content
signatures —

* ``content_sha``  — the whole file (any change at all);
* ``managed_sha``  — the agent-generated text inside the managed markers;
* ``operator_sha`` — everything OUTSIDE the managed block and frontmatter,
  i.e. the operator-authored layer that survives re-syncs.

``compute_deltas`` classifies every page against the manifest:
``operator_edited`` (the operator layer moved), ``operator_created`` (an
untracked note in a tracked section), ``missing`` (a tracked page vanished),
and ``unchanged``. ``ingested_operator_sha`` is the ingestion high-water mark
so the same operator note never becomes evidence twice.

The manifest lives at ``Forecasting/.sync-manifest.json`` — a dotfile, so
Obsidian never renders it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from plugins.obsidian.vault import MANAGED_BEGIN, MANAGED_END

MANIFEST_VERSION = 1
MANIFEST_RELATIVE = "Forecasting/.sync-manifest.json"

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n?", re.DOTALL)
_MANAGED_RE = re.compile(
    re.escape(MANAGED_BEGIN) + r".*?" + re.escape(MANAGED_END), re.DOTALL
)


def manifest_path(vault: Path) -> Path:
    return vault / MANIFEST_RELATIVE


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:24]


def split_note(text: str) -> dict[str, str]:
    """Split a note into its three layers: frontmatter, managed, operator."""
    text = text or ""
    front = ""
    match = _FRONTMATTER_RE.match(text)
    body = text
    if match:
        front = match.group(0)
        body = text[match.end():]
    managed_parts = _MANAGED_RE.findall(body)
    operator = _MANAGED_RE.sub("", body)
    return {
        "frontmatter": front,
        "managed": "\n".join(managed_parts),
        "operator": operator.strip(),
    }


def page_signature(text: str) -> dict[str, str]:
    layers = split_note(text)
    return {
        "content_sha": _sha(text or ""),
        "managed_sha": _sha(layers["managed"]),
        "operator_sha": _sha(layers["operator"]),
    }


def load_manifest(vault: Path) -> dict[str, Any]:
    path = manifest_path(vault)
    if not path.is_file():
        return {"version": MANIFEST_VERSION, "pages": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": MANIFEST_VERSION, "pages": {}}
    if not isinstance(data, dict) or not isinstance(data.get("pages"), dict):
        return {"version": MANIFEST_VERSION, "pages": {}}
    data.setdefault("version", MANIFEST_VERSION)
    return data


def save_manifest(vault: Path, manifest: dict[str, Any]) -> Path:
    path = manifest_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(manifest)
    payload["version"] = MANIFEST_VERSION
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    return path


def record_page(
    manifest: dict[str, Any],
    rel_path: str,
    text: str,
    *,
    mtime: float | None = None,
    synced_at: str | None = None,
    provenance: str | None = None,
    ledger_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Track (or re-track) a page. Preserves the ingestion high-water mark."""
    pages = manifest.setdefault("pages", {})
    entry = dict(pages.get(rel_path) or {})
    entry.update(page_signature(text))
    if mtime is not None:
        entry["mtime"] = float(mtime)
    if synced_at is not None:
        entry["synced_at"] = synced_at
    if provenance is not None:
        entry["provenance"] = provenance
    if ledger_refs is not None:
        entry["ledger_refs"] = list(ledger_refs)
    pages[rel_path] = entry
    return entry


def mark_ingested(manifest: dict[str, Any], rel_path: str, operator_sha: str) -> None:
    entry = manifest.setdefault("pages", {}).setdefault(rel_path, {})
    entry["ingested_operator_sha"] = operator_sha


def _tracked_section_dirs(section_dirs: list[str] | None) -> list[str]:
    if section_dirs:
        return list(section_dirs)
    # Late import to avoid a cycle (wiki imports manifest).
    from plugins.obsidian.wiki import SECTION_DIRS

    return list(SECTION_DIRS.values())


def compute_deltas(
    vault: Path,
    manifest: dict[str, Any] | None = None,
    *,
    section_dirs: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Classify every page against the manifest (the delta detection pass)."""
    manifest = manifest if manifest is not None else load_manifest(vault)
    pages: dict[str, Any] = manifest.get("pages") or {}
    deltas: dict[str, list[dict[str, Any]]] = {
        "operator_edited": [],
        "operator_created": [],
        "missing": [],
        "unchanged": [],
    }

    seen: set[str] = set()
    for rel_path, entry in sorted(pages.items()):
        seen.add(rel_path)
        path = vault / rel_path
        if not path.is_file():
            deltas["missing"].append({"path": rel_path})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        sig = page_signature(text)
        record = {
            "path": rel_path,
            "mtime": path.stat().st_mtime,
            **sig,
        }
        if sig["operator_sha"] != (entry or {}).get("operator_sha"):
            deltas["operator_edited"].append(record)
        else:
            deltas["unchanged"].append(record)

    for section in _tracked_section_dirs(section_dirs):
        root = vault / section
        if not root.is_dir():
            continue
        for note in sorted(root.rglob("*.md")):
            rel = str(note.relative_to(vault))
            if rel in seen:
                continue
            text = note.read_text(encoding="utf-8", errors="replace")
            deltas["operator_created"].append(
                {"path": rel, "mtime": note.stat().st_mtime, **page_signature(text)}
            )
    return deltas


__all__ = [
    "MANIFEST_RELATIVE",
    "manifest_path",
    "split_note",
    "page_signature",
    "load_manifest",
    "save_manifest",
    "record_page",
    "mark_ingested",
    "compute_deltas",
]
