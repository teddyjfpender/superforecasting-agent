"""
Configuration management for Superforecasting Agent.

Config files are stored in the runtime home for easy access:
- config.yaml  - All settings (model, toolsets, terminal, etc.)
- .env         - API keys and secrets

This module provides:
- superforecasting-agent config          - Show current configuration
- superforecasting-agent config edit     - Open config in editor
- superforecasting-agent config set      - Set a specific value
- superforecasting-agent config wizard   - Re-run setup wizard
"""

import copy
import logging
import os
import platform
import re
import stat
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from superforecasting_agent.paths import get_install_root
from typing import Dict, Any, Optional, List, Tuple

from superforecasting_agent.runtime.secret_prompt import masked_secret_prompt

logger = logging.getLogger(__name__)
_PRIMARY_CLI = "superforecasting-agent"
from superforecasting_agent.profile_paths import ignore_user_config_requested as _ignore_user_config_requested


def _first_present_env(names: tuple[str, ...], default: str = "") -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name)
        if value is not None:
            return name, value
    return "default", default


def _env_flag_exact_one(names: tuple[str, ...]) -> bool:
    _name, value = _first_present_env(names)
    return value == "1"


# Track which (config_path, mtime_ns, size) tuples we've already warned about
# so concurrent CLI/gateway loads of a broken config.yaml don't spam stderr
# every time. Cleared automatically when the file changes (different mtime).
_CONFIG_PARSE_WARNED: set = set()


