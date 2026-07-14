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
from forecasting.github.capabilities import GitHubPermissionError
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
        fork_repository_slug: str | None = None,
        fork_owner_login: str | None = None,
        fork_owner_github_user_id: str | None = None,
        fork_client: GitHubCaller | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        if not _SAFE_BRANCH.fullmatch(default_branch) or ".." in default_branch.split("/"):
            raise ValidationError("default_branch contains unsafe characters")
        self.ledger = ledger
        self.repository_slug = repository_slug
        self.default_branch = default_branch
        self.client = client
        self.fork_repository_slug = fork_repository_slug
        self.fork_owner_login = fork_owner_login
        self.fork_owner_github_user_id = fork_owner_github_user_id
        self.fork_client = fork_client
        fork_values = (
            fork_repository_slug,
            fork_owner_login,
            fork_owner_github_user_id,
            fork_client,
        )
        if any(value is not None for value in fork_values):
            if not all(value is not None for value in fork_values):
                raise ValidationError("owner-fork fallback configuration is incomplete")
            if not re.fullmatch(
                r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(fork_repository_slug)
            ):
                raise ValidationError("fork_repository_slug must use owner/repository form")
            fork_owner, _ = str(fork_repository_slug).split("/", 1)
            if fork_owner.casefold() != str(fork_owner_login).casefold():
                raise ValidationError("fork repository owner must match the linked GitHub login")

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
            repository_slug=self.repository_slug,
        )
        validate_workspace(root, raise_on_error=True)
        preview = preview_changeset(self.ledger, changeset_id)
        publication = dict((changeset.get("metadata") or {}).get("github_publication") or {})
        head_repository = str(publication.get("head_repository") or self.repository_slug)
        tree_client = self.client
        if head_repository != self.repository_slug:
            if head_repository != self.fork_repository_slug or self.fork_client is None:
                raise ValidationError("stored GitHub publication repository is not authorized")
            self._ensure_owner_fork()
            tree_client = self.fork_client
        try:
            try:
                head_sha = self._publish_tree(
                    root,
                    branch,
                    changeset,
                    repository_slug=head_repository,
                    client=tree_client,
                )
            except GitHubPermissionError:
                if head_repository != self.repository_slug or self.fork_client is None:
                    raise
                self._ensure_owner_fork()
                head_repository = str(self.fork_repository_slug)
                tree_client = self.fork_client
                head_sha = self._publish_tree(
                    root,
                    branch,
                    changeset,
                    repository_slug=head_repository,
                    client=tree_client,
                )
            body = self._pull_request_body(
                changeset,
                preview=preview,
                provenance_digest=bundle["digest"],
                slack_thread_url=slack_thread_url,
            )
            reuse_pr = bool(changeset.get("pr_number")) and (
                not publication or publication.get("head_repository") == head_repository
            )
            pr = self._publish_pull_request(
                changeset,
                branch=branch,
                body=body,
                head_repository=head_repository,
                reuse_pr=reuse_pr,
            )
        except Exception as exc:
            self._record_publication_failure(changeset_id, exc)
            raise

        current = get_changeset(self.ledger, changeset_id)
        metadata = dict(current.get("metadata") or {})
        recovering_publication = "github_publication_error" in metadata
        metadata["github_publication"] = {
            "canonical_repository": self.repository_slug,
            "head_repository": head_repository,
            "mode": "canonical" if head_repository == self.repository_slug else "owner_fork",
        }
        metadata.pop("github_publication_error", None)
        updated = transition_changeset(
            self.ledger,
            changeset_id,
            current["status"],
            fields={
                "branch": branch,
                "head_sha": head_sha,
                "pr_number": int(pr["number"]),
                "metadata": metadata,
            },
        )
        if updated["status"] == "publishing":
            updated = transition_changeset(
                self.ledger,
                changeset_id,
                "review_open",
                expected_status="publishing",
            )
        elif updated["status"] == "blocked" and recovering_publication:
            updated = transition_changeset(
                self.ledger,
                changeset_id,
                "checks_running",
                expected_status="blocked",
            )
        return {
            "changeset_id": changeset_id,
            "repository": self.repository_slug,
            "head_repository": head_repository,
            "publication_mode": (
                "canonical" if head_repository == self.repository_slug else "owner_fork"
            ),
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
        *,
        repository_slug: str,
        client: GitHubCaller,
    ) -> str:
        branch_path = f"/repos/{repository_slug}/git/ref/heads/{branch}"
        branch_ref = client.call(
            "repository.read", "GET", branch_path, expected_statuses=(404,)
        )
        branch_exists = branch_ref["status_code"] != 404
        if branch_exists:
            parent_sha = str(_body(branch_ref).get("object", {}).get("sha") or "")
        else:
            base_ref = client.call(
                "repository.read",
                "GET",
                f"/repos/{repository_slug}/git/ref/heads/{self.default_branch}",
            )
            parent_sha = str(_body(base_ref).get("object", {}).get("sha") or "")
        if not parent_sha:
            raise ValidationError("GitHub branch response did not include a commit SHA")
        parent_commit = client.call(
            "repository.read",
            "GET",
            f"/repos/{repository_slug}/git/commits/{parent_sha}",
        )
        parent_tree = str(_body(parent_commit).get("tree", {}).get("sha") or "")
        if not parent_tree:
            raise ValidationError("GitHub commit response did not include a tree SHA")

        entries: list[dict[str, str]] = []
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix()
            blob = client.call(
                "branch.write",
                "POST",
                f"/repos/{repository_slug}/git/blobs",
                {
                    "content": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "encoding": "base64",
                },
            )
            blob_sha = str(_body(blob).get("sha") or "")
            if not blob_sha:
                raise ValidationError(f"GitHub did not return a blob SHA for {relative}")
            entries.append({"path": relative, "mode": "100644", "type": "blob", "sha": blob_sha})
        tree = client.call(
            "branch.write",
            "POST",
            f"/repos/{repository_slug}/git/trees",
            {"base_tree": parent_tree, "tree": entries},
        )
        tree_sha = str(_body(tree).get("sha") or "")
        if not tree_sha:
            raise ValidationError("GitHub did not return a tree SHA")
        head_sha = parent_sha
        if tree_sha != parent_tree:
            commit = client.call(
                "branch.write",
                "POST",
                f"/repos/{repository_slug}/git/commits",
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
                client.call(
                    "branch.write",
                    "PATCH",
                    branch_path,
                    {"sha": head_sha, "force": False},
                )
        else:
            client.call(
                "branch.write",
                "POST",
                f"/repos/{repository_slug}/git/refs",
                {"ref": f"refs/heads/{branch}", "sha": head_sha},
            )
        return head_sha

    def _publish_pull_request(
        self,
        changeset: Mapping[str, Any],
        *,
        branch: str,
        body: str,
        head_repository: str,
        reuse_pr: bool,
    ) -> Mapping[str, Any]:
        head_owner = head_repository.split("/", 1)[0]
        payload = {
            "title": f"Forecast changeset {changeset['id']}",
            "body": body,
            "base": self.default_branch,
            "head": branch if head_repository == self.repository_slug else f"{head_owner}:{branch}",
            "draft": True,
        }
        if reuse_pr:
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

    def _ensure_owner_fork(self) -> Mapping[str, Any]:
        if self.fork_client is None or self.fork_repository_slug is None:
            raise GitHubPermissionError(
                "canonical branch write was denied and no owner fork is configured"
            )
        result = self.fork_client.call(
            "repository.read",
            "GET",
            f"/repos/{self.fork_repository_slug}",
            expected_statuses=(404,),
        )
        if result["status_code"] == 404:
            result = self.fork_client.call(
                "repository.fork",
                "POST",
                f"/repos/{self.repository_slug}/forks",
                {},
            )
        repository = _body(result)
        full_name = str(repository.get("full_name") or "")
        owner = repository.get("owner")
        parent = repository.get("parent")
        source = repository.get("source")
        if not (
            isinstance(owner, Mapping)
            and isinstance(parent, Mapping)
            and isinstance(source, Mapping)
        ):
            raise PermissionError("GitHub owner fork identity or ancestry is invalid")
        ancestry = {str(parent.get("full_name") or ""), str(source.get("full_name") or "")}
        if (
            full_name.casefold() != self.fork_repository_slug.casefold()
            or str(owner.get("login") or "").casefold()
            != str(self.fork_owner_login).casefold()
            or str(owner.get("id") or "") != str(self.fork_owner_github_user_id)
            or self.repository_slug.casefold()
            not in {value.casefold() for value in ancestry if value}
        ):
            raise PermissionError("GitHub owner fork identity or ancestry is invalid")
        return repository

    def _record_publication_failure(self, changeset_id: str, exc: Exception) -> None:
        current = get_changeset(self.ledger, changeset_id)
        metadata = dict(current.get("metadata") or {})
        metadata["github_publication_error"] = {
            "recoverable": True,
            "category": (
                "permission_denied"
                if isinstance(exc, (GitHubPermissionError, PermissionError))
                else "publication_failed"
            ),
        }
        status = "blocked" if current["status"] in _REPUBLISHABLE else current["status"]
        transition_changeset(
            self.ledger,
            changeset_id,
            status,
            expected_status=current["status"],
            fields={"metadata": metadata},
        )

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
