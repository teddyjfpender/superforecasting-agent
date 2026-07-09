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
  (``hermes_cli.config.read_raw_config()``). We *extend* the file the system
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger("forecasting.appconfig")

# Sentinel distinguishing "caller passed no default" (use the registry default)
# from "caller explicitly passed None/''" (use exactly that).
_UNSET: Any = object()

_TRUTHY = {"1", "true", "yes", "on"}
_FALSEY = {"0", "false", "no", "off", ""}


class AppConfigError(ValueError):
    """A typed accessor failed to coerce a value. The message NAMES the key."""


@dataclass(frozen=True)
class ConfigKey:
    """A known configuration key the loader can describe and coerce."""

    name: str
    type: str = "str"  # str | int | float | bool | path
    default: Any = None
    secret: bool = False
    description: str = ""
    # Deprecated env names that resolve to this canonical key (old → this).
    aliases: tuple[str, ...] = ()
    category: str = "config"


# ── The registry ─────────────────────────────────────────────────────────────
#
# Seeded from the ~40 highest-traffic vars in the inventory, FORECAST_* /
# HERMES_* / SUPERFORECASTING_AGENT_* families first, then the data/LLM provider
# secrets the desk actually reads. This is deliberately NOT all 218 vars — the
# long tail passes through untyped (see the unknown-var passthrough). Defaults
# mirror the call-site defaults documented in config-and-env.md.
_KEYS: tuple[ConfigKey, ...] = (
    # ── FORECAST_* runtime + ledger ──────────────────────────────────────────
    ConfigKey("FORECAST_LEDGER_DB", "path", None, False,
              "Override path to the forecast ledger SQLite database.", category="ledger"),
    ConfigKey("FORECAST_TRIAGE_MODEL", "str", None, False,
              "Model id for the cheap information-triage auto-labeler.", category="triage"),
    ConfigKey("FORECAST_TRIAGE_TRUST_MIN_SAMPLE", "int", 20, False,
              "Min labelled sample before the triage classifier is trusted.", category="triage"),
    ConfigKey("FORECAST_TRIAGE_TRUST_THRESHOLD", "float", 0.8, False,
              "Agreement threshold above which the triage classifier is trusted.", category="triage"),
    ConfigKey("FORECAST_GATE_DIRECT_WRITES", "str", "on", False,
              "Direct-write gate mode: on | warn | off.", category="ledger"),
    ConfigKey("FORECAST_DISABLE_HOOK_BLOCKING", "bool", False, False,
              "Kill-switch: disable saturation/style hook blocking on live commits.", category="ledger"),
    ConfigKey("FORECAST_HOOK_READINESS_FLOOR", "float", 80.0, False,
              "Machine-readiness (0-100) below which the readiness_floor hook fires on live commits.",
              category="ledger"),
    ConfigKey("FORECAST_DISABLE_SATURATION_ESCALATION", "bool", False, False,
              "Kill-switch: disable the saturation-escalation alert on autofix commits.", category="ledger"),
    ConfigKey("FORECAST_DISABLE_THESIS_CASCADE", "bool", False, False,
              "Kill-switch: disable thesis-cascade freshening on member commits.", category="ledger"),
    ConfigKey("FORECAST_NO_LESSON_SYNTHESIS", "bool", False, False,
              "Skip calibration-lesson synthesis in the cron runner.", category="cron"),
    ConfigKey("FORECAST_HIERARCHICAL_CALIBRATION", "bool", False, False,
              "Activate hierarchical Platt (per-cohort intercept offsets delta_s) at "
              "the terminal calibration. DEFAULT-OFF (same activation-gate pattern as "
              "the sqrt(3) slope): the derivation returns the global map until this is "
              "flipped on, backed by the `calibration --hierarchical` validation report.",
              category="ledger"),
    ConfigKey("FORECAST_BRIDGE_PORT", "int", 8787, False,
              "Port for the read-only forecast web bridge.", category="web"),
    # ── Agent tool-call budget (checkpoint-continuation soft cap) ─────────────
    ConfigKey("FORECAST_AGENT_MAX_TOOL_ITERATIONS", "int", 200, False,
              "Per-turn tool-call SOFT cap for the top-level agent loop. Hitting it "
              "is a CHECKPOINT (surface progress + reset the budget + continue), not a "
              "stop: interactive runs continue automatically; unattended runs continue "
              "when the spend policy grants llm_spend auto. Default 200 (raised from 90 "
              "for deep-research turns). Legacy aliases: SUPERFORECASTING_AGENT_MAX_"
              "ITERATIONS / FORECAST_MAX_ITERATIONS / HERMES_MAX_ITERATIONS.",
              category="runtime"),
    ConfigKey("FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER", "int", 10, False,
              "Absolute tool-call ceiling as a multiple of the soft cap (default 10× ⇒ "
              "2000). Even an interactive run stops here, with a message naming the key. "
              "The spend caps remain the primary governor of unattended cost.",
              category="runtime"),
    # ── Quorum panel (operator-pinned model line-up) ─────────────────────────
    # Comma list of ``provider:model`` seats that OVERRIDE the connected-provider
    # panel rebuild (e.g. "openai-codex:gpt-5.5, gemini:gemini-2.5-flash"). Each
    # entry is validated against callable providers — a non-callable entry errors
    # naming itself. Unset ⇒ the preset/connected resolution is used unchanged.
    ConfigKey("QUORUM_PANEL_MODELS", "str", None, False,
              "Comma list of provider:model quorum panel seats; overrides the "
              "connected-provider rebuild. Validated against callable providers.",
              category="quorum"),
    ConfigKey("QUORUM_JUDGE_MODEL", "str", None, False,
              "Optional provider:model for the quorum judge synthesis (overrides "
              "the preset/connected judge). Validated against callable providers.",
              category="quorum"),
    ConfigKey("FORECAST_BIN", "str", None, False,
              "Explicit path to the forecast CLI binary (kanban launcher).", category="runtime"),
    # ── Canonical home / timezone / redaction (deprecated aliases) ───────────
    ConfigKey("SUPERFORECASTING_AGENT_HOME", "path", None, False,
              "Agent home directory (config.yaml + .env + ledger live here).",
              aliases=("FORECAST_HOME", "HERMES_HOME"), category="runtime"),
    ConfigKey("SUPERFORECASTING_AGENT_TIMEZONE", "str", None, False,
              "Display/scheduling timezone for the desk.",
              aliases=("FORECAST_TIMEZONE", "HERMES_TIMEZONE"), category="runtime"),
    ConfigKey("SUPERFORECASTING_AGENT_REDACT_SECRETS", "bool", False, False,
              "Redact secret values in runtime logs/plugin migration.",
              aliases=("FORECAST_REDACT_SECRETS", "HERMES_REDACT_SECRETS"), category="runtime"),
    # ── Multiplayer identity (M1 of the Slack harness plan) ──────────────────
    # The name + stable instance id that make this desk a distinct, @-taggable
    # collaborator in a shared Slack channel. See ``forecasting/identity.py``.
    ConfigKey("AGENT_NAME", "str", None, False,
              "Agent display name for multiplayer collab (default 'Bernard' when unset). "
              "Flows into the soul, the TUI banner, and the sfp/1 wire sender.",
              category="identity"),
    ConfigKey("AGENT_INSTANCE_ID", "str", None, False,
              "Stable uuid identifying this instance across restarts. Minted once and "
              "persisted to {home}/identity.json when unset; an operator may pin it here.",
              category="identity"),
    ConfigKey("AGENT_PERSONA", "str", None, False,
              "Optional persona notes for this named agent (free text, surfaced in whoami).",
              category="identity"),
    # ── Multiplayer collab authorisation + rate limit (M3 import pipeline) ────
    ConfigKey("COLLAB_ALLOWED_INSTANCES", "str", None, False,
              "Comma-separated list of authorised counterparty instance_ids. CLOSED BY "
              "DEFAULT — empty/unset accepts no peer imports. Authorises by stable id, "
              "never display name.", category="identity"),
    ConfigKey("COLLAB_RATE_LIMIT_PER_HOUR", "int", 240, False,
              "Max peer sfp/1 messages the collab router accepts per channel per hour "
              "(a malicious channel can't drain the desk via inbound messages).",
              category="identity"),
    # ── HERMES_* runtime ─────────────────────────────────────────────────────
    ConfigKey("HERMES_HOME_MODE", "str", None, False,
              "Permission mode for the agent-home directory (managed installs).", category="runtime"),
    ConfigKey("HERMES_PROFILE", "str", None, False,
              "Active profile name (selects the config.yaml home).", category="runtime"),
    ConfigKey("HERMES_DEV", "str", None, False,
              "Developer mode flag.", category="runtime"),
    ConfigKey("HERMES_CONTAINER", "str", None, False,
              "Container-runtime marker.", category="runtime"),
    ConfigKey("HERMES_TENANT", "str", None, False,
              "Tenant id for multi-tenant kanban runs.", category="runtime"),
    ConfigKey("HERMES_BASE_URL", "str", None, False,
              "Base URL for the Hermes gateway/API surface.", category="web"),
    ConfigKey("HERMES_API_KEY", "str", None, True,
              "Bearer token guarding the tui gateway API.", category="secret"),
    ConfigKey("HERMES_SESSION_KEY", "str", None, True,
              "Per-session key for the terminal tool.", category="secret"),
    # ── Data-provider secrets (forecasting.source_adapters / marketdata) ─────
    ConfigKey("FRED_API_KEY", "str", None, True,
              "FRED — Federal Reserve Economic Data API key.", category="secret"),
    ConfigKey("EIA_API_KEY", "str", None, True,
              "EIA — US Energy Information Administration API key.", category="secret"),
    ConfigKey("BLS_API_KEY", "str", None, True,
              "BLS — US Bureau of Labor Statistics API key.", category="secret"),
    ConfigKey("CENSUS_API_KEY", "str", None, True,
              "US Census Bureau API key.", category="secret"),
    ConfigKey("BEA_API_KEY", "str", None, True,
              "BEA — Bureau of Economic Analysis API key (marketdata provider 'bea').",
              category="secret"),
    ConfigKey("RELIEFWEB_APPNAME", "str", "superforecasting-agent", False,
              "ReliefWeb API appname (polite identification).", category="config"),
    # ── Kalshi credential PAIR (two-var trap — see the doctor) ────────────────
    ConfigKey("KALSHI_ACCESS_KEY_ID", "str", None, True,
              "Kalshi access key id (websocket streaming only; REST is keyless).",
              category="secret"),
    ConfigKey("KALSHI_PRIVATE_KEY_PATH", "path", None, False,
              "Path to the Kalshi RSA private-key PEM (pairs with KALSHI_ACCESS_KEY_ID).",
              category="config"),
    # ── Web-search provider secrets ──────────────────────────────────────────
    ConfigKey("FIRECRAWL_API_KEY", "str", None, True,
              "Firecrawl paid web search + extract backend.", category="secret"),
    ConfigKey("EXA_API_KEY", "str", None, True, "Exa web search + contents.", category="secret"),
    ConfigKey("TAVILY_API_KEY", "str", None, True, "Tavily research search.", category="secret"),
    ConfigKey("BRAVE_API_KEY", "str", None, True, "Brave Search API.", category="secret"),
    ConfigKey("PARALLEL_API_KEY", "str", None, True, "Parallel web search + extract.", category="secret"),
    # ── LLM provider secrets ─────────────────────────────────────────────────
    ConfigKey("OPENAI_API_KEY", "str", None, True, "OpenAI / Codex provider key.", category="secret"),
    ConfigKey("ANTHROPIC_API_KEY", "str", None, True, "Anthropic (Claude) provider key.", category="secret"),
    ConfigKey("OPENROUTER_API_KEY", "str", None, True, "OpenRouter multi-model gateway key.", category="secret"),
    ConfigKey("XAI_API_KEY", "str", None, True, "xAI (Grok) provider key.", category="secret"),
    # ── Approval / spend policy matrix (architecture review item #9) ─────────
    # One knob per (run_mode × action_class) cell of the job-runtime approval matrix
    # — the ENV/registry spelling of the logical ``policy.<mode>.<class>`` key. Value:
    # auto | ask | never. UNSET (the default) means "use the matrix default", which is
    # ``auto`` for every cell today (zero behaviour change until an operator tightens
    # one). See ``forecasting/jobs/policy.py``.
    ConfigKey("FORECAST_POLICY_INTERACTIVE_LEDGER_WRITES", "str", None, False,
              "policy.interactive.ledger_writes = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_INTERACTIVE_NETWORK", "str", None, False,
              "policy.interactive.network = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_INTERACTIVE_LLM_SPEND", "str", None, False,
              "policy.interactive.llm_spend = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_INTERACTIVE_SUBPROCESS", "str", None, False,
              "policy.interactive.subprocess = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CYCLE_LEDGER_WRITES", "str", None, False,
              "policy.cycle.ledger_writes = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CYCLE_NETWORK", "str", None, False,
              "policy.cycle.network = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CYCLE_LLM_SPEND", "str", None, False,
              "policy.cycle.llm_spend = auto|ask|never (default auto, bounded by the reforecast cap).", category="policy"),
    ConfigKey("FORECAST_POLICY_CYCLE_SUBPROCESS", "str", None, False,
              "policy.cycle.subprocess = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CRON_LEDGER_WRITES", "str", None, False,
              "policy.cron.ledger_writes = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CRON_NETWORK", "str", None, False,
              "policy.cron.network = auto|ask|never (default auto).", category="policy"),
    ConfigKey("FORECAST_POLICY_CRON_LLM_SPEND", "str", None, False,
              "policy.cron.llm_spend = auto|ask|never (default auto, bounded by the paid-tier budget + interval).", category="policy"),
    ConfigKey("FORECAST_POLICY_CRON_SUBPROCESS", "str", None, False,
              "policy.cron.subprocess = auto|ask|never (default auto).", category="policy"),
    # ── Box-level unattended spend ceilings (P3.2) ────────────────────────────
    # Daily + monthly token/USD budgets enforced at authorize(LLM_SPEND). 0 = unset
    # (UNLIMITED) — zero behaviour change until an operator sets a ceiling. A breach
    # refuses paid jobs, raises a severity=high ledger alert, and fires a notify
    # event. Reset is implicit on the UTC day/month rollover. See forecasting/budget.py.
    ConfigKey("FORECAST_BUDGET_DAILY_TOKENS", "int", 0, False,
              "Box daily LLM token ceiling (0 = unlimited). Breach refuses paid jobs.",
              category="policy"),
    ConfigKey("FORECAST_BUDGET_DAILY_USD", "float", 0.0, False,
              "Box daily LLM cost ceiling in USD (0 = unlimited). Breach refuses paid jobs.",
              category="policy"),
    ConfigKey("FORECAST_BUDGET_MONTHLY_TOKENS", "int", 0, False,
              "Box monthly LLM token ceiling (0 = unlimited). Breach refuses paid jobs.",
              category="policy"),
    ConfigKey("FORECAST_BUDGET_MONTHLY_USD", "float", 0.0, False,
              "Box monthly LLM cost ceiling in USD (0 = unlimited). Breach refuses paid jobs.",
              category="policy"),
)

