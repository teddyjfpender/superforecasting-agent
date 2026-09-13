"""Read-only layered forecast settings, independent of diagnostics and execution.

Precedence: registry defaults, profile env section, environment, explicit override.
The compatibility AppConfig facade and infrastructure readers share this singleton.
ProfileConfiguration owns raw file snapshots; this module owns typed resolution.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Mapping

from forecasting.configuration.registry import (
    _ALIASES_OF as _ALIASES_OF,
)
from forecasting.configuration.registry import (
    _KEYS as _KEYS,
)
from forecasting.configuration.registry import (
    DEPRECATIONS as DEPRECATIONS,
)
from forecasting.configuration.registry import (
    REGISTRY as REGISTRY,
)
from forecasting.configuration.registry import (
    ConfigKey as ConfigKey,
)

logger = logging.getLogger("forecasting.appconfig")

# Sentinel distinguishing "caller passed no default" (use the registry default)
# from "caller explicitly passed None/''" (use exactly that).
_UNSET: Any = object()

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off", ""}


class AppConfigError(ValueError):
    """A typed accessor failed to coerce a value. The message NAMES the key."""


# Deprecation warnings are emitted at most once per old name per process.
_DEPRECATION_WARNED: set[str] = set()


def reset_deprecation_warnings() -> None:
    """Clear the once-only deprecation-warning memo (tests)."""
    _DEPRECATION_WARNED.clear()


def redact(value: str | None) -> str:
    """Render a secret's *presence* without leaking its value."""
    if not value:
        return "(not set)"
    text = str(value)
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}…{text[-4:]} ({len(text)} chars)"