def _warn_config_parse_failure(config_path: Path, exc: Exception) -> None:
    """Surface a config.yaml parse failure to user, log, and stderr.

    A YAML parse error in the active agent-home config.yaml causes
    ``load_config()`` to silently fall back to ``DEFAULT_CONFIG``, which means
    every user override (auxiliary providers, fallback chain, model overrides,
    etc.) is dropped. Before this helper that was a one-line ``print(...)``
    that scrolled off-screen on the first invocation and was never seen again.

    Now: warn once per (path, mtime_ns, size) on stderr **and** in
    ``agent.log`` / ``errors.log`` at WARNING level so
    ``superforecasting-agent logs`` surfaces it. Re-warns automatically if the
    file changes (different mtime/size), so users editing the config see the
    next failure.
    """
    try:
        st = config_path.stat()
        key = (str(config_path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = (str(config_path), 0, 0)
    if key in _CONFIG_PARSE_WARNED:
        return
    _CONFIG_PARSE_WARNED.add(key)

    msg = (
        f"Failed to parse {config_path}: {exc}. "
        f"Falling back to default config — every user override "
        f"(auxiliary providers, fallback chain, model settings) is being IGNORED. "
        f"Fix the YAML and restart."
    )
    logger.warning(msg)
    try:
        sys.stderr.write(f"⚠️  superforecasting-agent config: {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass

_IS_WINDOWS = platform.system() == "Windows"
_ENV_VAR_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Env var names that influence how the next subprocess executes —
# never writable through ``save_env_value`` (and therefore not through
# ``save_env_value_secure``, which routes through it). Anything that
# controls the loader, interpreter, shell, or replacement editor counts:
#
# * ``LD_PRELOAD`` / ``LD_LIBRARY_PATH`` / ``LD_AUDIT`` — Linux dynamic
#   loader. ``DYLD_*`` — macOS equivalent. Planting a path here means
#   the next ``subprocess.run([...])`` the agent makes loads attacker
#   code before main().
# * ``PYTHONPATH`` / ``PYTHONHOME`` / ``PYTHONSTARTUP`` /
#   ``PYTHONUSERBASE`` — Python interpreter init. The agent itself
#   starts from one of these on every restart.
# * ``NODE_OPTIONS`` / ``NODE_PATH`` — Node interpreter; affects npm,
#   updates, the TUI build.
# * ``PATH`` — too broad to allow. The dashboard never needs to rewrite
#   the operator's PATH; if a tool can't be found, the fix is to add an
#   absolute path in the integration config, not to mutate PATH globally.
# * ``GIT_SSH_COMMAND`` / ``GIT_EXEC_PATH`` — git rewrites that fire
#   on every plugin install / update.
# * ``BROWSER`` / ``EDITOR`` / ``VISUAL`` / ``PAGER`` — commands the
#   shell or CLI invokes implicitly. Wrong values here = RCE on next
#   ``$EDITOR``.
# * ``SHELL`` — what subprocess uses with ``shell=True`` (we try to
#   avoid that, but defense in depth).
# * ``SUPERFORECASTING_AGENT_HOME`` / ``_PROFILE`` / ``_CONFIG`` /
#   ``_ENV`` (and the ``FORECAST_*`` / ``HERMES_*`` aliases) — agent
#   runtime location flags. Writing these into ``.env`` would relocate
#   state in ways the user did not request from the dashboard.
#   ``config.yaml`` is the supported surface for these.
#
# IMPORTANT: ``SUPERFORECASTING_AGENT_*`` / ``FORECAST_*`` / ``HERMES_*``
# overall is NOT blocked. Many legitimate integration credentials follow
# those prefixes (HERMES_GEMINI_CLIENT_ID, HERMES_LANGFUSE_PUBLIC_KEY,
# HERMES_QWEN_BASE_URL, ...). The denylist is
# name-by-name on purpose so the gate stays narrow and doesn't
# accidentally break provider setup wizards.
#
# This is enforced on *write* only — values already in ``.env`` (set by
# the operator out-of-band, or pre-existing) keep working. The point is
# that the dashboard's writable surface cannot escalate by planting them.
_ENV_VAR_NAME_DENYLIST: frozenset[str] = frozenset({
    # Loader / linker
    "LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG",
    "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "DYLD_FRAMEWORK_PATH",
    "DYLD_FALLBACK_LIBRARY_PATH", "DYLD_FALLBACK_FRAMEWORK_PATH",
    # Python
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "PYTHONEXECUTABLE", "PYTHONNOUSERSITE",
    # Node
    "NODE_OPTIONS", "NODE_PATH",
    # General
    "PATH", "SHELL", "BROWSER", "EDITOR", "VISUAL", "PAGER",
    # Git
    "GIT_SSH_COMMAND", "GIT_EXEC_PATH", "GIT_SHELL",
    # Agent runtime location — never via dashboard env writer.
    # NOT a SUPERFORECASTING_AGENT_*/FORECAST_*/HERMES_* blanket:
    # integration credentials (HERMES_GEMINI_*, HERMES_LANGFUSE_*,
    # ...) ARE allowed. Only these runtime-location
    # names are blocked, and we block all three alias prefixes.
    "SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME",
    "SUPERFORECASTING_AGENT_PROFILE", "FORECAST_PROFILE", "HERMES_PROFILE",
    "SUPERFORECASTING_AGENT_CONFIG", "FORECAST_CONFIG", "HERMES_CONFIG",
    "SUPERFORECASTING_AGENT_ENV", "FORECAST_ENV", "HERMES_ENV",
})


def _reject_denylisted_env_var(key: str) -> None:
    """Raise if ``key`` is in :data:`_ENV_VAR_NAME_DENYLIST`.

    Centralised so both the regular and "secure" env writers share the
    same gate, and so the message is consistent for callers.
    """
    if key in _ENV_VAR_NAME_DENYLIST:
        raise ValueError(
            f"Environment variable {key!r} is on the writer denylist. "
            "Names that influence subprocess execution (LD_PRELOAD, "
            "PYTHONPATH, PATH, EDITOR, ...) or agent runtime location "
            "(SUPERFORECASTING_AGENT_HOME, HERMES_PROFILE, ...) cannot be "
            "persisted via the env writer. If you really need this, edit "
            "~/.superforecasting-agent/.env directly."
        )
_LAST_EXPANDED_CONFIG_BY_PATH: Dict[str, Any] = {}
# Cache by exact file bytes, not timestamps: editors may preserve mtime and size.
# Parsing/merging stays cached, and writable snapshots cannot bless stale values
# with a newer file revision.
_LOAD_CONFIG_CACHE: Dict[str, Tuple[bytes, Dict[str, Any]]] = {}
_RAW_CONFIG_CACHE: Dict[str, Tuple[bytes, Dict[str, Any]]] = {}
# Serializes all config read/write paths. libyaml's C extension is not
# thread-safe for concurrent safe_load() on the same file, and multiple
# tool threads (approval.py, browser_tool.py, setup flows) hit
# load_config / read_raw_config / save_config from different threads
# during long agent runs. RLock (not Lock) because save_config internally
# calls read_raw_config. Also covers mutation of the module-level cache
# dicts above.
_CONFIG_LOCK = threading.RLock()
# Env var names written to .env that aren't in OPTIONAL_ENV_VARS
# (managed by setup/provider flows directly).
from superforecasting_agent.configuration.environment_catalog import _EXTRA_ENV_KEYS as _EXTRA_ENV_KEYS
import yaml

from superforecasting_agent.runtime.colors import Colors, color
from superforecasting_agent.runtime.default_soul import DEFAULT_SOUL_MD


# =============================================================================
# Managed mode (NixOS declarative config)
# =============================================================================


def _managed_env_setting() -> tuple[str, str]:
    from superforecasting_agent.installation import _managed_env_setting as setting

    return setting()


def get_managed_system() -> Optional[str]:
    from superforecasting_agent.installation import get_managed_system as detect

    return detect(get_agent_home())


def is_managed() -> bool:
    """Check if Superforecasting Agent is running in package-managed mode.

    Two signals: a managed-install env var (prefer
    SUPERFORECASTING_AGENT_MANAGED / FORECAST_MANAGED; HERMES_MANAGED remains
    a legacy alias), or a .managed marker file in the agent home (set by the
    NixOS activation script, so interactive shells also see it).
    """
    return get_managed_system() is not None


_NIX_UPDATE_MSG = "Update your Nix flake input and rebuild (e.g. nix flake update, nixos-rebuild, or home-manager switch)"


def get_managed_update_command() -> Optional[str]:
    """Return the preferred upgrade command for a managed install."""
    managed_system = get_managed_system()
    if managed_system == "Homebrew":
        return "brew upgrade superforecasting-agent"
    if managed_system == "NixOS":
        return _NIX_UPDATE_MSG
    return None


def detect_install_method(project_root: Optional[Path] = None) -> str:
    """Detect how Superforecasting Agent was installed.

    Resolution order:
    1. Stamped ``<agent-home>/.install_method`` file (written by installers)
    2. Managed env aliases / .managed marker (NixOS, Homebrew)
    3. Container detection (/.dockerenv, /run/.containerenv, cgroup)
    4. .git directory presence -> 'git'
    5. Fallback -> 'pip'
    """
    stamp = get_agent_home() / ".install_method"
    try:
        method = stamp.read_text(encoding="utf-8").strip().lower()
        if method:
            return method
    except OSError:
        pass
    managed = get_managed_system()
    if managed:
        return managed.lower().replace(" ", "-")
    from superforecasting_agent.constants import is_container
    if is_container():
        return "docker"
    if project_root is None:
        project_root = get_install_root()
    if (project_root / ".git").is_dir():
        return "git"
    return "pip"


def stamp_install_method(method: str) -> None:
    """Write the install method to active agent-home .install_method."""
    stamp = get_agent_home() / ".install_method"
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_text(method + "\n", encoding="utf-8")
    except OSError:
        pass


def recommended_update_command_for_method(method: str) -> str:
    """Return the update command or guidance for a given install method."""
    if method == "nixos":
        return _NIX_UPDATE_MSG
    if method == "homebrew":
        return "brew upgrade superforecasting-agent"
    if method == "docker":
        return "docker pull teddyjfpender/superforecasting-agent:latest"
    if method in {"pip", "pipx", "release"}:
        if _IS_WINDOWS:
            return (
                "irm https://github.com/teddyjfpender/superforecasting-agent/"
                "releases/latest/download/install.ps1 | iex"
            )
        return (
            "curl -fsSL https://github.com/teddyjfpender/superforecasting-agent/"
            "releases/latest/download/install.sh | bash"
        )
    return "superforecasting-agent update"


def recommended_update_command() -> str:
    """Return the best update command for the current installation."""
    managed_cmd = get_managed_update_command()
    if managed_cmd:
        return managed_cmd
    method = detect_install_method()
    return recommended_update_command_for_method(method)


def format_managed_message(action: str = "modify this Superforecasting Agent installation") -> str:
    from superforecasting_agent.installation import format_managed_message as format_message

    return format_message(action, system=get_managed_system(), setting=_managed_env_setting())


def managed_error(action: str = "modify configuration"):
    """Print user-friendly error for managed mode."""
    print(format_managed_message(action), file=sys.stderr)


# =============================================================================
# Container-aware CLI (NixOS container mode)
# =============================================================================

def get_container_exec_info() -> Optional[dict]:
    """Read container mode metadata from the active agent home.

    Returns a dict with keys: backend, container_name, exec_user, hermes_bin
    or None if container mode is not active, we're already inside the
    container, or HERMES_DEV=1 is set.

    The .container-mode file is written by the NixOS activation script when
    container.enable = true. It tells the host CLI to exec into the container
    instead of running locally.
    """
    if os.environ.get("HERMES_DEV") == "1":
        return None

    from superforecasting_agent.constants import is_container
    if is_container():
        return None

    container_mode_file = get_agent_home() / ".container-mode"

    try:
        info = {}
        with open(container_mode_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    key, _, value = line.partition("=")
                    info[key.strip()] = value.strip()
    except FileNotFoundError:
        return None
    # All other exceptions (PermissionError, malformed data, etc.) propagate

    backend = info.get("backend", "docker")
    container_name = info.get("container_name", "superforecasting-agent")
    exec_user = info.get("exec_user", "hermes")
    hermes_bin = info.get("hermes_bin", "/data/current-package/bin/superforecasting-agent")

    return {
        "backend": backend,
        "container_name": container_name,
        "exec_user": exec_user,
        "hermes_bin": hermes_bin,
    }


# =============================================================================
# Config paths
# =============================================================================

# Re-export from superforecasting_agent.constants — canonical definition lives there.
from superforecasting_agent.constants import get_agent_home, display_agent_home  # noqa: F811,E402
from superforecasting_agent.storage.files import atomic_replace

def get_config_path() -> Path:
    """Get the main config file path."""
    return get_agent_home() / "config.yaml"

def get_env_path() -> Path:
    """Get the .env file path (for API keys)."""
    return get_agent_home() / ".env"

def get_project_root() -> Path:
    """Get the project installation directory."""
    return get_install_root()

def _secure_dir(path):
    """Set directory to owner-only access (0700 by default). No-op on Windows.

    Skipped in managed mode — the NixOS module sets group-readable
    permissions (0750) so interactive users in the hermes group can
    share state with the gateway service.

    The mode can be overridden via the HERMES_HOME_MODE environment variable
    (e.g. HERMES_HOME_MODE=0701) for deployments where a web server (nginx,
    caddy, etc.) needs to traverse HERMES_HOME to reach a served subdirectory.
    The execute-only bit on a directory permits cd-through without exposing
    directory listings.
    """
    if is_managed():
        return
    try:
        mode_str = os.environ.get("HERMES_HOME_MODE", "").strip()
        mode = int(mode_str, 8) if mode_str else 0o700
    except ValueError:
        mode = 0o700
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _is_container() -> bool:
    """Detect if we're running inside a Docker/Podman/LXC container.

    When Superforecasting Agent runs in a container with volume-mounted config
    files, forcing 0o600 permissions breaks multi-process setups where the
    gateway and dashboard run as different UIDs or the volume mount requires
    broader permissions.
    """
    # Explicit opt-out
    if os.environ.get("HERMES_CONTAINER") or os.environ.get("HERMES_SKIP_CHMOD"):
        return True
    # Docker / Podman marker file
    if os.path.exists("/.dockerenv"):
        return True
    # LXC / cgroup-based detection
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
            cgroup_content = f.read()
        if "docker" in cgroup_content or "lxc" in cgroup_content or "kubepods" in cgroup_content:
            return True
    except (OSError, IOError):
        pass
    return False


def _secure_file(path):
    """Set file to owner-only read/write (0600). No-op on Windows.

    Skipped in managed mode — the NixOS activation script sets
    group-readable permissions (0640) on config files.

    Skipped in containers — Docker/Podman volume mounts often need broader
    permissions.  Set HERMES_SKIP_CHMOD=1 to force-skip on other systems.
    """
    if is_managed() or _is_container():
        return
    try:
        if os.path.exists(str(path)):
            os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        pass


def _ensure_default_soul_md(home: Path) -> None:
    """Seed a default SOUL.md into the active agent home if none exists."""
    soul_path = home / "SOUL.md"
    if soul_path.exists():
        return
    soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
    _secure_file(soul_path)


def ensure_hermes_home():
    """Ensure the active agent-home directory exists with secure permissions.

    In managed mode (NixOS), dirs are created by the activation script with
    setgid + group-writable (2770). We skip mkdir and set umask(0o007) so
    any files created (e.g. SOUL.md) are group-writable (0660).
    """
    home = get_agent_home()
    if is_managed():
        old_umask = os.umask(0o007)
        try:
            _ensure_hermes_home_managed(home)
        finally:
            os.umask(old_umask)
    else:
        home.mkdir(parents=True, exist_ok=True)
        _secure_dir(home)
        for subdir in (
            "cron", "sessions", "logs", "logs/curator", "memories",
            "pairing", "hooks", "image_cache", "audio_cache", "skills",
        ):
            d = home / subdir
            d.mkdir(parents=True, exist_ok=True)
            _secure_dir(d)
        _ensure_default_soul_md(home)


def _ensure_hermes_home_managed(home: Path):
    """Managed-mode variant: verify dirs exist (activation creates them), seed SOUL.md."""
    if not home.is_dir():
        raise RuntimeError(
            f"HERMES_HOME {home} does not exist. "
            "Run 'sudo nixos-rebuild switch' first."
        )
    for subdir in ("cron", "sessions", "logs", "memories"):
        d = home / subdir
        if not d.is_dir():
            raise RuntimeError(
                f"{d} does not exist. "
                "Run 'sudo nixos-rebuild switch' first."
            )
    # Curator reports dir is a sub-path of logs/; create it if missing.
    # In managed mode the activation script may not know about this subdir,
    # so we mkdir it ourselves (it's inside an already-secured logs/ dir).
    (home / "logs" / "curator").mkdir(parents=True, exist_ok=True)
    # Inside umask(0o007) scope — SOUL.md will be created as 0660
    _ensure_default_soul_md(home)


# =============================================================================
# Config loading/saving
# =============================================================================

from superforecasting_agent.configuration import (
    DEFAULT_CONFIG as DEFAULT_CONFIG,
    _deep_merge as _deep_merge,
    _expand_env_vars as _expand_env_vars,
    _normalize_root_model_keys as _normalize_root_model_keys,
    _normalize_max_turns_config as _normalize_max_turns_config,
    cfg_get as cfg_get,
    _merge_user_config as _merge_user_config,
    resolve_config as resolve_config,
)

# =============================================================================
# Config Migration System
# =============================================================================

# Track which env vars were introduced in each config version.
# Migration only mentions vars new since the user's previous version.
ENV_VARS_BY_VERSION: Dict[int, List[str]] = {
    3: ["FIRECRAWL_API_KEY", "BROWSERBASE_API_KEY", "BROWSERBASE_PROJECT_ID", "FAL_KEY"],
    4: ["VOICE_TOOLS_OPENAI_KEY", "ELEVENLABS_API_KEY"],
    5: ["WHATSAPP_ENABLED", "WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS",
        "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"],
    10: ["TAVILY_API_KEY"],
    11: ["TERMINAL_MODAL_MODE"],
}

# Required environment variables with metadata for migration prompts.
# LLM provider is required but handled in the setup wizard's provider
# selection step (Nous Portal / OpenRouter / Custom endpoint), so this
# dict is intentionally empty — no single env var is universally required.
from superforecasting_agent.configuration.environment_catalog import REQUIRED_ENV_VARS as REQUIRED_ENV_VARS

# Optional environment variables that enhance functionality
from superforecasting_agent.configuration.environment_catalog import OPTIONAL_ENV_VARS as OPTIONAL_ENV_VARS

# Tool Gateway env vars are always visible — they're useful for
# self-hosted / custom gateway setups regardless of subscription state.


def get_missing_env_vars(required_only: bool = False) -> List[Dict[str, Any]]:
    """
    Check which environment variables are missing.
    
    Returns list of dicts with var info for missing variables.
    """
    missing = []
    
    # Check required vars
    for var_name, info in REQUIRED_ENV_VARS.items():
        if not get_env_value(var_name):
            missing.append({"name": var_name, **info, "is_required": True})
    
    # Check optional vars (if not required_only)
    if not required_only:
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if not get_env_value(var_name):
                missing.append({"name": var_name, **info, "is_required": False})
    
    return missing


def _set_nested(config, dotted_key: str, value):
    from superforecasting_agent.storage.files import set_nested
    return set_nested(config, dotted_key, value)


def get_missing_config_fields() -> List[Dict[str, Any]]:
    """
    Check which config fields are missing or outdated (recursive).
    
    Walks the DEFAULT_CONFIG tree at arbitrary depth and reports any keys
    present in defaults but absent from the user's loaded config.
    """
    config = load_config()
    missing = []

    def _check(defaults: dict, current: dict, prefix: str = ""):
        for key, default_value in defaults.items():
            if key.startswith('_'):
                continue
            full_key = key if not prefix else f"{prefix}.{key}"
            if key not in current:
                missing.append({
                    "key": full_key,
                    "default": default_value,
                    "description": f"New config option: {full_key}",
                })
            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
                _check(default_value, current[key], full_key)

    _check(DEFAULT_CONFIG, config)
    return missing


def get_missing_skill_config_vars() -> List[Dict[str, Any]]:
    """Return skill-declared config vars that are missing or empty in config.yaml.

    Scans all enabled skills for ``metadata.hermes.config`` entries, then checks
    which ones are absent or empty under ``skills.config.<key>`` in the user's
    config.yaml.  Returns a list of dicts suitable for prompting.
    """
    try:
        from agent.skill_utils import discover_all_skill_config_vars, SKILL_CONFIG_PREFIX
    except Exception:
        return []

    try:
        all_vars = discover_all_skill_config_vars()
    except Exception as e:
        # A malformed SKILL.md, unreadable external skill dir, or similar
        # should never break `superforecasting-agent update`. Skill-config
        # prompting is a post-migration nicety, not a blocker.
        import logging
        logging.getLogger(__name__).debug(
            "discover_all_skill_config_vars failed: %s", e
        )
        return []
    if not all_vars:
        return []

    config = load_config()
    missing: List[Dict[str, Any]] = []
    for var in all_vars:
        # Skill config is stored under skills.config.<logical_key>
        storage_key = f"{SKILL_CONFIG_PREFIX}.{var['key']}"
        parts = storage_key.split(".")
        current = config
        value = None
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
                value = current
            else:
                value = None
                break
        # Missing = key doesn't exist or is empty string
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(var)
    return missing


def _normalize_custom_provider_entry(
    entry: Any,
    *,
    provider_key: str = "",
) -> Optional[Dict[str, Any]]:
    """Return a runtime-compatible custom provider entry or ``None``."""
    if not isinstance(entry, dict):
        return None

    # Accept camelCase aliases commonly used in hand-written configs.
    _CAMEL_ALIASES: Dict[str, str] = {
        "apiKey": "api_key",
        "baseUrl": "base_url",
        "apiMode": "api_mode",
        "keyEnv": "key_env",
        "apiKeyEnv": "key_env",  # alias — OpenClaw-compatible + docs variant
        "defaultModel": "default_model",
        "contextLength": "context_length",
        "rateLimitDelay": "rate_limit_delay",
    }
    # api_key_env is a documented snake_case alias for key_env (see
    # website/docs/guides/azure-foundry.md).  Normalize it up front so the
    # rest of the normalizer treats it as the canonical field.
    if "api_key_env" in entry and "key_env" not in entry:
        entry["key_env"] = entry["api_key_env"]
    _KNOWN_KEYS = {
        "name", "api", "url", "base_url", "api_key", "key_env", "api_key_env",
        "api_mode", "transport", "model", "default_model", "models",
        "context_length", "rate_limit_delay",
        "request_timeout_seconds", "stale_timeout_seconds",
        "discover_models",
    }
    for camel, snake in _CAMEL_ALIASES.items():
        if camel in entry and snake not in entry:
            logger.warning(
                "providers.%s: camelCase key '%s' auto-mapped to '%s' "
                "(use snake_case to avoid this warning)",
                provider_key or "?", camel, snake,
            )
            entry[snake] = entry[camel]
    unknown = set(entry.keys()) - _KNOWN_KEYS - set(_CAMEL_ALIASES.keys())
    if unknown:
        logger.warning(
            "providers.%s: unknown config keys ignored: %s",
            provider_key or "?", ", ".join(sorted(unknown)),
        )

    from urllib.parse import urlparse

    base_url = ""
    for url_key in ("base_url", "url", "api"):
        raw_url = entry.get(url_key)
        if isinstance(raw_url, str) and raw_url.strip():
            candidate = raw_url.strip()
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                base_url = candidate
                break
            else:
                logger.warning(
                    "providers.%s: '%s' value '%s' is not a valid URL "
                    "(no scheme or host) — skipped",
                    provider_key or "?", url_key, candidate,
                )
    if not base_url:
        return None

    name = ""
    raw_name = entry.get("name")
    if isinstance(raw_name, str) and raw_name.strip():
        name = raw_name.strip()
    elif provider_key.strip():
        name = provider_key.strip()
    if not name:
        return None

    normalized: Dict[str, Any] = {
        "name": name,
        "base_url": base_url,
    }

    provider_key = provider_key.strip()
    if provider_key:
        normalized["provider_key"] = provider_key

    api_key = entry.get("api_key")
    if isinstance(api_key, str) and api_key.strip():
        normalized["api_key"] = api_key.strip()

    key_env = entry.get("key_env")
    if isinstance(key_env, str) and key_env.strip():
        normalized["key_env"] = key_env.strip()

    api_mode = entry.get("api_mode") or entry.get("transport")
    if isinstance(api_mode, str) and api_mode.strip():
        normalized["api_mode"] = api_mode.strip()

    model_name = entry.get("model") or entry.get("default_model")
    if isinstance(model_name, str) and model_name.strip():
        normalized["model"] = model_name.strip()

    models = entry.get("models")
    if isinstance(models, dict) and models:
        normalized["models"] = models
    elif isinstance(models, list) and models:
        # Hand-edited configs (and older Hermes versions) write ``models`` as
        # a plain list of model ids. Preserve them by converting to the dict
        # shape downstream code expects; otherwise normalize silently drops
        # the list and /model shows the provider with (0) models.
        normalized["models"] = {
            str(m): {} for m in models if isinstance(m, str) and m.strip()
        }

    context_length = entry.get("context_length")
    if isinstance(context_length, int) and context_length > 0:
        normalized["context_length"] = context_length

    rate_limit_delay = entry.get("rate_limit_delay")
    if isinstance(rate_limit_delay, (int, float)) and rate_limit_delay >= 0:
        normalized["rate_limit_delay"] = rate_limit_delay

    discover_models = entry.get("discover_models")
    if isinstance(discover_models, bool):
        normalized["discover_models"] = discover_models

    return normalized


def providers_dict_to_custom_providers(providers_dict: Any) -> List[Dict[str, Any]]:
    """Normalize ``providers`` config entries into the legacy custom-provider shape."""
    if not isinstance(providers_dict, dict):
        return []

    custom_providers: List[Dict[str, Any]] = []
    for key, entry in providers_dict.items():
        normalized = _normalize_custom_provider_entry(entry, provider_key=str(key))
        if normalized is not None:
            custom_providers.append(normalized)

    return custom_providers


def get_compatible_custom_providers(
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Return a deduplicated custom-provider view across legacy and v12+ config.

    ``custom_providers`` remains the on-disk legacy format, while ``providers``
    is the newer keyed schema.  Runtime and picker flows still need a single
    list-shaped view, but we should not materialise that compatibility layer
    back into config.yaml because it duplicates entries in UIs.
    """
    if config is None:
        config = load_config()

    compatible: List[Dict[str, Any]] = []
    seen_provider_keys: set = set()
    seen_name_url_pairs: set = set()

    def _append_if_new(entry: Optional[Dict[str, Any]]) -> None:
        if entry is None:
            return
        provider_key = str(entry.get("provider_key", "") or "").strip().lower()
        name = str(entry.get("name", "") or "").strip().lower()
        base_url = str(entry.get("base_url", "") or "").strip().rstrip("/").lower()
        model = str(entry.get("model", "") or "").strip().lower()
        pair = (name, base_url, model)

        if provider_key and provider_key in seen_provider_keys:
            return
        if name and base_url and pair in seen_name_url_pairs:
            return

        compatible.append(entry)
        if provider_key:
            seen_provider_keys.add(provider_key)
        if name and base_url:
            seen_name_url_pairs.add(pair)

    custom_providers = config.get("custom_providers")
    if custom_providers is not None:
        if not isinstance(custom_providers, list):
            return []
        for entry in custom_providers:
            _append_if_new(_normalize_custom_provider_entry(entry))

    for entry in providers_dict_to_custom_providers(config.get("providers")):
        _append_if_new(entry)

    return compatible


def get_custom_provider_context_length(
    model: str,
    base_url: str,
    custom_providers: Optional[List[Dict[str, Any]]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Look up a per-model ``context_length`` override from ``custom_providers``.

    Matches any entry whose ``base_url`` equals ``base_url`` (trailing-slash
    insensitive) and returns ``custom_providers[i].models.<model>.context_length``
    if present and valid.  Returns ``None`` when no override applies.

    This is the single source of truth for custom-provider context overrides,
    used by:
      * ``AIAgent.__init__`` (startup resolution)
      * ``AIAgent.switch_model`` (mid-session ``/model`` switch)
      * ``superforecasting_agent.runtime.model_switch.resolve_display_context_length`` (``/model`` confirmation display)
      * ``gateway.run._format_session_info`` (``/info`` display)
      * ``agent.model_metadata.get_model_context_length`` (when custom_providers is threaded through)

    Before this helper existed, the lookup was duplicated in ``run_agent.py``'s
    startup path only; every other path (notably ``/model`` switch) fell back
    to the 128K default.  See #15779.
    """
    if not model or not base_url:
        return None
    if custom_providers is None:
        try:
            custom_providers = get_compatible_custom_providers(config)
        except Exception:
            if config is None:
                return None
            raw = config.get("custom_providers")
            custom_providers = raw if isinstance(raw, list) else []
    if not isinstance(custom_providers, list):
        return None

    target_url = (base_url or "").rstrip("/")
    if not target_url:
        return None

    for entry in custom_providers:
        if not isinstance(entry, dict):
            continue
        entry_url = (entry.get("base_url") or "").rstrip("/")
        if not entry_url or entry_url != target_url:
            continue
        models = entry.get("models")
        if not isinstance(models, dict):
            continue
        model_cfg = models.get(model)
        if not isinstance(model_cfg, dict):
            continue
        raw_ctx = model_cfg.get("context_length")
        if raw_ctx is None:
            continue
        try:
            ctx = int(raw_ctx)
        except (TypeError, ValueError):
            continue
        if ctx > 0:
            return ctx
    return None


def check_config_version() -> Tuple[int, int]:
    """
    Check config version.
    
    Returns (current_version, latest_version).
    """
    config = load_config()
    current = config.get("_config_version", 0)
    latest = DEFAULT_CONFIG.get("_config_version", 1)
    return current, latest


# =============================================================================
# Config structure validation
# =============================================================================

# Fields that are valid at root level of config.yaml
_KNOWN_ROOT_KEYS = {
    "_config_version", "model", "providers", "fallback_model",
    "fallback_providers", "credential_pool_strategies", "toolsets",
    "agent", "terminal", "display", "compression", "delegation",
    "auxiliary", "custom_providers", "context", "memory", "gateway",
    "sessions",
}

# Valid fields inside a custom_providers list entry
_VALID_CUSTOM_PROVIDER_FIELDS = {
    "name", "base_url", "api_key", "api_mode", "model", "models",
    "context_length", "rate_limit_delay",
    # key_env is read at runtime by runtime_provider.py and auxiliary_client.py
    # — include it here so the set accurately describes the supported schema.
    "key_env",
}

# Fields that look like they should be inside custom_providers, not at root
_CUSTOM_PROVIDER_LIKE_FIELDS = {"base_url", "api_key", "rate_limit_delay", "api_mode"}


@dataclass
class ConfigIssue:
    """A detected config structure problem."""

    severity: str  # "error", "warning"
    message: str
    hint: str


def validate_config_structure(config: Optional[Dict[str, Any]] = None) -> List["ConfigIssue"]:
    """Validate config.yaml structure and return a list of detected issues.

    Catches common YAML formatting mistakes that produce confusing runtime
    errors (like "Unknown provider") instead of clear diagnostics.

    Can be called with a pre-loaded config dict, or will load from disk.
    """
    if config is None:
        try:
            config = load_config()
        except Exception:
            return [
                ConfigIssue(
                    "error",
                    "Could not load config.yaml",
                    f"Run '{_PRIMARY_CLI} setup' to create a valid config",
                )
            ]

    issues: List[ConfigIssue] = []

    # ── multiplayer ledger collaboration ────────────────────────────────
    collaboration = config.get("collaboration")
    if collaboration is not None and not isinstance(collaboration, dict):
        issues.append(ConfigIssue(
            "error",
            "collaboration must be a YAML mapping",
            "Use collaboration: {enabled: false, github: ..., repository: ...}",
        ))
    elif isinstance(collaboration, dict):
        from urllib.parse import urlparse

        github = collaboration.get("github") or {}
        repository = collaboration.get("repository") or {}
        review = collaboration.get("review") or {}
        discussion = collaboration.get("discussion") or {}
        transcripts = collaboration.get("transcripts") or {}
        for section_name, section in (
            ("github", github),
            ("repository", repository),
            ("review", review),
            ("discussion", discussion),
            ("transcripts", transcripts),
        ):
            if not isinstance(section, dict):
                issues.append(ConfigIssue(
                    "error",
                    f"collaboration.{section_name} must be a YAML mapping",
                    f"Replace collaboration.{section_name} with a mapping of named settings",
                ))
        if isinstance(github, dict):
            for key in ("api_url", "upload_url"):
                value = str(github.get(key) or "")
                parsed = urlparse(value)
                if parsed.scheme != "https" or not parsed.hostname:
                    issues.append(ConfigIssue(
                        "error",
                        f"collaboration.github.{key} must be an absolute HTTPS URL",
                        f"Set collaboration.github.{key} to an https:// endpoint",
                    ))
            public_base = str(github.get("public_base_url") or "")
            if public_base:
                parsed = urlparse(public_base)
                if parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment:
                    issues.append(ConfigIssue(
                        "error",
                        "collaboration.github.public_base_url must be an absolute HTTPS URL",
                        "Example: https://forecast.example.com",
                    ))
            for key in ("oauth_state_ttl_seconds", "installation_state_ttl_seconds"):
                ttl = github.get(key, 600)
                if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 60:
                    issues.append(ConfigIssue(
                        "error",
                        f"collaboration.github.{key} must be at least 60",
                        "Use 600 for the default ten-minute authorization window",
                    ))
            app_slug = str(github.get("app_slug") or "")
            if app_slug and not re.fullmatch(r"[A-Za-z0-9-]+", app_slug):
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.github.app_slug is invalid",
                    "Use the slug from https://github.com/apps/<app-slug>",
                ))
            for key in (
                "oauth_callback_path",
                "installation_begin_path",
                "installation_callback_path",
                "webhook_path",
            ):
                path = str(github.get(key) or "")
                if not path.startswith("/") or ".." in path or "\\" in path:
                    issues.append(ConfigIssue(
                        "error",
                        f"collaboration.github.{key} must be a safe absolute path",
                        "Use a fixed absolute /api/... path without traversal",
                    ))
        if isinstance(repository, dict):
            slug = str(repository.get("slug") or "").strip()
            if slug and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.repository.slug must use owner/repository form",
                    "Example: forecasting-team/forecast-ledger",
                ))
            branch = str(repository.get("default_branch") or "").strip()
            if not branch or branch.startswith(("-", ".")) or any(
                marker in branch for marker in ("..", "~", "^", ":", "\\", " ")
            ):
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.repository.default_branch is not a safe Git ref",
                    "Use a simple branch name such as main",
                ))
        if isinstance(review, dict):
            threshold = review.get("materiality_threshold", 0.10)
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
                    or not 0 <= float(threshold) <= 1:
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.review.materiality_threshold must be between 0 and 1",
                    "Use 0.10 for the default ten-percentage-point boundary",
                ))
            for key in ("medium_required_humans", "high_required_humans"):
                value = review.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                    issues.append(ConfigIssue(
                        "error",
                        f"collaboration.review.{key} must be a non-negative integer",
                        "Use 1 for medium risk and 2 for high risk",
                    ))
            overrides = review.get("risk_overrides") or {}
            if not isinstance(overrides, dict):
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.review.risk_overrides must be a mapping",
                    "Map operation kinds to low, medium, or high",
                ))
            elif any(value not in {"low", "medium", "high"} for value in overrides.values()):
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.review.risk_overrides contains an unknown risk tier",
                    "Risk override values must be low, medium, or high",
                ))
        if isinstance(transcripts, dict):
            retention = transcripts.get("raw_retention_days", 90)
            if isinstance(retention, bool) or not isinstance(retention, int) or retention < 0:
                issues.append(ConfigIssue(
                    "error",
                    "collaboration.transcripts.raw_retention_days must be non-negative",
                    "Use 90 for the default retention period",
                ))
        if isinstance(discussion, dict):
            for key in (
                "max_comments",
                "max_rounds",
                "max_tokens",
                "max_elapsed_seconds",
                "max_concurrent_tasks",
                "agent_loop_threshold",
                "max_comment_bytes",
            ):
                value = discussion.get(key)
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    issues.append(ConfigIssue(
                        "error",
                        f"collaboration.discussion.{key} must be a positive integer",
                        "Use the documented default or another value greater than zero",
                    ))

    # ── custom_providers must be a list, not a dict ──────────────────────
    cp = config.get("custom_providers")
    if cp is not None:
        if isinstance(cp, dict):
            issues.append(ConfigIssue(
                "error",
                "custom_providers is a dict — it must be a YAML list (items prefixed with '-')",
                "Change to:\n"
                "  custom_providers:\n"
                "    - name: my-provider\n"
                "      base_url: https://...\n"
                "      api_key: ...",
            ))
            # Check if dict keys look like they should be list-entry fields
            cp_keys = set(cp.keys()) if isinstance(cp, dict) else set()
            suspicious = cp_keys & _CUSTOM_PROVIDER_LIKE_FIELDS
            if suspicious:
                issues.append(ConfigIssue(
                    "warning",
                    f"Root-level keys {sorted(suspicious)} look like custom_providers entry fields",
                    "These should be indented under a '- name: ...' list entry, not at root level",
                ))
        elif isinstance(cp, list):
            # Validate each entry in the list
            for i, entry in enumerate(cp):
                if not isinstance(entry, dict):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] is not a dict (got {type(entry).__name__})",
                        "Each entry should have at minimum: name, base_url",
                    ))
                    continue
                if not entry.get("name"):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] is missing 'name' field",
                        "Add a name, e.g.: name: my-provider",
                    ))
                if not entry.get("base_url"):
                    issues.append(ConfigIssue(
                        "warning",
                        f"custom_providers[{i}] is missing 'base_url' field",
                        "Add the API endpoint URL, e.g.: base_url: https://api.example.com/v1",
                    ))

    # ── fallback_model: single dict OR list of dicts (chain) ─────────────
    fb = config.get("fallback_model")
    if fb is not None:
        if isinstance(fb, list):
            # Chain fallback — validate each entry
            for i, entry in enumerate(fb):
                if not isinstance(entry, dict):
                    issues.append(ConfigIssue(
                        "error",
                        f"fallback_model[{i}] should be a dict, got {type(entry).__name__}",
                        "Each entry needs provider + model",
                    ))
                else:
                    if not entry.get("provider"):
                        issues.append(ConfigIssue(
                            "warning",
                            f"fallback_model[{i}] is missing 'provider' field",
                            "Add: provider: openrouter (or another provider)",
                        ))
                    if not entry.get("model"):
                        issues.append(ConfigIssue(
                            "warning",
                            f"fallback_model[{i}] is missing 'model' field",
                            "Add: model: <model-name>",
                        ))
        elif not isinstance(fb, dict):
            issues.append(ConfigIssue(
                "error",
                f"fallback_model should be a dict with 'provider' and 'model', got {type(fb).__name__}",
                "Change to:\n"
                "  fallback_model:\n"
                "    provider: openrouter\n"
                "    model: anthropic/claude-sonnet-4",
            ))
        elif fb:
            if not fb.get("provider"):
                issues.append(ConfigIssue(
                    "warning",
                    "fallback_model is missing 'provider' field — fallback will be disabled",
                    "Add: provider: openrouter (or another provider)",
                ))
            if not fb.get("model"):
                issues.append(ConfigIssue(
                    "warning",
                    "fallback_model is missing 'model' field — fallback will be disabled",
                    "Add: model: anthropic/claude-sonnet-4 (or another model)",
                ))

    # ── Check for fallback_model accidentally nested inside custom_providers ──
    if isinstance(cp, dict) and "fallback_model" not in config and "fallback_model" in (cp or {}):
        issues.append(ConfigIssue(
            "error",
            "fallback_model appears inside custom_providers instead of at root level",
            "Move fallback_model to the top level of config.yaml (no indentation)",
        ))

    # ── model section: should exist when custom_providers is configured ──
    model_cfg = config.get("model")
    if cp and not model_cfg:
        issues.append(ConfigIssue(
            "warning",
            "custom_providers defined but no 'model' section — Superforecasting Agent won't know which provider to use",
            "Add a model section:\n"
            "  model:\n"
            "    provider: custom\n"
            "    default: your-model-name\n"
            "    base_url: https://...",
        ))

    # ── Root-level keys that look misplaced ──────────────────────────────
    for key in config:
        if key.startswith("_"):
            continue
        if key not in _KNOWN_ROOT_KEYS and key in _CUSTOM_PROVIDER_LIKE_FIELDS:
            issues.append(ConfigIssue(
                "warning",
                f"Root-level key '{key}' looks misplaced — should it be under 'model:' or inside a 'custom_providers' entry?",
                f"Move '{key}' under the appropriate section",
            ))

    return issues


