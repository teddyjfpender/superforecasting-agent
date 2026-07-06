"""The second-brain vault schema + the enriched ledger→vault sync.

``sync_wiki`` publishes the whole forecast-domain concept graph (a superset of
:func:`plugins.obsidian.sync.sync_learnings`, which stays untouched for
back-compat): question dossiers enriched with cruxes / forecast links / thesis
membership, calibration lessons, theses (members + entities), cruxes,
postmortems, and entity pages — all wikilinked, all with the frontmatter
contract ``{summary, provenance, as_of, ledger_refs, status}``, all spliced
into managed markers so operator annotations survive every re-sync.

Every published page is recorded in the delta manifest
(:mod:`plugins.obsidian.manifest`), which is what makes the vault→agent half
of the collaboration loop (operator-note ingestion) possible.

Tombstoned pages (``status: tombstone`` in frontmatter — the prune pass's
apply artifact) are never resurrected by a sync.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from plugins.obsidian.manifest import (
    load_manifest,
    record_page,
    save_manifest,
)
from plugins.obsidian.sync import _publish
from plugins.obsidian.vault import render_frontmatter, slugify

FORECASTING_DIR = "Forecasting"
INDEX_NOTE = f"{FORECASTING_DIR}/Forecast Desk Index.md"
ARCHIVE_DIR = f"{FORECASTING_DIR}/Archive"

QUESTIONS_DIR = f"{FORECASTING_DIR}/Questions"
LESSONS_DIR = f"{FORECASTING_DIR}/Lessons"
THESES_DIR = f"{FORECASTING_DIR}/Theses"
CRUXES_DIR = f"{FORECASTING_DIR}/Cruxes"
POSTMORTEMS_DIR = f"{FORECASTING_DIR}/Postmortems"
ENTITIES_DIR = f"{FORECASTING_DIR}/Entities"

SECTION_DIRS: dict[str, str] = {
    "questions": QUESTIONS_DIR,
    "lessons": LESSONS_DIR,
    "theses": THESES_DIR,
    "cruxes": CRUXES_DIR,
    "postmortems": POSTMORTEMS_DIR,
    "entities": ENTITIES_DIR,
}

_ANALYST_NOTES_PER_QUESTION = 5


def is_tombstone_text(text: str | None) -> bool:
    """A tombstoned page must never be re-published by a sync."""
    if not text or not text.startswith("---"):
        return False
    head = text.split("---", 2)
    if len(head) < 3:
        return False
    return any(
        line.strip() == "status: tombstone" for line in head[1].splitlines()
    )


def _front(
    *,
    summary: str,
    provenance: str,
    as_of: str | None,
    ledger_refs: list[str],
    status: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    meta: dict[str, Any] = {
        "summary": (summary or "").strip().replace("\n", " ")[:300],
        "provenance": provenance,
        "as_of": as_of,
        "ledger_refs": ledger_refs,
        "status": status,
    }
    if extra:
        meta.update(extra)
    return render_frontmatter(meta)


def _link(relative_note: str, label: str | None = None) -> str:
    target = relative_note.removesuffix(".md")
    return f"[[{target}|{label}]]" if label else f"[[{target}]]"


def question_note_name(question: Any) -> str:
    return f"{slugify(question.title, max_len=60)}-{question.id[-6:]}"


def lesson_note_name(lesson: dict[str, Any]) -> str:
    scope = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
    return f"lesson-{slugify(str(scope), max_len=40)}-{str(lesson.get('id', ''))[-6:]}"


def crux_note_name(crux: dict[str, Any]) -> str:
    return f"{slugify(str(crux.get('crux_variable', '')), max_len=50)}-{str(crux.get('id', ''))[-6:]}"


def postmortem_note_name(pm: dict[str, Any], question: Any) -> str:
    return f"pm-{slugify(question.title, max_len=50)}-{str(pm.get('id', ''))[-6:]}"


def entity_note_name(name: str) -> str:
    return slugify(name, max_len=60)


def _forecast_line(snapshot: Any) -> list[str]:
    if snapshot is None:
        return []
    value = snapshot.probability_or_distribution
    if isinstance(value, (int, float)):
        return [f"**Current forecast:** {value:.1%} (as of {snapshot.as_of})", ""]
    return [f"**Current forecast:** `{value}` (as of {snapshot.as_of})", ""]


def _render_question_page(
    question: Any,
    snapshot: Any,
    notes: list[dict[str, Any]],
    *,
    crux_names: list[tuple[str, dict[str, Any]]],
    links: list[dict[str, Any]],
    question_names: dict[str, str],
    thesis_names: list[tuple[str, str]],
    lesson_links: list[str],
) -> tuple[str, str]:
    front = _front(
        summary=(question.description or question.title or "").strip(),
        provenance=f"ledger:question:{question.id}",
        as_of=snapshot.as_of if snapshot is not None else question.created_at,
        ledger_refs=[question.id],
        status=question.status,
        extra={
            "question_id": question.id,
            "domain": question.domain,
            "tags": ["forecasting/question"]
            + [f"topic/{slugify(t)}" for t in (question.tags or [])[:6]],
        },
    )
    lines: list[str] = [f"# {question.title}", ""]
    lines += _forecast_line(snapshot)
    if (question.description or "").strip():
        lines += [question.description.strip(), ""]
    lines += [
        "## Resolution criteria",
        "",
        (question.resolution_criteria or "").strip() or "_none recorded_",
        "",
    ]
    if snapshot is not None and (snapshot.rationale or "").strip():
        lines += ["## Current rationale", "", snapshot.rationale.strip(), ""]
    if crux_names:
        lines += ["## Cruxes", ""]
        for name, crux in crux_names:
            crux_link = _link(f"{CRUXES_DIR}/{name}", crux.get("crux_variable"))
            lines.append(
                f"- {crux_link} ({crux.get('materiality')}, {crux.get('status')})"
            )
        lines.append("")
    if notes:
        lines += ["## Analyst notes", ""]
        for note in reversed(notes[-_ANALYST_NOTES_PER_QUESTION:]):
            headline = (note.get("headline") or "").strip() or note.get("kind", "note")
            lines.append(f"### {note.get('as_of', note.get('created_at', ''))} — {headline}")
            body = (note.get("body") or "").strip()
            if body:
                lines += ["", body]
            lines.append("")
    if links:
        lines += ["## Related forecasts", ""]
        for link in links:
            other = (
                link.get("to_question_id")
                if link.get("from_question_id") == question.id
                else link.get("from_question_id")
            )
            other_name = question_names.get(str(other))
            label = f"{link.get('link_type', 'related')}: "
            if other_name:
                lines.append(f"- {label}{_link(f'{QUESTIONS_DIR}/{other_name}')}")
            else:
                lines.append(f"- {label}`{other}`")
        lines.append("")
    if thesis_names:
        lines += ["## Theses", ""]
        lines += [
            f"- {_link(f'{THESES_DIR}/{name}', title)}" for name, title in thesis_names
        ]
        lines.append("")
    if lesson_links:
        lines += ["## Related lessons", ""]
        lines += [f"- {_link(f'{LESSONS_DIR}/{name}')}" for name in lesson_links]
        lines.append("")
    lines.append(_link(INDEX_NOTE, "Forecast Desk Index"))
    return front, "\n".join(lines)


def _render_lesson_page(lesson: dict[str, Any]) -> tuple[str, str]:
    scope_label = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
    front = _front(
        summary=str(lesson.get("lesson") or ""),
        provenance=f"ledger:lesson:{lesson.get('id')}",
        as_of=lesson.get("updated_at") or lesson.get("created_at"),
        ledger_refs=[str(lesson.get("id"))],
        status=lesson.get("status"),
        extra={
            "scope_type": lesson.get("scope_type"),
            "scope_ref": lesson.get("scope_ref"),
            "confidence": lesson.get("confidence"),
            "tags": ["forecasting/lesson", f"scope/{lesson.get('scope_type', 'global')}"],
        },
    )
    lines = [
        f"# Lesson — {scope_label}",
        "",
        (lesson.get("lesson") or "").strip(),
        "",
        f"- **Status:** {lesson.get('status', 'unknown')}",
        f"- **Confidence:** {lesson.get('confidence')}",
    ]
    adjustment = lesson.get("recommended_adjustment") or {}
    if adjustment:
        lines.append(f"- **Recommended adjustment:** `{adjustment}`")
    refs = (lesson.get("source_postmortem_refs") or []) + (
        lesson.get("source_score_record_refs") or []
    )
    if refs:
        lines.append(f"- **Evidence refs:** {', '.join(f'`{r}`' for r in refs)}")
    lines += ["", _link(INDEX_NOTE, "Forecast Desk Index")]
    return front, "\n".join(lines)


def _render_thesis_page(
    thesis: Any,
    snapshot: Any,
    members: list[dict[str, Any]],
    entities: list[dict[str, Any]],
    question_names: dict[str, str],
) -> tuple[str, str]:
    front = _front(
        summary=(thesis.description or thesis.title or "").strip(),
        provenance=f"ledger:question:{thesis.id}",
        as_of=snapshot.as_of if snapshot is not None else thesis.created_at,
        ledger_refs=[thesis.id],
        status=thesis.status,
        extra={"question_id": thesis.id, "tags": ["forecasting/thesis"]},
    )
    lines: list[str] = [f"# Thesis — {thesis.title}", ""]
    lines += _forecast_line(snapshot)
    if (thesis.description or "").strip():
        lines += [thesis.description.strip(), ""]
    if members:
        lines += ["## Members", ""]
        for member in members:
            mid = str(member.get("member_question_id"))
            name = question_names.get(mid)
            target = _link(f"{QUESTIONS_DIR}/{name}") if name else f"`{mid}`"
            lines.append(
                f"- {target} ({member.get('direction', 'support')}, w={member.get('weight')})"
            )
        lines.append("")
    if entities:
        lines += ["## Entities", ""]
        for entity in entities:
            name = str(entity.get("name") or "")
            entity_link = _link(f"{ENTITIES_DIR}/{entity_note_name(name)}", name)
            lines.append(f"- {entity_link} ({entity.get('kind', 'entity')})")
        lines.append("")
    lines.append(_link(INDEX_NOTE, "Forecast Desk Index"))
    return front, "\n".join(lines)


def _render_crux_page(
    crux: dict[str, Any], question: Any, question_name: str
) -> tuple[str, str]:
    front = _front(
        summary=str(crux.get("crux_variable") or ""),
        provenance=f"ledger:crux:{crux.get('id')}",
        as_of=crux.get("updated_at") or crux.get("created_at"),
        ledger_refs=[str(crux.get("id")), question.id],
        status=crux.get("status"),
        extra={
            "question_id": question.id,
            "materiality": crux.get("materiality"),
            "tags": ["forecasting/crux"],
        },
    )
    question_link = _link(f"{QUESTIONS_DIR}/{question_name}", question.title)
    lines = [
        f"# Crux — {crux.get('crux_variable')}",
        "",
        f"Decisive variable for {question_link}.",
        "",
        f"- **Materiality:** {crux.get('materiality')}",
        f"- **Evidence status:** {crux.get('status')}",
    ]
    roles = crux.get("preferred_roles") or []
    if roles:
        lines.append(f"- **Preferred source roles:** {', '.join(str(r) for r in roles)}")
    notes = (crux.get("notes") or "").strip()
    if notes:
        lines += ["", notes]
    lines += ["", _link(INDEX_NOTE, "Forecast Desk Index")]
    return front, "\n".join(lines)


def _render_postmortem_page(
    pm: dict[str, Any], question: Any, question_name: str
) -> tuple[str, str]:
    front = _front(
        summary=str(pm.get("summary") or ""),
        provenance=f"ledger:postmortem:{pm.get('id')}",
        as_of=pm.get("created_at"),
        ledger_refs=[str(pm.get("id")), question.id],
        status="resolved",
        extra={"question_id": question.id, "tags": ["forecasting/postmortem"]},
    )
    question_link = _link(f"{QUESTIONS_DIR}/{question_name}", question.title)
    lines = [
        f"# Postmortem — {question.title}",
        "",
        (pm.get("summary") or "").strip(),
        "",
        f"Question: {question_link}",
        "",
    ]
    for label, key in (
        ("What happened", "what_happened"),
        ("What was expected", "what_was_expected"),
        ("Missed evidence", "missed_evidence"),
        ("Overweighted evidence", "overweighted_evidence"),
        ("Lesson", "lesson"),
    ):
        value = (pm.get(key) or "").strip()
        if value:
            lines += [f"## {label}", "", value, ""]
    lines.append(_link(INDEX_NOTE, "Forecast Desk Index"))
    return front, "\n".join(lines)


def _render_entity_page(
    name: str, appearances: list[dict[str, Any]], thesis_names: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    ids = [str(a.get("id")) for a in appearances if a.get("id")]
    kinds = sorted({str(a.get("kind") or "entity") for a in appearances})
    as_of = max(
        (str(a.get("updated_at") or a.get("created_at") or "") for a in appearances),
        default=None,
    )
    front = _front(
        summary=f"{name} ({', '.join(kinds)}) across {len(appearances)} thesis view(s)",
        provenance=f"ledger:thesis_entity:{ids[0]}" if ids else "ledger:thesis_entity",
        as_of=as_of or None,
        ledger_refs=ids,
        status="active",
        extra={"tags": ["forecasting/entity"] + [f"entity/{slugify(k)}" for k in kinds]},
    )
    lines = [f"# {name}", ""]
    for appearance in appearances:
        tid = str(appearance.get("thesis_question_id"))
        entry = thesis_names.get(tid)
        target = _link(f"{THESES_DIR}/{entry[0]}", entry[1]) if entry else f"`{tid}`"
        label = (appearance.get("label") or "").strip()
        suffix = f" — {label}" if label else ""
        lines.append(f"- {target} ({appearance.get('kind', 'entity')}){suffix}")
    lines += ["", _link(INDEX_NOTE, "Forecast Desk Index")]
    return front, "\n".join(lines)


def _render_index(sections: dict[str, list[tuple[str, str]]]) -> str:
    lines = [
        "# Forecast Desk Index",
        "",
        "Auto-published from the superforecasting-agent ledger (the source of",
        "truth). Content inside the managed markers is regenerated by",
        "`obsidian_wiki_sync`; annotate above/below them and your notes survive.",
        "Operator annotations on question pages are ingested as evidence via",
        "`obsidian_ingest_notes` (triage-gated).",
        "",
    ]
    titles = {
        "questions": "Active questions",
        "theses": "Theses",
        "lessons": "Calibration lessons",
        "cruxes": "Cruxes",
        "postmortems": "Postmortems",
        "entities": "Entities",
    }
    for key, heading in titles.items():
        entries = sections.get(key) or []
        lines += [f"## {heading}", ""]
        if entries:
            lines += [
                f"- {_link(f'{SECTION_DIRS[key]}/{name}', label)}" for name, label in entries
            ]
        else:
            lines.append("_none synced_")
        lines.append("")
    return "\n".join(lines).rstrip()


_FRONT_BLOCK_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)

#: Frontmatter keys re-synced to ledger truth on every publish (the rest of
#: the block — including operator-added keys — is left alone).
_REFRESH_KEYS = ("as_of", "status")


def _refresh_frontmatter(text: str, new_front: str) -> str:
    """Update the ledger-truth keys (as_of, status) in an existing frontmatter
    block. Frontmatter sits outside the managed markers (it must stay at byte
    0 for Obsidian), so `_publish` writes it only on first publish — without
    this, as_of would freeze at first sync and the prune pass's staleness /
    contradiction checks would read stale truth."""
    old_match = _FRONT_BLOCK_RE.match(text or "")
    new_match = _FRONT_BLOCK_RE.match(new_front or "")
    if not (old_match and new_match):
        return text
    replacements: dict[str, str] = {}
    for line in new_match.group(1).splitlines():
        key = line.partition(":")[0].strip()
        if key in _REFRESH_KEYS:
            replacements[key] = line
    if not replacements:
        return text
    out_lines: list[str] = []
    seen: set[str] = set()
    for line in old_match.group(1).splitlines():
        key = line.partition(":")[0].strip()
        if key in replacements:
            out_lines.append(replacements[key])
            seen.add(key)
        else:
            out_lines.append(line)
    out_lines += [line for key, line in replacements.items() if key not in seen]
    return "---\n" + "\n".join(out_lines) + "\n---\n" + text[old_match.end():]


def _publish_page(
    vault: Path,
    manifest: dict[str, Any],
    relative: str,
    frontmatter: str,
    body: str,
    *,
    now: str,
    provenance: str | None,
    ledger_refs: list[str] | None,
) -> bool:
    """Publish one page (managed-marker splice) unless it is a tombstone.

    Returns True when the page was written; records it in the manifest.
    """
    path = vault / relative
    if path.is_file() and is_tombstone_text(
        path.read_text(encoding="utf-8", errors="replace")
    ):
        return False
    _publish(vault, relative, frontmatter, body)
    text = path.read_text(encoding="utf-8", errors="replace")
    refreshed = _refresh_frontmatter(text, frontmatter)
    if refreshed != text:
        path.write_text(refreshed, encoding="utf-8")
        text = refreshed
    record_page(
        manifest,
        relative,
        text,
        mtime=path.stat().st_mtime,
        synced_at=now,
        provenance=provenance,
        ledger_refs=ledger_refs,
    )
    return True


def sync_wiki(
    vault: Path,
    *,
    db: str | None = None,
    question_status: str | None = "active",
    limit: int | None = None,
) -> dict[str, Any]:
    """Publish the enriched concept-page graph into *vault*.

    Returns a summary dict with per-section counts + the manifest path.
    """
    from forecasting.ledger import ForecastLedger
    from forecasting.models import utc_now_iso

    ledger = ForecastLedger(db)
    now = utc_now_iso()
    manifest = load_manifest(vault)
    summary: dict[str, Any] = {"vault": str(vault)}

    all_questions = ledger.list_questions(status=question_status, limit=limit)
    theses = [q for q in all_questions if ledger.is_thesis(q)]
    questions = [q for q in all_questions if not ledger.is_thesis(q)]

    question_names = {q.id: question_note_name(q) for q in questions}
    thesis_names = {t.id: (question_note_name(t), t.title) for t in theses}

    # Lessons first, so question pages can wikilink domain lessons.
    lessons = ledger.list_calibration_lessons(active_only=False)
    lesson_entries: list[tuple[str, str]] = []
    lessons_by_domain: dict[str, list[str]] = {}
    for lesson in lessons:
        name = lesson_note_name(lesson)
        front, body = _render_lesson_page(lesson)
        _publish_page(
            vault, manifest, f"{SECTION_DIRS['lessons']}/{name}.md", front, body,
            now=now, provenance=f"ledger:lesson:{lesson.get('id')}",
            ledger_refs=[str(lesson.get("id"))],
        )
        scope_label = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
        lesson_entries.append((name, str(scope_label)))
        ref = (lesson.get("scope_ref") or "").strip().lower()
        if ref:
            lessons_by_domain.setdefault(ref, []).append(name)

    crux_entries: list[tuple[str, str]] = []
    question_entries: list[tuple[str, str]] = []
    for question in questions:
        snapshot = ledger.get_current_snapshot(question.id)
        notes = ledger.list_analyst_notes(question.id, limit=None)
        cruxes = ledger.list_cruxes(question.id)
        links = ledger.list_forecast_links(question.id)
        memberships = ledger.list_theses_for_member(question.id)
        crux_names = [(crux_note_name(c), c) for c in cruxes]
        member_of = [
            thesis_names[str(m.get("thesis_id"))]
            for m in memberships
            if str(m.get("thesis_id")) in thesis_names
        ]
        domain_lessons = lessons_by_domain.get((question.domain or "").strip().lower(), [])
        qname = question_names[question.id]
        front, body = _render_question_page(
            question, snapshot, notes,
            crux_names=crux_names, links=links, question_names=question_names,
            thesis_names=member_of, lesson_links=domain_lessons,
        )
        _publish_page(
            vault, manifest, f"{SECTION_DIRS['questions']}/{qname}.md", front, body,
            now=now, provenance=f"ledger:question:{question.id}",
            ledger_refs=[question.id],
        )
        question_entries.append((qname, question.title))

        for name, crux in crux_names:
            cfront, cbody = _render_crux_page(crux, question, qname)
            _publish_page(
                vault, manifest, f"{SECTION_DIRS['cruxes']}/{name}.md", cfront, cbody,
                now=now, provenance=f"ledger:crux:{crux.get('id')}",
                ledger_refs=[str(crux.get("id")), question.id],
            )
            crux_entries.append((name, str(crux.get("crux_variable") or name)))

    # Postmortems belong to RESOLVED questions, which fall outside the default
    # status filter — sync them from the full postmortem list so resolutions
    # keep their retrospective pages after the question leaves the active book.
    postmortem_entries: list[tuple[str, str]] = []
    for pm in ledger.list_postmortems():
        try:
            pm_question = ledger.get_question(str(pm.get("question_id")))
        except Exception:  # noqa: BLE001 — a postmortem for a purged question
            continue
        qname = question_names.get(pm_question.id) or question_note_name(pm_question)
        pname = postmortem_note_name(pm, pm_question)
        pfront, pbody = _render_postmortem_page(pm, pm_question, qname)
        _publish_page(
            vault, manifest, f"{SECTION_DIRS['postmortems']}/{pname}.md", pfront, pbody,
            now=now, provenance=f"ledger:postmortem:{pm.get('id')}",
            ledger_refs=[str(pm.get("id")), pm_question.id],
        )
        postmortem_entries.append((pname, str(pm.get("summary") or pname)[:60]))

    thesis_entries: list[tuple[str, str]] = []
    entity_appearances: dict[str, list[dict[str, Any]]] = {}
    for thesis in theses:
        snapshot = ledger.get_current_snapshot(thesis.id)
        members = ledger.list_thesis_members(thesis.id)
        entities = ledger.list_thesis_entities(thesis.id)
        tname = thesis_names[thesis.id][0]
        front, body = _render_thesis_page(
            thesis, snapshot, members, entities, question_names
        )
        _publish_page(
            vault, manifest, f"{SECTION_DIRS['theses']}/{tname}.md", front, body,
            now=now, provenance=f"ledger:question:{thesis.id}",
            ledger_refs=[thesis.id],
        )
        thesis_entries.append((tname, thesis.title))
        for entity in entities:
            name = str(entity.get("name") or "").strip()
            if name:
                entity_appearances.setdefault(name, []).append(entity)

    entity_entries: list[tuple[str, str]] = []
    for name, appearances in sorted(entity_appearances.items()):
        ename = entity_note_name(name)
        front, body = _render_entity_page(name, appearances, thesis_names)
        _publish_page(
            vault, manifest, f"{SECTION_DIRS['entities']}/{ename}.md", front, body,
            now=now, provenance=None,
            ledger_refs=[str(a.get("id")) for a in appearances if a.get("id")],
        )
        entity_entries.append((ename, name))

    sections = {
        "questions": question_entries,
        "theses": thesis_entries,
        "lessons": lesson_entries,
        "cruxes": crux_entries,
        "postmortems": postmortem_entries,
        "entities": entity_entries,
    }
    _publish(vault, INDEX_NOTE, "", _render_index(sections))
    index_text = (vault / INDEX_NOTE).read_text(encoding="utf-8", errors="replace")
    record_page(manifest, INDEX_NOTE, index_text, synced_at=now, provenance="index")

    manifest["generated_at"] = now
    manifest_file = save_manifest(vault, manifest)

    summary.update({key: len(entries) for key, entries in sections.items()})
    summary["index"] = str(vault / INDEX_NOTE)
    summary["manifest"] = str(manifest_file)
    return summary


__all__ = [
    "SECTION_DIRS",
    "ARCHIVE_DIR",
    "INDEX_NOTE",
    "is_tombstone_text",
    "question_note_name",
    "lesson_note_name",
    "crux_note_name",
    "postmortem_note_name",
    "entity_note_name",
    "sync_wiki",
]
