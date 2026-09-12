"""Tests for contested-label routing (the L8 trick) + operator hand-labeling."""

from __future__ import annotations

import json

import pytest

from forecasting import warnings as fwarn
from forecasting.ledger import ForecastLedger
from forecasting.warnings import (
    AGGREGATE_TIER_FOR_KIND,
    WARNING_TIERS,
    ResolutionKind,
    ResolutionRunners,
    classify_warning,
    resolve_alert,
    select_open_warnings,
)


# ── warnings classification ────────────────────────────────────────────────


def test_contested_label_classification():
    assert classify_warning("contested_label:tl_abc123") is ResolutionKind.CONTESTED_LABEL
    assert classify_warning("contested_label") is ResolutionKind.CONTESTED_LABEL


def test_contested_label_is_manual_tier():
    assert AGGREGATE_TIER_FOR_KIND[ResolutionKind.CONTESTED_LABEL] == "manual"


def test_contested_label_not_in_any_sweep_tier():
    # The whole point: no automode sweep ever selects a contested label.
    for kinds in WARNING_TIERS.values():
        assert ResolutionKind.CONTESTED_LABEL not in kinds


def test_contested_label_surfaced_never_acked():
    led = _Recorder()
    alert = _FakeAlert(reason="contested_label:tl_1")
    result = resolve_alert(led, alert, runners=ResolutionRunners())
    assert result["status"] == "surfaced"
    assert result["acknowledged"] is False
    assert led.acknowledged == []  # never bare-acked


class _FakeAlert:
    def __init__(self, reason):
        self.id = "al_fake"
        self.created_at = "2026-06-30T00:00:00Z"
        self.severity = "warning"
        self.scope_type = "question"
        self.scope_ref = "q1"
        self.reason = reason
        self.recommended_action = "hand-label"
        self.last_attempted_at = None
        self.attempt_count = 0


class _Recorder:
    def __init__(self):
        self.acknowledged = []

    def acknowledge_alert(self, alert_id, *, acknowledged_at=None):
        self.acknowledged.append(alert_id)


# ── the contested → relabel loop ────────────────────────────────────────────


@pytest.fixture
def ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "contested.db"))


def _seed_auto_rows(ledger):
    return ledger.record_triage_labels(
        question_id="q1",
        verdicts=[
            {"triage_label": "relevant_interesting", "title": "clear keep", "candidate_ref": "A", "relevance": 0.95, "materiality": "high"},
            {"triage_label": "relevant_uninteresting", "title": "boundary", "candidate_ref": "B", "relevance": 0.5, "materiality": "medium"},
            {"triage_label": "irrelevant", "title": "high-mat but irrelevant", "candidate_ref": "C", "relevance": 0.92, "materiality": "high"},
            {"triage_label": "irrelevant", "title": "clear skip", "candidate_ref": "D", "relevance": 0.04, "materiality": "low"},
        ],
    )


def _tool():
    from tools.forecasting_tool import forecast_ledger_tool

    return forecast_ledger_tool


