"""The pruning doctrine — deep pruning against context rot.

The edge over the append-only wiki pattern: the vault is kept dense by a
recurring PRUNE pass that detects seven rot classes and emits a PROPOSAL
report. Nothing mutates on detection — apply happens only on operator confirm
or a policy-matrix grant (see ``forecasting/jobs/types/wiki_prune.py``), and
apply means TOMBSTONES, never deletions: the full page is archived under
``Forecasting/Archive/`` and the original becomes a two-line tombstone
pointing at both the archive and its successor. Auditability is the point.

Rot classes:

* ``broken_links``            — a wikilink that resolves to no page;
* ``orphans``                 — a page with no in/out links (index, archive,
                                tombstones excluded);
* ``stale``                   — frontmatter ``as_of`` older than the window on
                                a non-resolved page;
* ``near_duplicates``         — identical name/digit-stripped skeletons (the
                                ``detect_templated_batches`` fingerprint)
                                within a section;
* ``resolution_condensation`` — the page's ledger question is resolved: fold
                                into the postmortem/lesson and archive;
* ``contradictions``          — page frontmatter vs LEDGER TRUTH (status
                                drift; provenance pointing at a missing row);
* ``oversized``               — over the per-page byte budget (re-distill
                                candidates).

Plus the per-section page-count budget with an HONEST overflow report — a
budget breach is surfaced, never silently trimmed.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from pathlib import Path
from typing import Any

from plugins.obsidian.manifest import (
    compute_deltas,
    load_manifest,
    record_page,
    save_manifest,
    split_note,
)
from plugins.obsidian.vault import MANAGED_BEGIN, MANAGED_END
from plugins.obsidian.wiki import (
    ARCHIVE_DIR,
    FORECASTING_DIR,
    INDEX_NOTE,
    SECTION_DIRS,
    is_tombstone_text,
)

DEFAULT_STALE_DAYS = 45
DEFAULT_PAGE_BYTE_BUDGET = 16_000
DEFAULT_SECTION_BUDGETS: dict[str, int] = {
    "questions": 200,
    "lessons": 120,
    "theses": 40,
    "cruxes": 300,
    "postmortems": 150,
    "entities": 150,
}

#: Classes with a safe deterministic apply. ``near_duplicates`` is opt-in
#: (pass it explicitly in ``classes``) — a legitimate shared template can
#: cluster, so tombstoning dupes needs a deliberate operator choice.
DEFAULT_APPLY_CLASSES: tuple[str, ...] = ("resolution_condensation",)
APPLYABLE_CLASSES: tuple[str, ...] = ("resolution_condensation", "near_duplicates")

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_FRONT_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def _parse_frontmatter(front_block: str) -> dict[str, str]:
    """Loose line-based frontmatter parse — enough for status/as_of/ids."""
    out: dict[str, str] = {}
    body = front_block.strip()
    if body.startswith("---"):
        body = body.strip("-\n")
    for line in body.splitlines():
        match = _FRONT_LINE_RE.match(line.strip())
        if match:
            value = match.group(2).strip().strip('"')
            out[match.group(1)] = value
    return out


def _skeleton(text: str) -> str:
    """The templated-batch fingerprint: drop digits + Capitalized tokens so two
    bodies that differ only by substituted names/numbers hash identically."""
    text = re.sub(r"\d+(?:\.\d+)?", "", text or "")
    words = re.findall(r"[A-Za-z']+", text)
    stripped = [w.lower() for w in words if not w[:1].isupper()]
    return " ".join(stripped if len(stripped) >= 6 else (w.lower() for w in words))


def _parse_as_of(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    raw = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed


def scan_vault(vault: Path) -> list[dict[str, Any]]:
    """Read every tracked-section page into an analyzable record."""
    pages: list[dict[str, Any]] = []
    for section, rel_dir in SECTION_DIRS.items():
        root = vault / rel_dir
        if not root.is_dir():
            continue
        for note in sorted(root.rglob("*.md")):
            rel = str(note.relative_to(vault))
            text = note.read_text(encoding="utf-8", errors="replace")
            layers = split_note(text)
            front = _parse_frontmatter(layers["frontmatter"])
            body = (layers["managed"] + "\n" + layers["operator"]).strip()
            pages.append(
                {
                    "path": rel,
                    "section": section,
                    "text": text,
                    "front": front,
                    "body": body,
                    "bytes": len(text.encode("utf-8", errors="replace")),
                    "mtime": note.stat().st_mtime,
                    "tombstone": is_tombstone_text(text),
                    "links_out": [t.strip() for t in _WIKILINK_RE.findall(text)],
                }
            )
    return pages


def _resolvable_targets(vault: Path) -> set[str]:
    """Every wikilink target that resolves: full path or bare basename.

    Scans all of ``Forecasting/`` (index + archive included), not just the
    section dirs, so tombstone→archive links resolve.
    """
    targets: set[str] = set()
    root = vault / FORECASTING_DIR
    if not root.is_dir():
        return targets
    for note in root.rglob("*.md"):
        rel = str(note.relative_to(vault))
        targets.add(rel.removesuffix(".md"))
        targets.add(note.stem)
    return targets


def _ledger_question_status(ledger: Any, question_id: str) -> str | None:
    """The question's LEDGER-TRUTH status, or None when the row is missing."""
    if ledger is None or not question_id:
        return None
    try:
        return ledger.get_question(question_id).status
    except Exception:  # noqa: BLE001 — missing row IS the signal (contradiction)
        return "__missing__"


