"""Resolve startup tool choices independently of terminal presentation."""

from collections.abc import Callable
from typing import Any


def resolve_startup_toolsets(
    explicit_value: str,
    *,
    setting_label: str,
    warn: Callable[[str], None],
    config: dict[str, Any] | None = None,
) -> list[str] | None:
    explicit = [item.strip() for item in explicit_value.split(",") if item.strip()]
    fallback_notice = None

    validate_toolset: Callable[[str], bool] | None
    try:
        from superforecasting_agent.tooling.toolsets import (
            validate_toolset as validator,
        )

        validate_toolset = validator
    except Exception:
        validate_toolset = None

    if explicit and validate_toolset is not None:
        built_in = [name for name in explicit if validate_toolset(name)]
        unresolved = [name for name in explicit if name not in built_in]

        if unresolved:
            try:
                from superforecasting_agent.runtime.plugins import discover_plugins

                discover_plugins()
                plugin_valid = [name for name in unresolved if validate_toolset(name)]
            except Exception:
                plugin_valid = []

            if plugin_valid:
                built_in.extend(plugin_valid)
                unresolved = [name for name in unresolved if name not in plugin_valid]

        if any(name in {"all", "*"} for name in built_in):
            ignored = [name for name in explicit if name not in {"all", "*"}]
            if ignored:
                warn(
                    f"{setting_label}=all enables every toolset; "
                    f"ignoring additional entries: {', '.join(ignored)}",
                )
            return None

        if not unresolved:
            return built_in

        mcp_names: set[str] = set()
        mcp_disabled: set[str] = set()
        try:
            from superforecasting_agent.runtime.config import read_raw_config
            from superforecasting_agent.tooling.selection import _parse_enabled_flag

            raw_cfg = config if config is not None else read_raw_config()
            mcp_servers = raw_cfg.get("mcp_servers")
            if not isinstance(mcp_servers, dict):
                mcp_servers = {}
            for name, server_cfg in mcp_servers.items():
                if not isinstance(server_cfg, dict):
                    continue
                if _parse_enabled_flag(server_cfg.get("enabled", True), default=True):
                    mcp_names.add(str(name))
                else:
                    mcp_disabled.add(str(name))
        except Exception:
            mcp_names = set()
            mcp_disabled = set()

        mcp_valid = [name for name in unresolved if name in mcp_names]
        disabled = [name for name in unresolved if name in mcp_disabled]
        unknown = [
            name
            for name in unresolved
            if name not in mcp_names and name not in mcp_disabled
        ]
        valid = built_in + mcp_valid

        if unknown:
            warn(
                f"ignoring unknown {setting_label} entries: {', '.join(unknown)}",
            )
        if disabled:
            warn(
                f"ignoring disabled MCP servers in {setting_label} "
                "(set enabled: true in config.yaml to use): "
                f"{', '.join(disabled)}",
            )

        if valid:
            return valid

        fallback_notice = (
            f"no valid {setting_label} entries; using configured CLI toolsets"
        )

    try:
        from superforecasting_agent.runtime.config import load_config
        from superforecasting_agent.tooling.selection import _get_platform_tools

        cfg = config if config is not None else load_config()

        # Runtime toolset resolution must include default MCP servers so the
        # agent can actually call them. Passing ``False`` here is the
        # config-editing variant — used when we need to persist a toolset
        # list without baking in implicit MCP defaults. Using the wrong
        # variant at agent creation time makes MCP tools silently missing
        # from the TUI. See PR #3252 for the original design split.
        enabled = sorted(
            _get_platform_tools(cfg, "cli", include_default_mcp_servers=True)
        )
        if fallback_notice is not None:
            warn(fallback_notice)
        # An empty resolved selection means no tools; None means all tools.
        # Do not widen an explicit empty platform selection at startup.
        return enabled
    except Exception:
        if fallback_notice is not None:
            warn(
                f"no valid {setting_label} entries and configured CLI toolsets could not be loaded; enabling all toolsets",
            )
        return None
