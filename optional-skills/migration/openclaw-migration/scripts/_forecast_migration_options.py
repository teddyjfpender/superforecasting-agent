"""Migration categories, presets, report items, and option selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


ENTRY_DELIMITER = "\n§\n"
DEFAULT_MEMORY_CHAR_LIMIT = 2200
DEFAULT_USER_CHAR_LIMIT = 1375
SKILL_CATEGORY_DIRNAME = "openclaw-imports"
SKILL_CATEGORY_DESCRIPTION = (
    "Skills migrated from an OpenClaw workspace."
)
SKILL_CONFLICT_MODES = {"skip", "overwrite", "rename"}
SUPPORTED_SECRET_TARGETS={
    "TELEGRAM_BOT_TOKEN",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "ELEVENLABS_API_KEY",
    "VOICE_TOOLS_OPENAI_KEY",
}
WORKSPACE_INSTRUCTIONS_FILENAME = "AGENTS" + ".md"
MIGRATION_OPTION_METADATA: Dict[str, Dict[str, str]] = {
    "soul": {
        "label": "SOUL.md",
        "description": "Import the OpenClaw persona file into Superforecasting Agent.",
    },
    "workspace-agents": {
        "label": "Workspace instructions",
        "description": "Copy the OpenClaw workspace instructions file into a chosen workspace.",
    },
    "memory": {
        "label": "MEMORY.md",
        "description": "Import long-term memory entries into Superforecasting Agent memories.",
    },
    "user-profile": {
        "label": "USER.md",
        "description": "Import user profile entries into Superforecasting Agent memories.",
    },
    "messaging-settings": {
        "label": "Messaging settings",
        "description": "Import Superforecasting Agent-compatible messaging settings such as allowlists and working directory.",
    },
    "secret-settings": {
        "label": "Allowlisted secrets",
        "description": "Import the small allowlist of Superforecasting Agent-compatible secrets when explicitly enabled.",
    },
    "command-allowlist": {
        "label": "Command allowlist",
        "description": "Merge OpenClaw exec approval patterns into Superforecasting Agent command_allowlist.",
    },
    "skills": {
        "label": "User skills",
        "description": "Copy OpenClaw skills into ~/.superforecasting-agent/skills/openclaw-imports/.",
    },
    "tts-assets": {
        "label": "TTS assets",
        "description": "Copy compatible workspace TTS assets into ~/.superforecasting-agent/tts/.",
    },
    "discord-settings": {
        "label": "Discord settings",
        "description": "Import Discord bot token and allowlist into Superforecasting Agent .env.",
    },
    "slack-settings": {
        "label": "Slack settings",
        "description": "Import Slack bot/app tokens and allowlist into Superforecasting Agent .env.",
    },
    "whatsapp-settings": {
        "label": "WhatsApp settings",
        "description": "Import WhatsApp allowlist into Superforecasting Agent .env.",
    },
    "signal-settings": {
        "label": "Signal settings",
        "description": "Import Signal account, HTTP URL, and allowlist into Superforecasting Agent .env.",
    },
    "provider-keys": {
        "label": "Provider API keys",
        "description": "Import model provider API keys into Superforecasting Agent .env (requires --migrate-secrets).",
    },
    "model-config": {
        "label": "Default model",
        "description": "Import the default model setting into Superforecasting Agent config.yaml.",
    },
    "tts-config": {
        "label": "TTS configuration",
        "description": "Import TTS provider and voice settings into Superforecasting Agent config.yaml.",
    },
    "shared-skills": {
        "label": "Shared skills",
        "description": "Copy shared OpenClaw skills from ~/.openclaw/skills/ into Superforecasting Agent.",
    },
    "daily-memory": {
        "label": "Daily memory files",
        "description": "Merge daily memory entries from workspace/memory/ into Superforecasting Agent MEMORY.md.",
    },
    "archive": {
        "label": "Archive unmapped docs",
        "description": "Archive compatible-but-unmapped docs for later manual review.",
    },
    "mcp-servers": {
        "label": "MCP servers",
        "description": "Import MCP server definitions from OpenClaw into Superforecasting Agent config.yaml.",
    },
    "plugins-config": {
        "label": "Plugins configuration",
        "description": "Archive OpenClaw plugin configuration and installed extensions for manual review.",
    },
    "cron-jobs": {
        "label": "Cron / scheduled tasks",
        "description": "Import cron job definitions. Archive for manual recreation via 'superforecasting-agent cron'.",
    },
    "hooks-config": {
        "label": "Hooks and webhooks",
        "description": "Archive OpenClaw hook configuration (internal hooks, webhooks, Gmail integration).",
    },
    "agent-config": {
        "label": "Agent defaults and multi-agent setup",
        "description": "Import agent defaults (compaction, context, thinking) into Superforecasting Agent config. Archive multi-agent list.",
    },
    "gateway-config": {
        "label": "Gateway configuration",
        "description": "Import gateway port and auth settings. Archive full gateway config for manual setup.",
    },
    "session-config": {
        "label": "Session configuration",
        "description": "Import session reset policies (daily/idle) into Superforecasting Agent session_reset config.",
    },
    "full-providers": {
        "label": "Full model provider definitions",
        "description": "Import custom model providers (baseUrl, apiType, headers) into Superforecasting Agent custom_providers.",
    },
    "deep-channels": {
        "label": "Deep channel configuration",
        "description": "Import extended channel settings (Matrix, Mattermost, IRC, group configs). Archive complex settings.",
    },
    "browser-config": {
        "label": "Browser configuration",
        "description": "Import browser automation settings into Superforecasting Agent config.yaml.",
    },
    "tools-config": {
        "label": "Tools configuration",
        "description": "Import tool settings (exec timeout, sandbox, web search) into Superforecasting Agent config.yaml.",
    },
    "approvals-config": {
        "label": "Approval rules",
        "description": "Import approval mode and rules into Superforecasting Agent config.yaml approvals section.",
    },
    "memory-backend": {
        "label": "Memory backend configuration",
        "description": "Archive OpenClaw memory backend settings (QMD, vector search, citations) for manual review.",
    },
    "skills-config": {
        "label": "Skills registry configuration",
        "description": "Archive per-skill enabled/config/env settings from OpenClaw skills.entries.",
    },
    "ui-identity": {
        "label": "UI and identity settings",
        "description": "Archive OpenClaw UI theme, assistant identity, and display preferences.",
    },
    "logging-config": {
        "label": "Logging and diagnostics",
        "description": "Archive OpenClaw logging and diagnostics configuration.",
    },
}
MIGRATION_PRESETS: Dict[str, set[str]] = {
    "user-data": {
        "soul",
        "workspace-agents",
        "memory",
        "user-profile",
        "messaging-settings",
        "command-allowlist",
        "skills",
        "tts-assets",
        "discord-settings",
        "slack-settings",
        "whatsapp-settings",
        "signal-settings",
        "model-config",
        "tts-config",
        "shared-skills",
        "daily-memory",
        "archive",
        "mcp-servers",
        "agent-config",
        "session-config",
        "browser-config",
        "tools-config",
        "approvals-config",
        "deep-channels",
        "full-providers",
        "plugins-config",
        "cron-jobs",
        "hooks-config",
        "memory-backend",
        "skills-config",
        "ui-identity",
        "logging-config",
        "gateway-config",
    },
    "full": set(MIGRATION_OPTION_METADATA),
}


# ───────────────────────────────────────────────────────────────────────
# Item shape constants — kept stable for downstream consumers of report.json.
# Inspired by OpenClaw's src/plugin-sdk/migration.ts so both sides speak the
# same vocabulary.  Values intentionally match the strings already produced
# by this script (migrated/archived/skipped/conflict/error) so the addition
# is backward-compatible.
# ───────────────────────────────────────────────────────────────────────
STATUS_MIGRATED = "migrated"
STATUS_ARCHIVED = "archived"
STATUS_SKIPPED = "skipped"
STATUS_CONFLICT = "conflict"
STATUS_ERROR = "error"
STATUS_PLANNED = "planned"

REASON_TARGET_EXISTS = "Target exists and overwrite is disabled"
REASON_BLOCKED_BY_APPLY_CONFLICT = "blocked by earlier apply conflict"


@dataclass
class ItemResult:
    kind: str
    source: Optional[str]
    destination: Optional[str]
    status: str
    reason: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    sensitive: bool = False


def parse_selection_values(values: Optional[Sequence[str]]) -> List[str]:
    parsed: List[str] = []
    for value in values or ():
        for part in str(value).split(","):
            part = part.strip().lower()
            if part:
                parsed.append(part)
    return parsed


def resolve_selected_options(
    include: Optional[Sequence[str]] = None,
    exclude: Optional[Sequence[str]] = None,
    preset: Optional[str] = None,
) -> set[str]:
    include_values = parse_selection_values(include)
    exclude_values = parse_selection_values(exclude)
    valid = set(MIGRATION_OPTION_METADATA)
    preset_name = (preset or "").strip().lower()

    if preset_name and preset_name not in MIGRATION_PRESETS:
        raise ValueError(
            "Unknown migration preset: "
            + preset_name
            + ". Valid presets: "
            + ", ".join(sorted(MIGRATION_PRESETS))
        )

    unknown = (set(include_values) - {"all"} - valid) | (set(exclude_values) - {"all"} - valid)
    if unknown:
        raise ValueError(
            "Unknown migration option(s): "
            + ", ".join(sorted(unknown))
            + ". Valid options: "
            + ", ".join(sorted(valid))
        )

    if preset_name:
        selected = set(MIGRATION_PRESETS[preset_name])
    elif not include_values or "all" in include_values:
        selected = set(valid)
    else:
        selected = set(include_values)

    if "all" in exclude_values:
        selected.clear()
    selected -= (set(exclude_values) - {"all"})
    return selected
