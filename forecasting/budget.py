"""Box-level unattended spend ceilings (P3.2 hardening).

The jobs policy matrix (:mod:`forecasting.jobs.policy`) meters LLM spend per job
at the ``authorize(LLM_SPEND)`` chokepoint, but the only brakes on an UNATTENDED
box were the per-cycle caps (the reforecast batch cap, the warning-automode paid
budget + interval). A box left running can still spend without bound *across*
cycles — the failure that costs money, not uptime.

This module adds BOX-LEVEL ceilings: daily + monthly **token** and **USD-cost**
budgets, declared in :mod:`forecasting.appconfig` (so ``forecast config doctor``
shows them), accumulated in a small JSON meter under ``{home}/spend/`` (``0600``,
mirroring the notify/pairing on-disk discipline rather than adding a ledger
migration), and ENFORCED at ``authorize(LLM_SPEND)``. A breach:

  * REFUSES further paid jobs — raises :class:`BudgetExceeded`, a
    :class:`~forecasting.jobs.policy.PolicyRefused` subclass, so the job runtime
    already treats it as a terminal, *teaching* refusal (it names the keys);
  * raises a ``severity="high"`` ledger alert (deduped on the breach window); and
  * emits a notify-router ``"alert"`` event to the connected surfaces.

Reset is IMPLICIT and honest: usage is keyed on the current **UTC day**
(``YYYY-MM-DD``) and **UTC month** (``YYYY-MM``); a new day/month simply reads
zero. No cron, no sweep, no clock skew between "reset" and "check".

**Zero behaviour change by default:** every budget is unset (``0`` == unlimited),
so :func:`enforce_llm_spend` is a strict no-op until an operator (or the Hetzner
bootstrap) sets a ceiling — the same activation-gate discipline the policy matrix
uses. The meter is fed by :func:`record_spend`.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from forecasting.jobs.policy import ActionClass, PolicyRefused, RunMode

logger = logging.getLogger("forecasting.budget")

# ── appconfig keys (declared in forecasting/appconfig.py) ──────────────────────
DAILY_TOKENS_KEY = "FORECAST_BUDGET_DAILY_TOKENS"
DAILY_USD_KEY = "FORECAST_BUDGET_DAILY_USD"
MONTHLY_TOKENS_KEY = "FORECAST_BUDGET_MONTHLY_TOKENS"
MONTHLY_USD_KEY = "FORECAST_BUDGET_MONTHLY_USD"

# Retention on the meter file so it can never grow without bound (a box that runs
# for years). We only ever read the CURRENT day/month, so anything older is dead
# weight — keep a small trailing window for a human eyeballing the file.
_KEEP_DAYS = 62
_KEEP_MONTHS = 24


# ── data model ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetConfig:
    """The four box-level ceilings. ``0`` / ``0.0`` means UNLIMITED (unset)."""

    daily_tokens: int = 0
    daily_usd: float = 0.0
    monthly_tokens: int = 0
    monthly_usd: float = 0.0

    def any_set(self) -> bool:
        return bool(self.daily_tokens or self.daily_usd or self.monthly_tokens or self.monthly_usd)

    def as_dict(self) -> dict[str, Any]:
        return {
            "daily_tokens": self.daily_tokens,
            "daily_usd": self.daily_usd,
            "monthly_tokens": self.monthly_tokens,
            "monthly_usd": self.monthly_usd,
        }


@dataclass(frozen=True)
class Usage:
    """The accumulated spend for the current UTC day + month."""

    day: str
    month: str
    day_tokens: int
    day_usd: float
    month_tokens: int
    month_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "month": self.month,
            "day_tokens": self.day_tokens,
            "day_usd": round(self.day_usd, 6),
            "month_tokens": self.month_tokens,
            "month_usd": round(self.month_usd, 6),
        }


# The (scope, metric) → appconfig key + the Usage field to read. Order is the
# CHECK ORDER: the first breached ceiling is the one reported/raised.
_CHECKS: tuple[tuple[str, str, str, str, str], ...] = (
    # scope,     metric,  config key,          usage-used field, usage-window field
    ("daily", "tokens", DAILY_TOKENS_KEY, "day_tokens", "day"),
    ("daily", "usd", DAILY_USD_KEY, "day_usd", "day"),
    ("monthly", "tokens", MONTHLY_TOKENS_KEY, "month_tokens", "month"),
    ("monthly", "usd", MONTHLY_USD_KEY, "month_usd", "month"),
)


@dataclass(frozen=True)
class BudgetBreach:
    """A crossed box-level ceiling. ``used >= limit`` (a hard cap: reaching the
    ceiling refuses the NEXT paid job)."""

    scope: str  # "daily" | "monthly"
    metric: str  # "tokens" | "usd"
    used: float
    limit: float
    window: str  # the UTC day / month key this breach lives in
    config_key: str

    @property
    def scope_ref(self) -> str:
        """The alert dedup key: fresh per window, touched within a window."""
        return f"budget:{self.scope}:{self.metric}:{self.window}"

    @property
    def event_id(self) -> str:
        return self.scope_ref

    @property
    def message(self) -> str:
        unit = "tokens" if self.metric == "tokens" else "USD"
        used = f"{int(self.used)}" if self.metric == "tokens" else f"${self.used:.2f}"
        limit = f"{int(self.limit)}" if self.metric == "tokens" else f"${self.limit:.2f}"
        return (
            f"Box {self.scope} {unit} budget reached: {used} of {limit} "
            f"(window {self.window}). Paid LLM jobs are REFUSED until the {self.scope} "
            f"budget resets (UTC {'midnight' if self.scope == 'daily' else 'month'}). "
            f"Raise or clear {self.config_key} in the config.yaml env: section or the "
            f"environment to loosen the ceiling."
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "metric": self.metric,
            "used": round(self.used, 6),
            "limit": round(self.limit, 6),
            "window": self.window,
            "config_key": self.config_key,
        }


class BudgetExceeded(PolicyRefused):
    """A box-level spend ceiling refused a paid action.

    A :class:`~forecasting.jobs.policy.PolicyRefused` subclass so the job runtime's
    existing ``except PolicyRefused`` arm treats it as a terminal refusal carrying
    the teaching message — no runtime change needed. Carries the :class:`BudgetBreach`.
    """

    def __init__(self, breach: BudgetBreach, *, run_mode: Optional[RunMode] = None) -> None:
        self.breach = breach
        self.run_mode = run_mode
        self.action_class = ActionClass.LLM_SPEND
        # Skip PolicyRefused.__init__ (it builds its own message from a policy cell);
        # ours is the budget message.
        Exception.__init__(self, breach.message)


# ── on-disk meter ──────────────────────────────────────────────────────────────


def _spend_dir() -> Path:
    from superforecasting_agent.constants import get_agent_home

    d = get_agent_home() / "spend"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _secure_write_json(path: Path, data: Any) -> None:
    """Atomic 0600 write (mirrors notify.py's on-disk discipline)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover — non-POSIX fs
            pass
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class SpendMeter:
    """The box spend accumulator — ``{home}/spend/meter.json`` (0600).

    Buckets are keyed on the UTC day (``YYYY-MM-DD``) and month (``YYYY-MM``), so
    reads of the current window auto-reset on a rollover (no cron). A ``clock``
    injection makes day/month rollover deterministically testable.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._path = path
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    @property
    def path(self) -> Path:
        return self._path or (_spend_dir() / "meter.json")

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:  # be forgiving of a naive test clock
            now = now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)

    def _keys(self) -> tuple[str, str]:
        now = self._now()
        return now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")

    def _load(self) -> dict[str, Any]:
        p = self.path
        if not p.exists():
            return {}
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _prune(data: dict[str, Any]) -> None:
        days = data.get("days") or {}
        months = data.get("months") or {}
        for bucket, keep in ((days, _KEEP_DAYS), (months, _KEEP_MONTHS)):
            if len(bucket) > keep:
                for stale in sorted(bucket)[: len(bucket) - keep]:
                    bucket.pop(stale, None)

    def record(self, *, tokens: int = 0, cost_usd: float = 0.0) -> Usage:
        """Add spend to the current UTC day + month buckets; return live usage."""
        tokens = max(0, int(tokens or 0))
        cost_usd = max(0.0, float(cost_usd or 0.0))
        day, month = self._keys()
        data = self._load()
        days = data.setdefault("days", {})
        months = data.setdefault("months", {})
        d = days.setdefault(day, {"tokens": 0, "usd": 0.0})
        m = months.setdefault(month, {"tokens": 0, "usd": 0.0})
        d["tokens"] = int(d.get("tokens") or 0) + tokens
        d["usd"] = float(d.get("usd") or 0.0) + cost_usd
        m["tokens"] = int(m.get("tokens") or 0) + tokens
        m["usd"] = float(m.get("usd") or 0.0) + cost_usd
        self._prune(data)
        _secure_write_json(self.path, data)
        return self.usage()

    def usage(self) -> Usage:
        day, month = self._keys()
        data = self._load()
        d = (data.get("days") or {}).get(day) or {}
        m = (data.get("months") or {}).get(month) or {}
        return Usage(
            day=day,
            month=month,
            day_tokens=int(d.get("tokens") or 0),
            day_usd=float(d.get("usd") or 0.0),
            month_tokens=int(m.get("tokens") or 0),
            month_usd=float(m.get("usd") or 0.0),
        )

    def reset(self) -> None:
        """Wipe the meter (operator override / test helper)."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ── budget resolution + breach check ───────────────────────────────────────────


def resolve_budget(cfg: Any = None) -> BudgetConfig:
    """Read the four ceilings from appconfig. A bad/typo'd value falls to 0
    (unlimited) — a config typo never accidentally halts the desk."""

    from forecasting import appconfig

    def _int(name: str) -> int:
        try:
            return max(0, int(appconfig.get_int(name, 0) or 0))
        except Exception:  # noqa: BLE001
            return 0

    def _float(name: str) -> float:
        try:
            return max(0.0, float(appconfig.get_float(name, 0.0) or 0.0))
        except Exception:  # noqa: BLE001
            return 0.0

    return BudgetConfig(
        daily_tokens=_int(DAILY_TOKENS_KEY),
        daily_usd=_float(DAILY_USD_KEY),
        monthly_tokens=_int(MONTHLY_TOKENS_KEY),
        monthly_usd=_float(MONTHLY_USD_KEY),
    )


def check_budget(usage: Usage, budget: BudgetConfig) -> Optional[BudgetBreach]:
    """The first crossed ceiling (``used >= limit``), in :data:`_CHECKS` order,
    or ``None``. An unset ceiling (``0``) is never a breach."""

    for scope, metric, key, used_field, window_field in _CHECKS:
        limit = getattr(budget, f"{scope}_{metric}")
        if not limit or limit <= 0:
            continue
        used = getattr(usage, used_field)
        if used >= limit:
            return BudgetBreach(
                scope=scope,
                metric=metric,
                used=float(used),
                limit=float(limit),
                window=getattr(usage, window_field),
                config_key=key,
            )
    return None


# ── enforcement (the authorize(LLM_SPEND) chokepoint) ──────────────────────────


def evaluate(
    meter: Optional[SpendMeter] = None,
    budget: Optional[BudgetConfig] = None,
) -> Optional[BudgetBreach]:
    """Pure check: is the box over a ceiling right now? No side effects."""
    budget = budget if budget is not None else resolve_budget()
    if not budget.any_set():
        return None
    meter = meter or SpendMeter()
    return check_budget(meter.usage(), budget)


def enforce_llm_spend(
    *,
    run_mode: Optional[RunMode] = None,
    db_path: Optional[str] = None,
    meter: Optional[SpendMeter] = None,
    budget: Optional[BudgetConfig] = None,
    notify: bool = True,
) -> Optional[BudgetBreach]:
    """The chokepoint entry: returns the :class:`BudgetBreach` (caller then raises
    :class:`BudgetExceeded`) or ``None`` to proceed. On a breach it fires the
    ``severity="high"`` ledger alert and the notify-router event as side effects —
    both best-effort so an alerting hiccup never turns a refusal into a crash.

    Fails **open** only on an unexpected meter-read error (a disk fault must not
    halt every forecast); the breach itself is deterministic."""

    try:
        breach = evaluate(meter, budget)
    except Exception:  # noqa: BLE001 — a meter fault fails open (never halt the desk)
        logger.warning("budget: meter read failed; allowing spend (fail-open)", exc_info=True)
        return None
    if breach is None:
        return None
    _raise_ledger_alert(breach, db_path=db_path)
    if notify:
        _emit_notify(breach)
    return breach


def _raise_ledger_alert(breach: BudgetBreach, *, db_path: Optional[str]) -> None:
    """Open a ``severity="high"`` global alert for the breach (deduped per window)."""
    try:
        from forecasting.ledger import ForecastLedger, allow_ledger_writes

        ledger = ForecastLedger(db_path)
        with allow_ledger_writes(reason="box_spend_budget"):
            ledger.create_alert(
                severity="high",
                scope_type="global",
                scope_ref=breach.scope_ref,
                reason="box_spend_budget_exceeded",
                recommended_action=breach.message,
                refresh_action=True,
            )
    except Exception:  # noqa: BLE001 — alerting is best-effort
        logger.warning("budget: could not raise ledger alert for %s", breach.scope_ref, exc_info=True)


def _emit_notify(breach: BudgetBreach) -> None:
    """Fan a compact ``alert`` event out to the connected surfaces (deduped)."""
    try:
        from forecasting import notify as _notify

        event = _notify.NotifyEvent(
            event_class="alert",
            title="Spend budget exceeded — paid jobs refused",
            body=breach.message,
            event_id=breach.event_id,
        )
        _notify.deliver_event(event)
    except Exception:  # noqa: BLE001 — notification is best-effort
        logger.warning("budget: could not emit notify event for %s", breach.scope_ref, exc_info=True)


# ── the feed (callers record spend here) ───────────────────────────────────────


def record_spend(
    *,
    tokens: int = 0,
    cost_usd: float = 0.0,
    meter: Optional[SpendMeter] = None,
) -> Usage:
    """Record LLM spend against the box meter. The single feed the ceilings read.

    Best-effort by construction — a metering failure returns the prior usage
    rather than propagating (recording spend must never break the run that spent
    it)."""
    try:
        return (meter or SpendMeter()).record(tokens=tokens, cost_usd=cost_usd)
    except Exception:  # noqa: BLE001
        logger.warning("budget: record_spend failed", exc_info=True)
        try:
            return (meter or SpendMeter()).usage()
        except Exception:  # noqa: BLE001
            now = datetime.now(timezone.utc)
            return Usage(now.strftime("%Y-%m-%d"), now.strftime("%Y-%m"), 0, 0.0, 0, 0.0)


def status_report(
    meter: Optional[SpendMeter] = None,
    budget: Optional[BudgetConfig] = None,
) -> dict[str, Any]:
    """The doctor / ``/status`` section: current usage, the ceilings, headroom."""
    meter = meter or SpendMeter()
    budget = budget if budget is not None else resolve_budget()
    usage = meter.usage()
    breach = check_budget(usage, budget) if budget.any_set() else None

    def _headroom(limit: float, used: float) -> Optional[float]:
        if not limit or limit <= 0:
            return None
        return round(max(0.0, limit - used), 6)

    return {
        "enabled": budget.any_set(),
        "usage": usage.as_dict(),
        "budget": budget.as_dict(),
        "headroom": {
            "daily_tokens": _headroom(budget.daily_tokens, usage.day_tokens),
            "daily_usd": _headroom(budget.daily_usd, usage.day_usd),
            "monthly_tokens": _headroom(budget.monthly_tokens, usage.month_tokens),
            "monthly_usd": _headroom(budget.monthly_usd, usage.month_usd),
        },
        "breached": breach.as_dict() if breach else None,
    }


__all__ = [
    "DAILY_TOKENS_KEY",
    "DAILY_USD_KEY",
    "MONTHLY_TOKENS_KEY",
    "MONTHLY_USD_KEY",
    "BudgetConfig",
    "Usage",
    "BudgetBreach",
    "BudgetExceeded",
    "SpendMeter",
    "resolve_budget",
    "check_budget",
    "evaluate",
    "enforce_llm_spend",
    "record_spend",
    "status_report",
]
