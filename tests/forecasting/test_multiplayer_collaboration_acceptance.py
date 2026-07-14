from __future__ import annotations

import hashlib
import hmac
import json

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
from forecasting.change_control.transcripts import render_review_transcript
from forecasting.github import (
    GitHubWebhookProcessor,
    MergeApplyReconciler,
    PromotionCheckPublisher,
    ingest_github_webhook,
)
from forecasting.slack_collaboration import SlackActionService, SlackChangesetCardService
from forecasting.workspace import bootstrap_workspace, export_workspace, validate_workspace


def _signed(payload):
    body = json.dumps(payload, sort_keys=True).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    return body, signature


def _binding(control, index, persona):
    return control.bind_identity(
        owner_id=f"owner_{index}",
        slack_team_id="T1",
        slack_user_id=f"U{index}",
        agent_instance_id=f"agent_{index}",
        agent_persona=persona,
        github_user_id=str(100 + index),
        github_node_id=f"node-{index}",
        github_login=f"owner-{index}",
        agent_avatar_url=f"https://images.test/{index}.png",
    )


def test_three_owner_slack_github_ledger_acceptance_harness(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / "home"))
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    bindings = [
        _binding(control, 1, "Mira"),
        _binding(control, 2, "Orion"),
        _binding(control, 3, "Sable"),
    ]
    thread = control.thread_changeset(
        workspace_id="desk_1",
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        owner_id="owner_1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
    )
    changeset_id = thread["changeset_id"]
    for index, binding in enumerate(bindings, start=1):
        for actor_kind in ("human", "agent"):
            control.record_contribution(
                changeset_id,
                idempotency_key=f"contribution-{index}-{actor_kind}",
                binding=binding,
                actor_kind=actor_kind,
                commit_sha=f"commit-{index}",
                metadata={"transport": "slack"},
            )
    for index in (1, 2):
        control.add_operation(
            changeset_id,
            LedgerOperation(
                id=f"document_{index}",
                kind="document.update",
                target_ref=f"forecast_brief_{index}",
                payload={
                    "path": f"documents/forecast-{index}.md",
                    "content": f"Collaborative forecast thesis {index}.",
                },
            ),
        )
    control.add_decision_record(
        changeset_id,
        conclusion="Publish the two reviewed forecast theses.",
        evidence_refs=["evidence-1", "evidence-2"],
        tests=["portable workspace validation"],
    )
    rendered = render_review_transcript(
        changeset_id=changeset_id,
        goal="Publish two collaborative forecast theses",
        sessions={
            "session-1": [
                {"role": "user", "content": "Publish both collaborative forecast theses."},
                {"role": "assistant", "content": "Both forecast theses passed review."},
                {"role": "tool", "name": "pytest", "content": "raw output omitted"},
            ]
        },
        changed_files=["documents/forecast-1.md", "documents/forecast-2.md"],
    )
    control.record_transcript(
        changeset_id,
        format="markdown",
        status="safe",
        digest=rendered.digest,
        byte_size=len(rendered.markdown.encode()),
        content=rendered.markdown,
    )
    control.record_transcript_consent(
        changeset_id,
        transcript_digest=rendered.digest,
        repository_slug="acme/forecasts",
        owner_id="owner_1",
        decision="include",
    )
    control.transition(changeset_id, "ready")
    control.transition(changeset_id, "publishing")
    control.transition(
        changeset_id,
        "review_open",
        fields={
            "branch": f"forecast/changesets/{changeset_id}",
            "head_sha": "head-7",
            "pr_number": 7,
        },
    )
    cards = SlackChangesetCardService(ledger)
    cards.update(
        changeset_id,
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        phase="review_required",
        next_action="Review the draft PR.",
        active_owner_id="owner_1",
        active_agent_instance_id="agent_1",
        active_agent_persona="Mira",
        state={"heartbeat_expected": False},
    )
    actions = SlackActionService(
        ledger, signing_key=b"s" * 32, repository_slug="acme/forecasts"
    )
    token = actions.issue(
        changeset_id,
        "approve",
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
    )
    action_args = {
        "action_id": "forecast_approve",
        "slack_team_id": "T1",
        "slack_channel_id": "C1",
        "slack_thread_ts": "1710000000.000001",
        "slack_user_id": "U2",
    }
    assert actions.handle(token, **action_args) == actions.handle(token, **action_args)

    workspace = tmp_path / "workspace"
    export_workspace(
        ledger,
        workspace,
        workspace_id="desk_1",
        repository_slug="acme/forecasts",
    )
    assert validate_workspace(workspace).valid
    assert (workspace / f"transcripts/{changeset_id}/transcript.md").is_file()

    class _App:
        def call(self, action, method, path, body=None, *, expected_statuses=()):
            return {"status_code": 201, "body": {"id": 700}}

    checked = PromotionCheckPublisher(
        ledger,
        repository_slug="acme/forecasts",
        app_id="1234",
        client=_App(),
    ).publish(changeset_id, workspace)
    assert checked["status"] == "merge_ready"

    processor = GitHubWebhookProcessor(
        ledger, repository_slug="acme/forecasts", promotion_app_id="1234"
    )
    queue_payload = {
        "action": "checks_requested",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "merge_group": {
            "id": 70,
            "head_ref": "refs/heads/gh-readonly-queue/main/pr-7-abcdef",
            "head_sha": "queue-head-7",
        },
    }
    queue_body, queue_signature = _signed(queue_payload)
    queue_headers = {
        "X-Hub-Signature-256": queue_signature,
        "X-GitHub-Delivery": "queue-7",
        "X-GitHub-Event": "merge_group",
    }
    for _ in range(2):
        ingest_github_webhook(
            ledger,
            headers=queue_headers,
            body=queue_body,
            secret="secret",
            repository_slug="acme/forecasts",
        )
    processor.process("queue-7")
    assert control.get_changeset(changeset_id)["status"] == "merge_queued"

    merge_payload = {
        "action": "closed",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "merge-7",
            "head": {"ref": thread["branch"], "sha": "head-7"},
            "base": {"ref": "main", "sha": "base"},
        },
    }
    merge_body, merge_signature = _signed(merge_payload)
    ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": merge_signature,
            "X-GitHub-Delivery": "merge-7",
            "X-GitHub-Event": "pull_request",
        },
        body=merge_body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    processor.process("merge-7")
    assert control.get_changeset(changeset_id)["status"] == "merged_apply_pending"

    restarted = MergeApplyReconciler(ForecastLedger(ledger.db_path))
    assert restarted.run()[0]["state"] == "applied"
    assert restarted.run() == []
    applied = control.get_changeset(changeset_id)
    assert applied["applied_revision"] == 1
    with ledger._connect() as conn:
        contributions = conn.execute(
            """SELECT owner_id, agent_persona, actor_kind, commit_sha
               FROM collaboration_contributions WHERE changeset_id = ?""",
            (changeset_id,),
        ).fetchall()
    assert len(contributions) == 6
    assert {row["agent_persona"] for row in contributions} == {"Mira", "Orion", "Sable"}
    assert {row["commit_sha"] for row in contributions} == {
        "commit-1",
        "commit-2",
        "commit-3",
    }

    final_workspace = tmp_path / "final-workspace"
    final_manifest = export_workspace(
        ledger,
        final_workspace,
        workspace_id="desk_1",
        repository_slug="acme/forecasts",
    )
    restored_path = tmp_path / "restored.db"
    restored_result = bootstrap_workspace(final_workspace, restored_path)
    restored = ChangeControl(ForecastLedger(restored_path))
    assert restored.current_revision() == control.current_revision()
    assert restored_result["content_digest"] == final_manifest.content_digest


