"""Durable GitHub App installation and repository permission state."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import urlencode

from forecasting.models import ValidationError, utc_now_iso


_ACTION_PERMISSION = {
    "repository.read": ("contents", "read"),
    "branch.write": ("contents", "write"),
    "pull_request.write": ("pull_requests", "write"),
    "review.write": ("pull_requests", "write"),
    "comment.write": ("issues", "write"),
    "repository.fork": ("contents", "read"),
    "check.write": ("checks", "write"),
}
_LEVEL = {"read": 1, "write": 2, "admin": 3}


class GitHubInstallationRegistry:
    """Project signed installation webhooks into one repository-bound grant."""

    def __init__(self, ledger: Any, *, app_id: str, repository_slug: str) -> None:
        if not str(app_id or "").strip():
            raise ValidationError("GitHub App ID is required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        self.ledger = ledger
        self.app_id = str(app_id)
        self.repository_slug = repository_slug.lower()

    def apply(
        self, *, event_type: str, action: str, payload: Mapping[str, Any]
    ) -> None:
        if event_type not in {"installation", "installation_repositories"}:
            raise ValidationError("unsupported GitHub installation event")
        installation = payload.get("installation") or {}
        installation_id = str(installation.get("id") or "")
        event_app_id = str(installation.get("app_id") or self.app_id)
        if not installation_id or event_app_id != self.app_id:
            raise PermissionError("GitHub installation event belongs to another App")
        if event_type == "installation":
            self._installation(installation_id, action, installation, payload)
        else:
            self._repositories(installation_id, action, installation, payload)

    def authorize(self, repository_slug: str, action: str) -> str:
        """Require the App-side half of a delegated user capability."""

        if repository_slug.lower() != self.repository_slug:
            raise PermissionError(
                "GitHub App installation is bound to another repository"
            )
        permission = _ACTION_PERMISSION.get(action)
        if permission is None:
            raise PermissionError(
                "GitHub App installation does not recognize this action"
            )
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT i.installation_id, i.permissions
                   FROM github_app_installations i
                   JOIN github_app_installation_repositories r
                     ON r.installation_id = i.installation_id
                   WHERE i.app_id = ? AND i.status = 'active'
                     AND lower(r.repository_slug) = ? AND r.status = 'active'
                   ORDER BY i.updated_at DESC, i.installation_id""",
                (self.app_id, self.repository_slug),
            ).fetchall()
        if not rows:
            raise PermissionError(
                "GitHub App is not actively installed for the workspace repository"
            )
        name, required = permission
        for row in rows:
            if _permits(json.loads(row["permissions"]), name, required):
                return str(row["installation_id"])
        raise PermissionError(
            f"GitHub App installation lacks required {name}:{required} permission"
        )

    def status(self) -> list[dict[str, Any]]:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT i.installation_id, i.app_id, i.account_id,
                          i.account_login, i.target_type, i.repository_selection,
                          i.permissions, i.status, i.suspended_at, i.updated_at,
                          r.repository_id, r.repository_slug, r.private,
                          r.status AS repository_status
                   FROM github_app_installations i
                   LEFT JOIN github_app_installation_repositories r
                     ON r.installation_id = i.installation_id
                   ORDER BY i.updated_at DESC, i.installation_id, r.repository_slug"""
            ).fetchall()
        return [
            {
                **dict(row),
                "permissions": json.loads(row["permissions"]),
                "private": None if row["private"] is None else bool(row["private"]),
            }
            for row in rows
        ]

    def begin(self, *, app_slug: str, ttl_seconds: int = 600) -> dict[str, Any]:
        state = secrets.token_urlsafe(32)
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        ttl = max(60, min(int(ttl_seconds), 3600))
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(seconds=ttl))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_installation_states
                   (state_hash, repository_slug, expires_at, created_at)
                   VALUES (?, ?, ?, ?)""",
                (state_hash, self.repository_slug, expires_at, utc_now_iso()),
            )
        return {
            "installation_url": installation_url(app_slug, state=state),
            "repository": self.repository_slug,
            "expires_in_seconds": ttl,
        }

    def complete(self, *, state: str, installation_id: str) -> dict[str, Any]:
        state_hash = hashlib.sha256(str(state or "").encode()).hexdigest()
        installation_id = str(installation_id or "")
        if not state or not installation_id:
            raise ValidationError("GitHub installation callback is invalid")
        with self.ledger.transaction(immediate=True):
            with self.ledger._connect() as conn:
                pending = conn.execute(
                    "SELECT * FROM github_installation_states WHERE state_hash = ?",
                    (state_hash,),
                ).fetchone()
                if pending is None or pending["consumed_at"]:
                    raise ValidationError(
                        "GitHub installation state is invalid or already used"
                    )
                if pending["expires_at"] <= utc_now_iso():
                    raise ValidationError("GitHub installation state expired")
                if str(pending["repository_slug"]).lower() != self.repository_slug:
                    raise PermissionError(
                        "GitHub installation state belongs to another repository"
                    )
                grant = conn.execute(
                    """SELECT i.installation_id FROM github_app_installations i
                       JOIN github_app_installation_repositories r
                         ON r.installation_id = i.installation_id
                       WHERE i.installation_id = ? AND i.app_id = ?
                         AND i.status = 'active' AND r.status = 'active'
                         AND lower(r.repository_slug) = ?""",
                    (installation_id, self.app_id, self.repository_slug),
                ).fetchone()
                if grant is None:
                    raise PermissionError(
                        "GitHub installation has not granted the workspace repository"
                    )
                conn.execute(
                    """UPDATE github_installation_states
                       SET installation_id = ?, consumed_at = ? WHERE state_hash = ?""",
                    (installation_id, utc_now_iso(), state_hash),
                )
        return {
            "status": "installed",
            "installation_id": installation_id,
            "repository": self.repository_slug,
        }

    def _installation(
        self,
        installation_id: str,
        action: str,
        installation: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> None:
        account = installation.get("account") or {}
        now = utc_now_iso()
        if action == "deleted":
            with self.ledger._connect() as conn:
                conn.execute(
                    """UPDATE github_app_installations
                       SET status = 'deleted', updated_at = ? WHERE installation_id = ?""",
                    (now, installation_id),
                )
                conn.execute(
                    """UPDATE github_app_installation_repositories
                       SET status = 'removed', updated_at = ? WHERE installation_id = ?""",
                    (now, installation_id),
                )
            return
        if action not in {
            "created",
            "new_permissions_accepted",
            "suspend",
            "unsuspend",
        }:
            return
        account_id = str(account.get("id") or "")
        account_login = str(account.get("login") or "")
        if not account_id or not account_login:
            raise ValidationError(
                "GitHub installation lacks immutable account identity"
            )
        status = (
            "suspended"
            if action == "suspend" or installation.get("suspended_at")
            else "active"
        )
        suspended_at = str(installation.get("suspended_at") or "") or (
            now if status == "suspended" else None
        )
        permissions = _permissions(installation.get("permissions"))
        selection = str(installation.get("repository_selection") or "selected")
        if selection not in {"all", "selected"}:
            raise ValidationError("GitHub installation repository selection is invalid")
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_app_installations
                   (installation_id, app_id, account_id, account_node_id,
                    account_login, target_type, repository_selection, permissions,
                    status, suspended_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(installation_id) DO UPDATE SET
                     app_id = excluded.app_id, account_id = excluded.account_id,
                     account_node_id = excluded.account_node_id,
                     account_login = excluded.account_login,
                     target_type = excluded.target_type,
                     repository_selection = excluded.repository_selection,
                     permissions = excluded.permissions, status = excluded.status,
                     suspended_at = excluded.suspended_at,
                     updated_at = excluded.updated_at""",
                (
                    installation_id,
                    self.app_id,
                    account_id,
                    str(account.get("node_id") or "") or None,
                    account_login,
                    str(installation.get("target_type") or "") or None,
                    selection,
                    json.dumps(permissions, sort_keys=True),
                    status,
                    suspended_at,
                    now,
                    now,
                ),
            )
        self._upsert_repositories(
            installation_id, payload.get("repositories") or [], "active"
        )

    def _repositories(
        self,
        installation_id: str,
        action: str,
        installation: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> None:
        if action not in {"added", "removed"}:
            return
        with self.ledger._connect() as conn:
            row = conn.execute(
                "SELECT app_id FROM github_app_installations WHERE installation_id = ?",
                (installation_id,),
            ).fetchone()
        if row is None or row["app_id"] != self.app_id:
            raise PermissionError("GitHub installation repository event is not linked")
        permissions = installation.get("permissions")
        selection = installation.get("repository_selection")
        if permissions is not None or selection is not None:
            fields: list[str] = ["updated_at = ?"]
            values: list[Any] = [utc_now_iso()]
            if permissions is not None:
                fields.append("permissions = ?")
                values.append(json.dumps(_permissions(permissions), sort_keys=True))
            if selection is not None:
                fields.append("repository_selection = ?")
                values.append(str(selection))
            values.append(installation_id)
            with self.ledger._connect() as conn:
                conn.execute(
                    f"UPDATE github_app_installations SET {', '.join(fields)} WHERE installation_id = ?",
                    values,
                )
        key = "repositories_added" if action == "added" else "repositories_removed"
        self._upsert_repositories(
            installation_id,
            payload.get(key) or [],
            "active" if action == "added" else "removed",
        )

    def _upsert_repositories(
        self, installation_id: str, repositories: Any, status: str
    ) -> None:
        if not isinstance(repositories, list):
            raise ValidationError("GitHub installation repositories must be a list")
        now = utc_now_iso()
        with self.ledger._connect() as conn:
            for repository in repositories:
                if not isinstance(repository, Mapping):
                    raise ValidationError("GitHub installation repository is invalid")
                repository_id = str(repository.get("id") or "")
                slug = str(repository.get("full_name") or "")
                if not repository_id or not re.fullmatch(
                    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug
                ):
                    raise ValidationError(
                        "GitHub installation repository identity is invalid"
                    )
                conn.execute(
                    """INSERT INTO github_app_installation_repositories
                       (installation_id, repository_id, repository_node_id,
                        repository_slug, private, status, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(installation_id, repository_id) DO UPDATE SET
                         repository_node_id = excluded.repository_node_id,
                         repository_slug = excluded.repository_slug,
                         private = excluded.private, status = excluded.status,
                         updated_at = excluded.updated_at""",
                    (
                        installation_id,
                        repository_id,
                        str(repository.get("node_id") or "") or None,
                        slug,
                        int(bool(repository.get("private", True))),
                        status,
                        now,
                    ),
                )


def installation_url(app_slug: str, *, state: str | None = None) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]+", str(app_slug or "")):
        raise ValidationError("GitHub App slug is required for installation")
    base = f"https://github.com/apps/{app_slug}/installations/new"
    return base if state is None else f"{base}?{urlencode({'state': state})}"


def _permissions(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValidationError("GitHub installation permissions are invalid")
    result = {str(name): str(level).lower() for name, level in value.items()}
    if any(level not in _LEVEL for level in result.values()):
        raise ValidationError("GitHub installation permission level is invalid")
    return result


def _permits(permissions: Mapping[str, str], name: str, required: str) -> bool:
    return _LEVEL.get(str(permissions.get(name) or ""), 0) >= _LEVEL[required]


__all__ = ["GitHubInstallationRegistry", "installation_url"]
