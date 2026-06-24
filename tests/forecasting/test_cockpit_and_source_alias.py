"""The user's top-3 deliverable commands: `forecast source add --role ...` (an
alias for `watch`, matching the feedback's vocabulary) and `forecast calibration
status` (the readiness cockpit that makes claim_live_superforecasting actionable)."""

from __future__ import annotations

from forecasting import cli
from forecasting.ledger import ForecastLedger

CRIT = "Resolves yes if the reported value exceeds the threshold at the close date."


def test_source_is_an_alias_for_watch(tmp_path, capsys):
    db = str(tmp_path / "a.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()
    q = lg.create_question(title="Will X exceed Y by close?", resolution_criteria=CRIT)
    cli.main(["--db", db, "source", "add", "https://x/feed.rss", "--question", q.id, "--source-type", "rss", "--role", "resolver"])
    out = capsys.readouterr().out
    assert "role: resolver" in out
    # the alias actually persisted via the same path as `watch`
    sources = lg.list_watched_sources(scope_type="question", scope_ref=q.id)
    assert sources and sources[0]["role"] == "resolver"


def test_calibration_status_prints_actionable_cockpit(tmp_path, capsys):
    db = str(tmp_path / "c.db")
    ForecastLedger(db_path=db).initialize_schema()
    cli.main(["--db", db, "calibration", "status"])
    out = capsys.readouterr().out
    assert "calibration / readiness cockpit" in out
    assert "claim_live_superforecasting" in out
    # actionable: it surfaces the readiness requirements/gaps, not just a number
    assert "live_scored" in out


def test_bare_calibration_still_works(tmp_path, capsys):
    db = str(tmp_path / "b.db")
    ForecastLedger(db_path=db).initialize_schema()
    cli.main(["--db", db, "calibration"])
    out = capsys.readouterr().out
    assert "count:" in out  # the existing summary view, unbroken
