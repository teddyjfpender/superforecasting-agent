"""Typed, layered configuration for the forecast desk (architecture review item #8).

The desk reads ~218 environment variables at call sites scattered across the
codebase (see ``docs/reference/config-and-env.md`` — the generated inventory).
Each read hand-rolls its own ``os.environ.get('X', default)`` + coercion, so a
typo in a var name silently falls through to the default, a bad ``int`` value
crashes with an opaque ``ValueError`` that never names the key, and there is no
single place to ask "what is set, where did it come from, is it a secret".

This module is that single place: one typed loader with an explicit precedence
order and a declarative registry of the highest-traffic keys.

Precedence (lowest → highest):

    registry default  <  config file  <  environment  <  explicit override

* **registry default** — the declared fallback for a known key (``REGISTRY``).
* **config file** — the ``env:`` section of the agent-home ``config.yaml``
  (``superforecasting_agent.storage.configuration.ProfileConfiguration``). We *extend* the file the system
  already reads; we do not invent a second one. A flat ``ENV_NAME: value`` map
  under ``env:`` lets an operator pin a value in the config instead of the
  shell.
* **environment** — ``os.environ``, which already includes everything the
  user ``.env`` loaded at boot (``load_forecast_dotenv``). This is the layer
  the historical call sites read, so migrating a call site to ``appconfig``
  is behaviour-identical when the config-file layer is empty.
* **override** — an explicit per-process value set via :meth:`set_override`
  (tests, ``config doctor``, an operator knob).

The loader never logs a secret's *value*: :meth:`secret` returns it for use,
but :func:`redact` / the doctor only ever report presence.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

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


# ── `forecast config doctor` report (pure — the CLI verb just prints it) ─────

DEFAULT_DOC_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "reference" / "config-and-env.md"
)

_PRODUCT_PREFIXES = ("FORECAST_", "HERMES_", "SUPERFORECASTING_AGENT_", "KALSHI_")


def load_inventory(doc_path: Path | None = None) -> set[str]:
    """Parse the generated inventory doc for the set of KNOWN var names.

    Used for typo detection: a set-but-unregistered var that also isn't in the
    inventory (and looks like ours) is probably a typo. Degrades to an empty
    set when the doc is missing — the registry alone still catches obvious ones.
    """
    import re

    path = doc_path or DEFAULT_DOC_PATH
    names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return names
    for match in re.finditer(
        r"^\|\s*`([A-Za-z_][A-Za-z0-9_()]*)`\s*\|", text, re.MULTILINE
    ):
        names.add(match.group(1))
    return names


def _known_names(cfg: AppConfig, inventory: Iterable[str]) -> set[str]:
    known: set[str] = set(cfg.registry) | set(DEPRECATIONS)
    known |= set(inventory)
    try:  # marketdata + api-key surfaces are legitimate known names
        from forecasting.marketdata.keys import PROVIDER_ENV

        known |= set(PROVIDER_ENV.values())
    except Exception:  # pragma: no cover
        pass
    try:
        from forecasting.api_keys import API_KEY_PROVIDERS

        known |= {p.env_var for p in API_KEY_PROVIDERS}
    except Exception:  # pragma: no cover
        pass
    return known


def _kalshi_report(cfg: AppConfig) -> dict[str, Any]:
    """The two-env-var trap + marketdata alias mismatch the review named."""
    key_id = bool((cfg.secret("KALSHI_ACCESS_KEY_ID") or "").strip())
    pem = bool((cfg.get_str("KALSHI_PRIVATE_KEY_PATH") or "").strip())
    mismatches: list[dict[str, str]] = []
    try:
        from forecasting.api_keys import API_KEY_PROVIDERS
        from forecasting.marketdata.keys import PROVIDER_ENV

        for slug, env_var in PROVIDER_ENV.items():
            settable = any(p.matches(slug) for p in API_KEY_PROVIDERS)
            if not settable:
                mismatches.append({
                    "slug": slug,
                    "env_var": env_var,
                    "note": (
                        f"marketdata resolves '{slug}'→{env_var}, but no `forecast api-key set "
                        f"{slug}` provider exists — set it with the UPPERCASE env name "
                        f"(`forecast api-key set {env_var} <value>`)."
                    ),
                })
    except Exception:  # pragma: no cover
        pass
    return {
        "key_id_set": key_id,
        "pem_path_set": pem,
        "half_configured": key_id != pem,
        "alias_mismatches": mismatches,
    }


def build_doctor_report(
    cfg: AppConfig | None = None,
    *,
    inventory: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the structured ``config doctor`` report (pure + testable)."""
    import difflib

    cfg = cfg or _config
    inv = set(inventory) if inventory is not None else load_inventory()
    known = _known_names(cfg, inv)
    env = dict(cfg.environ)

    # 1. known-but-unset with defaults in effect / known set values.
    known_unset: list[dict[str, Any]] = []
    known_set: list[dict[str, Any]] = []
    for name, key in sorted(cfg.registry.items()):
        raw, source = cfg._resolve(name)
        row = {
            "name": name,
            "source": source,
            "secret": key.secret,
            "category": key.category,
        }
        if raw is None:
            row["default"] = key.default
            known_unset.append(row)
        else:
            row["value"] = redact(raw) if key.secret else raw
            known_set.append(row)

    # 2. set-but-unknown vars (typo detection). The suggestion pool is restricted
    # to PRODUCT-relevant names so a legit OS var (FPATH, LSCOLORS) isn't nagged
    # for merely resembling a generic one (PATH); a genuine typo of one of OUR
    # vars (FORECST_LEDGER_DB → FORECAST_LEDGER_DB) still close-matches.
    def _product_relevant(n: str) -> bool:
        return n.startswith(_PRODUCT_PREFIXES) or n.endswith((
            "_API_KEY",
            "_TOKEN",
            "_SECRET",
        ))

    suggest_pool = sorted(
        n for n in (set(cfg.registry) | set(DEPRECATIONS) | inv) if _product_relevant(n)
    )
    unknown_set: list[dict[str, Any]] = []
    for name in sorted(env):
        if name in known:
            continue
        looks_ours = name.startswith(_PRODUCT_PREFIXES)
        close = difflib.get_close_matches(name, suggest_pool, n=1, cutoff=0.82)
        if not looks_ours and not close:
            continue  # genuine long-tail / OS var — passthrough, don't nag
        unknown_set.append({"name": name, "suggestion": close[0] if close else None})

    # 3. secrets present/absent (presence only — never the value).
    secrets: list[dict[str, Any]] = []
    for name, key in sorted(cfg.registry.items()):
        if not key.secret:
            continue
        raw, source = cfg._resolve(name)
        secrets.append({
            "name": name,
            "present": bool(raw and str(raw).strip()),
            "source": source if raw else "unset",
        })

    # 4. file-vs-env precedence conflicts (same key in both → env wins).
    cfg_layer = cfg._config_env()
    conflicts: list[dict[str, Any]] = []
    for name in sorted(cfg_layer):
        if name in env:
            conflicts.append({
                "name": name,
                "winner": "env",
                "shadowed": "config.yaml env:",
            })

    return {
        "layers": {
            "config_file_keys": sorted(cfg_layer),
            "env_var_count": len(env),
        },
        "known_set": known_set,
        "known_unset": known_unset,
        "unknown_set": unknown_set,
        "secrets": secrets,
        "precedence_conflicts": conflicts,
        "kalshi": _kalshi_report(cfg),
        "connections": _connections_report(),
        "budgets": _budgets_report(),
    }


