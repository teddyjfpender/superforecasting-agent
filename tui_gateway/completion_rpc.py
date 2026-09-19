"""Completion and paste RPCs bound to one host's explicit capabilities."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import count
from pathlib import Path
from typing import Any

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.rpc_binding import (
    ErrorResponse,
    Registrar,
    RpcHandler,
    bind_host_handler,
)


@dataclass(frozen=True)
class CompletionContext:
    host: Callable[[], RuntimeHost]
    home: Callable[[], Path]
    cwd: Callable[[], str]
    list_repo_files: Callable[[str], list[str]]
    fuzzy_basename_rank: Callable[[str, str], tuple[int, int] | None]
    normalize_path: Callable[[str], str]
    details: Callable[[str], list[dict[str, Any]] | None]
    skill_commands: Callable[[], dict[str, dict[str, Any]]]
    skill_bundles: Callable[[], dict[str, dict[str, Any]]]
    ok: Callable[[Any, dict[str, Any]], dict[str, Any]]
    error: ErrorResponse
    paste_numbers: Iterator[int] = field(default_factory=lambda: count(1))


def register_handlers(
    context: CompletionContext, *, method: Registrar, rpc_validated: Registrar
) -> None:
    def bind(
        handler: Callable[[CompletionContext, Any, dict[str, Any]], dict[str, Any]],
    ) -> RpcHandler:
        return bind_host_handler(
            context.host,
            context.error,
            lambda owner, rid, params: handler(context, rid, params),
        )

    method("paste.collapse")(bind(collapse_paste))
    rpc_validated("complete.path")(bind(complete_path))
    rpc_validated("complete.slash")(bind(complete_slash))


def register(server) -> None:
    """Legacy singleton composition, including its existing call-time reload hooks."""
    from agent.skill_bundles import get_skill_bundles
    from agent.skill_commands import get_skill_commands

    context = CompletionContext(
        host=lambda: server._host,
        home=lambda: server._agent_home,
        cwd=os.getcwd,
        list_repo_files=lambda root: server._list_repo_files(root),
        fuzzy_basename_rank=lambda name, query: server._fuzzy_basename_rank(
            name, query
        ),
        normalize_path=lambda path: server._normalize_completion_path(path),
        details=lambda text: server._details_completions(text),
        skill_commands=get_skill_commands,
        skill_bundles=get_skill_bundles,
        ok=lambda rid, result: server._ok(rid, result),
        error=lambda rid, code, message: server._err(rid, code, message),
    )
    register_handlers(context, method=server.method, rpc_validated=server.rpc_validated)


def collapse_paste(
    context: CompletionContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    text = params.get("text", "")
    if not text:
        return context.error(rid, 4004, "empty paste")
    number = next(context.paste_numbers)
    line_count = text.count("\n") + 1
    paste_dir = context.home() / "pastes"
    paste_dir.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects separate hosts/restarts, even in the same profile.
    paste_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=paste_dir,
            prefix=f"paste_{number}_",
            suffix=".txt",
            delete=False,
        ) as stream:
            paste_file = Path(stream.name)
            stream.write(text)
            stream.flush()
    except BaseException:
        if paste_file is not None:
            paste_file.unlink(missing_ok=True)
        raise
    return context.ok(
        rid,
        {
            "placeholder": f"[Pasted text #{number}: {line_count} lines → {paste_file}]",
            "path": str(paste_file),
            "lines": line_count,
        },
    )


def complete_path(
    context: CompletionContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    word = params.get("word", "")
    if not word:
        return context.ok(rid, {"items": []})

    items: list[dict] = []
    try:
        is_context = word.startswith("@")
        query = word[1:] if is_context else word

        if is_context and not query:
            items = [
                {"text": "@diff", "display": "@diff", "meta": "git diff"},
                {"text": "@staged", "display": "@staged", "meta": "staged diff"},
                {"text": "@file:", "display": "@file:", "meta": "attach file"},
                {"text": "@folder:", "display": "@folder:", "meta": "attach folder"},
                {"text": "@url:", "display": "@url:", "meta": "fetch url"},
                {"text": "@git:", "display": "@git:", "meta": "git log"},
            ]
            return context.ok(rid, {"items": items})

        # Accept both `@folder:path` and the bare `@folder` form so the user
        # sees directory listings as soon as they finish typing the keyword,
        # without first accepting the static `@folder:` hint.
        if is_context and query in {"file", "folder"}:
            prefix_tag, path_part = query, ""
        elif is_context and query.startswith(("file:", "folder:")):
            prefix_tag, _, tail = query.partition(":")
            path_part = tail
        else:
            prefix_tag = ""
            path_part = query if is_context else query

        # Fuzzy basename search across the repo when the user types a bare
        # name with no path separator — `@appChrome` surfaces every file
        # whose basename matches, regardless of directory depth. Matches what
        # editors like Cursor / VS Code do for Cmd-P. Path-ish queries (with
        # `/`, `./`, `~/`, `/abs`) fall through to the directory-listing
        # path so explicit navigation intent is preserved.
        if is_context and path_part and "/" not in path_part and prefix_tag != "folder":
            root = context.cwd()
            ranked: list[tuple[tuple[int, int], str, str]] = []
            for rel in context.list_repo_files(root):
                basename = os.path.basename(rel)
                if basename.startswith(".") and not path_part.startswith("."):
                    continue
                rank = context.fuzzy_basename_rank(basename, path_part)
                if rank is None:
                    continue
                ranked.append((rank, rel, basename))

            ranked.sort(key=lambda r: (r[0], len(r[1]), r[1]))
            tag = prefix_tag or "file"
            for _, rel, basename in ranked[:30]:
                items.append({
                    "text": f"@{tag}:{rel}",
                    "display": basename,
                    "meta": os.path.dirname(rel),
                })

            return context.ok(rid, {"items": items})

        expanded = context.normalize_path(path_part) if path_part else "."
        if expanded == "." or not expanded:
            search_dir, match = ".", ""
        elif expanded.endswith("/"):
            search_dir, match = expanded, ""
        else:
            search_dir = os.path.dirname(expanded) or "."
            match = os.path.basename(expanded)

        root = context.cwd()
        search_dir = os.path.join(root, search_dir)
        if not os.path.isdir(search_dir):
            return context.ok(rid, {"items": []})

        want_dir = prefix_tag == "folder"
        match_lower = match.lower()
        for entry in sorted(os.listdir(search_dir)):
            if match and not entry.lower().startswith(match_lower):
                continue
            if is_context and not prefix_tag and entry.startswith("."):
                continue
            full = os.path.join(search_dir, entry)
            is_dir = os.path.isdir(full)
            # Explicit `@folder:` / `@file:` — honour the user's filter.  Skip
            # the opposite kind instead of auto-rewriting the completion tag,
            # which used to defeat the prefix and let `@folder:` list files.
            if prefix_tag and want_dir != is_dir:
                continue
            rel = os.path.relpath(full, root)
            suffix = "/" if is_dir else ""

            if is_context and prefix_tag:
                text = f"@{prefix_tag}:{rel}{suffix}"
            elif is_context:
                kind = "folder" if is_dir else "file"
                text = f"@{kind}:{rel}{suffix}"
            elif word.startswith("~"):
                text = "~/" + os.path.relpath(full, os.path.expanduser("~")) + suffix
            elif word.startswith("./"):
                text = "./" + rel + suffix
            else:
                text = rel + suffix

            items.append({
                "text": text,
                "display": entry + suffix,
                "meta": "dir" if is_dir else "",
            })
            if len(items) >= 30:
                break
    except Exception as e:
        return context.error(rid, 5021, str(e))

    return context.ok(rid, {"items": items})


def complete_slash(
    context: CompletionContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    text = params.get("text", "")
    if not text.startswith("/"):
        return context.ok(rid, {"items": []})

    try:
        from prompt_toolkit.document import Document
        from prompt_toolkit.formatted_text import to_plain_text

        from superforecasting_agent.runtime.commands import SlashCommandCompleter

        completer = SlashCommandCompleter(
            skill_commands_provider=context.skill_commands,
            skill_bundles_provider=context.skill_bundles,
        )
        doc = Document(text, len(text))
        items = [
            {
                "text": c.text,
                "display": to_plain_text(c.display) if c.display else c.text,
                "meta": to_plain_text(c.display_meta) if c.display_meta else "",
            }
            for c in completer.get_completions(doc, None)
        ][:30]
        text_lower = text.lower()
        extras = [
            {
                "text": "/compact",
                "display": "/compact",
                "meta": "Toggle compact display mode",
            },
            {
                "text": "/details",
                "display": "/details",
                "meta": "Control agent detail visibility",
            },
            {
                "text": "/logs",
                "display": "/logs",
                "meta": "Show recent gateway log lines",
            },
            {
                "text": "/mouse",
                "display": "/mouse",
                "meta": "Toggle mouse/wheel tracking [on|off|toggle]",
            },
            # TUI-native commands handled by the Ink slash registry (not the
            # superforecasting_agent.runtime completer catalog) — list them here so they're
            # discoverable in the composer's autocomplete.
            {
                "text": "/theme",
                "display": "/theme",
                "meta": "Pick a color theme (interactive picker, live preview)",
            },
            {
                "text": "/auth",
                "display": "/auth",
                "meta": "Sign in to an AI provider without leaving the TUI",
            },
            {
                "text": "/panel",
                "display": "/panel",
                "meta": "Multi-perspective forecast panel (outside/inside/market/red-team/sanity)",
            },
            {
                "text": "/bayes",
                "display": "/bayes",
                "meta": "Auditable Bayesian scratchpad (priors, likelihood ratios, pooling)",
            },
            {
                "text": "/calibration",
                "display": "/calibration",
                "meta": "Calibration analytics; /calibration --visual for the reliability view",
            },
        ]
        for extra in extras:
            if extra["text"].startswith(text_lower) and not any(
                item["text"] == extra["text"] for item in items
            ):
                items.append(extra)

        details_items = context.details(text)
        if details_items is not None:
            return context.ok(
                rid,
                {
                    "items": details_items,
                    "replace_from": text.rfind(" ") + 1 if " " in text else len(text),
                },
            )

        return context.ok(
            rid,
            {"items": items, "replace_from": text.rfind(" ") + 1 if " " in text else 1},
        )
    except Exception as e:
        return context.error(rid, 5020, str(e))
