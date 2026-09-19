"""Tool inspection and configuration bound to explicit runtime capabilities."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from superforecasting_agent.hosting.runtime import RuntimeHost
from superforecasting_agent.hosting.sessions import SessionBusy
from tui_gateway.rpc_binding import (
    ErrorResponse,
    Registrar,
    RpcHandler,
    bind_host_handler,
)


class ResetSession(Protocol):
    def __call__(
        self, sid: str, session: dict[str, Any], *, reserved: bool = False
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolContext:
    host: Callable[[], RuntimeHost]
    enabled_toolsets: Callable[[], list[str] | None]
    load_config: Callable[[], dict[str, Any]]
    save_config: Callable[[dict[str, Any]], None]
    reset_session: ResetSession
    ok: Callable[[Any, dict[str, Any]], dict[str, Any]]
    error: ErrorResponse


def register_handlers(
    context: ToolContext, *, method: Registrar, rpc_validated: Registrar
) -> None:
    def bind(
        handler: Callable[[ToolContext, Any, dict[str, Any]], dict[str, Any]],
    ) -> RpcHandler:
        return bind_host_handler(
            context.host,
            context.error,
            lambda owner, rid, params: handler(
                replace(context, host=lambda: owner), rid, params
            ),
        )

    method("tools.list")(bind(tools_list))
    method("tools.show")(bind(tools_show))
    rpc_validated("tools.configure")(bind(tools_configure))
    method("toolsets.list")(bind(toolsets_list))
    method("superforecasting_agent.tooling.toolsets.list")(bind(toolsets_list))


def register(server) -> None:
    """Legacy singleton composition; no handler globals are rebound."""
    from superforecasting_agent.runtime import config

    context = ToolContext(
        host=lambda: server._host,
        enabled_toolsets=lambda: server._load_enabled_toolsets(),
        load_config=lambda: config.load_config(),
        save_config=lambda cfg: config.save_config(cfg),
        reset_session=lambda sid, session, *, reserved=False: (
            server._reset_session_agent(sid, session, reserved=reserved)
        ),
        ok=lambda rid, result: server._ok(rid, result),
        error=lambda rid, code, message: server._err(rid, code, message),
    )
    register_handlers(context, method=server.method, rpc_validated=server.rpc_validated)


__all__ = ["ToolContext", "register", "register_handlers"]


def _session_toolsets(
    context: ToolContext, params: dict[str, Any]
) -> Sequence[str] | None:
    """Use a live agent's selection, or configured selection before its build."""
    from superforecasting_agent.tooling.inventory import session_toolset_selection

    return session_toolset_selection(
        context.host().sessions.get(params.get("session_id", "")),
        context.enabled_toolsets,
    )


def tools_list(
    context: ToolContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from superforecasting_agent.tooling.inventory import toolset_inventory

        items = toolset_inventory(_session_toolsets(context, params))
        return context.ok(rid, {"toolsets": items})
    except Exception as e:
        return context.error(rid, 5031, str(e))


def tools_show(
    context: ToolContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from superforecasting_agent.tooling.runtime import (
            get_tool_definitions,
            get_toolset_for_tool,
        )

        enabled = _session_toolsets(context, params)
        tools = get_tool_definitions(
            enabled_toolsets=list(enabled) if enabled is not None else None,
            quiet_mode=True,
        )
        sections = {}

        for tool in sorted(tools, key=lambda t: t["function"]["name"]):
            name = tool["function"]["name"]
            desc = str(tool["function"].get("description", "") or "").split("\n")[0]
            if ". " in desc:
                desc = desc[: desc.index(". ") + 1]
            sections.setdefault(get_toolset_for_tool(name) or "unknown", []).append({
                "name": name,
                "description": desc,
            })

        return context.ok(
            rid,
            {
                "sections": [
                    {"name": name, "tools": rows}
                    for name, rows in sorted(sections.items())
                ],
                "total": len(tools),
            },
        )
    except Exception as e:
        return context.error(rid, 5034, str(e))


def tools_configure(
    context: ToolContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    from superforecasting_agent.tooling.selection import normalize_tool_names

    action = params.get("action")
    if isinstance(action, str):
        action = action.strip().lower()
    if not isinstance(action, str) or action not in {"disable", "enable"}:
        return context.error(rid, 4017, f"unknown tools action: {action}")
    try:
        targets = normalize_tool_names(params.get("names"))
    except ValueError as exc:
        return context.error(rid, 4018, str(exc))

    session = context.host().sessions.get(params.get("session_id", ""))
    if params.get("session_id") and session is None:
        return context.error(rid, 4001, "session not found")

    try:
        from superforecasting_agent.tooling.selection import (
            _get_platform_tools,
            change_tools,
        )

        cfg = context.load_config()
        result = change_tools(cfg, "cli", targets, action)
        changed = result["changed"]
        unknown = result["unknown"] + result["restricted"]
        missing_servers = result["missing_servers"]
        info = None
        if changed:
            from contextlib import ExitStack

            from superforecasting_agent.hosting.sessions import replacement

            with ExitStack() as reservation:
                # Own admission rather than the dispatcher's ordinary use lease:
                # that lease would make this request reject its own replacement.
                with context.host().sessions.lock:
                    if (
                        context.host().sessions.get(params.get("session_id", ""))
                        is not session
                    ):
                        raise SessionBusy(
                            "session changed before tool configuration could be applied"
                        )
                    if session is not None:
                        reservation.enter_context(replacement(session))
                context.save_config(cfg)
                if session is not None:
                    try:
                        info = context.reset_session(
                            params.get("session_id", ""), session, reserved=True
                        )
                    except Exception as exc:
                        raise RuntimeError(
                            "Tool configuration saved, but session reset failed; "
                            "close or recreate the session to recover. " + str(exc)
                        ) from exc
        enabled = sorted(
            _get_platform_tools(
                context.load_config(), "cli", include_default_mcp_servers=False
            )
        )

        return context.ok(
            rid,
            {
                "changed": changed,
                "enabled_toolsets": enabled,
                "info": info,
                "missing_servers": sorted(missing_servers),
                "reset": bool(session and changed),
                "unknown": unknown,
            },
        )
    except SessionBusy:
        raise
    except Exception as e:
        return context.error(rid, 5035, str(e))


def toolsets_list(
    context: ToolContext, rid: Any, params: dict[str, Any]
) -> dict[str, Any]:
    try:
        from superforecasting_agent.tooling.inventory import toolset_inventory

        items = [
            {key: value for key, value in item.items() if key != "tools"}
            for item in toolset_inventory(_session_toolsets(context, params))
        ]
        return context.ok(rid, {"toolsets": items})
    except Exception as e:
        return context.error(rid, 5032, str(e))
