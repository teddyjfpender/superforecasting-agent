"""Gateway RPCs for the tools / toolsets family — carved from server.py.

Moves-only slice of the Wave-2 server family-split (docs/plans/2026-07-10-
modularization-program.md §W2.a). ``tools.list`` / ``tools.show`` /
``tools.configure`` / ``toolsets.list`` moved here VERBATIM. The local
``rpc_validated`` / ``method`` decorators capture handlers into ``_REGISTRARS``;
``server.py`` calls :func:`register` (at load AND on ``importlib.reload`` — the
pm_rpc/jobs_rpc sibling contract), replaying them through the REAL
``server.rpc_validated`` / ``server.method`` so registration lands in the same
``tui_gateway.server._methods`` dispatch dict — wire byte-identical.

The monkeypatched ``_load_enabled_toolsets`` and the mutable ``_sessions``
registry are reached via the ``_core.`` call-time hop. ``_reset_session_agent``
(session runtime, stays in core) and ``_ok`` / ``_err`` are imported bare.
"""
from __future__ import annotations

import tui_gateway.server as _core
from tui_gateway.server import _err, _ok, _reset_session_agent

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
    """(Re-)register every carved tools/toolsets handler into ``server._methods``."""
    global _core, _ok, _err, _reset_session_agent
    _core = server
    _ok = server._ok
    _err = server._err
    _reset_session_agent = server._reset_session_agent
    for kind, name, fn in _REGISTRARS:
        getattr(server, kind)(name)(fn)


__all__ = ["register"]


def _session_toolsets(params: dict):
    """Use a live agent's selection, or configured selection before its build."""
    from superforecasting_agent.tooling.inventory import session_toolset_selection
    return session_toolset_selection(
        _core._host.sessions.get(params.get("session_id", "")),
        _core._load_enabled_toolsets,
    )


@method("tools.list")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.tooling.inventory import toolset_inventory

        items = toolset_inventory(_session_toolsets(params))
        return _ok(rid, {"toolsets": items})
    except Exception as e:
        return _err(rid, 5031, str(e))


@method("tools.show")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.tooling.runtime import get_toolset_for_tool, get_tool_definitions

        enabled = _session_toolsets(params)
        tools = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True)
        sections = {}

        for tool in sorted(tools, key=lambda t: t["function"]["name"]):
            name = tool["function"]["name"]
            desc = str(tool["function"].get("description", "") or "").split("\n")[0]
            if ". " in desc:
                desc = desc[: desc.index(". ") + 1]
            sections.setdefault(get_toolset_for_tool(name) or "unknown", []).append(
                {
                    "name": name,
                    "description": desc,
                }
            )

        return _ok(
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
        return _err(rid, 5034, str(e))


@rpc_validated("tools.configure")
def _(rid, params: dict) -> dict:
    action = str(params.get("action", "") or "").strip().lower()
    targets = [
        str(name).strip() for name in params.get("names", []) or [] if str(name).strip()
    ]
    if action not in {"disable", "enable"}:
        return _err(rid, 4017, f"unknown tools action: {action}")
    if not targets:
        return _err(rid, 4018, "names required")

    try:
        from superforecasting_agent.runtime.config import load_config, save_config
        from superforecasting_agent.tooling.selection import change_tools, _get_platform_tools

        cfg = load_config()
        result = change_tools(cfg, "cli", targets, action)
        changed = result["changed"]
        unknown = result["unknown"] + result["restricted"]
        missing_servers = result["missing_servers"]
        if changed:
            save_config(cfg)

        session = _core._host.sessions.get(params.get("session_id", ""))
        info = (
            _reset_session_agent(params.get("session_id", ""), session)
            if session and changed
            else None
        )
        enabled = sorted(
            _get_platform_tools(load_config(), "cli", include_default_mcp_servers=False)
        )

        return _ok(
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
    except Exception as e:
        return _err(rid, 5035, str(e))


@method("toolsets.list")
@method("superforecasting_agent.tooling.toolsets.list")
def _(rid, params: dict) -> dict:
    try:
        from superforecasting_agent.tooling.inventory import toolset_inventory

        items = [
            {key: value for key, value in item.items() if key != "tools"}
            for item in toolset_inventory(_session_toolsets(params))
        ]
        return _ok(rid, {"toolsets": items})
    except Exception as e:
        return _err(rid, 5032, str(e))
