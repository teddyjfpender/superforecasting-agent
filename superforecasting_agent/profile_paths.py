"""Profile identity admission and paths, without administrative side effects."""

from __future__ import annotations

import re
from pathlib import Path

from superforecasting_agent.constants import get_default_agent_root

_RESERVED_NAMES = frozenset({
    "forecast",
    "hermes",
    "hermes-agent",
    "superforecast",
    "superforecasting-agent",
    "default",
    "test",
    "tmp",
    "root",
    "sudo",
})


def normalize_profile_name(name: str) -> str:
    """Return the canonical profile id used on disk and in CLI ``-p`` argv.

    Named profiles are stored lowercase under ``profiles/<id>/``. The special
    alias ``default`` is matched case-insensitively (``Default`` → ``default``).
    Dashboards and tools may pass title-cased display labels; normalize before
    validation, assignment, and subprocess spawn (see issue #18498).
    """
    if not isinstance(name, str):
        name = str(name)
    stripped = name.strip()
    if not stripped:
        raise ValueError("profile name cannot be empty")
    if stripped.casefold() == "default":
        return "default"
    return stripped.lower()


def validate_profile_name(name: str) -> None:
    """Raise ``ValueError`` if *name* is not a valid profile identifier.

    Validates the input as-given — strict lowercase match. Callers that accept
    mixed-case or title-cased input from users (dashboard UI, CLI args) should
    call :func:`normalize_profile_name` first. This separation keeps validate
    honest about what the on-disk directory name must look like, while
    ingress-point normalization handles UX flexibility (see #18498).

    Also rejects names in :data:`_RESERVED_NAMES` that would create confusing
    on-disk collisions, clobber fork-native wrapper commands such as
    ``forecast`` or ``superforecasting-agent``, or get refused at
    alias-creation time anyway. ``default`` is a special pass-through — it's a
    valid alias for the built-in root profile.
    """
    if name == "default":
        return  # special alias for the default runtime root
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError(
            f"Invalid profile name {name!r}. Must match [a-z0-9][a-z0-9_-]{{0,63}}"
        )
    if name in _RESERVED_NAMES:
        raise ValueError(
            f"Profile name {name!r} is reserved — it collides with either "
            f"the Superforecasting Agent installation itself or a common system binary.  "
            f"Pick a different name."
        )


def get_profile_dir(name: str) -> Path:
    """Resolve a profile name to its HERMES_HOME directory."""
    canon = normalize_profile_name(name)
    validate_profile_name(canon)
    if canon == "default":
        return get_default_agent_root()
    return (get_default_agent_root() / "profiles") / canon


def resolve_profile_env(profile_name: str) -> str:
    """Resolve a profile name to a HERMES_HOME path string.

    Called early in the CLI entry point, before any runtime modules
    are imported, to set the HERMES_HOME environment variable.
    """
    canon = normalize_profile_name(profile_name)
    validate_profile_name(canon)
    profile_dir = get_profile_dir(canon)

    if canon != "default" and not profile_dir.is_dir():
        raise FileNotFoundError(
            f"Profile '{canon}' does not exist. "
            f"Create it with: superforecasting-agent profile create {canon}"
        )

    return str(profile_dir)
