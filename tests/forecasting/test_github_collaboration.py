from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.github.auth import GitHubOAuthService
from forecasting.github.capabilities import GitHubCapabilityBroker
from forecasting.github.webhooks import ingest_github_webhook, mark_delivery_processed
from forecasting.models import LedgerNotFoundError, ValidationError


class _Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.status_code = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("GitHub request failed")

    def json(self):
        return self.payload


def _service(tmp_path, *, posts=None, user=None):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    post_values = list(
        posts
        or [
            {
                "access_token": "ghu_access_token_value_123456789",
                "refresh_token": "ghr_refresh_token_value_123456789",
                "expires_in": 28_800,
                "refresh_token_expires_in": 15_897_600,
                "token_type": "bearer",
            }
        ]
    )
    calls = []

    def post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return _Response(post_values.pop(0))

    def get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return _Response(
            user
            or {"id": 101, "node_id": "MDQ6VXNlcjEwMQ==", "login": "verified-user"}
        )

    return (
        GitHubOAuthService(
            ledger,
            client_id="Iv1.client",
            client_secret="client-secret",
            token_key=b"k" * 32,
            http_post=post,
            http_get=get,
        ),
        calls,
    )


def test_oauth_uses_state_pkce_verified_user_and_encrypted_tokens(tmp_path):
    service, calls = _service(tmp_path)
    started = service.begin(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        redirect_uri="https://forecast.example/api/oauth/github/callback",
    )
    query = parse_qs(urlsplit(started["authorization_url"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == [started["state"]]
    assert "code_challenge" in query

    binding = service.complete(
        state=started["state"],
        code="one-time-code",
        redirect_uri="https://forecast.example/api/oauth/github/callback",
    )

    assert binding["github_user_id"] == "101"
    assert binding["github_node_id"] == "MDQ6VXNlcjEwMQ=="
    assert binding["github_login"] == "verified-user"
    assert calls[1][1].endswith("/user")
    with service.ledger._connect() as conn:
        token_row = conn.execute("SELECT * FROM github_user_tokens").fetchone()
    assert "ghu_access_token" not in token_row["access_ciphertext"]
    assert "ghr_refresh_token" not in token_row["refresh_ciphertext"]
    assert service.control_plane_token(binding["id"]) == "ghu_access_token_value_123456789"
    with pytest.raises(ValidationError, match="already used"):
        service.complete(
            state=started["state"],
            code="replay",
            redirect_uri="https://forecast.example/api/oauth/github/callback",
        )


def test_oauth_callback_rejects_mismatched_uri_without_consuming_state(tmp_path):
    service, _ = _service(tmp_path)
    started = service.begin(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        redirect_uri="https://forecast.example/callback",
    )
    with pytest.raises(ValidationError, match="does not match"):
        service.complete(
            state=started["state"],
            code="code",
            redirect_uri="https://attacker.example/callback",
        )
    service.complete(
        state=started["state"],
        code="code",
        redirect_uri="https://forecast.example/callback",
    )


def test_oauth_refreshes_expired_access_and_local_revoke_blocks_use(tmp_path):
    service, calls = _service(
        tmp_path,
        posts=[
            {
                "access_token": "expired-access-token",
                "refresh_token": "refresh-token",
                "expires_in": 0,
                "refresh_token_expires_in": 3_600,
            },
            {
                "access_token": "fresh-access-token",
                "refresh_token": "fresh-refresh-token",
                "expires_in": 3_600,
                "refresh_token_expires_in": 7_200,
            },
        ],
    )
    started = service.begin(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        redirect_uri="https://forecast.example/callback",
    )
    binding = service.complete(
        state=started["state"],
        code="code",
        redirect_uri="https://forecast.example/callback",
    )
    assert service.control_plane_token(binding["id"]) == "fresh-access-token"
    refresh_call = [call for call in calls if call[0] == "post"][-1]
    assert refresh_call[2]["data"]["grant_type"] == "refresh_token"

    service.revoke_local(binding["id"])
    with pytest.raises(LedgerNotFoundError, match="no active"):
        service.control_plane_token(binding["id"])


def _signed(secret, payload):
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, signature


def test_webhook_verifies_before_persisting_and_deduplicates_delivery(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    secret = "It's a Secret to Everybody"
    payload = {
        "action": "submitted",
        "installation": {"id": 77},
        "repository": {"id": 42, "full_name": "acme/forecasts", "private": True},
        "review": {
            "id": 9,
            "state": "approved",
            "body": "private review body ghu_not_persisted_123456789",
            "user": {"id": 101, "node_id": "node", "login": "reviewer"},
        },
        "sender": {"id": 101, "node_id": "node", "login": "reviewer"},
    }
    body, signature = _signed(secret, payload)
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-1",
        "X-GitHub-Event": "pull_request_review",
    }
    first = ingest_github_webhook(
        ledger,
        headers=headers,
        body=body,
        secret=secret,
        repository_slug="acme/forecasts",
        repository_id="42",
    )
    second = ingest_github_webhook(
        ledger,
        headers=headers,
        body=body,
        secret=secret,
        repository_slug="acme/forecasts",
        repository_id="42",
    )
    assert first["delivery_id"] == second["delivery_id"]
    assert first["state"] == "pending"
    assert "private review body" not in json.dumps(first["payload"])
    assert mark_delivery_processed(ledger, "delivery-1")["state"] == "processed"
    assert mark_delivery_processed(ledger, "delivery-1")["state"] == "processed"
    with ledger._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM github_webhook_deliveries").fetchone()[0] == 1


def test_webhook_quarantines_wrong_repository_and_rejects_bad_signature(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    body, signature = _signed(
        "secret",
        {"repository": {"id": 99, "full_name": "other/repo"}, "action": "opened"},
    )
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "delivery-wrong-repo",
        "X-GitHub-Event": "pull_request",
    }
    row = ingest_github_webhook(
        ledger,
        headers=headers,
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    assert row["state"] == "quarantined"
    assert row["quarantine_reason"] == "unauthorized_repository"

    with pytest.raises(PermissionError, match="did not match"):
        ingest_github_webhook(
            ledger,
            headers={**headers, "X-GitHub-Delivery": "bad", "X-Hub-Signature-256": "sha256=0"},
            body=body,
            secret="secret",
            repository_slug="acme/forecasts",
        )
    with ledger._connect() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM github_webhook_deliveries WHERE delivery_id = 'bad'"
        ).fetchone()[0] == 0


def _capability_fixture(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        github_user_id="101",
        github_node_id="MDQ6VXNlcjEwMQ==",
        github_login="verified-user",
    )
    changeset = control.create_changeset(
        workspace_id="desk_1",
        author_owner_ids=["owner_1"],
    )
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _Response(
            {
                "id": 55,
                "access_token": "ghu_response_token_12345678901234567890",
                "nested": {"message": "Bearer secret-token-value-123456789"},
            },
            status=201,
        )

    broker = GitHubCapabilityBroker(
        ledger,
        repository_slug="acme/forecasts",
        signing_key=b"s" * 32,
        token_provider=lambda binding_id: f"ghu_control_plane_{binding_id}_123456789",
        request=request,
    )
    return control, binding, changeset, broker, calls


def test_capability_executes_once_with_control_plane_token_and_full_audit(tmp_path):
    control, binding, changeset, broker, calls = _capability_fixture(tmp_path)
    path = "/repos/acme/forecasts/issues/7/comments"
    capability = broker.issue(
        changeset_id=changeset["id"],
        identity_binding_id=binding["id"],
        actor_kind="agent",
        action="comment.write",
        method="POST",
        path=path,
    )
    result = broker.execute(capability, method="POST", path=path, json_body={"body": "ready"})

    assert result == {
        "status_code": 201,
        "body": {
            "id": 55,
            "access_token": "[REDACTED]",
            "nested": {"message": "[REDACTED]"},
        },
    }
    assert calls[0][2]["headers"]["Authorization"].startswith("Bearer ghu_control_plane_")
    assert "Authorization" not in json.dumps(result)
    with control.ledger._connect() as conn:
        audit = dict(conn.execute("SELECT * FROM github_action_audit").fetchone())
    assert audit["human_owner"] == "owner_1"
    assert audit["github_actor"] == "101"
    assert audit["agent_instance"] == "agent_1"
    assert audit["agent_persona"] == "Mira"
    assert audit["actor_kind"] == "agent"

    with pytest.raises(PermissionError, match="already been used"):
        broker.execute(capability, method="POST", path=path, json_body={"body": "again"})
    assert len(calls) == 1


def test_capability_rejects_tampering_path_confusion_and_revoked_identity(tmp_path):
    control, binding, changeset, broker, calls = _capability_fixture(tmp_path)
    path = "/repos/acme/forecasts/pulls"
    capability = broker.issue(
        changeset_id=changeset["id"],
        identity_binding_id=binding["id"],
        actor_kind="human",
        action="pull_request.write",
        method="POST",
        path=path,
    )
    with pytest.raises(PermissionError, match="method or path"):
        broker.execute(capability, method="POST", path="/repos/acme/forecasts/pulls/1")
    with pytest.raises(PermissionError, match="signature"):
        broker.execute(capability[:-1] + "x", method="POST", path=path)
    with pytest.raises(PermissionError, match="another repository"):
        broker.issue(
            changeset_id=changeset["id"],
            identity_binding_id=binding["id"],
            actor_kind="agent",
            action="pull_request.write",
            method="POST",
            path="/repos/other/forecasts/pulls",
        )

    control.revoke_identity(binding["id"])
    with pytest.raises(PermissionError, match="revoked"):
        broker.execute(capability, method="POST", path=path)
    assert calls == []
