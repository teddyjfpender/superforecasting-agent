"""`forecast warnings` CLI (slice 2). The dispatcher brain is unit-tested in
test_warnings_dispatcher.py; here we pin the CLI wiring: `warnings list` groups the
open backlog by reason (counts + priority order), and `warnings automode --dry-run`
prints the per-alert plan WITHOUT writing (no ack, no runner spend).
"""

from __future__ import annotations

import argparse
import json

from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "w.db"))
    lg.initialize_schema()
    return lg


def _seed_alerts(lg: ForecastLedger) -> None:
    # Two postmortems (POSTMORTEM), one source-change (MATERIAL_CHANGE), one
    # human-judgment domain-error (NO_AUTO), one staleness (REFORECAST), one
    # bookkeeping notice (BOOKKEEPING).
    lg.create_alert(severity="high", scope_type="question", scope_ref="fq_a",
                    reason="postmortem_due", recommended_action="Run a postmortem.")
    lg.create_alert(severity="high", scope_type="question", scope_ref="fq_b",
                    reason="postmortem_due", recommended_action="Run a postmortem.")
    lg.create_alert(severity="warning", scope_type="question", scope_ref="fq_c",
                    reason="watched_source_changed:src1", recommended_action="Recheck the source.")
    lg.create_alert(severity="warning", scope_type="question", scope_ref="fq_d",
                    reason="domain_error_profile_applies:politics", recommended_action="Human review.")
    lg.create_alert(severity="warning", scope_type="question", scope_ref="fq_e",
                    reason="evidence_stale_7d_plus", recommended_action="Re-forecast.")
    lg.create_alert(severity="info", scope_type="question", scope_ref="fq_f",
                    reason="autopilot_enabled", recommended_action="Informational.")


def _args(tmp_path, **over):
    base = dict(
        db=str(tmp_path / "w.db"),
        reason=None,
        scope=None,
        limit=None,
        json=True,
        dry_run=False,
        agent=False,
        model=None,
        provider=None,
        max_iterations=5,
        max_questions=None,
        force=False,
        no_reconcile=False,
        now=None,
    )
    base.update(over)
    return argparse.Namespace(**base)


def test_warnings_list_groups_by_reason_with_counts(tmp_path, capsys):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    cli._cmd_warnings_list(_args(tmp_path, json=True))
    payload = json.loads(capsys.readouterr().out)

    assert payload["open_total"] == 6
    assert payload["group_count"] == 5  # 6 alerts, but the 2 postmortem_due collapse into 1 group
    by_reason = {g["reason"]: g for g in payload["groups"]}
    assert by_reason["postmortem_due"]["count"] == 2
    assert by_reason["postmortem_due"]["kind"] == "postmortem"
    assert by_reason["watched_source_changed:src1"]["kind"] == "material_change"
    assert by_reason["domain_error_profile_applies:politics"]["kind"] == "no_auto"
    assert by_reason["domain_error_profile_applies:politics"]["auto_resolvable"] is False
    assert by_reason["evidence_stale_7d_plus"]["kind"] == "reforecast"
    assert by_reason["autopilot_enabled"]["kind"] == "bookkeeping"

    # Priority order: high-severity material/reforecast/postmortem groups precede
    # the info-level bookkeeping notice.
    order = [g["reason"] for g in payload["groups"]]
    assert order.index("postmortem_due") < order.index("autopilot_enabled")


def test_warnings_list_reason_filter(tmp_path, capsys):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    cli._cmd_warnings_list(_args(tmp_path, json=True, reason="postmortem"))
    payload = json.loads(capsys.readouterr().out)
    assert payload["open_total"] == 2
    assert {g["reason"] for g in payload["groups"]} == {"postmortem_due"}


def test_warnings_automode_dry_run_plans_without_writing(tmp_path, capsys):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    cli._cmd_warnings_automode(_args(tmp_path, json=True, dry_run=True, agent=False))
    payload = json.loads(capsys.readouterr().out)

    assert payload["dry_run"] is True
    assert payload["count"] == 6
    planned = {entry["alert_id"]: entry for entry in payload["plan"]}
    by_reason = {e["reason"]: e for e in payload["plan"]}

    # POSTMORTEM + MATERIAL_CHANGE always have a runner -> would_run.
    assert by_reason["postmortem_due"]["planned"] == "would_run"
    assert by_reason["watched_source_changed:src1"]["planned"] == "would_run"
    # NO_AUTO surfaced for a human.
    assert by_reason["domain_error_profile_applies:politics"]["planned"] == "surfaced"
    # REFORECAST without --agent has no runner -> would_skip (NOT bare-acked).
    assert by_reason["evidence_stale_7d_plus"]["planned"] == "would_skip"
    # BOOKKEEPING notice -> would_acknowledge.
    assert by_reason["autopilot_enabled"]["planned"] == "would_acknowledge"

    assert payload["tally"]["would_run"] == 3  # 2 postmortem + 1 material
    assert len(planned) == 6

    # The load-bearing invariant: a dry run writes NOTHING — every alert is still open.
    assert len(lg.list_alerts(unresolved_only=True)) == 6


def test_warnings_automode_dry_run_agent_enables_reforecast_runner(tmp_path, capsys):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    _seed_alerts(lg)

    cli._cmd_warnings_automode(_args(tmp_path, json=True, dry_run=True, agent=True))
    payload = json.loads(capsys.readouterr().out)
    by_reason = {e["reason"]: e for e in payload["plan"]}
    # With --agent the REFORECAST family now has a runner wired.
    assert by_reason["evidence_stale_7d_plus"]["planned"] == "would_run"
    # NO_AUTO is still surfaced regardless of --agent.
    assert by_reason["domain_error_profile_applies:politics"]["planned"] == "surfaced"
    assert len(lg.list_alerts(unresolved_only=True)) == 6  # still no writes
