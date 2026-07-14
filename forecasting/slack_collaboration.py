"""Durable Slack changeset cards, liveness, presence, and signed review actions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from forecasting.change_control.collaboration import resolve_slack_owner_binding
from forecasting.change_control.provenance import record_consent
from forecasting.change_control.store import (
    add_review,
    get_changeset,
    transition_changeset,
)
from forecasting.github.events import record_github_origin
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


CARD_PHASES = frozenset(
    {
        "researching",
        "editing",
        "transcript_preview",
        "checks_running",
        "draft_pr",
        "review_required",
        "held",
        "merge_queued",
        "merged_apply_pending",
        "applied",
        "conflicted",
        "failed",
        "cancelled",
        "abandoned",
    }
)
PRESENCE_STATES = frozenset(
    {"working", "queued", "reviewing", "waiting", "disconnected"}
)
ACTION_NAMES = frozenset(
    {
        "view_diff",
        "preview_transcript",
        "transcript_include",
        "transcript_omit",
        "approve",
        "request_changes",
        "reject",
        "hold",
        "resume",
        "open_pr",
        "cancel",
    }
)
_REVIEW_ACTIONS = {
    "approve": ("approve", "APPROVE"),
    "request_changes": ("request_changes", "REQUEST_CHANGES"),
    "reject": ("reject", "REQUEST_CHANGES"),
}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _escape(value: Any) -> str:
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class SlackActionService:
    """Issue and consume exact, expiring, single-use Block Kit action values."""

    def __init__(
        self,
        ledger: Any,
        *,
        signing_key: bytes,
        repository_slug: str,
        github_client_factory: Callable[[dict[str, Any], str], Any] | None = None,
        github_publisher_factory: Callable[[dict[str, Any], dict[str, Any]], Any]
        | None = None,
        role_resolver: Callable[[str, dict[str, Any]], set[str]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(signing_key) < 32:
            raise ValidationError("Slack changeset action signing key must be at least 32 bytes")
        self.ledger = ledger
        self.signing_key = signing_key
        self.repository_slug = repository_slug
        self.github_client_factory = github_client_factory
        self.github_publisher_factory = github_publisher_factory
        self.role_resolver = role_resolver or self._default_roles
        self.clock = clock

    def issue(
        self,
        changeset_id: str,
        action: str,
        *,
        slack_team_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
        ttl_seconds: int = 900,
        metadata: Mapping[str, str] | None = None,
    ) -> str:
        if action not in ACTION_NAMES:
            raise ValidationError(f"unsupported Slack changeset action: {action}")
        changeset = get_changeset(self.ledger, changeset_id)
        nonce = secrets.token_urlsafe(18)
        expires_at = int(self.clock()) + max(60, min(int(ttl_seconds), 3600))
        safe_metadata = {
            key: str(value)
            for key, value in dict(metadata or {}).items()
            if key in {"transcript_digest"} and len(str(value)) <= 128
        }
        payload = {
            "version": 1,
            "nonce": nonce,
            "changeset_id": changeset_id,
            "changeset_digest": changeset["digest"],
            "action": action,
            "team": slack_team_id,
            "channel": slack_channel_id,
            "thread": slack_thread_ts,
            "expires_at": expires_at,
            "metadata": safe_metadata,
        }
        encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).digest())
        nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()
        with self.ledger._connect() as conn:
            conn.execute(
                """DELETE FROM slack_changeset_action_nonces
                   WHERE status = 'issued' AND expires_at < ?""",
                (int(self.clock()),),
            )
            conn.execute(
                """INSERT INTO slack_changeset_action_nonces (
                       nonce_hash, changeset_id, changeset_digest, action,
                       slack_team_id, slack_channel_id, slack_thread_ts,
                       expires_at, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    nonce_hash,
                    changeset_id,
                    changeset["digest"],
                    action,
                    slack_team_id,
                    slack_channel_id,
                    slack_thread_ts,
                    expires_at,
                    utc_now_iso(),
                ),
            )
        return f"{encoded}.{signature}"

    def handle(
        self,
        token: str,
        *,
        action_id: str,
        slack_team_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
        slack_user_id: str,
    ) -> dict[str, Any]:
        payload = self._verify(token)
        action = action_id.removeprefix("forecast_")
        expected = (slack_team_id, slack_channel_id, slack_thread_ts, action)
        actual = (payload["team"], payload["channel"], payload["thread"], payload["action"])
        if actual != expected:
            raise PermissionError("Slack changeset action context does not match")
        changeset = get_changeset(self.ledger, payload["changeset_id"])
        if changeset["digest"] != payload["changeset_digest"]:
            raise PermissionError("Slack changeset action is stale")
        binding = resolve_slack_owner_binding(
            self.ledger,
            slack_team_id=slack_team_id,
            slack_user_id=slack_user_id,
        )
        roles = set(self.role_resolver(binding["owner_id"], changeset))
        self._authorize(action, roles, binding["owner_id"], changeset)
        nonce_hash = hashlib.sha256(str(payload["nonce"]).encode()).hexdigest()
        replay = self._reserve(nonce_hash, slack_user_id)
        if replay is not None:
            return replay
        try:
            result = self._apply(action, payload, changeset, binding, nonce_hash)
            self._finish(nonce_hash, "completed", result)
            return result
        except Exception:
            result = {
                "ok": False,
                "action": action,
                "changeset_id": changeset["id"],
                "state": "failed",
                "status": get_changeset(self.ledger, changeset["id"])["status"],
                "message": "The changeset action could not be completed safely.",
            }
            self._finish(nonce_hash, "failed", result)
            if action == "open_pr":
                return result
            raise

    def _apply(
        self,
        action: str,
        payload: dict[str, Any],
        changeset: dict[str, Any],
        binding: dict[str, Any],
        nonce_hash: str,
    ) -> dict[str, Any]:
        correlation_id = f"slack_action_{nonce_hash[:20]}"
        result: dict[str, Any] = {
            "ok": True,
            "action": action,
            "changeset_id": changeset["id"],
            "correlation_id": correlation_id,
        }
        if action in _REVIEW_ACTIONS:
            decision, github_event = _REVIEW_ACTIONS[action]
            review = add_review(
                self.ledger,
                changeset["id"],
                review_id=f"slack_review_{nonce_hash[:24]}",
                decision=decision,
                actor_kind="human",
                source="slack",
                owner_id=binding["owner_id"],
                github_user_id=binding["github_user_id"],
                slack_user_id=binding["slack_user_id"],
                head_sha=changeset.get("head_sha"),
                metadata={"correlation_id": correlation_id},
            )
            result["review_id"] = review["id"]
            if action == "request_changes":
                self._transition_review_decision(changeset["id"], "changes_requested")
            elif action == "reject":
                self._transition_review_decision(changeset["id"], "rejected")
            result.update(
                self._mirror_github_review(
                    changeset,
                    binding,
                    github_event=github_event,
                    correlation_id=correlation_id,
                )
            )
        elif action == "hold":
            transition_changeset(self.ledger, changeset["id"], "held")
        elif action == "resume":
            target = "review_open" if changeset["risk_tier"] == "low" else "review_required"
            transition_changeset(self.ledger, changeset["id"], target, expected_status="held")
        elif action == "cancel":
            transition_changeset(self.ledger, changeset["id"], "cancelled")
        elif action in {"transcript_include", "transcript_omit"}:
            digest = str((payload.get("metadata") or {}).get("transcript_digest") or "")
            if not digest:
                raise ValidationError("transcript action lacks an artifact digest")
            consent = record_consent(
                self.ledger,
                changeset["id"],
                transcript_digest=digest,
                repository_slug=self.repository_slug,
                owner_id=binding["owner_id"],
                decision="include" if action == "transcript_include" else "omit",
            )
            result["consent"] = consent["decision"]
        elif action == "open_pr":
            if changeset.get("pr_number"):
                result["pr_number"] = changeset["pr_number"]
            elif self.github_publisher_factory is None:
                raise ValidationError("GitHub publication is not configured")
            else:
                publisher = self.github_publisher_factory(binding, changeset)
                with tempfile.TemporaryDirectory(prefix="forecast-github-publish-") as root:
                    published = publisher.publish(changeset["id"], root)
                result.update(
                    {
                        "pr_number": published["pr_number"],
                        "pr_url": published.get("pr_url"),
                        "head_repository": published.get("head_repository"),
                        "publication_mode": published.get("publication_mode"),
                    }
                )
        elif action in {"view_diff", "preview_transcript"}:
            result["read_only"] = True
        result["status"] = get_changeset(self.ledger, changeset["id"])["status"]
        return result

    def _mirror_github_review(
        self,
        changeset: dict[str, Any],
        binding: dict[str, Any],
        *,
        github_event: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        if not self.github_client_factory or not changeset.get("pr_number"):
            return {"github_state": "not_linked"}
        try:
            client = self.github_client_factory(binding, changeset["id"])
            response = client.call(
                "review.write",
                "POST",
                f"/repos/{self.repository_slug}/pulls/{int(changeset['pr_number'])}/reviews",
                {
                    "event": github_event,
                    "body": (
                        f"Slack review by linked owner `{binding['owner_id']}`. "
                        f"Correlation: `{correlation_id}`."
                    ),
                    **({"commit_id": changeset["head_sha"]} if changeset.get("head_sha") else {}),
                },
            )
            body = response.get("body") if isinstance(response, Mapping) else None
            remote_id = str(body.get("id") or "") if isinstance(body, Mapping) else ""
            if not remote_id:
                raise ValidationError("GitHub review response lacks an ID")
            record_github_origin(
                self.ledger,
                remote_kind="review",
                remote_id=remote_id,
                changeset_id=changeset["id"],
                actor_kind="human",
                identity_binding_id=binding["id"],
                correlation_id=correlation_id,
            )
            return {"github_state": "posted", "github_review_id": remote_id}
        except Exception:
            return {"github_state": "pending_retry"}

    def _transition_review_decision(self, changeset_id: str, target: str) -> None:
        changeset = get_changeset(self.ledger, changeset_id)
        if target == "rejected" and changeset["status"] in {"review_open", "checks_running"}:
            transition_changeset(self.ledger, changeset_id, "review_required")
            changeset = get_changeset(self.ledger, changeset_id)
        if changeset["status"] != target:
            transition_changeset(self.ledger, changeset_id, target)

    def _verify(self, token: str) -> dict[str, Any]:
        try:
            encoded, supplied = token.split(".", 1)
            expected = _b64(
                hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(expected, supplied):
                raise ValueError("signature")
            payload = json.loads(_unb64(encoded))
        except Exception as exc:
            raise PermissionError("Slack changeset action signature is invalid") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("version") != 1
            or payload.get("action") not in ACTION_NAMES
        ):
            raise PermissionError("Slack changeset action version is invalid")
        if int(payload.get("expires_at") or 0) < int(self.clock()):
            raise PermissionError("Slack changeset action expired")
        return payload

    def _reserve(self, nonce_hash: str, slack_user_id: str) -> dict[str, Any] | None:
        with self.ledger.transaction(immediate=True):
            with self.ledger._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM slack_changeset_action_nonces WHERE nonce_hash = ?",
                    (nonce_hash,),
                ).fetchone()
                if row is None:
                    raise PermissionError("Slack changeset action nonce is unknown")
                if row["expires_at"] < int(self.clock()):
                    raise PermissionError("Slack changeset action expired")
                if row["status"] != "issued":
                    if row["result"]:
                        return json.loads(row["result"])
                    return {
                        "ok": True,
                        "action": row["action"],
                        "changeset_id": row["changeset_id"],
                        "state": "processing",
                    }
                conn.execute(
                    """UPDATE slack_changeset_action_nonces
                       SET status = 'processing', slack_user_id = ?, consumed_at = ?
                       WHERE nonce_hash = ? AND status = 'issued'""",
                    (slack_user_id, utc_now_iso(), nonce_hash),
                )
        return None

    def _finish(self, nonce_hash: str, status: str, result: dict[str, Any]) -> None:
        with self.ledger._connect() as conn:
            conn.execute(
                """UPDATE slack_changeset_action_nonces SET status = ?, result = ?
                   WHERE nonce_hash = ?""",
                (status, json.dumps(result, sort_keys=True), nonce_hash),
            )

    @staticmethod
    def _default_roles(owner_id: str, changeset: dict[str, Any]) -> set[str]:
        return {"owner"} if owner_id in changeset["author_owner_ids"] else {"reviewer"}

    @staticmethod
    def _authorize(
        action: str,
        roles: set[str],
        owner_id: str,
        changeset: dict[str, Any],
    ) -> None:
        if not roles:
            raise PermissionError("Slack user is not authorized for this changeset")
        if action == "cancel" and not ({"owner", "admin"} & roles):
            raise PermissionError("only a changeset owner or administrator may cancel")
        if action in {"transcript_include", "transcript_omit"} and owner_id not in changeset[
            "author_owner_ids"
        ]:
            raise PermissionError("only an initiating owner may publish transcript content")
        if action == "open_pr" and owner_id not in changeset["author_owner_ids"]:
            raise PermissionError("only a contributing owner may publish this changeset")
        if action in _REVIEW_ACTIONS and not (
            {"reviewer", "owner", "steward", "admin"} & roles
        ):
            raise PermissionError("Slack user is not an eligible reviewer")


