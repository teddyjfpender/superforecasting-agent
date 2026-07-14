from __future__ import annotations

import sqlite3

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
from forecasting.change_control.models import canonical_json, content_digest
from forecasting.change_control.policy import classify_operations
from forecasting.ledger import allow_ledger_writes
from forecasting.models import ValidationError


def _control(tmp_path):
    return ChangeControl(ForecastLedger(tmp_path / "forecasting.db"))


def _operation(
    *,
    operation_id: str = "op_1",
    probability: float = 0.55,
    prior: float = 0.50,
) -> LedgerOperation:
    return LedgerOperation(
        id=operation_id,
        kind="forecast.update",
        target_ref="q_1",
        payload={
            "probability_or_distribution": probability,
            "rationale": "The registered evidence moved the estimate.",
        },
        preconditions={"prior_probability": prior},
        provenance_refs=("session_1",),
        author_attestation={"owner_id": "owner_author", "actor_kind": "agent"},
    )


def _question(ledger, *, probability: float | None = None):
    with allow_ledger_writes("test_change_control"):
        question = ledger.create_question(
            title="Will the filing arrive before the deadline?",
            resolution_criteria="Resolve Yes if the official filing arrives before the deadline.",
        )
        if probability is not None:
            ledger.create_snapshot(
                question_id=question.id,
                probability_or_distribution=probability,
                rationale="The initial evidence supports this estimate.",
                require_style=False,
                require_output_structure=False,
            )
    return question


def _merge_ready(control, changeset_id: str, *, head_sha: str | None = None):
    changeset = control.get_changeset(changeset_id)
    metadata = {**changeset["metadata"], "checks_passed": True}
    fields = {"metadata": metadata}
    if head_sha:
        fields["head_sha"] = head_sha
    control.transition(changeset_id, "ready", fields=fields)
    control.transition(changeset_id, "checks_running")
    return control.transition(changeset_id, "merge_ready")


def _evidence_operation(question_id: str, operation_id: str, **payload):
    return LedgerOperation(
        id=operation_id,
        kind="evidence.attach",
        target_ref=question_id,
        payload={"source_type": "manual_note", "claim": "A new filing was logged.", **payload},
    )


def test_canonical_digest_is_order_independent():
    left = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": [2, 1]}
    assert canonical_json(left) == canonical_json(right)
    assert content_digest(left) == content_digest(right)


def test_operation_rejects_unknown_version_and_kind():
    with pytest.raises(ValidationError, match="unsupported operation version"):
        LedgerOperation(
            id="op_1",
            kind="forecast.update",
            target_ref="q_1",
            payload={"probability_or_distribution": 0.5, "rationale": "x"},
            version=2,
        )
    with pytest.raises(ValidationError, match="unsupported operation kind"):
        LedgerOperation(id="op_1", kind="shell.run", target_ref="q_1", payload={})


def test_operation_requires_kind_payload_fields():
    with pytest.raises(ValidationError, match="rationale"):
        LedgerOperation(
            id="op_1",
            kind="forecast.update",
            target_ref="q_1",
            payload={"probability_or_distribution": 0.6},
        )


def test_change_control_schema_is_initialized_with_ledger(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    with ledger._connect() as conn:
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "ledger_revisions",
        "ledger_changesets",
        "ledger_change_operations",
        "ledger_reviews",
        "ledger_apply_attempts",
        "ledger_artifact_links",
    } <= tables


def test_new_ledger_starts_at_revision_zero(tmp_path):
    control = _control(tmp_path)
    revision = control.current_revision()
    assert revision["revision"] == 0
    assert len(revision["digest"]) == 64