def print_config_warnings(config: Optional[Dict[str, Any]] = None) -> None:
    """Print config structure warnings to stderr at startup.

    Called early in CLI and gateway init so users see problems before
    they hit cryptic "Unknown provider" errors.  Prints nothing if
    config is healthy.
    """
    try:
        issues = validate_config_structure(config)
    except Exception:
        return
    if not issues:
        return

    lines = ["\033[33m⚠ Config issues detected in config.yaml:\033[0m"]
    for ci in issues:
        marker = "\033[31m✗\033[0m" if ci.severity == "error" else "\033[33m⚠\033[0m"
        lines.append(f"  {marker} {ci.message}")
    lines.append(f"  \033[2mRun '{_PRIMARY_CLI} doctor' for fix suggestions.\033[0m")
    sys.stderr.write("\n".join(lines) + "\n\n")


def warn_deprecated_cwd_env_vars(config: Optional[Dict[str, Any]] = None) -> None:
    """Warn if MESSAGING_CWD or TERMINAL_CWD is set in .env instead of config.yaml.

    These env vars are deprecated — the canonical setting is terminal.cwd
    in config.yaml.  Prints a migration hint to stderr.
    """
    messaging_cwd = os.environ.get("MESSAGING_CWD")
    terminal_cwd_env = os.environ.get("TERMINAL_CWD")

    if config is None:
        try:
            config = load_config()
        except Exception:
            return

    terminal_cfg = config.get("terminal", {})
    config_cwd = terminal_cfg.get("cwd", ".") if isinstance(terminal_cfg, dict) else "."
    # Only warn if config.yaml doesn't have an explicit path
    config_has_explicit_cwd = config_cwd not in {".", "auto", "cwd", ""}

    lines: list[str] = []
    if messaging_cwd:
        lines.append(
            f"  \033[33m⚠\033[0m MESSAGING_CWD={messaging_cwd} found in .env — "
            f"this is deprecated."
        )
    if terminal_cwd_env and not config_has_explicit_cwd:
        # TERMINAL_CWD in env but not from config bridge — likely from .env
        lines.append(
            f"  \033[33m⚠\033[0m TERMINAL_CWD={terminal_cwd_env} found in .env — "
            f"this is deprecated."
        )
    if lines:
        hint_path = display_agent_home()
        lines.insert(0, "\033[33m⚠ Deprecated .env settings detected:\033[0m")
        lines.append(
            f"  \033[2mMove to config.yaml instead:  "
            f"terminal:\\n    cwd: /your/project/path\033[0m"
        )
        lines.append(
            f"  \033[2mThen remove the old entries from {hint_path}/.env\033[0m"
        )
        sys.stderr.write("\n".join(lines) + "\n\n")


