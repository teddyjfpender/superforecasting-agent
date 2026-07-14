"""Deterministic Git branch and draft-PR publication for one changeset."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Mapping, Protocol

from forecasting.change_control.policy import evaluate_quorum
from forecasting.change_control.preview import preview_changeset
from forecasting.change_control.provenance import ensure_bundle
from forecasting.change_control.store import (
    get_changeset,
    list_reviews,
    transition_changeset,
)
from forecasting.models import ValidationError
from forecasting.workspace import export_workspace, validate_workspace


_SAFE_BRANCH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,239}$")
_REPUBLISHABLE = frozenset(
    {
        "publishing",
        "review_open",
        "checks_running",
        "review_required",
        "changes_requested",
        "held",
        "blocked",
    }
)


class GitHubCaller(Protocol):
    def call(
        self,
        action: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        expected_statuses: tuple[int, ...] = (),
    ) -> dict[str, Any]: ...


class GitHubPublisher:
    """Publish validated workspace files without exposing delegated credentials."""

    def __init__(
        self,
        ledger: Any,
        *,
        repository_slug: str,
        client: GitHubCaller,
        default_branch: str = "main",
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        if not _SAFE_BRANCH.fullmatch(default_branch) or ".." in default_branch.split("/"):
            raise ValidationError("default_branch contains unsafe characters")
        self.ledger = ledger
        self.repository_slug = repository_slug
        self.default_branch = default_branch
        self.client = client

    def publish(
        self,
        changeset_id: str,
        output_dir: str | Path,
        *,
        slack_thread_url: str | None = None,
    ) -> dict[str, Any]:
        changeset = self._prepare(changeset_id)
        branch = str(changeset.get("branch") or f"forecast/changesets/{changeset_id}")
        if not _SAFE_BRANCH.fullmatch(branch) or ".." in branch.split("/"):
            raise ValidationError("changeset branch contains unsafe characters")

        bundle = ensure_bundle(self.ledger, changeset_id)
        root = Path(output_dir).expanduser()
        export_workspace(
            self.ledger,
            root,
            workspace_id=changeset["workspace_id"],
            default_branch=self.default_branch,
        )
        validate_workspace(root, raise_on_error=True)
        preview = preview_changeset(self.ledger, changeset_id)
        head_sha = self._publish_tree(root, branch, changeset)
        body = self._pull_request_body(
            changeset,
            preview=preview,
            provenance_digest=bundle["digest"],
            slack_thread_url=slack_thread_url,
        )
        pr = self._publish_pull_request(changeset, branch=branch, body=body)

        current = get_changeset(self.ledger, changeset_id)
        updated = transition_changeset(
            self.ledger,
            changeset_id,
            current["status"],
            fields={
                "branch": branch,
                "head_sha": head_sha,
                "pr_number": int(pr["number"]),
            },
        )
        if updated["status"] == "publishing":
            updated = transition_changeset(
                self.ledger,
                changeset_id,
                "review_open",
                expected_status="publishing",
            )
        return {
            "changeset_id": changeset_id,
            "repository": self.repository_slug,
            "branch": branch,
            "head_sha": head_sha,
            "pr_number": int(pr["number"]),
            "pr_url": pr.get("html_url"),
            "provenance_digest": bundle["digest"],
            "projection_digest": preview["projection_digest"],
            "status": updated["status"],
        }

    def _prepare(self, changeset_id: str) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        if changeset["status"] in {"draft", "preview_failed"}:
            preview = preview_changeset(self.ledger, changeset_id)
            if preview["failures"]:
                if changeset["status"] == "draft":
                    transition_changeset(self.ledger, changeset_id, "preview_failed")
                raise ValidationError("changeset preview failed; publication stopped")
            changeset = transition_changeset(self.ledger, changeset_id, "ready")
        if changeset["status"] == "ready":
            changeset = transition_changeset(self.ledger, changeset_id, "publishing")
        if changeset["status"] not in _REPUBLISHABLE:
            raise ValidationError(
                f"cannot publish changeset {changeset_id} in status {changeset['status']}"
            )
        return changeset

    def _publish_tree(
        self,
        root: Path,
        branch: str,
        changeset: Mapping[str, Any],
    ) -> str:
        branch_path = f"/repos/{self.repository_slug}/git/ref/heads/{branch}"
        branch_ref = self.client.call(
            "repository.read", "GET", branch_path, expected_statuses=(404,)
        )
        branch_exists = branch_ref["status_code"] != 404
        if branch_exists:
            parent_sha = str(_body(branch_ref).get("object", {}).get("sha") or "")
        else:
            base_ref = self.client.call(
                "repository.read",
                "GET",
                f"/repos/{self.repository_slug}/git/ref/heads/{self.default_branch}",
            )
            parent_sha = str(_body(base_ref).get("object", {}).get("sha") or "")
        if not parent_sha:
            raise ValidationError("GitHub branch response did not include a commit SHA")
        parent_commit = self.client.call(
            "repository.read",
            "GET",
            f"/repos/{self.repository_slug}/git/commits/{parent_sha}",
        )
        parent_tree = str(_body(parent_commit).get("tree", {}).get("sha") or "")
        if not parent_tree:
            raise ValidationError("GitHub commit response did not include a tree SHA")

        entries: list[dict[str, str]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            blob = self.client.call(
                "branch.write",
                "POST",
                f"/repos/{self.repository_slug}/git/blobs",
                {
                    "content": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blob_sha = str(_body(blob).get("sha") or "")
            if not blob_sha:
                raise ValidationError(f"GitHub did not return a blob SHA for {relative}")
            entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": blob_sha})
        tree = self.client.call(
            "branch.write",
            "POST",
            f"/repos/{self.repository_slug}/git/trees",
            {"base_tree": parent_tree, "tree": entries},
        )
        tree_sha = str(_body(tree).get("sha") or "")
        if not tree_sha:
            raise ValidationError("GitHub did not return a tree SHA")
        head_sha = parent_sha
        if tree_sha != parent_tree:
            commit = self.client.call(
                "branch.write",
                "POST",
                f"/repos/{self.repository_slug}/git/commits",
                {
                    "message": f"Forecast changeset {changeset['id']}\n\nDigest: {changeset['digest']}",
                    "tree": tree_sha,
                    "parents": [parent_sha],
                },
            )
            head_sha = str(_body(commit).get("sha") or "")
            if not head_sha:
                raise ValidationError("GitHub did not return a commit SHA")
        if branch_exists:
            if head_sha != parent_sha:
                self.client.call(
                    "branch.write",
                    "PATCH",
                    branch_path,
                    {"sha": head_sha, "force": False},
                )
        else:
            self.client.call(
                "branch.write",
                "POST",
                f"/repos/{self.repository_slug}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": head_sha},
            )
        return head_sha

    def _publish_pull_request(
        self,
        changeset: Mapping[str, Any],
        *,
        branch: str,
        body: str,
    ) -> Mapping[str, Any]:
        payload = {
            "title": f"Forecast changeset {changeset['id']}",
            "body": body,
            "base": self.default_branch,
            "head": branch,
            "draft": True,
        }
        if changeset.get("pr_number"):
            result = self.client.call(
                "pull_request.write",
                "PATCH",
                f"/repos/{self.repository_slug}/pulls/{int(changeset['pr_number'])}",
                {"title": payload["title"], "body": body},
            )
        else:
            result = self.client.call(
                "pull_request.write",
                "POST",
                f"/repos/{self.repository_slug}/pulls",
                payload,
            )
        value = _body(result)
        if not value.get("number"):
            raise ValidationError("GitHub did not return a pull request number")
        return value

    def _pull_request_body(
        self,
        changeset: Mapping[str, Any],
        *,
        preview: Mapping[str, Any],
        provenance_digest: str,
        slack_thread_url: str | None,
    ) -> str:
        quorum = evaluate_quorum(
            risk_tier=str(changeset["risk_tier"]),
            reviews=list_reviews(self.ledger, str(changeset["id"])),
            changeset_digest=str(changeset["digest"]),
            head_sha=changeset.get("head_sha"),
            author_owner_ids=changeset.get("author_owner_ids") or (),
        )
        lines = [
            "<!-- forecast-changeset:start -->",
            f"## Forecast changeset `{changeset['id']}`",
            "",
            f"- Risk: **{changeset['risk_tier']}**",
            f"- Base ledger revision: `{changeset['base_revision']}`",
            f"- Changeset digest: `{changeset['digest']}`",
            f"- Projection digest: `{preview['projection_digest']}`",
            f"- Provenance digest: `{provenance_digest}`",
            f"- Required human approvals: `{quorum.required_humans}`",
            f"- Quorum satisfied: `{'yes' if quorum.satisfied else 'no'}`",
            f"- Preview checks: `{'passing' if preview['would_apply'] else 'blocked'}`",
        ]
        if slack_thread_url:
            lines.append(f"- Slack thread: {slack_thread_url}")
        affected = changeset.get("affected_question_ids") or ()
        lines.extend(["", "### Affected forecasts", ""])
        lines.extend(f"- `{question_id}`" for question_id in affected)
        if not affected:
            lines.append("- None declared")
        lines.extend(["", "### Before / after", "", str(preview["markdown"]).strip()])
        lines.extend(
            [
                "",
                "> Agent-authored commits and comments use the owner's delegated GitHub identity ",
                "> but remain explicitly attested as agent actions and never count as human approval.",
                "<!-- forecast-changeset:end -->",
            ]
        )
        return "\n".join(lines).rstrip() + "\n"


def _body(result: Mapping[str, Any]) -> Mapping[str, Any]:
    value = result.get("body")
    if not isinstance(value, Mapping):
        raise ValidationError("GitHub returned an invalid response body")
    return value


__all__ = ["GitHubCaller", "GitHubPublisher"]
