from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
from forecasting.models import LedgerNotFoundError
from forecasting.slack_collaboration import SlackActionService, SlackChangesetCardService


class _Reviews:
    def __init__(self):
        self.calls = []

    def call(self, action, method, path, body=None, *, expected_statuses=()):
        self.calls.append((action, method, path, body))
        return {"status_code": 200, "body": {"id": 991}}


def _setup(tmp_path, *, author="author_1"):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="reviewer_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_reviewer",
        agent_persona="Nova",
        github_user_id="101",
        github_node_id="node-101",
        github_login="reviewer",
    )
    changeset = control.create_changeset(
        workspace_id="desk_1",
        author_owner_ids=[author],
        affected_question_ids=["question_1", "question_2"],
    )
    control.transition(changeset["id"], "ready")
    control.transition(changeset["id"], "publishing")
    control.transition(
        changeset["id"],
        "review_open",
        fields={
            "branch": f"forecast/changesets/{changeset['id']}",
            "pr_number": 7,
            "head_sha": "head-7",
        },
    )
    return ledger, control, binding, control.get_changeset(changeset["id"])


def _service(ledger, reviews=None, *, clock=None, roles=None):
    return SlackActionService(
        ledger,
        signing_key=b"s" * 32,
        repository_slug="acme/forecasts",
        github_client_factory=(lambda binding, changeset_id: reviews) if reviews else None,
        role_resolver=roles,
        clock=clock or __import__("time").time,
    )


def _issue(service, changeset_id, action="approve", **kwargs):
    return service.issue(
        changeset_id,
        action,
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        **kwargs,
    )


def _handle(service, token, action="approve", **kwargs):
    values = {
        "action_id": f"forecast_{action}",
        "slack_team_id": "T1",
        "slack_channel_id": "C1",
        "slack_thread_ts": "1710000000.000001",
        "slack_user_id": "U1",
    }
    values.update(kwargs)
    return service.handle(token, **values)


def test_human_slack_approval_is_single_use_and_mirrored_with_owner_token(tmp_path):
    ledger, control, binding, changeset = _setup(tmp_path)
    reviews = _Reviews()
    service = _service(ledger, reviews)
    token = _issue(service, changeset["id"])

    first = _handle(service, token)
    second = _handle(service, token)

    assert first == second
    assert first["github_state"] == "posted"
    assert first["github_review_id"] == "991"
    assert len(reviews.calls) == 1
    assert reviews.calls[0][0:3] == (
        "review.write",
        "POST",
        "/repos/acme/forecasts/pulls/7/reviews",
    )
    assert reviews.calls[0][3]["event"] == "APPROVE"
    recorded = control.list_reviews(changeset["id"])
    assert len(recorded) == 1
    assert recorded[0]["actor_kind"] == "human"
    assert recorded[0]["owner_id"] == "reviewer_1"
    assert recorded[0]["agent_persona"] is None
    with ledger._connect() as conn:
        marker = dict(conn.execute("SELECT * FROM github_origin_markers").fetchone())
    assert marker["identity_binding_id"] == binding["id"]
    assert marker["actor_kind"] == "human"


def test_action_rejects_context_swap_stale_digest_expiry_and_unlinked_user(tmp_path):
    ledger, control, _, changeset = _setup(tmp_path)
    now = [1_000.0]
    service = _service(ledger, clock=lambda: now[0])
    token = _issue(service, changeset["id"])
    with pytest.raises(PermissionError, match="context"):
        _handle(service, token, slack_channel_id="C_OTHER")
    with pytest.raises(LedgerNotFoundError, match="no unambiguous"):
        _handle(service, token, slack_user_id="U_OTHER")

    stale = _issue(service, changeset["id"], action="view_diff")
    control.transition(changeset["id"], "changes_requested")
    control.transition(changeset["id"], "draft")
    control.add_operation(
        changeset["id"],
        LedgerOperation(
            id="document_2",
            kind="document.update",
            target_ref="brief",
            payload={"path": "documents/brief.md", "content": "Changed."},
        ),
    )
    with pytest.raises(PermissionError, match="stale"):
        _handle(service, stale, action="view_diff")

    expiring = _issue(service, changeset["id"], action="view_diff", ttl_seconds=60)
    now[0] += 61
    with pytest.raises(PermissionError, match="expired"):
        _handle(service, expiring, action="view_diff")


