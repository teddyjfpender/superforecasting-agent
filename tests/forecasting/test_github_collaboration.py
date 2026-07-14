from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.github.auth import GitHubOAuthService
from forecasting.github.capabilities import GitHubCapabilityBroker, GitHubPermissionError
from forecasting.github.events import GitHubWebhookProcessor, record_github_origin
from forecasting.github.slack_sync import GitHubSlackMirror
from forecasting.github.webhooks import ingest_github_webhook, mark_delivery_processed
from forecasting.models import LedgerNotFoundError, ValidationError
from forecasting.slack_collaboration import SlackChangesetCardService


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
    assert first["redelivery_count"] == 0
    assert second["redelivery_count"] == 1
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


def test_capability_binds_one_exact_owner_fork_without_repository_confusion(tmp_path):
    control, binding, changeset, _, _ = _capability_fixture(tmp_path)
    broker = GitHubCapabilityBroker(
        control.ledger,
        repository_slug="acme/forecasts",
        additional_repository_slugs=["verified-user/forecasts"],
        signing_key=b"f" * 32,
        token_provider=lambda binding_id: f"ghu_control_plane_{binding_id}_123456789",
        request=lambda method, url, **kwargs: _Response(
            {"full_name": "verified-user/forecasts", "owner": {"id": 101}}
        ),
    )
    fork_path = "/repos/verified-user/forecasts"
    capability = broker.issue(
        changeset_id=changeset["id"], identity_binding_id=binding["id"],
        actor_kind="agent", action="repository.read", method="GET", path=fork_path,
    )
    assert broker.execute(capability, method="GET", path=fork_path)["status_code"] == 200
    with pytest.raises(PermissionError, match="another repository"):
        broker.issue(
            changeset_id=changeset["id"], identity_binding_id=binding["id"],
            actor_kind="agent", action="repository.read", method="GET",
            path="/repos/attacker/forecasts",
        )
    with pytest.raises(PermissionError, match="canonical repository"):
        broker.issue(
            changeset_id=changeset["id"], identity_binding_id=binding["id"],
            actor_kind="agent", action="repository.fork", method="POST",
            path="/repos/verified-user/forecasts/forks",
        )


@pytest.mark.parametrize("status_code", [403, 404])
def test_capability_exposes_only_redacted_permission_failure_for_fallback(
    tmp_path, status_code
):
    control, binding, changeset, _, _ = _capability_fixture(tmp_path)
    broker = GitHubCapabilityBroker(
        control.ledger,
        repository_slug="acme/forecasts",
        signing_key=b"p" * 32,
        token_provider=lambda binding_id: f"ghu_control_plane_{binding_id}_123456789",
        request=lambda method, url, **kwargs: _Response(
            {"message": "denied ghu_secret_value_12345678901234567890"},
            status=status_code,
        ),
    )
    path = "/repos/acme/forecasts/git/blobs"
    capability = broker.issue(
        changeset_id=changeset["id"], identity_binding_id=binding["id"],
        actor_kind="agent", action="branch.write", method="POST", path=path,
    )
    with pytest.raises(GitHubPermissionError, match="denied branch.write") as failure:
        broker.execute(capability, method="POST", path=path, json_body={"content": "x"})
    assert failure.value.status_code == status_code
    assert "secret" not in str(failure.value)


def _published_changeset(tmp_path, *, status="review_open"):
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
    control.transition(
        changeset["id"],
        "review_open",
        fields={"pr_number": 7, "head_sha": "head-7", "branch": "forecast/changesets/7"},
    )
    if status == "merge_ready":
        control.transition(changeset["id"], "checks_running")
        control.transition(changeset["id"], "merge_ready")
    return ledger, control, binding, control.get_changeset(changeset["id"])


def test_webhook_processor_records_direct_human_review_idempotently(tmp_path):
    ledger, control, _, changeset = _published_changeset(tmp_path)
    payload = {
        "action": "submitted",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "pull_request": {
            "number": 7,
            "head": {"ref": changeset["branch"], "sha": "head-7"},
            "base": {"ref": "main", "sha": "base"},
        },
        "review": {
            "id": 88,
            "state": "approved",
            "commit_id": "head-7",
            "user": {"id": 101, "node_id": "node-101", "login": "reviewer"},
        },
        "sender": {"id": 101, "node_id": "node-101", "login": "reviewer"},
    }
    body, signature = _signed("secret", payload)
    row = ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "review-delivery",
            "X-GitHub-Event": "pull_request_review",
        },
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    processor = GitHubWebhookProcessor(
        ledger,
        repository_slug="acme/forecasts",
        promotion_app_id="1234",
    )
    assert processor.process(row["delivery_id"])["state"] == "processed"
    assert processor.process(row["delivery_id"])["state"] == "processed"
    reviews = control.list_reviews(changeset["id"])
    assert len(reviews) == 1
    assert reviews[0]["actor_kind"] == "human"
    assert reviews[0]["owner_id"] == "owner_1"


def test_agent_origin_review_never_becomes_human_approval(tmp_path):
    ledger, control, binding, changeset = _published_changeset(tmp_path)
    record_github_origin(
        ledger,
        remote_kind="review",
        remote_id="89",
        changeset_id=changeset["id"],
        actor_kind="agent",
        identity_binding_id=binding["id"],
        correlation_id="slack-action-1",
    )
    payload = {
        "action": "submitted",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "pull_request": {
            "number": 7,
            "head": {"ref": changeset["branch"], "sha": "head-7"},
            "base": {"ref": "main", "sha": "base"},
        },
        "review": {
            "id": 89,
            "state": "approved",
            "commit_id": "head-7",
            "user": {"id": 101, "node_id": "node-101", "login": "reviewer"},
        },
        "sender": {"id": 101, "node_id": "node-101", "login": "reviewer"},
    }
    body, signature = _signed("secret", payload)
    ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "agent-review",
            "X-GitHub-Event": "pull_request_review",
        },
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    GitHubWebhookProcessor(
        ledger,
        repository_slug="acme/forecasts",
        promotion_app_id="1234",
    ).process("agent-review")

    review = control.list_reviews(changeset["id"])[0]
    assert review["actor_kind"] == "agent"
    assert review["agent_persona"] == "Mira"
    assert control.quorum(changeset["id"]).approved_owner_ids == ()