def build_prune_report(
    vault: Path,
    *,
    ledger: Any = None,
    stale_days: int = DEFAULT_STALE_DAYS,
    page_byte_budget: int = DEFAULT_PAGE_BYTE_BUDGET,
    section_budgets: dict[str, int] | None = None,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Detect every rot class. Read-only — a PROPOSAL, never a mutation."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    budgets = dict(DEFAULT_SECTION_BUDGETS)
    budgets.update(section_budgets or {})

    pages = scan_vault(vault)
    live = [p for p in pages if not p["tombstone"]]
    targets = _resolvable_targets(vault)
    proposals: dict[str, Any] = {
        "broken_links": [],
        "orphans": [],
        "stale": [],
        "near_duplicates": [],
        "resolution_condensation": [],
        "contradictions": [],
        "oversized": [],
    }

    # link graph — incoming edges by resolvable identity (path or basename).
    # The index participates as a linker (an index-listed page is not an
    # orphan; orphans are the pages NOTHING references — operator stragglers).
    incoming: set[str] = set()
    linkers: list[tuple[str, list[str]]] = [
        (page["path"], page["links_out"]) for page in pages
    ]
    index_path = vault / INDEX_NOTE
    if index_path.is_file():
        index_links = [
            t.strip()
            for t in _WIKILINK_RE.findall(
                index_path.read_text(encoding="utf-8", errors="replace")
            )
        ]
        linkers.append((INDEX_NOTE, index_links))
    for source, links_out in linkers:
        for target in links_out:
            incoming.add(target)
            if target not in targets:
                proposals["broken_links"].append(
                    {"path": source, "target": target}
                )

    index_stem = INDEX_NOTE.removesuffix(".md")
    for page in live:
        stem = page["path"].removesuffix(".md")
        basename = Path(page["path"]).stem
        outbound = [t for t in page["links_out"] if t != index_stem]
        has_incoming = stem in incoming or basename in incoming
        if not outbound and not has_incoming:
            proposals["orphans"].append({"path": page["path"], "section": page["section"]})

    # staleness — as_of older than the window on a non-resolved page
    for page in live:
        status = (page["front"].get("status") or "").lower()
        if status in ("resolved", "closed", "archived"):
            continue
        as_of = _parse_as_of(page["front"].get("as_of"))
        if as_of is None:
            continue
        age_days = (now - as_of).total_seconds() / 86_400
        if age_days > stale_days:
            proposals["stale"].append(
                {
                    "path": page["path"],
                    "as_of": page["front"].get("as_of"),
                    "age_days": round(age_days, 1),
                }
            )

    # near-duplicates — identical skeleton within a section, ≥25 words
    clusters: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for page in live:
        skeleton = _skeleton(page["body"])
        if len(skeleton.split()) < 25:
            continue
        key = (page["section"], hashlib.sha1(skeleton.encode()).hexdigest()[:16])
        clusters.setdefault(key, []).append(page)
    for (section, fingerprint), members in sorted(clusters.items()):
        if len(members) < 2:
            continue
        ordered = sorted(members, key=lambda p: p["mtime"])
        proposals["near_duplicates"].append(
            {
                "section": section,
                "fingerprint": fingerprint,
                "keep": ordered[0]["path"],
                "members": [p["path"] for p in ordered],
                "tombstone": [p["path"] for p in ordered[1:]],
            }
        )

    # ledger-truth checks — condensation candidates + contradictions
    postmortem_by_question: dict[str, str] = {}
    for page in live:
        if page["section"] == "postmortems" and page["front"].get("question_id"):
            postmortem_by_question.setdefault(
                page["front"]["question_id"], page["path"]
            )
    for page in live:
        question_id = page["front"].get("question_id")
        if not question_id:
            continue
        ledger_status = _ledger_question_status(ledger, question_id)
        if ledger_status is None:
            continue
        if ledger_status == "__missing__":
            proposals["contradictions"].append(
                {
                    "path": page["path"],
                    "field": "provenance",
                    "page_value": question_id,
                    "ledger_value": "missing",
                    "detail": "page provenance points at a question the ledger does not have",
                }
            )
            continue
        page_status = (page["front"].get("status") or "").lower()
        if page["section"] in ("questions", "cruxes") and ledger_status in (
            "resolved",
            "closed",
        ):
            proposals["resolution_condensation"].append(
                {
                    "path": page["path"],
                    "section": page["section"],
                    "question_id": question_id,
                    "ledger_status": ledger_status,
                    "fold_into": postmortem_by_question.get(question_id),
                }
            )
        if (
            page["section"] in ("questions", "theses")
            and page_status
            and page_status != ledger_status.lower()
        ):
            proposals["contradictions"].append(
                {
                    "path": page["path"],
                    "field": "status",
                    "page_value": page_status,
                    "ledger_value": ledger_status,
                    "detail": "page status drifted from ledger truth — re-sync or condense",
                }
            )

    # oversized — re-distillation candidates
    for page in live:
        if page["bytes"] > page_byte_budget:
            proposals["oversized"].append(
                {"path": page["path"], "bytes": page["bytes"], "budget": page_byte_budget}
            )

    # section budgets — honest overflow only, never a silent trim
    by_section: dict[str, int] = {}
    for page in live:
        by_section[page["section"]] = by_section.get(page["section"], 0) + 1
    budget_state: dict[str, dict[str, int]] = {}
    for section, budget in budgets.items():
        count = by_section.get(section, 0)
        budget_state[section] = {
            "count": count,
            "budget": budget,
            "over_by": max(0, count - budget),
        }

    counts = {key: len(value) for key, value in proposals.items()}
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vault": str(vault),
        "pages": len(pages),
        "tombstones": len(pages) - len(live),
        "proposals": proposals,
        "counts": counts,
        "proposal_count": sum(counts.values()),
        "budget": budget_state,
        "apply_classes": list(DEFAULT_APPLY_CLASSES),
    }


