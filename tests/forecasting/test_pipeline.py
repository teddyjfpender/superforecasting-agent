"""Tests for the guided forecasting-loop pipeline driver.

The pipeline sequences a question through parse -> research -> base_rate ->
model -> update -> resolve -> postmortem. It is a GUIDE: it reports which
stages are satisfied (from ledger artifacts) and refuses to *advance* to a
stage whose prerequisites are unmet (the keystone being: no commit before an
outside view + evidence exist). The raw `forecast update` and per-stage
commands stay free.
"""

from __future__ import annotations

import argparse
import json

import pytest

from forecasting import ForecastLedger
from forecasting.cli import register_cli
from forecasting.protocol import (
    build_pipeline_status,
    pipeline_advance_block,
)
from tools.forecasting_tool import forecast_ledger_tool


# ── helpers ─────────────────────────────────────────────────────────────────


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "pipeline.db"))
    ledger.initialize_schema()
    return ledger


def _question(ledger, **overrides):
    defaults = dict(
        title="Will CPI YoY be below 3.0% for the July 2026 release?",
        resolution_criteria="Resolves yes if BLS CPI-U YoY for the July 2026 release is below 3.0%; otherwise no.",
    )
    defaults.update(overrides)
    return ledger.create_question(**defaults)


def _research(ledger, qid):
    ledger.add_evidence(
        question_id=qid,
        source_or_note="BLS CPI release schedule and prior prints",
        available_at="2026-01-01T00:00:00Z",
    )