def test_merge_webhook_sets_apply_pending_without_claiming_ledger_application(tmp_path):
    ledger, control, _, changeset = _published_changeset(tmp_path, status="merge_ready")
    payload = {
        "action": "closed",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "pull_request": {
            "number": 7,
            "merged": True,
            "merge_commit_sha": "merge-7",
            "head": {"ref": changeset["branch"], "sha": "head-7"},
            "base": {"ref": "main", "sha": "base"},
        },
        "sender": {"id": 101, "node_id": "node-101", "login": "reviewer"},
    }
    body, signature = _signed("secret", payload)
    ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "merge-delivery",
            "X-GitHub-Event": "pull_request",
        },
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    GitHubWebhookProcessor(
        ledger,
        repository_slug="acme/forecasts",
        promotion_app_id="1234",
    ).process("merge-delivery")
    merged = control.get_changeset(changeset["id"])
    assert merged["status"] == "merged_apply_pending"
    assert merged["merge_sha"] == "merge-7"
    assert merged["applied_revision"] is None


def test_merge_group_tracks_queue_state_idempotently(tmp_path):
    ledger, control, _, changeset = _published_changeset(tmp_path, status="merge_ready")
    payload = {
        "action": "checks_requested",
        "repository": {"id": 42, "full_name": "acme/forecasts"},
        "merge_group": {
            "id": 901,
            "head_ref": "refs/heads/gh-readonly-queue/main/pr-7-deadbeef",
            "head_sha": "merge-group-head",
            "base_ref": "refs/heads/main",
            "base_sha": "base",
        },
    }
    body, signature = _signed("secret", payload)
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Delivery": "merge-group-1",
        "X-GitHub-Event": "merge_group",
    }
    ingest_github_webhook(
        ledger,
        headers=headers,
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    ingest_github_webhook(
        ledger,
        headers=headers,
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    processor = GitHubWebhookProcessor(
        ledger, repository_slug="acme/forecasts", promotion_app_id="1234"
    )

    processor.process("merge-group-1")
    processor.process("merge-group-1")

    queued = control.get_changeset(changeset["id"])
    assert queued["status"] == "merge_queued"
    assert queued["metadata"]["merge_group"]["head_sha"] == "merge-group-head"
    with ledger._connect() as conn:
        redeliveries = conn.execute(
            """SELECT redelivery_count FROM github_webhook_deliveries
               WHERE delivery_id = 'merge-group-1'"""
        ).fetchone()[0]
    assert redeliveries == 1


def test_merge_apply_reconciler_stops_retrying_semantic_failures(tmp_path):
    from forecasting.github import MergeApplyReconciler

    ledger, control, _, changeset = _published_changeset(tmp_path, status="merge_ready")
    control.transition(
        changeset["id"],
        "merged_apply_pending",
        fields={"merge_sha": "merge-7"},
    )
    reconciler = MergeApplyReconciler(ledger)

    first = reconciler.reconcile(changeset["id"])
    second = reconciler.reconcile(changeset["id"])

    assert first == {
        "changeset_id": changeset["id"],
        "state": "apply_failed",
        "retryable": False,
        "reason": "application_failed",
    }
    assert second["state"] == "blocked"
    assert second["reason"] == "semantic_failure_requires_superseding_changeset"
    with ledger._connect() as conn:
        attempts = conn.execute(
            "SELECT diagnostic FROM ledger_apply_attempts WHERE changeset_id = ?",
            (changeset["id"],),
        ).fetchall()
    assert len(attempts) == 1
    assert attempts[0]["diagnostic"].startswith("semantic:")


def test_github_comment_mirrors_to_slack_card_durably_without_body(tmp_path):
    ledger, _, _, changeset = _published_changeset(tmp_path)
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
        "issue": {
            "id": 70,
            "number": 7,
            "html_url": "https://github.test/acme/forecasts/pull/7",
            "pull_request": {"url": "https://api.github.test/repos/acme/forecasts/pulls/7"},
        },
        "comment": {
            "id": 99,
            "body": "untrusted body must not be persisted or mirrored",
            "html_url": "https://github.test/acme/forecasts/pull/7#issuecomment-99",
            "user": {"id": 303, "login": "reviewer-three"},
        },
        "sender": {"id": 303, "login": "reviewer-three"},
    }
    body, signature = _signed("secret", payload)
    ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "comment-delivery",
            "X-GitHub-Event": "issue_comment",
        },
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    GitHubWebhookProcessor(
        ledger,
        repository_slug="acme/forecasts",
        promotion_app_id="1234",
    ).process("comment-delivery")
    mirror = GitHubSlackMirror(ledger, cards)

    prepared = mirror.prepare("comment-delivery")

    assert "reviewer-three added a comment" in prepared["summary"]
    assert "untrusted body" not in json.dumps(prepared)
    assert cards.get(changeset["id"])["state"]["github_correlation_id"] == "comment-delivery"
    assert mirror.pending() == ["comment-delivery"]
    mirror.mark("comment-delivery", delivered=True)
    assert mirror.prepare("comment-delivery") is None
    assert mirror.pending() == []
