from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl
from forecasting.models import LedgerNotFoundError, ValidationError


def _control(tmp_path):
    return ChangeControl(ForecastLedger(tmp_path / "forecasting.db"))


def _thread(control, **overrides):
    values = {
        "workspace_id": "desk_1",
        "slack_team_id": "T1",
        "slack_channel_id": "C1",
        "slack_thread_ts": "1710000000.000001",
        "owner_id": "owner_1",
        "agent_instance_id": "agent_1",
        "agent_persona": "Mira",
    }
    values.update(overrides)
    return control.thread_changeset(**values)


def _binding(control, **overrides):
    values = {
        "owner_id": "owner_1",
        "slack_team_id": "T1",
        "slack_user_id": "U1",
        "agent_instance_id": "agent_1",
        "agent_persona": "Mira",
        "github_user_id": "101",
        "github_node_id": "MDQ6VXNlcjEwMQ==",
        "github_login": "octoforecaster",
    }
    values.update(overrides)
    return control.bind_identity(**values)


def test_thread_maps_concurrently_to_one_changeset_and_secret_free_branch(tmp_path):
    control = _control(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        rows = list(executor.map(lambda _: _thread(control), range(4)))
    assert len({row["changeset_id"] for row in rows}) == 1
    assert len({row["branch"] for row in rows}) == 1
    assert rows[0]["branch"] == f"forecast/changesets/{rows[0]['changeset_id']}"
    assert "1710000000" not in rows[0]["branch"]


def test_terminal_thread_changeset_starts_next_generation(tmp_path):
    control = _control(tmp_path)
    first = _thread(control)
    control.transition(first["changeset_id"], "abandoned")
    second = _thread(control)
    assert second["generation"] == 1
    assert second["changeset_id"] != first["changeset_id"]


def test_persona_can_change_without_switching_owner_or_github_identity(tmp_path):
    control = _control(tmp_path)
    first = _binding(control)
    renamed = _binding(control, agent_persona="Nova", agent_avatar_url="https://example.test/nova.png")
    assert renamed["id"] == first["id"]
    assert renamed["agent_persona"] == "Nova"
    assert renamed["owner_id"] == "owner_1"
    assert renamed["github_user_id"] == "101"

    with pytest.raises(ValidationError, match="different GitHub"):
        _binding(control, github_user_id="202", github_node_id="different")
    with pytest.raises(ValidationError, match="another owner"):
        _binding(control, owner_id="owner_2")


def test_owner_can_bind_multiple_personas_but_revocation_blocks_writes(tmp_path):
    control = _control(tmp_path)
    _binding(control)
    second = _binding(
        control,
        agent_instance_id="agent_2",
        agent_persona="Atlas",
        slack_user_id="U1",
    )
    assert second["owner_id"] == "owner_1"
    control.revoke_identity(second["id"])
    with pytest.raises(LedgerNotFoundError, match="no active"):
        control.resolve_identity(
            slack_team_id="T1", slack_user_id="U1", agent_instance_id="agent_2"
        )


def test_contribution_attests_all_identity_layers_and_is_idempotent(tmp_path):
    control = _control(tmp_path)
    binding = _binding(control)
    thread = _thread(control)
    first = control.record_contribution(
        thread["changeset_id"],
        idempotency_key="slack-event-1",
        binding=binding,
        actor_kind="agent",
        commit_sha="a" * 40,
    )
    second = control.record_contribution(
        thread["changeset_id"],
        idempotency_key="slack-event-1",
        binding=binding,
        actor_kind="agent",
        commit_sha="a" * 40,
    )
    assert first["id"] == second["id"]
    assert first["attestation"] == {
        "human_owner": "owner_1",
        "github_actor": "101",
        "agent_instance": "agent_1",
        "agent_persona": "Mira",
        "actor_kind": "agent",
        "changeset_id": thread["changeset_id"],
        "commit_sha": "a" * 40,
        "metadata": {},
    }
    with pytest.raises(ValidationError, match="replayed"):
        control.record_contribution(
            thread["changeset_id"],
            idempotency_key="slack-event-1",
            binding=binding,
            actor_kind="human",
        )