def test_transcript_consent_is_bound_to_initiating_owner_and_digest(tmp_path):
    ledger, _, _, changeset = _setup(tmp_path, author="reviewer_1")
    service = _service(ledger)
    token = _issue(
        service,
        changeset["id"],
        action="transcript_include",
        metadata={"transcript_digest": "a" * 64},
    )
    result = _handle(service, token, action="transcript_include")
    assert result["consent"] == "include"
    with ledger._connect() as conn:
        consent = dict(conn.execute("SELECT * FROM provenance_consents").fetchone())
    assert consent["transcript_digest"] == "a" * 64
    assert consent["repository_slug"] == "acme/forecasts"
    assert consent["owner_id"] == "reviewer_1"


def test_contributing_owner_can_publish_draft_pr_from_slack_action(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="owner_1", slack_team_id="T1", slack_user_id="U1",
        agent_instance_id="agent_1", agent_persona="Mira",
        github_user_id="101", github_node_id="node-101", github_login="owner-one",
    )
    changeset = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_1"]
    )
    factory_calls = []

    class _Publisher:
        def publish(self, changeset_id, output_dir):
            factory_calls.append((changeset_id, output_dir))
            assert Path(output_dir).is_dir()
            return {
                "pr_number": 8,
                "pr_url": "https://github.test/acme/forecasts/pull/8",
                "head_repository": "owner-one/forecasts",
                "publication_mode": "owner_fork",
            }

    service = SlackActionService(
        ledger, signing_key=b"s" * 32, repository_slug="acme/forecasts",
        github_publisher_factory=lambda resolved, value: (
            factory_calls.append((resolved["id"], value["id"])) or _Publisher()
        ),
    )
    result = _handle(
        service, _issue(service, changeset["id"], action="open_pr"), action="open_pr"
    )
    assert result["pr_number"] == 8
    assert result["publication_mode"] == "owner_fork"
    assert factory_calls[0] == (binding["id"], changeset["id"])
    assert factory_calls[1][0] == changeset["id"]


def test_failed_slack_publication_returns_safe_recoverable_state(tmp_path):
    ledger, _, _, changeset = _setup(tmp_path, author="reviewer_1")
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE ledger_changesets SET pr_number = NULL WHERE id = ?",
            (changeset["id"],),
        )

    class _Publisher:
        def publish(self, changeset_id, output_dir):
            raise PermissionError("sensitive upstream diagnostic")

    service = SlackActionService(
        ledger,
        signing_key=b"s" * 32,
        repository_slug="acme/forecasts",
        github_publisher_factory=lambda binding, value: _Publisher(),
    )
    token = _issue(service, changeset["id"], action="open_pr")

    result = _handle(service, token, action="open_pr")

    assert result["ok"] is False
    assert result["state"] == "failed"
    assert "sensitive" not in json.dumps(result)


def test_status_card_is_one_editable_message_with_presence_liveness_and_final(tmp_path):
    ledger, _, _, changeset = _setup(tmp_path)
    cards = SlackChangesetCardService(ledger, stale_after_seconds=30)
    cards.update(
        changeset["id"],
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        phase="checks_running",
        next_action="Waiting for ledger/promotion.",
        active_owner_id="reviewer_1",
        active_agent_instance_id="agent_reviewer",
        active_agent_persona="Nova",
        pr_url="https://github.test/acme/forecasts/pull/7",
        checks_state="running",
    )
    cards.presence(
        changeset["id"],
        owner_id="reviewer_1",
        agent_instance_id="agent_reviewer",
        agent_persona="Nova",
        presence="reviewing",
    )
    cards.set_message_ts(changeset["id"], "1710000001.000001")
    action_service = _service(ledger)
    rendered = cards.render(
        changeset["id"],
        actions=action_service,
        transcript_digest="b" * 64,
    )

    assert rendered["message_ts"] == "1710000001.000001"
    encoded = json.dumps(rendered)
    assert "Nova: reviewing" in encoded
    assert "Waiting for ledger/promotion" in encoded
    assert "forecast_approve" in encoded
    assert "forecast_transcript_include" in encoded
    assert len([block for block in rendered["blocks"] if block["type"] == "actions"]) >= 2

    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE slack_changeset_cards SET last_heartbeat_at = ? WHERE changeset_id = ?",
            (old, changeset["id"]),
        )
    delayed = cards.render(changeset["id"])
    assert delayed["delayed"] is True
    assert "delayed / reconnecting" in delayed["text"]
    assert "failed" not in delayed["text"]
    final = cards.render_final(changeset["id"])
    assert final["thread_ts"] == "1710000000.000001"
    assert "not applied" in final["text"]
