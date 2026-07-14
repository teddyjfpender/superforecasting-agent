"""Slack-thread changeset ownership and cross-platform identity bindings."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from forecasting.change_control.models import content_digest
from forecasting.change_control.store import (
    create_changeset,
    get_changeset,
    transition_changeset,
)
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


_TERMINAL_CHANGESET_STATUSES = frozenset(
    {"applied", "rejected", "cancelled", "abandoned", "superseded"}
)


def get_or_create_thread_changeset(
    ledger: Any,
    *,
    workspace_id: str,
    slack_team_id: str,
    slack_channel_id: str,
    slack_thread_ts: str,
    owner_id: str,
    agent_instance_id: str,
    agent_persona: str,
) -> dict[str, Any]:
    """Map one Slack thread generation to exactly one changeset and branch."""

    required = {
        "workspace_id": workspace_id,
        "slack_team_id": slack_team_id,
        "slack_channel_id": slack_channel_id,
        "slack_thread_ts": slack_thread_ts,
        "owner_id": owner_id,
        "agent_instance_id": agent_instance_id,
        "agent_persona": agent_persona,
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValidationError(f"thread collaboration missing: {', '.join(missing)}")
    with ledger.transaction(immediate=True):
        with ledger._connect() as conn:
            latest = conn.execute(
                """SELECT t.*, c.status AS changeset_status
                   FROM collaboration_threads t
                   JOIN ledger_changesets c ON c.id = t.changeset_id
                   WHERE t.workspace_id = ? AND t.slack_team_id = ?
                     AND t.slack_channel_id = ? AND t.slack_thread_ts = ?
                   ORDER BY t.generation DESC LIMIT 1""",
                (workspace_id, slack_team_id, slack_channel_id, slack_thread_ts),
            ).fetchone()
        if latest is not None and latest["changeset_status"] not in _TERMINAL_CHANGESET_STATUSES:
            return _thread_row(latest)
        generation = 0 if latest is None else int(latest["generation"]) + 1
        changeset = create_changeset(
            ledger,
            workspace_id=workspace_id,
            author_owner_ids=[owner_id],
            author_identities=[
                {
                    "owner_id": owner_id,
                    "agent_instance_id": agent_instance_id,
                    "agent_persona": agent_persona,
                    "actor_kind": "agent",
                }
            ],
            slack_thread_key=f"slack:{slack_team_id}:{slack_channel_id}:{slack_thread_ts}",
            metadata={"thread_generation": generation},
        )
        branch = f"forecast/changesets/{changeset['id']}"
        transition_changeset(
            ledger,
            changeset["id"],
            changeset["status"],
            fields={"branch": branch},
        )
        now = utc_now_iso()
        thread_id = f"thread_{uuid.uuid4().hex[:16]}"
        with ledger._connect() as conn:
            conn.execute(
                """INSERT INTO collaboration_threads
                   (id, workspace_id, slack_team_id, slack_channel_id,
                    slack_thread_ts, generation, changeset_id, branch,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    thread_id,
                    workspace_id,
                    slack_team_id,
                    slack_channel_id,
                    slack_thread_ts,
                    generation,
                    changeset["id"],
                    branch,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                """SELECT t.*, c.status AS changeset_status
                   FROM collaboration_threads t
                   JOIN ledger_changesets c ON c.id = t.changeset_id WHERE t.id = ?""",
                (thread_id,),
            ).fetchone()
    return _thread_row(row)