def _budgets_report() -> dict[str, Any]:
    """The box-level spend-ceiling section (usage vs ceilings + headroom).

    Lazy import so this module carries no load-time edge to the budget/ledger
    stack, and a config-only environment still reports cleanly.
    """
    try:
        from forecasting import budget

        return budget.status_report()
    except Exception as exc:  # pragma: no cover — degrade, never break doctor
        return {"enabled": False, "error": f"{exc.__class__.__name__}: {exc}"}


def _connections_report() -> dict[str, Any]:
    """The notification-surface section — bound chats + last delivery status.

    Lazy import so this module has no load-time edge to the notify/transport
    stack (and so a config-only environment without the messaging deps still
    reports cleanly).
    """
    try:
        from forecasting import notify

        return notify.connections_report()
    except Exception as exc:  # pragma: no cover — degrade, never break doctor
        return {
            "surfaces": {},
            "routes": [],
            "error": f"{exc.__class__.__name__}: {exc}",
        }


def render_doctor_report(report: dict[str, Any]) -> str:
    """Human-readable rendering of :func:`build_doctor_report` (no secret values)."""
    out: list[str] = []
    a = out.append

    a("forecast config doctor")
    a("=" * 60)
    layers = report["layers"]
    a(f"process env vars: {layers['env_var_count']}")
    cfg_keys = layers["config_file_keys"]
    a(
        f"config.yaml env: section: {len(cfg_keys)} key(s)"
        + (f" — {', '.join(cfg_keys)}" if cfg_keys else "")
    )

    a("")
    a(f"KNOWN keys set ({len(report['known_set'])}):")
    for row in report["known_set"]:
        val = row.get("value")
        a(f"  {row['name']:<38} [{row['source']}] = {val}")
    a("")
    a(f"KNOWN keys unset — registry default in effect ({len(report['known_unset'])}):")
    for row in report["known_unset"]:
        a(f"  {row['name']:<38} default={row['default']!r}")

    unknown = report["unknown_set"]
    a("")
    a(f"SET-BUT-UNKNOWN vars ({len(unknown)}):")
    if not unknown:
        a("  (none — all set product vars are known)")
    for row in unknown:
        hint = f"  — did you mean {row['suggestion']}?" if row["suggestion"] else ""
        a(f"  ⚠ {row['name']}{hint}")

    a("")
    a("SECRETS (presence only — values never printed):")
    present = [s for s in report["secrets"] if s["present"]]
    absent = [s for s in report["secrets"] if not s["present"]]
    a(
        f"  present ({len(present)}): {', '.join(s['name'] for s in present) or '(none)'}"
    )
    a(f"  absent  ({len(absent)}): {', '.join(s['name'] for s in absent) or '(none)'}")

    conflicts = report["precedence_conflicts"]
    a("")
    a(f"FILE-vs-ENV precedence conflicts ({len(conflicts)}):")
    if not conflicts:
        a("  (none)")
    for row in conflicts:
        a(
            f"  ⚠ {row['name']}: set in both env and {row['shadowed']} — {row['winner']} WINS"
        )

    k = report["kalshi"]
    a("")
    a("KALSHI credential pair (two-var trap):")
    a(f"  KALSHI_ACCESS_KEY_ID:   {'set' if k['key_id_set'] else 'unset'}")
    a(f"  KALSHI_PRIVATE_KEY_PATH: {'set' if k['pem_path_set'] else 'unset'}")
    if k["half_configured"]:
        a(
            "  ⚠ HALF-CONFIGURED: exactly one of the pair is set — Kalshi streaming will "
            "silently fall back to REST polling. Set both with `forecast api-key set kalshi "
            "<key-id> --pem-file key.pem`."
        )
    else:
        a("  ok (both set, or both unset → keyless REST default).")
    if k["alias_mismatches"]:
        a("  marketdata alias mismatches:")
        for m in k["alias_mismatches"]:
            a(f"    ⚠ {m['note']}")

    conn = report.get("connections") or {}
    a("")
    a("NOTIFICATION connections (surfaces + bound chats):")
    surfaces = conn.get("surfaces") or {}
    if not surfaces:
        a(
            "  (notify stack unavailable"
            + (f": {conn['error']}" if conn.get("error") else "")
            + ")"
        )
    for name in sorted(surfaces):
        info = surfaces[name]
        tok = "token set" if info.get("token_present") else "no token"
        bound = info.get("bound_count", 0)
        health = "" if info.get("healthy", True) else "  ⚠ a binding is failing"
        a(f"  {name:<10} {tok}  ·  {bound} binding(s){health}")
    for row in conn.get("routes") or []:
        status = row.get("last_status") or "never delivered"
        fails = row.get("consecutive_failures") or 0
        warn = f"  ⚠ {fails} consecutive failures" if fails else ""
        a(
            f"    - {row['id']}  events=[{', '.join(row.get('events') or [])}]  last={status}{warn}"
        )

    bud = report.get("budgets") or {}
    a("")
    a("BOX SPEND ceilings (unattended-box guard):")
    if not bud.get("enabled"):
        note = bud.get("error")
        a("  (no ceiling set — unlimited" + (f"; {note}" if note else "") + ")")
    else:
        usage = bud.get("usage") or {}
        budget = bud.get("budget") or {}
        head = bud.get("headroom") or {}

        def _line(label: str, used, limit, headroom) -> str:
            if not limit:
                return f"  {label:<16} {used} used  ·  no ceiling"
            flag = "  ⚠ BREACHED" if headroom is not None and headroom <= 0 else ""
            return f"  {label:<16} {used} / {limit}  ·  headroom {headroom}{flag}"

        a(
            _line(
                "daily tokens",
                usage.get("day_tokens"),
                budget.get("daily_tokens"),
                head.get("daily_tokens"),
            )
        )
        a(
            _line(
                "daily USD",
                usage.get("day_usd"),
                budget.get("daily_usd"),
                head.get("daily_usd"),
            )
        )
        a(
            _line(
                "monthly tokens",
                usage.get("month_tokens"),
                budget.get("monthly_tokens"),
                head.get("monthly_tokens"),
            )
        )
        a(
            _line(
                "monthly USD",
                usage.get("month_usd"),
                budget.get("monthly_usd"),
                head.get("monthly_usd"),
            )
        )
        if bud.get("breached"):
            b = bud["breached"]
            a(
                f"  ⚠ paid jobs REFUSED: {b['scope']} {b['metric']} ceiling reached ({b['config_key']})"
            )

    return "\n".join(out)


__all__ = [
    "AppConfig",
    "AppConfigError",
    "ConfigKey",
    "REGISTRY",
    "DEPRECATIONS",
    "redact",
    "configure",
    "get_config",
    "get_str",
    "get_int",
    "get_float",
    "get_bool",
    "get_path",
    "secret",
    "set_override",
    "reset_deprecation_warnings",
    "load_inventory",
    "build_doctor_report",
    "render_doctor_report",
]