def migrate_config(interactive: bool = True, quiet: bool = False) -> Dict[str, Any]:
    """
    Migrate config to latest version, prompting for new required fields.
    
    Args:
        interactive: If True, prompt user for missing values
        quiet: If True, suppress output
        
    Returns:
        Dict with migration results: {"env_added": [...], "config_added": [...], "warnings": [...]}
    """
    results = {"env_added": [], "config_added": [], "warnings": []}

    # ── Always: sanitize .env (split concatenated keys) ──
    try:
        fixes = sanitize_env_file()
        if fixes and not quiet:
            print(f"  ✓ Repaired .env file ({fixes} corrupted entries fixed)")
    except Exception:
        pass  # best-effort; don't block migration on sanitize failure

    # Check config version
    current_ver, latest_ver = check_config_version()
    
    # ── Version 3 → 4: migrate tool progress from .env to config.yaml ──
    if current_ver < 4:
        config = load_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        if "tool_progress" not in display:
            old_enabled = get_env_value("HERMES_TOOL_PROGRESS")
            old_mode = get_env_value("HERMES_TOOL_PROGRESS_MODE")
            if old_enabled and old_enabled.lower() in {"false", "0", "no"}:
                display["tool_progress"] = "off"
                results["config_added"].append("display.tool_progress=off (from HERMES_TOOL_PROGRESS=false)")
            elif old_mode and old_mode.lower() in {"new", "all"}:
                display["tool_progress"] = old_mode.lower()
                results["config_added"].append(f"display.tool_progress={old_mode.lower()} (from HERMES_TOOL_PROGRESS_MODE)")
            else:
                display["tool_progress"] = "all"
                results["config_added"].append("display.tool_progress=all (default)")
            config["display"] = display
            save_config(config)
            if not quiet:
                print(f"  ✓ Migrated tool progress to config.yaml: {display['tool_progress']}")
    
    # ── Version 4 → 5: add timezone field ──
    if current_ver < 5:
        config = load_config()
        if "timezone" not in config:
            old_tz = (
                os.getenv("SUPERFORECASTING_AGENT_TIMEZONE", "")
                or os.getenv("FORECAST_TIMEZONE", "")
                or os.getenv("HERMES_TIMEZONE", "")
            )
            if old_tz and old_tz.strip():
                config["timezone"] = old_tz.strip()
                results["config_added"].append("timezone="
                                               f"{old_tz.strip()} (from environment)")
            else:
                config["timezone"] = ""
                results["config_added"].append("timezone= (empty, uses server-local)")
            save_config(config)
            if not quiet:
                tz_display = config["timezone"] or "(server-local)"
                print(f"  ✓ Added timezone to config.yaml: {tz_display}")

    # ── Version 8 → 9: clear ANTHROPIC_TOKEN from .env ──
    # The new Anthropic auth flow no longer uses this env var.
    if current_ver < 9:
        try:
            old_token = get_env_value("ANTHROPIC_TOKEN")
            if old_token:
                save_env_value("ANTHROPIC_TOKEN", "")
                if not quiet:
                    print("  ✓ Cleared ANTHROPIC_TOKEN from .env (no longer used)")
        except Exception:
            pass

    # ── Version 11 → 12: migrate custom_providers list → providers dict ──
    if current_ver < 12:
        config = load_config()
        custom_list = config.get("custom_providers")
        if isinstance(custom_list, list) and custom_list:
            providers_dict = config.get("providers", {})
            if not isinstance(providers_dict, dict):
                providers_dict = {}
            migrated_count = 0
            for entry in custom_list:
                if not isinstance(entry, dict):
                    continue
                old_name = entry.get("name", "")
                old_url = entry.get("base_url", "") or entry.get("url", "") or ""
                old_key = entry.get("api_key", "")
                if not old_url:
                    continue  # skip entries with no URL

                # Generate a kebab-case key from the display name
                key = old_name.strip().lower().replace(" ", "-").replace("(", "").replace(")", "")
                # Remove consecutive hyphens and trailing hyphens
                while "--" in key:
                    key = key.replace("--", "-")
                key = key.strip("-")
                if not key:
                    # Fallback: derive from URL hostname
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(old_url)
                        key = (parsed.hostname or "endpoint").replace(".", "-")
                    except Exception:
                        key = f"endpoint-{migrated_count}"

                # Don't overwrite existing entries
                if key in providers_dict:
                    key = f"{key}-{migrated_count}"

                new_entry = {"api": old_url}
                if old_name:
                    new_entry["name"] = old_name
                if old_key and old_key not in {"no-key", "no-key-required", ""}:
                    new_entry["api_key"] = old_key

                # Carry over model and api_mode if present
                if entry.get("model"):
                    new_entry["default_model"] = entry["model"]
                if entry.get("api_mode"):
                    new_entry["transport"] = entry["api_mode"]

                providers_dict[key] = new_entry
                migrated_count += 1

            if migrated_count > 0:
                config["providers"] = providers_dict
                # Remove the old list — runtime reads via get_compatible_custom_providers()
                config.pop("custom_providers", None)
                save_config(config)
                if not quiet:
                    print(f"  ✓ Migrated {migrated_count} custom provider(s) to providers: section")
                    for key in list(providers_dict.keys())[-migrated_count:]:
                        ep = providers_dict[key]
                        print(f"    → {key}: {ep.get('api', '')}")

    # ── Version 12 → 13: clear dead LLM_MODEL / OPENAI_MODEL from .env ──
    # These env vars were written by the old setup wizard but nothing reads
    # them anymore (config.yaml is the sole source of truth since March 2026).
    # Stale entries cause user confusion — see issue report.
    if current_ver < 13:
        for dead_var in ("LLM_MODEL", "OPENAI_MODEL"):
            try:
                old_val = get_env_value(dead_var)
                if old_val:
                    save_env_value(dead_var, "")
                    if not quiet:
                        print(f"  ✓ Cleared {dead_var} from .env (no longer used — config.yaml is source of truth)")
            except Exception:
                pass

    # ── Version 13 → 14: migrate legacy flat stt.model to provider section ──
    # Old configs (and cli-config.yaml.example) had a flat `stt.model` key
    # that was provider-agnostic.  When the provider was "local" this caused
    # OpenAI model names (e.g. "whisper-1") to be fed to faster-whisper,
    # crashing with "Invalid model size".  Move the value into the correct
    # provider-specific section and remove the flat key.
    if current_ver < 14:
        # Read raw config (no defaults merged) to check what the user actually
        # wrote, then apply changes to the merged config for saving.
        raw = read_raw_config()
        raw_stt = raw.get("stt", {})
        if isinstance(raw_stt, dict) and "model" in raw_stt:
            legacy_model = raw_stt["model"]
            provider = raw_stt.get("provider", "local")
            config = load_config()
            stt = config.get("stt", {})
            # Remove the legacy flat key
            stt.pop("model", None)
            # Place it in the appropriate provider section only if the
            # user didn't already set a model there
            if provider in {"local", "local_command"}:
                # Don't migrate an OpenAI model name into the local section
                _local_models = {
                    "tiny.en", "tiny", "base.en", "base", "small.en", "small",
                    "medium.en", "medium", "large-v1", "large-v2", "large-v3",
                    "large", "distil-large-v2", "distil-medium.en",
                    "distil-small.en", "distil-large-v3", "distil-large-v3.5",
                    "large-v3-turbo", "turbo",
                }
                if legacy_model in _local_models:
                    # Check raw config — only set if user didn't already
                    # have a nested local.model
                    raw_local = raw_stt.get("local", {})
                    if not isinstance(raw_local, dict) or "model" not in raw_local:
                        local_cfg = stt.setdefault("local", {})
                        local_cfg["model"] = legacy_model
                # else: drop it — it was an OpenAI model name, local section
                # already defaults to "base" via DEFAULT_CONFIG
            else:
                # Cloud provider — put it in that provider's section only
                # if user didn't already set a nested model
                raw_provider = raw_stt.get(provider, {})
                if not isinstance(raw_provider, dict) or "model" not in raw_provider:
                    provider_cfg = stt.setdefault(provider, {})
                    provider_cfg["model"] = legacy_model
            config["stt"] = stt
            save_config(config)
            if not quiet:
                print(f"  ✓ Migrated legacy stt.model to provider-specific config")

    # ── Version 14 → 15: add explicit gateway interim-message gate ──
    if current_ver < 15:
        config = read_raw_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        if "interim_assistant_messages" not in display:
            display["interim_assistant_messages"] = True
            config["display"] = display
            results["config_added"].append("display.interim_assistant_messages=true (default)")
            save_config(config)
            if not quiet:
                print("  ✓ Added display.interim_assistant_messages=true")

    # ── Version 15 → 16: migrate tool_progress_overrides into display.platforms ──
    if current_ver < 16:
        config = read_raw_config()
        display = config.get("display", {})
        if not isinstance(display, dict):
            display = {}
        old_overrides = display.get("tool_progress_overrides")
        if isinstance(old_overrides, dict) and old_overrides:
            platforms = display.get("platforms", {})
            if not isinstance(platforms, dict):
                platforms = {}
            for plat, mode in old_overrides.items():
                if plat not in platforms:
                    platforms[plat] = {}
                if "tool_progress" not in platforms[plat]:
                    platforms[plat]["tool_progress"] = mode
            display["platforms"] = platforms
            config["display"] = display
            save_config(config)
            if not quiet:
                migrated = ", ".join(f"{p}={m}" for p, m in old_overrides.items())
                print(f"  ✓ Migrated tool_progress_overrides → display.platforms: {migrated}")
            results["config_added"].append("display.platforms (migrated from tool_progress_overrides)")

    # ── Version 16 → 17: remove legacy compression.summary_* keys ──
    if current_ver < 17:
        config = read_raw_config()
        comp = config.get("compression", {})
        if isinstance(comp, dict):
            s_model = comp.pop("summary_model", None)
            s_provider = comp.pop("summary_provider", None)
            s_base_url = comp.pop("summary_base_url", None)
            migrated_keys = []
            # Migrate non-empty, non-default values to auxiliary.compression
            if s_model and str(s_model).strip():
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("model"):
                    aux_comp["model"] = str(s_model).strip()
                    migrated_keys.append(f"model={s_model}")
            if s_provider and str(s_provider).strip() not in {"", "auto"}:
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("provider") or aux_comp.get("provider") == "auto":
                    aux_comp["provider"] = str(s_provider).strip()
                    migrated_keys.append(f"provider={s_provider}")
            if s_base_url and str(s_base_url).strip():
                aux = config.setdefault("auxiliary", {})
                aux_comp = aux.setdefault("compression", {})
                if not aux_comp.get("base_url"):
                    aux_comp["base_url"] = str(s_base_url).strip()
                    migrated_keys.append(f"base_url={s_base_url}")
            if migrated_keys or s_model is not None or s_provider is not None or s_base_url is not None:
                config["compression"] = comp
                save_config(config)
                if not quiet:
                    if migrated_keys:
                        print(f"  ✓ Migrated compression.summary_* → auxiliary.compression: {', '.join(migrated_keys)}")
                    else:
                        print("  ✓ Removed unused compression.summary_* keys")

    # ── Version 20 → 21: plugins are now opt-in; grandfather existing user plugins ──
    # The loader now requires plugins to appear in ``plugins.enabled`` before
    # loading. Existing installs had all discovered plugins loading by default
    # (minus anything in ``plugins.disabled``). To avoid silently breaking
    # those setups on upgrade, populate ``plugins.enabled`` with the set of
    # currently-installed user plugins that aren't already disabled.
    #
    # Bundled plugins (shipped in the repo itself) are NOT grandfathered —
    # they ship off for everyone, including existing users, so any user who
    # wants one has to opt in explicitly.
    if current_ver < 21:
        config = read_raw_config()
        plugins_cfg = config.get("plugins")
        if not isinstance(plugins_cfg, dict):
            plugins_cfg = {}
        # Only migrate if the enabled allow-list hasn't been set yet.
        if "enabled" not in plugins_cfg:
            disabled = plugins_cfg.get("disabled", []) or []
            if not isinstance(disabled, list):
                disabled = []
            disabled_set = set(disabled)

            # Scan ``$HERMES_HOME/plugins/`` for currently installed user plugins.
            grandfathered: List[str] = []
            try:
                user_plugins_dir = get_agent_home() / "plugins"
                if user_plugins_dir.is_dir():
                    for child in sorted(user_plugins_dir.iterdir()):
                        if not child.is_dir():
                            continue
                        manifest_file = child / "plugin.yaml"
                        if not manifest_file.exists():
                            manifest_file = child / "plugin.yml"
                        if not manifest_file.exists():
                            continue
                        try:
                            with open(manifest_file, encoding="utf-8") as _mf:
                                manifest = yaml.safe_load(_mf) or {}
                        except Exception:
                            manifest = {}
                        name = manifest.get("name") or child.name
                        if name in disabled_set:
                            continue
                        grandfathered.append(name)
            except Exception:
                grandfathered = []

            plugins_cfg["enabled"] = grandfathered
            config["plugins"] = plugins_cfg
            save_config(config)
            results["config_added"].append(
                f"plugins.enabled (opt-in allow-list, {len(grandfathered)} grandfathered)"
            )
            if not quiet:
                if grandfathered:
                    print(
                        f"  ✓ Plugins now opt-in: grandfathered "
                        f"{len(grandfathered)} existing plugin(s) into plugins.enabled"
                    )
                else:
                    print(
                        "  ✓ Plugins now opt-in: no existing plugins to grandfather. "
                        "Use `superforecasting-agent plugins enable <name>` to activate."
                    )

    # ── Version 22 → 23: seed curator defaults + create logs/curator/ ──
    # The curator (background skill maintenance) was added in PR #16049, but
    # existing configs from before that PR (or before the April 2026
    # unification under `auxiliary.curator`) never wrote the curator section
    # to disk. The runtime deep-merge in `load_config()` fills defaults at
    # read time, so the curator *functions*; but users can't see/edit the
    # settings in their `config.yaml`, and `superforecasting-agent curator status` has no
    # stable logs dir to point at until the first run mkdir's it.
    #
    # This migration:
    #   1. Writes the `curator` top-level section to config.yaml (enabled,
    #      interval_hours, min_idle_hours, stale_after_days, archive_after_days)
    #      — only keys the user hasn't already overridden.
    #   2. Writes the `auxiliary.curator` aux-task slot (provider, model,
    #      base_url, api_key, timeout, extra_body) — canonical slot for
    #      routing the curator fork to a cheaper aux model.
    #   3. Creates active agent-home `logs/curator/` if missing (belt-and-suspenders
    #      on top of ensure_hermes_home() — old profiles that predate this
    #      migration still benefit).
    if current_ver < 23:
        try:
            curator_dir = get_agent_home() / "logs" / "curator"
            curator_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            results["warnings"].append(f"Could not create {curator_dir}: {e}")

        config = read_raw_config()
        touched = False

        # (1) Top-level curator section — only add missing keys
        _curator_defaults = DEFAULT_CONFIG.get("curator", {})
        raw_curator = config.get("curator")
        if not isinstance(raw_curator, dict):
            raw_curator = {}
        added_curator: List[str] = []
        for k, v in _curator_defaults.items():
            if k not in raw_curator:
                raw_curator[k] = copy.deepcopy(v)
                added_curator.append(k)
        if added_curator:
            config["curator"] = raw_curator
            touched = True

        # (2) auxiliary.curator task slot
        _aux_curator_defaults = (
            DEFAULT_CONFIG.get("auxiliary", {}).get("curator", {})
        )
        raw_aux = config.get("auxiliary")
        if not isinstance(raw_aux, dict):
            raw_aux = {}
        raw_aux_curator = raw_aux.get("curator")
        if not isinstance(raw_aux_curator, dict):
            raw_aux_curator = {}
        added_aux: List[str] = []
        for k, v in _aux_curator_defaults.items():
            if k not in raw_aux_curator:
                raw_aux_curator[k] = copy.deepcopy(v)
                added_aux.append(k)
        if added_aux:
            raw_aux["curator"] = raw_aux_curator
            config["auxiliary"] = raw_aux
            touched = True

        if touched:
            save_config(config)
            if added_curator:
                results["config_added"].append(
                    f"curator ({len(added_curator)} default key(s))"
                )
                if not quiet:
                    print(
                        "  ✓ Seeded curator defaults in config.yaml: "
                        f"{', '.join(added_curator)}"
                    )
            if added_aux:
                results["config_added"].append(
                    f"auxiliary.curator ({len(added_aux)} default key(s))"
                )
                if not quiet:
                    print(
                        "  ✓ Seeded auxiliary.curator defaults in config.yaml: "
                        f"{', '.join(added_aux)}"
                    )

    if current_ver < latest_ver and not quiet:
        print(f"Config version: {current_ver} → {latest_ver}")
    
    # Check for missing required env vars
    missing_env = get_missing_env_vars(required_only=True)
    
    if missing_env and not quiet:
        print("\n⚠️  Missing required environment variables:")
        for var in missing_env:
            print(f"   • {var['name']}: {var['description']}")
    
    if interactive and missing_env:
        print("\nLet's configure them now:\n")
        for var in missing_env:
            if var.get("url"):
                print(f"  Get your key at: {var['url']}")
            
            if var.get("password"):
                value = masked_secret_prompt(f"  {var['prompt']}: ")
            else:
                value = input(f"  {var['prompt']}: ").strip()
            
            if value:
                save_env_value(var["name"], value)
                results["env_added"].append(var["name"])
                print(f"  ✓ Saved {var['name']}")
            else:
                results["warnings"].append(f"Skipped {var['name']} - some features may not work")
            print()
    
    # Check for missing optional env vars and offer to configure interactively
    # Skip "advanced" vars (like OPENAI_BASE_URL) -- those are for power users
    missing_optional = get_missing_env_vars(required_only=False)
    required_names = {v["name"] for v in missing_env} if missing_env else set()
    missing_optional = [
        v for v in missing_optional
        if v["name"] not in required_names and not v.get("advanced")
    ]
    
    # Only offer to configure env vars that are NEW since the user's previous version
    new_var_names = set()
    for ver in range(current_ver + 1, latest_ver + 1):
        new_var_names.update(ENV_VARS_BY_VERSION.get(ver, []))

    if new_var_names and interactive and not quiet:
        new_and_unset = [
            (name, OPTIONAL_ENV_VARS[name])
            for name in sorted(new_var_names)
            if not get_env_value(name) and name in OPTIONAL_ENV_VARS
        ]
        if new_and_unset:
            print(f"\n  {len(new_and_unset)} new optional key(s) in this update:")
            for name, info in new_and_unset:
                print(f"    • {name} — {info.get('description', '')}")
            print()
            try:
                answer = input("  Configure new keys? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"

            if answer in {"y", "yes"}:
                print()
                for name, info in new_and_unset:
                    if info.get("url"):
                        print(f"  {info.get('description', name)}")
                        print(f"  Get your key at: {info['url']}")
                    else:
                        print(f"  {info.get('description', name)}")
                    if info.get("password"):
                        value = masked_secret_prompt(
                            f"  {info.get('prompt', name)} (Enter to skip): "
                        )
                    else:
                        value = input(f"  {info.get('prompt', name)} (Enter to skip): ").strip()
                    if value:
                        save_env_value(name, value)
                        results["env_added"].append(name)
                        print(f"  ✓ Saved {name}")
                    print()
            else:
                print(f"  Set later with: {_PRIMARY_CLI} config set <key> <value>")
    
    # Check for missing config fields
    missing_config = get_missing_config_fields()
    
    if missing_config:
        config = load_config()
        
        for field in missing_config:
            key = field["key"]
            default = field["default"]
            
            _set_nested(config, key, default)
            results["config_added"].append(key)
            if not quiet:
                print(f"  ✓ Added {key} = {default}")
        
        # Update version and save
        config["_config_version"] = latest_ver
        save_config(config)
    elif current_ver < latest_ver:
        # Just update version
        config = load_config()
        config["_config_version"] = latest_ver
        save_config(config)

    # ── Skill-declared config vars ──────────────────────────────────────
    # Skills can declare config.yaml settings they need via
    # metadata.hermes.config in their SKILL.md frontmatter.
    # Prompt for any that are missing/empty.
    missing_skill_config = get_missing_skill_config_vars()
    if missing_skill_config and interactive and not quiet:
        print(f"\n  {len(missing_skill_config)} skill setting(s) not configured:")
        for var in missing_skill_config:
            skill_name = var.get("skill", "unknown")
            print(f"    • {var['key']} — {var['description']} (from skill: {skill_name})")
        print()
        try:
            answer = input("  Configure skill settings? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer in {"y", "yes"}:
            print()
            config = load_config()
            try:
                from agent.skill_utils import SKILL_CONFIG_PREFIX
            except Exception:
                SKILL_CONFIG_PREFIX = "skills.config"
            for var in missing_skill_config:
                default = var.get("default", "")
                default_hint = f" (default: {default})" if default else ""
                value = input(f"  {var['prompt']}{default_hint}: ").strip()
                if not value and default:
                    value = str(default)
                if value:
                    storage_key = f"{SKILL_CONFIG_PREFIX}.{var['key']}"
                    _set_nested(config, storage_key, value)
                    results["config_added"].append(var["key"])
                    print(f"  ✓ Saved {var['key']} = {value}")
                else:
                    results["warnings"].append(
                        f"Skipped {var['key']} — skill '{var.get('skill', '?')}' may ask for it later"
                    )
                print()
            save_config(config)
        else:
            print(f"  Set later with: {_PRIMARY_CLI} config set <key> <value>")

    return results






def _items_by_unique_name(items):
    """Return a name-indexed dict only when all items have unique string names."""
    if not isinstance(items, list):
        return None
    indexed = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            return None
        name = item["name"]
        if name in indexed:
            return None
        indexed[name] = item
    return indexed


def _preserve_env_ref_templates(current, raw, loaded_expanded=None):
    """Restore raw ``${VAR}`` templates when a value is otherwise unchanged.

    ``load_config()`` expands env refs for runtime use. When a caller later
    persists that config after modifying some unrelated setting, keep the
    original on-disk template instead of writing the expanded plaintext
    secret back to ``config.yaml``.

    Prefer preserving the raw template when ``current`` still matches either
    the value previously returned by ``load_config()`` for this config path or
    the current environment expansion of ``raw``. This handles env-var
    rotation between load and save while still treating mixed literal/template
    string edits as caller-owned once their rendered value diverges.
    """
    if isinstance(current, str) and isinstance(raw, str) and re.search(r"\${[^}]+}", raw):
        if current == raw:
            return raw
        if isinstance(loaded_expanded, str) and current == loaded_expanded:
            return raw
        if _expand_env_vars(raw) == current:
            return raw
        return current

    if isinstance(current, dict) and isinstance(raw, dict):
        return {
            key: _preserve_env_ref_templates(
                value,
                raw.get(key),
                loaded_expanded.get(key) if isinstance(loaded_expanded, dict) else None,
            )
            for key, value in current.items()
        }

    if isinstance(current, list) and isinstance(raw, list):
        # Prefer matching named config objects (e.g. custom_providers) by name
        # so harmless reordering doesn't drop the original template. If names
        # are duplicated, fall back to positional matching instead of silently
        # shadowing one entry.
        current_by_name = _items_by_unique_name(current)
        raw_by_name = _items_by_unique_name(raw)
        loaded_by_name = _items_by_unique_name(loaded_expanded)
        if current_by_name is not None and raw_by_name is not None:
            return [
                _preserve_env_ref_templates(
                    item,
                    raw_by_name.get(item.get("name")),
                    loaded_by_name.get(item.get("name")) if loaded_by_name is not None else None,
                )
                for item in current
            ]
        return [
            _preserve_env_ref_templates(
                item,
                raw[index] if index < len(raw) else None,
                loaded_expanded[index]
                if isinstance(loaded_expanded, list) and index < len(loaded_expanded)
                else None,
            )
            for index, item in enumerate(current)
        ]

    return current









def read_raw_config() -> Dict[str, Any]:
    """Read a revision-bearing raw snapshot suitable for a checked save."""
    with _CONFIG_LOCK:
        path = get_config_path()
        revision = _config_revision(path)
        result = _ConfigSnapshot(_read_raw_config())
        result._path, result._revision = path.resolve(), revision
        return result


def _read_raw_config() -> Dict[str, Any]:
    """Read active agent-home config.yaml as-is, without merging defaults or migrating.

    Returns the raw YAML dict, or ``{}`` if the file doesn't exist or can't
    be parsed.  Use this for lightweight config reads where you just need a
    single value and don't want the overhead of ``load_config()``'s deep-merge
    + migration pipeline.

    Cached on the config file's contents — same strategy as
    ``load_config()``. Returns a deepcopy on every call since some callers
    mutate the result before passing to ``save_config()``.
    """
    with _CONFIG_LOCK:
        if _ignore_user_config_requested():
            return {}

        try:
            config_path = get_config_path()
            cache_key = config_path.read_bytes()
        except (FileNotFoundError, OSError):
            return {}

        path_key = str(config_path)
        cached = _RAW_CONFIG_CACHE.get(path_key)
        if cached is not None and cached[0] == cache_key:
            return copy.deepcopy(cached[1])

        try:
            data = yaml.safe_load(cache_key.decode("utf-8")) or {}
        except Exception as e:
            _warn_config_parse_failure(config_path, e)
            return {}

        if not isinstance(data, dict):
            data = {}
        _RAW_CONFIG_CACHE[path_key] = (cache_key, copy.deepcopy(data))
        return data


# Stable across runtime module reloads and compatibility import paths. Keeping
# this type in storage prevents an old snapshot from losing revision validation.
from superforecasting_agent.storage.files import ConfigSnapshot as _ConfigSnapshot


from superforecasting_agent.storage.files import config_revision as _config_revision


# Preserve compatibility for callers that serialize a loaded mapping directly.
yaml.SafeDumper.add_representer(_ConfigSnapshot, yaml.representer.SafeRepresenter.represent_dict)
yaml.Dumper.add_representer(_ConfigSnapshot, yaml.representer.SafeRepresenter.represent_dict)


def load_config() -> Dict[str, Any]:
    """Load configuration from ~/.superforecasting-agent/config.yaml.

    Cached on the config file's contents. Returns a deepcopy of
    the cached value when unchanged, since most call sites mutate the
    result (e.g. ``cfg["model"]["default"] = ...`` before ``save_config``).
    The cache is keyed on ``str(config_path)`` so profile switches
    (which change ``HERMES_HOME`` and therefore ``get_config_path()``)
    don't collide.

    Read-only callers should use ``load_config_readonly()`` to skip the
    defensive deepcopy — that path matters in agent-loop hot spots like
    ``get_provider_request_timeout`` which is called once per API turn.

    ``SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG=1`` skips the user config
    entirely, with ``FORECAST_IGNORE_USER_CONFIG`` and
    ``HERMES_IGNORE_USER_CONFIG`` retained as compatibility aliases.
    """
    with _CONFIG_LOCK:
        path = get_config_path().resolve()
        revision = _config_revision(path)
        config = _ConfigSnapshot(_load_config_impl(want_deepcopy=True))
        config._path = path
        # A concurrent replacement during the read conservatively forces reload
        # before saving. Reading a managed/read-only config requires no lock file.
        config._revision = revision
        return config


def reload_config_in_place(config):
    """Replace a wizard's mapping with a fresh snapshot, including its revision."""
    refreshed = load_config()
    config.clear()
    config.update(refreshed)
    if isinstance(config, _ConfigSnapshot):
        config._path = refreshed._path
        config._revision = refreshed._revision
    return config


def load_config_readonly() -> Dict[str, Any]:
    """Fast-path variant of ``load_config()`` for callers that ONLY READ.

    Returns the cached config dict directly without the defensive deepcopy
    that ``load_config()`` applies. **Mutating the returned dict (or any
    nested structure) corrupts the in-process cache for every subsequent
    caller** — only use this when you are absolutely sure your code path
    will not write to the result. If you need to mutate or pass to
    ``save_config``, call ``load_config()`` instead.

    Why this exists: ``load_config()`` cache-hit cost is ~265us per call,
    half of which (~135us) is the defensive deepcopy. The agent loop calls
    into config reads (timeouts, thresholds, feature flags) ~20-50x per
    conversation; skipping deepcopy here removes a measurable allocation
    source and the GC pressure that comes with it.

    Note: this returns a plain ``dict`` (not ``MappingProxyType``) so
    existing ``isinstance(x, dict)`` guards downstream keep working. The
    safety guarantee is purely documented, not enforced — be careful.
    """
    return _load_config_impl(want_deepcopy=False)






def _load_config_impl(*, want_deepcopy: bool) -> Dict[str, Any]:
    with _CONFIG_LOCK:
        ensure_hermes_home()
        config_path = get_config_path()
        path_key = str(config_path)
        ignore_user_config = _ignore_user_config_requested()

        try:
            cache_key: Optional[bytes] = config_path.read_bytes()
        except FileNotFoundError:
            cache_key = None

        cached = _LOAD_CONFIG_CACHE.get(path_key)
        if (
            not ignore_user_config
            and cached is not None
            and cache_key is not None
            and cached[0] == cache_key
        ):
            return copy.deepcopy(cached[1]) if want_deepcopy else cached[1]

        config = copy.deepcopy(DEFAULT_CONFIG)

        if cache_key is not None and not ignore_user_config:
            try:
                user_config = yaml.safe_load(cache_key.decode("utf-8")) or {}

                config = _merge_user_config(user_config)
            except Exception as e:
                _warn_config_parse_failure(config_path, e)

        normalized = _normalize_root_model_keys(_normalize_max_turns_config(config))
        expanded = _expand_env_vars(normalized)
        _LAST_EXPANDED_CONFIG_BY_PATH[path_key] = copy.deepcopy(expanded)
        if cache_key is not None and not ignore_user_config:
            # Cache stores a separate deepcopy so subsequent ``load_config()``
            # (deepcopy=True) callers can mutate freely without affecting the
            # cached value, and ``load_config_readonly()`` (deepcopy=False)
            # callers all see the same stable cached object.
            cached_copy = copy.deepcopy(expanded)
            _LOAD_CONFIG_CACHE[path_key] = (cache_key, cached_copy)
            # On the readonly path return the same cached object subsequent
            # calls will see — keeps "two readonly calls return the same
            # object" invariant that callers may rely on for identity checks.
            if not want_deepcopy:
                return cached_copy
        else:
            _LOAD_CONFIG_CACHE.pop(path_key, None)
        # First-load result is a fresh dict (not aliased to the cache); safe
        # to return directly. For the deepcopy=True path this is the
        # canonical "freshly-built mutable result" the function has always
        # returned. For the deepcopy=False path with no cache (e.g. config
        # file missing), it's also fine — callers get an isolated object.
        return expanded


_SECURITY_COMMENT = """
# ── Security ──────────────────────────────────────────────────────────
# Secret redaction is ON by default — strings that look like API keys,
# tokens, and passwords are masked in tool output, logs, and chat
# responses before the model or user ever sees them. Set redact_secrets
# to false to disable (e.g. when developing the redactor itself).
# tirith pre-exec scanning is enabled by default when the tirith binary
# is available. Configure via security.tirith_* keys or env vars
# (TIRITH_ENABLED, TIRITH_BIN, TIRITH_TIMEOUT, TIRITH_FAIL_OPEN).
#
# security:
#   redact_secrets: true
#   tirith_enabled: true
#   tirith_path: "tirith"
#   tirith_timeout: 5
#   tirith_fail_open: true
"""

_FALLBACK_COMMENT = """
# ── Fallback Model ────────────────────────────────────────────────────
# Automatic provider failover when primary is unavailable.
# Uncomment and configure to enable. Triggers on rate limits (429),
# overload (529), service errors (503), or connection failures.
#
# Supported providers:
#   openrouter   (OPENROUTER_API_KEY)  — routes to any model
#   openai-codex (OAuth — superforecasting-agent auth) — OpenAI Codex
#   nous         (OAuth — superforecasting-agent auth) — Nous Portal
#   zai          (ZAI_API_KEY)         — Z.AI / GLM
#   kimi-coding  (KIMI_API_KEY)        — Kimi / Moonshot
#   kimi-coding-cn (KIMI_CN_API_KEY)   — Kimi / Moonshot (China)
#   minimax      (MINIMAX_API_KEY)     — MiniMax
#   minimax-cn   (MINIMAX_CN_API_KEY)  — MiniMax (China)
#   bedrock      (AWS IAM / boto3)     — AWS Bedrock (Converse API)
#
# For custom OpenAI-compatible endpoints, add base_url and key_env.
#
# fallback_model:
#   provider: openrouter
#   model: anthropic/claude-sonnet-4
"""


_COMMENTED_SECTIONS = """
# ── Security ──────────────────────────────────────────────────────────
# Secret redaction is ON by default. Set to false to pass tool output,
# logs, and chat responses through unmodified (e.g. for redactor dev).
#
# security:
#   redact_secrets: true

# ── Fallback Model ────────────────────────────────────────────────────
# Automatic provider failover when primary is unavailable.
# Uncomment and configure to enable. Triggers on rate limits (429),
# overload (529), service errors (503), or connection failures.
#
# Supported providers:
#   openrouter   (OPENROUTER_API_KEY)  — routes to any model
#   openai-codex (OAuth — superforecasting-agent auth) — OpenAI Codex
#   nous         (OAuth — superforecasting-agent auth) — Nous Portal
#   zai          (ZAI_API_KEY)         — Z.AI / GLM
#   kimi-coding  (KIMI_API_KEY)        — Kimi / Moonshot
#   kimi-coding-cn (KIMI_CN_API_KEY)   — Kimi / Moonshot (China)
#   minimax      (MINIMAX_API_KEY)     — MiniMax
#   minimax-cn   (MINIMAX_CN_API_KEY)  — MiniMax (China)
#   bedrock      (AWS IAM / boto3)     — AWS Bedrock (Converse API)
#
# For custom OpenAI-compatible endpoints, add base_url and key_env.
#
# fallback_model:
#   provider: openrouter
#   model: anthropic/claude-sonnet-4
"""


def save_config(config: Dict[str, Any]):
    """Save configuration, refusing stale loaded snapshots and malformed files."""
    if is_managed():
        managed_error("save configuration")
        return
    from superforecasting_agent.storage.files import yaml_update_lock
    with _CONFIG_LOCK, yaml_update_lock(get_config_path()):
        from superforecasting_agent.storage.files import atomic_yaml_write

        ensure_hermes_home()
        config_path = get_config_path()
        if isinstance(config, _ConfigSnapshot) and (
            config._path != config_path.resolve() or config._revision != _config_revision(config_path)
        ):
            raise ValueError("Configuration changed since it was loaded; reload before saving to preserve concurrent edits")
        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if raw is not None and not isinstance(raw, dict):
                raise ValueError("Configuration root must be a mapping; refusing to overwrite it")
        current_normalized = _normalize_root_model_keys(_normalize_max_turns_config(config))
        normalized = current_normalized
        raw_existing = _normalize_root_model_keys(_normalize_max_turns_config(read_raw_config()))
        if raw_existing:
            normalized = _preserve_env_ref_templates(
                normalized,
                raw_existing,
                _LAST_EXPANDED_CONFIG_BY_PATH.get(str(config_path)),
            )

        # Build optional commented-out sections for features that are off by
        # default or only relevant when explicitly configured.
        parts = []
        sec = normalized.get("security", {})
        if not sec or sec.get("redact_secrets") is None:
            parts.append(_SECURITY_COMMENT)
        fb = normalized.get("fallback_model", {})
        fb_is_valid = False
        if isinstance(fb, list):
            fb_is_valid = any(isinstance(e, dict) and e.get("provider") and e.get("model") for e in fb)
        elif isinstance(fb, dict):
            fb_is_valid = bool(fb.get("provider") and fb.get("model"))
        if not fb_is_valid:
            parts.append(_FALLBACK_COMMENT)

        atomic_yaml_write(
            config_path,
            normalized,
            extra_content="".join(parts) if parts else None,
        )
        _secure_file(config_path)
        if isinstance(config, _ConfigSnapshot):
            config._revision = _config_revision(config_path)
        _LAST_EXPANDED_CONFIG_BY_PATH[str(config_path)] = copy.deepcopy(current_normalized)


def load_env() -> Dict[str, str]:
    """Load environment variables from the active agent-home .env.

    Sanitizes lines before parsing so that corrupted files (e.g.
    concatenated KEY=VALUE pairs on a single line) are handled
    gracefully instead of producing mangled values such as duplicated
    bot tokens.  See #8908.

    The parsed dict is memoised keyed on the .env file mtime, because
    ``get_env_value()`` is called dozens-to-hundreds of times per
    interactive menu render (`superforecasting-agent tools`, setup, status
    panels). Sanitisation is O(lines × known-keys), so re-parsing the
    same file on every call was burning ~300ms of CPU per `superforecasting-agent tools`
    menu paint on top of the OAuth-refresh slowness. The mtime check
    invalidates the cache when the user edits .env mid-process.
    """
    global _env_cache
    env_path = get_env_path()

    try:
        mtime = env_path.stat().st_mtime
        size = env_path.stat().st_size
        cache_key = (str(env_path), mtime, size)
    except FileNotFoundError:
        cache_key = (str(env_path), None, None)
    except Exception:
        cache_key = None

    if cache_key is not None and _env_cache is not None:
        cached_key, cached_vars = _env_cache
        if cached_key == cache_key:
            return dict(cached_vars)

    env_vars: Dict[str, str] = {}

    if env_path.exists():
        # On Windows, open() defaults to the system locale (cp1252) which can
        # fail on UTF-8 .env files. Always use explicit UTF-8; tolerate BOM
        # via utf-8-sig since users may edit .env in Notepad which adds one.
        open_kw = {"encoding": "utf-8-sig", "errors": "replace"}
        with open(env_path, **open_kw) as f:
            raw_lines = f.readlines()
        # Sanitize before parsing: split concatenated lines & drop stale
        # placeholders so corrupted .env files don't produce invalid tokens.
        lines = _sanitize_env_lines(raw_lines)
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                env_vars[key.strip()] = value.strip().strip('"\'')

    if cache_key is not None:
        _env_cache = (cache_key, dict(env_vars))

    return env_vars


# Module-level memo for load_env(), keyed on (path, mtime, size).
# Editing .env bumps mtime → next load_env() rebuilds. invalidate_env_cache()
# is the explicit knob for writers that update .env via this module
# (set_env_value, save_env, etc.) without relying on filesystem mtime
# resolution.
_env_cache: Optional[Tuple[Tuple[str, Optional[float], Optional[int]], Dict[str, str]]] = None


def invalidate_env_cache() -> None:
    """Clear the load_env() process-level memo.

    Writers that mutate .env (set_env_value, save_env, etc.) call this
    to guarantee the next load_env() sees their change even on
    filesystems with coarse mtime resolution. Reads invalidate naturally
    via the mtime/size check.
    """
    global _env_cache
    _env_cache = None


def _sanitize_env_lines(lines: list) -> list:
    """Repair environment lines against the current credential catalog."""
    from superforecasting_agent.configuration.env_lines import sanitize_env_lines
    return sanitize_env_lines(lines, set(OPTIONAL_ENV_VARS) | _EXTRA_ENV_KEYS)


def sanitize_env_file() -> int:
    """Read, sanitize, and rewrite active agent-home .env in place.

    Returns the number of lines that were fixed (concatenation splits +
    placeholder removals).  Returns 0 when no changes are needed.
    """
    env_path = get_env_path()
    if not env_path.exists():
        return 0

    from superforecasting_agent.storage.files import yaml_update_lock
    with yaml_update_lock(env_path):
        read_kw = {"encoding": "utf-8-sig", "errors": "replace"}
        write_kw = {"encoding": "utf-8"}

        with open(env_path, **read_kw) as f:
            original_lines = f.readlines()

        sanitized = _sanitize_env_lines(original_lines)

        if sanitized == original_lines:
            return 0

        # Count fixes: difference in line count (from splits) + removed lines
        fixes = abs(len(sanitized) - len(original_lines))
        if fixes == 0:
            # Lines changed content (e.g. *** removal) even if count is same
            fixes = sum(1 for a, b in zip(original_lines, sanitized) if a != b)
            fixes += abs(len(sanitized) - len(original_lines))

        fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix=".tmp", prefix=".env_")
        try:
            with os.fdopen(fd, "w", **write_kw) as f:
                f.writelines(sanitized)
                f.flush()
                os.fsync(f.fileno())
            atomic_replace(tmp_path, env_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _secure_file(env_path)
        invalidate_env_cache()
        return fixes


def _check_non_ascii_credential(key: str, value: str) -> str:
    """Warn and strip non-ASCII characters from credential values.

    API keys and tokens must be pure ASCII — they are sent as HTTP header
    values which httpx/httpcore encode as ASCII.  Non-ASCII characters
    (commonly introduced by copy-pasting from rich-text editors or PDFs
    that substitute lookalike Unicode glyphs for ASCII letters) cause
    ``UnicodeEncodeError: 'ascii' codec can't encode character`` at
    request time.

    Returns the sanitized (ASCII-only) value.  Prints a warning if any
    non-ASCII characters were found and removed.
    """
    try:
        value.encode("ascii")
        return value  # all ASCII — nothing to do
    except UnicodeEncodeError:
        pass

    # Build a readable list of the offending characters
    bad_chars: list[str] = []
    for i, ch in enumerate(value):
        if ord(ch) > 127:
            bad_chars.append(f"  position {i}: {ch!r} (U+{ord(ch):04X})")
    sanitized = value.encode("ascii", errors="ignore").decode("ascii")

    print(
        f"\n  Warning: {key} contains non-ASCII characters that will break API requests.\n"
        f"  This usually happens when copy-pasting from a PDF, rich-text editor,\n"
        f"  or web page that substitutes lookalike Unicode glyphs for ASCII letters.\n"
        f"\n"
        + "\n".join(f"  {line}" for line in bad_chars[:5])
        + ("\n  ... and more" if len(bad_chars) > 5 else "")
        + f"\n\n  The non-ASCII characters have been stripped automatically.\n"
        f"  If authentication fails, re-copy the key from the provider's dashboard.\n",
        file=sys.stderr,
    )
    return sanitized


def save_env_value(key: str, value: str):
    """Save or update a value in active agent-home .env."""
    if is_managed():
        managed_error(f"set {key}")
        return
    if not _ENV_VAR_NAME_RE.match(key):
        raise ValueError(f"Invalid environment variable name: {key!r}")
    _reject_denylisted_env_var(key)
    value = value.replace("\n", "").replace("\r", "")
    # API keys / tokens must be ASCII — strip non-ASCII with a warning.
    value = _check_non_ascii_credential(key, value)
    ensure_hermes_home()
    env_path = get_env_path()
    from superforecasting_agent.storage.files import yaml_update_lock
    with yaml_update_lock(env_path):

        # On Windows, open() defaults to the system locale (cp1252) which can
        # cause OSError errno 22 on UTF-8 .env files.
        read_kw = {"encoding": "utf-8-sig", "errors": "replace"}
        write_kw = {"encoding": "utf-8"}

        lines = []
        if env_path.exists():
            with open(env_path, **read_kw) as f:
                lines = f.readlines()
            # Sanitize on every read: split concatenated keys, drop stale placeholders
            lines = _sanitize_env_lines(lines)

        # Find and update or append
        found = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                found = True
                break

        if not found:
            # Ensure there's a newline at the end of the file before appending
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"{key}={value}\n")
    
        fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix='.tmp', prefix='.env_')
        # Preserve original permissions so Docker volume mounts aren't clobbered.
        original_mode = None
        if env_path.exists():
            try:
                original_mode = stat.S_IMODE(env_path.stat().st_mode)
            except OSError:
                pass
        try:
            with os.fdopen(fd, 'w', **write_kw) as f:
                f.writelines(lines)
                f.flush()
                os.fsync(f.fileno())
            atomic_replace(tmp_path, env_path)
            # Restore original permissions before _secure_file may tighten them.
            if original_mode is not None:
                try:
                    os.chmod(env_path, original_mode)
                except OSError:
                    pass
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        _secure_file(env_path)

        os.environ[key] = value
        invalidate_env_cache()


