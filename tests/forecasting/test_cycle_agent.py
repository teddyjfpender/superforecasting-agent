"""`forecast cycle run --agent` autonomous reforecast. The LLM itself can't run in a
test, so we stub it and assert the wiring: cron_runner SELECTS the right flagged
questions (dedup, bookkeeping excluded) and the CLI runner GATES (skip inactive /
update-gated), honors --force, and never lets one failure abort the sweep."""

from __future__ import annotations

import argparse

from forecasting import cron_runner
from forecasting.ledger import ForecastLedger


class _Alert:
    def __init__(self, scope_ref, reason):
        self.severity = "warn"
        self.scope_ref = scope_ref
        self.reason = reason
        self.recommended_action = "re-run the forecast"
        self.scope_type = "question"


def test_cron_selects_flagged_questions_excluding_bookkeeping(tmp_path, monkeypatch):
    def fake_reviews(self, **kwargs):
        return [{
            "run": {"id": "sr_1"},
            "alerts": [
                _Alert("fq_a", "stale_forecast"),
                _Alert("fq_b", "large_delta"),
                _Alert("fq_a", "stale_forecast"),         # duplicate -> deduped
                _Alert("fq_s", "score_created:sc_1"),     # bookkeeping -> excluded
                _Alert("fq_p", "postmortem_created:pm_1"),# bookkeeping -> excluded
            ],
        }]

    monkeypatch.setattr(ForecastLedger, "run_due_scheduled_reviews", fake_reviews)
    captured = {}

    def runner(ids):
        captured["ids"] = ids
        return [{"question_id": i, "status": "committed", "detail": "new snapshot x"} for i in ids]

    report = cron_runner.run_due_reviews(
        db_path=str(tmp_path / "c.db"), reforecast_runner=runner,
        thesis_aggregate=False, reconcile_alerts=False, propose_resolutions=False,
    )
    assert captured["ids"] == ["fq_a", "fq_b"]  # deduped; score_/postmortem_ excluded
    assert "Autonomous reforecast" in report
    assert "committed 2" in report


def _ledger(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "c.db"))
    lg.initialize_schema()
    return lg


def _args(tmp_path, **over):
    base = dict(db=str(tmp_path / "c.db"), model=None, provider=None, max_iterations=5, max_questions=None, force=False)
    base.update(over)
    return argparse.Namespace(**base)


def test_runner_skips_inactive_and_gated_without_invoking_agent(tmp_path, monkeypatch):
    import forecasting.cli as cli
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric exceed target by the close date?", resolution_criteria="Resolves yes if it exceeds target; otherwise no.")
    calls: list[str] = []
    monkeypatch.setattr(cli, "_run_update_agent", lambda ledger, qid, **kw: calls.append(qid) or {})
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path, force=False))
    res = {r["question_id"]: r for r in runner([q.id, "fq_missing"])}
    # a fresh question has no research/base-rate artifacts -> update stage is gated
    assert res[q.id]["status"] == "skipped" and "gated" in res[q.id]["detail"]
    assert res["fq_missing"]["status"] == "skipped"
    assert calls == []  # the agent is never invoked for a gated/invalid question


def test_force_invokes_agent_past_the_gate(tmp_path, monkeypatch):
    import forecasting.cli as cli
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Will the metric exceed target by the close date?", resolution_criteria="Resolves yes if it exceeds target; otherwise no.")
    calls: list[str] = []
    monkeypatch.setattr(cli, "_run_update_agent", lambda ledger, qid, **kw: calls.append(qid) or {})
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path, force=True))
    res = runner([q.id])
    assert calls == [q.id]  # --force bypasses the gate and invokes the agent
    # the stub committed nothing, so the runner honestly reports no new snapshot
    assert res[0]["status"] == "skipped" and "no new snapshot" in res[0]["detail"]


def test_cron_excludes_non_question_scoped_alerts(tmp_path, monkeypatch):
    class _DomainAlert(_Alert):
        def __init__(self, scope_ref, reason):
            super().__init__(scope_ref, reason)
            self.scope_type = "domain"

    def fake_reviews(self, **kwargs):
        return [{"run": {"id": "sr_1"}, "alerts": [_Alert("fq_q", "stale_forecast"), _DomainAlert("politics", "domain_drift")]}]

    monkeypatch.setattr(ForecastLedger, "run_due_scheduled_reviews", fake_reviews)
    captured = {}
    cron_runner.run_due_reviews(
        db_path=str(tmp_path / "c.db"),
        reforecast_runner=lambda ids: (captured.__setitem__("ids", ids), [])[1],
        thesis_aggregate=False, reconcile_alerts=False, propose_resolutions=False,
    )
    assert captured["ids"] == ["fq_q"]  # the domain-scoped alert is not a reforecast target


def test_max_questions_caps_processed_runs_not_just_commits(tmp_path, monkeypatch):
    import forecasting.cli as cli
    lg = _ledger(tmp_path)
    q1 = lg.create_question(title="First question that exceeds target by close?", resolution_criteria="Resolves yes if it exceeds target.")
    q2 = lg.create_question(title="Second question that exceeds target by close?", resolution_criteria="Resolves yes if it exceeds target.")
    calls: list[str] = []
    # the stub commits nothing — under a commit-counted cap it would never bite
    monkeypatch.setattr(cli, "_run_update_agent", lambda ledger, qid, **kw: calls.append(qid) or {})
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path, force=True, max_questions=1))
    res = {r["question_id"]: r for r in runner([q1.id, q2.id])}
    assert len(calls) == 1  # the cap bounds expensive LLM runs to 1, even with no commits
    assert res[q2.id]["status"] == "skipped" and "max-questions" in res[q2.id]["detail"]


def test_one_failure_does_not_abort_the_sweep(tmp_path, monkeypatch):
    import forecasting.cli as cli
    lg = _ledger(tmp_path)
    q1 = lg.create_question(title="First question that exceeds target by close?", resolution_criteria="Resolves yes if it exceeds target.")
    q2 = lg.create_question(title="Second question that exceeds target by close?", resolution_criteria="Resolves yes if it exceeds target.")

    def boom(ledger, qid, **kw):
        if qid == q1.id:
            raise RuntimeError("agent blew up")
        return {}

    monkeypatch.setattr(cli, "_run_update_agent", boom)
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path, force=True))
    res = {r["question_id"]: r for r in runner([q1.id, q2.id])}
    assert res[q1.id]["status"] == "error" and "blew up" in res[q1.id]["detail"]
    assert res[q2.id]["status"] in ("skipped", "committed")  # sweep continued past the failure