class AppConfig:
    """Layered, typed config loader.

    ``environ`` and ``config_file`` are injectable for tests; when ``None`` the
    loader reads the *live* ``os.environ`` (so a key added mid-process via
    ``forecast api-key set`` is picked up without a restart) and the agent-home
    ``config.yaml`` ``env:`` section.
    """

    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        config_file: Mapping[str, Any] | None = None,
        registry: Mapping[str, ConfigKey] | None = None,
    ) -> None:
        self._environ_override = environ
        self._config_override = config_file
        self._config_reader = None
        self._overrides: dict[str, str] = {}
        self.registry = dict(REGISTRY if registry is None else registry)

    # ── layers ───────────────────────────────────────────────────────────────

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ_override is None else self._environ_override

    def _config_env(self) -> dict[str, Any]:
        if self._config_override is not None:
            return dict(self._config_override)
        data: dict[str, Any] = {}
        try:  # lazy — avoid an import cycle and the yaml read cost at import time
            from superforecasting_agent.constants import get_agent_home
            from superforecasting_agent.profile_paths import (
                ignore_user_config_requested,
            )
            from superforecasting_agent.storage.configuration import (
                ProfileConfiguration,
            )

            if ignore_user_config_requested():
                return {}
            if self._config_reader is None:
                self._config_reader = ProfileConfiguration()
            raw = self._config_reader.load(get_agent_home() / "config.yaml")
            section = raw.get("env") if isinstance(raw, dict) else None
            if isinstance(section, dict):
                data = {str(k): v for k, v in section.items()}
        except Exception:  # pragma: no cover — config file is best-effort
            data = {}
        return data

    def reload(self) -> None:
        """Drop the cached config-file layer so the next read re-reads it."""
        self._config_reader = None

    # ── overrides ────────────────────────────────────────────────────────────

    def set_override(self, name: str, value: str) -> None:
        self._overrides[name] = value

    def clear_override(self, name: str) -> None:
        self._overrides.pop(name, None)

    def clear_overrides(self) -> None:
        self._overrides.clear()

    # ── resolution ───────────────────────────────────────────────────────────

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    def _warn_deprecated(self, old: str, canonical: str) -> None:
        if old in _DEPRECATION_WARNED:
            return
        _DEPRECATION_WARNED.add(old)
        logger.warning(
            "config: %s is deprecated; use %s instead (value honoured for now).",
            old,
            canonical,
        )

    def _resolve(self, name: str) -> tuple[str | None, str]:
        """Return ``(raw_value_or_None, source)`` across all layers.

        Applies the deprecation shim: a read of a deprecated name is redirected
        to its canonical key (warn once), and a canonical key that is unset
        falls back to any set deprecated alias (warn once).
        """
        canonical = DEPRECATIONS.get(name)
        if canonical is not None:
            self._warn_deprecated(name, canonical)
            name = canonical

        if name in self._overrides:
            return self._overrides[name], "override"
        env = self.environ
        if name in env:
            return env[name], "env"
        cfg = self._config_env()
        if name in cfg:
            return self._stringify(cfg[name]), "config"

        for old in _ALIASES_OF.get(name, ()):  # canonical unset → try old names
            if old in self._overrides:
                self._warn_deprecated(old, name)
                return self._overrides[old], "override(deprecated)"
            if old in env:
                self._warn_deprecated(old, name)
                return env[old], "env(deprecated)"
            if old in cfg:
                self._warn_deprecated(old, name)
                return self._stringify(cfg[old]), "config(deprecated)"

        return None, "unset"

    def source_of(self, name: str) -> str:
        """Which layer supplies ``name`` (``override``/``env``/``config``/``unset``)."""
        return self._resolve(name)[1]

    def _effective_default(self, name: str, default: Any) -> Any:
        if default is not _UNSET:
            return default
        key = self.registry.get(DEPRECATIONS.get(name, name))
        return key.default if key is not None else None

    # ── typed accessors ──────────────────────────────────────────────────────

    def get_str(self, name: str, default: Any = _UNSET) -> str | None:
        raw, _ = self._resolve(name)
        if raw is None:
            return self._effective_default(name, default)
        return raw

    def get_int(self, name: str, default: Any = _UNSET) -> int | None:
        raw, _ = self._resolve(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return self._effective_default(name, default)
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            raise AppConfigError(f"{name}: expected an integer, got {raw!r}") from None

    def get_float(self, name: str, default: Any = _UNSET) -> float | None:
        raw, _ = self._resolve(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            return self._effective_default(name, default)
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            raise AppConfigError(f"{name}: expected a number, got {raw!r}") from None

    def get_bool(
        self, name: str, default: Any = _UNSET, *, strict: bool = False
    ) -> bool:
        """Coerce a flag.

        Lenient (default): recognised truthy tokens → ``True``, everything else
        → the effective default (matching the historical
        ``os.environ.get(...).strip().lower() in {...}`` idiom). ``strict=True``
        raises :class:`AppConfigError` (naming the key) on an unrecognised value.
        """
        raw, _ = self._resolve(name)
        base = self._effective_default(name, default)
        base = bool(base) if base is not _UNSET and base is not None else False
        if raw is None:
            return base
        token = str(raw).strip().lower()
        if token in _TRUTHY:
            return True
        if token in _FALSEY:
            return False
        if strict:
            raise AppConfigError(
                f"{name}: expected a boolean (one of {sorted(_TRUTHY | _FALSEY)}), got {raw!r}"
            )
        return base

    def get_path(self, name: str, default: Any = _UNSET) -> Path | None:
        raw, _ = self._resolve(name)
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            fallback = self._effective_default(name, default)
            if fallback is None or fallback is _UNSET:
                return None
            return Path(fallback).expanduser()
        return Path(str(raw)).expanduser()

    def secret(self, name: str, default: Any = _UNSET) -> str | None:
        """Return a secret's value for USE. Never logged — the doctor and
        :func:`redact` only ever report presence."""
        raw, _ = self._resolve(name)
        if raw is None:
            return self._effective_default(name, default)
        return raw

    def is_secret(self, name: str) -> bool:
        key = self.registry.get(DEPRECATIONS.get(name, name))
        if key is not None:
            return key.secret
        upper = name.upper()
        return any(
            tok in upper
            for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")
        )

    def __repr__(self) -> str:  # never dumps values
        return f"AppConfig(registry={len(self.registry)} keys, overrides={len(self._overrides)})"


# ── module-level singleton + delegating helpers (the call-site surface) ──────

_config = AppConfig()


def configure(
    *,
    environ: Mapping[str, str] | None = None,
    config_file: Mapping[str, Any] | None = None,
) -> AppConfig:
    """Swap the process singleton's layers (tests). Returns the new instance."""
    global _config
    _config = AppConfig(environ=environ, config_file=config_file)
    return _config


def get_config() -> AppConfig:
    return _config


def get_str(name: str, default: Any = _UNSET) -> str | None:
    return _config.get_str(name, default)


def get_int(name: str, default: Any = _UNSET) -> int | None:
    return _config.get_int(name, default)


def get_float(name: str, default: Any = _UNSET) -> float | None:
    return _config.get_float(name, default)


def get_bool(name: str, default: Any = _UNSET, *, strict: bool = False) -> bool:
    return _config.get_bool(name, default, strict=strict)


def get_path(name: str, default: Any = _UNSET) -> Path | None:
    return _config.get_path(name, default)


def secret(name: str, default: Any = _UNSET) -> str | None:
    return _config.secret(name, default)


def set_override(name: str, value: str) -> None:
    _config.set_override(name, value)