def remove_env_value(key: str) -> bool:
    """Remove a key from active agent-home .env and os.environ.

    Returns True if the key was found and removed, False otherwise.
    """
    if is_managed():
        managed_error(f"remove {key}")
        return False
    if not _ENV_VAR_NAME_RE.match(key):
        raise ValueError(f"Invalid environment variable name: {key!r}")
    env_path = get_env_path()
    if not env_path.exists():
        os.environ.pop(key, None)
        return False

    from superforecasting_agent.storage.files import yaml_update_lock
    with yaml_update_lock(env_path):
        read_kw = {"encoding": "utf-8-sig", "errors": "replace"}
        write_kw = {"encoding": "utf-8"}

        with open(env_path, **read_kw) as f:
            lines = f.readlines()
        lines = _sanitize_env_lines(lines)

        new_lines = [line for line in lines if not line.strip().startswith(f"{key}=")]
        found = len(new_lines) < len(lines)

        if found:
            fd, tmp_path = tempfile.mkstemp(dir=str(env_path.parent), suffix='.tmp', prefix='.env_')
            # Preserve original permissions so Docker volume mounts aren't clobbered.
            original_mode = None
            try:
                original_mode = stat.S_IMODE(env_path.stat().st_mode)
            except OSError:
                pass
            try:
                with os.fdopen(fd, 'w', **write_kw) as f:
                    f.writelines(new_lines)
                    f.flush()
                    os.fsync(f.fileno())
                atomic_replace(tmp_path, env_path)
                if original_mode is not None:
                    try:
                        os.chmod(env_path, original_mode)
                    except OSError:
                        pass
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            _secure_file(env_path)

        os.environ.pop(key, None)
        invalidate_env_cache()
        return found