def test_triage_contested_heuristic_flags_boundary_and_conflict(ledger, tmp_path):
    _seed_auto_rows(ledger)
    out = _tool()({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"})
    payload = json.loads(out)
    assert payload["success"] is True
    # B (boundary) and C (high-materiality but irrelevant) are contested; A and D agree.
    titles = {c["title"] for c in payload["contested"]}
    assert titles == {"boundary", "high-mat but irrelevant"}
    assert payload["agreed_count"] == 2
    assert len(payload["opened_alerts"]) == 2
    # the contested rows are marked + linked to an alert
    for c in payload["contested"]:
        assert c["contested"] is True
        assert c["alert_id"]


def test_triage_contested_verifier_path(ledger):
    rows = _seed_auto_rows(ledger)
    # verifier disagrees only on candidate A (auto=relevant_interesting -> verifier irrelevant)
    out = _tool()(
        {
            "action": "triage_contested",
            "db": ledger.db_path,
            "question_id": "q1",
            "verifier_labels": [
                {"candidate_ref": "A", "label": "irrelevant"},
                {"candidate_ref": "B", "label": "relevant_uninteresting"},
            ],
        }
    )
    payload = json.loads(out)
    assert payload["contested_count"] == 1
    assert payload["contested"][0]["candidate_ref"] == "A"
    assert "verifier said irrelevant" in payload["contested"][0]["contested_reason"]


def test_contested_alert_surfaces_as_open_manual_warning(ledger):
    _seed_auto_rows(ledger)
    _tool()({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"})
    open_warnings = select_open_warnings(ledger)
    contested = [w for w in open_warnings if w.kind is ResolutionKind.CONTESTED_LABEL]
    assert len(contested) == 2
    assert all(not w.is_auto_resolvable for w in contested)


def test_relabel_route_records_expert_and_acks(ledger):
    _seed_auto_rows(ledger)
    contested_out = json.loads(
        _tool()({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"})
    )
    target = contested_out["contested"][0]
    alert_id = target["alert_id"]

    relabel_out = json.loads(
        _tool()(
            {
                "action": "relabel_route",
                "db": ledger.db_path,
                "label_id": target["id"],
                "label": "relevant_interesting",
            }
        )
    )
    assert relabel_out["count"] == 1
    row = relabel_out["relabeled"][0]
    assert row["expert_label"] == "relevant_interesting"
    assert row["triage_label"] == "relevant_interesting"
    assert row["label_source"] == "expert"
    assert row["contested"] is False
    assert row["adjudicated_at"]

    # the linked alert is now acknowledged (real work done — not a bare ack)
    remaining = [w for w in select_open_warnings(ledger) if w.id == alert_id]
    assert remaining == []


def test_relabel_route_batch(ledger):
    rows = _seed_auto_rows(ledger)
    out = json.loads(
        _tool()(
            {
                "action": "relabel_route",
                "db": ledger.db_path,
                "adjudications": [
                    {"label_id": rows[0]["id"], "label": "irrelevant"},
                    {"label_id": rows[1]["id"], "label": "relevant_interesting"},
                ],
            }
        )
    )
    assert out["count"] == 2
    by_id = {r["id"]: r for r in out["relabeled"]}
    assert by_id[rows[0]["id"]]["expert_label"] == "irrelevant"
    assert by_id[rows[1]["id"]]["verdict"] == "keep"


def test_relabel_route_requires_target(ledger):
    out = json.loads(_tool()({"action": "relabel_route", "db": ledger.db_path}))
    assert out.get("error")
    assert "label_id" in out["error"]


def test_reconcile_never_acks_a_contested_label_alert(tmp_path):
    """A question-scoped contested_label alert must survive reconcile even when
    fresh evidence + a newer snapshot land — it is closed ONLY by relabel_route."""
    import time

    crit = "Resolves yes if the reported value exceeds the stated threshold at close."
    lg = ForecastLedger(db_path=str(tmp_path / "rec.db"))
    q = lg.create_question(title="Will the metric exceed target by close?", resolution_criteria=crit)
    # a contested_label alert scoped to the question (the dangerous case)
    contested_alert = lg.create_alert(
        severity="warning", scope_type="question", scope_ref=q.id,
        reason="contested_label:tl_abc", recommended_action="hand-label",
    )
    # a watched-source alert that SHOULD reconcile, as a control
    control = lg.create_alert(
        severity="info", scope_type="question", scope_ref=q.id,
        reason="watched_source_changed:w1", recommended_action="review",
    )

    time.sleep(1.1)  # evidence + snapshot land strictly after the alerts
    lg.add_evidence(question_id=q.id, source_or_note="post-alert read", claim="value moved")
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="updated after change")

    result = lg.reconcile_alerts()
    reconciled_ids = [e["id"] for e in result["reconciled"]]
    assert control.id in reconciled_ids  # the control was consumed -> acked
    assert contested_alert.id not in reconciled_ids  # the contested label was NOT
    still_open_ids = [a.id for a in lg.list_alerts(unresolved_only=True)]
    assert contested_alert.id in still_open_ids


@pytest.mark.parametrize("stage", ["contest", "adjudicate"])
@pytest.mark.parametrize("failure", [ValueError("injected persistence failure"), KeyboardInterrupt()])
def test_triage_coupled_writes_roll_back_on_failure(ledger, monkeypatch, stage, failure):
    def dispatch(payload):
        if isinstance(failure, KeyboardInterrupt):
            with pytest.raises(KeyboardInterrupt):
                _tool()(payload)
            return {"success": False}
        return json.loads(_tool()(payload))

    _seed_auto_rows(ledger)
    if stage == "contest":
        before = ledger.list_triage_labels(question_id="q1")
        original = ForecastLedger.update_triage_label
        def fail(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise failure
        monkeypatch.setattr(ForecastLedger, "update_triage_label", fail)
        result = dispatch({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"})
        assert result["success"] is False
        assert ledger.list_triage_labels(question_id="q1") == before
        assert select_open_warnings(ledger) == []
        monkeypatch.setattr(ForecastLedger, "update_triage_label", original)
        for _ in range(2):
            retry = json.loads(_tool()({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"}))
            assert retry["success"] is True
        assert len(select_open_warnings(ledger)) == 2
    else:
        result = json.loads(_tool()({"action": "triage_contested", "db": ledger.db_path, "question_id": "q1"}))
        target = result["contested"][0]
        before = ledger.get_triage_label(target["id"])
        original = ForecastLedger.acknowledge_alert
        def fail(self, *args, **kwargs):
            original(self, *args, **kwargs)
            raise failure
        monkeypatch.setattr(ForecastLedger, "acknowledge_alert", fail)
        result = dispatch({"action": "relabel_route", "db": ledger.db_path, "label_id": target["id"], "label": "relevant_interesting"})
        assert result["success"] is False
        assert ledger.get_triage_label(target["id"]) == before
        assert ledger.get_alert(target["alert_id"]).acknowledged_at is None

        monkeypatch.setattr(ForecastLedger, "acknowledge_alert", original)
        retry = json.loads(_tool()({"action": "relabel_route", "db": ledger.db_path, "label_id": target["id"], "label": "relevant_interesting"}))
        assert retry["success"] is True
        assert ledger.get_triage_label(target["id"])["label_source"] == "expert"
        assert ledger.get_alert(target["alert_id"]).acknowledged_at
