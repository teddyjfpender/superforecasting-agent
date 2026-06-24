"""The dedicated thesis dashboard surface: build_thesis_summary feeds the CLI
`thesis dashboard`, the `thesis_dashboard` tool action, and the gateway
`forecast.theses` RPC — a standalone thesis master list, no full forecast workspace."""

from __future__ import annotations

import argparse
import json

from forecasting.dashboard import build_thesis_summary
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

THCRIT = "Resolves from the aggregate health of its tagged member forecasts at the close date."


def _ledger_with_thesis(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "t.db"))
    lg.initialize_schema()
    th = lg.create_question(
        title="AI infrastructure scarcity thesis holds through year end?",
        resolution_criteria=THCRIT, domain="markets",
        outcome_space=OutcomeSpace(type="thesis"),
    )
    member = lg.create_question(title="Does GPU supply stay tight through Q4?", resolution_criteria="Resolves yes if supply stays tight.")
    lg.add_thesis_member(th.id, member.id, direction="support", weight=1.0)
    return lg, th


def test_build_thesis_summary_lists_active_theses(tmp_path):
    lg, th = _ledger_with_thesis(tmp_path)
    rows = build_thesis_summary(ledger=lg)
    assert [r["id"] for r in rows] == [th.id]
    row = rows[0]
    assert row["member_count"] == 1
    assert row["status"] in ("ok", "withheld")  # withheld until aggregated (health None)
    assert "health_display" in row and "thesis_score" in row


def test_thesis_dashboard_tool_action(tmp_path):
    lg, th = _ledger_with_thesis(tmp_path)
    from tools.forecasting_tool import forecast_ledger_tool

    r = json.loads(forecast_ledger_tool({"action": "thesis_dashboard", "db": str(tmp_path / "t.db")}))
    assert r["success"] is True
    assert [t["id"] for t in r["theses"]] == [th.id]
    assert "factors" in r


def test_cli_thesis_dashboard_json(tmp_path, capsys):
    from forecasting.cli import _cmd_thesis_dashboard

    lg, th = _ledger_with_thesis(tmp_path)
    _cmd_thesis_dashboard(argparse.Namespace(db=str(tmp_path / "t.db"), json=True))
    data = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in data] == [th.id]


def test_cli_thesis_dashboard_table_renders(tmp_path, capsys):
    from forecasting.cli import _cmd_thesis_dashboard

    lg, th = _ledger_with_thesis(tmp_path)
    _cmd_thesis_dashboard(argparse.Namespace(db=str(tmp_path / "t.db"), json=False))
    out = capsys.readouterr().out
    assert "thesis" in out and "health" in out  # header
    assert th.title[:20] in out