def save_anthropic_oauth_token(value: str, save_fn=None):
    """Persist an Anthropic OAuth/setup token and clear the API-key slot."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_TOKEN", value)
    writer("ANTHROPIC_API_KEY", "")


def use_anthropic_claude_code_credentials(save_fn=None):
    """Use Claude Code's own credential files instead of persisting env tokens."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_TOKEN", "")
    writer("ANTHROPIC_API_KEY", "")


def save_anthropic_api_key(value: str, save_fn=None):
    """Persist an Anthropic API key and clear the OAuth/setup-token slot."""
    writer = save_fn or save_env_value
    writer("ANTHROPIC_API_KEY", value)
    writer("ANTHROPIC_TOKEN", "")


def save_env_value_secure(key: str, value: str) -> Dict[str, Any]:
    save_env_value(key, value)
    return {
        "success": True,
        "stored_as": key,
        "validated": False,
    }



def reload_env() -> int:
    """Re-read active agent-home .env into os.environ.

    Adds/updates vars that changed and removes vars that were deleted from
    the .env file (but only known agent env vars — OPTIONAL_ENV_VARS and
    _EXTRA_ENV_KEYS — to avoid clobbering unrelated environment).
    """
    env_vars = load_env()
    known_keys = set(OPTIONAL_ENV_VARS.keys()) | _EXTRA_ENV_KEYS
    count = 0
    for key, value in env_vars.items():
        if os.environ.get(key) != value:
            os.environ[key] = value
            count += 1
    # Remove known agent vars that are no longer in .env
    for key in known_keys:
        if key not in env_vars and key in os.environ:
            del os.environ[key]
            count += 1
    return count


