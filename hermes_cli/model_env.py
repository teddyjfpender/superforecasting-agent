"""Runtime model/provider environment aliases for the forecast fork."""

from __future__ import annotations

import os
from collections.abc import MutableMapping

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


def first_env(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


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
