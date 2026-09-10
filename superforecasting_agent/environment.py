"""Environment aliases and typed values shared by runtime entry points."""

import os
from typing import Any


TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})


EPHEMERAL_SYSTEM_PROMPT_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_EPHEMERAL_SYSTEM_PROMPT",
    "FORECAST_EPHEMERAL_SYSTEM_PROMPT",
    "HERMES_EPHEMERAL_SYSTEM_PROMPT",
)


PREFILL_MESSAGES_FILE_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_PREFILL_MESSAGES_FILE",
    "FORECAST_PREFILL_MESSAGES_FILE",
    "HERMES_PREFILL_MESSAGES_FILE",
)


INTERACTIVE_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_INTERACTIVE",
    "FORECAST_INTERACTIVE",
    "HERMES_INTERACTIVE",
)


SESSION_SOURCE_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_SESSION_SOURCE",
    "FORECAST_SESSION_SOURCE",
    "HERMES_SESSION_SOURCE",
)


MODEL_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_MODEL",
    "FORECAST_MODEL",
    "HERMES_MODEL",
)


INFERENCE_MODEL_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_INFERENCE_MODEL",
    "FORECAST_INFERENCE_MODEL",
    "HERMES_INFERENCE_MODEL",
)


INFERENCE_PROVIDER_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_INFERENCE_PROVIDER",
    "FORECAST_INFERENCE_PROVIDER",
    "HERMES_INFERENCE_PROVIDER",
)


def is_truthy_value(value: Any, default: bool = False) -> bool:
    """Coerce bool-ish values using the project's shared truthy string set."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_STRINGS
    return bool(value)


def env_var_enabled(name: str, default: str = "") -> bool:
    """Return True when an environment variable is set to a truthy value."""
    return is_truthy_value(os.getenv(name, default), default=False)


def env_var_alias_enabled(names: tuple[str, ...], default: str = "") -> bool:
    """Return True for the first present env var in a compatibility alias set."""
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return is_truthy_value(value, default=False)
    return is_truthy_value(default, default=False)


def env_var_alias_value(
    names: tuple[str, ...], default: str | None = None
) -> str | None:
    """Return the first present value in a compatibility alias set."""
    for name in names:
        value = os.getenv(name)
        if value is not None:
            return value
    return default


def env_var_alias_nonempty_value(names: tuple[str, ...], default: str = "") -> str:
    """Return the first non-empty, stripped value in an env alias set."""
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def env_var_alias_float(names: tuple[str, ...], default: float) -> float:
    """Return the first present alias value as a float, or *default*."""
    value = env_var_alias_value(names)
    return default if value is None else float(value)


def env_var_alias_int(names: tuple[str, ...], default: int) -> int:
    """Return the first present alias value as an int, or *default*."""
    value = env_var_alias_value(names)
    return default if value is None else int(value)


def env_int(key: str, default: int = 0) -> int:
    """Read an environment variable as an integer, with fallback."""
    raw = os.getenv(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def env_bool(key: str, default: bool = False) -> bool:
    """Read an environment variable as a boolean."""
    return is_truthy_value(os.getenv(key, ""), default=default)
