"""Runtime model/provider environment aliases for the forecast fork."""

from __future__ import annotations

from collections.abc import MutableMapping

from utils import (
    INFERENCE_MODEL_ENV_NAMES,
    INFERENCE_PROVIDER_ENV_NAMES,
    MODEL_ENV_NAMES,
    env_var_alias_nonempty_value,
)


def first_env(names: tuple[str, ...], default: str = "") -> str:
    return env_var_alias_nonempty_value(names, default)


def model_env(default: str = "") -> str:
    return first_env(MODEL_ENV_NAMES + INFERENCE_MODEL_ENV_NAMES, default)


def inference_model_env(default: str = "") -> str:
    return first_env(INFERENCE_MODEL_ENV_NAMES, default)


def inference_provider_env(default: str = "") -> str:
    return first_env(INFERENCE_PROVIDER_ENV_NAMES, default)


def set_env_aliases(
    env: MutableMapping[str, str],
    names: tuple[str, ...],
    value: object,
) -> None:
    text = str(value)
    for name in names:
        env[name] = text
