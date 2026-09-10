"""Nous Portal environment alias helpers for Superforecasting Agent."""

from __future__ import annotations

import os


NOUS_PORTAL_BASE_URL_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_NOUS_PORTAL_BASE_URL",
    "FORECAST_NOUS_PORTAL_BASE_URL",
    "SUPERFORECASTING_AGENT_PORTAL_BASE_URL",
    "FORECAST_PORTAL_BASE_URL",
    "HERMES_PORTAL_BASE_URL",
    "NOUS_PORTAL_BASE_URL",
    "NOUS_BASE_URL",
)
NOUS_INFERENCE_BASE_URL_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_NOUS_INFERENCE_BASE_URL",
    "FORECAST_NOUS_INFERENCE_BASE_URL",
    "NOUS_INFERENCE_BASE_URL",
)
NOUS_MIN_KEY_TTL_SECONDS_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_NOUS_MIN_KEY_TTL_SECONDS",
    "FORECAST_NOUS_MIN_KEY_TTL_SECONDS",
    "HERMES_NOUS_MIN_KEY_TTL_SECONDS",
)
NOUS_TIMEOUT_SECONDS_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_NOUS_TIMEOUT_SECONDS",
    "FORECAST_NOUS_TIMEOUT_SECONDS",
    "HERMES_NOUS_TIMEOUT_SECONDS",
)


def _first_env_value(names: tuple[str, ...], default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def nous_portal_base_url(default: str = "") -> str:
    return _first_env_value(NOUS_PORTAL_BASE_URL_ENV_NAMES, default).rstrip("/")


def nous_inference_base_url(default: str = "") -> str:
    return _first_env_value(NOUS_INFERENCE_BASE_URL_ENV_NAMES, default).rstrip("/")


def nous_min_key_ttl_seconds(default: int = 1800) -> int:
    raw = _first_env_value(NOUS_MIN_KEY_TTL_SECONDS_ENV_NAMES, str(default))
    return max(60, int(raw))


def nous_timeout_seconds(default: float = 15.0) -> float:
    raw = _first_env_value(NOUS_TIMEOUT_SECONDS_ENV_NAMES, str(default))
    return float(raw)