def get_env_value(key: str) -> Optional[str]:
    """Get a value from active agent-home .env or environment."""
    # Check environment first
    if key in os.environ:
        return os.environ[key]
    
    # Then check .env file
    env_vars = load_env()
    return env_vars.get(key)


# =============================================================================
# Config display
# =============================================================================

def redact_key(key: str) -> str:
    """Redact an API key for display.

    Thin wrapper over :func:`agent.redact.mask_secret` — preserves the
    "(not set)" placeholder in dim color for the empty case.
    """
    from agent.redact import mask_secret
    return mask_secret(key, empty=color("(not set)", Colors.DIM))


def show_config():
    """Display current configuration."""
    config = load_config()
    
    print()
    print(color("┌─────────────────────────────────────────────────────────┐", Colors.CYAN))
    print(color("│       ⚕ Superforecasting Agent Configuration           │", Colors.CYAN))
    print(color("└─────────────────────────────────────────────────────────┘", Colors.CYAN))
    
    # Paths
    print()
    print(color("◆ Paths", Colors.CYAN, Colors.BOLD))
    print(f"  Config:       {get_config_path()}")
    print(f"  Secrets:      {get_env_path()}")
    print(f"  Install:      {get_project_root()}")
    
    # API Keys
    print()
    print(color("◆ API Keys", Colors.CYAN, Colors.BOLD))
    
    keys = [
        ("OPENROUTER_API_KEY", "OpenRouter"),
        ("VOICE_TOOLS_OPENAI_KEY", "OpenAI (STT/TTS)"),
        ("EXA_API_KEY", "Exa"),
        ("PARALLEL_API_KEY", "Parallel"),
        ("FIRECRAWL_API_KEY", "Firecrawl"),
        ("TAVILY_API_KEY", "Tavily"),
        ("BROWSERBASE_API_KEY", "Browserbase"),
        ("BROWSER_USE_API_KEY", "Browser Use"),
        ("FAL_KEY", "FAL"),
    ]
    
    for env_key, name in keys:
        value = get_env_value(env_key)
        print(f"  {name:<14} {redact_key(value)}")
    from superforecasting_agent.runtime.auth import get_anthropic_key
    anthropic_value = get_anthropic_key()
    print(f"  {'Anthropic':<14} {redact_key(anthropic_value)}")
    
    # Model settings
    print()
    print(color("◆ Model", Colors.CYAN, Colors.BOLD))
    print(f"  Model:        {config.get('model', 'not set')}")
    print(f"  Max turns:    {config.get('agent', {}).get('max_turns', DEFAULT_CONFIG['agent']['max_turns'])}")
    
    # Display
    print()
    print(color("◆ Display", Colors.CYAN, Colors.BOLD))
    display = config.get('display', {})
    print(f"  Style:        {display.get('personality', 'neutral')}")
    print(f"  Reasoning:    {'on' if display.get('show_reasoning', False) else 'off'}")
    print(f"  Bell:         {'on' if display.get('bell_on_complete', False) else 'off'}")
    ump = display.get('user_message_preview', {}) if isinstance(display.get('user_message_preview', {}), dict) else {}
    ump_first = ump.get('first_lines', 2)
    ump_last = ump.get('last_lines', 2)
    print(f"  User preview: first {ump_first} line(s), last {ump_last} line(s)")

    # Terminal
    print()
    print(color("◆ Terminal", Colors.CYAN, Colors.BOLD))
    terminal = config.get('terminal', {})
    print(f"  Backend:      {terminal.get('backend', 'local')}")
    print(f"  Working dir:  {terminal.get('cwd', '.')}")
    print(f"  Timeout:      {terminal.get('timeout', 60)}s")
    
    if terminal.get('backend') == 'docker':
        print(f"  Docker image: {terminal.get('docker_image', 'nikolaik/python-nodejs:python3.11-nodejs20')}")
    elif terminal.get('backend') == 'singularity':
        print(f"  Image:        {terminal.get('singularity_image', 'docker://nikolaik/python-nodejs:python3.11-nodejs20')}")
    elif terminal.get('backend') == 'modal':
        print(f"  Modal image:  {terminal.get('modal_image', 'nikolaik/python-nodejs:python3.11-nodejs20')}")
        modal_token = get_env_value('MODAL_TOKEN_ID')
        print(f"  Modal token:  {'configured' if modal_token else '(not set)'}")
    elif terminal.get('backend') == 'daytona':
        print(f"  Daytona image: {terminal.get('daytona_image', 'nikolaik/python-nodejs:python3.11-nodejs20')}")
        daytona_key = get_env_value('DAYTONA_API_KEY')
        print(f"  API key:      {'configured' if daytona_key else '(not set)'}")
    elif terminal.get('backend') == 'vercel_sandbox':
        print(f"  Vercel runtime: {terminal.get('vercel_runtime', 'node24')}")
        print(f"  Vercel auth:    {'configured' if get_env_value('VERCEL_OIDC_TOKEN') or (get_env_value('VERCEL_TOKEN') and get_env_value('VERCEL_PROJECT_ID') and get_env_value('VERCEL_TEAM_ID')) else '(not set)'}")
    elif terminal.get('backend') == 'ssh':
        ssh_host = get_env_value('TERMINAL_SSH_HOST')
        ssh_user = get_env_value('TERMINAL_SSH_USER')
        print(f"  SSH host:     {ssh_host or '(not set)'}")
        print(f"  SSH user:     {ssh_user or '(not set)'}")
    
    # Timezone
    print()
    print(color("◆ Timezone", Colors.CYAN, Colors.BOLD))
    tz = config.get('timezone', '')
    if tz:
        print(f"  Timezone:     {tz}")
    else:
        print(f"  Timezone:     {color('(server-local)', Colors.DIM)}")

    # Compression
    print()
    print(color("◆ Context Compression", Colors.CYAN, Colors.BOLD))
    compression = config.get('compression', {})
    enabled = compression.get('enabled', True)
    print(f"  Enabled:      {'yes' if enabled else 'no'}")
    if enabled:
        print(f"  Threshold:    {compression.get('threshold', 0.50) * 100:.0f}%")
        print(f"  Target ratio: {compression.get('target_ratio', 0.20) * 100:.0f}% of threshold preserved")
        print(f"  Protect last: {compression.get('protect_last_n', 20)} messages")
        print(f"  Protect first: {compression.get('protect_first_n', 3)} non-system head messages")
        _aux_comp = config.get('auxiliary', {}).get('compression', {})
        _sm = _aux_comp.get('model', '') or '(auto)'
        print(f"  Model:        {_sm}")
        comp_provider = _aux_comp.get('provider', 'auto')
        if comp_provider and comp_provider != 'auto':
            print(f"  Provider:     {comp_provider}")
    
    # Auxiliary models
    auxiliary = config.get('auxiliary', {})
    aux_tasks = {
        "Vision":      auxiliary.get('vision', {}),
        "Web extract": auxiliary.get('web_extract', {}),
    }
    has_overrides = any(
        t.get('provider', 'auto') != 'auto' or t.get('model', '')
        for t in aux_tasks.values()
    )
    if has_overrides:
        print()
        print(color("◆ Auxiliary Models (overrides)", Colors.CYAN, Colors.BOLD))
        for label, task_cfg in aux_tasks.items():
            prov = task_cfg.get('provider', 'auto')
            mdl = task_cfg.get('model', '')
            if prov != 'auto' or mdl:
                parts = [f"provider={prov}"]
                if mdl:
                    parts.append(f"model={mdl}")
                print(f"  {label:12s}  {', '.join(parts)}")
    
    # Messaging
    print()
    print(color("◆ Messaging Platforms", Colors.CYAN, Colors.BOLD))
    
    telegram_token = get_env_value('TELEGRAM_BOT_TOKEN')
    discord_token = get_env_value('DISCORD_BOT_TOKEN')
    
    print(f"  Telegram:     {'configured' if telegram_token else color('not configured', Colors.DIM)}")
    print(f"  Discord:      {'configured' if discord_token else color('not configured', Colors.DIM)}")
    
    # Skill config
    try:
        from agent.skill_utils import discover_all_skill_config_vars, resolve_skill_config_values
        skill_vars = discover_all_skill_config_vars()
        if skill_vars:
            resolved = resolve_skill_config_values(skill_vars)
            print()
            print(color("◆ Skill Settings", Colors.CYAN, Colors.BOLD))
            for var in skill_vars:
                key = var["key"]
                value = resolved.get(key, "")
                skill_name = var.get("skill", "")
                display_val = str(value) if value else color("(not set)", Colors.DIM)
                print(f"  {key:<20s} {display_val}  {color(f'[{skill_name}]', Colors.DIM)}")
    except Exception:
        pass

    print()
    print(color("─" * 60, Colors.DIM))
    print(color("  superforecasting-agent config edit     # Edit config file", Colors.DIM))
    print(color("  superforecasting-agent config set <key> <value>", Colors.DIM))
    print(color("  superforecasting-agent setup           # Run setup wizard", Colors.DIM))
    print()