def test_create_changeset_records_identity_and_base_revision(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(
        workspace_id="desk_1",
        changeset_id="chg_fixed",
        author_owner_ids=["owner_1", "owner_1"],
        author_identities=[{"owner_id": "owner_1", "agent": "Mira"}],
        affected_question_ids=["q_1", "q_2"],
        slack_thread_key="slack:T:C:123",
    )
    assert changeset["id"] == "chg_fixed"
    assert changeset["base_revision"] == 0
    assert changeset["author_owner_ids"] == ["owner_1"]
    assert changeset["author_identities"][0]["agent"] == "Mira"
    assert changeset["affected_question_ids"] == ["q_1", "q_2"]


def test_base_revision_cannot_point_past_ledger(tmp_path):
    control = _control(tmp_path)
    with pytest.raises(ValidationError, match="outside ledger history"):
        control.create_changeset(workspace_id="desk_1", base_revision=1)


def test_add_operation_updates_digest_and_risk(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    original_digest = changeset["digest"]
    changeset = control.add_operation(changeset["id"], _operation())
    assert changeset["digest"] != original_digest
    assert changeset["risk_tier"] == "medium"
    assert len(control.list_operations(changeset["id"])) == 1


def test_exact_ten_point_probability_move_is_high_risk(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    changeset = control.add_operation(
        changeset["id"], _operation(probability=0.60, prior=0.50)
    )
    assert changeset["risk_tier"] == "high"
    assert any("probability delta" in reason for reason in changeset["risk_reasons"])


def test_protected_operation_is_always_high_risk(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    changeset = control.add_operation(
        changeset["id"],
        LedgerOperation(
            id="op_criteria",
            kind="question.criteria.update",
            target_ref="q_1",
            payload={"resolution_criteria": "Resolve Yes only after the official filing."},
        ),
    )
    assert changeset["risk_tier"] == "high"


def test_duplicate_operation_id_and_sequence_are_constrained(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.add_operation(changeset["id"], _operation())
    with pytest.raises(sqlite3.IntegrityError):
        control.add_operation(changeset["id"], _operation())


def test_medium_quorum_requires_non_author_human(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_author"]
    )
    changeset = control.add_operation(changeset["id"], _operation())
    assert control.quorum(changeset["id"]).satisfied is False
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="owner_author",
        source="slack",
    )
    assert control.quorum(changeset["id"]).satisfied is False
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="owner_reviewer",
        source="slack",
    )
    assert control.quorum(changeset["id"]).satisfied is True


def test_agent_review_never_gets_human_quorum_credit(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    changeset = control.add_operation(changeset["id"], _operation())
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="agent",
        owner_id="owner_reviewer",
        agent_instance_id="agent_1",
        source="github",
    )
    assert control.quorum(changeset["id"]).satisfied is False


def test_high_quorum_requires_two_humans_and_owner_or_steward(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    changeset = control.add_operation(
        changeset["id"], _operation(probability=0.70, prior=0.50)
    )
    for owner_id, role in (("reviewer_1", "reviewer"), ("reviewer_2", "reviewer")):
        control.add_review(
            changeset["id"],
            decision="approve",
            actor_kind="human",
            owner_id=owner_id,
            role=role,
            source="slack",
        )
    result = control.quorum(changeset["id"])
    assert result.satisfied is False
    assert result.owner_or_steward_present is False
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="steward_1",
        role="domain_steward",
        source="slack",
    )
    assert control.quorum(changeset["id"]).satisfied is True


def test_new_operation_stales_existing_reviews(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    changeset = control.add_operation(changeset["id"], _operation())
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="reviewer_1",
        source="slack",
    )
    assert control.quorum(changeset["id"]).satisfied is True
    control.add_operation(
        changeset["id"], _operation(operation_id="op_2", probability=0.56)
    )
    reviews = control.list_reviews(changeset["id"])
    assert reviews[0]["stale_at"] is not None
    assert control.quorum(changeset["id"]).satisfied is False


def test_review_head_sha_must_match_changeset(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.transition(changeset["id"], "ready")
    control.transition(changeset["id"], "publishing")
    changeset = control.transition(
        changeset["id"], "review_open", fields={"head_sha": "a" * 40}
    )
    with pytest.raises(ValidationError, match="head_sha"):
        control.add_review(
            changeset["id"],
            decision="approve",
            actor_kind="human",
            owner_id="reviewer_1",
            source="github",
            head_sha="b" * 40,
        )


def test_transition_is_compare_and_set_and_rejects_invalid_edge(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    with pytest.raises(ValidationError, match="invalid changeset transition"):
        control.transition(changeset["id"], "applied")
    control.transition(changeset["id"], "ready", expected_status="draft")
    with pytest.raises(ValidationError, match="expected draft"):
        control.transition(changeset["id"], "publishing", expected_status="draft")


def test_list_changesets_filters_workspace_and_status(tmp_path):
    control = _control(tmp_path)
    first = control.create_changeset(workspace_id="desk_1")
    control.create_changeset(workspace_id="desk_2")
    control.transition(first["id"], "ready")
    rows = control.list_changesets(workspace_id="desk_1", status="ready")
    assert [row["id"] for row in rows] == [first["id"]]


def test_human_review_requires_owner_id(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    with pytest.raises(ValidationError, match="owner_id"):
        control.add_review(
            changeset["id"],
            decision="approve",
            actor_kind="human",
            source="slack",
        )


def test_workspace_risk_override_can_raise_but_not_lower_protected_minimum():
    low = LedgerOperation(
        id="doc_1",
        kind="document.update",
        target_ref="brief_1",
        payload={"path": "documents/brief.md", "content": "Current thesis."},
    )
    protected = LedgerOperation(
        id="criteria_1",
        kind="question.criteria.update",
        target_ref="q_1",
        payload={"resolution_criteria": "Use the official release."},
    )
    assert classify_operations([low], risk_overrides={"document.update": "medium"}).tier == "medium"
    assert (
        classify_operations(
            [protected], risk_overrides={"question.criteria.update": "low"}
        ).tier
        == "high"
    )


def test_preview_is_repeatable_and_does_not_mutate_live_ledger(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = _question(ledger)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.add_operation(
        changeset["id"], _evidence_operation(question.id, "evidence_1")
    )
    # Stabilize WAL bookkeeping before the byte comparison. A read-only online
    # backup may checkpoint already-committed WAL pages, which changes SQLite's
    # container header without changing any ledger content.
    with ledger._connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    before = ledger.db_path.read_bytes()

    first = control.preview(changeset["id"])
    second = control.preview(changeset["id"])

    assert first["would_apply"] is True
    assert first["projection_digest"] == second["projection_digest"]
    assert first["markdown"].startswith(f"# Changeset {changeset['id']}")
    assert ledger.db_path.read_bytes() == before
    assert ledger.list_evidence(question.id) == []


def test_preview_reports_failures_for_every_operation(tmp_path):
    control = _control(tmp_path)
    changeset = control.create_changeset(workspace_id="desk_1")
    for index in (1, 2):
        control.add_operation(
            changeset["id"],
            LedgerOperation(
                id=f"op_{index}",
                kind="forecast.update",
                target_ref=f"missing_{index}",
                payload={
                    "probability_or_distribution": 0.55,
                    "rationale": "Evidence changed the estimate.",
                },
            ),
        )
    preview = control.preview(changeset["id"])
    failed_ids = {item["operation_id"] for item in preview["failures"]}
    assert {"op_1", "op_2"} <= failed_ids
    assert preview["would_apply"] is False


def test_transactional_apply_is_idempotent_and_increments_revision(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = _question(ledger)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.add_operation(
        changeset["id"], _evidence_operation(question.id, "evidence_1")
    )
    _merge_ready(control, changeset["id"])

    first = control.apply(changeset["id"])
    second = control.apply(changeset["id"])

    assert first == second
    assert first["revision"] == 1
    assert len(first["ledger_digest"]) == 64
    assert len(ledger.list_evidence(question.id)) == 1
    assert control.get_changeset(changeset["id"])["status"] == "applied"


def test_failed_operation_rolls_back_entire_changeset_and_records_attempt(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = _question(ledger)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.add_operation(
        changeset["id"], _evidence_operation(question.id, "evidence_1")
    )
    control.add_operation(
        changeset["id"],
        _evidence_operation(question.id, "evidence_2", reliability_rating=2.0),
    )
    _merge_ready(control, changeset["id"])

    with pytest.raises(ValidationError, match="reliability_rating"):
        control.apply(changeset["id"])

    assert ledger.list_evidence(question.id) == []
    assert control.current_revision()["revision"] == 0
    assert control.get_changeset(changeset["id"])["status"] == "apply_failed"
    with ledger._connect() as conn:
        attempt = conn.execute(
            "SELECT state, diagnostic FROM ledger_apply_attempts WHERE changeset_id = ?",
            (changeset["id"],),
        ).fetchone()
    assert attempt["state"] == "failed"
    assert "reliability_rating" not in attempt["diagnostic"]


def test_forecast_update_requires_sha_bound_non_author_approval(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = _question(ledger, probability=0.50)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["author_1"]
    )
    operation = LedgerOperation(
        id="forecast_1",
        kind="forecast.update",
        target_ref=question.id,
        payload={
            "probability_or_distribution": 0.55,
            "rationale": "The official update moved the estimate modestly.",
            "require_style": False,
            "require_output_structure": False,
        },
        preconditions={"prior_probability": 0.50},
    )
    control.add_operation(changeset["id"], operation)
    head_sha = "a" * 40
    _merge_ready(control, changeset["id"], head_sha=head_sha)
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="reviewer_1",
        source="github",
        head_sha=head_sha,
    )

    result = control.apply(changeset["id"])

    assert result["objects"][0]["question_id"] == question.id
    assert ledger.get_current_snapshot(question.id).probability_or_distribution == 0.55


def test_legacy_proposal_bridge_does_not_double_create_snapshot(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question = _question(ledger, probability=0.50)
    prior = ledger.get_current_snapshot(question.id)
    evidence = ledger.add_evidence(
        question_id=question.id,
        source_or_note="The official filing was published.",
        claim="The filing contains new information.",
    )
    proposal = ledger.create_forecast_update_proposal(
        question_id=question.id,
        run_id=None,
        prior_forecast_id=prior.forecast_id,
        proposed_probability_or_distribution=0.55,
        rationale="The official update moved the estimate modestly.",
        evidence_refs=[evidence.id],
    )
    control = ChangeControl(ledger)
    changeset = control.wrap_legacy_proposal(
        proposal["id"], workspace_id="desk_1", author_owner_ids=["author_1"]
    )
    assert ledger.get_forecast_update_proposal(proposal["id"])["status"] == "pending"
    head_sha = "b" * 40
    _merge_ready(control, changeset["id"], head_sha=head_sha)
    control.add_review(
        changeset["id"],
        decision="approve",
        actor_kind="human",
        owner_id="reviewer_1",
        source="github",
        head_sha=head_sha,
    )

    control.apply(changeset["id"])
    control.apply(changeset["id"])

    assert ledger.get_forecast_update_proposal(proposal["id"])["status"] == "approved"
    assert len(ledger.list_snapshots(question.id)) == 2
