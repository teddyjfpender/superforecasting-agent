"""Configuration values shared by hosts, services and product adapters.

This package owns defaults, mapping normalization and environment expansion.
It does not read profiles, persist settings or initialize runtime services.
"""

from __future__ import annotations

import copy
import os
import re
from typing import Any, Dict, Optional

from superforecasting_agent.configuration.defaults import (
    DEFAULT_CONFIG as DEFAULT_CONFIG,
)


def model_section(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("configuration must be a mapping")
    raw = config.get("model")
    if isinstance(raw, str):
        section = {"default": raw.strip()}
    elif isinstance(raw, dict):
        section = dict(raw)
        if not section.get("default") and section.get("model"):
            section["default"] = section["model"]
    elif raw is None:
        section = {}
    else:
        raise ValueError("model configuration must be a string or mapping")
    for key in ("provider", "base_url", "context_length"):
        if not section.get(key) and config.get(key):
            section[key] = config[key]
    for key in ("default", "provider", "base_url", "api_mode"):
        value = section.get(key)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError(f"model.{key} must be a string")
            section[key] = value.strip()
    return section


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*, preserving nested defaults.

    Keys in *override* take precedence. If both values are dicts the merge
    recurses, so a user who overrides only ``tts.elevenlabs.voice_id`` will
    keep the default ``tts.elevenlabs.model_id`` intact.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand ``${VAR}`` references in config values.

    Only string values are processed; dict keys, numbers, booleans, and
    None are left untouched.  Unresolved references (variable not in
    ``os.environ``) are kept verbatim so callers can detect them.
    """
    if isinstance(obj, str):
        return re.sub(
            r"\${([^}]+)}",
            lambda m: os.environ.get(m.group(1), m.group(0)),
            obj,
        )
    if isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def _normalize_root_model_keys(config: Dict[str, Any]) -> Dict[str, Any]:
    """Move stale root-level provider/base_url/context_length into model section.

    Some users (or older code) placed ``provider:``, ``base_url:``, or
    ``context_length:`` at the config root instead of inside ``model:``.
    These root-level keys are only used as a fallback when the corresponding
    ``model.*`` key is empty — they never override an existing value.
    After migration the root-level keys are removed so they can't cause
    confusion on subsequent loads.
    """
    # Only act if there are root-level keys to migrate
    has_root = any(config.get(k) for k in ("provider", "base_url", "context_length"))
    if not has_root:
        return config

    config = dict(config)
    model = config.get("model")
    if not isinstance(model, dict):
        model = {"default": model} if model else {}
        config["model"] = model

    for key in ("provider", "base_url", "context_length"):
        root_val = config.get(key)
        if root_val and not model.get(key):
            model[key] = root_val
        config.pop(key, None)

    return config


def _normalize_max_turns_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy root-level max_turns into agent.max_turns."""
    config = dict(config)
    agent_config = dict(config.get("agent") or {})

    if "max_turns" in config and "max_turns" not in agent_config:
        agent_config["max_turns"] = config["max_turns"]

    if "max_turns" not in agent_config:
        agent_config["max_turns"] = DEFAULT_CONFIG["agent"]["max_turns"]

    config["agent"] = agent_config
    config.pop("max_turns", None)
    return config


def cfg_get(cfg: Optional[Dict[str, Any]], *keys: str, default: Any = None) -> Any:
    """Traverse nested dict keys safely, returning ``default`` on any miss.

    Canonical helper for the ``cfg.get("X", {}).get("Y", default)`` pattern
    that appears 50+ times across the codebase. Handles three common gotchas
    in one place:

      1. Missing intermediate keys (returns ``default``, no KeyError).
      2. An intermediate value that's not a dict (e.g. a user wrote a string
         where a section was expected). Returns ``default`` instead of
         AttributeError on ``.get()``.
      3. ``cfg is None`` (callers sometimes pass ``load_config() or None``).

    Named ``cfg_get`` rather than ``cfg_path`` to avoid shadowing the
    ubiquitous ``cfg_path = _hermes_home / "config.yaml"`` local variable
    that appears in gateway/run.py, cron/scheduler.py, main.py, etc.

    Explicit ``None`` values are returned as-is (matches ``dict.get(key,
    default)`` semantics — ``default`` is only returned when the key is
    *absent*, not when it's present but set to ``None``).

    Examples:
        >>> cfg_get({"agent": {"reasoning_effort": "high"}}, "agent", "reasoning_effort")
        'high'
        >>> cfg_get({}, "agent", "reasoning_effort", default="medium")
        'medium'
        >>> cfg_get({"agent": "oops_a_string"}, "agent", "reasoning_effort", default="low")
        'low'
        >>> cfg_get(None, "anything", default=42)
        42
        >>> cfg_get({"a": {"b": None}}, "a", "b", default="def")  # explicit None preserved
        >>> cfg_get({"a": {"b": False}}, "a", "b", default=True)  # falsy values preserved
        False
    """
    if not isinstance(cfg, dict):
        return default
    node: Any = cfg
    for key in keys:
        if not isinstance(node, dict):
            return default
        if key not in node:
            return default
        node = node[key]
    return node


def _merge_user_config(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a raw snapshot without mutating it or reading another profile."""
    if not isinstance(user_config, dict):
        raise ValueError("Configuration root must be a mapping")
    user_config = copy.deepcopy(user_config)
    if "max_turns" in user_config:
        agent_user_config = dict(user_config.get("agent") or {})
        if agent_user_config.get("max_turns") is None:
            agent_user_config["max_turns"] = user_config["max_turns"]
        user_config["agent"] = agent_user_config
        user_config.pop("max_turns", None)

    # Promote explicit model.model before defaults can shadow it.
    if not isinstance(user_config.get("model"), (str, type(None))):
        user_config["model"] = model_section(user_config)
    return _deep_merge(copy.deepcopy(DEFAULT_CONFIG), user_config)


def resolve_config(user_config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve a captured raw profile using the same rules as file loading.

    The result is for runtime use, not persistence: it contains defaults and
    expanded environment references, without the raw snapshot's save revision.
    """
    config = _merge_user_config(user_config)
    return _expand_env_vars(
        _normalize_root_model_keys(_normalize_max_turns_config(config))
    )
