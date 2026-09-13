"""Data-only forecast setting contracts, defaults and compatibility aliases."""

from dataclasses import dataclass
from typing import Any


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
    ConfigKey(
        "FORECAST_LEDGER_DB",
        "path",
        None,
        False,
        "Override path to the forecast ledger SQLite database.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_TRIAGE_MODEL",
        "str",
        None,
        False,
        "Model id for the cheap information-triage auto-labeler.",
        category="triage",
    ),
    ConfigKey(
        "FORECAST_TRIAGE_TRUST_MIN_SAMPLE",
        "int",
        20,
        False,
        "Min labelled sample before the triage classifier is trusted.",
        category="triage",
    ),
    ConfigKey(
        "FORECAST_TRIAGE_TRUST_THRESHOLD",
        "float",
        0.8,
        False,
        "Agreement threshold above which the triage classifier is trusted.",
        category="triage",
    ),
    ConfigKey(
        "FORECAST_GATE_DIRECT_WRITES",
        "str",
        "on",
        False,
        "Direct-write gate mode: on | warn | off.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_DISABLE_HOOK_BLOCKING",
        "bool",
        False,
        False,
        "Kill-switch: disable saturation/style hook blocking on live commits.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_HOOK_READINESS_FLOOR",
        "float",
        80.0,
        False,
        "Machine-readiness (0-100) below which the readiness_floor hook fires on live commits.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_DISABLE_SATURATION_ESCALATION",
        "bool",
        False,
        False,
        "Kill-switch: disable the saturation-escalation alert on autofix commits.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_DISABLE_THESIS_CASCADE",
        "bool",
        False,
        False,
        "Kill-switch: disable thesis-cascade freshening on member commits.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_NO_LESSON_SYNTHESIS",
        "bool",
        False,
        False,
        "Skip calibration-lesson synthesis in the cron runner.",
        category="cron",
    ),
    ConfigKey(
        "FORECAST_HIERARCHICAL_CALIBRATION",
        "bool",
        False,
        False,
        "Activate hierarchical Platt (per-cohort intercept offsets delta_s) at "
        "the terminal calibration. DEFAULT-OFF (same activation-gate pattern as "
        "the sqrt(3) slope): the derivation returns the global map until this is "
        "flipped on, backed by the `calibration --hierarchical` validation report.",
        category="ledger",
    ),
    ConfigKey(
        "FORECAST_BRIDGE_PORT",
        "int",
        8787,
        False,
        "Port for the read-only forecast web bridge.",
        category="web",
    ),
    # ── Agent tool-call budget (checkpoint-continuation soft cap) ─────────────
    ConfigKey(
        "FORECAST_AGENT_MAX_TOOL_ITERATIONS",
        "int",
        200,
        False,
        "Per-turn tool-call SOFT cap for the top-level agent loop. Hitting it "
        "is a CHECKPOINT (surface progress + reset the budget + continue), not a "
        "stop: interactive runs continue automatically; unattended runs continue "
        "when the spend policy grants llm_spend auto. Default 200 (raised from 90 "
        "for deep-research turns). Legacy aliases: SUPERFORECASTING_AGENT_MAX_"
        "ITERATIONS / FORECAST_MAX_ITERATIONS / HERMES_MAX_ITERATIONS.",
        category="runtime",
    ),
    ConfigKey(
        "FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER",
        "int",
        10,
        False,
        "Absolute tool-call ceiling as a multiple of the soft cap (default 10× ⇒ "
        "2000). Even an interactive run stops here, with a message naming the key. "
        "The spend caps remain the primary governor of unattended cost.",
        category="runtime",
    ),
    # ── Quorum panel (operator-pinned model line-up) ─────────────────────────
    # Comma list of ``provider:model`` seats that OVERRIDE the connected-provider
    # panel rebuild (e.g. "openai-codex:gpt-5.5, gemini:gemini-2.5-flash"). Each
    # entry is validated against callable providers — a non-callable entry errors
    # naming itself. Unset ⇒ the preset/connected resolution is used unchanged.
    ConfigKey(
        "QUORUM_PANEL_MODELS",
        "str",
        None,
        False,
        "Comma list of provider:model quorum panel seats; overrides the "
        "connected-provider rebuild. Validated against callable providers.",
        category="quorum",
    ),
    ConfigKey(
        "QUORUM_JUDGE_MODEL",
        "str",
        None,
        False,
        "Optional provider:model for the quorum judge synthesis (overrides "
        "the preset/connected judge). Validated against callable providers.",
        category="quorum",
    ),
    ConfigKey(
        "FORECAST_BIN",
        "str",
        None,
        False,
        "Explicit path to the forecast CLI binary (kanban launcher).",
        category="runtime",
    ),
    # ── Canonical home / timezone / redaction (deprecated aliases) ───────────
    ConfigKey(
        "SUPERFORECASTING_AGENT_HOME",
        "path",
        None,
        False,
        "Agent home directory (config.yaml + .env + ledger live here).",
        aliases=("FORECAST_HOME", "HERMES_HOME"),
        category="runtime",
    ),
    ConfigKey(
        "SUPERFORECASTING_AGENT_TIMEZONE",
        "str",
        None,
        False,
        "Display/scheduling timezone for the desk.",
        aliases=("FORECAST_TIMEZONE", "HERMES_TIMEZONE"),
        category="runtime",
    ),
    ConfigKey(
        "SUPERFORECASTING_AGENT_REDACT_SECRETS",
        "bool",
        False,
        False,
        "Redact secret values in runtime logs/plugin migration.",
        aliases=("FORECAST_REDACT_SECRETS", "HERMES_REDACT_SECRETS"),
        category="runtime",
    ),
    # ── Multiplayer identity (M1 of the Slack harness plan) ──────────────────
    # The name + stable instance id that make this desk a distinct, @-taggable
    # collaborator in a shared Slack channel. See ``forecasting/identity.py``.
    ConfigKey(
        "AGENT_NAME",
        "str",
        None,
        False,
        "Agent display name for multiplayer collab (default 'Bernard' when unset). "
        "Flows into the soul, the TUI banner, and the sfp/1 wire sender.",
        category="identity",
    ),
    ConfigKey(
        "AGENT_INSTANCE_ID",
        "str",
        None,
        False,
        "Stable uuid identifying this instance across restarts. Minted once and "
        "persisted to {home}/identity.json when unset; an operator may pin it here.",
        category="identity",
    ),
    ConfigKey(
        "AGENT_PERSONA",
        "str",
        None,
        False,
        "Optional persona notes for this named agent (free text, surfaced in whoami).",
        category="identity",
    ),
    # ── Multiplayer collab authorisation + rate limit (M3 import pipeline) ────
    ConfigKey(
        "COLLAB_ALLOWED_INSTANCES",
        "str",
        None,
        False,
        "Comma-separated list of authorised counterparty instance_ids. CLOSED BY "
        "DEFAULT — empty/unset accepts no peer imports. Authorises by stable id, "
        "never display name.",
        category="identity",
    ),
    ConfigKey(
        "COLLAB_RATE_LIMIT_PER_HOUR",
        "int",
        240,
        False,
        "Max peer sfp/1 messages the collab router accepts per channel per hour "
        "(a malicious channel can't drain the desk via inbound messages).",
        category="identity",
    ),
    # ── HERMES_* runtime ─────────────────────────────────────────────────────
    ConfigKey(
        "HERMES_HOME_MODE",
        "str",
        None,
        False,
        "Permission mode for the agent-home directory (managed installs).",
        category="runtime",
    ),
    ConfigKey(
        "HERMES_PROFILE",
        "str",
        None,
        False,
        "Active profile name (selects the config.yaml home).",
        category="runtime",
    ),
    ConfigKey(
        "HERMES_DEV", "str", None, False, "Developer mode flag.", category="runtime"
    ),
    ConfigKey(
        "HERMES_CONTAINER",
        "str",
        None,
        False,
        "Container-runtime marker.",
        category="runtime",
    ),
    ConfigKey(
        "HERMES_TENANT",
        "str",
        None,
        False,
        "Tenant id for multi-tenant kanban runs.",
        category="runtime",
    ),
    ConfigKey(
        "HERMES_BASE_URL",
        "str",
        None,
        False,
        "Base URL for the Hermes gateway/API surface.",
        category="web",
    ),
    ConfigKey(
        "HERMES_API_KEY",
        "str",
        None,
        True,
        "Bearer token guarding the tui gateway API.",
        category="secret",
    ),
    ConfigKey(
        "HERMES_SESSION_KEY",
        "str",
        None,
        True,
        "Per-session key for the terminal tool.",
        category="secret",
    ),
    # ── Data-provider secrets (forecasting.source_adapters / marketdata) ─────
    ConfigKey(
        "FRED_API_KEY",
        "str",
        None,
        True,
        "FRED — Federal Reserve Economic Data API key.",
        category="secret",
    ),
    ConfigKey(
        "EIA_API_KEY",
        "str",
        None,
        True,
        "EIA — US Energy Information Administration API key.",
        category="secret",
    ),
    ConfigKey(
        "BLS_API_KEY",
        "str",
        None,
        True,
        "BLS — US Bureau of Labor Statistics API key.",
        category="secret",
    ),
    ConfigKey(
        "CENSUS_API_KEY",
        "str",
        None,
        True,
        "US Census Bureau API key.",
        category="secret",
    ),
    ConfigKey(
        "BEA_API_KEY",
        "str",
        None,
        True,
        "BEA — Bureau of Economic Analysis API key (marketdata provider 'bea').",
        category="secret",
    ),
    ConfigKey(
        "RELIEFWEB_APPNAME",
        "str",
        "superforecasting-agent",
        False,
        "ReliefWeb API appname (polite identification).",
        category="config",
    ),
    # ── Kalshi credential PAIR (two-var trap — see the doctor) ────────────────
    ConfigKey(
        "KALSHI_ACCESS_KEY_ID",
        "str",
        None,
        True,
        "Kalshi access key id (websocket streaming only; REST is keyless).",
        category="secret",
    ),
    ConfigKey(
        "KALSHI_PRIVATE_KEY_PATH",
        "path",
        None,
        False,
        "Path to the Kalshi RSA private-key PEM (pairs with KALSHI_ACCESS_KEY_ID).",
        category="config",
    ),
    # ── Web-search provider secrets ──────────────────────────────────────────
    ConfigKey(
        "FIRECRAWL_API_KEY",
        "str",
        None,
        True,
        "Firecrawl paid web search + extract backend.",
        category="secret",
    ),
    ConfigKey(
        "EXA_API_KEY",
        "str",
        None,
        True,
        "Exa web search + contents.",
        category="secret",
    ),
    ConfigKey(
        "TAVILY_API_KEY",
        "str",
        None,
        True,
        "Tavily research search.",
        category="secret",
    ),
    ConfigKey(
        "BRAVE_API_KEY", "str", None, True, "Brave Search API.", category="secret"
    ),
    ConfigKey(
        "PARALLEL_API_KEY",
        "str",
        None,
        True,
        "Parallel web search + extract.",
        category="secret",
    ),
    # ── LLM provider secrets ─────────────────────────────────────────────────
    ConfigKey(
        "OPENAI_API_KEY",
        "str",
        None,
        True,
        "OpenAI / Codex provider key.",
        category="secret",
    ),
    ConfigKey(
        "ANTHROPIC_API_KEY",
        "str",
        None,
        True,
        "Anthropic (Claude) provider key.",
        category="secret",
    ),
    ConfigKey(
        "OPENROUTER_API_KEY",
        "str",
        None,
        True,
        "OpenRouter multi-model gateway key.",
        category="secret",
    ),
    ConfigKey(
        "XAI_API_KEY", "str", None, True, "xAI (Grok) provider key.", category="secret"
    ),
    # ── Approval / spend policy matrix (architecture review item #9) ─────────
    # One knob per (run_mode × action_class) cell of the job-runtime approval matrix
    # — the ENV/registry spelling of the logical ``policy.<mode>.<class>`` key. Value:
    # auto | ask | never. UNSET (the default) means "use the matrix default", which is
    # ``auto`` for every cell today (zero behaviour change until an operator tightens
    # one). See ``forecasting/jobs/policy.py``.
    ConfigKey(
        "FORECAST_POLICY_INTERACTIVE_LEDGER_WRITES",
        "str",
        None,
        False,
        "policy.interactive.ledger_writes = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_INTERACTIVE_NETWORK",
        "str",
        None,
        False,
        "policy.interactive.network = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_INTERACTIVE_LLM_SPEND",
        "str",
        None,
        False,
        "policy.interactive.llm_spend = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_INTERACTIVE_SUBPROCESS",
        "str",
        None,
        False,
        "policy.interactive.subprocess = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CYCLE_LEDGER_WRITES",
        "str",
        None,
        False,
        "policy.cycle.ledger_writes = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CYCLE_NETWORK",
        "str",
        None,
        False,
        "policy.cycle.network = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CYCLE_LLM_SPEND",
        "str",
        None,
        False,
        "policy.cycle.llm_spend = auto|ask|never (default auto, bounded by the reforecast cap).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CYCLE_SUBPROCESS",
        "str",
        None,
        False,
        "policy.cycle.subprocess = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CRON_LEDGER_WRITES",
        "str",
        None,
        False,
        "policy.cron.ledger_writes = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CRON_NETWORK",
        "str",
        None,
        False,
        "policy.cron.network = auto|ask|never (default auto).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CRON_LLM_SPEND",
        "str",
        None,
        False,
        "policy.cron.llm_spend = auto|ask|never (default auto, bounded by the paid-tier budget + interval).",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_POLICY_CRON_SUBPROCESS",
        "str",
        None,
        False,
        "policy.cron.subprocess = auto|ask|never (default auto).",
        category="policy",
    ),
    # ── Box-level unattended spend ceilings (P3.2) ────────────────────────────
    # Daily + monthly token/USD budgets enforced at authorize(LLM_SPEND). 0 = unset
    # (UNLIMITED) — zero behaviour change until an operator sets a ceiling. A breach
    # refuses paid jobs, raises a severity=high ledger alert, and fires a notify
    # event. Reset is implicit on the UTC day/month rollover. See forecasting/budget.py.
    ConfigKey(
        "FORECAST_BUDGET_DAILY_TOKENS",
        "int",
        0,
        False,
        "Box daily LLM token ceiling (0 = unlimited). Breach refuses paid jobs.",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_BUDGET_DAILY_USD",
        "float",
        0.0,
        False,
        "Box daily LLM cost ceiling in USD (0 = unlimited). Breach refuses paid jobs.",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_BUDGET_MONTHLY_TOKENS",
        "int",
        0,
        False,
        "Box monthly LLM token ceiling (0 = unlimited). Breach refuses paid jobs.",
        category="policy",
    ),
    ConfigKey(
        "FORECAST_BUDGET_MONTHLY_USD",
        "float",
        0.0,
        False,
        "Box monthly LLM cost ceiling in USD (0 = unlimited). Breach refuses paid jobs.",
        category="policy",
    ),
)

REGISTRY: dict[str, ConfigKey] = {k.name: k for k in _KEYS}

# Reverse map old (deprecated) name → canonical key name, built from aliases.
DEPRECATIONS: dict[str, str] = {old: k.name for k in _KEYS for old in k.aliases}
# Forward map canonical → its deprecated aliases (for the fallback loop).
_ALIASES_OF: dict[str, tuple[str, ...]] = {
    k.name: k.aliases for k in _KEYS if k.aliases
}
