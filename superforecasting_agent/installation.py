"""Installation ownership and managed-configuration policy without CLI setup."""

from __future__ import annotations

import os
from pathlib import Path

from superforecasting_agent.constants import get_agent_home

_MANAGED_TRUE_VALUES = ("true", "1", "yes")

_MANAGED_SYSTEM_NAMES = {
    "brew": "Homebrew",
    "homebrew": "Homebrew",
    "nix": "NixOS",
    "nixos": "NixOS",
}

_MANAGED_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_MANAGED",
    "FORECAST_MANAGED",
    "HERMES_MANAGED",
)


def _managed_env_setting() -> tuple[str, str]:
    """Return the first non-empty managed-install env setting."""
    for name in _MANAGED_ENV_NAMES:
        raw = os.getenv(name, "").strip()
        if raw:
            return name, raw
    return "HERMES_MANAGED", ""


def get_managed_system(home: Path | None = None) -> str | None:
    """Return the package manager owning this install, if any."""
    _env_name, raw = _managed_env_setting()
    if raw:
        normalized = raw.lower()
        if normalized in _MANAGED_TRUE_VALUES:
            return "NixOS"
        return _MANAGED_SYSTEM_NAMES.get(normalized, raw)

    managed_marker = (home if home is not None else get_agent_home()) / ".managed"
    if managed_marker.exists():
        return "NixOS"
    return None


def format_managed_message(
    action: str = "modify this Superforecasting Agent installation",
    *,
    system: str | None = None,
    setting: tuple[str, str] | None = None,
) -> str:
    """Build a user-facing error for managed installs."""
    managed_system = system or get_managed_system() or "a package manager"
    env_name, raw_value = setting if setting is not None else _managed_env_setting()
    raw = raw_value.lower()

    if managed_system == "NixOS":
        env_hint = "true" if raw in _MANAGED_TRUE_VALUES else raw or "true"
        return (
            f"Cannot {action}: this Superforecasting Agent installation is managed by NixOS "
            f"({env_name}={env_hint}).\n"
            "Edit services.superforecasting-agent.settings in your configuration.nix and run:\n"
            "  sudo nixos-rebuild switch"
        )

    if managed_system == "Homebrew":
        env_hint = raw or "homebrew"
        return (
            f"Cannot {action}: this Superforecasting Agent installation is managed by Homebrew "
            f"({env_name}={env_hint}).\n"
            "Use:\n"
            "  brew upgrade superforecasting-agent"
        )

    return (
        f"Cannot {action}: this Superforecasting Agent installation is managed by {managed_system}.\n"
        "Use your package manager to upgrade or reinstall Superforecasting Agent."
    )


def require_configuration_writable(
    action: str = "modify configuration", *, home: Path | None = None
) -> None:
    system = get_managed_system(home)
    if system is not None:
        raise PermissionError(format_managed_message(action, system=system))
