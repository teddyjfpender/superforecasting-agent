"""Auto-reforecast COMMIT policy: ``forecast refresh <id> --agent`` (and the
``cycle run --agent`` sweep) must COMMIT a material move, not stop at a preview.

The bug this pins: the live reforecasts conflated the decision-card ACTION
threshold ("act if P>=0.65") with the forecast-UPDATE commit decision, so the
agent sharpened 46%->56% then reported "No snapshot has been committed". The fix
is twofold — (1) the update-stage prompt grows an explicit commit-material policy
that separates the two, and (2) the cron reforecast runner classifies a committed
snapshot by MATERIALITY (|Δp| >= 3pp for a binary) and counts a material-move
commit as success. The LLM can't run in a test, so we stub it and drive the
materiality decision the prompt instructs the real agent to make."""

from __future__ import annotations

import argparse

from forecasting.ledger import ForecastLedger
from forecasting.protocol import _stage_task
from forecasting.warnings import MATERIAL_MOVE_THRESHOLD, is_material_move


# ---------------------------------------------------------------------------
# is_material_move — the shared materiality threshold
# ---------------------------------------------------------------------------

def test_material_move_threshold_for_binary():
    # 46% -> 56% is a 10pp move: material.
    assert is_material_move(0.46, 0.56) is True
    # 46% -> 47% is 1pp: marginal.
    assert is_material_move(0.46, 0.47) is False
    # exactly at the threshold counts as material.
    assert is_material_move(0.50, 0.50 + MATERIAL_MOVE_THRESHOLD) is True
    # just under does not.
    assert is_material_move(0.50, 0.50 + MATERIAL_MOVE_THRESHOLD - 1e-6) is False


def test_material_move_no_prior_or_distribution_is_material():
    # a genuinely first forecast (no comparable prior scalar) is always worth recording.
    assert is_material_move(None, 0.42) is True
    # a distribution that actually changed is material; an identical one is not.
    assert is_material_move({"a": 0.5, "b": 0.5}, {"a": 0.6, "b": 0.4}) is True
    assert is_material_move({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) is False
    # a true no-op (same scalar) is not material.
    assert is_material_move(0.5, 0.5) is False


# ---------------------------------------------------------------------------
# the update-stage prompt carries the commit-material policy only when asked
# ---------------------------------------------------------------------------

def test_commit_material_policy_only_under_autonomous_policy():
    interactive = _stage_task("update")
    autonomous = _stage_task("update", commit_policy="commit_material")
    assert "COMMIT POLICY" not in interactive  # interactive keeps recommend-and-preview
    assert "COMMIT POLICY" in autonomous
    # the bright line: forecast-UPDATE commit is separate from the ACTION threshold.
    assert "SEPARATE decision from recommending decision-card ACTION" in autonomous
    assert "MATERIAL move" in autonomous and "MARGINAL" in autonomous


# ---------------------------------------------------------------------------
# the cron reforecast runner classifies the commit by materiality
# ---------------------------------------------------------------------------

def _ledger(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "c.db"))
    lg.initialize_schema()
    return lg


def _args(tmp_path, **over):
    base = dict(
        db=str(tmp_path / "c.db"), model=None, provider=None,
        max_iterations=5, max_questions=None, force=True,
    )
    base.update(over)
    return argparse.Namespace(**base)


def _seed_with_prior(lg, prior_prob):
    q = lg.create_question(
        title="Will the metric exceed target by the close date?",
        resolution_criteria="Resolves yes if it exceeds target; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=prior_prob,
        rationale="Prior estimate.",
        as_of="2026-05-01T00:00:00Z",
        confidence=0.55,
        method="weighted_ensemble",
    )
    return q


