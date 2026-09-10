"""External integrations and archived OpenClaw service configuration."""

from __future__ import annotations

from _forecast_migration_reports import write_config_archive

import shutil
from typing import Any, Dict, Optional

from _forecast_migration_files import load_yaml_file, dump_yaml_file


def migrate_mcp_servers(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    mcp_raw = (config.get("mcp") or {}).get("servers") or {}
    if not mcp_raw:
        self.record("mcp-servers", None, None, "skipped", "No MCP servers found in OpenClaw config")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    existing_mcp = target_config.get("mcp_servers") or {}
    added = 0

    for name, srv in mcp_raw.items():
        if not isinstance(srv, dict):
            continue
        if name in existing_mcp and not self.overwrite:
            self.record("mcp-servers", f"mcp.servers.{name}", f"mcp_servers.{name}", "conflict",
                        "MCP server already exists in Superforecasting Agent config")
            continue

        target_server: Dict[str, Any] = {}
        # STDIO transport
        if srv.get("command"):
            target_server["command"] = srv["command"]
            if srv.get("args"):
                target_server["args"] = srv["args"]
            if self.migrate_secrets and srv.get("env"):
                target_server["env"] = srv["env"]
            if srv.get("cwd"):
                target_server["cwd"] = srv["cwd"]
        # HTTP/SSE transport
        if srv.get("url"):
            target_server["url"] = srv["url"]
            if self.migrate_secrets and srv.get("headers"):
                target_server["headers"] = srv["headers"]
            if self.migrate_secrets and srv.get("auth"):
                target_server["auth"] = srv["auth"]
        # Common fields
        if srv.get("enabled") is False:
            target_server["enabled"] = False
        if srv.get("timeout"):
            target_server["timeout"] = srv["timeout"]
        if srv.get("connectTimeout"):
            target_server["connect_timeout"] = srv["connectTimeout"]
        # Tool filtering
        tools_cfg = srv.get("tools") or {}
        if tools_cfg.get("include") or tools_cfg.get("exclude"):
            target_server["tools"] = {}
            if tools_cfg.get("include"):
                target_server["tools"]["include"] = tools_cfg["include"]
            if tools_cfg.get("exclude"):
                target_server["tools"]["exclude"] = tools_cfg["exclude"]
        # Sampling
        sampling = srv.get("sampling")
        if sampling and isinstance(sampling, dict):
            target_server["sampling"] = {
                k: v for k, v in {
                    "enabled": sampling.get("enabled"),
                    "model": sampling.get("model"),
                    "max_tokens_cap": sampling.get("maxTokensCap") or sampling.get("max_tokens_cap"),
                    "timeout": sampling.get("timeout"),
                    "max_rpm": sampling.get("maxRpm") or sampling.get("max_rpm"),
                }.items() if v is not None
            }

        if not self.migrate_secrets and any(srv.get(field) for field in ("env", "headers", "auth")):
            self.record("mcp-servers", f"mcp.servers.{name}", f"mcp_servers.{name}", "skipped",
                        "Credential fields (env, headers, auth) omitted; use --migrate-secrets to import them.")
        existing_mcp[name] = target_server
        added += 1
        self.record("mcp-servers", f"mcp.servers.{name}", f"config.yaml mcp_servers.{name}",
                    "migrated", servers_added=added)

    if added > 0 and self.execute:
        self.maybe_backup(target_config_path)
        target_config["mcp_servers"] = existing_mcp
        dump_yaml_file(target_config_path, target_config)


def migrate_plugins_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    plugins = config.get("plugins") or {}
    if not plugins:
        self.record("plugins-config", None, None, "skipped", "No plugins configuration found")
        return

    # Archive the full plugins config
    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "plugins-config.json"
        write_config_archive(dest, plugins)
        self.record("plugins-config", "openclaw.json plugins.*", str(dest), "archived",
                    "Plugins config archived for manual review")
    else:
        self.record("plugins-config", "openclaw.json plugins.*", "archive/plugins-config.json",
                    "archived" if not self.execute else "migrated", "Would archive plugins config")

    # Copy extensions directory if it exists
    ext_dir = self.source_root / "extensions"
    if ext_dir.is_dir() and self.archive_dir:
        dest_ext = self.archive_dir / "extensions"
        if self.execute:
            shutil.copytree(ext_dir, dest_ext, dirs_exist_ok=True)
        self.record("plugins-config", str(ext_dir), str(dest_ext), "archived",
                    "Extensions directory archived")

    # Extract any plugin env vars
    entries = plugins.get("entries") or {}
    for plugin_name, plugin_cfg in entries.items():
        if isinstance(plugin_cfg, dict):
            env_vars = plugin_cfg.get("env") or {}
            api_key = plugin_cfg.get("apiKey")
            if api_key and self.migrate_secrets:
                env_key = f"PLUGIN_{plugin_name.upper().replace('-', '_')}_API_KEY"
                self._set_env_var(env_key, api_key, f"plugins.entries.{plugin_name}.apiKey")


def migrate_cron_jobs(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    cron = config.get("cron") or {}
    cron_store = self.source_root / "cron"
    found_any = False

    # Archive the full cron config when present
    if cron:
        found_any = True
        if self.archive_dir and self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "cron-config.json"
            write_config_archive(dest, cron)
            self.record("cron-jobs", "openclaw.json cron.*", str(dest), "archived",
                        "Cron config archived. Use 'superforecasting-agent cron' to recreate jobs manually.")
        else:
            self.record("cron-jobs", "openclaw.json cron.*", "archive/cron-config.json",
                        "archived", "Would archive cron config")

    # Also check for cron store files even when config.cron is missing
    if cron_store.is_dir() and self.archive_dir:
        found_any = True
        dest_cron = self.archive_dir / "cron-store"
        if self.execute:
            shutil.copytree(cron_store, dest_cron, dirs_exist_ok=True)
        self.record("cron-jobs", str(cron_store), str(dest_cron), "archived",
                    "Cron job store archived")

    if not found_any:
        self.record("cron-jobs", None, None, "skipped", "No cron configuration found")


def migrate_hooks_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    hooks = config.get("hooks") or {}
    if not hooks:
        self.record("hooks-config", None, None, "skipped", "No hooks configuration found")
        return

    # Archive the full hooks config
    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "hooks-config.json"
        write_config_archive(dest, hooks)
        self.record("hooks-config", "openclaw.json hooks.*", str(dest), "archived",
                    "Hooks config archived for manual review")
    else:
        self.record("hooks-config", "openclaw.json hooks.*", "archive/hooks-config.json",
                    "archived", "Would archive hooks config")

    # Copy workspace hooks directory
    for ws_name in ("workspace", "workspace.default"):
        hooks_dir = self.source_root / ws_name / "hooks"
        if hooks_dir.is_dir() and self.archive_dir:
            dest_hooks = self.archive_dir / "workspace-hooks"
            if self.execute:
                shutil.copytree(hooks_dir, dest_hooks, dirs_exist_ok=True)
            self.record("hooks-config", str(hooks_dir), str(dest_hooks), "archived",
                        "Workspace hooks directory archived")
            break


def migrate_gateway_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    gateway = config.get("gateway") or {}
    if not gateway:
        self.record("gateway-config", None, None, "skipped", "No gateway configuration found")
        return

    # Archive the full gateway config (complex, many settings)
    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "gateway-config.json"
        write_config_archive(dest, gateway)
    self.record("gateway-config", "openclaw.json gateway.*", "archive/gateway-config.json",
                "archived", "Gateway config archived. Use 'superforecasting-agent gateway' to configure.")

    # Extract gateway auth token to .env if present
    auth = gateway.get("auth") or {}
    if auth.get("token") and self.migrate_secrets:
        self._set_env_var("HERMES_GATEWAY_TOKEN", auth["token"], "gateway.auth.token")


def migrate_full_providers(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    models = config.get("models") or {}
    providers = models.get("providers") or {}
    if not providers:
        self.record("full-providers", None, None, "skipped", "No model providers found")
        return

    target_config_path = self.target_root / "config.yaml"
    target_config = load_yaml_file(target_config_path)
    custom_providers = target_config.get("custom_providers") or []
    added = 0

    # Well-known providers: just extract API keys
    WELL_KNOWN = {"openrouter", "openai", "anthropic", "deepseek", "google", "groq"}

    for prov_name, prov_cfg in providers.items():
        if not isinstance(prov_cfg, dict):
            continue

        # Extract API key to .env
        api_key = prov_cfg.get("apiKey") or prov_cfg.get("api_key")
        if api_key and self.migrate_secrets:
            env_key = f"{prov_name.upper().replace('-', '_')}_API_KEY"
            self._set_env_var(env_key, api_key, f"models.providers.{prov_name}.apiKey")

        # For non-well-known providers, create custom_providers entry
        if prov_name.lower() not in WELL_KNOWN and prov_cfg.get("baseUrl"):
            # Check if already exists
            existing_names = {p.get("name", "").lower() for p in custom_providers}
            if prov_name.lower() in existing_names and not self.overwrite:
                self.record("full-providers", f"models.providers.{prov_name}",
                            "config.yaml custom_providers", "conflict",
                            f"Provider '{prov_name}' already exists")
                continue

            api_type = prov_cfg.get("apiType") or prov_cfg.get("api") or prov_cfg.get("type") or "openai"
            api_mode_map = {
                "openai": "chat_completions",
                "openai-completions": "chat_completions",
                "openai-responses": "chat_completions",
                "anthropic": "anthropic_messages",
                "anthropic-messages": "anthropic_messages",
                "google-generative-ai": "chat_completions",
                "cohere": "chat_completions",
            }
            entry = {
                "name": prov_name,
                "base_url": prov_cfg["baseUrl"],
                "api_key": "",  # referenced from .env
                "api_mode": api_mode_map.get(api_type, "chat_completions"),
            }
            custom_providers.append(entry)
            added += 1
            self.record("full-providers", f"models.providers.{prov_name}",
                        f"config.yaml custom_providers[{prov_name}]", "migrated")

    if added > 0 and self.execute:
        self.maybe_backup(target_config_path)
        target_config["custom_providers"] = custom_providers
        dump_yaml_file(target_config_path, target_config)

    # Archive model aliases/catalog
    agent_defaults = (config.get("agents") or {}).get("defaults") or {}
    model_aliases = agent_defaults.get("models") or {}
    if model_aliases:
        if self.archive_dir and self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "model-aliases.json"
            write_config_archive(dest, model_aliases)
        self.record("full-providers", "agents.defaults.models", "archive/model-aliases.json",
                    "archived", f"Model aliases/catalog ({len(model_aliases)} entries) archived")


def migrate_memory_backend(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    memory = config.get("memory") or {}
    if not memory:
        self.record("memory-backend", None, None, "skipped", "No memory backend configuration found")
        return

    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "memory-backend-config.json"
        write_config_archive(dest, memory)
    self.record("memory-backend", "openclaw.json memory.*", "archive/memory-backend-config.json",
                "archived", "Memory backend config (QMD, vector search, citations) archived for manual review")


def migrate_skills_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    skills = config.get("skills") or {}
    entries = skills.get("entries") or {}
    if not entries and not skills:
        self.record("skills-config", None, None, "skipped", "No skills registry configuration found")
        return

    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "skills-registry-config.json"
        write_config_archive(dest, skills)
    self.record("skills-config", "openclaw.json skills.*", "archive/skills-registry-config.json",
                "archived", f"Skills registry config ({len(entries)} entries) archived")


def migrate_ui_identity(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    ui = config.get("ui") or {}
    if not ui:
        self.record("ui-identity", None, None, "skipped", "No UI/identity configuration found")
        return

    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "ui-identity-config.json"
        write_config_archive(dest, ui)
    self.record("ui-identity", "openclaw.json ui.*", "archive/ui-identity-config.json",
                "archived", "UI theme and identity settings archived")


def migrate_logging_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    logging_cfg = config.get("logging") or {}
    diagnostics = config.get("diagnostics") or {}
    combined = {}
    if logging_cfg:
        combined["logging"] = logging_cfg
    if diagnostics:
        combined["diagnostics"] = diagnostics
    if not combined:
        self.record("logging-config", None, None, "skipped", "No logging/diagnostics configuration found")
        return

    if self.archive_dir and self.execute:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        dest = self.archive_dir / "logging-diagnostics-config.json"
        write_config_archive(dest, combined)
    self.record("logging-config", "openclaw.json logging/diagnostics",
                "archive/logging-diagnostics-config.json", "archived")
