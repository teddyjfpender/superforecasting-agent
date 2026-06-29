"""Agent tool actions for warning resolution (slice 3c):
`resolve_warning {ref}` and `run_warning_automode {limit?, dry_run?}`.

These let the agent drive the open-alert backlog through the SAME gated
dispatcher the CLI/cron/gateway use — acking ONLY on genuine gated work.
"""

from __future__ import annotations

import json

from forecasting.ledger import ForecastLedger
from tools.forecasting_tool import forecast_ledger_tool


def _seed(tmp_path):
    db = str(tmp_path / "w.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    ids = {}
    ids["postmortem"] = lg.create_alert(
        severity="high", scope_type="question", scope_ref="fq_a",
        reason="postmortem_due", recommended_action="Run a postmortem.").id
    ids["no_auto"] = lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_d",
        reason="domain_error_profile_applies:politics", recommended_action="Human review.").id
    ids["bookkeeping"] = lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_f",
        reason="autopilot_enabled", recommended_action="Informational.").id
    return db, lg, ids


def test_run_warning_automode_dry_run_writes_nothing(tmp_path):
    db, lg, _ = _seed(tmp_path)

    out = json.loads(forecast_ledger_tool(
        {"action": "run_warning_automode", "db": db, "dry_run": True}
    ))
    assert out["success"] is True
    assert out["dry_run"] is True
    assert out["total"] == 3
    by_reason = {e["reason"]: e for e in out["results"]}
    assert by_reason["autopilot_enabled"]["planned"] == "would_acknowledge"
    assert by_reason["domain_error_profile_applies:politics"]["planned"] == "surfaced"
    # Dry run is pure — all alerts still open.
    assert len(lg.list_alerts(unresolved_only=True)) == 3


def test_run_warning_automode_real_acks_only_bookkeeping(tmp_path):
    db, lg, ids = _seed(tmp_path)

    out = json.loads(forecast_ledger_tool(
        {"action": "run_warning_automode", "db": db, "reconcile": False}
    ))
    assert out["success"] is True
    by_id = {r["alert_id"]: r for r in out["results"]}
    assert by_id[ids["bookkeeping"]]["status"] == "resolved"
    assert by_id[ids["no_auto"]]["status"] == "surfaced"

    open_now = {a.id for a in lg.list_alerts(unresolved_only=True)}
    assert ids["bookkeeping"] not in open_now
    assert ids["no_auto"] in open_now
    assert ids["postmortem"] in open_now  # cannot score a non-existent question


def test_resolve_warning_by_alert_id(tmp_path):
    db, lg, ids = _seed(tmp_path)

    out = json.loads(forecast_ledger_tool(
        {"action": "resolve_warning", "db": db, "ref": ids["bookkeeping"]}
    ))
    assert out["success"] is True
    assert out["count"] == 1
    assert out["results"][0]["status"] == "resolved"
    assert ids["bookkeeping"] not in {a.id for a in lg.list_alerts(unresolved_only=True)}


def test_resolve_warning_by_scope_ref(tmp_path):
    db, lg, ids = _seed(tmp_path)

    out = json.loads(forecast_ledger_tool(
        {"action": "resolve_warning", "db": db, "ref": "fq_d"}
    ))
    # fq_d only carries the NO_AUTO alert -> surfaced, never acked.
    assert out["success"] is True
    assert out["results"][0]["status"] == "surfaced"
    assert ids["no_auto"] in {a.id for a in lg.list_alerts(unresolved_only=True)}


def test_resolve_warning_unknown_ref_errors(tmp_path):
    db, _, _ = _seed(tmp_path)
    out = json.loads(forecast_ledger_tool(
        {"action": "resolve_warning", "db": db, "ref": "al_nope"}
    ))
    assert out["success"] is False
