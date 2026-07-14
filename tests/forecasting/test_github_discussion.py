from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.github.discussion import (
    AgentDiscussionCoordinator,
    DiscussionLimits,
    record_human_discussion_activity,
)
from forecasting.github.events import GitHubWebhookProcessor
from forecasting.github.slack_sync import GitHubSlackMirror
from forecasting.github.webhooks import ingest_github_webhook
from forecasting.models import ValidationError
from forecasting.slack_collaboration import SlackChangesetCardService


class _GitHubClient:
    actor_kind = "agent"

    def __init__(self, identity_binding_id: str) -> None:
        self.identity_binding_id = identity_binding_id
        self.calls: list[tuple] = []

    def call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        number = len(self.calls)
        return {
            "status_code": 201,
            "body": {
                "id": 100 + number,
                "html_url": f"https://github.test/comment/{100 + number}",
            },
        }


def _coordinator(tmp_path, **limit_overrides):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        github_user_id="101",
        github_node_id="node-101",
        github_login="reviewer",
    )
    changeset = control.create_changeset(workspace_id="desk_1")
    control.transition(changeset["id"], "ready")
    control.transition(changeset["id"], "publishing")
    changeset = control.transition(
        changeset["id"],
        "review_open",
        fields={"pr_number": 7, "head_sha": "head-7"},
    )
    client = _GitHubClient(binding["id"])
    limits = DiscussionLimits(**limit_overrides)
    coordinator = AgentDiscussionCoordinator(
        ledger,
        client,
        repository_slug="acme/forecasts",
        limits=limits,
    )
    return ledger, control, binding, changeset, client, coordinator


def _respond(coordinator, changeset_id, binding_id, run_id="run_1", **kwargs):
    return coordinator.respond(
        changeset_id,
        identity_binding_id=binding_id,
        trigger=kwargs.pop("trigger", "assigned"),
        body=kwargs.pop(
            "body", "The reference class supports keeping the estimate unchanged."
        ),
        model=kwargs.pop("model", "forecast-model-1"),
        run_id=run_id,
        round_number=kwargs.pop("round_number", 1),
        token_count=kwargs.pop("token_count", 20),
        **kwargs,
    )


def test_agent_comment_is_owner_attributed_audited_and_idempotent(tmp_path):
    ledger, _, binding, changeset, client, coordinator = _coordinator(tmp_path)

    first = _respond(coordinator, changeset["id"], binding["id"])
    second = _respond(coordinator, changeset["id"], binding["id"])

    assert first["state"] == "posted"
    assert second["state"] == "already_posted"
    assert len(client.calls) == 1
    comment = client.calls[0][0][3]["body"]
    assert "Agent review — Mira" in comment
    assert "owner_1" in comment
    assert "@reviewer" in comment
    assert "forecast-model-1" in comment
    assert changeset["digest"] in comment
    with ledger._connect() as conn:
        event = dict(
            conn.execute("SELECT * FROM github_agent_discussion_events").fetchone()
        )
        marker = dict(conn.execute("SELECT * FROM github_origin_markers").fetchone())
    assert event["actor_kind"] == "agent"
    assert event["body_digest"] and "reference class" not in str(event)
    assert marker["actor_kind"] == "agent"
    assert marker["identity_binding_id"] == binding["id"]


def test_discussion_rejects_unapproved_trigger_secret_and_wrong_owner(tmp_path):
    _, _, binding, changeset, client, coordinator = _coordinator(tmp_path)
    with pytest.raises(PermissionError, match="trigger"):
        _respond(
            coordinator,
            changeset["id"],
            binding["id"],
            trigger="unsolicited",
        )
    with pytest.raises(PermissionError, match="secret-safety"):
        _respond(
            coordinator,
            changeset["id"],
            binding["id"],
            body="Use Bearer abcdefghijklmnopqrstuvwxyz123456 to reproduce.",
        )
    coordinator.github_client.identity_binding_id = "identity_other"
    with pytest.raises(PermissionError, match="another owner"):
        _respond(coordinator, changeset["id"], binding["id"])
    assert client.calls == []


