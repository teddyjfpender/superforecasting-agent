"""Sync the forecast desk's learnings into the Obsidian vault.

What gets written (all under ``Forecasting/`` in the vault):

* ``Lessons/<scope>-<id>.md``    — one note per calibration lesson: the
  distilled opinion, its scope, confidence, status, and evidence refs.
* ``Questions/<title>-<id>.md``  — one dossier per question: description,
  resolution criteria, current probability, and the analyst-note timeline
  (briefs + retrospectives), wikilinked to lessons that share its domain.
* ``Forecast Desk Index.md``     — the entry point linking everything.

Notes are regenerated idempotently: agent content lives between the
``superforecasting`` managed markers (see :mod:`plugins.obsidian.vault`), so a
human can annotate above/below the block and survive the next sync. The vault
is treated as a publishing target, never as a source of truth — the ledger DB
stays authoritative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from plugins.obsidian.vault import (
    render_frontmatter,
    slugify,
    splice_managed_block,
    write_note,
)

FORECASTING_DIR = "Forecasting"
LESSONS_DIR = f"{FORECASTING_DIR}/Lessons"
QUESTIONS_DIR = f"{FORECASTING_DIR}/Questions"
INDEX_NOTE = f"{FORECASTING_DIR}/Forecast Desk Index.md"

_ANALYST_NOTES_PER_QUESTION = 5


def _lesson_note_name(lesson: dict[str, Any]) -> str:
    scope = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
    return f"lesson-{slugify(str(scope), max_len=40)}-{str(lesson.get('id', ''))[-6:]}"


def _question_note_name(question: Any) -> str:
    return f"{slugify(question.title, max_len=60)}-{question.id[-6:]}"


def _render_lesson(lesson: dict[str, Any]) -> tuple[str, str]:
    """Return (frontmatter, body) for a calibration-lesson note."""
    front = render_frontmatter(
        {
            "lesson_id": lesson.get("id"),
            "scope_type": lesson.get("scope_type"),
            "scope_ref": lesson.get("scope_ref"),
            "status": lesson.get("status"),
            "confidence": lesson.get("confidence"),
            "updated_at": lesson.get("updated_at"),
            "tags": ["forecasting/lesson", f"scope/{lesson.get('scope_type', 'global')}"],
        }
    )
    scope_label = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
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
    lines.append("")
    lines.append(f"[[{INDEX_NOTE.removesuffix('.md')}|Forecast Desk Index]]")
    return front, "\n".join(lines)


def _render_question(
    question: Any,
    snapshot: Any | None,
    notes: list[dict[str, Any]],
    domain_lessons: list[str],
) -> tuple[str, str]:
    """Return (frontmatter, body) for a question dossier note."""
    probability = None
    if snapshot is not None:
        probability = snapshot.probability_or_distribution
    front = render_frontmatter(
        {
            "question_id": question.id,
            "status": question.status,
            "domain": question.domain,
            "obsidian_tags": ["forecasting/question"] + [f"topic/{slugify(t)}" for t in (question.tags or [])[:6]],
            "close_time": question.close_time,
            "current_probability": probability if isinstance(probability, (int, float)) else None,
            "as_of": snapshot.as_of if snapshot is not None else None,
        }
    )
    lines = [f"# {question.title}", ""]
    if isinstance(probability, (int, float)):
        lines.append(f"**Current forecast:** {probability:.1%} (as of {snapshot.as_of})")
        lines.append("")
    elif snapshot is not None:
        lines.append(f"**Current forecast:** `{probability}` (as of {snapshot.as_of})")
        lines.append("")
    if (question.description or "").strip():
        lines += [question.description.strip(), ""]
    lines += [
        "## Resolution criteria",
        "",
        question.resolution_criteria.strip() or "_none recorded_",
        "",
    ]
    if snapshot is not None and (snapshot.rationale or "").strip():
        lines += ["## Current rationale", "", snapshot.rationale.strip(), ""]
    if notes:
        lines += ["## Analyst notes", ""]
        for note in reversed(notes[-_ANALYST_NOTES_PER_QUESTION:]):
            headline = (note.get("headline") or "").strip() or note.get("kind", "note")
            lines.append(f"### {note.get('as_of', note.get('created_at', ''))} — {headline}")
            body = (note.get("body") or "").strip()
            if body:
                lines += ["", body]
            for label, key in (
                ("Looking for", "looking_for"),
                ("Be aware", "be_aware"),
            ):
                extra = (note.get(key) or "").strip()
                if extra:
                    lines.append(f"- **{label}:** {extra}")
            lines.append("")
    if domain_lessons:
        lines += ["## Related lessons", ""]
        lines += [f"- [[{LESSONS_DIR}/{name}]]" for name in domain_lessons]
        lines.append("")
    lines.append(f"[[{INDEX_NOTE.removesuffix('.md')}|Forecast Desk Index]]")
    return front, "\n".join(lines)


def _render_index(
    question_entries: list[tuple[str, Any]],
    lesson_entries: list[tuple[str, dict[str, Any]]],
) -> str:
    lines = [
        "# Forecast Desk Index",
        "",
        "Auto-published from the superforecasting-agent ledger. The ledger DB",
        "is the source of truth; edits inside the managed markers are",
        "overwritten on the next `obsidian_sync_learnings` run.",
        "",
        "## Active questions",
        "",
    ]
    if question_entries:
        for name, question in question_entries:
            domain = f" · {question.domain}" if question.domain else ""
            lines.append(f"- [[{QUESTIONS_DIR}/{name}|{question.title}]] ({question.status}{domain})")
    else:
        lines.append("_no questions synced_")
    lines += ["", "## Calibration lessons", ""]
    if lesson_entries:
        for name, lesson in lesson_entries:
            scope = lesson.get("scope_ref") or lesson.get("scope_type") or "global"
            lines.append(
                f"- [[{LESSONS_DIR}/{name}|{scope}]] ({lesson.get('status', '?')})"
            )
    else:
        lines.append("_no lessons synced_")
    return "\n".join(lines)


def _publish(vault: Path, relative: str, frontmatter: str, body: str) -> None:
    path = vault / relative
    existing = path.read_text(encoding="utf-8") if path.is_file() else None
    managed = splice_managed_block(existing, body)
    # Frontmatter must stay at byte 0 for Obsidian to parse it, so it sits
    # outside the managed block and is only written on first publish.
    if existing is None or not existing.startswith("---"):
        managed = frontmatter + managed
    write_note(path, managed)


def sync_learnings(
    vault: Path,
    *,
    db: str | None = None,
    scope: str = "all",
    active_only: bool = False,
    question_status: str | None = "active",
    limit: int | None = None,
) -> dict[str, Any]:
    """Publish ledger learnings into *vault*. Returns a summary dict.

    scope: "lessons", "questions", or "all".
    active_only: restrict lessons to status='active'.
    question_status: ledger question-status filter (None = all).
    """
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger(db)
    summary: dict[str, Any] = {"vault": str(vault), "lessons": 0, "questions": 0}

    lesson_entries: list[tuple[str, dict[str, Any]]] = []
    if scope in ("lessons", "all"):
        lessons = ledger.list_calibration_lessons(active_only=active_only)
        if limit:
            lessons = lessons[: int(limit)]
        for lesson in lessons:
            name = _lesson_note_name(lesson)
            front, body = _render_lesson(lesson)
            _publish(vault, f"{LESSONS_DIR}/{name}.md", front, body)
            lesson_entries.append((name, lesson))
        summary["lessons"] = len(lesson_entries)

    question_entries: list[tuple[str, Any]] = []
    if scope in ("questions", "all"):
        questions = ledger.list_questions(status=question_status, limit=limit)
        lessons_by_domain: dict[str, list[str]] = {}
        for name, lesson in lesson_entries:
            ref = (lesson.get("scope_ref") or "").strip().lower()
            if ref:
                lessons_by_domain.setdefault(ref, []).append(name)
        for question in questions:
            snapshot = ledger.get_current_snapshot(question.id)
            notes = ledger.list_analyst_notes(question.id, limit=None)
            domain_lessons = lessons_by_domain.get((question.domain or "").strip().lower(), [])
            name = _question_note_name(question)
            front, body = _render_question(question, snapshot, notes, domain_lessons)
            _publish(vault, f"{QUESTIONS_DIR}/{name}.md", front, body)
            question_entries.append((name, question))
        summary["questions"] = len(question_entries)

    index_body = _render_index(question_entries, lesson_entries)
    _publish(vault, INDEX_NOTE, "", index_body)
    summary["index"] = str(vault / INDEX_NOTE)
    return summary
