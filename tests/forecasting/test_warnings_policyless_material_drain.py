"""Policy-less MATERIAL_CHANGE drain (the free-tier autopilot re-check bug).

THE BUG (found live): watched sources / update-triggers are attached to a question
at spec/import time WITHOUT the operator ever enabling autopilot — autopilot is a
deliberate PER-QUESTION opt-in. Those sources still emit `watched_source_changed`
alerts, which land in the FREE resolution tier. The free-tier drain routed every
one of them through `run_autopilot`, which HARD-required an active autopilot policy
and raised ``LedgerNotFoundError('active autopilot policy not found for …')``. On
the live ledger that failed 130/130 MATERIAL_CHANGE alerts across 58 policy-less
questions -> ``resolved: 0``.

The fix: the policy governs only the MATERIALITY threshold + the auto-commit MODE
(whether a change becomes a proposal / auto-commit). Resolving a source-change
alert deterministically — re-read the source, record a source-snapshot audit row,
propose/commit NOTHING — needs NO policy. So the free-drain re-check is made
policy-OPTIONAL (``run_autopilot(require_policy=False)``): conservative deterministic
behaviour with no policy, the policy consulted in full when present. The explicit
``forecast autopilot run`` path keeps ``require_policy=True`` (it SHOULD error loudly
when asked to autopilot a question with no policy).
"""

from __future__ import annotations

import pytest

from forecasting.cron_runner import run_warning_resolution
from forecasting.ledger import ForecastLedger
from forecasting.models import LedgerNotFoundError


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "drain.db"))
    lg.initialize_schema()
    return lg


def _question_with_file_watch(lg: ForecastLedger, tmp_path, name: str = "src"):
    """A question with a deterministic OFFLINE `file` watched source and a baseline
    snapshot, but NO autopilot policy — exactly the operator's live shape."""
    src = tmp_path / f"{name}.txt"
    src.write_text("baseline reading\n")
    q = lg.create_question(
        title=f"Will the {name} metric exceed target by the close date?",
        resolution_criteria="Resolves yes if it exceeds target; otherwise no.",
    )
    lg.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.4,
        rationale="prior estimate",
        require_panel=False,
    )
    watch = lg.add_watched_source(
        scope_type="question", scope_ref=q.id,
        source=str(src), source_type="file",
    )
    return q.id, watch["id"]


def test_policyless_material_alert_drains_via_deterministic_recheck(tmp_path):
    """RED-then-GREEN: a `watched_source_changed` alert on a policy-LESS question
    RESOLVES through a deterministic, zero-spend source re-check — no policy needed,
    no proposal / auto-commit created."""
    lg = _ledger(tmp_path)
    qid, watch_id = _question_with_file_watch(lg, tmp_path)
    alert_id = lg.create_alert(
        severity="info", scope_type="question", scope_ref=qid,
        reason=f"watched_source_changed:{watch_id}",
        recommended_action="Recheck the source.").id

    # sanity: the question genuinely has NO active autopilot policy.
    assert lg.list_autopilot_policies(question_id=qid, enabled_only=True) == []

    summary = run_warning_resolution(ledger=lg, tier="free", reconcile=False)

    by_id = {r["alert_id"]: r for r in summary["results"]}
    # GREEN: the drain resolved it (was: failed with LedgerNotFoundError).
    assert by_id[alert_id]["status"] == "resolved"
    assert summary["tally"].get("resolved") == 1
    assert not summary.get("failures")  # no uniform crash fold
    # The alert is acked (no longer open).
    assert alert_id not in {a.id for a in lg.list_alerts(unresolved_only=True)}
    # REAL WORK, NOT A BARE ACK: a source-snapshot audit row was recorded.
    assert len(lg.list_source_snapshots(watched_source_id=watch_id)) >= 1
    # CONSERVATIVE: no policy => no proposal, no autopilot_run, no forecast move.
    assert lg.list_autopilot_runs(question_id=qid) == []
    assert lg.list_forecast_update_proposals(question_id=qid) == []


def test_policyless_recheck_never_bare_acks_when_no_watch_remains(tmp_path):
    """Fail-SOFT, never a crash: a material-change alert whose watched source was
    removed records NO source snapshot -> left OPEN and folded into failures[], but
    the sweep completes cleanly (no LedgerNotFoundError storm)."""
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the orphaned metric exceed target?",
        resolution_criteria="Resolves yes if it exceeds target; otherwise no.",
    )
    # A material-change alert whose watch id no longer exists (source removed).
    alert_id = lg.create_alert(
        severity="info", scope_type="question", scope_ref=q.id,
        reason="watched_source_changed:ws_gone",
        recommended_action="Recheck the source.").id

    summary = run_warning_resolution(ledger=lg, tier="free", reconcile=False)

    by_id = {r["alert_id"]: r for r in summary["results"]}
    assert by_id[alert_id]["status"] == "failed"  # no real work -> never bare-acked
    assert alert_id in {a.id for a in lg.list_alerts(unresolved_only=True)}
    # Fail-soft surface: a folded skip-reason, NOT a per-alert crash storm.
    assert summary["failures"]  # non-empty fold


def test_explicit_run_autopilot_still_requires_a_policy(tmp_path):
    """Behaviour unchanged for the explicit path: `run_autopilot` (require_policy
    default True) STILL raises for a policy-less question, so `forecast autopilot
    run <q>` errors loudly instead of silently degrading."""
    lg = _ledger(tmp_path)
    qid, _watch = _question_with_file_watch(lg, tmp_path, name="explicit")

    with pytest.raises(LedgerNotFoundError):
        lg.run_autopilot(qid)


def test_policy_present_behaviour_unchanged(tmp_path):
    """A question WITH an active policy runs the FULL autopilot machinery through the
    drain (records an autopilot_run) — the policy path is untouched by the fix."""
    lg = _ledger(tmp_path)
    qid, watch_id = _question_with_file_watch(lg, tmp_path, name="policied")
    lg.enable_autopilot(
        question_id=qid,
        sources=[str(tmp_path / "policied.txt")],
        cadence="P7D",
        mode="alert_only",
        allow_missing_resolution_source=True,
    )
    lg.create_alert(
        severity="info", scope_type="question", scope_ref=qid,
        reason=f"watched_source_changed:{watch_id}",
        recommended_action="Recheck the source.")

    run_warning_resolution(ledger=lg, tier="free", reconcile=False)

    # The full policy path ran: an autopilot_run was recorded (policy-less path
    # records none), proving the material alert used the policy machinery.
    assert lg.list_autopilot_runs(question_id=qid) != []