def edit_config():
    """Open config file in user's editor."""
    if is_managed():
        managed_error("edit configuration")
        return
    config_path = get_config_path()
    
    # Ensure config exists
    if not config_path.exists():
        save_config(DEFAULT_CONFIG)
        print(f"Created {config_path}")
    
    # Find editor
    editor = os.getenv('EDITOR') or os.getenv('VISUAL')

    if not editor:
        # Try common editors — order is platform-aware so Windows users
        # land on a working editor (notepad) even without Git Bash or nano
        # installed.  On POSIX, prefer nano/vim over code/notepad because
        # it's more likely to be present on headless / server systems.
        import shutil
        import sys as _sys
        if _sys.platform == "win32":
            candidates = ['notepad', 'code', 'vim', 'vi', 'nano']
        else:
            candidates = ['nano', 'vim', 'vi', 'code', 'notepad']
        for cmd in candidates:
            if shutil.which(cmd):
                editor = cmd
                break
    
    if not editor:
        print("No editor found. Config file is at:")
        print(f"  {config_path}")
        return
    
    print(f"Opening {config_path} in {editor}...")
    subprocess.run([editor, str(config_path)])


def set_config_value(key: str, value: str):
    """Set a configuration value."""
    if is_managed():
        managed_error("set configuration values")
        return
    # Check if it's an API key (goes to .env)
    api_keys = [
        'OPENROUTER_API_KEY', 'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'VOICE_TOOLS_OPENAI_KEY',
        'EXA_API_KEY', 'PARALLEL_API_KEY', 'FIRECRAWL_API_KEY', 'FIRECRAWL_API_URL',
        'FIRECRAWL_GATEWAY_URL', 'TOOL_GATEWAY_DOMAIN', 'TOOL_GATEWAY_SCHEME',
        'TOOL_GATEWAY_USER_TOKEN', 'TAVILY_API_KEY',
        'BROWSERBASE_API_KEY', 'BROWSERBASE_PROJECT_ID', 'BROWSER_USE_API_KEY',
        'FAL_KEY', 'TELEGRAM_BOT_TOKEN', 'DISCORD_BOT_TOKEN',
        'TERMINAL_SSH_HOST', 'TERMINAL_SSH_USER', 'TERMINAL_SSH_KEY',
        'SUDO_PASSWORD', 'SLACK_BOT_TOKEN', 'SLACK_APP_TOKEN',
        'GITHUB_TOKEN', 'HONCHO_API_KEY',
    ]
    
    if key.upper() in api_keys or key.upper().endswith(('_API_KEY', '_TOKEN')) or key.upper().startswith('TERMINAL_SSH'):
        save_env_value(key.upper(), value)
        print(f"✓ Set {key} in {get_env_path()}")
        return
    
    # Otherwise it goes to config.yaml
    # Read the raw user config (not merged with defaults) to avoid
    # dumping all default values back to the file
    config_path = get_config_path()
    # Handle nested keys (e.g., "tts.provider") including numeric list
    # indices (e.g., "custom_providers.0.api_key").  Delegates to
    # _set_nested which preserves list-typed nodes; before #17876 the
    # inline navigation here silently overwrote lists with dicts.

    from superforecasting_agent.configuration import parse_setting_value
    value = parse_setting_value(value)

    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_update
    with _CONFIG_LOCK:
        atomic_roundtrip_yaml_update(config_path, key, value)

    # Keep .env in sync for keys that terminal_tool reads directly from env vars.
    # config.yaml is authoritative, but terminal_tool only reads TERMINAL_ENV etc.
    _config_to_env_sync = {
        "terminal.backend": "TERMINAL_ENV",
        "terminal.modal_mode": "TERMINAL_MODAL_MODE",
        "terminal.docker_image": "TERMINAL_DOCKER_IMAGE",
        "terminal.singularity_image": "TERMINAL_SINGULARITY_IMAGE",
        "terminal.modal_image": "TERMINAL_MODAL_IMAGE",
        "terminal.daytona_image": "TERMINAL_DAYTONA_IMAGE",
        "terminal.vercel_runtime": "TERMINAL_VERCEL_RUNTIME",
        "terminal.docker_mount_cwd_to_workspace": "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE",
        "terminal.docker_run_as_host_user": "TERMINAL_DOCKER_RUN_AS_HOST_USER",
        "terminal.docker_env": "TERMINAL_DOCKER_ENV",
        # terminal.cwd intentionally excluded — CLI resolves at runtime,
        # gateway bridges it in gateway/run.py. Persisting to .env causes
        # stale values to poison child processes.
        "terminal.timeout": "TERMINAL_TIMEOUT",
        "terminal.sandbox_dir": "TERMINAL_SANDBOX_DIR",
        "terminal.persistent_shell": "TERMINAL_PERSISTENT_SHELL",
        "terminal.container_cpu": "TERMINAL_CONTAINER_CPU",
        "terminal.container_memory": "TERMINAL_CONTAINER_MEMORY",
        "terminal.container_disk": "TERMINAL_CONTAINER_DISK",
        "terminal.container_persistent": "TERMINAL_CONTAINER_PERSISTENT",
    }
    if key in _config_to_env_sync:
        save_env_value(_config_to_env_sync[key], str(value))

    print(f"✓ Set {key} = {value} in {config_path}")


# =============================================================================
# Command handler
# =============================================================================

def config_command(args):
    """Handle config subcommands."""
    subcmd = getattr(args, 'config_command', None)
    
    if subcmd is None or subcmd == "show":
        show_config()
    
    elif subcmd == "edit":
        edit_config()
    
    elif subcmd == "set":
        key = getattr(args, 'key', None)
        value = getattr(args, 'value', None)
        if not key or value is None:
            print("Usage: superforecasting-agent config set <key> <value>")
            print()
            print("Examples:")
            print("  superforecasting-agent config set model anthropic/claude-sonnet-4")
            print("  superforecasting-agent config set terminal.backend docker")
            print("  superforecasting-agent config set OPENROUTER_API_KEY sk-or-...")
            sys.exit(1)
        set_config_value(key, value)
    
    elif subcmd == "path":
        print(get_config_path())
    
    elif subcmd == "env-path":
        print(get_env_path())
    
    elif subcmd == "migrate":
        print()
        print(color("🔄 Checking configuration for updates...", Colors.CYAN, Colors.BOLD))
        print()
        
        # Check what's missing
        missing_env = get_missing_env_vars(required_only=False)
        missing_config = get_missing_config_fields()
        current_ver, latest_ver = check_config_version()
        
        if not missing_env and not missing_config and current_ver >= latest_ver:
            print(color("✓ Configuration is up to date!", Colors.GREEN))
            print()
            return
        
        # Show what needs to be updated
        if current_ver < latest_ver:
            print(f"  Config version: {current_ver} → {latest_ver}")
        
        if missing_config:
            print(f"\n  {len(missing_config)} new config option(s) will be added with defaults")
        
        required_missing = [v for v in missing_env if v.get("is_required")]
        optional_missing = [
            v for v in missing_env
            if not v.get("is_required") and not v.get("advanced")
        ]
        
        if required_missing:
            print(f"\n  ⚠️  {len(required_missing)} required API key(s) missing:")
            for var in required_missing:
                print(f"     • {var['name']}")
        
        if optional_missing:
            print(f"\n  ℹ️  {len(optional_missing)} optional API key(s) not configured:")
            for var in optional_missing:
                tools = var.get("tools", [])
                tools_str = f" (enables: {', '.join(tools[:2])})" if tools else ""
                print(f"     • {var['name']}{tools_str}")
        
        print()
        
        # Run migration
        results = migrate_config(interactive=True, quiet=False)
        
        print()
        if results["env_added"] or results["config_added"]:
            print(color("✓ Configuration updated!", Colors.GREEN))
        
        if results["warnings"]:
            print()
            for warning in results["warnings"]:
                print(color(f"  ⚠️  {warning}", Colors.YELLOW))
        
        print()
    
    elif subcmd == "check":
        # Non-interactive check for what's missing
        print()
        print(color("📋 Configuration Status", Colors.CYAN, Colors.BOLD))
        print()
        
        current_ver, latest_ver = check_config_version()
        if current_ver >= latest_ver:
            print(f"  Config version: {current_ver} ✓")
        else:
            print(color(f"  Config version: {current_ver} → {latest_ver} (update available)", Colors.YELLOW))
        
        print()
        print(color("  Required:", Colors.BOLD))
        for var_name in REQUIRED_ENV_VARS:
            if get_env_value(var_name):
                print(f"    ✓ {var_name}")
            else:
                print(color(f"    ✗ {var_name} (missing)", Colors.RED))
        
        print()
        print(color("  Optional:", Colors.BOLD))
        for var_name, info in OPTIONAL_ENV_VARS.items():
            if get_env_value(var_name):
                print(f"    ✓ {var_name}")
            else:
                tools = info.get("tools", [])
                tools_str = f" → {', '.join(tools[:2])}" if tools else ""
                print(color(f"    ○ {var_name}{tools_str}", Colors.DIM))
        
        missing_config = get_missing_config_fields()
        if missing_config:
            print()
            print(color(f"  {len(missing_config)} new config option(s) available", Colors.YELLOW))
            print("    Run 'superforecasting-agent config migrate' to add them")
        
        print()
    
    else:
        print(f"Unknown config command: {subcmd}")
        print()
        print("Available commands:")
        print("  superforecasting-agent config           Show current configuration")
        print("  superforecasting-agent config edit      Open config in editor")
        print("  superforecasting-agent config set <key> <value>   Set a config value")
        print("  superforecasting-agent config check     Check for missing/outdated config")
        print("  superforecasting-agent config migrate   Update config with new options")
        print("  superforecasting-agent config path      Show config file path")
        print("  superforecasting-agent config env-path  Show .env file path")
        sys.exit(1)


# ── Profile-driven env var injection ─────────────────────────────────────────
# Any provider registered in providers/ with auth_type="api_key" automatically
# gets its env_vars exposed in OPTIONAL_ENV_VARS without editing this file.
# Runs once at import time.

_profile_env_vars_injected = False


def _inject_profile_env_vars() -> None:
    """Populate OPTIONAL_ENV_VARS from provider profiles not already listed.

    Called once at module load time. Idempotent — repeated calls are no-ops.
    """
    global _profile_env_vars_injected
    if _profile_env_vars_injected:
        return
    _profile_env_vars_injected = True
    try:
        from providers import list_providers
        for _pp in list_providers():
            if _pp.auth_type not in {"api_key",}:
                continue
            for _var in _pp.env_vars:
                if _var in OPTIONAL_ENV_VARS:
                    continue
                _is_key = not _var.endswith("_BASE_URL") and not _var.endswith("_URL")
                OPTIONAL_ENV_VARS[_var] = {
                    "description": f"{_pp.display_name or _pp.name} {'API key' if _is_key else 'base URL override'}",
                    "prompt": f"{_pp.display_name or _pp.name} {'API key' if _is_key else 'base URL (leave empty for default)'}",
                    "url": _pp.signup_url or None,
                    "password": _is_key,
                    "category": "provider",
                    "advanced": True,
                }
    except Exception:
        pass


# Eagerly inject so that OPTIONAL_ENV_VARS is fully populated at import time.
_inject_profile_env_vars()


# ── Platform-plugin env var injection ────────────────────────────────────────
# Bundled platform plugins under ``plugins/platforms/*/plugin.yaml`` declare
# their required env vars via ``requires_env``.  This mirror of
# ``_inject_profile_env_vars`` surfaces them in
# ``superforecasting-agent config`` UI so users can configure Teams / IRC /
# Google Chat without the core repo ever needing to know they exist.
#
# Each ``requires_env`` entry may be a bare string (name only) or a dict:
#
#   requires_env:
#     - TEAMS_CLIENT_ID                          # minimal
#     - name: TEAMS_CLIENT_SECRET                # rich
#       description: "Teams bot client secret"
#       url: "https://portal.azure.com/"
#       password: true
#       prompt: "Teams client secret"
#
# An optional ``optional_env`` block surfaces non-required vars the same way
# (e.g. allowlist, home channel).

_platform_plugin_env_vars_injected = False


def _inject_platform_plugin_env_vars() -> None:
    """Populate OPTIONAL_ENV_VARS from bundled platform plugin manifests.

    Called once at module load time. Idempotent — repeated calls are no-ops.
    Failures are swallowed so a malformed plugin.yaml can't break CLI import.
    """
    global _platform_plugin_env_vars_injected
    if _platform_plugin_env_vars_injected:
        return
    _platform_plugin_env_vars_injected = True
    try:
        import yaml  # type: ignore

        # Resolve the bundled plugins dir from this file's location so the
        # injector works regardless of CWD.
        repo_root = get_install_root()
        platforms_dir = repo_root / "plugins" / "platforms"
        if not platforms_dir.is_dir():
            return
        for child in platforms_dir.iterdir():
            if not child.is_dir():
                continue
            manifest_path = child / "plugin.yaml"
            if not manifest_path.exists():
                manifest_path = child / "plugin.yml"
            if not manifest_path.exists():
                continue
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = yaml.safe_load(f) or {}
            except Exception:
                continue
            label = manifest.get("label") or manifest.get("name") or child.name
            # Merge required + optional env var declarations.
            entries = list(manifest.get("requires_env") or [])
            entries.extend(manifest.get("optional_env") or [])
            for entry in entries:
                if isinstance(entry, str):
                    name = entry
                    meta: dict = {}
                elif isinstance(entry, dict) and entry.get("name"):
                    name = entry["name"]
                    meta = entry
                else:
                    continue
                if name in OPTIONAL_ENV_VARS:
                    continue  # hardcoded entry wins (back-compat)
                # Heuristic: anything named *TOKEN, *SECRET, *KEY, *PASSWORD
                # is a password field unless explicitly overridden.
                name_upper = name.upper()
                is_secret = bool(meta.get("password") or meta.get("secret"))
                if not is_secret and not meta.get("password") is False:
                    is_secret = any(
                        name_upper.endswith(suf)
                        for suf in ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_JSON")
                    )
                OPTIONAL_ENV_VARS[name] = {
                    "description": (
                        meta.get("description")
                        or f"{label} configuration"
                    ),
                    "prompt": meta.get("prompt") or name,
                    "url": meta.get("url") or None,
                    "password": is_secret,
                    "category": meta.get("category") or "messaging",
                }
    except Exception:
        pass


# Eagerly inject so that platform plugin env vars show up in the setup wizard.
_inject_platform_plugin_env_vars()
