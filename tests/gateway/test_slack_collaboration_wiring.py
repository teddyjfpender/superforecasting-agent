from __future__ import annotations

from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from gateway.run import GatewayRunner
from gateway.config import Platform


class _Slack:
    def __init__(self):
        self.message_handler = None
        self.action_handler = None
        self.upsert_changeset_card = AsyncMock(
            return_value=type("Result", (), {"success": True, "message_id": "card-1"})()
        )

    def set_changeset_message_handler(self, handler):
        self.message_handler = handler

    def set_changeset_action_handler(self, handler):
        self.action_handler = handler


@pytest.mark.asyncio
async def test_gateway_wires_thread_changeset_card_without_resetting_existing_phase(
    tmp_path, monkeypatch
):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    control = ChangeControl(ledger)
    control.bind_identity(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        github_user_id="101",
        github_node_id="node-101",
        github_login="reviewer",
    )
    config = {
        "collaboration": {
            "enabled": True,
            "github": {"enabled": False},
            "repository": {
                "slug": "acme/forecasts",
                "workspace_id": "desk_1",
                "default_branch": "main",
            },
        }
    }
    monkeypatch.setenv("SLACK_CHANGESET_ACTION_SIGNING_KEY", "test-action-secret")
    runner = GatewayRunner.__new__(GatewayRunner)
    slack = _Slack()
    runner.adapters = {Platform.SLACK: slack}
    with patch("hermes_cli.config.load_config", return_value=config), patch(
        "forecasting.ForecastLedger", return_value=ledger
    ):
        runner._configure_slack_changeset_collaboration(slack)

    assert slack.message_handler is not None
    assert slack.action_handler is not None
    context = {
        "team_id": "T1",
        "channel_id": "C1",
        "thread_ts": "1710000000.000001",
        "message_ts": "1710000001.000001",
        "user_id": "U1",
        "text": "Research this forecast.",
    }
    await slack.message_handler(context)
    services = runner._slack_changeset_services
    changeset = services["control"].list_changesets(workspace_id="desk_1")[0]
    card = services["cards"].get(changeset["id"])
    assert card["phase"] == "researching"
    assert card["message_ts"] == "card-1"

    services["cards"].update(
        changeset["id"],
        slack_team_id="T1",
        slack_channel_id="C1",
        slack_thread_ts="1710000000.000001",
        phase="review_required",
        next_action="One human approval is required.",
    )
    await slack.message_handler(context)
    assert services["cards"].get(changeset["id"])["phase"] == "review_required"
    assert slack.upsert_changeset_card.await_count == 2

    event = SimpleNamespace(raw_message={"team": "T1", "channel": "C1", "ts": "1710000000.000001"})
    source = SimpleNamespace(
        platform=Platform.SLACK,
        chat_id="C1",
        thread_id="1710000000.000001",
    )
    runner._update_slack_changeset_progress(
        event,
        source,
        event_type="tool.started",
        tool_name="web_search",
    )
    working = services["cards"].get(changeset["id"])
    assert working["state"]["heartbeat_expected"] is True
    assert "web_search" in working["next_action"]

    await runner._settle_slack_changeset_card(event, source, run_status="completed")
    waiting = services["cards"].get(changeset["id"])
    assert waiting["state"]["heartbeat_expected"] is False
    assert waiting["state"]["run_state"] == "completed"
    with ledger._connect() as conn:
        presence = conn.execute(
            "SELECT presence FROM slack_changeset_presence WHERE changeset_id = ?",
            (changeset["id"],),
        ).fetchone()["presence"]
    assert presence == "waiting"