class SlackChangesetCardService:
    """Persist one public card and render the same Block Kit for every transport."""

    def __init__(self, ledger: Any, *, stale_after_seconds: int = 120) -> None:
        self.ledger = ledger
        self.stale_after_seconds = max(30, int(stale_after_seconds))

    def update(
        self,
        changeset_id: str,
        *,
        slack_team_id: str,
        slack_channel_id: str,
        slack_thread_ts: str,
        phase: str,
        next_action: str,
        active_owner_id: str | None = None,
        active_agent_instance_id: str | None = None,
        active_agent_persona: str | None = None,
        pr_url: str | None = None,
        checks_state: str = "pending",
        state: Mapping[str, Any] | None = None,
        progress: bool = True,
    ) -> dict[str, Any]:
        if phase not in CARD_PHASES:
            raise ValidationError(f"unsupported Slack changeset phase: {phase}")
        get_changeset(self.ledger, changeset_id)
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO slack_changeset_cards (
                       changeset_id, slack_team_id, slack_channel_id, slack_thread_ts,
                       phase, active_owner_id, active_agent_instance_id,
                       active_agent_persona, pr_url, checks_state, next_action,
                       state, render_revision, last_progress_at, last_heartbeat_at,
                       created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                   ON CONFLICT(changeset_id) DO UPDATE SET
                       slack_team_id = excluded.slack_team_id,
                       slack_channel_id = excluded.slack_channel_id,
                       slack_thread_ts = excluded.slack_thread_ts,
                       phase = excluded.phase,
                       active_owner_id = COALESCE(excluded.active_owner_id, slack_changeset_cards.active_owner_id),
                       active_agent_instance_id = COALESCE(excluded.active_agent_instance_id, slack_changeset_cards.active_agent_instance_id),
                       active_agent_persona = COALESCE(excluded.active_agent_persona, slack_changeset_cards.active_agent_persona),
                       pr_url = COALESCE(excluded.pr_url, slack_changeset_cards.pr_url),
                       checks_state = excluded.checks_state,
                       next_action = excluded.next_action,
                       state = excluded.state,
                       render_revision = slack_changeset_cards.render_revision + 1,
                       last_progress_at = CASE WHEN ? THEN excluded.last_progress_at
                                               ELSE slack_changeset_cards.last_progress_at END,
                       last_heartbeat_at = excluded.last_heartbeat_at,
                       updated_at = excluded.updated_at""",
                (
                    changeset_id,
                    slack_team_id,
                    slack_channel_id,
                    slack_thread_ts,
                    phase,
                    active_owner_id,
                    active_agent_instance_id,
                    active_agent_persona,
                    pr_url,
                    checks_state,
                    str(next_action or "Waiting for the next system action."),
                    json.dumps(dict(state or {}), sort_keys=True),
                    now,
                    now,
                    now,
                    now,
                    int(bool(progress)),
                ),
            )
        return self.get(changeset_id)

    def heartbeat(self, changeset_id: str) -> dict[str, Any]:
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            cursor = conn.execute(
                """UPDATE slack_changeset_cards
                   SET last_heartbeat_at = ?, updated_at = ? WHERE changeset_id = ?""",
                (now, now, changeset_id),
            )
        if cursor.rowcount != 1:
            raise LedgerNotFoundError(f"Slack changeset card not found: {changeset_id}")
        return self.get(changeset_id)

    def set_message_ts(
        self, changeset_id: str, message_ts: str, *, final: bool = False
    ) -> dict[str, Any]:
        field = "final_message_ts" if final else "message_ts"
        with self.ledger._connect() as conn:
            cursor = conn.execute(
                f"UPDATE slack_changeset_cards SET {field} = ?, updated_at = ? WHERE changeset_id = ?",
                (message_ts, utc_now_iso(), changeset_id),
            )
        if cursor.rowcount != 1:
            raise LedgerNotFoundError(f"Slack changeset card not found: {changeset_id}")
        return self.get(changeset_id)

    def presence(
        self,
        changeset_id: str,
        *,
        owner_id: str,
        agent_instance_id: str,
        agent_persona: str,
        presence: str,
    ) -> None:
        if presence not in PRESENCE_STATES:
            raise ValidationError(f"unsupported collaboration presence: {presence}")
        get_changeset(self.ledger, changeset_id)
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO slack_changeset_presence (
                       changeset_id, owner_id, agent_instance_id, agent_persona,
                       presence, last_seen_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(changeset_id, agent_instance_id) DO UPDATE SET
                       owner_id = excluded.owner_id,
                       agent_persona = excluded.agent_persona,
                       presence = excluded.presence,
                       last_seen_at = excluded.last_seen_at""",
                (
                    changeset_id,
                    owner_id,
                    agent_instance_id,
                    agent_persona,
                    presence,
                    utc_now_iso(),
                ),
            )

    def get(self, changeset_id: str) -> dict[str, Any]:
        with self.ledger._connect() as conn:
            row = conn.execute(
                "SELECT * FROM slack_changeset_cards WHERE changeset_id = ?",
                (changeset_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"Slack changeset card not found: {changeset_id}")
        result = dict(row)
        result["state"] = json.loads(result["state"])
        return result

    def render(
        self,
        changeset_id: str,
        *,
        actions: SlackActionService | None = None,
        transcript_digest: str | None = None,
    ) -> dict[str, Any]:
        card = self.get(changeset_id)
        changeset = get_changeset(self.ledger, changeset_id)
        with self.ledger._connect() as conn:
            presence = [
                dict(row)
                for row in conn.execute(
                    """SELECT owner_id, agent_instance_id, agent_persona, presence, last_seen_at
                       FROM slack_changeset_presence WHERE changeset_id = ?
                       ORDER BY agent_persona, agent_instance_id""",
                    (changeset_id,),
                ).fetchall()
            ]
        from forecasting.change_control.policy import evaluate_quorum
        from forecasting.change_control.store import list_reviews

        quorum = evaluate_quorum(
            risk_tier=changeset["risk_tier"],
            reviews=list_reviews(self.ledger, changeset_id),
            changeset_digest=changeset["digest"],
            head_sha=changeset.get("head_sha"),
            author_owner_ids=changeset["author_owner_ids"],
        )
        delayed = self._is_stale(card)
        phase_label = "delayed / reconnecting" if delayed else card["phase"].replace("_", " ")
        actor = card.get("active_agent_persona") or card.get("active_owner_id") or "No active actor"
        affected = changeset["affected_question_ids"]
        presence_text = ", ".join(
            f"{_escape(item['agent_persona'])}: {_escape(item['presence'])}" for item in presence
        ) or "No active collaborators"
        body = (
            f"*Changeset* `{_escape(changeset_id)}`  •  *{_escape(phase_label)}*\n"
            f"*Actor* {_escape(actor)}  •  *Risk* `{_escape(changeset['risk_tier'])}`  •  "
            f"*Checks* `{_escape(card['checks_state'])}`\n"
            f"*Approvals* `{len(quorum.approved_owner_ids)}/{quorum.required_humans}`  •  "
            f"*Forecasts* `{len(affected)}`\n"
            f"*Presence* {presence_text}\n"
            f"*Next* {_escape(card['next_action'])}"
        )
        blocks: list[dict[str, Any]] = [
            {"type": "header", "text": {"type": "plain_text", "text": "Forecast changeset"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": body}},
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            f"Last progress `{_escape(card['last_progress_at'])}` • "
                            f"Heartbeat `{_escape(card['last_heartbeat_at'])}` • "
                            f"Render `{card['render_revision']}`"
                        ),
                    }
                ],
            },
        ]
        if card.get("pr_url"):
            blocks.append(
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": f"PR: {_escape(card['pr_url'])}"}],
                }
            )
        if actions is not None:
            blocks.extend(self._action_blocks(card, changeset, actions, transcript_digest))
        return {
            "text": f"Forecast changeset {changeset_id}: {phase_label}",
            "blocks": blocks,
            "channel": card["slack_channel_id"],
            "thread_ts": card["slack_thread_ts"],
            "message_ts": card.get("message_ts"),
            "delayed": delayed,
        }

    def render_final(self, changeset_id: str) -> dict[str, Any]:
        card = self.get(changeset_id)
        changeset = get_changeset(self.ledger, changeset_id)
        revision = changeset.get("applied_revision")
        text = (
            f"Ledger result for `{_escape(changeset_id)}`: *{_escape(changeset['status'])}*. "
            f"Revision: `{revision if revision is not None else 'not applied'}`."
        )
        if card.get("pr_url"):
            text += f" PR: {_escape(card['pr_url'])}"
        return {
            "text": text,
            "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
            "channel": card["slack_channel_id"],
            "thread_ts": card["slack_thread_ts"],
        }

    def _action_blocks(
        self,
        card: dict[str, Any],
        changeset: dict[str, Any],
        service: SlackActionService,
        transcript_digest: str | None,
    ) -> list[dict[str, Any]]:
        labels = {
            "view_diff": "View diff",
            "preview_transcript": "Preview transcript",
            "transcript_include": "Include transcript",
            "transcript_omit": "Withhold transcript",
            "approve": "Approve",
            "request_changes": "Request changes",
            "reject": "Reject",
            "hold": "Hold",
            "resume": "Resume",
            "open_pr": "Open PR",
            "cancel": "Cancel",
        }
        names = ["view_diff", "preview_transcript"]
        if transcript_digest:
            names.extend(["transcript_include", "transcript_omit"])
        names.extend(["approve", "request_changes", "reject"])
        names.append("resume" if changeset["status"] == "held" else "hold")
        if not changeset.get("pr_number"):
            names.append("open_pr")
        names.append("cancel")
        elements = []
        for name in names:
            metadata = {"transcript_digest": transcript_digest} if transcript_digest else None
            value = service.issue(
                changeset["id"],
                name,
                slack_team_id=card["slack_team_id"],
                slack_channel_id=card["slack_channel_id"],
                slack_thread_ts=card["slack_thread_ts"],
                metadata=metadata,
            )
            button: dict[str, Any] = {
                "type": "button",
                "text": {"type": "plain_text", "text": labels[name]},
                "action_id": f"forecast_{name}",
                "value": value,
            }
            if name == "approve":
                button["style"] = "primary"
            elif name in {"reject", "cancel"}:
                button["style"] = "danger"
            elements.append(button)
        return [
            {"type": "actions", "elements": elements[index : index + 5]}
            for index in range(0, len(elements), 5)
        ]

    def _is_stale(self, card: dict[str, Any]) -> bool:
        if card["state"].get("heartbeat_expected") is False:
            return False
        if card["phase"] in {"applied", "failed", "cancelled", "abandoned"}:
            return False
        try:
            heartbeat = datetime.fromisoformat(
                str(card["last_heartbeat_at"]).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
        except (TypeError, ValueError):
            return True
        return (datetime.now(timezone.utc) - heartbeat).total_seconds() > self.stale_after_seconds


__all__ = [
    "ACTION_NAMES",
    "CARD_PHASES",
    "PRESENCE_STATES",
    "SlackActionService",
    "SlackChangesetCardService",
]
