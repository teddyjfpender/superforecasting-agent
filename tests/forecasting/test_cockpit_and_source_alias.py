"""The user's top-3 deliverable commands: `forecast source add --role ...` (an
alias for `watch`, matching the feedback's vocabulary) and `forecast calibration
status` (the readiness cockpit that makes claim_live_superforecasting actionable)."""

from __future__ import annotations

from forecasting import cli
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace

CRIT = "Resolves yes if the reported value exceeds the threshold at the close date."
DCRIT = "Resolves to the official value reported by the named source on the close date."


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


def test_thesis_show_sensitivity_explainability(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    lg = ForecastLedger(db_path=db)
    lg.initialize_schema()

    def dist_member(title, mean):
        q = lg.create_question(title=title, resolution_criteria=DCRIT, outcome_space=OutcomeSpace(type="distribution", units="x"))
        lg.create_snapshot(question_id=q.id, probability_or_distribution={"mean": mean, "sd": 0.15, "q05": mean - 0.25, "q50": mean, "q95": mean + 0.25}, rationale="x")
        return q

    a, b, c = dist_member("Compute member?", 0.6), dist_member("GPU member?", 0.55), dist_member("Power member?", 0.5)
    th = lg.create_question(title="Infra scarcity thesis", resolution_criteria="Aggregate health of tagged members; reviewed as they update.", outcome_space=OutcomeSpace(type="thesis"))
    for m in (a, b, c):
        lg.add_thesis_member(th.id, m.id, direction="support", weight=1.0, target=0.5)

    cli.main(["--db", db, "thesis", "show", th.id, "--sensitivity"])
    out = capsys.readouterr().out
    assert "EXPLAINABILITY" in out
    assert "biggest movers" in out
    # correlation sensitivity sweeps rho and shows the band depends on it
    assert "correlation sensitivity" in out
    assert "rho=0.0" in out and "rho=0.8" in out


def test_bare_calibration_still_works(tmp_path, capsys):
    db = str(tmp_path / "b.db")
    ForecastLedger(db_path=db).initialize_schema()
    cli.main(["--db", db, "calibration"])
    out = capsys.readouterr().out
    assert "count:" in out  # the existing summary view, unbroken
