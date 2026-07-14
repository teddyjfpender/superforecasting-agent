from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.change_control.trace_archive import capture_trace_archive
from forecasting.collaboration_health import collaboration_health
from forecasting.github.webhooks import ingest_github_webhook
from forecasting.slack_collaboration import SlackChangesetCardService


def test_collaboration_health_is_offline_safe_redacted_and_actionable(tmp_path):
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
        github_login="owner-one",
    )
    changeset = control.create_changeset(workspace_id="desk_1")
    for status in ("ready", "publishing", "review_open", "review_required"):
        control.transition(changeset["id"], status)
    cards = SlackChangesetCardService(ledger)
    cards.update(
        changeset["id"],
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1.1",
        phase="review_required",
        next_action="Review is required.",
        state={"heartbeat_expected": True},
    )
    control.record_transcript(
        changeset["id"],
        format="markdown",
        status="unsafe",
        digest="a" * 64,
        byte_size=0,
        safety_findings=[{"class": "github_token", "location": "message:1"}],
    )
    capture_trace_archive(
        ledger,
        changeset["id"],
        {"secret": "private trace body"},
        workspace_key=base64.urlsafe_b64encode(b"k" * 32).decode(),
        retention_days=0,
        object_dir=tmp_path / "private",
    )
    body = json.dumps(
        {"action": "opened", "repository": {"id": 42, "full_name": "acme/forecasts"}}
    ).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "pull_request",
    }
    for _ in range(2):
        ingest_github_webhook(
            ledger,
            headers=headers,
            body=body,
            secret="secret",
            repository_slug="acme/forecasts",
        )
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE github_webhook_deliveries SET received_at = '2020-01-01T00:00:00Z'"
        )
        conn.execute(
            "UPDATE slack_changeset_cards SET last_heartbeat_at = '2020-01-01T00:00:00Z'"
        )
        conn.execute(
            "UPDATE provenance_trace_archives SET retention_deadline = '2020-01-01T00:00:00Z'"
        )
        conn.execute(
            """INSERT INTO github_user_tokens
               (id, identity_binding_id, access_ciphertext, expires_at,
                refresh_expires_at, status, created_at, updated_at)
               VALUES ('token_1', ?, 'ciphertext-must-not-print',
                       '2020-01-01T00:00:00Z', '2020-01-02T00:00:00Z',
                       'active', '2020-01-01T00:00:00Z', '2020-01-01T00:00:00Z')""",
            (binding["id"],),
        )

    result = collaboration_health(
        ledger, now=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )

    assert result["metrics"]["webhook_pending"] == 1
    assert result["metrics"]["webhook_redeliveries"] == 1
    assert result["metrics"]["approval_waiting"] == 1
    assert result["metrics"]["slack_stale_cards"] == 1
    assert result["metrics"]["transcript_safety_failures"] == 1
    assert result["metrics"]["retention_overdue"] == 1
    assert result["metrics"]["github_tokens_expired_unrefreshable"] == 1
    assert {alert["code"] for alert in result["alerts"]} >= {
        "webhook_backlog",
        "stale_slack_card",
        "retention_overdue",
    }
    encoded = json.dumps(result)
    assert "private trace body" not in encoded
    assert "ciphertext-must-not-print" not in encoded
