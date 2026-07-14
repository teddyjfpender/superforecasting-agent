"""Publish the authoritative ledger promotion result as a GitHub App check."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from forecasting.change_control.policy import evaluate_quorum
from forecasting.change_control.preview import preview_changeset
from forecasting.change_control.store import (
    current_revision,
    get_changeset,
    list_reviews,
    transition_changeset,
)
from forecasting.models import ValidationError, utc_now_iso
from forecasting.workspace import validate_workspace


class PromotionCheckPublisher:
    def __init__(
        self,
        ledger: Any,
        *,
        repository_slug: str,
        app_id: str,
        client: Any,
    ) -> None:
        self.ledger = ledger
        self.repository_slug = repository_slug
        self.app_id = str(app_id)
        self.client = client

    def publish(self, changeset_id: str, workspace_root: str | Path) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        head_sha = str(changeset.get("head_sha") or "")
        if not head_sha:
            raise ValidationError("promotion check requires an exact Git head SHA")
        report = validate_workspace(workspace_root)
        preview = preview_changeset(self.ledger, changeset_id)
        quorum = evaluate_quorum(
            risk_tier=changeset["risk_tier"],
            reviews=list_reviews(self.ledger, changeset_id),
            changeset_digest=changeset["digest"],
            head_sha=head_sha,
            author_owner_ids=changeset["author_owner_ids"],
        )
        revision_fresh = changeset["base_revision"] == current_revision(self.ledger)["revision"]
        transcript_state = self._transcript_state(changeset_id)
        hard_failures = [
            name
            for name, passed in (
                ("workspace schema/digest", report.valid),
                ("base revision freshness", revision_fresh),
                ("ledger preview/hooks", preview["would_apply"]),
                ("transcript safety", transcript_state != "unsafe"),
            )
            if not passed
        ]
        if hard_failures:
            conclusion = "failure"
        elif not quorum.satisfied:
            conclusion = "action_required"
        else:
            conclusion = "success"
        details = {
            "schema_valid": report.valid,
            "base_revision_fresh": revision_fresh,
            "hooks_passed": preview["would_apply"],
            "transcript_state": transcript_state,
            "risk_tier": changeset["risk_tier"],
            "quorum_satisfied": quorum.satisfied,
            "quorum_reasons": list(quorum.reasons),
            "projection_digest": preview["projection_digest"],
            "hard_failures": hard_failures,
        }
        response = self.client.call(
            "check.write",
            "POST",
            f"/repos/{self.repository_slug}/check-runs",
            {
                "name": "ledger/promotion",
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": conclusion,
                "output": {
                    "title": f"Ledger promotion: {conclusion.replace('_', ' ')}",
                    "summary": self._summary(details),
                },
            },
        )
        body = response.get("body")
        if not isinstance(body, dict) or not body.get("id"):
            raise ValidationError("GitHub did not return a check-run ID")
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_promotion_checks (
                       id, changeset_id, repository_slug, app_id, github_check_id,
                       head_sha, conclusion, details, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(changeset_id, head_sha, app_id) DO UPDATE SET
                       github_check_id = excluded.github_check_id,
                       conclusion = excluded.conclusion,
                       details = excluded.details,
                       created_at = excluded.created_at""",
                (
                    f"ghcheck_{uuid.uuid4().hex[:16]}",
                    changeset_id,
                    self.repository_slug,
                    self.app_id,
                    str(body["id"]),
                    head_sha,
                    conclusion,
                    json.dumps(details, sort_keys=True),
                    utc_now_iso(),
                ),
            )
        updated = self._transition(changeset_id, conclusion)
        return {
            "changeset_id": changeset_id,
            "head_sha": head_sha,
            "check_run_id": str(body["id"]),
            "conclusion": conclusion,
            "details": details,
            "status": updated["status"],
        }

    def _transition(self, changeset_id: str, conclusion: str) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        if changeset["status"] in {
            "review_open",
            "review_required",
            "changes_requested",
            "blocked",
        }:
            changeset = transition_changeset(self.ledger, changeset_id, "checks_running")
        if changeset["status"] != "checks_running":
            raise ValidationError(
                f"cannot record promotion check from status {changeset['status']}"
            )
        target = {
            "success": "merge_ready",
            "action_required": "review_required",
            "failure": "blocked",
        }[conclusion]
        metadata = dict(changeset.get("metadata") or {})
        metadata["checks_passed"] = conclusion == "success"
        metadata["promotion_check"] = {
            "app_id": self.app_id,
            "head_sha": changeset.get("head_sha"),
            "conclusion": conclusion,
        }
        return transition_changeset(
            self.ledger,
            changeset_id,
            target,
            fields={"metadata": metadata},
        )

    def _transcript_state(self, changeset_id: str) -> str:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT t.status FROM provenance_transcripts t
                   JOIN provenance_bundles b ON b.id = t.bundle_id
                   WHERE b.changeset_id = ?""",
                (changeset_id,),
            ).fetchall()
        statuses = {str(row["status"]) for row in rows}
        if "unsafe" in statuses:
            return "unsafe"
        if "safe" in statuses:
            return "safe"
        if "withheld" in statuses:
            return "withheld"
        return "not_available"

    @staticmethod
    def _summary(details: dict[str, Any]) -> str:
        return "\n".join(
            [
                f"- Schema and content digest: {'pass' if details['schema_valid'] else 'fail'}",
                f"- Base revision: {'fresh' if details['base_revision_fresh'] else 'stale'}",
                f"- Ledger hooks: {'pass' if details['hooks_passed'] else 'fail'}",
                f"- Transcript safety: {details['transcript_state']}",
                f"- Risk tier: {details['risk_tier']}",
                f"- Human quorum: {'satisfied' if details['quorum_satisfied'] else 'waiting'}",
                f"- Projection digest: `{details['projection_digest']}`",
            ]
        )


__all__ = ["PromotionCheckPublisher"]
