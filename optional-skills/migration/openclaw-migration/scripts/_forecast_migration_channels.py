"""Messaging settings, allowlisted channel secrets, and environment merging."""

from __future__ import annotations

from _forecast_migration_reports import write_config_archive

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from _forecast_migration_files import parse_env_file, save_env_file, resolve_secret_input
from _forecast_migration_options import SUPPORTED_SECRET_TARGETS
from _forecast_migration_workspace import migrate_workspace_cwd


def load_openclaw_env(self) -> Dict[str, str]:
    """Load the OpenClaw .env file for secrets that live there instead of config."""
    return parse_env_file(self.source_root / ".env")


def merge_env_values(self, additions: Dict[str, str], kind: str, source: Path) -> None:
    destination = self.target_root / ".env"
    env_data = parse_env_file(destination)
    added: Dict[str, str] = {}
    conflicts: List[str] = []

    for key, value in additions.items():
        current = env_data.get(key)
        if current == value:
            continue
        if current and not self.overwrite:
            conflicts.append(key)
            continue
        env_data[key] = value
        added[key] = value

    if conflicts and not added:
        self.record(kind, source, destination, "conflict", "Destination .env already has different values", conflicting_keys=conflicts)
        return
    if not conflicts and not added:
        self.record(kind, source, destination, "skipped", "All env values already present")
        return

    if self.execute:
        backup_path = self.maybe_backup(destination)
        save_env_file(destination, env_data)
        self.record(
            kind,
            source,
            destination,
            "migrated",
            backup=str(backup_path) if backup_path else "",
            added_keys=sorted(added.keys()),
            conflicting_keys=conflicts,
        )
    else:
        self.record(
            kind,
            source,
            destination,
            "migrated",
            "Would merge env values",
            added_keys=sorted(added.keys()),
            conflicting_keys=conflicts,
        )


