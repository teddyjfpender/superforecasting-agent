"""Publish authoritative ledger promotion and application GitHub checks."""

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

    def publish(
        self,
        changeset_id: str,
        workspace_root: str | Path,
        *,
        head_sha: str | None = None,
    ) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        source_head_sha = str(changeset.get("head_sha") or "")
        target_head_sha = str(head_sha or source_head_sha)
        if not source_head_sha or not target_head_sha:
            raise ValidationError("promotion check requires an exact Git head SHA")
        merge_group = target_head_sha != source_head_sha
        if merge_group:
            group = dict((changeset.get("metadata") or {}).get("merge_group") or {})
            if (
                group.get("state") != "checks_requested"
                or str(group.get("head_sha") or "") != target_head_sha
            ):
                raise ValidationError("promotion check head is not the active merge group")

        report = validate_workspace(workspace_root)
        preview = preview_changeset(self.ledger, changeset_id)
        quorum = evaluate_quorum(
            risk_tier=changeset["risk_tier"],
            reviews=list_reviews(self.ledger, changeset_id),
            changeset_digest=changeset["digest"],
            head_sha=source_head_sha,
            author_owner_ids=changeset["author_owner_ids"],
        )
        revision_fresh = (
            changeset["base_revision"] == current_revision(self.ledger)["revision"]
        )
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
            "source_head_sha": source_head_sha,
            "merge_group": merge_group,
        }
        with self.ledger._connect() as conn:
            existing = conn.execute(
                """SELECT github_check_id FROM github_promotion_checks
                   WHERE changeset_id = ? AND head_sha = ? AND app_id = ?""",
                (changeset_id, target_head_sha, self.app_id),
            ).fetchone()
        payload = {
            "status": "completed",
            "conclusion": conclusion,
            "output": {
                "title": f"Ledger promotion: {conclusion.replace('_', ' ')}",
                "summary": self._summary(details),
            },
        }
        if existing is None:
            method = "POST"
            path = f"/repos/{self.repository_slug}/check-runs"
            payload = {
                "name": "ledger/promotion",
                "head_sha": target_head_sha,
                "external_id": f"forecast:{changeset_id}:{target_head_sha}",
                **payload,
            }
        else:
            method = "PATCH"
            path = (
                f"/repos/{self.repository_slug}/check-runs/"
                f"{existing['github_check_id']}"
            )
        response = self._client().call("check.write", method, path, payload)
        body = response.get("body")
        remote_id = str(body.get("id") or "") if isinstance(body, dict) else ""
        check_run_id = remote_id or (
            str(existing["github_check_id"]) if existing is not None else ""
        )
        if not check_run_id:
            raise ValidationError("GitHub did not return a check-run ID")
        if existing is not None and check_run_id != str(existing["github_check_id"]):
            raise ValidationError("GitHub updated a different promotion check")
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
                    check_run_id,
                    target_head_sha,
                    conclusion,
                    json.dumps(details, sort_keys=True),
                    utc_now_iso(),
                ),
            )
        updated = changeset if merge_group else self._transition(changeset_id, conclusion)
        return {
            "changeset_id": changeset_id,
            "head_sha": target_head_sha,
            "check_run_id": check_run_id,
            "conclusion": conclusion,
            "details": details,
            "status": updated["status"],
        }

    def publish_application_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Update the exact PR-head check with authoritative ledger outcome."""

        changeset_id = str(result.get("changeset_id") or "")
        changeset = get_changeset(self.ledger, changeset_id)
        state = str(changeset["status"])
        if state not in {"applied", "apply_failed"}:
            raise ValidationError("application result is not terminal")
        head_sha = str(changeset.get("head_sha") or "")
        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT github_check_id, details FROM github_promotion_checks
                   WHERE changeset_id = ? AND head_sha = ? AND app_id = ?""",
                (changeset_id, head_sha, self.app_id),
            ).fetchone()
        if row is None:
            raise ValidationError("application result requires the exact promotion check")
        details = json.loads(row["details"])
        application = {
            "state": state,
            "revision": changeset.get("applied_revision"),
            "ledger_digest": (changeset.get("metadata") or {})
            .get("apply_result", {})
            .get("ledger_digest"),
            "retryable": bool(result.get("retryable")),
            "reason": str(result.get("reason") or "")[:120] or None,
        }
        details["application_result"] = application
        conclusion = "success" if state == "applied" else "failure"
        check_run_id = str(row["github_check_id"])
        response = self._client().call(
            "check.write",
            "PATCH",
            f"/repos/{self.repository_slug}/check-runs/{check_run_id}",
            {
                "status": "completed",
                "conclusion": conclusion,
                "output": {
                    "title": f"Ledger application: {state.replace('_', ' ')}",
                    "summary": self._application_summary(application),
                },
            },
        )
        body = response.get("body")
        remote_id = str(body.get("id") or "") if isinstance(body, dict) else ""
        if remote_id and remote_id != check_run_id:
            raise ValidationError("GitHub updated a different promotion check")
        with self.ledger._connect() as conn:
            conn.execute(
                """UPDATE github_promotion_checks
                   SET details = ?, created_at = ?
                   WHERE changeset_id = ? AND head_sha = ? AND app_id = ?""",
                (
                    json.dumps(details, sort_keys=True),
                    utc_now_iso(),
                    changeset_id,
                    head_sha,
                    self.app_id,
                ),
            )
        return {
            "changeset_id": changeset_id,
            "head_sha": head_sha,
            "check_run_id": check_run_id,
            "state": state,
            "conclusion": conclusion,
        }

    def reconcile_application_results(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Repair terminal results lost between ledger commit and GitHub update."""

        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT c.id, c.status, p.details
                   FROM ledger_changesets c
                   JOIN github_promotion_checks p
                     ON p.changeset_id = c.id AND p.head_sha = c.head_sha
                    AND p.app_id = ?
                   WHERE c.status IN ('applied', 'apply_failed')
                   ORDER BY c.updated_at, c.id LIMIT ?""",
                (self.app_id, max(1, min(int(limit), 1000))),
            ).fetchall()
        pending = [
            row
            for row in rows
            if (json.loads(row["details"]).get("application_result") or {}).get("state")
            != row["status"]
        ]
        return [
            self.publish_application_result({"changeset_id": row["id"]})
            for row in pending
        ]

    def _client(self) -> Any:
        return self.client() if callable(self.client) else self.client

    def _transition(self, changeset_id: str, conclusion: str) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        target = {
            "success": "merge_ready",
            "action_required": "review_required",
            "failure": "blocked",
        }[conclusion]
        recorded = dict((changeset.get("metadata") or {}).get("promotion_check") or {})
        if changeset["status"] == target and recorded == {
            "app_id": self.app_id,
            "head_sha": changeset.get("head_sha"),
            "conclusion": conclusion,
        }:
            return changeset
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
        metadata = dict(changeset.get("metadata") or {})
        metadata["checks_passed"] = conclusion == "success"
        metadata["promotion_check"] = {
            "app_id": self.app_id,
            "head_sha": changeset.get("head_sha"),
            "conclusion": conclusion,
        }
        metadata.pop("promotion_check_error", None)
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

    @staticmethod
    def _application_summary(result: dict[str, Any]) -> str:
        if result["state"] == "applied":
            return "\n".join(
                [
                    "- Authoritative ledger application: applied",
                    f"- Ledger revision: `{result['revision']}`",
                    f"- Ledger digest: `{result['ledger_digest']}`",
                ]
            )
        return "\n".join(
            [
                "- Authoritative ledger application: failed",
                "- No partial ledger mutation was accepted.",
                "- Operator action: inspect safe diagnostics and create a superseding changeset for semantic conflicts.",
            ]
        )


__all__ = ["PromotionCheckPublisher"]