REGISTRY: dict[str, ConfigKey] = {k.name: k for k in _KEYS}

# Reverse map old (deprecated) name → canonical key name, built from aliases.
DEPRECATIONS: dict[str, str] = {
    old: k.name for k in _KEYS for old in k.aliases
}
# Forward map canonical → its deprecated aliases (for the fallback loop).
_ALIASES_OF: dict[str, tuple[str, ...]] = {k.name: k.aliases for k in _KEYS if k.aliases}

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
        self._config_cache: dict[str, Any] | None = None
        self._overrides: dict[str, str] = {}
        self.registry = dict(REGISTRY if registry is None else registry)

    # ── layers ───────────────────────────────────────────────────────────────

    @property
    def environ(self) -> Mapping[str, str]:
        return os.environ if self._environ_override is None else self._environ_override

    def _config_env(self) -> dict[str, Any]:
        if self._config_override is not None:
            return dict(self._config_override)
        if self._config_cache is not None:
            return self._config_cache
        data: dict[str, Any] = {}
        try:  # lazy — avoid an import cycle and the yaml read cost at import time
            from hermes_cli.config import read_raw_config

            raw = read_raw_config()
            section = raw.get("env") if isinstance(raw, dict) else None
            if isinstance(section, dict):
                data = {str(k): v for k, v in section.items()}
        except Exception:  # pragma: no cover — config file is best-effort
            data = {}
        self._config_cache = data
        return data

    def reload(self) -> None:
        """Drop the cached config-file layer so the next read re-reads it."""
        self._config_cache = None

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
            old, canonical,
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

    def get_bool(self, name: str, default: Any = _UNSET, *, strict: bool = False) -> bool:
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
        return any(tok in upper for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL"))

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

DEFAULT_DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "reference" / "config-and-env.md"

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
    for match in re.finditer(r"^\|\s*`([A-Za-z_][A-Za-z0-9_()]*)`\s*\|", text, re.MULTILINE):
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
        from forecasting.marketdata.keys import PROVIDER_ENV
        from forecasting.api_keys import API_KEY_PROVIDERS

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
        row = {"name": name, "source": source, "secret": key.secret, "category": key.category}
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
        return n.startswith(_PRODUCT_PREFIXES) or n.endswith(("_API_KEY", "_TOKEN", "_SECRET"))

    suggest_pool = sorted(n for n in (set(cfg.registry) | set(DEPRECATIONS) | inv) if _product_relevant(n))
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
            conflicts.append({"name": name, "winner": "env", "shadowed": "config.yaml env:"})

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
        return {"surfaces": {}, "routes": [], "error": f"{exc.__class__.__name__}: {exc}"}


def render_doctor_report(report: dict[str, Any]) -> str:
    """Human-readable rendering of :func:`build_doctor_report` (no secret values)."""
    out: list[str] = []
    a = out.append

    a("forecast config doctor")
    a("=" * 60)
    layers = report["layers"]
    a(f"process env vars: {layers['env_var_count']}")
    cfg_keys = layers["config_file_keys"]
    a(f"config.yaml env: section: {len(cfg_keys)} key(s)" + (f" — {', '.join(cfg_keys)}" if cfg_keys else ""))

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
    a(f"  present ({len(present)}): {', '.join(s['name'] for s in present) or '(none)'}")
    a(f"  absent  ({len(absent)}): {', '.join(s['name'] for s in absent) or '(none)'}")

    conflicts = report["precedence_conflicts"]
    a("")
    a(f"FILE-vs-ENV precedence conflicts ({len(conflicts)}):")
    if not conflicts:
        a("  (none)")
    for row in conflicts:
        a(f"  ⚠ {row['name']}: set in both env and {row['shadowed']} — {row['winner']} WINS")

    k = report["kalshi"]
    a("")
    a("KALSHI credential pair (two-var trap):")
    a(f"  KALSHI_ACCESS_KEY_ID:   {'set' if k['key_id_set'] else 'unset'}")
    a(f"  KALSHI_PRIVATE_KEY_PATH: {'set' if k['pem_path_set'] else 'unset'}")
    if k["half_configured"]:
        a("  ⚠ HALF-CONFIGURED: exactly one of the pair is set — Kalshi streaming will "
          "silently fall back to REST polling. Set both with `forecast api-key set kalshi "
          "<key-id> --pem-file key.pem`.")
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
        a("  (notify stack unavailable" + (f": {conn['error']}" if conn.get("error") else "") + ")")
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
        a(f"    - {row['id']}  events=[{', '.join(row.get('events') or [])}]  last={status}{warn}")

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

        a(_line("daily tokens", usage.get("day_tokens"), budget.get("daily_tokens"), head.get("daily_tokens")))
        a(_line("daily USD", usage.get("day_usd"), budget.get("daily_usd"), head.get("daily_usd")))
        a(_line("monthly tokens", usage.get("month_tokens"), budget.get("monthly_tokens"), head.get("monthly_tokens")))
        a(_line("monthly USD", usage.get("month_usd"), budget.get("monthly_usd"), head.get("monthly_usd")))
        if bud.get("breached"):
            b = bud["breached"]
            a(f"  ⚠ paid jobs REFUSED: {b['scope']} {b['metric']} ceiling reached ({b['config_key']})")

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
