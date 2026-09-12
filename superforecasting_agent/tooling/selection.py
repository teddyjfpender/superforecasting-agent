"""Noninteractive platform tool selection and its shared catalog."""

from __future__ import annotations

import os
from typing import Dict, List, Set

from superforecasting_agent.runtime.config import cfg_get
from superforecasting_agent.runtime.platforms import PLATFORMS as _PLATFORMS_REGISTRY

# ─── Toolset Registry ─────────────────────────────────────────────────────────

# Toolsets shown in the configurator, grouped for display.
# Each entry: (toolset_name, label, description)
# These map to keys in toolsets.py TOOLSETS dict.
CONFIGURABLE_TOOLSETS = [
    (
        "forecasting",
        "📈 Forecast Ledger",
        "forecast_ledger lifecycle and learning writes",
    ),
    ("web", "🔍 Web Search & Scraping", "web_search, web_extract"),
    ("browser", "🌐 Browser Automation", "navigate, click, type, scroll"),
    ("terminal", "💻 Terminal & Processes", "terminal, process"),
    ("file", "📁 File Operations", "read, write, patch, search"),
    ("code_execution", "⚡ Code Execution", "execute_code"),
    ("vision", "👁️  Vision / Image Analysis", "vision_analyze"),
    ("video", "🎬 Video Analysis", "video_analyze (requires video-capable model)"),
    ("image_gen", "🎨 Image Generation", "image_generate"),
    (
        "video_gen",
        "🎬 Video Generation",
        "video_generate (text-to-video + image-to-video)",
    ),
    (
        "x_search",
        "🐦 X (Twitter) Search",
        "x_search (requires xAI OAuth or XAI_API_KEY)",
    ),
    ("moa", "🧠 Mixture of Agents", "mixture_of_agents"),
    ("tts", "🔊 Text-to-Speech", "text_to_speech"),
    ("skills", "📚 Skills", "list, view, manage"),
    ("todo", "📋 Task Planning", "todo"),
    ("memory", "💾 Memory", "persistent memory across sessions"),
    ("session_search", "🔎 Session Search", "search past conversations"),
    ("clarify", "❓ Clarifying Questions", "clarify"),
    ("delegation", "👥 Task Delegation", "delegate_task"),
    (
        "cronjob",
        "⏰ Cron Jobs",
        "create/list/update/pause/resume/run, with optional attached skills",
    ),
    ("messaging", "📨 Cross-Platform Messaging", "send_message"),
    ("homeassistant", "🏠 Home Assistant", "smart home device control"),
    (
        "discord",
        "💬 Discord (read/participate)",
        "fetch messages, search members, create thread",
    ),
    (
        "discord_admin",
        "🛡️  Discord Server Admin",
        "list channels/roles, pin, assign roles",
    ),
    ("yuanbao", "🤖 Yuanbao", "group info, member queries, DM"),
    (
        "computer_use",
        "🖱️  Computer Use (macOS)",
        "background desktop control via cua-driver",
    ),
]

# Toolsets that are OFF by default for new installs.
# They're still in _HERMES_CORE_TOOLS (available at runtime if enabled),
# but the setup checklist won't pre-select them for first-time users.
#
# Video gen is off by default — it's a niche, paid, slow feature. Users
# who want it opt in via `superforecasting-agent tools` → Video Generation,
# which walks them through provider + model selection.
#
# X search is off by default for users without xAI credentials, but
# auto-enables when SuperGrok OAuth tokens are stored OR XAI_API_KEY is
# set — mirroring the HASS_TOKEN → homeassistant auto-enable below. The
# `superforecasting-agent tools` → X (Twitter) Search setup walks users
# through credential setup. The tool's check_fn means the schema still won't
# appear to the model if the credential later goes missing or expires.
_DEFAULT_OFF_TOOLSETS = {
    "moa",
    "homeassistant",
    "discord",
    "discord_admin",
    "video",
    "video_gen",
    "x_search",
}


