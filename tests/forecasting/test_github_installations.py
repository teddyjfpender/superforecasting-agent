from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import parse_qs, urlsplit

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.github.capabilities import GitHubCapabilityBroker
from forecasting.github.events import GitHubWebhookProcessor
from forecasting.github.installations import (
    GitHubInstallationRegistry,
    installation_url,
)
from forecasting.github.webhooks import ingest_github_webhook
from forecasting.models import ValidationError


def _deliver(ledger, registry, *, delivery_id, event_type, action, extra=None):
    payload = {
        "action": action,
        "installation": {
            "id": 77,
            "app_id": 1234,
            "account": {
                "id": 900,
                "node_id": "account-node-900",
                "login": "acme",
                "type": "Organization",
            },
            "target_type": "Organization",
            "repository_selection": "selected",
            "permissions": {
                "contents": "write",
                "pull_requests": "write",
                "issues": "write",
                "checks": "write",
            },
            "suspended_at": None,
        },
        **(extra or {}),
    }
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    ingested = ingest_github_webhook(
        ledger,
        headers={
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": delivery_id,
            "X-GitHub-Event": event_type,
        },
        body=body,
        secret="secret",
        repository_slug="acme/forecasts",
    )
    GitHubWebhookProcessor(
        ledger,
        repository_slug="acme/forecasts",
        promotion_app_id="1234",
        installation_registry=registry,
    ).process(delivery_id)
    return ingested


def _repository():
    return {
        "id": 42,
        "node_id": "repo-node-42",
        "full_name": "acme/forecasts",
        "private": True,
        "html_url": "https://github.test/acme/forecasts",
    }


def test_signed_installation_webhook_grants_exact_repository_permissions(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )

    delivery = _deliver(
        ledger,
        registry,
        delivery_id="installation-created",
        event_type="installation",
        action="created",
        extra={"repositories": [_repository()]},
    )

    assert delivery["state"] == "pending"
    assert "github.test" not in json.dumps(delivery["payload"])
    for action in (
        "repository.read",
        "branch.write",
        "pull_request.write",
        "review.write",
        "comment.write",
        "repository.fork",
    ):
        registry.authorize("acme/forecasts", action)
    with pytest.raises(PermissionError, match="another repository"):
        registry.authorize("other/forecasts", "branch.write")
    status = registry.status()
    assert status[0]["installation_id"] == "77"
    assert status[0]["repository_id"] == "42"
    assert status[0]["private"] is True
    assert "token" not in json.dumps(status).lower()


def test_repository_removal_suspension_and_deletion_revoke_immediately(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )
    _deliver(
        ledger,
        registry,
        delivery_id="created",
        event_type="installation",
        action="created",
        extra={"repositories": [_repository()]},
    )
    _deliver(
        ledger,
        registry,
        delivery_id="removed",
        event_type="installation_repositories",
        action="removed",
        extra={"repositories_removed": [_repository()]},
    )
    with pytest.raises(PermissionError, match="not actively installed"):
        registry.authorize("acme/forecasts", "branch.write")

    _deliver(
        ledger,
        registry,
        delivery_id="added",
        event_type="installation_repositories",
        action="added",
        extra={"repositories_added": [_repository()]},
    )
    registry.authorize("acme/forecasts", "branch.write")
    _deliver(
        ledger,
        registry,
        delivery_id="suspended",
        event_type="installation",
        action="suspend",
    )
    with pytest.raises(PermissionError, match="not actively installed"):
        registry.authorize("acme/forecasts", "branch.write")
    _deliver(
        ledger,
        registry,
        delivery_id="unsuspended",
        event_type="installation",
        action="unsuspend",
        extra={"repositories": [_repository()]},
    )
    registry.authorize("acme/forecasts", "branch.write")
    _deliver(
        ledger,
        registry,
        delivery_id="deleted",
        event_type="installation",
        action="deleted",
    )
    with pytest.raises(PermissionError, match="not actively installed"):
        registry.authorize("acme/forecasts", "branch.write")


