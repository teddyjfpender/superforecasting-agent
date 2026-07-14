"""Idempotent GitHub webhook projection into reviews and merge/apply state."""

from __future__ import annotations

import json
import re
from typing import Any

from forecasting.change_control.collaboration import get_identity_binding
from forecasting.change_control.store import (
    add_review,
    get_changeset,
    get_review,
    transition_changeset,
)
from forecasting.github.webhooks import mark_delivery_processed
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


_REVIEW_DECISIONS = {
    "approved": "approve",
    "changes_requested": "request_changes",
}


def record_github_origin(
    ledger: Any,
    *,
    remote_kind: str,
    remote_id: str,
    changeset_id: str,
    actor_kind: str,
    identity_binding_id: str | None,
    correlation_id: str,
) -> None:
    if actor_kind not in {"human", "agent"}:
        raise ValidationError("GitHub origin actor_kind must be human or agent")
    get_changeset(ledger, changeset_id)
    if identity_binding_id:
        get_identity_binding(ledger, identity_binding_id)
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO github_origin_markers (
                   remote_kind, remote_id, changeset_id, actor_kind,
                   identity_binding_id, correlation_id, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(remote_kind, remote_id) DO NOTHING""",
            (
                remote_kind,
                str(remote_id),
                changeset_id,
                actor_kind,
                identity_binding_id,
                correlation_id,
                utc_now_iso(),
            ),
        )
        if remote_kind in {"comment", "review"}:
            conn.execute(
                """UPDATE github_agent_discussion_events
                   SET actor_kind = ?, identity_binding_id = ?
                   WHERE remote_kind = ? AND remote_id = ? AND changeset_id = ?""",
                (
                    actor_kind,
                    identity_binding_id,
                    remote_kind,
                    str(remote_id),
                    changeset_id,
                ),
            )


class GitHubWebhookProcessor:
    def __init__(
        self,
        ledger: Any,
        *,
        repository_slug: str,
        promotion_app_id: str,
    ) -> None:
        self.ledger = ledger
        self.repository_slug = repository_slug
        self.promotion_app_id = str(promotion_app_id)

    def process(self, delivery_id: str) -> dict[str, Any]:
        with self.ledger._connect() as conn:
            row = conn.execute(
                "SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"GitHub delivery not found: {delivery_id}")
        delivery = dict(row)
        delivery["payload"] = json.loads(delivery["payload"])
        if delivery["state"] in {"processed", "quarantined"}:
            return delivery
        if str(delivery.get("repository_slug") or "").lower() != self.repository_slug.lower():
            raise PermissionError("GitHub delivery repository does not match workspace")
        event_type = delivery["event_type"]
        if event_type == "pull_request_review":
            self._review(delivery)
        elif event_type in {"issue_comment", "pull_request_review_comment"}:
            self._comment(delivery)
        elif event_type == "pull_request":
            self._pull_request(delivery)
        elif event_type == "check_run":
            self._check_run(delivery)
        elif event_type == "merge_group":
            self._merge_group(delivery)
        elif event_type == "github_app_authorization":
            self._authorization(delivery)
        return mark_delivery_processed(self.ledger, delivery_id)

    def _review(self, delivery: dict[str, Any]) -> None:
        if delivery.get("action") != "submitted":
            return
        payload = delivery["payload"]
        review = payload.get("review") or {}
        decision = _REVIEW_DECISIONS.get(str(review.get("state") or "").lower())
        if decision is None:
            return
        changeset = self._changeset_for_pull(payload)
        review_id = f"github_review_{review.get('id')}"
        try:
            get_review(self.ledger, review_id)
            return
        except LedgerNotFoundError:
            pass
        remote_user = review.get("user") or payload.get("sender") or {}
        github_user_id = str(remote_user.get("id") or "")
        if not github_user_id:
            raise ValidationError("GitHub review lacks an immutable user ID")
        with self.ledger._connect() as conn:
            marker = conn.execute(
                """SELECT * FROM github_origin_markers
                   WHERE remote_kind = 'review' AND remote_id = ?""",
                (str(review.get("id")),),
            ).fetchone()
        if marker is not None:
            marker = dict(marker)
            if marker["changeset_id"] != changeset["id"]:
                raise PermissionError("GitHub review origin belongs to another changeset")
            actor_kind = marker["actor_kind"]
            binding = (
                get_identity_binding(self.ledger, marker["identity_binding_id"])
                if marker.get("identity_binding_id")
                else None
            )
        else:
            actor_kind = "human"
            binding = self._binding_for_github(github_user_id)
            from forecasting.github.discussion import record_human_discussion_activity

            record_human_discussion_activity(
                self.ledger,
                changeset_id=changeset["id"],
                remote_kind="review",
                remote_id=str(review.get("id")),
                identity_binding_id=binding["id"],
            )
        add_review(
            self.ledger,
            changeset["id"],
            review_id=review_id,
            decision=decision,
            actor_kind=actor_kind,
            source="github",
            owner_id=None if binding is None else binding["owner_id"],
            github_user_id=github_user_id,
            agent_instance_id=(
                binding["agent_instance_id"] if actor_kind == "agent" and binding else None
            ),
            agent_persona=(
                binding["agent_persona"] if actor_kind == "agent" and binding else None
            ),
            head_sha=str(review.get("commit_id") or changeset.get("head_sha") or "") or None,
            metadata={"github_review_id": str(review.get("id"))},
        )

    def _comment(self, delivery: dict[str, Any]) -> None:
        if delivery.get("action") not in {"created", "edited"}:
            return
        payload = delivery["payload"]
        comment = payload.get("comment") or {}
        remote_id = str(comment.get("id") or "")
        if not remote_id:
            raise ValidationError("GitHub comment lacks an immutable ID")
        changeset = self._changeset_for_pull(payload)
        with self.ledger._connect() as conn:
            marker = conn.execute(
                """SELECT actor_kind FROM github_origin_markers
                   WHERE remote_kind = 'comment' AND remote_id = ?""",
                (remote_id,),
            ).fetchone()
        if marker is not None and marker["actor_kind"] == "agent":
            return
        remote_user = comment.get("user") or payload.get("sender") or {}
        if str(remote_user.get("type") or "").lower() == "bot":
            return
        github_user_id = str(remote_user.get("id") or "")
        binding = None
        if github_user_id:
            try:
                binding = self._binding_for_github(github_user_id)
            except PermissionError:
                pass
        from forecasting.github.discussion import record_human_discussion_activity

        record_human_discussion_activity(
            self.ledger,
            changeset_id=changeset["id"],
            remote_kind="comment",
            remote_id=remote_id,
            identity_binding_id=None if binding is None else binding["id"],
        )

    def _pull_request(self, delivery: dict[str, Any]) -> None:
        if delivery.get("action") != "closed":
            return
        pull = delivery["payload"].get("pull_request") or {}
        if not pull.get("merged"):
            return
        changeset = self._changeset_for_pull(delivery["payload"])
        if changeset["status"] == "merged_apply_pending":
            return
        head_sha = str((pull.get("head") or {}).get("sha") or "")
        merge_sha = str(pull.get("merge_commit_sha") or "")
        if not head_sha or head_sha != changeset.get("head_sha"):
            raise ValidationError("merged pull request head does not match changeset head")
        if not merge_sha:
            raise ValidationError("merged pull request lacks merge commit SHA")
        if changeset["status"] not in {"merge_ready", "merge_queued"}:
            raise ValidationError(
                f"merged changeset is not promotable from status {changeset['status']}"
            )
        transition_changeset(
            self.ledger,
            changeset["id"],
            "merged_apply_pending",
            fields={"merge_sha": merge_sha},
        )

    def _check_run(self, delivery: dict[str, Any]) -> None:
        check = delivery["payload"].get("check_run") or {}
        if check.get("name") != "ledger/promotion":
            return
        app_id = str((check.get("app") or {}).get("id") or "")
        if app_id != self.promotion_app_id:
            raise PermissionError("ledger/promotion check came from an unauthorized App")
        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT head_sha FROM github_promotion_checks
                   WHERE github_check_id = ? AND app_id = ?""",
                (str(check.get("id")), self.promotion_app_id),
            ).fetchone()
        if row is None or row["head_sha"] != check.get("head_sha"):
            raise PermissionError("ledger/promotion check is not bound to a known head")

    def _merge_group(self, delivery: dict[str, Any]) -> None:
        action = str(delivery.get("action") or "")
        if action not in {"checks_requested", "destroyed"}:
            return
        group = delivery["payload"].get("merge_group") or {}
        head_ref = str(group.get("head_ref") or "")
        match = re.search(r"(?:^|/)pr-(\d+)(?:-|$)", head_ref)
        if match is None:
            raise ValidationError("merge group head does not identify a pull request")
        changeset = self._changeset_for_pull(
            {"pull_request": {"number": int(match.group(1))}}
        )
        metadata = dict(changeset.get("metadata") or {})
        metadata["merge_group"] = {
            "head_ref": head_ref,
            "head_sha": str(group.get("head_sha") or ""),
            "state": action,
        }
        if action == "checks_requested":
            if changeset["status"] == "merge_ready":
                transition_changeset(
                    self.ledger,
                    changeset["id"],
                    "merge_queued",
                    fields={"metadata": metadata},
                )
            elif changeset["status"] != "merge_queued":
                raise ValidationError(
                    f"merge queue cannot start from status {changeset['status']}"
                )
        elif changeset["status"] == "merge_queued":
            transition_changeset(
                self.ledger,
                changeset["id"],
                "held",
                fields={"metadata": metadata},
            )

    def _authorization(self, delivery: dict[str, Any]) -> None:
        if delivery.get("action") not in {"revoked", "deleted"}:
            return
        user = (delivery["payload"].get("authorization") or {}).get("user") or {}
        github_user_id = str(user.get("id") or "")
        if not github_user_id:
            return
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT id FROM collaboration_identity_bindings
                   WHERE github_user_id = ? AND status = 'active'""",
                (github_user_id,),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """UPDATE collaboration_identity_bindings
                       SET status = 'revoked', revoked_at = ?, updated_at = ? WHERE id = ?""",
                    (now, now, row["id"]),
                )
                conn.execute(
                    """UPDATE github_user_tokens
                       SET status = 'revoked', revoked_at = ?, updated_at = ?
                       WHERE identity_binding_id = ?""",
                    (now, now, row["id"]),
                )

    def _changeset_for_pull(self, payload: dict[str, Any]) -> dict[str, Any]:
        pull = payload.get("pull_request") or {}
        issue = payload.get("issue") or {}
        number = pull.get("number") or (
            issue.get("number") if issue.get("pull_request") else None
        )
        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT id FROM ledger_changesets
                   WHERE pr_number = ? ORDER BY created_at DESC LIMIT 1""",
                (number,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"no changeset for GitHub pull request {number}")
        return get_changeset(self.ledger, row["id"])

    def _binding_for_github(self, github_user_id: str) -> dict[str, Any]:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM collaboration_identity_bindings
                   WHERE github_user_id = ? AND status = 'active'
                   ORDER BY created_at, id""",
                (github_user_id,),
            ).fetchall()
        owners = {row["owner_id"] for row in rows}
        if len(owners) != 1:
            raise PermissionError("GitHub reviewer has no unambiguous linked owner")
        return dict(rows[0])


__all__ = ["GitHubWebhookProcessor", "record_github_origin"]