def _xai_credentials_present() -> bool:
    """Cheap, side-effect-free check for usable xAI credentials.

    Used to auto-enable the ``x_search`` toolset when the user has either
    completed xAI Grok OAuth (SuperGrok subscription) or set
    ``XAI_API_KEY``. Does NOT hit the network — only inspects the local
    auth store and environment. The tool's runtime ``check_fn`` still
    gates schema registration if creds later expire or get revoked.
    """
    try:
        from superforecasting_agent.runtime.auth import _read_xai_oauth_tokens

        _read_xai_oauth_tokens()
        return True
    except Exception:
        pass
    try:
        from tools.xai_http import get_env_value as _xai_get_env_value

        if str(_xai_get_env_value("XAI_API_KEY") or "").strip():
            return True
    except Exception:
        pass
    return bool(str(os.environ.get("XAI_API_KEY") or "").strip())


# Platform-scoped toolsets: only appear in the `superforecasting-agent tools`
# checklist for these platforms, and only resolve/save for these platforms.  A toolset
# absent from this map is available on every platform (current behaviour).
#
# Use this for tools whose APIs only make sense on one platform (Discord
# server admin, Slack workspace admin, etc.).  Keeps every other platform's
# checklist from filling up with irrelevant toggles.
_TOOLSET_PLATFORM_RESTRICTIONS: Dict[str, Set[str]] = {
    "discord": {"discord"},
    "discord_admin": {"discord"},
}


def _toolset_allowed_for_platform(ts_key: str, platform: str) -> bool:
    """Return True if ``ts_key`` is configurable on ``platform``.

    Toolsets without a restriction entry are allowed everywhere (the default).
    """
    allowed = _TOOLSET_PLATFORM_RESTRICTIONS.get(ts_key)
    return allowed is None or platform in allowed


def _fallback_platform_toolset(platform: str, toolsets: dict) -> str:
    """Return the composite toolset for a dynamic platform.

    New plugin/platform integrations should use ``forecast-<platform>``.
    Legacy ``hermes-<platform>`` toolsets remain valid during the fork
    transition so existing plugins do not lose their default tools.
    """
    forecast_toolset = f"forecast-{platform}"
    if forecast_toolset in toolsets:
        return forecast_toolset
    legacy_toolset = f"hermes-{platform}"
    if legacy_toolset in toolsets:
        return legacy_toolset
    return forecast_toolset


def _get_effective_configurable_toolsets():
    """Return CONFIGURABLE_TOOLSETS + any plugin-provided toolsets.

    Plugin toolsets are appended at the end so they appear after the
    built-in toolsets in the TUI checklist. A plugin whose toolset key
    already appears in ``CONFIGURABLE_TOOLSETS`` is skipped — bundled
    plugins share their toolset key with the
    built-in entry, and we want the built-in label/description to win.
    Without the dedupe, ``superforecasting-agent tools`` → "reconfigure existing" would
    list the same toolset twice.
    """
    result = list(CONFIGURABLE_TOOLSETS)
    seen = {ts_key for ts_key, _, _ in result}
    try:
        from superforecasting_agent.runtime.plugins import (
            discover_plugins,
            get_plugin_toolsets,
        )

        discover_plugins()  # idempotent — ensures plugins are loaded
        for entry in get_plugin_toolsets():
            if entry[0] in seen:
                continue
            seen.add(entry[0])
            result.append(entry)
    except Exception:
        pass
    return result


def _get_plugin_toolset_keys() -> set:
    """Return the set of toolset keys provided by plugins."""
    try:
        from superforecasting_agent.runtime.plugins import (
            discover_plugins,
            get_plugin_toolsets,
        )

        discover_plugins()  # idempotent — ensures plugins are loaded
        return {ts_key for ts_key, _, _ in get_plugin_toolsets()}
    except Exception:
        return set()


# Platform display config — derived from the canonical registry so every
# module shares the same data.  Kept as dict-of-dicts for backward
# compatibility with existing ``PLATFORMS[key]["label"]`` access patterns.

PLATFORMS = {
    k: {"label": info.label, "default_toolset": info.default_toolset}
    for k, info in _PLATFORMS_REGISTRY.items()
}