def migrate_messaging_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    additions: Dict[str, str] = {}

    workspace_found = False
    workspace = (
        config.get("agents", {})
        .get("defaults", {})
        .get("workspace")
    )
    if isinstance(workspace, str) and workspace.strip():
        ws_path = workspace.strip()
        # Skip if the workspace points inside the OpenClaw source directory —
        # that path will be stale after migration and would cause the Superforecasting Agent
        # gateway to use the old OpenClaw workspace as its cwd, picking up
        # OpenClaw's AGENTS.md, MEMORY.md, etc.
        try:
            inside_source = Path(ws_path).resolve().is_relative_to(self.source_root.resolve())
        except (ValueError, OSError):
            inside_source = False
        if not inside_source:
            workspace_found = True
            migrate_workspace_cwd(self, ws_path)

    allowlist_path = self.source_root / "credentials" / "telegram-default-allowFrom.json"
    if allowlist_path.exists():
        try:
            allow_data = json.loads(allowlist_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self.record("messaging-settings", allowlist_path, self.target_root / ".env", "error", "Invalid JSON in Telegram allowlist file")
        else:
            allow_from = allow_data.get("allowFrom", [])
            if isinstance(allow_from, list):
                users = [str(user).strip() for user in allow_from if str(user).strip()]
                if users:
                    additions["TELEGRAM_ALLOWED_USERS"] = ",".join(users)

    if additions:
        self.merge_env_values(additions, "messaging-settings", self.source_root / "openclaw.json")
    elif not workspace_found:
        self.record("messaging-settings", self.source_root / "openclaw.json", self.target_root / ".env", "skipped", "No Superforecasting Agent-compatible messaging settings found")


def handle_secret_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    if self.migrate_secrets:
        self.migrate_secret_settings(config)
        return

    config_path = self.source_root / "openclaw.json"
    if config_path.exists():
        self.record(
            "secret-settings",
            config_path,
            self.target_root / ".env",
            "skipped",
            "Secret migration disabled. Re-run with --migrate-secrets to import allowlisted secrets.",
            supported_targets=sorted(SUPPORTED_SECRET_TARGETS),
        )
    else:
        self.record(
            "secret-settings",
            config_path,
            self.target_root / ".env",
            "skipped",
            "OpenClaw config file not found",
            supported_targets=sorted(SUPPORTED_SECRET_TARGETS),
        )


def migrate_secret_settings(self, config: Dict[str, Any]) -> None:
    secret_additions: Dict[str, str] = {}

    tg_cfg = config.get("channels", {}).get("telegram", {})
    telegram_token = self._get_channel_field(tg_cfg, "botToken") if isinstance(tg_cfg, dict) else None
    if isinstance(telegram_token, str) and telegram_token.strip():
        secret_additions["TELEGRAM_BOT_TOKEN"] = telegram_token.strip()

    if secret_additions:
        self.merge_env_values(secret_additions, "secret-settings", self.source_root / "openclaw.json")
    else:
        self.record(
            "secret-settings",
            self.source_root / "openclaw.json",
            self.target_root / ".env",
            "skipped",
            "No allowlisted Superforecasting Agent-compatible secrets found",
            supported_targets=sorted(SUPPORTED_SECRET_TARGETS),
        )


def _resolve_channel_secret(self, value: Any) -> Optional[str]:
    """Resolve a channel config value that may be a SecretRef."""
    return resolve_secret_input(value, self.load_openclaw_env())


def _get_channel_field(ch_cfg: Dict[str, Any], field: str) -> Any:
    """Get a field from channel config, checking both flat and accounts.default layout."""
    val = ch_cfg.get(field)
    if val is not None:
        return val
    accounts = ch_cfg.get("accounts")
    if isinstance(accounts, dict):
        default = accounts.get("default")
        if isinstance(default, dict):
            return default.get(field)
    return None


def migrate_discord_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    additions: Dict[str, str] = {}
    discord = config.get("channels", {}).get("discord", {})
    if isinstance(discord, dict):
        token = self._get_channel_field(discord, "token")
        if self.migrate_secrets and isinstance(token, str) and token.strip():
            additions["DISCORD_BOT_TOKEN"] = token.strip()
        allow_from = self._get_channel_field(discord, "allowFrom") or []
        if isinstance(allow_from, list):
            users = [str(u).strip() for u in allow_from if str(u).strip()]
            if users:
                additions["DISCORD_ALLOWED_USERS"] = ",".join(users)
    if additions:
        self.merge_env_values(additions, "discord-settings", self.source_root / "openclaw.json")
    else:
        self.record("discord-settings", self.source_root / "openclaw.json", self.target_root / ".env", "skipped", "No Discord settings found")


def migrate_slack_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    additions: Dict[str, str] = {}
    slack = config.get("channels", {}).get("slack", {})
    if isinstance(slack, dict):
        bot_token = self._get_channel_field(slack, "botToken")
        if self.migrate_secrets and isinstance(bot_token, str) and bot_token.strip():
            additions["SLACK_BOT_TOKEN"] = bot_token.strip()
        app_token = self._get_channel_field(slack, "appToken")
        if self.migrate_secrets and isinstance(app_token, str) and app_token.strip():
            additions["SLACK_APP_TOKEN"] = app_token.strip()
        allow_from = self._get_channel_field(slack, "allowFrom") or []
        if isinstance(allow_from, list):
            users = [str(u).strip() for u in allow_from if str(u).strip()]
            if users:
                additions["SLACK_ALLOWED_USERS"] = ",".join(users)
    if additions:
        self.merge_env_values(additions, "slack-settings", self.source_root / "openclaw.json")
    else:
        self.record("slack-settings", self.source_root / "openclaw.json", self.target_root / ".env", "skipped", "No Slack settings found")


def migrate_whatsapp_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    additions: Dict[str, str] = {}
    whatsapp = config.get("channels", {}).get("whatsapp", {})
    if isinstance(whatsapp, dict):
        allow_from = self._get_channel_field(whatsapp, "allowFrom") or []
        if isinstance(allow_from, list):
            users = [str(u).strip() for u in allow_from if str(u).strip()]
            if users:
                additions["WHATSAPP_ALLOWED_USERS"] = ",".join(users)
    if additions:
        self.merge_env_values(additions, "whatsapp-settings", self.source_root / "openclaw.json")
    else:
        self.record("whatsapp-settings", self.source_root / "openclaw.json", self.target_root / ".env", "skipped", "No WhatsApp settings found")


def migrate_signal_settings(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    additions: Dict[str, str] = {}
    signal = config.get("channels", {}).get("signal", {})
    if isinstance(signal, dict):
        account = self._get_channel_field(signal, "account")
        if isinstance(account, str) and account.strip():
            additions["SIGNAL_ACCOUNT"] = account.strip()
        http_url = self._get_channel_field(signal, "httpUrl")
        if isinstance(http_url, str) and http_url.strip():
            additions["SIGNAL_HTTP_URL"] = http_url.strip()
        allow_from = self._get_channel_field(signal, "allowFrom") or []
        if isinstance(allow_from, list):
            users = [str(u).strip() for u in allow_from if str(u).strip()]
            if users:
                additions["SIGNAL_ALLOWED_USERS"] = ",".join(users)
    if additions:
        self.merge_env_values(additions, "signal-settings", self.source_root / "openclaw.json")
    else:
        self.record("signal-settings", self.source_root / "openclaw.json", self.target_root / ".env", "skipped", "No Signal settings found")


from _forecast_migration_files import load_yaml_file, dump_yaml_file

def migrate_deep_channels(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    channels = config.get("channels") or {}
    if not channels:
        self.record("deep-channels", None, None, "skipped", "No channel configuration found")
        return

    # Extended channel token/allowlist mapping
    CHANNEL_ENV_MAP = {
        "matrix": {"token": "MATRIX...OKEN", "tokenField": "accessToken", "allowFrom": "MATRIX_ALLOWED_USERS",
                    "extras": {"homeserverUrl": "MATRIX_HOMESERVER_URL", "userId": "MATRIX_USER_ID"}},
        "mattermost": {"token": "MATTERMOST_BOT_TOKEN", "allowFrom": "MATTERMOST_ALLOWED_USERS",
                       "extras": {"url": "MATTERMOST_URL", "teamId": "MATTERMOST_TEAM_ID"}},
        "irc": {"extras": {"server": "IRC_SERVER", "nick": "IRC_NICK", "channels": "IRC_CHANNELS"}},
        "googlechat": {"extras": {"serviceAccountKeyPath": "GOOGLE_CHAT_SA_KEY_PATH"}},
        "imessage": {},
        "bluebubbles": {"extras": {"server": "BLUEBUBBLES_SERVER", "password": "BLUEBUBBLES_PASSWORD"}},
        "msteams": {"token": "MSTEAMS_BOT_TOKEN", "allowFrom": "MSTEAMS_ALLOWED_USERS"},
        "nostr": {"extras": {"nsec": "NOSTR_NSEC", "relays": "NOSTR_RELAYS"}},
        "twitch": {"token": "TWITCH_BOT_TOKEN", "extras": {"channels": "TWITCH_CHANNELS"}},
    }

    for ch_name, ch_mapping in CHANNEL_ENV_MAP.items():
        ch_cfg = channels.get(ch_name) or {}
        if not ch_cfg:
            continue

        # Extract tokens (check flat path, then accounts.default)
        token_field = ch_mapping.get("tokenField", "botToken")
        bot_token = self._get_channel_field(ch_cfg, token_field)
        if ch_mapping.get("token") and bot_token and self.migrate_secrets:
            self._set_env_var(ch_mapping["token"], str(bot_token),
                              f"channels.{ch_name}.{token_field}")
        allow_val = self._get_channel_field(ch_cfg, "allowFrom")
        if ch_mapping.get("allowFrom") and allow_val:
            if isinstance(allow_val, list):
                allow_val = ",".join(str(x) for x in allow_val)
            self._set_env_var(ch_mapping["allowFrom"], str(allow_val),
                              f"channels.{ch_name}.allowFrom")
        # Extra fields
        for oc_key, env_key in (ch_mapping.get("extras") or {}).items():
            val = self._get_channel_field(ch_cfg, oc_key)
            if val:
                if isinstance(val, list):
                    val = ",".join(str(x) for x in val)
                is_secret = "password" in oc_key.lower() or "token" in oc_key.lower() or "nsec" in oc_key.lower()
                if is_secret and not self.migrate_secrets:
                    continue
                self._set_env_var(env_key, str(val), f"channels.{ch_name}.{oc_key}")

    # Map Discord-specific settings to Superforecasting Agent config
    discord_cfg = channels.get("discord") or {}
    if discord_cfg:
        target_config_path = self.target_root / "config.yaml"
        target_config = load_yaml_file(target_config_path)
        target_discord = target_config.get("discord") or {}
        changed = False
        if "requireMention" in discord_cfg:
            target_discord["require_mention"] = discord_cfg["requireMention"]
            changed = True
        if discord_cfg.get("autoThread") is not None:
            target_discord["auto_thread"] = discord_cfg["autoThread"]
            changed = True
        if changed and self.execute:
            target_config["discord"] = target_discord
            dump_yaml_file(target_config_path, target_config)

    # Archive complex channel configs (group settings, thread bindings, etc.)
    complex_archive = {}
    for ch_name, ch_cfg in channels.items():
        if not isinstance(ch_cfg, dict):
            continue
        complex_keys = {k: v for k, v in ch_cfg.items()
                      if k not in {"botToken", "appToken", "allowFrom", "enabled"}
                      and v and k not in {"requireMention", "autoThread"}}
        if complex_keys:
            complex_archive[ch_name] = complex_keys

    if complex_archive and self.archive_dir:
        if self.execute:
            self.archive_dir.mkdir(parents=True, exist_ok=True)
            dest = self.archive_dir / "channels-deep-config.json"
            write_config_archive(dest, complex_archive)
        self.record("deep-channels", "openclaw.json channels (advanced settings)",
                    "archive/channels-deep-config.json", "archived",
                    f"Deep channel config for {len(complex_archive)} channels archived")


def _set_env_var(self, key: str, value: str, source_label: str) -> None:
    env_path = self.target_root / ".env"
    if self.execute:
        env_data = parse_env_file(env_path)
        if key in env_data and not self.overwrite:
            self.record("env-var", source_label, f".env {key}", "conflict",
                        f"Env var {key} already set")
            return
        env_data[key] = value
        save_env_file(env_path, env_data)
    self.record("env-var", source_label, f".env {key}", "migrated")
