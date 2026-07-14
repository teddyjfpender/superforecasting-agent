"""Durable GitHub activity projection into the shared Slack changeset card."""

from __future__ import annotations

import json
from typing import Any

from forecasting.models import utc_now_iso


_STATUS_PHASE = {
    "publishing": "draft_pr",
    "review_open": "review_required",
    "checks_running": "checks_running",
    "review_required": "review_required",
    "changes_requested": "review_required",
    "held": "held",
    "merge_ready": "review_required",
    "merge_queued": "merge_queued",
    "merged_apply_pending": "merged_apply_pending",
    "applying": "merged_apply_pending",
    "applied": "applied",
    "apply_failed": "failed",
    "blocked": "failed",
    "cancelled": "cancelled",
    "abandoned": "abandoned",
}


class GitHubSlackMirror:
    def __init__(self, ledger: Any, cards: Any, *, actions: Any = None) -> None:
        self.ledger = ledger
        self.cards = cards
        self.actions = actions

    def prepare(self, delivery_id: str) -> dict[str, Any] | None:
        with self.ledger._connect() as conn:
            delivery = conn.execute(
                "SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
            existing = conn.execute(
                "SELECT * FROM github_slack_mirrors WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        if delivery is None or delivery["state"] != "processed":
            return None
        if existing is not None and existing["state"] == "delivered":
            return None
        payload = json.loads(delivery["payload"])
        pull = payload.get("pull_request") or {}
        issue = payload.get("issue") or {}
        number = pull.get("number") or (issue.get("number") if issue.get("pull_request") else None)
        if not number:
            return None
        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT * FROM ledger_changesets WHERE pr_number = ?
                   ORDER BY created_at DESC, id DESC LIMIT 1""",
                (number,),
            ).fetchone()
        if row is None:
            return None
        changeset = dict(row)
        card = self.cards.get(changeset["id"])
        phase = _STATUS_PHASE.get(changeset["status"], card["phase"])
        event_type = delivery["event_type"]
        actor = (payload.get("sender") or {}).get("login") or "GitHub"
        checks_state = card["checks_state"]
        next_action = f"GitHub activity from {actor} was synchronized."
        if event_type == "check_run":
            check = payload.get("check_run") or {}
            checks_state = str(check.get("conclusion") or check.get("status") or "pending")
            next_action = f"GitHub check `{check.get('name') or 'check'}` is {checks_state}."
        elif event_type == "pull_request_review":
            review = payload.get("review") or {}
            next_action = f"{actor} submitted a GitHub review: {review.get('state') or 'updated'}."
        elif event_type in {"issue_comment", "pull_request_review_comment"}:
            metadata = json.loads(changeset.get("metadata") or "{}")
            if changeset["status"] == "held" and metadata.get("discussion_pause"):
                phase = "held"
                next_action = (
                    "Autonomous agent discussion paused after consecutive agent turns; "
                    "human direction is required in Slack or GitHub."
                )
            else:
                next_action = f"{actor} added a GitHub PR comment; review it before responding."
        elif event_type == "merge_group":
            phase = "merge_queued"
            next_action = "GitHub merge queue state changed; policy checks remain authoritative."
        elif event_type == "pull_request" and delivery["action"] == "closed":
            next_action = (
                "The accepted Git proposal was applied to the authoritative ledger."
                if changeset["status"] == "applied"
                else "Git merged the proposal; authoritative ledger application needs attention."
            )
        state = {
            **card["state"],
            "heartbeat_expected": False,
            "last_github_delivery_id": delivery_id,
            "last_github_event": event_type,
            "github_correlation_id": delivery_id,
        }
        self.cards.update(
            changeset["id"],
            slack_team_id=card["slack_team_id"],
            slack_channel_id=card["slack_channel_id"],
            slack_thread_ts=card["slack_thread_ts"],
            phase=phase,
            next_action=next_action,
            active_owner_id=card.get("active_owner_id"),
            active_agent_instance_id=card.get("active_agent_instance_id"),
            active_agent_persona=card.get("active_agent_persona"),
            pr_url=card.get("pr_url"),
            checks_state=checks_state,
            state=state,
            progress=True,
        )
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_slack_mirrors
                   (delivery_id, changeset_id, state, attempts, created_at, updated_at)
                   VALUES (?, ?, 'pending', 0, ?, ?)
                   ON CONFLICT(delivery_id) DO UPDATE SET updated_at = excluded.updated_at""",
                (delivery_id, changeset["id"], now, now),
            )
            marker = None
            remote = payload.get("review") or payload.get("comment") or {}
            if remote.get("id"):
                marker = conn.execute(
                    """SELECT correlation_id FROM github_origin_markers
                       WHERE remote_kind IN ('review', 'comment') AND remote_id = ?""",
                    (str(remote["id"]),),
                ).fetchone()
        summary = None
        if event_type in {"issue_comment", "pull_request_review_comment"} and marker is None:
            url = (payload.get("comment") or {}).get("html_url") or issue.get("html_url")
            summary = f"GitHub PR #{number}: {actor} added a comment."
            if url:
                summary += f" {url}"
        final = changeset["status"] in {"applied", "apply_failed", "cancelled", "abandoned"}
        final_render = self.cards.render_final(changeset["id"]) if final else None
        if final_render is not None:
            final_render["correlation_id"] = f"{delivery_id}:final"
        return {
            "delivery_id": delivery_id,
            "changeset_id": changeset["id"],
            "render": self.cards.render(changeset["id"], actions=self.actions),
            "summary": summary,
            "final": final_render,
        }

    def mark(self, delivery_id: str, *, delivered: bool, error: str | None = None) -> None:
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            conn.execute(
                """UPDATE github_slack_mirrors
                   SET state = ?, attempts = attempts + 1, last_error = ?,
                       delivered_at = CASE WHEN ? THEN ? ELSE delivered_at END,
                       updated_at = ? WHERE delivery_id = ?""",
                (
                    "delivered" if delivered else "pending",
                    None if delivered else str(error or "Slack delivery failed")[:300],
                    int(delivered),
                    now,
                    now,
                    delivery_id,
                ),
            )

    def pending(self, *, limit: int = 100) -> list[str]:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT d.delivery_id FROM github_webhook_deliveries d
                   LEFT JOIN github_slack_mirrors m ON m.delivery_id = d.delivery_id
                   WHERE d.state = 'processed' AND (m.state IS NULL OR m.state = 'pending')
                   ORDER BY d.received_at, d.delivery_id LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [row["delivery_id"] for row in rows]


__all__ = ["GitHubSlackMirror"]