def _policy_stub(target_prob):
    """A stand-in for the LLM update stage that follows the commit-material policy:
    it commits a fresh snapshot ONLY when ``target_prob`` is a material move versus
    the current snapshot (exactly what the prompt instructs the real agent to do)."""

    def _stub(ledger, qid, **kw):
        # the autonomous paths must hand the agent the commit-material policy.
        assert kw.get("commit_policy") == "commit_material"
        current = ledger.get_current_snapshot(qid)
        prior_p = current.probability_or_distribution if current is not None else None
        if is_material_move(prior_p, target_prob):
            ledger.create_snapshot(
                question_id=qid,
                probability_or_distribution=target_prob,
                rationale="Re-reasoned on fresh evidence.",
                as_of="2026-05-08T00:00:00Z",
                confidence=0.6,
                method="weighted_ensemble",
            )
        return {}

    return _stub


def test_material_move_reforecast_commits_a_snapshot(tmp_path, monkeypatch):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _seed_with_prior(lg, 0.46)
    before = lg.get_current_snapshot(q.id).forecast_id

    monkeypatch.setattr(cli, "_run_update_agent", _policy_stub(0.56))
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path))
    res = {r["question_id"]: r for r in runner([q.id])}

    after = lg.get_current_snapshot(q.id)
    assert after.forecast_id != before  # a new snapshot was committed
    assert abs(float(after.probability_or_distribution) - 0.56) < 1e-9
    assert res[q.id]["status"] == "committed"
    assert "marginal" not in res[q.id]["detail"]
    assert "+0.100" in res[q.id]["detail"]  # the delta is surfaced honestly


def test_marginal_move_reforecast_does_not_commit(tmp_path, monkeypatch):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _seed_with_prior(lg, 0.46)
    before = lg.get_current_snapshot(q.id).forecast_id

    monkeypatch.setattr(cli, "_run_update_agent", _policy_stub(0.47))  # 1pp: marginal
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path))
    res = {r["question_id"]: r for r in runner([q.id])}

    after = lg.get_current_snapshot(q.id)
    assert after.forecast_id == before  # no new snapshot — marginal stays preview
    assert res[q.id]["status"] == "skipped"
    assert "no new snapshot" in res[q.id]["detail"]


def _always_commit_stub(target_prob):
    """A stand-in for an agent that slips the commit-material policy: it commits a
    fresh snapshot UNCONDITIONALLY, even for a marginal move. Used to pin that the
    runner REPORTS such a commit honestly as 'marginal' rather than tallying it as a
    material-move success."""

    def _stub(ledger, qid, **kw):
        assert kw.get("commit_policy") == "commit_material"
        ledger.create_snapshot(
            question_id=qid,
            probability_or_distribution=target_prob,
            rationale="Re-reasoned; committed despite a marginal move.",
            as_of="2026-05-08T00:00:00Z",
            confidence=0.6,
            method="weighted_ensemble",
        )
        return {}

    return _stub


def test_marginal_delta_commit_is_reported_as_marginal_not_material_success(tmp_path, monkeypatch):
    """If the agent commits anyway on a MARGINAL delta (slipping the prompt policy),
    the runner must classify the result HONESTLY as status 'marginal' — NOT tally it
    as a 'committed' material-move success — so the sweep's status counts stay
    truthful. A snapshot did land (so it is not 'skipped'), but it is not material."""
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _seed_with_prior(lg, 0.46)
    before = lg.get_current_snapshot(q.id).forecast_id

    monkeypatch.setattr(cli, "_run_update_agent", _always_commit_stub(0.47))  # 1pp commit
    runner = cli._build_cycle_reforecast_runner(_args(tmp_path))
    res = {r["question_id"]: r for r in runner([q.id])}

    after = lg.get_current_snapshot(q.id)
    assert after.forecast_id != before                 # a new snapshot DID land
    assert res[q.id]["status"] == "marginal"           # …but reported honestly, not "committed"
    assert "MARGINAL" in res[q.id]["detail"]
    assert "+0.010" in res[q.id]["detail"]             # the sub-threshold delta is surfaced