def _archive_relative(rel_path: str) -> str:
    inner = rel_path.removeprefix(f"{FORECASTING_DIR}/")
    return f"{ARCHIVE_DIR}/{inner}"


def tombstone_page(
    vault: Path,
    rel_path: str,
    *,
    reason: str,
    superseded_by: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Archive the full page, rewrite the original as a tombstone. Never deletes.

    Idempotent: an already-tombstoned page is skipped.
    """
    path = vault / rel_path
    if not path.is_file():
        return {"path": rel_path, "skipped": "missing"}
    text = path.read_text(encoding="utf-8", errors="replace")
    if is_tombstone_text(text):
        return {"path": rel_path, "skipped": "already_tombstoned"}

    now = now or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    archive_rel = _archive_relative(rel_path)
    archive_path = vault / archive_rel
    if archive_path.exists():
        stem, suffix = archive_path.stem, archive_path.suffix
        counter = 2
        while archive_path.exists():
            archive_path = archive_path.with_name(f"{stem}-{counter}{suffix}")
            counter += 1
        archive_rel = str(archive_path.relative_to(vault))
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(text, encoding="utf-8")

    front_lines = [
        "---",
        "status: tombstone",
        f"tombstoned_at: {now}",
        f"reason: {reason}",
        f"archive: {archive_rel}",
    ]
    if superseded_by:
        front_lines.append(f"superseded_by: {superseded_by.removesuffix('.md')}")
    front_lines.append("---")
    body_lines = [
        MANAGED_BEGIN,
        "# Tombstone",
        "",
        f"Pruned ({reason}) on {now}. Nothing is deleted: the full page is",
        f"archived at [[{archive_rel.removesuffix('.md')}]].",
    ]
    if superseded_by:
        body_lines.append(f"Successor: [[{superseded_by.removesuffix('.md')}]].")
    body_lines.append(MANAGED_END)
    path.write_text("\n".join(front_lines) + "\n" + "\n".join(body_lines) + "\n", encoding="utf-8")
    return {
        "path": rel_path,
        "archive": archive_rel,
        "superseded_by": superseded_by,
        "reason": reason,
        "tombstoned_at": now,
    }


def apply_prune(
    vault: Path,
    report: dict[str, Any],
    *,
    classes: tuple[str, ...] | list[str] = DEFAULT_APPLY_CLASSES,
    now: str | None = None,
) -> dict[str, Any]:
    """Apply a prune report's safe classes as tombstones. Updates the manifest
    so a tombstone rewrite is never mistaken for an operator edit."""
    unknown = [c for c in classes if c not in APPLYABLE_CLASSES]
    if unknown:
        raise ValueError(
            f"not applyable: {unknown} — applyable classes are {list(APPLYABLE_CLASSES)}"
        )
    proposals = report.get("proposals") or {}
    tombstoned: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    if "resolution_condensation" in classes:
        for proposal in proposals.get("resolution_condensation") or []:
            result = tombstone_page(
                vault,
                proposal["path"],
                reason="resolution_condensation",
                superseded_by=proposal.get("fold_into"),
                now=now,
            )
            (skipped if result.get("skipped") else tombstoned).append(result)

    if "near_duplicates" in classes:
        for cluster in proposals.get("near_duplicates") or []:
            for rel in cluster.get("tombstone") or []:
                result = tombstone_page(
                    vault,
                    rel,
                    reason="near_duplicate",
                    superseded_by=cluster.get("keep"),
                    now=now,
                )
                (skipped if result.get("skipped") else tombstoned).append(result)

    if tombstoned:
        manifest = load_manifest(vault)
        for entry in tombstoned:
            path = vault / entry["path"]
            record_page(
                manifest,
                entry["path"],
                path.read_text(encoding="utf-8", errors="replace"),
                mtime=path.stat().st_mtime,
                synced_at=entry.get("tombstoned_at"),
            )
        save_manifest(vault, manifest)

    return {"tombstoned": tombstoned, "skipped": skipped, "classes": list(classes)}


def build_vault_health(vault: Path, *, ledger: Any = None) -> dict[str, Any]:
    """The doctor's vault-health section: read-only, cheap, honest."""
    report = build_prune_report(vault, ledger=ledger)
    manifest = load_manifest(vault)
    deltas = compute_deltas(vault, manifest)
    pending = [
        d["path"]
        for kind in ("operator_edited", "operator_created")
        for d in deltas[kind]
    ]
    over = {
        section: state
        for section, state in (report.get("budget") or {}).items()
        if state.get("over_by")
    }
    return {
        "vault": str(vault),
        "pages": report.get("pages", 0),
        "tombstones": report.get("tombstones", 0),
        "orphans": report["counts"].get("orphans", 0),
        "broken_links": report["counts"].get("broken_links", 0),
        "stale": report["counts"].get("stale", 0),
        "contradictions": report["counts"].get("contradictions", 0),
        "prune_proposals": report.get("proposal_count", 0),
        "budget_overflows": over,
        "operator_edits_pending": len(pending),
        "pending_paths": pending[:10],
    }


__all__ = [
    "DEFAULT_STALE_DAYS",
    "DEFAULT_PAGE_BYTE_BUDGET",
    "DEFAULT_SECTION_BUDGETS",
    "DEFAULT_APPLY_CLASSES",
    "APPLYABLE_CLASSES",
    "scan_vault",
    "build_prune_report",
    "tombstone_page",
    "apply_prune",
    "build_vault_health",
]