def _base_rate(ledger, qid):
    ledger.add_reference_class(
        question_id=qid,
        name="Recent CPI prints",
        inclusion_criteria="last 12 monthly YoY prints",
        base_rate=0.4,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forecast-test")
    sub = parser.add_subparsers(dest="command")
    register_cli(sub)
    return parser


def _stage(status, name):
    return next(entry for entry in status["stages"] if entry["stage"] == name)


# ── build_pipeline_status ───────────────────────────────────────────────────


def test_pipeline_status_fresh_question_blocks_update(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    status = build_pipeline_status(ledger, q.id)

    assert status["update_ready"] is False
    assert set(status["update_blockers"]) == {"research", "base_rate"}
    assert _stage(status, "research")["status"] == "ready"
    assert _stage(status, "base_rate")["status"] == "ready"
    assert _stage(status, "update")["status"] == "blocked"
    assert _stage(status, "model")["status"] == "optional"
    # Later stages chain off update.
    assert _stage(status, "resolve")["status"] == "blocked"
    assert _stage(status, "postmortem")["status"] == "blocked"


def test_pipeline_status_research_and_base_rate_unlock_update(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    status = build_pipeline_status(ledger, q.id)

    assert status["update_ready"] is True
    assert status["update_blockers"] == []
    assert _stage(status, "research")["status"] == "done"
    assert _stage(status, "base_rate")["status"] == "done"
    assert _stage(status, "update")["status"] == "ready"


def test_pipeline_status_marks_committed_and_resolved_stages_done(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.45,
        rationale="committed forecast",
        require_panel=False,
    )
    status = build_pipeline_status(ledger, q.id)
    assert _stage(status, "update")["status"] == "done"
    assert _stage(status, "resolve")["status"] == "ready"

    ledger.resolve_question(question_id=q.id, outcome="yes")
    status = build_pipeline_status(ledger, q.id)
    assert _stage(status, "resolve")["status"] == "done"
    assert _stage(status, "postmortem")["status"] == "ready"


def test_pipeline_status_parse_done_when_decision_card_complete(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(
        ledger,
        decision_owner="desk",
        action_threshold="hedge if p>0.6",
        update_triggers=[{"mechanism": "new CPI print", "threshold": "monthly"}],
    )
    status = build_pipeline_status(ledger, q.id)
    assert _stage(status, "parse")["status"] == "done"
    assert status["decision_readiness_issues"] == []


# ── pipeline_advance_block ──────────────────────────────────────────────────


def test_advance_block_refuses_update_without_research_and_base_rate(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    status = build_pipeline_status(ledger, q.id)
    block = pipeline_advance_block(status, "update")
    assert block is not None
    assert "research" in block and "base_rate" in block


def test_advance_block_allows_update_once_prerequisites_met(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    status = build_pipeline_status(ledger, q.id)
    assert pipeline_advance_block(status, "update") is None


def test_advance_block_refuses_resolve_before_update(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    status = build_pipeline_status(ledger, q.id)
    block = pipeline_advance_block(status, "resolve")
    assert block is not None
    assert "update" in block


def test_advance_block_does_not_gate_early_stages(tmp_path):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    status = build_pipeline_status(ledger, q.id)
    # research / base_rate have no prerequisites — never blocked by the pipeline.
    assert pipeline_advance_block(status, "research") is None
    assert pipeline_advance_block(status, "base_rate") is None


# ── CLI: forecast pipeline ──────────────────────────────────────────────────


def test_cli_pipeline_overview_reports_blockers(tmp_path, capsys):
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    parser = _parser()
    args = parser.parse_args(["forecast", "--db", str(tmp_path / "pipeline.db"), "pipeline", q.id])
    args.func(args)
    out = capsys.readouterr().out
    assert "update_ready: False" in out
    assert "update_blocked_by: research, base_rate" in out
    assert "research" in out


def test_cli_pipeline_advance_to_update_refused_then_allowed(tmp_path, capsys):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    parser = _parser()

    with pytest.raises(SystemExit):
        a = parser.parse_args(["forecast", "--db", db, "pipeline", q.id, "--stage", "update"])
        a.func(a)
    assert "will not advance to 'update'" in capsys.readouterr().err

    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    a = parser.parse_args(["forecast", "--db", db, "pipeline", q.id, "--stage", "update"])
    a.func(a)
    out = capsys.readouterr().out
    assert "## system" in out
    assert "## user" in out


def test_cli_pipeline_force_bypasses_gate(tmp_path, capsys):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    parser = _parser()
    a = parser.parse_args(
        ["forecast", "--db", db, "pipeline", q.id, "--stage", "update", "--force"]
    )
    a.func(a)
    out = capsys.readouterr().out
    assert "## system" in out


def test_cli_pipeline_json_output(tmp_path, capsys):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    parser = _parser()
    a = parser.parse_args(["forecast", "--db", db, "pipeline", q.id, "--json"])
    a.func(a)
    data = json.loads(capsys.readouterr().out)
    assert data["question_id"] == q.id
    assert data["update_ready"] is False
    assert {s["stage"] for s in data["stages"]} >= {"research", "base_rate", "update"}


# ── agent tool: action="pipeline" ───────────────────────────────────────────


def test_tool_pipeline_returns_status(tmp_path):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    out = json.loads(forecast_ledger_tool({"db": db, "action": "pipeline", "question_id": q.id}))
    assert out["success"] is True
    assert out["pipeline"]["update_ready"] is False
    assert set(out["pipeline"]["update_blockers"]) == {"research", "base_rate"}


def test_tool_pipeline_stage_refused_until_prerequisites(tmp_path):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    refused = json.loads(
        forecast_ledger_tool(
            {"db": db, "action": "pipeline", "question_id": q.id, "stage": "update"}
        )
    )
    assert refused["success"] is False
    assert "will not advance" in refused["error"]

    _research(ledger, q.id)
    _base_rate(ledger, q.id)
    allowed = json.loads(
        forecast_ledger_tool(
            {"db": db, "action": "pipeline", "question_id": q.id, "stage": "update"}
        )
    )
    assert allowed["success"] is True
    assert allowed["stage"] == "update"
    assert allowed["messages"]


def test_tool_pipeline_force_bypasses_gate(tmp_path):
    db = str(tmp_path / "pipeline.db")
    ledger = _ledger(tmp_path)
    q = _question(ledger)
    out = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "pipeline",
                "question_id": q.id,
                "stage": "update",
                "force": True,
            }
        )
    )
    assert out["success"] is True
    assert out["messages"]
