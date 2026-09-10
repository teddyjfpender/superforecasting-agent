"""Provider credentials, model selection, and speech configuration migration."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from _forecast_migration_files import resolve_secret_input, load_yaml_file, dump_yaml_file, yaml
from _forecast_migration_options import SUPPORTED_SECRET_TARGETS


def handle_provider_keys(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    if not self.migrate_secrets:
        config_path = self.source_root / "openclaw.json"
        self.record(
            "provider-keys",
            config_path,
            self.target_root / ".env",
            "skipped",
            "Secret migration disabled. Re-run with --migrate-secrets to import provider API keys.",
            supported_targets=sorted(SUPPORTED_SECRET_TARGETS),
        )
        return
    self.migrate_provider_keys(config)


def migrate_provider_keys(self, config: Dict[str, Any]) -> None:
    secret_additions: Dict[str, str] = {}

    # Extract provider API keys from models.providers
    # Note: apiKey values can be strings, env templates, or SecretRef objects
    openclaw_env = self.load_openclaw_env()
    providers = config.get("models", {}).get("providers", {})
    if isinstance(providers, dict):
        for provider_name, provider_cfg in providers.items():
            if not isinstance(provider_cfg, dict):
                continue
            raw_key = provider_cfg.get("apiKey")
            api_key = resolve_secret_input(raw_key, openclaw_env)
            if not api_key:
                # Warn if a SecretRef with file/exec source was silently unresolvable
                if isinstance(raw_key, dict) and raw_key.get("source") in {"file", "exec"}:
                    self.record(
                        "provider-keys",
                        self.source_root / "openclaw.json",
                        None,
                        "skipped",
                        f"Provider '{provider_name}' uses a {raw_key['source']}-backed SecretRef "
                        f"that cannot be auto-migrated. Add this key manually via: superforecasting-agent config set",
                    )
                continue

            base_url = provider_cfg.get("baseUrl", "")
            api_type = provider_cfg.get("api", "")
            env_var = None

            # Match by baseUrl first
            if isinstance(base_url, str):
                if "openrouter" in base_url.lower():
                    env_var = "OPENROUTER_API_KEY"
                elif "openai.com" in base_url.lower():
                    env_var = "OPENAI_API_KEY"
                elif "anthropic" in base_url.lower():
                    env_var = "ANTHROPIC_API_KEY"

            # Match by api type
            if not env_var and isinstance(api_type, str) and api_type == "anthropic-messages":
                env_var = "ANTHROPIC_API_KEY"

            # Match by provider name
            if not env_var:
                name_lower = provider_name.lower()
                if name_lower == "openrouter":
                    env_var = "OPENROUTER_API_KEY"
                elif "openai" in name_lower:
                    env_var = "OPENAI_API_KEY"

            if env_var:
                secret_additions[env_var] = api_key

    # Extract TTS API keys
    tts = config.get("messages", {}).get("tts", {})
    if isinstance(tts, dict):
        elevenlabs = tts.get("elevenlabs", {})
        if isinstance(elevenlabs, dict):
            el_key = elevenlabs.get("apiKey")
            if isinstance(el_key, str) and el_key.strip():
                secret_additions["ELEVENLABS_API_KEY"] = el_key.strip()
        openai_tts = tts.get("openai", {})
        if isinstance(openai_tts, dict):
            oai_key = openai_tts.get("apiKey")
            if isinstance(oai_key, str) and oai_key.strip():
                secret_additions["VOICE_TOOLS_OPENAI_KEY"] = oai_key.strip()

    # Also check the OpenClaw .env file — many users store keys there
    # instead of inline in openclaw.json
    openclaw_env = self.load_openclaw_env()
    env_key_mapping = {
        "OPENROUTER_API_KEY": "OPENROUTER_API_KEY",
        "OPENAI_API_KEY": "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY": "ANTHROPIC_API_KEY",
        "ELEVENLABS_API_KEY": "ELEVENLABS_API_KEY",
        "TELEGRAM_BOT_TOKEN": "TELEGRAM_BOT_TOKEN",
        "DEEPSEEK_API_KEY": "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY": "GEMINI_API_KEY",
        "ZAI_API_KEY": "ZAI_API_KEY",
        "MINIMAX_API_KEY": "MINIMAX_API_KEY",
    }
    for oc_key, target_key in env_key_mapping.items():
        val = openclaw_env.get(oc_key, "").strip()
        if val and target_key not in secret_additions:
            secret_additions[target_key] = val

    # Check the openclaw.json "env" sub-object — some OpenClaw setups
    # store API keys here instead of in a separate .env file.
    # Keys can be at env.<KEY> or env.vars.<KEY>.
    json_env = config.get("env")
    if isinstance(json_env, dict):
        env_vars = json_env.get("vars")
        sources = [json_env]
        if isinstance(env_vars, dict):
            sources.append(env_vars)
        for src in sources:
            for oc_key, target_key in env_key_mapping.items():
                val = src.get(oc_key)
                if isinstance(val, str) and val.strip() and target_key not in secret_additions:
                    secret_additions[target_key] = val.strip()

    # Check per-agent auth-profiles.json for additional credentials
    auth_profiles_path = self.source_root / "agents" / "main" / "agent" / "auth-profiles.json"
    if auth_profiles_path.exists():
        try:
            profiles = json.loads(auth_profiles_path.read_text(encoding="utf-8"))
            if isinstance(profiles, dict):
                # auth-profiles.json wraps profiles in a "profiles" key
                profile_entries = profiles.get("profiles", profiles) if isinstance(profiles.get("profiles"), dict) else profiles
                for profile_name, profile_data in profile_entries.items():
                    if not isinstance(profile_data, dict):
                        continue
                    # Canonical field is "key", "apiKey" is accepted as alias
                    api_key = profile_data.get("key", "") or profile_data.get("apiKey", "")
                    if not isinstance(api_key, str) or not api_key.strip():
                        continue
                    name_lower = profile_name.lower()
                    if "openrouter" in name_lower and "OPENROUTER_API_KEY" not in secret_additions:
                        secret_additions["OPENROUTER_API_KEY"] = api_key.strip()
                    elif "openai" in name_lower and "OPENAI_API_KEY" not in secret_additions:
                        secret_additions["OPENAI_API_KEY"] = api_key.strip()
                    elif "anthropic" in name_lower and "ANTHROPIC_API_KEY" not in secret_additions:
                        secret_additions["ANTHROPIC_API_KEY"] = api_key.strip()
        except (json.JSONDecodeError, OSError):
            pass

    if secret_additions:
        self.merge_env_values(secret_additions, "provider-keys", self.source_root / "openclaw.json")
    else:
        self.record(
            "provider-keys",
            self.source_root / "openclaw.json",
            self.target_root / ".env",
            "skipped",
            "No provider API keys found",
            supported_targets=sorted(SUPPORTED_SECRET_TARGETS),
        )


def migrate_model_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    destination = self.target_root / "config.yaml"
    source_path = self.source_root / "openclaw.json"

    model_value = config.get("agents", {}).get("defaults", {}).get("model")
    if model_value is None:
        self.record("model-config", source_path, destination, "skipped", "No default model found in OpenClaw config")
        return

    if isinstance(model_value, dict):
        model_str = model_value.get("primary")
    else:
        model_str = model_value

    if not isinstance(model_str, str) or not model_str.strip():
        self.record("model-config", source_path, destination, "skipped", "Default model value is empty or invalid")
        return

    model_str = model_str.strip()

    # Resolve a model alias against the OpenClaw model catalog.
    # OpenClaw stores agents.defaults.model as either a bare string or
    # {"primary": "<value>"}, and that value can be either:
    #   - a full provider/model API ID (e.g. "anthropic/claude-opus-4-6"), or
    #   - a display alias (e.g. "Claude Opus 4.6") that maps to one.
    # The catalog at agents.defaults.models is keyed by the full
    # provider/model API ID with an "alias" field on the value, e.g.:
    #   {"anthropic/claude-opus-4-6": {"alias": "Claude Opus 4.6"}}
    # If model_str matches an alias in the catalog, rewrite it to the
    # catalog key (the real API ID).  If it's already an API ID or has
    # no catalog match, leave it alone and let downstream pass it through.
    model_catalog = config.get("agents", {}).get("defaults", {}).get("models", {})
    if isinstance(model_catalog, dict) and model_str not in model_catalog:
        for api_id, entry in model_catalog.items():
            if not isinstance(api_id, str):
                continue
            if isinstance(entry, dict) and entry.get("alias") == model_str:
                model_str = api_id
                break
            if isinstance(entry, str) and entry == model_str:
                model_str = api_id
                break

    if yaml is None:
        self.record("model-config", source_path, destination, "error", "PyYAML is not available")
        return

    target_config = load_yaml_file(destination)
    current_model = target_config.get("model")
    if current_model == model_str:
        self.record("model-config", source_path, destination, "skipped", "Model already set to the same value")
        return
    if current_model and not self.overwrite:
        self.record("model-config", source_path, destination, "conflict", "Model already set and overwrite is disabled", current=current_model, incoming=model_str)
        return

    if self.execute:
        backup_path = self.maybe_backup(destination)
        existing_model = target_config.get("model")
        if isinstance(existing_model, dict):
            existing_model["default"] = model_str
        else:
            target_config["model"] = {"default": model_str}
        dump_yaml_file(destination, target_config)
        self.record("model-config", source_path, destination, "migrated", backup=str(backup_path) if backup_path else "", model=model_str)
    else:
        self.record("model-config", source_path, destination, "migrated", "Would set model", model=model_str)


def migrate_tts_config(self, config: Optional[Dict[str, Any]] = None) -> None:
    config = config or self.load_openclaw_config()
    destination = self.target_root / "config.yaml"
    source_path = self.source_root / "openclaw.json"

    tts = config.get("messages", {}).get("tts", {})
    if not isinstance(tts, dict) or not tts:
        self.record("tts-config", source_path, destination, "skipped", "No TTS configuration found in OpenClaw config")
        return

    if yaml is None:
        self.record("tts-config", source_path, destination, "error", "PyYAML is not available")
        return

    tts_data: Dict[str, Any] = {}

    provider = tts.get("provider")
    if isinstance(provider, str) and provider in {"elevenlabs", "openai", "edge", "microsoft"}:
        # OpenClaw renamed "edge" to "microsoft"; Superforecasting Agent still uses "edge"
        tts_data["provider"] = "edge" if provider == "microsoft" else provider

    # TTS provider settings live under messages.tts.providers.{provider}
    # in OpenClaw (not messages.tts.elevenlabs directly)
    providers = tts.get("providers") or {}

    # Also check the top-level "talk" config which has provider settings too
    talk_cfg = (config or self.load_openclaw_config()).get("talk") or {}
    talk_providers = talk_cfg.get("providers") or {}

    # Merge: messages.tts.providers takes priority, then talk.providers,
    # then legacy flat keys (messages.tts.elevenlabs, etc.)
    elevenlabs = (
        (providers.get("elevenlabs") or {})
        if isinstance(providers.get("elevenlabs"), dict) else
        (talk_providers.get("elevenlabs") or {})
        if isinstance(talk_providers.get("elevenlabs"), dict) else
        (tts.get("elevenlabs") or {})
    )
    if isinstance(elevenlabs, dict):
        el_settings: Dict[str, str] = {}
        voice_id = elevenlabs.get("voiceId") or talk_cfg.get("voiceId")
        if isinstance(voice_id, str) and voice_id.strip():
            el_settings["voice_id"] = voice_id.strip()
        model_id = elevenlabs.get("modelId") or talk_cfg.get("modelId")
        if isinstance(model_id, str) and model_id.strip():
            el_settings["model_id"] = model_id.strip()
        if el_settings:
            tts_data["elevenlabs"] = el_settings

    openai_tts = (
        (providers.get("openai") or {})
        if isinstance(providers.get("openai"), dict) else
        (talk_providers.get("openai") or {})
        if isinstance(talk_providers.get("openai"), dict) else
        (tts.get("openai") or {})
    )
    if isinstance(openai_tts, dict):
        oai_settings: Dict[str, str] = {}
        oai_model = openai_tts.get("model") or openai_tts.get("modelId")
        if isinstance(oai_model, str) and oai_model.strip():
            oai_settings["model"] = oai_model.strip()
        oai_voice = openai_tts.get("voice")
        if isinstance(oai_voice, str) and oai_voice.strip():
            oai_settings["voice"] = oai_voice.strip()
        if oai_settings:
            tts_data["openai"] = oai_settings

    edge_tts = (
        (providers.get("edge") or providers.get("microsoft") or {})
        if isinstance(providers.get("edge"), dict) or isinstance(providers.get("microsoft"), dict) else
        (tts.get("edge") or tts.get("microsoft") or {})
    )
    if isinstance(edge_tts, dict):
        edge_voice = edge_tts.get("voice")
        if isinstance(edge_voice, str) and edge_voice.strip():
            tts_data["edge"] = {"voice": edge_voice.strip()}

    if not tts_data:
        self.record("tts-config", source_path, destination, "skipped", "No compatible TTS settings found")
        return

    target_config = load_yaml_file(destination)
    existing_tts = target_config.get("tts", {})
    if not isinstance(existing_tts, dict):
        existing_tts = {}

    if self.execute:
        backup_path = self.maybe_backup(destination)
        merged_tts = dict(existing_tts)
        for key, value in tts_data.items():
            if isinstance(value, dict) and isinstance(merged_tts.get(key), dict):
                merged_tts[key] = {**merged_tts[key], **value}
            else:
                merged_tts[key] = value
        target_config["tts"] = merged_tts
        dump_yaml_file(destination, target_config)
        self.record("tts-config", source_path, destination, "migrated", backup=str(backup_path) if backup_path else "", settings=list(tts_data.keys()))
    else:
        self.record("tts-config", source_path, destination, "migrated", "Would set TTS config", settings=list(tts_data.keys()))
