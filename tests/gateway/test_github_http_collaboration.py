from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import pytest

from gateway.config import PlatformConfig
from gateway.platforms.api_server import APIServerAdapter
from gateway.run import GatewayRunner


class _Request:
    def __init__(self, *, body=b"{}", headers=None, payload=None, query=None):
        self._body = body
        self.headers = headers or {}
        self._payload = payload
        self.query = query or {}

    async def read(self):
        return self._body

    async def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_github_webhook_is_persisted_before_async_processing():
    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    order = []

    def ingest(headers, body):
        order.append(("ingest", headers["X-GitHub-Delivery"], body))
        return {"delivery_id": "delivery-1", "state": "pending"}

    def process(delivery_id):
        order.append(("process", delivery_id))

    adapter.set_github_collaboration_handlers(ingest=ingest, process=process)
    response = await adapter._handle_github_webhook(
        _Request(body=b'{"action":"opened"}', headers={"X-GitHub-Delivery": "delivery-1"})
    )
    await asyncio.sleep(0.05)

    assert response.status == 202
    assert json.loads(response.body)["delivery_id"] == "delivery-1"
    assert [item[0] for item in order] == ["ingest", "process"]


@pytest.mark.asyncio
async def test_github_webhook_rejects_forged_signature_without_processing():
    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    processed = []

    def reject(_headers, _body):
        raise PermissionError("forged")

    adapter.set_github_collaboration_handlers(
        ingest=reject,
        process=lambda delivery_id: processed.append(delivery_id),
    )
    response = await adapter._handle_github_webhook(_Request())

    assert response.status == 401
    assert processed == []


@pytest.mark.asyncio
async def test_github_oauth_begin_requires_api_auth_and_callback_returns_identity():
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "api-secret"}))
    adapter.set_github_collaboration_handlers(
        ingest=lambda _headers, _body: {},
        process=lambda _delivery_id: None,
        oauth_begin=lambda payload: {"authorization_url": "https://github.test/auth", **payload},
        oauth_complete=lambda state, code: {
            "owner_id": "owner-1",
            "github_login": f"octocat-{code}",
            "agent_persona": state,
        },
    )
    denied = await adapter._handle_github_oauth_begin(_Request(payload={"owner_id": "owner-1"}))
    allowed = await adapter._handle_github_oauth_begin(
        _Request(
            headers={"Authorization": "Bearer api-secret"},
            payload={"owner_id": "owner-1"},
        )
    )
    callback = await adapter._handle_github_oauth_callback(
        _Request(query={"state": "Mira", "code": "123"})
    )

    assert denied.status == 401
    assert allowed.status == 201
    assert json.loads(callback.body)["github_login"] == "octocat-123"


@pytest.mark.asyncio
async def test_github_installation_begin_requires_auth_and_callback_validates_state():
    adapter = APIServerAdapter(PlatformConfig(enabled=True, extra={"key": "api-secret"}))
    adapter.set_github_collaboration_handlers(
        ingest=lambda _headers, _body: {},
        process=lambda _delivery_id: None,
        installation_begin=lambda: {"installation_url": "https://github.test/install"},
        installation_complete=lambda state, installation_id: {
            "status": "installed",
            "installation_id": installation_id,
            "state_seen": state,
        },
    )
    denied = await adapter._handle_github_installation_begin(_Request())
    allowed = await adapter._handle_github_installation_begin(
        _Request(headers={"Authorization": "Bearer api-secret"})
    )
    invalid = await adapter._handle_github_installation_callback(_Request(query={}))
    callback = await adapter._handle_github_installation_callback(
        _Request(query={"state": "one-time", "installation_id": "77"})
    )

    assert denied.status == 401
    assert allowed.status == 201
    assert invalid.status == 400
    assert json.loads(callback.body)["installation_id"] == "77"


def test_github_route_paths_fail_closed():
    adapter = APIServerAdapter(PlatformConfig(enabled=True))
    with pytest.raises(ValueError, match="unsafe"):
        adapter.set_github_collaboration_handlers(
            ingest=lambda _headers, _body: {},
            process=lambda _delivery_id: None,
            webhook_path="/api/../escape",
        )
    with pytest.raises(ValueError, match="unsafe"):
        adapter.set_github_collaboration_handlers(
            ingest=lambda _headers, _body: {},
            process=lambda _delivery_id: None,
            installation_callback_path="../escape",
        )


def test_gateway_wires_signed_github_ingress_before_connect(tmp_path, monkeypatch):
    from forecasting import ForecastLedger
    from forecasting.change_control import ChangeControl, LedgerOperation

    ledger = ForecastLedger(tmp_path / "ledger.db")
    control = ChangeControl(ledger)
    changeset = control.create_changeset(workspace_id="desk_1")
    control.add_operation(
        changeset["id"],
        LedgerOperation(
            id="document_1",
            kind="document.update",
            target_ref="brief_1",
            payload={"path": "documents/brief.md", "content": "Recovered."},
        ),
    )
    control.add_decision_record(
        changeset["id"], conclusion="Recover the merged portable document update."
    )
    for state in (
        "ready",
        "publishing",
        "review_open",
        "checks_running",
        "merge_ready",
        "merged_apply_pending",
    ):
        fields = (
            {"merge_sha": "merge-1"}
            if state == "merged_apply_pending"
            else ({"metadata": {"checks_passed": True}} if state == "merge_ready" else None)
        )
        control.transition(changeset["id"], state, fields=fields)
    config = {
        "collaboration": {
            "enabled": True,
            "github": {
                "enabled": True,
                "app_id": "1234",
                "webhook_path": "/api/webhooks/github",
            },
            "repository": {"slug": "acme/forecasts", "workspace_id": "desk_1"},
        }
    }
    monkeypatch.setattr("superforecasting_agent.runtime.config.load_config", lambda: config)
    monkeypatch.setattr("forecasting.ForecastLedger", lambda: ledger)
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "webhook-secret")
    captured = {}

    class Adapter:
        def set_github_collaboration_handlers(self, **handlers):
            captured.update(handlers)

    GatewayRunner.__new__(GatewayRunner)._configure_github_http_collaboration(Adapter())
    body = json.dumps(
        {"action": "opened", "repository": {"id": 42, "full_name": "acme/forecasts"}},
        sort_keys=True,
    ).encode()
    signature = "sha256=" + hmac.new(b"webhook-secret", body, hashlib.sha256).hexdigest()
    delivery = captured["ingest"](
        {
            "X-Hub-Signature-256": signature,
            "X-GitHub-Delivery": "delivery-1",
            "X-GitHub-Event": "pull_request",
        },
        body,
    )

    assert captured["webhook_path"] == "/api/webhooks/github"
    assert captured["installation_begin_path"] == "/api/install/github/begin"
    assert captured["installation_callback_path"] == "/api/install/github/callback"
    assert delivery["state"] == "pending"
    assert control.get_changeset(changeset["id"])["status"] == "applied"