def test_app_permission_is_required_in_addition_to_user_authority(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )
    _deliver(
        ledger,
        registry,
        delivery_id="read-only",
        event_type="installation",
        action="created",
        extra={"repositories": [_repository()]},
    )
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE github_app_installations SET permissions = ?",
            (json.dumps({"contents": "read", "pull_requests": "read"}),),
        )

    registry.authorize("acme/forecasts", "repository.read")
    with pytest.raises(PermissionError, match="contents:write"):
        registry.authorize("acme/forecasts", "branch.write")
    with pytest.raises(PermissionError, match="issues:write"):
        registry.authorize("acme/forecasts", "comment.write")


def test_installation_rejects_wrong_app_and_safe_install_url(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )
    with pytest.raises(PermissionError, match="another App"):
        registry.apply(
            event_type="installation",
            action="created",
            payload={"installation": {"id": 77, "app_id": 9999}},
        )
    assert installation_url("forecast-desk") == (
        "https://github.com/apps/forecast-desk/installations/new"
    )
    with pytest.raises(ValidationError, match="slug"):
        installation_url("../../settings")


def test_installation_setup_state_is_short_lived_bound_and_single_use(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )
    expired = registry.begin(app_slug="forecast-desk")
    expired_state = parse_qs(urlsplit(expired["installation_url"]).query)["state"][0]
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE github_installation_states SET expires_at = '2020-01-01T00:00:00Z'"
        )
    with pytest.raises(ValidationError, match="expired"):
        registry.complete(state=expired_state, installation_id="77")

    begun = registry.begin(app_slug="forecast-desk")
    state = parse_qs(urlsplit(begun["installation_url"]).query)["state"][0]
    with pytest.raises(PermissionError, match="has not granted"):
        registry.complete(state=state, installation_id="77")
    _deliver(
        ledger,
        registry,
        delivery_id="setup-install",
        event_type="installation",
        action="created",
        extra={"repositories": [_repository()]},
    )
    assert registry.complete(state=state, installation_id="77") == {
        "status": "installed",
        "installation_id": "77",
        "repository": "acme/forecasts",
    }
    with pytest.raises(ValidationError, match="already used"):
        registry.complete(state=state, installation_id="77")


def test_capability_rechecks_installation_before_using_owner_token(tmp_path):
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
    registry = GitHubInstallationRegistry(
        ledger, app_id="1234", repository_slug="acme/forecasts"
    )
    token_calls = []
    broker = GitHubCapabilityBroker(
        ledger,
        repository_slug="acme/forecasts",
        signing_key=b"s" * 32,
        token_provider=lambda binding_id: (
            token_calls.append(binding_id) or "owner-token"
        ),
        installation_authorizer=registry.authorize,
        request=lambda *args, **kwargs: None,
    )
    path = "/repos/acme/forecasts/git/blobs"
    with pytest.raises(PermissionError, match="not actively installed"):
        broker.issue(
            changeset_id=changeset["id"],
            identity_binding_id=binding["id"],
            actor_kind="agent",
            action="branch.write",
            method="POST",
            path=path,
        )
    _deliver(
        ledger,
        registry,
        delivery_id="capability-install",
        event_type="installation",
        action="created",
        extra={"repositories": [_repository()]},
    )
    capability = broker.issue(
        changeset_id=changeset["id"],
        identity_binding_id=binding["id"],
        actor_kind="agent",
        action="branch.write",
        method="POST",
        path=path,
    )
    _deliver(
        ledger,
        registry,
        delivery_id="capability-remove",
        event_type="installation_repositories",
        action="removed",
        extra={"repositories_removed": [_repository()]},
    )
    with pytest.raises(PermissionError, match="not actively installed"):
        broker.execute(capability, method="POST", path=path, json_body={"content": "x"})
    assert token_calls == []
