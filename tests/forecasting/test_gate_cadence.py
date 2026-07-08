"""G5 · UPDATE-CADENCE ESCALATION (sweep-side) — stale beyond cadence becomes a rule
verdict + a deduped alert, never a commit block.

The rule fires ONLY on lint/finish_sweep for a live current snapshot past its review
cadence × the grace multiple (default 1.5) with no recorded stale_evidence_reason. It
never evaluates at commit (its applies() excludes the update event). The sweep opens a
deduped cadence_overdue alert that folds through create_alert (touch, never re-row)
and ages up the P1 escalation ladder."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from forecasting.hooks import lint_forecast, resolve_severities, run_hooks
from forecasting.hooks.spec import HookContext
from forecasting.ledger import ForecastLedger


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "cadence.db"))
    lg.initialize_schema()
    return lg


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _seed(lg, *, age_days: int, cadence="weekly", reason=None):
    q = lg.create_question(
        title="Will the metric hold by close?",
        resolution_criteria="Resolves yes if the metric holds at close; otherwise no.",
        review_cadence=cadence,
    )
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    meta = {"stale_evidence_reason": reason} if reason else None
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.4, rationale="read",
        require_panel=False, enforce_resolved_hooks=False, as_of=_days_ago(age_days), metadata=meta,
    )
    return q


def _cadence_verdict(lg, qid):
    report = lint_forecast(lg, qid, event="lint")
    return next((v for v in report.verdicts if v.rule_id == "update_cadence_honored"), None)


# ── the rule: fires past grace, honest when explained ─────────────────────────
def test_overdue_weekly_forecast_fails_on_lint(tmp_path):
    lg = _ledger(tmp_path)
    q = _seed(lg, age_days=12)  # 12/7 = 1.7x > 1.5 grace
    v = _cadence_verdict(lg, q.id)
    assert v is not None and v.passed is False and v.severity.value == "warn"
    assert "past its weekly review cadence" in v.message


def test_within_grace_passes(tmp_path):
    lg = _ledger(tmp_path)
    q = _seed(lg, age_days=8)  # 8/7 = 1.14x < 1.5 grace
    v = _cadence_verdict(lg, q.id)
    assert v is not None and v.passed is True


def test_recorded_stale_reason_passes_even_when_overdue(tmp_path):
    lg = _ledger(tmp_path)
    q = _seed(lg, age_days=20, reason="nothing material can change until the vote")
    v = _cadence_verdict(lg, q.id)
    assert v is not None and v.passed is True


# ── the commit event NEVER evaluates the rule ─────────────────────────────────
def test_rule_does_not_apply_at_commit():
    ctx = HookContext(question_id="fq", event="update", forecast_origin="live",
                      review_cadence="weekly", cadence_overdue_ratio=5.0, is_thesis_or_factor=False)
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    assert not any(v.rule_id == "update_cadence_honored" for v in report.verdicts)


def test_rule_requires_a_cadence():
    ctx = HookContext(question_id="fq", event="lint", forecast_origin="live",
                      review_cadence=None, cadence_overdue_ratio=5.0, is_thesis_or_factor=False)
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    assert not any(v.rule_id == "update_cadence_honored" for v in report.verdicts)


# ── the sweep alert: deduped (touch, never re-row) ────────────────────────────
def test_sweep_opens_deduped_cadence_alert(tmp_path):
    lg = _ledger(tmp_path)
    q = _seed(lg, age_days=15)
    first = lg.sweep_cadence_alerts()
    assert first["overdue"] == 1 and first["alerted"] == [q.id]

    # A SECOND sweep touches the same open alert instead of re-rowing it.
    second = lg.sweep_cadence_alerts()
    assert second["overdue"] == 1 and second["alerted"] == []  # already open
    open_cadence = [a for a in lg.list_alerts(unresolved_only=True) if a.reason == "cadence_overdue"]
    assert len(open_cadence) == 1
    assert (open_cadence[0].seen_count or 1) >= 2  # folded, not stacked


def test_cadence_alert_closes_on_fresh_snapshot(tmp_path):
    lg = _ledger(tmp_path)
    q = _seed(lg, age_days=15)
    # Raise the cadence alert in the past (deterministic: a fresh commit's created_at
    # is strictly after it, so reconcile's snapshot-after close fires).
    lg.create_alert(severity="warning", scope_type="question", scope_ref=q.id,
                    reason="cadence_overdue", recommended_action="refresh", now=_days_ago(2))
    assert any(a.reason == "cadence_overdue" for a in lg.list_alerts(unresolved_only=True))
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.45, rationale="fresh",
                       require_panel=False, enforce_resolved_hooks=False)
    lg.reconcile_alerts()
    assert not any(a.reason == "cadence_overdue" for a in lg.list_alerts(unresolved_only=True))
    # ...and the rule itself now passes (the forecast was refreshed on cadence).
    v = _cadence_verdict(lg, q.id)
    assert v is not None and v.passed is True
