"""Box-level unattended spend ceilings (P3.2).

Covers the meter accumulation + UTC day/month reset semantics, the under/at/over
budget breach detection, the enforce chokepoint firing a severity=high ledger
alert AND a notify-router event, and the authorize(LLM_SPEND) integration where a
breach refuses the job with a teaching :class:`BudgetExceeded`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forecasting import budget
from forecasting.jobs.policy import PolicyRefused


# ── clock helper ───────────────────────────────────────────────────────────────


class _Clock:
    def __init__(self, dt: datetime) -> None:
        self.dt = dt

    def __call__(self) -> datetime:
        return self.dt


def _meter(tmp_path, dt=None):
    dt = dt or datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    return budget.SpendMeter(path=tmp_path / "meter.json", clock=_Clock(dt))


# ── meter accumulation ─────────────────────────────────────────────────────────


def test_record_accumulates_day_and_month(tmp_path):
    m = _meter(tmp_path)
    m.record(tokens=100, cost_usd=0.5)
    m.record(tokens=50, cost_usd=0.25)
    u = m.usage()
    assert u.day_tokens == 150
    assert u.day_usd == pytest.approx(0.75)
    assert u.month_tokens == 150
    assert u.month_usd == pytest.approx(0.75)
    assert u.day == "2026-07-09"
    assert u.month == "2026-07"
    # the file is 0600
    assert (tmp_path / "meter.json").exists()
    assert oct((tmp_path / "meter.json").stat().st_mode & 0o777) == "0o600"


def test_meter_survives_missing_and_corrupt_file(tmp_path):
    m = _meter(tmp_path)
    assert m.usage().day_tokens == 0  # no file yet
    (tmp_path / "meter.json").write_text("{not json", encoding="utf-8")
    assert m.usage().day_tokens == 0  # corrupt file → zero, not a crash
    m.record(tokens=10)
    assert m.usage().day_tokens == 10


# ── reset semantics (UTC day / month rollover) ─────────────────────────────────


def test_day_rollover_resets_daily_keeps_monthly(tmp_path):
    path = tmp_path / "meter.json"
    day1 = budget.SpendMeter(path=path, clock=_Clock(datetime(2026, 7, 9, 23, 0, tzinfo=timezone.utc)))
    day1.record(tokens=1000, cost_usd=4.0)
    # advance to the next UTC day, same month
    day2 = budget.SpendMeter(path=path, clock=_Clock(datetime(2026, 7, 10, 1, 0, tzinfo=timezone.utc)))
    u = day2.usage()
    assert u.day_tokens == 0  # daily budget reset on the new UTC day
    assert u.month_tokens == 1000  # monthly total carries across days


def test_month_rollover_resets_monthly(tmp_path):
    path = tmp_path / "meter.json"
    jul = budget.SpendMeter(path=path, clock=_Clock(datetime(2026, 7, 31, 23, 0, tzinfo=timezone.utc)))
    jul.record(tokens=5000, cost_usd=20.0)
    aug = budget.SpendMeter(path=path, clock=_Clock(datetime(2026, 8, 1, 0, 5, tzinfo=timezone.utc)))
    u = aug.usage()
    assert u.day_tokens == 0
    assert u.month_tokens == 0  # new UTC month reads zero


# ── under / at / over budget ───────────────────────────────────────────────────


def _usage(day_tokens=0, day_usd=0.0, month_tokens=0, month_usd=0.0):
    return budget.Usage("2026-07-09", "2026-07", day_tokens, day_usd, month_tokens, month_usd)


def test_check_budget_under_at_over_daily_tokens():
    b = budget.BudgetConfig(daily_tokens=1000)
    assert budget.check_budget(_usage(day_tokens=999), b) is None       # under → ok
    at = budget.check_budget(_usage(day_tokens=1000), b)                 # at → breach (hard cap)
    assert at is not None and at.scope == "daily" and at.metric == "tokens"
    over = budget.check_budget(_usage(day_tokens=1500), b)              # over → breach
    assert over is not None and over.used == 1500 and over.limit == 1000


def test_check_budget_daily_usd_and_monthly():
    assert budget.check_budget(_usage(day_usd=4.99), budget.BudgetConfig(daily_usd=5.0)) is None
    breach = budget.check_budget(_usage(day_usd=5.0), budget.BudgetConfig(daily_usd=5.0))
    assert breach.metric == "usd" and breach.scope == "daily"
    mb = budget.check_budget(_usage(month_tokens=100_000), budget.BudgetConfig(monthly_tokens=90_000))
    assert mb.scope == "monthly" and mb.metric == "tokens"


def test_unset_budget_never_breaches():
    # every ceiling 0 == unlimited
    assert budget.check_budget(_usage(day_tokens=10**9, month_usd=10**6), budget.BudgetConfig()) is None
    assert budget.evaluate(meter=None, budget=budget.BudgetConfig()) is None


def test_check_order_daily_before_monthly():
    b = budget.BudgetConfig(daily_tokens=10, monthly_tokens=10)
    breach = budget.check_budget(_usage(day_tokens=20, month_tokens=20), b)
    assert breach.scope == "daily"  # daily is checked first


# ── enforce fires the ledger alert + notify event ──────────────────────────────


def test_enforce_no_budget_is_noop(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "_emit_notify", lambda b: calls.append(b))
    monkeypatch.setattr(budget, "_raise_ledger_alert", lambda b, db_path=None: calls.append(b))
    out = budget.enforce_llm_spend(meter=_meter(tmp_path), budget=budget.BudgetConfig())
    assert out is None
    assert calls == []


def test_enforce_over_budget_fires_alert_and_notify(tmp_path, monkeypatch):
    m = _meter(tmp_path)
    m.record(tokens=1500)
    b = budget.BudgetConfig(daily_tokens=1000)

    ledger_db = str(tmp_path / "ledger.db")
    notified = []
    monkeypatch.setattr(budget, "_emit_notify", lambda breach: notified.append(breach))

    breach = budget.enforce_llm_spend(meter=m, budget=b, db_path=ledger_db)
    assert breach is not None
    assert breach.scope == "daily" and breach.metric == "tokens"

    # the notify event fired exactly once, with the window-scoped event_id
    assert len(notified) == 1
    assert notified[0].event_id == "budget:daily:tokens:2026-07-09"

    # a severity=high ledger alert landed
    from forecasting.ledger import ForecastLedger

    alerts = ForecastLedger(ledger_db).list_alerts()
    hits = [a for a in alerts if a.reason == "box_spend_budget_exceeded"]
    assert hits, "expected a box_spend_budget_exceeded alert"
    assert hits[0].severity == "high"


def test_emit_notify_delivers_alert_event(monkeypatch):
    captured = []
    from forecasting import notify

    monkeypatch.setattr(notify, "deliver_event", lambda event: captured.append(event))
    breach = budget.BudgetBreach("monthly", "usd", 120.0, 100.0, "2026-07", budget.MONTHLY_USD_KEY)
    budget._emit_notify(breach)
    assert len(captured) == 1
    assert captured[0].event_class == "alert"
    assert captured[0].event_id == "budget:monthly:usd:2026-07"


# ── BudgetExceeded is a teaching PolicyRefused ─────────────────────────────────


def test_budget_exceeded_is_policy_refused():
    breach = budget.BudgetBreach("daily", "tokens", 1500, 1000, "2026-07-09", budget.DAILY_TOKENS_KEY)
    exc = budget.BudgetExceeded(breach)
    assert isinstance(exc, PolicyRefused)
    msg = str(exc)
    assert "budget" in msg.lower()
    assert budget.DAILY_TOKENS_KEY in msg  # names the key to loosen


# ── status_report (doctor / /status) ───────────────────────────────────────────


def test_status_report_shape(tmp_path):
    m = _meter(tmp_path)
    m.record(tokens=300, cost_usd=1.0)
    rep = budget.status_report(meter=m, budget=budget.BudgetConfig(daily_tokens=1000, daily_usd=5.0))
    assert rep["enabled"] is True
    assert rep["usage"]["day_tokens"] == 300
    assert rep["headroom"]["daily_tokens"] == 700
    assert rep["headroom"]["daily_usd"] == pytest.approx(4.0)
    assert rep["breached"] is None


# ── authorize(LLM_SPEND) integration ───────────────────────────────────────────


def test_authorize_llm_spend_refused_over_budget(tmp_path, monkeypatch):
    from forecasting import appconfig
    from forecasting.jobs.context import JobContext
    from forecasting.jobs.model import JobRecord
    from forecasting.jobs.policy import ActionClass
    from forecasting.jobs.store import JobStore

    # Point the home at a temp dir so the default SpendMeter + notify land there.
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    # Set a daily token ceiling via appconfig.
    appconfig.configure(environ={"SUPERFORECASTING_AGENT_HOME": str(home),
                                 "FORECAST_BUDGET_DAILY_TOKENS": "1000"})
    # Silence notify (no bindings) — we only care the job is refused.
    monkeypatch.setattr(budget, "_emit_notify", lambda breach: None)

    # Pre-spend past the ceiling on the default meter.
    budget.record_spend(tokens=1200)

    store = JobStore(home=home)
    rec = JobRecord(job_id="j1", type="reforecast", spec={"db": str(home / "ledger.db"),
                                                          "run_mode": "cron"})
    store.write(rec)
    ctx = JobContext(rec, store, persist=True)

    with pytest.raises(budget.BudgetExceeded):
        ctx.authorize(ActionClass.LLM_SPEND, "reforecast chain")

    # the refusal is stamped on the audit trail
    outcomes = [d.get("outcome") for d in rec.policy_decisions]
    assert "budget_exceeded" in outcomes

    appconfig.configure()  # restore the singleton


def test_authorize_llm_spend_proceeds_under_budget(tmp_path, monkeypatch):
    from forecasting import appconfig
    from forecasting.jobs.context import JobContext
    from forecasting.jobs.model import JobRecord
    from forecasting.jobs.policy import ActionClass
    from forecasting.jobs.store import JobStore

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    appconfig.configure(environ={"SUPERFORECASTING_AGENT_HOME": str(home),
                                 "FORECAST_BUDGET_DAILY_TOKENS": "1000"})
    budget.record_spend(tokens=100)  # well under

    store = JobStore(home=home)
    rec = JobRecord(job_id="j2", type="reforecast", spec={"run_mode": "cron"})
    store.write(rec)
    ctx = JobContext(rec, store, persist=True)

    assert ctx.authorize(ActionClass.LLM_SPEND, "reforecast chain") is True
    appconfig.configure()
