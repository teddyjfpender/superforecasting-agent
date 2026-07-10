"""Gateway RPCs for the Obsidian vault plane — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). Every ``obsidian.*`` handler body moved here
VERBATIM. The local ``rpc_validated`` / ``method`` decorators only CAPTURE the
handlers into ``_REGISTRARS``; ``server.py`` calls :func:`register` (at load AND
on ``importlib.reload`` — the pm_rpc/jobs_rpc sibling contract), which replays
them through the REAL ``server.rpc_validated`` / ``server.method`` so the
registration lands in the same ``tui_gateway.server._methods`` dispatch dict and
the wire stays byte-identical.

The handlers delegate to :mod:`plugins.obsidian`; they reference only ``_ok`` /
``_err`` from core (neither is monkeypatched), so no ``_core.`` hop is needed.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from tui_gateway.server import _err, _ok

# Handlers captured at import; replayed into the gateway by register() so they
# survive a server module reload (server's own @rpc_validated re-runs on reload,
# but a carved module is imported once — register() is the re-entrant seam).
_REGISTRARS: list[tuple[str, str, object]] = []


def rpc_validated(name: str):
    def _dec(fn):
        _REGISTRARS.append(("rpc_validated", name, fn))
        return fn

    return _dec


def method(name: str):
    def _dec(fn):
        _REGISTRARS.append(("method", name, fn))
        return fn

    return _dec


def register(server) -> None:
    """(Re-)register every carved obsidian handler into ``server._methods``."""
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]


@rpc_validated("obsidian.status")
def _(rid, params: dict) -> dict:
    """Vault status + a list of the desk's notes for the Obsidian view.

    The ledger is the source of truth; the vault is a published view. This
    enumerates the vault's markdown notes (Forecasting/ first, then most-recent),
    with a title + one-line excerpt, so the TUI can browse the write-ups and
    dossiers the agent has synced. Bounded to keep the payload small.
    """
    try:
        import re

        from plugins.obsidian.vault import resolve_vault_path

        vault = resolve_vault_path()
        if vault is None:
            return _ok(rid, {"vault": None, "exists": False, "count": 0, "notes": []})

        limit = int(params.get("limit") or 200)
        md_files: list[Path] = []
        for root, dirs, files in os.walk(vault):
            dirs[:] = [d for d in dirs if not d.startswith(".")]  # skip .obsidian etc.
            for name in files:
                if name.endswith(".md"):
                    md_files.append(Path(root) / name)

        def _sort_key(p: Path):
            try:
                rel = p.relative_to(vault)
                mtime = p.stat().st_mtime
            except OSError:
                return (2, 0.0)
            forecasting_first = 0 if str(rel).startswith("Forecasting") else 1
            return (forecasting_first, -mtime)

        md_files.sort(key=_sort_key)

        notes: list[dict] = []
        for p in md_files[:limit]:
            try:
                rel = p.relative_to(vault)
                st = p.stat()
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            title = p.stem
            excerpt = ""
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    if title == p.stem:
                        title = stripped.lstrip("#").strip() or title
                    continue
                if stripped.startswith(("---", "```", ">", "<!--")):
                    continue
                excerpt = stripped[:160]
                break
            folder = str(rel.parent) if str(rel.parent) != "." else ""
            # Extract [[wikilink]] targets (drop |alias and #heading) so the
            # client can build the outgoing/backlink graph without extra reads.
            links: list[str] = []
            seen_links: set[str] = set()
            for m in re.finditer(r"\[\[([^\]\n]+)\]\]", text):
                target = m.group(1).split("|", 1)[0].split("#", 1)[0].strip()
                key = target.lower()
                if target and key not in seen_links:
                    seen_links.add(key)
                    links.append(target)
            notes.append(
                {
                    "title": title,
                    "rel_path": str(rel),
                    "folder": folder,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "size": st.st_size,
                    "excerpt": excerpt,
                    "links": links,
                }
            )

        return _ok(rid, {"vault": str(vault), "exists": True, "count": len(md_files), "notes": notes})
    except Exception as e:
        return _err(rid, 5009, str(e))


@method("obsidian.setup")
def _(rid, params: dict) -> dict:
    """Create the vault (if needed) and seed the starter forecasting wiki.

    Targets OBSIDIAN_VAULT_PATH when set, else the managed workspace vault
    (~/.superforecasting-agent/docs/vault). Seeding never overwrites existing
    notes, so this is safe to run repeatedly.
    """
    try:
        from plugins.obsidian.starter import seed_starter_vault
        from plugins.obsidian.vault import managed_vault_path

        configured = os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
        target = Path(configured).expanduser() if configured else managed_vault_path()
        target.mkdir(parents=True, exist_ok=True)
        result = seed_starter_vault(target)
        return _ok(
            rid,
            {
                "ok": True,
                "vault": str(target),
                "created": result["created"],
                "skipped": result["skipped"],
            },
        )
    except Exception as e:
        return _err(rid, 5010, str(e))


@rpc_validated("obsidian.note")
def _(rid, params: dict) -> dict:
    """Read one vault note's content for the Obsidian view's reading pane."""
    try:
        from plugins.obsidian.vault import resolve_vault_path, safe_note_path

        vault = resolve_vault_path()
        if vault is None:
            return _err(rid, 5011, "no Obsidian vault configured")
        rel = str(params.get("rel_path") or "").strip()
        if not rel:
            return _err(rid, 5011, "rel_path is required")
        path = safe_note_path(vault, rel)  # refuses paths escaping the vault
        if not path.is_file():
            return _err(rid, 5011, f"note not found: {rel}")
        text = path.read_text(encoding="utf-8", errors="replace")
        max_chars = 80_000
        truncated = len(text) > max_chars
        return _ok(
            rid,
            {
                "rel_path": rel,
                "content": text[:max_chars],
                "truncated": truncated,
                "size": path.stat().st_size,
            },
        )
    except Exception as e:
        return _err(rid, 5011, str(e))


@method("obsidian.create")
def _(rid, params: dict) -> dict:
    """Create a new note (refuses to clobber an existing one)."""
    try:
        from plugins.obsidian.vault import resolve_vault_path, safe_note_path, write_note

        vault = resolve_vault_path()
        if vault is None:
            return _err(rid, 5012, "no Obsidian vault configured")
        rel = str(params.get("rel_path") or "").strip()
        if not rel:
            return _err(rid, 5012, "rel_path is required")
        path = safe_note_path(vault, rel)
        if path.exists():
            return _err(rid, 5012, f"note already exists: {path.relative_to(vault)}")
        title = str(params.get("title") or path.stem).strip()
        body = str(params.get("content") or f"---\ntags: [forecasting]\ntype: note\n---\n\n# {title}\n\n")
        write_note(path, body)
        return _ok(rid, {"ok": True, "rel_path": str(path.relative_to(vault))})
    except Exception as e:
        return _err(rid, 5012, str(e))


@method("obsidian.append")
def _(rid, params: dict) -> dict:
    """Append text (a comment / note) to an existing note."""
    try:
        from plugins.obsidian.vault import resolve_vault_path, safe_note_path, write_note

        vault = resolve_vault_path()
        if vault is None:
            return _err(rid, 5013, "no Obsidian vault configured")
        rel = str(params.get("rel_path") or "").strip()
        text = str(params.get("text") or "").strip()
        if not rel or not text:
            return _err(rid, 5013, "rel_path and text are required")
        path = safe_note_path(vault, rel)
        if not path.is_file():
            return _err(rid, 5013, f"note not found: {rel}")
        existing = path.read_text(encoding="utf-8", errors="replace").rstrip("\n")
        write_note(path, f"{existing}\n\n{text}\n")
        return _ok(rid, {"ok": True, "rel_path": rel})
    except Exception as e:
        return _err(rid, 5013, str(e))


@method("obsidian.write")
def _(rid, params: dict) -> dict:
    """Overwrite a note's full content (used by the in-pane editor's autosave)."""
    try:
        from plugins.obsidian.vault import resolve_vault_path, safe_note_path, write_note

        vault = resolve_vault_path()
        if vault is None:
            return _err(rid, 5014, "no Obsidian vault configured")
        rel = str(params.get("rel_path") or "").strip()
        content = params.get("content")
        if not rel or not isinstance(content, str):
            return _err(rid, 5014, "rel_path and string content are required")
        path = safe_note_path(vault, rel)
        write_note(path, content)
        return _ok(rid, {"ok": True, "rel_path": rel, "size": len(content.encode("utf-8"))})
    except Exception as e:
        return _err(rid, 5014, str(e))


@rpc_validated("obsidian.search")
def _(rid, params: dict) -> dict:
    """Ranked full-text search across the vault for the TUI search modal.

    Scores each note by weighted term frequency (title > headings > body) so
    the most relevant notes float to the top, with the best-matching line as a
    snippet. This is lexical, not vector-semantic — there is no embedding
    service wired in — but multi-term weighted ranking gets most of the way for
    a knowledge base of this size. (A future obsidian.search could add a
    semantic mode if embeddings become available.)
    """
    try:
        import re

        from plugins.obsidian.vault import resolve_vault_path

        vault = resolve_vault_path()
        if vault is None:
            return _err(rid, 5015, "no Obsidian vault configured")

        query = str(params.get("query") or "").strip()
        if not query:
            return _ok(rid, {"query": query, "count": 0, "results": []})

        limit = max(1, min(int(params.get("limit") or 30), 100))
        terms = [t for t in re.split(r"\s+", query.lower()) if t]

        results: list[dict] = []
        for path in vault.rglob("*.md"):
            parts = path.relative_to(vault).parts
            if any(p.startswith(".") for p in parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            lines = text.splitlines()
            title = path.stem
            for line in lines:
                s = line.strip()
                if s.startswith("#"):
                    title = s.lstrip("#").strip() or title
                    break

            low = text.lower()
            title_low = title.lower()
            heading_low = "\n".join(s.lstrip("#").strip().lower() for s in lines if s.strip().startswith("#"))

            score = 0
            matched_terms = 0
            for term in terms:
                t_body = low.count(term)
                if t_body == 0 and term not in title_low:
                    continue
                matched_terms += 1
                score += title_low.count(term) * 6
                score += heading_low.count(term) * 3
                score += t_body
            if matched_terms == 0:
                continue
            # Require all terms for multi-term queries to win the top slots, but
            # still surface partial matches below them.
            if matched_terms == len(terms):
                score += 10

            # Best snippet: the first line containing any term.
            snippet = ""
            sn_line = 0
            for lineno, line in enumerate(lines, start=1):
                ll = line.lower()
                if any(term in ll for term in terms):
                    snippet = line.strip()[:160]
                    sn_line = lineno
                    break

            results.append(
                {
                    "rel_path": str(path.relative_to(vault)),
                    "title": title,
                    "score": score,
                    "matched_terms": matched_terms,
                    "snippet": snippet,
                    "line": sn_line,
                }
            )

        results.sort(key=lambda r: (-r["score"], r["rel_path"]))
        return _ok(rid, {"query": query, "count": len(results), "results": results[:limit]})
    except Exception as e:
        return _err(rid, 5015, str(e))
