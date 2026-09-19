"""Cron and skills RPC adapters bound to an admitted host and explicit services."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.rpc_binding import ErrorResponse, Registrar, bind_host_handler


@dataclass(frozen=True)
class CronSkillsContext:
    host: Callable[[], RuntimeHost]
    cron: Callable[..., str]
    available_skills: Callable[[], dict[str, list[str]]]
    search: Callable[[str], list[dict[str, str]]]
    install: Callable[[str], bool]
    browse: Callable[[int, int], dict[str, Any]]
    inspect: Callable[[str], dict[str, Any] | None]
    reload: Callable[[], dict[str, Any]]
    ok: Callable[[Any, dict[str, Any]], dict[str, Any]]
    error: ErrorResponse


def register_handlers(context: CronSkillsContext, *, method: Registrar) -> None:
    for name, handler in (
        ("cron.manage", manage_cron),
        ("skills.manage", manage_skills),
        ("skills.reload", reload_skills),
    ):
        method(name)(
            bind_host_handler(
                context.host,
                context.error,
                lambda owner, rid, params, operation=handler: operation(
                    context, rid, params
                ),
            )
        )


def register(server) -> None:
    """Compose legacy singleton services; independent hosts inject scoped services."""
    context = CronSkillsContext(
        host=lambda: server._host,
        cron=_cron,
        available_skills=_available,
        search=_search,
        install=_install,
        browse=_browse,
        inspect=_inspect,
        reload=_reload,
        ok=lambda rid, result: server._ok(rid, result),
        error=lambda rid, code, message: server._err(rid, code, message),
    )
    register_handlers(context, method=server.method)


def _search(query: str) -> list[dict[str, str]]:
    from tools.skills_hub import GitHubAuth, create_source_router, unified_search

    results = (
        unified_search(
            query, create_source_router(GitHubAuth()), source_filter="all", limit=20
        )
        or []
    )
    return [
        {"name": result.name, "description": result.description} for result in results
    ]


def _install(query: str) -> bool:
    from rich.console import Console

    from superforecasting_agent.runtime.skills_hub import do_install

    return do_install(query, skip_confirm=True, console=Console(quiet=True)) is True


def _cron(**kwargs: Any) -> str:
    from tools.cronjob_tools import cronjob

    return cronjob(**kwargs)


def _available() -> dict[str, list[str]]:
    from superforecasting_agent.runtime.banner import get_available_skills

    return get_available_skills()


def _browse(page: int, size: int) -> dict[str, Any]:
    from superforecasting_agent.runtime.skills_hub import browse_skills

    return browse_skills(page=page, page_size=size)


def _inspect(query: str) -> dict[str, Any] | None:
    from superforecasting_agent.runtime.skills_hub import inspect_skill

    return inspect_skill(query)


def _reload() -> dict[str, Any]:
    from agent.skill_commands import reload_skills

    return reload_skills()


def manage_cron(
    context: CronSkillsContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    action, jid = params.get("action", "list"), params.get("name", "")
    try:
        if action == "list":
            return context.ok(rid, json.loads(context.cron(action="list")))
        if action == "add":
            return context.ok(
                rid,
                json.loads(
                    context.cron(
                        action="create",
                        name=jid,
                        schedule=params.get("schedule", ""),
                        prompt=params.get("prompt", ""),
                    )
                ),
            )
        if action in {"remove", "pause", "resume"}:
            return context.ok(rid, json.loads(context.cron(action=action, job_id=jid)))
        return context.error(rid, 4016, f"unknown cron action: {action}")
    except Exception as e:
        return context.error(rid, 5023, str(e))


def manage_skills(
    context: CronSkillsContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    action, query = params.get("action", "list"), params.get("query", "")
    try:
        if action == "list":
            return context.ok(rid, {"skills": context.available_skills()})
        if action == "search":
            return context.ok(rid, {"results": context.search(query)})
        if action == "install":
            return context.ok(rid, {"installed": context.install(query), "name": query})
        if action == "browse":
            pg = int(params.get("page", 0) or 0) or (
                int(query) if query.isdigit() else 1
            )
            return context.ok(rid, context.browse(pg, int(params.get("page_size", 20))))
        if action == "inspect":
            return context.ok(rid, {"info": context.inspect(query) or {}})
        return context.error(rid, 4017, f"unknown skills action: {action}")
    except Exception as e:
        return context.error(rid, 5024, str(e))


def reload_skills(
    context: CronSkillsContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        result = context.reload()
        added = result.get("added") or []
        removed = result.get("removed") or []
        total = int(result.get("total") or 0)

        lines = ["Reloading skills..."]
        if not added and not removed:
            lines.append("No new skills detected.")
        if added:
            lines.append("Added skills:")
            lines.extend(f"  - {item.get('name', '')}" for item in added)
        if removed:
            lines.append("Removed skills:")
            lines.extend(f"  - {item.get('name', '')}" for item in removed)
        lines.append(f"{total} skill(s) available")
        return context.ok(rid, {"output": "\n".join(lines), "result": result})
    except Exception as e:
        return context.error(rid, 5025, str(e))
