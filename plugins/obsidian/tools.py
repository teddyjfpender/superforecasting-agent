"""Agent-facing tools for the obsidian plugin.

Tools:
  obsidian_read_note      — read a note (vault-relative path)
  obsidian_write_note     — create/overwrite a note, optional frontmatter
  obsidian_append_note    — append a section (creates the note if missing)
  obsidian_search         — filename or content search across vault markdown
  obsidian_sync_learnings — publish ledger learnings (lessons, question
                            dossiers, index) into the vault
  obsidian_wiki_sync      — the enriched second-brain sync: questions (with
                            cruxes/links), lessons, theses, cruxes,
                            postmortems, entities + the delta manifest
  obsidian_wiki_query     — retrieval-before-forecast: a question's concept
                            page plus one hop of its wikilink neighbourhood
  obsidian_ingest_notes   — ingest operator note deltas as evidence, through
                            the triage trust gate (never around it)

All handlers return JSON strings. Paths are vault-relative and traversal-safe;
the vault root comes from OBSIDIAN_VAULT_PATH, else the managed workspace vault
~/.superforecasting-agent/docs/vault (created on first use).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict

from plugins.obsidian.vault import (
    render_frontmatter,
    resolve_vault_path,
    safe_note_path,
)

_MAX_SEARCH_RESULTS = 50
_MAX_READ_BYTES = 256_000


def check_obsidian_available() -> bool:
    """Runtime gate: a vault directory must be resolvable."""
    return resolve_vault_path() is not None


def _json(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _err(message: str, **extra: Any) -> str:
    return _json({"success": False, "error": message, **extra})


def _vault_or_error() -> tuple[Path | None, str | None]:
    vault = resolve_vault_path()
    if vault is None:
        return None, (
            "OBSIDIAN_VAULT_PATH points at a path that isn't a directory — "
            "unset it to use the managed workspace vault "
            "(~/.superforecasting-agent/docs/vault), or point it at a real "
            "vault directory (e.g. in ~/.superforecasting-agent/.env)"
        )
    return vault, None


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

OBSIDIAN_READ_NOTE_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_read_note",
    "description": (
        "Read a note from the Obsidian vault. Path is relative to the vault "
        "root ('.md' is optional). Returns the note text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Vault-relative note path, e.g. 'Forecasting/Forecast Desk Index'.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    },
}

OBSIDIAN_WRITE_NOTE_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_write_note",
    "description": (
        "Create or overwrite a note in the Obsidian vault. Refuses to "
        "overwrite an existing note unless overwrite=true. Optional "
        "frontmatter dict is rendered as YAML at the top. Use [[wikilinks]] "
        "in the content to link related notes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Vault-relative note path ('.md' optional). Folders are created as needed.",
            },
            "content": {
                "type": "string",
                "description": "Markdown body of the note.",
            },
            "frontmatter": {
                "type": "object",
                "description": "Optional YAML frontmatter key/values (tags, aliases, dates...).",
            },
            "overwrite": {
                "type": "boolean",
                "description": "Allow replacing an existing note. Default false.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}

OBSIDIAN_APPEND_NOTE_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_append_note",
    "description": (
        "Append markdown to a note in the Obsidian vault (creates the note "
        "if missing). With 'heading', the content is inserted at the end of "
        "that section instead of the end of the file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Vault-relative note path ('.md' optional).",
            },
            "content": {
                "type": "string",
                "description": "Markdown to append.",
            },
            "heading": {
                "type": "string",
                "description": "Optional heading text — append at the end of this section.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
}

OBSIDIAN_SEARCH_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_search",
    "description": (
        "Search the Obsidian vault's markdown notes. kind='files' matches "
        "note names; kind='content' greps note bodies (case-insensitive "
        "regex). Returns up to 50 matches."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Substring (files) or regex (content) to search for.",
            },
            "kind": {
                "type": "string",
                "enum": ["files", "content"],
                "description": "What to search. Default 'content'.",
            },
            "folder": {
                "type": "string",
                "description": "Optional vault-relative folder to restrict the search to.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

OBSIDIAN_WIKI_SYNC_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_wiki_sync",
    "description": (
        "Publish the full second-brain concept graph into the Obsidian vault: "
        "question dossiers (with cruxes, related forecasts, thesis membership), "
        "calibration lessons, theses (members + entities), crux pages, "
        "postmortems, entity pages, and the index — all wikilinked, all with "
        "provenance frontmatter, all inside managed markers so operator "
        "annotations survive. Updates the delta manifest. The ledger stays the "
        "source of truth; tombstoned pages are never resurrected."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question_status": {
                "type": "string",
                "description": "Question status filter (e.g. 'active', 'resolved'). Default 'active'.",
            },
            "limit": {
                "type": "integer",
                "description": "Cap on questions/theses published (most recent first).",
            },
        },
        "additionalProperties": False,
    },
}

OBSIDIAN_WIKI_QUERY_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_wiki_query",
    "description": (
        "Retrieval-before-forecast: pull a question's second-brain context "
        "from the vault — its concept page plus one hop of its wikilink "
        "neighbourhood (cruxes, lessons/reference classes, theses, entities), "
        "operator annotations included. Give a question_id (preferred) or a "
        "free-text query. Bounded output."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question_id": {
                "type": "string",
                "description": "Ledger question id whose vault neighbourhood to pull.",
            },
            "query": {
                "type": "string",
                "description": "Free-text match on page titles/content (used when no question_id).",
            },
            "max_pages": {
                "type": "integer",
                "description": "Cap on returned pages (default 8).",
            },
        },
        "additionalProperties": False,
    },
}

OBSIDIAN_INGEST_NOTES_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_ingest_notes",
    "description": (
        "Ingest the operator's vault annotations as evidence — the vault→agent "
        "half of the collaboration loop. Detects operator-authored deltas via "
        "the manifest, triages each with the cheap labeler (staged as "
        "triage_labels), and imports keep/skim verdicts through add_evidence "
        "with provenance operator-note:<page> and the page's real modified "
        "time. Respects the triage trust gate: while suggest_only, skip-labeled "
        "notes are surfaced for review, never silently dropped. dry_run lists "
        "pending deltas without any writes or model spend."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dry_run": {
                "type": "boolean",
                "description": "List pending operator deltas without ingesting. Default false.",
            },
            "question_id": {
                "type": "string",
                "description": "Only ingest deltas mapped to this question.",
            },
            "model": {
                "type": "string",
                "description": "Model id for the cheap triage labeler (default $FORECAST_TRIAGE_MODEL or the house judge model).",
            },
        },
        "additionalProperties": False,
    },
}

OBSIDIAN_SYNC_LEARNINGS_SCHEMA: Dict[str, Any] = {
    "name": "obsidian_sync_learnings",
    "description": (
        "Publish the forecast desk's learnings into the Obsidian vault as "
        "linked notes: one note per calibration lesson, one dossier per "
        "question (description, current probability, analyst-note timeline), "
        "and a Forecast Desk Index. Idempotent — regenerated content lives "
        "between managed markers so human edits around it survive. The "
        "ledger DB stays the source of truth."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["all", "lessons", "questions"],
                "description": "What to publish. Default 'all'.",
            },
            "active_only": {
                "type": "boolean",
                "description": "Only publish lessons with status='active'. Default false.",
            },
            "question_status": {
                "type": "string",
                "description": "Question status filter (e.g. 'active', 'resolved'). Default 'active'.",
            },
            "limit": {
                "type": "integer",
                "description": "Cap on questions/lessons published (most recent first).",
            },
        },
        "additionalProperties": False,
    },
}


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def handle_obsidian_read_note(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    try:
        path = safe_note_path(vault, args.get("path", ""))
    except ValueError as e:
        return _err(str(e))
    if not path.is_file():
        return _err(f"note not found: {args.get('path')!r}", vault=str(vault))
    text = path.read_text(encoding="utf-8", errors="replace")
    truncated = len(text.encode("utf-8")) > _MAX_READ_BYTES
    if truncated:
        text = text[:_MAX_READ_BYTES]
    return _json(
        {
            "success": True,
            "path": str(path.relative_to(vault)),
            "content": text,
            "truncated": truncated,
        }
    )


def handle_obsidian_write_note(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    try:
        path = safe_note_path(vault, args.get("path", ""))
    except ValueError as e:
        return _err(str(e))
    if path.is_file() and not args.get("overwrite"):
        return _err(
            f"note already exists: {args.get('path')!r} — pass overwrite=true "
            "to replace it, or use obsidian_append_note"
        )
    frontmatter = args.get("frontmatter") or {}
    content = args.get("content", "")
    text = render_frontmatter(frontmatter) + content
    if not text.endswith("\n"):
        text += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return _json({"success": True, "path": str(path.relative_to(vault)), "bytes": len(text)})


def handle_obsidian_append_note(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    try:
        path = safe_note_path(vault, args.get("path", ""))
    except ValueError as e:
        return _err(str(e))
    content = (args.get("content") or "").rstrip("\n")
    if not content:
        return _err("content is required")
    heading = (args.get("heading") or "").strip()
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if heading and existing:
        lines = existing.splitlines()
        head_re = re.compile(rf"^#{{1,6}}\s+{re.escape(heading)}\s*$", re.IGNORECASE)
        start = next((i for i, ln in enumerate(lines) if head_re.match(ln)), None)
        if start is None:
            return _err(f"heading not found: {heading!r}", path=str(path.relative_to(vault)))
        end = next(
            (i for i in range(start + 1, len(lines)) if re.match(r"^#{1,6}\s", lines[i])),
            len(lines),
        )
        lines[end:end] = ["", content]
        new_text = "\n".join(lines).rstrip("\n") + "\n"
    else:
        base = existing.rstrip("\n")
        new_text = (base + "\n\n" if base else "") + content + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_text, encoding="utf-8")
    return _json({"success": True, "path": str(path.relative_to(vault)), "appended": len(content)})


def handle_obsidian_search(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    query = (args.get("query") or "").strip()
    if not query:
        return _err("query is required")
    kind = args.get("kind") or "content"
    root = vault
    folder = (args.get("folder") or "").strip()
    if folder:
        if Path(folder).is_absolute() or folder.startswith("~"):
            return _err("folder must be relative to the vault root")
        root = (vault / folder).resolve()
        if not root.is_relative_to(vault.resolve()):
            return _err(f"folder escapes the vault: {folder!r}")
        if not root.is_dir():
            return _err(f"folder not found: {folder!r}")
    matches: list[Dict[str, Any]] = []
    if kind == "files":
        needle = query.lower()
        for note in sorted(root.rglob("*.md")):
            if needle in note.stem.lower():
                matches.append({"path": str(note.relative_to(vault))})
                if len(matches) >= _MAX_SEARCH_RESULTS:
                    break
    else:
        try:
            pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            return _err(f"invalid regex: {e}")
        for note in sorted(root.rglob("*.md")):
            try:
                text = note.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(
                        {
                            "path": str(note.relative_to(vault)),
                            "line": lineno,
                            "snippet": line.strip()[:200],
                        }
                    )
                    if len(matches) >= _MAX_SEARCH_RESULTS:
                        break
            if len(matches) >= _MAX_SEARCH_RESULTS:
                break
    return _json(
        {
            "success": True,
            "kind": kind,
            "count": len(matches),
            "capped": len(matches) >= _MAX_SEARCH_RESULTS,
            "matches": matches,
        }
    )


def handle_obsidian_sync_learnings(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    from plugins.obsidian.sync import sync_learnings

    scope = args.get("scope") or "all"
    if scope not in ("all", "lessons", "questions"):
        return _err(f"invalid scope: {scope!r}")
    try:
        summary = sync_learnings(
            vault,
            scope=scope,
            active_only=bool(args.get("active_only")),
            question_status=args.get("question_status", "active") or None,
            limit=args.get("limit"),
        )
    except Exception as e:
        return _err(f"sync failed: {e}")
    return _json({"success": True, **summary})


def handle_obsidian_wiki_sync(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    from plugins.obsidian.wiki import sync_wiki

    try:
        summary = sync_wiki(
            vault,
            question_status=args.get("question_status", "active") or None,
            limit=args.get("limit"),
        )
    except Exception as e:
        return _err(f"wiki sync failed: {e}")
    return _json({"success": True, **summary})


_WIKI_QUERY_MAX_PAGES = 8
_WIKI_QUERY_MAX_CHARS = 4000


def handle_obsidian_wiki_query(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    question_id = (args.get("question_id") or "").strip()
    query = (args.get("query") or "").strip()
    if not question_id and not query:
        return _err("obsidian_wiki_query requires a question_id or a query")
    try:
        max_pages = int(args.get("max_pages") or _WIKI_QUERY_MAX_PAGES)
    except (TypeError, ValueError):
        max_pages = _WIKI_QUERY_MAX_PAGES
    max_pages = max(1, min(max_pages, 20))

    from plugins.obsidian.prune import scan_vault

    pages = [p for p in scan_vault(vault) if not p["tombstone"]]
    by_stem: Dict[str, Dict[str, Any]] = {}
    for page in pages:
        by_stem[page["path"].removesuffix(".md")] = page
        by_stem.setdefault(Path(page["path"]).stem, page)

    seeds: list[Dict[str, Any]] = []
    if question_id:
        for page in pages:
            front = page["front"]
            if front.get("question_id") == question_id or question_id in (
                front.get("provenance") or ""
            ):
                seeds.append(page)
    else:
        needle = query.lower()
        for page in pages:
            if needle in page["path"].lower() or needle in page["text"].lower():
                seeds.append(page)
    if not seeds:
        return _json(
            {"success": True, "count": 0, "pages": [],
             "note": "no vault pages matched — run obsidian_wiki_sync first?"}
        )

    ordered: list[Dict[str, Any]] = []
    seen: set[str] = set()

    def _add(page: Dict[str, Any]) -> None:
        if page["path"] not in seen and len(ordered) < max_pages:
            seen.add(page["path"])
            ordered.append(page)

    for seed in seeds:
        _add(seed)
    for seed in list(ordered):  # one hop of the wikilink neighbourhood
        for target in seed["links_out"]:
            neighbour = by_stem.get(target.strip())
            if neighbour is not None and neighbour["path"] != seed["path"]:
                _add(neighbour)

    results = [
        {
            "path": page["path"],
            "section": page["section"],
            "summary": page["front"].get("summary"),
            "status": page["front"].get("status"),
            "as_of": page["front"].get("as_of"),
            "content": page["text"][:_WIKI_QUERY_MAX_CHARS],
            "truncated": len(page["text"]) > _WIKI_QUERY_MAX_CHARS,
        }
        for page in ordered
    ]
    return _json({"success": True, "count": len(results), "pages": results})


def handle_obsidian_ingest_notes(args: Dict[str, Any], **_kw) -> str:
    vault, error = _vault_or_error()
    if error:
        return _err(error)
    from plugins.obsidian.ingest import ingest_operator_notes

    dry_run = bool(args.get("dry_run"))
    runner = None
    model = args.get("model")
    if not dry_run:
        import os

        from forecasting.quorum import DEFAULT_JUDGE_MODEL, make_aiagent_runner

        model = model or os.getenv("FORECAST_TRIAGE_MODEL") or DEFAULT_JUDGE_MODEL
        runner = make_aiagent_runner(toolsets=(), max_iterations=2, quiet=True, timeout=180)
    try:
        report = ingest_operator_notes(
            vault,
            runner=runner,
            model=model,
            question_id=(args.get("question_id") or "").strip() or None,
            dry_run=dry_run,
        )
    except Exception as e:
        return _err(f"ingest failed: {e}")
    return _json(
        {
            "success": True,
            **report,
            "note": (
                "Operator note deltas triaged through the trust gate: keep/skim landed as "
                "evidence (provenance operator-note:<page>, timestamped with the page's real "
                "modified time); needs_review items were labeled skip while the gate is "
                "suggest_only — adjudicate with relabel_route or edit the note."
            ),
        }
    )
