"""Coordinate selected OpenClaw migration steps and conflict reporting."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from _forecast_migration_files import load_yaml_file as load_yaml_file
from _forecast_migration_options import (
    DEFAULT_MEMORY_CHAR_LIMIT as DEFAULT_MEMORY_CHAR_LIMIT,
    DEFAULT_USER_CHAR_LIMIT as DEFAULT_USER_CHAR_LIMIT,
    SKILL_CONFLICT_MODES as SKILL_CONFLICT_MODES,
    MIGRATION_OPTION_METADATA as MIGRATION_OPTION_METADATA,
    STATUS_SKIPPED as STATUS_SKIPPED,
    STATUS_CONFLICT as STATUS_CONFLICT,
    STATUS_ERROR as STATUS_ERROR,
    REASON_BLOCKED_BY_APPLY_CONFLICT as REASON_BLOCKED_BY_APPLY_CONFLICT,
    ItemResult as ItemResult,
)


class Migrator:
    def __init__(
        self,
        source_root: Path,
        target_root: Path,
        execute: bool,
        workspace_target: Optional[Path],
        overwrite: bool,
        migrate_secrets: bool,
        output_dir: Optional[Path],
        selected_options: Optional[set[str]] = None,
        preset_name: str = "",
        skill_conflict_mode: str = "skip",
    ):
        self.source_root = source_root
        self.target_root = target_root
        self.execute = execute
        self.workspace_target = workspace_target
        self.overwrite = overwrite
        self.migrate_secrets = migrate_secrets
        self.selected_options = set(selected_options or MIGRATION_OPTION_METADATA.keys())
        self.preset_name = preset_name.strip().lower()
        self.skill_conflict_mode = skill_conflict_mode.strip().lower() or "skip"
        self.timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        self.output_dir = output_dir or (
            target_root / "migration" / "openclaw" / self.timestamp if execute else None
        )
        self.archive_dir = self.output_dir / "archive" if self.output_dir else None
        self.backup_dir = self.output_dir / "backups" if self.output_dir else None
        self.overflow_dir = self.output_dir / "overflow" if self.output_dir else None
        self.items: List[ItemResult] = []
        # Once a config.yaml write hits conflict/error mid-run, later
        # config.yaml writes are deliberately short-circuited to avoid
        # leaving config in a partially-written state.  Modelled on
        # OpenClaw's extensions/migrate-hermes/apply.ts "blocked by earlier
        # apply conflict" sequencing.
        self._config_apply_blocked: bool = False

        # Resolve the configured workspace directory from openclaw.json.
        # Many users (especially those who started before the OpenClaw rebrand)
        # have a custom workspace path (e.g. ~/clawd/) that differs from the
        # default ~/.openclaw/workspace/.  Reading agents.defaults.workspace
        # lets source_candidate() find files in the actual workspace.
        self._custom_workspace: Optional[Path] = None
        oc_config = self.load_openclaw_config()
        ws = (oc_config.get("agents", {}).get("defaults", {}).get("workspace") or "").strip()
        if ws:
            ws_path = Path(ws).expanduser().resolve()
            # Only use it if it exists and is outside the source_root tree
            # (otherwise the standard relative-path logic already covers it).
            if ws_path.is_dir():
                try:
                    ws_path.relative_to(self.source_root)
                except ValueError:
                    # ws_path is outside source_root — use it as custom workspace
                    self._custom_workspace = ws_path

        config = load_yaml_file(self.target_root / "config.yaml")
        mem_cfg = config.get("memory", {}) if isinstance(config.get("memory"), dict) else {}
        self.memory_limit = int(mem_cfg.get("memory_char_limit", DEFAULT_MEMORY_CHAR_LIMIT))
        self.user_limit = int(mem_cfg.get("user_char_limit", DEFAULT_USER_CHAR_LIMIT))

        if self.skill_conflict_mode not in SKILL_CONFLICT_MODES:
            raise ValueError(
                "Unknown skill conflict mode: "
                + self.skill_conflict_mode
                + ". Valid modes: "
                + ", ".join(sorted(SKILL_CONFLICT_MODES))
            )

    def is_selected(self, option_id: str) -> bool:
        return option_id in self.selected_options

    # Option ids that mutate the Superforecasting Agent config.yaml file.  Once any one of
    # them records a conflict/error on config.yaml, subsequent ones are
    # short-circuited to avoid partial writes.  Keep in sync with methods
    # that call load_yaml_file(target_root / "config.yaml") + dump_yaml_file.
    _CONFIG_MUTATING_OPTIONS = frozenset({
        "messaging-settings",
        "model-config",
        "tts-config",
        "mcp-servers",
        "plugins-config",
        "cron-jobs",
        "hooks-config",
        "agent-config",
        "gateway-config",
        "session-config",
        "full-providers",
        "deep-channels",
        "browser-config",
        "tools-config",
        "approvals-config",
        "memory-backend",
        "skills-config",
        "ui-identity",
        "logging-config",
        "command-allowlist",
    })

    def record(
        self,
        kind: str,
        source: Optional[Path],
        destination: Optional[Path],
        status: str,
        reason: str = "",
        **details: Any,
    ) -> None:
        sensitive = bool(details.pop("sensitive", False))
        self.items.append(
            ItemResult(
                kind=kind,
                source=str(source) if source else None,
                destination=str(destination) if destination else None,
                status=status,
                reason=reason,
                details=details,
                sensitive=sensitive,
            )
        )
        # Flip the config-block flag when a conflict/error occurs on a
        # config.yaml write.  Later config-mutating options will skip rather
        # than attempting a partial write.
        if status in {STATUS_CONFLICT, STATUS_ERROR} and destination is not None:
            dest_str = str(destination)
            if dest_str.endswith("config.yaml") or dest_str.endswith("config.yml"):
                self._config_apply_blocked = True

    from _forecast_migration_workspace import source_candidate as source_candidate

    from _forecast_migration_skills import resolve_skill_destination as resolve_skill_destination

    def migrate(self) -> Dict[str, Any]:
        if not self.source_root.exists():
            self.record("source", self.source_root, None, "error", "OpenClaw directory does not exist")
            return self.build_report()

        config = self.load_openclaw_config()

        self.run_if_selected("soul", self.migrate_soul)
        self.run_if_selected("workspace-agents", self.migrate_workspace_agents)
        self.run_if_selected(
            "memory",
            lambda: self.migrate_memory(
                self.source_candidate("workspace/MEMORY.md", "workspace.default/MEMORY.md"),
                self.target_root / "memories" / "MEMORY.md",
                self.memory_limit,
                kind="memory",
            ),
        )
        self.run_if_selected(
            "user-profile",
            lambda: self.migrate_memory(
                self.source_candidate("workspace/USER.md", "workspace.default/USER.md"),
                self.target_root / "memories" / "USER.md",
                self.user_limit,
                kind="user-profile",
            ),
        )
        self.run_if_selected("messaging-settings", lambda: self.migrate_messaging_settings(config))
        self.run_if_selected("secret-settings", lambda: self.handle_secret_settings(config))
        self.run_if_selected("discord-settings", lambda: self.migrate_discord_settings(config))
        self.run_if_selected("slack-settings", lambda: self.migrate_slack_settings(config))
        self.run_if_selected("whatsapp-settings", lambda: self.migrate_whatsapp_settings(config))
        self.run_if_selected("signal-settings", lambda: self.migrate_signal_settings(config))
        self.run_if_selected("provider-keys", lambda: self.handle_provider_keys(config))
        self.run_if_selected("model-config", lambda: self.migrate_model_config(config))
        self.run_if_selected("tts-config", lambda: self.migrate_tts_config(config))
        self.run_if_selected("command-allowlist", self.migrate_command_allowlist)
        self.run_if_selected("skills", self.migrate_skills)
        self.run_if_selected("shared-skills", self.migrate_shared_skills)
        self.run_if_selected("daily-memory", self.migrate_daily_memory)
        self.run_if_selected(
            "tts-assets",
            lambda: self.copy_tree_non_destructive(
                self.source_candidate("workspace/tts"),
                self.target_root / "tts",
                kind="tts-assets",
                ignore_dir_names={".venv", "generated", "__pycache__"},
            ),
        )
        self.run_if_selected("archive", self.archive_docs)

        # ── v2 migration modules ──────────────────────────────
        self.run_if_selected("mcp-servers", lambda: self.migrate_mcp_servers(config))
        self.run_if_selected("plugins-config", lambda: self.migrate_plugins_config(config))
        self.run_if_selected("cron-jobs", lambda: self.migrate_cron_jobs(config))
        self.run_if_selected("hooks-config", lambda: self.migrate_hooks_config(config))
        self.run_if_selected("agent-config", lambda: self.migrate_agent_config(config))
        self.run_if_selected("gateway-config", lambda: self.migrate_gateway_config(config))
        self.run_if_selected("session-config", lambda: self.migrate_session_config(config))
        self.run_if_selected("full-providers", lambda: self.migrate_full_providers(config))
        self.run_if_selected("deep-channels", lambda: self.migrate_deep_channels(config))
        self.run_if_selected("browser-config", lambda: self.migrate_browser_config(config))
        self.run_if_selected("tools-config", lambda: self.migrate_tools_config(config))
        self.run_if_selected("approvals-config", lambda: self.migrate_approvals_config(config))
        self.run_if_selected("memory-backend", lambda: self.migrate_memory_backend(config))
        self.run_if_selected("skills-config", lambda: self.migrate_skills_config(config))
        self.run_if_selected("ui-identity", lambda: self.migrate_ui_identity(config))
        self.run_if_selected("logging-config", lambda: self.migrate_logging_config(config))

        # Generate migration notes
        self.generate_migration_notes()

        return self.build_report()

    def run_if_selected(self, option_id: str, func) -> None:
        if not self.is_selected(option_id):
            meta = MIGRATION_OPTION_METADATA[option_id]
            self.record(option_id, None, None, "skipped", "Not selected for this run", option_label=meta["label"])
            return
        # If a previous config.yaml write hit a conflict/error during apply,
        # skip remaining config-mutating options rather than risk a partial
        # write.  Dry-run mode never blocks — the user needs the full preview
        # to decide how to proceed (re-run with --overwrite, etc.).
        if (
            self.execute
            and self._config_apply_blocked
            and option_id in self._CONFIG_MUTATING_OPTIONS
        ):
            meta = MIGRATION_OPTION_METADATA[option_id]
            self.record(
                option_id,
                None,
                None,
                STATUS_SKIPPED,
                REASON_BLOCKED_BY_APPLY_CONFLICT,
                option_label=meta["label"],
            )
            return
        func()

    from _forecast_migration_reports import build_report as build_report

    from _forecast_migration_reports import _build_warnings as _build_warnings

    from _forecast_migration_reports import _build_next_steps as _build_next_steps

    from _forecast_migration_workspace import maybe_backup as maybe_backup

    from _forecast_migration_workspace import write_overflow_entries as write_overflow_entries

    from _forecast_migration_workspace import copy_file as copy_file

    from _forecast_migration_workspace import migrate_soul as migrate_soul

    from _forecast_migration_workspace import migrate_workspace_agents as migrate_workspace_agents

    from _forecast_migration_workspace import migrate_memory as migrate_memory

    from _forecast_migration_preferences import migrate_command_allowlist as migrate_command_allowlist

    def load_openclaw_config(self) -> Dict[str, Any]:
        # Check current name and legacy config filenames
        for name in ("openclaw.json", "clawdbot.json", "moltbot.json"):
            config_path = self.source_root / name
            if config_path.exists():
                try:
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                    return data if isinstance(data, dict) else {}
                except json.JSONDecodeError:
                    continue
        return {}

    from _forecast_migration_channels import load_openclaw_env as load_openclaw_env

    from _forecast_migration_channels import merge_env_values as merge_env_values

    from _forecast_migration_channels import migrate_messaging_settings as migrate_messaging_settings

    from _forecast_migration_channels import handle_secret_settings as handle_secret_settings

    from _forecast_migration_channels import migrate_secret_settings as migrate_secret_settings

    from _forecast_migration_channels import _resolve_channel_secret as _resolve_channel_secret

    from _forecast_migration_channels import _get_channel_field as _get_channel_field
    _get_channel_field = staticmethod(_get_channel_field)

    from _forecast_migration_channels import migrate_discord_settings as migrate_discord_settings

    from _forecast_migration_channels import migrate_slack_settings as migrate_slack_settings

    from _forecast_migration_channels import migrate_whatsapp_settings as migrate_whatsapp_settings

    from _forecast_migration_channels import migrate_signal_settings as migrate_signal_settings

    from _forecast_migration_providers import handle_provider_keys as handle_provider_keys

    from _forecast_migration_providers import migrate_provider_keys as migrate_provider_keys

    from _forecast_migration_providers import migrate_model_config as migrate_model_config

    from _forecast_migration_providers import migrate_tts_config as migrate_tts_config

    from _forecast_migration_skills import migrate_shared_skills as migrate_shared_skills

    from _forecast_migration_skills import _import_skill_directory as _import_skill_directory

    from _forecast_migration_workspace import migrate_daily_memory as migrate_daily_memory

    from _forecast_migration_skills import migrate_skills as migrate_skills

    from _forecast_migration_workspace import copy_tree_non_destructive as copy_tree_non_destructive

    from _forecast_migration_workspace import archive_docs as archive_docs

    from _forecast_migration_workspace import archive_path as archive_path

    # ── MCP servers ─────────────────────────────────────────────
    from _forecast_migration_integrations import migrate_mcp_servers as migrate_mcp_servers

    # ── Plugins ───────────────────────────────────────────────
    from _forecast_migration_integrations import migrate_plugins_config as migrate_plugins_config

    # ── Cron jobs ─────────────────────────────────────────────
    from _forecast_migration_integrations import migrate_cron_jobs as migrate_cron_jobs

    # ── Hooks ─────────────────────────────────────────────────
    from _forecast_migration_integrations import migrate_hooks_config as migrate_hooks_config

    # ── Agent config ──────────────────────────────────────────
    from _forecast_migration_preferences import migrate_agent_config as migrate_agent_config

    # ── Gateway config ────────────────────────────────────────
    from _forecast_migration_integrations import migrate_gateway_config as migrate_gateway_config

    # ── Session config ────────────────────────────────────────
    from _forecast_migration_preferences import migrate_session_config as migrate_session_config

    # ── Full model providers ──────────────────────────────────
    from _forecast_migration_integrations import migrate_full_providers as migrate_full_providers

    # ── Deep channel config ───────────────────────────────────
    from _forecast_migration_channels import migrate_deep_channels as migrate_deep_channels

    # ── Browser config ────────────────────────────────────────
    from _forecast_migration_preferences import migrate_browser_config as migrate_browser_config

    # ── Tools config ──────────────────────────────────────────
    from _forecast_migration_preferences import migrate_tools_config as migrate_tools_config

    # ── Approvals config ──────────────────────────────────────
    from _forecast_migration_preferences import migrate_approvals_config as migrate_approvals_config

    # ── Memory backend ────────────────────────────────────────
    from _forecast_migration_integrations import migrate_memory_backend as migrate_memory_backend

    # ── Skills config ─────────────────────────────────────────
    from _forecast_migration_integrations import migrate_skills_config as migrate_skills_config

    # ── UI / Identity ─────────────────────────────────────────
    from _forecast_migration_integrations import migrate_ui_identity as migrate_ui_identity

    # ── Logging / Diagnostics ─────────────────────────────────
    from _forecast_migration_integrations import migrate_logging_config as migrate_logging_config

    # ── Helper: set env var ───────────────────────────────────
    from _forecast_migration_channels import _set_env_var as _set_env_var

    # ── Generate migration notes ──────────────────────────────
    from _forecast_migration_reports import generate_migration_notes as generate_migration_notes
