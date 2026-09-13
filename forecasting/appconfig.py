"""Typed, layered configuration for the forecast desk (architecture review item #8).

The desk reads ~218 environment variables at call sites scattered across the
codebase (see ``docs/reference/config-and-env.md`` — the generated inventory).
Each read hand-rolls its own ``os.environ.get('X', default)`` + coercion, so a
typo in a var name silently falls through to the default, a bad ``int`` value
crashes with an opaque ``ValueError`` that never names the key, and there is no
single place to ask "what is set, where did it come from, is it a secret".

The read-only loader is owned by
``superforecasting_agent.storage.forecast_configuration``. This compatibility
facade re-exports its API and owns the diagnostic report, whose optional runtime
checks must not become dependencies of source acquisition.

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

from pathlib import Path
from typing import Any, Iterable

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
from superforecasting_agent.storage.forecast_configuration import (
    _UNSET as _UNSET,
)
from superforecasting_agent.storage.forecast_configuration import (
    AppConfig as AppConfig,
)
from superforecasting_agent.storage.forecast_configuration import (
    AppConfigError as AppConfigError,
)
from superforecasting_agent.storage.forecast_configuration import (
    configure as configure,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_bool as get_bool,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_config as get_config,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_float as get_float,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_int as get_int,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_path as get_path,
)
from superforecasting_agent.storage.forecast_configuration import (
    get_str as get_str,
)
from superforecasting_agent.storage.forecast_configuration import (
    redact as redact,
)
from superforecasting_agent.storage.forecast_configuration import (
    reset_deprecation_warnings as reset_deprecation_warnings,
)
from superforecasting_agent.storage.forecast_configuration import (
    secret as secret,
)
from superforecasting_agent.storage.forecast_configuration import (
    set_override as set_override,
)

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

    cfg = cfg or get_config()
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