def test_medium_high_quorum_and_stale_approval_fixtures(tmp_path):
    control = ChangeControl(ForecastLedger(tmp_path / "forecasting.db"))
    medium = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_1"]
    )
    control.add_operation(
        medium["id"],
        LedgerOperation(
            id="forecast_1",
            kind="forecast.update",
            target_ref="question_1",
            payload={"probability_or_distribution": 0.55, "rationale": "New evidence."},
        ),
    )
    current = control.get_changeset(medium["id"])
    review = control.add_review(
        medium["id"],
        decision="approve",
        actor_kind="human",
        source="github",
        owner_id="owner_2",
        head_sha="head-1",
    )
    assert control.quorum(medium["id"]).satisfied
    control.add_operation(
        medium["id"],
        LedgerOperation(
            id="assumption_1",
            kind="assumption.upsert",
            target_ref="question_1",
            payload={"text": "A changed assumption."},
        ),
    )
    assert control.get_changeset(medium["id"])["digest"] != current["digest"]
    assert control.list_reviews(medium["id"])[0]["id"] == review["id"]
    assert control.list_reviews(medium["id"])[0]["stale_at"] is not None
    assert not control.quorum(medium["id"]).satisfied

    high = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_1"]
    )
    control.add_operation(
        high["id"],
        LedgerOperation(
            id="criteria_1",
            kind="question.criteria.update",
            target_ref="question_1",
            payload={"resolution_criteria": "Resolve from the official release record."},
        ),
    )
    for owner, role in (("owner_2", "reviewer"), ("owner_3", "domain_steward")):
        control.add_review(
            high["id"],
            decision="approve",
            actor_kind="human",
            source="github",
            owner_id=owner,
            role=role,
        )
    quorum = control.quorum(high["id"])
    assert quorum.required_humans == 2
    assert quorum.approved_owner_ids == ("owner_2", "owner_3")
    assert quorum.owner_or_steward_present
    assert quorum.satisfied