@pytest.mark.parametrize(
    ("limits", "kwargs", "message"),
    [
        ({"max_comments": 1}, {"run_id": "run_2"}, "comment budget"),
        ({"max_rounds": 1}, {"run_id": "run_2", "round_number": 2}, "round budget"),
        (
            {"max_tokens": 20},
            {"run_id": "run_2", "token_count": 20},
            "token budget",
        ),
    ],
)
def test_discussion_enforces_per_changeset_budgets(tmp_path, limits, kwargs, message):
    _, _, binding, changeset, client, coordinator = _coordinator(tmp_path, **limits)
    _respond(
        coordinator,
        changeset["id"],
        binding["id"],
        token_count=10,
        body="A compact evidence note.",
    )
    with pytest.raises(PermissionError, match=message):
        _respond(coordinator, changeset["id"], binding["id"], **kwargs)
    assert len(client.calls) == 1


def test_discussion_enforces_elapsed_and_concurrent_task_budgets(tmp_path):
    ledger, _, binding, changeset, client, coordinator = _coordinator(
        tmp_path, max_elapsed_seconds=1, max_concurrent_tasks=1
    )
    _respond(coordinator, changeset["id"], binding["id"], body="A compact note.")
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE github_agent_discussion_events SET created_at = ?",
            (old,),
        )
    with pytest.raises(PermissionError, match="elapsed-time"):
        _respond(coordinator, changeset["id"], binding["id"], run_id="run_2")

    with ledger._connect() as conn:
        conn.execute("DELETE FROM github_agent_discussion_events")
        conn.execute(
            """INSERT INTO github_agent_discussion_leases
               (id, changeset_id, identity_binding_id, trigger_kind, run_id,
                state, started_at, expires_at)
               VALUES ('busy', ?, ?, 'assigned', 'busy_run', 'active', ?, ?)""",
            (
                changeset["id"],
                binding["id"],
                datetime.now(timezone.utc).isoformat(),
                (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            ),
        )
    with pytest.raises(PermissionError, match="concurrency"):
        _respond(coordinator, changeset["id"], binding["id"], run_id="run_3")
    assert len(client.calls) == 1


def test_agent_loop_pauses_changeset_and_human_activity_resets_sequence(tmp_path):
    ledger, control, binding, changeset, client, coordinator = _coordinator(
        tmp_path, agent_loop_threshold=2
    )
    _respond(coordinator, changeset["id"], binding["id"], run_id="run_1")
    record_human_discussion_activity(
        ledger,
        changeset_id=changeset["id"],
        remote_kind="comment",
        remote_id="human-1",
        identity_binding_id=binding["id"],
    )
    second = _respond(coordinator, changeset["id"], binding["id"], run_id="run_2")
    assert second["paused"] is False
    third = _respond(coordinator, changeset["id"], binding["id"], run_id="run_3")

    assert third["state"] == "human_direction_required"
    assert control.get_changeset(changeset["id"])["status"] == "held"
    assert "Human direction is required" in client.calls[-1][0][3]["body"]
    with pytest.raises(PermissionError, match="not open"):
        _respond(coordinator, changeset["id"], binding["id"], run_id="run_4")

    cards = SlackChangesetCardService(ledger)
    cards.update(
        changeset["id"],
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        phase="review_required",
        next_action="Review the proposal.",
    )
    payload = {
        "action": "created",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "issue": {"number": 7, "pull_request": {"url": "pull"}},
        "comment": {"id": 103, "user": {"id": 101, "login": "reviewer"}},
        "sender": {"id": 101, "login": "reviewer"},
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"secret", raw, hashlib.sha256).hexdigest()
    ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "agent-loop-comment",
            "X-GitHub-Event": "issue_comment",
        },
        body=raw,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    GitHubWebhookProcessor(
        ledger, repository_slug="acme/forecasts", promotion_app_id="1234"
    ).process("agent-loop-comment")
    prepared = GitHubSlackMirror(ledger, cards).prepare("agent-loop-comment")
    assert prepared["summary"] is None
    assert cards.get(changeset["id"])["phase"] == "held"
    assert "human direction is required" in cards.get(changeset["id"])["next_action"]


def test_discussion_limit_values_must_be_positive():
    with pytest.raises(ValidationError, match="positive"):
        DiscussionLimits(max_comments=0)
