"""Pure provenance plans and transactional revalidation of stale previews."""

import json
from dataclasses import FrozenInstanceError

import pytest

from forecasting.application.source_batches import commit_source_payloads, SourceRevisionConflict
from forecasting.application.source_plans import prepare_source_import
from forecasting.ledger import ForecastLedger


def row(value=1):
    return {"source_or_note": "source", "source_type": "adapter:fred", "metadata": {"entry_id": "x", "adapter_item": {"value": value}}}


def test_plan_reports_duplicates_and_revisions_without_persistence():
    plan = prepare_source_import([row(), row(), row(2)])
    assert [item.disposition for item in plan.rows] == ["accepted", "duplicate", "rejected"]
    assert [item.reason_code for item in plan.rows] == ["new_observation", "exact_duplicate", "source_revision_conflict"]
    assert plan.rows[2].index == 2
    assert plan.rows[2].entry_id == "x"


def test_snapshot_and_decisions_do_not_follow_caller_mutation():
    source = row()
    plan = prepare_source_import([source])
    source["metadata"]["adapter_item"]["value"] = 2
    assert json.loads(plan.payload_json)[0]["metadata"]["adapter_item"]["value"] == 1
    assert plan.digest == prepare_source_import([row()]).digest
    assert plan.digest != prepare_source_import([source]).digest
    with pytest.raises(FrozenInstanceError):
        plan.digest = "changed"


def test_explicit_revision_append_policy_and_missing_publication():
    plan = prepare_source_import([row(), row(2)], dedupe=False)
    assert all(item.disposition == "accepted" for item in plan.rows)
    assert "published_at" not in json.loads(plan.payload_json)[0]


def test_stale_preview_cannot_authorize_conflicting_commit(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecast.db")
    question = ledger.create_question(title="Plan race", resolution_criteria="Resolves yes if the observation is published.")
    preview = prepare_source_import([row()])
    assert preview.rows[0].disposition == "accepted"
    commit_source_payloads(ledger, question.id, [row(2)])
    current = prepare_source_import([row()], ledger.list_evidence(question.id))
    assert current.rows[0].reason_code == "source_revision_conflict"
    with pytest.raises(SourceRevisionConflict):
        commit_source_payloads(ledger, question.id, json.loads(preview.payload_json))
    assert len(ledger.list_evidence(question.id)) == 1


def test_changed_revision_is_rejected_before_first_write(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "forecast.db")
    question = ledger.create_question(title="No writes", resolution_criteria="Resolves yes if the observation is published.")
    def forbidden(*args, **kwargs):
        pytest.fail("conflicting plan reached ledger write")
    monkeypatch.setattr(ledger, "add_evidence", forbidden)
    with pytest.raises(SourceRevisionConflict):
        commit_source_payloads(ledger, question.id, [row(), row(2)])