def _parse_enabled_flag(value, default: bool = True) -> bool:
    """Parse bool-like config values used by tool/platform settings."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _get_platform_tools(
    config: dict,
    platform: str,
    *,
    include_default_mcp_servers: bool = True,
) -> Set[str]:
    """Resolve which individual toolset names are enabled for a platform."""
    from superforecasting_agent.tooling.toolsets import TOOLSETS, resolve_toolset

    platform_toolsets = config.get("platform_toolsets") or {}
    toolset_names = platform_toolsets.get(platform)
    if toolset_names == []:
        # A saved empty selection is authoritative, including for newly
        # discovered plugins, credential-based opt-ins and default MCP servers.
        return set()

    if toolset_names is None or not isinstance(toolset_names, list):
        plat_info = PLATFORMS.get(platform)
        if plat_info:
            default_ts = plat_info["default_toolset"]
        else:
            # Plugin platform — derive toolset name from platform key
            default_ts = _fallback_platform_toolset(platform, TOOLSETS)
        toolset_names = [default_ts]

    # YAML may parse bare numeric names (e.g. ``12306:``) as int.
    # Normalise to str so downstream sorted() never mixes types.
    toolset_names = [str(ts) for ts in toolset_names]

    configurable_keys = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS}
    plugin_ts_keys = _get_plugin_toolset_keys()
    platform_default_keys = {p["default_toolset"] for p in PLATFORMS.values()}

    # If the saved list contains any configurable keys directly, the user
    # has explicitly configured this platform — use direct membership.
    # This avoids the subset-inference bug where composite toolsets like
    # "hermes-cli" (which include all _HERMES_CORE_TOOLS) cause disabled
    # toolsets to re-appear as enabled.
    has_explicit_config = any(ts in configurable_keys for ts in toolset_names)

    if has_explicit_config:
        enabled_toolsets = {
            ts
            for ts in toolset_names
            if ts in configurable_keys and _toolset_allowed_for_platform(ts, platform)
        }
        # Mixed config: composite toolset alongside configurables (e.g.
        # ``[hermes-cli, homeassistant]`` after enabling a toolset via ``hermes
        # tools``). Without expansion the composite name is silently dropped,
        # leaving sessions with only the configurable opt-ins and no native
        # tools. Mirror the else-branch's subset inference, but apply
        # _DEFAULT_OFF_TOOLSETS only to the implicit expansion — anything the
        # user explicitly listed (e.g. ``homeassistant``) must survive.
        composite_tools = set()
        for ts_name in toolset_names:
            if ts_name in configurable_keys or ts_name in plugin_ts_keys:
                continue
            if ts_name not in TOOLSETS:
                continue
            composite_tools.update(resolve_toolset(ts_name))

        if composite_tools:
            expanded = set()
            for ts_key, _, _ in CONFIGURABLE_TOOLSETS:
                if not _toolset_allowed_for_platform(ts_key, platform):
                    continue
                ts_tools = set(resolve_toolset(ts_key))
                if ts_tools and ts_tools.issubset(composite_tools):
                    expanded.add(ts_key)

            default_off = set(_DEFAULT_OFF_TOOLSETS)
            if (
                platform in default_off
                and platform not in _TOOLSET_PLATFORM_RESTRICTIONS
            ):
                default_off.remove(platform)
            if "homeassistant" in default_off and os.getenv("HASS_TOKEN"):
                default_off.remove("homeassistant")
            expanded -= default_off

            enabled_toolsets |= expanded
    else:
        # No explicit config — fall back to resolving composite toolset names
        # (e.g. "hermes-cli") to individual tool names and reverse-mapping.
        all_tool_names = set()
        for ts_name in toolset_names:
            all_tool_names.update(resolve_toolset(ts_name))

        enabled_toolsets = set()
        for ts_key, _, _ in CONFIGURABLE_TOOLSETS:
            if not _toolset_allowed_for_platform(ts_key, platform):
                continue
            ts_tools = set(resolve_toolset(ts_key))
            if ts_tools and ts_tools.issubset(all_tool_names):
                enabled_toolsets.add(ts_key)

        # Auto-enable ``x_search`` when xAI credentials are configured.
        # Unlike ``homeassistant`` (whose ``ha_*`` tools live inside the
        # platform composite and thus pass the subset check above),
        # ``x_search`` is its own one-tool toolset that the composite does
        # NOT include, so the subset loop never picks it up. Inject it
        # directly here, mirroring the HASS_TOKEN → ``homeassistant`` rule
        # below: once you have working creds, you don't have to also click
        # through ``superforecasting-agent tools`` to flip the toolset on. Only fires when
        # the user has not yet saved an explicit toolset list — once they
        # do, the saved list is authoritative.
        x_search_auto_enabled = (
            _toolset_allowed_for_platform("x_search", platform)
            and _xai_credentials_present()
        )
        if x_search_auto_enabled:
            enabled_toolsets.add("x_search")

        default_off = set(_DEFAULT_OFF_TOOLSETS)
        # Legacy safety: if the platform's own name matches a default-off
        # toolset (e.g. `homeassistant` platform + `homeassistant` toolset),
        # keep that toolset enabled on first install.  Skip this dodge for
        # platform-restricted toolsets — those are always opt-in even on
        # their own platform (e.g. `discord` + `discord` should stay OFF).
        if platform in default_off and platform not in _TOOLSET_PLATFORM_RESTRICTIONS:
            default_off.remove(platform)
        # Home Assistant is already runtime-gated by its check_fn (requires
        # HASS_TOKEN to register any tools). When a user has configured
        # HASS_TOKEN, they've explicitly opted in — don't also strip it via
        # _DEFAULT_OFF_TOOLSETS, which would silently drop HA from platforms
        # (e.g. cron) that run through _get_platform_tools without an
        # explicit saved toolset list. Without this, Norbert's HA cron jobs
        # regressed after #14798 made cron honor per-platform tool config.
        if "homeassistant" in default_off and os.getenv("HASS_TOKEN"):
            default_off.remove("homeassistant")
        # Symmetric carve-out for x_search auto-enable (see the inject
        # block above). Without this, the default_off subtraction would
        # strip the entry we just added.
        if x_search_auto_enabled and "x_search" in default_off:
            default_off.remove("x_search")
        enabled_toolsets -= default_off

    # Recover non-configurable platform toolsets (e.g. discord, feishu_doc,
    # feishu_drive).  These are part of the platform's default composite but
    # absent from CONFIGURABLE_TOOLSETS, so they can't appear in the TUI
    # checklist or in a user-saved config.  Must run in BOTH branches —
    # otherwise saving via `superforecasting-agent tools` (which flips has_explicit_config
    # to True) silently drops them.
    _plat_info = PLATFORMS.get(platform)
    _default_ts = (
        _plat_info["default_toolset"]
        if _plat_info
        else _fallback_platform_toolset(platform, TOOLSETS)
    )
    platform_tool_universe = set(resolve_toolset(_default_ts))
    for ts_name in toolset_names:
        if ts_name in configurable_keys or ts_name in plugin_ts_keys:
            continue
        if ts_name not in TOOLSETS:
            continue
        platform_tool_universe.update(resolve_toolset(ts_name))
    configurable_tool_universe = set()
    for ck in configurable_keys:
        configurable_tool_universe.update(resolve_toolset(ck))
    claimed = set()
    for ts_key in enabled_toolsets:
        claimed.update(resolve_toolset(ts_key))
    skip = configurable_keys | plugin_ts_keys | platform_default_keys
    skip |= {k for k in TOOLSETS if k.startswith(("forecast-", "hermes-"))}
    skip |= set(_DEFAULT_OFF_TOOLSETS) - {platform}
    for ts_key, ts_def in TOOLSETS.items():
        if ts_key in skip:
            continue
        if ts_def.get("includes"):
            continue
        ts_tools = set(resolve_toolset(ts_key))
        if not ts_tools or not ts_tools.issubset(platform_tool_universe):
            continue
        if ts_tools.issubset(configurable_tool_universe):
            continue
        if not ts_tools.issubset(claimed):
            enabled_toolsets.add(ts_key)
            claimed.update(ts_tools)

    # Plugin toolsets: enabled by default unless explicitly disabled, or
    # unless the toolset is in _DEFAULT_OFF_TOOLSETS (bundled plugins the
    # user must opt in to via `superforecasting-agent tools` so we don't
    # ship their tool schemas to users who don't use them). A plugin
    # toolset is "known" for a platform once
    # `superforecasting-agent tools` has been saved for that platform (tracked
    # via known_plugin_toolsets).
    # Unknown plugins default to enabled; known-but-absent = disabled.
    if plugin_ts_keys:
        known_map = config.get("known_plugin_toolsets", {})
        known_for_platform = set(known_map.get(platform, []))
        for pts in plugin_ts_keys:
            if pts in toolset_names:
                # Explicitly listed in config — enabled
                enabled_toolsets.add(pts)
            elif pts in _DEFAULT_OFF_TOOLSETS:
                # Opt-in plugin toolset — stay off until user picks it
                continue
            elif pts not in known_for_platform:
                # New plugin not yet seen by superforecasting-agent tools — default enabled
                enabled_toolsets.add(pts)
            # else: known but not in config = user disabled it

    # Preserve any explicit non-configurable toolset entries (for example,
    # custom toolsets or MCP server names saved in platform_toolsets).
    explicit_passthrough = {
        ts
        for ts in toolset_names
        if ts not in configurable_keys
        and ts not in plugin_ts_keys
        and ts not in platform_default_keys
    }

    # MCP servers are expected to be available on all platforms by default.
    # If the platform explicitly lists one or more MCP server names, treat that
    # as an allowlist. Otherwise include every globally enabled MCP server.
    # Special sentinel: "no_mcp" in the toolset list disables all MCP servers.
    mcp_servers = config.get("mcp_servers") or {}
    enabled_mcp_servers = {
        str(name)
        for name, server_cfg in mcp_servers.items()
        if isinstance(server_cfg, dict)
        and _parse_enabled_flag(server_cfg.get("enabled", True), default=True)
    }
    # Allow "no_mcp" sentinel to opt out of all MCP servers for this platform
    if "no_mcp" in toolset_names:
        explicit_mcp_servers = set()
        enabled_toolsets.update(explicit_passthrough - enabled_mcp_servers - {"no_mcp"})
    else:
        explicit_mcp_servers = explicit_passthrough & enabled_mcp_servers
        enabled_toolsets.update(explicit_passthrough - enabled_mcp_servers)
    if include_default_mcp_servers:
        if explicit_mcp_servers or "no_mcp" in toolset_names:
            enabled_toolsets.update(explicit_mcp_servers)
        else:
            enabled_toolsets.update(enabled_mcp_servers)
    else:
        enabled_toolsets.update(explicit_mcp_servers)

    # Honor agent.disabled_toolsets from config.yaml — allows users to
    # globally suppress specific toolsets (e.g. "memory") across all
    # platforms without per-platform toolset configuration.  This runs
    # last so it overrides everything above.
    agent_cfg = config.get("agent") or {}
    disabled_toolsets = agent_cfg.get("disabled_toolsets") or []
    if disabled_toolsets:
        disabled_set = {str(ts) for ts in disabled_toolsets}
        enabled_toolsets -= disabled_set

    return enabled_toolsets


def set_platform_tools(config: dict, platform: str, enabled_toolset_keys: Set[str]):
    """Save the selected toolset keys for a platform to config.

    Preserves any non-configurable toolset entries (like MCP server names)
    that were already in the config for this platform.
    """
    config.setdefault("platform_toolsets", {})

    # Drop platform-scoped toolsets that don't apply here.  Prevents the
    # "Configure all platforms" checklist (or a hand-edited config.yaml)
    # from turning on, say, the `discord` toolset for Telegram.
    enabled_toolset_keys = {
        ts for ts in enabled_toolset_keys if _toolset_allowed_for_platform(ts, platform)
    }

    # Get the set of all configurable toolset keys (built-in + plugin)
    configurable_keys = {ts_key for ts_key, _, _ in CONFIGURABLE_TOOLSETS}
    plugin_keys = _get_plugin_toolset_keys()
    configurable_keys |= plugin_keys

    # Also exclude platform default and bundled composite toolsets
    # (forecast-desk, hermes-cli, hermes-telegram, etc.). These composites can
    # re-enable tools that the user unchecked when the saved config is read.
    platform_default_keys = {p["default_toolset"] for p in PLATFORMS.values()}
    from superforecasting_agent.tooling.toolsets import TOOLSETS

    bundled_composite_keys = {
        key
        for key, value in TOOLSETS.items()
        if key.startswith("hermes-") or value.get("includes")
    }

    # Get existing toolsets for this platform
    existing_toolsets = cfg_get(config, "platform_toolsets", platform, default=[])
    if not isinstance(existing_toolsets, list):
        existing_toolsets = []
    existing_toolsets = [str(ts) for ts in existing_toolsets]

    # Preserve any entries that are NOT configurable toolsets and NOT platform
    # defaults (i.e. only MCP server names should be preserved)
    preserved_entries = {
        entry
        for entry in existing_toolsets
        if (
            entry not in configurable_keys
            and entry not in platform_default_keys
            and entry not in bundled_composite_keys
        )
    }
    # Opening `superforecasting-agent tools` is the user's opt-in to reconfigure tools, so treat
    # saving from the picker as consent to clear the "no_mcp" sentinel. The
    # picker has no checkbox for no_mcp, so without this users who once set it
    # by hand could never re-enable MCP servers through the UI.
    preserved_entries.discard("no_mcp")

    # Merge preserved entries with new enabled toolsets
    config["platform_toolsets"][platform] = sorted(
        enabled_toolset_keys | preserved_entries
    )

    # Track which plugin toolsets are "known" for this platform so we can
    # distinguish "new plugin, default enabled" from "user disabled it".
    if plugin_keys:
        config.setdefault("known_plugin_toolsets", {})
        config["known_plugin_toolsets"][platform] = sorted(plugin_keys)


def apply_toolset_change(
    config: dict, platform: str, toolset_names: List[str], action: str
):
    """Add or remove built-in toolsets for a platform."""
    if action not in {"enable", "disable"}:
        raise ValueError(f"Unknown tools action: {action}")
    enabled = _get_platform_tools(config, platform, include_default_mcp_servers=False)
    if action == "disable":
        updated = enabled - set(toolset_names)
    else:
        updated = enabled | set(toolset_names)
    set_platform_tools(config, platform, updated)


def apply_mcp_change(config: dict, targets: List[str], action: str) -> Set[str]:
    """Add or remove specific MCP tools from a server's exclude list.

    Returns the set of server names that were not found in config.
    """
    if action not in {"enable", "disable"}:
        raise ValueError(f"Unknown tools action: {action}")
    failed_servers: Set[str] = set()
    mcp_servers = config.get("mcp_servers") or {}

    for target in targets:
        server_name, tool_name = target.split(":", 1)
        if server_name not in mcp_servers:
            failed_servers.add(server_name)
            continue
        tools_cfg = mcp_servers[server_name].setdefault("tools", {})
        exclude = list(tools_cfg.get("exclude") or [])
        if action == "disable":
            if tool_name not in exclude:
                exclude.append(tool_name)
        else:
            exclude = [t for t in exclude if t != tool_name]
        tools_cfg["exclude"] = exclude

    return failed_servers


def change_tools(config: dict, platform: str, targets: List[str], action: str) -> dict:
    """Validate and apply one tool selection edit without persistence or reset."""
    from copy import deepcopy

    if action not in {"enable", "disable"}:
        raise ValueError(f"Unknown tools action: {action}")
    if not targets or any(
        not isinstance(name, str) or not name.strip() for name in targets
    ):
        raise ValueError("Tool names must be nonempty strings")
    targets = list(dict.fromkeys(name.strip() for name in targets))
    if any(":" in name and not all(name.split(":", 1)) for name in targets):
        raise ValueError("MCP targets must have server:tool form")
    valid = {key for key, _, _ in CONFIGURABLE_TOOLSETS} | _get_plugin_toolset_keys()
    unknown = [name for name in targets if ":" not in name and name not in valid]
    restricted = [
        name
        for name in targets
        if ":" not in name
        and name in valid
        and not _toolset_allowed_for_platform(name, platform)
    ]
    toolsets = [
        name for name in targets if ":" not in name and name not in unknown + restricted
    ]
    mcp = [name for name in targets if ":" in name]
    before = deepcopy(config)
    # Prepare detached state so a malformed MCP configuration cannot leave a
    # preceding toolset edit half applied in the caller's snapshot.
    updated = deepcopy(config)
    if toolsets:
        apply_toolset_change(updated, platform, toolsets, action)
    missing = apply_mcp_change(updated, mcp, action) if mcp else set()
    accepted = [
        name
        for name in targets
        if name not in unknown + restricted
        and (":" not in name or name.split(":", 1)[0] not in missing)
    ]
    changed = accepted if updated != before else []
    if changed:
        config.clear()
        config.update(updated)
    return {
        "changed": changed,
        "unknown": unknown,
        "restricted": restricted,
        "missing_servers": sorted(missing),
    }