def bind_identity(
    ledger: Any,
    *,
    owner_id: str,
    slack_team_id: str,
    slack_user_id: str,
    agent_instance_id: str,
    agent_persona: str,
    github_user_id: str,
    github_node_id: str,
    github_login: str,
    agent_avatar_url: str | None = None,
    slack_bot_user_id: str | None = None,
) -> dict[str, Any]:
    """Bind immutable owner/Slack/GitHub IDs; persona presentation may change."""

    values = {
        "owner_id": owner_id,
        "slack_team_id": slack_team_id,
        "slack_user_id": slack_user_id,
        "agent_instance_id": agent_instance_id,
        "agent_persona": agent_persona,
        "github_user_id": github_user_id,
        "github_node_id": github_node_id,
        "github_login": github_login,
    }
    if any(not str(value or "").strip() for value in values.values()):
        raise ValidationError("identity binding fields must be non-empty")
    now = utc_now_iso()
    with ledger.transaction(immediate=True):
        with ledger._connect() as conn:
            conflicts = conn.execute(
                """SELECT * FROM collaboration_identity_bindings
                   WHERE status = 'active' AND (
                       agent_instance_id = ? OR
                       (slack_team_id = ? AND slack_user_id = ?) OR
                       owner_id = ? OR github_user_id = ? OR github_node_id = ?
                   )""",
                (
                    agent_instance_id,
                    slack_team_id,
                    slack_user_id,
                    owner_id,
                    github_user_id,
                    github_node_id,
                ),
            ).fetchall()
            for row in conflicts:
                if row["owner_id"] != owner_id:
                    raise ValidationError(
                        "Slack user, agent instance, or GitHub identity is bound to another owner"
                    )
                if (
                    row["github_user_id"] != github_user_id
                    or row["github_node_id"] != github_node_id
                ):
                    raise ValidationError("owner is already bound to a different GitHub identity")
            existing = next(
                (row for row in conflicts if row["agent_instance_id"] == agent_instance_id),
                None,
            )
            if existing is not None:
                conn.execute(
                    """UPDATE collaboration_identity_bindings
                       SET agent_persona = ?, agent_avatar_url = ?, slack_bot_user_id = ?,
                           github_login = ?, updated_at = ? WHERE id = ?""",
                    (
                        agent_persona,
                        agent_avatar_url,
                        slack_bot_user_id,
                        github_login,
                        now,
                        existing["id"],
                    ),
                )
                binding_id = existing["id"]
            else:
                binding_id = f"identity_{uuid.uuid4().hex[:16]}"
                conn.execute(
                    """INSERT INTO collaboration_identity_bindings (
                           id, owner_id, slack_team_id, slack_user_id,
                           agent_instance_id, agent_persona, agent_avatar_url,
                           slack_bot_user_id, github_user_id, github_node_id,
                           github_login, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        binding_id,
                        owner_id,
                        slack_team_id,
                        slack_user_id,
                        agent_instance_id,
                        agent_persona,
                        agent_avatar_url,
                        slack_bot_user_id,
                        github_user_id,
                        github_node_id,
                        github_login,
                        now,
                        now,
                    ),
                )
    return get_identity_binding(ledger, binding_id)


def get_identity_binding(ledger: Any, binding_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM collaboration_identity_bindings WHERE id = ?", (binding_id,)
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"collaboration identity not found: {binding_id}")
    return dict(row)


def resolve_identity_binding(
    ledger: Any,
    *,
    slack_team_id: str,
    slack_user_id: str,
    agent_instance_id: str,
) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            """SELECT * FROM collaboration_identity_bindings
               WHERE slack_team_id = ? AND slack_user_id = ?
                 AND agent_instance_id = ? AND status = 'active'""",
            (slack_team_id, slack_user_id, agent_instance_id),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError("no active Slack/agent/GitHub identity binding")
    return dict(row)


def revoke_identity_binding(ledger: Any, binding_id: str) -> dict[str, Any]:
    get_identity_binding(ledger, binding_id)
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE collaboration_identity_bindings
               SET status = 'revoked', revoked_at = ?, updated_at = ? WHERE id = ?""",
            (now, now, binding_id),
        )
    return get_identity_binding(ledger, binding_id)


def record_contribution(
    ledger: Any,
    changeset_id: str,
    *,
    idempotency_key: str,
    binding: Mapping[str, Any],
    actor_kind: str,
    commit_sha: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if actor_kind not in {"human", "agent"}:
        raise ValidationError("contribution actor_kind must be human or agent")
    get_changeset(ledger, changeset_id)
    current = resolve_identity_binding(
        ledger,
        slack_team_id=str(binding["slack_team_id"]),
        slack_user_id=str(binding["slack_user_id"]),
        agent_instance_id=str(binding["agent_instance_id"]),
    )
    attestation = {
        "human_owner": current["owner_id"],
        "github_actor": current["github_user_id"],
        "agent_instance": current["agent_instance_id"],
        "agent_persona": current["agent_persona"],
        "actor_kind": actor_kind,
        "changeset_id": changeset_id,
        "commit_sha": commit_sha,
        "metadata": dict(metadata or {}),
    }
    contribution_id = f"contrib_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO collaboration_contributions (
                   id, changeset_id, idempotency_key, owner_id, slack_user_id,
                   github_user_id, agent_instance_id, agent_persona, actor_kind,
                   commit_sha, attestation, attestation_digest, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                contribution_id,
                changeset_id,
                idempotency_key,
                current["owner_id"],
                current["slack_user_id"],
                current["github_user_id"],
                current["agent_instance_id"],
                current["agent_persona"],
                actor_kind,
                commit_sha,
                json.dumps(attestation, sort_keys=True),
                content_digest(attestation),
                utc_now_iso(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM collaboration_contributions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    result = dict(row)
    result["attestation"] = json.loads(result["attestation"])
    if (
        result["changeset_id"] != changeset_id
        or result["owner_id"] != current["owner_id"]
        or result["actor_kind"] != actor_kind
    ):
        raise ValidationError("contribution idempotency key was replayed in another context")
    return result


def _thread_row(row: Any) -> dict[str, Any]:
    return dict(row)


__all__ = [
    "bind_identity",
    "get_or_create_thread_changeset",
    "get_identity_binding",
    "record_contribution",
    "resolve_identity_binding",
    "revoke_identity_binding",
]
