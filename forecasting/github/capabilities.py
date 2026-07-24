"""Single-use GitHub request capabilities executed by the control plane."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from typing import Any, Callable, Iterable, Mapping

from forecasting.change_control.collaboration import get_identity_binding
from forecasting.change_control.store import get_changeset
from forecasting.models import ValidationError, utc_now_iso


_ACTION_RULES: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "repository.read": (("GET", re.compile(r"^/repos/[^/]+/[^/]+(?:/.*)?$")),),
    "branch.write": (
        ("POST", re.compile(r"^/repos/[^/]+/[^/]+/git/(?:refs|blobs|trees|commits)$")),
        ("PATCH", re.compile(r"^/repos/[^/]+/[^/]+/git/refs/heads/[A-Za-z0-9._/-]+$")),
        ("PUT", re.compile(r"^/repos/[^/]+/[^/]+/contents/[A-Za-z0-9._/-]+$")),
    ),
    "pull_request.write": (
        ("POST", re.compile(r"^/repos/[^/]+/[^/]+/pulls$")),
        ("PATCH", re.compile(r"^/repos/[^/]+/[^/]+/pulls/[0-9]+$")),
    ),
    "review.write": (
        ("POST", re.compile(r"^/repos/[^/]+/[^/]+/pulls/[0-9]+/reviews$")),
    ),
    "comment.write": (
        ("POST", re.compile(r"^/repos/[^/]+/[^/]+/issues/[0-9]+/comments$")),
    ),
    "repository.fork": (
        ("POST", re.compile(r"^/repos/[^/]+/[^/]+/forks$")),
    ),
}
_SECRET = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9_]{20,}|\bBearer\s+[A-Za-z0-9._~+/=-]{16,})",
    re.I,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class GitHubCapabilityBroker:
    def __init__(
        self,
        ledger: Any,
        *,
        repository_slug: str,
        signing_key: bytes,
        token_provider: Callable[[str], str],
        request: Callable[..., Any] | None = None,
        api_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        additional_repository_slugs: Iterable[str] = (),
        installation_authorizer: Callable[[str, str], object] | None = None,
    ) -> None:
        if len(signing_key) < 32:
            raise ValidationError("GitHub capability signing key must be at least 32 bytes")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        self.ledger = ledger
        self.repository_slug = repository_slug
        repositories = [repository_slug]
        for slug in additional_repository_slugs:
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", slug):
                raise ValidationError("additional repository slug is invalid")
            repositories.append(slug)
        self.repository_slugs = tuple(dict.fromkeys(repositories))
        self.signing_key = signing_key
        self.token_provider = token_provider
        if request is None:
            import httpx

            request = httpx.request
        self.request = request
        self.api_url = api_url.rstrip("/")
        self.api_version = api_version
        self.installation_authorizer = installation_authorizer

    def issue(
        self,
        *,
        changeset_id: str,
        identity_binding_id: str,
        actor_kind: str,
        action: str,
        method: str,
        path: str,
        ttl_seconds: int = 120,
    ) -> str:
        get_changeset(self.ledger, changeset_id)
        binding = get_identity_binding(self.ledger, identity_binding_id)
        if binding["status"] != "active":
            raise PermissionError("GitHub identity binding is revoked")
        if actor_kind not in {"human", "agent"}:
            raise ValidationError("GitHub capability actor_kind must be human or agent")
        method = method.upper()
        repository = self._authorize(action, method, path)
        payload = {
            "version": 1,
            "id": f"ghcap_{uuid.uuid4().hex[:16]}",
            "repository": repository,
            "changeset_id": changeset_id,
            "identity_binding_id": identity_binding_id,
            "owner_id": binding["owner_id"],
            "github_user_id": binding["github_user_id"],
            "agent_instance_id": binding["agent_instance_id"],
            "agent_persona": binding["agent_persona"],
            "actor_kind": actor_kind,
            "action": action,
            "method": method,
            "path": path,
            "expires_at": int(time.time()) + max(1, min(int(ttl_seconds), 600)),
        }
        encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
        signature = _b64(hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).digest())
        return f"{encoded}.{signature}"

    def execute(
        self,
        capability: str,
        *,
        method: str,
        path: str,
        json_body: Mapping[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        payload = self._verify(capability)
        method = method.upper()
        if payload["method"] != method or payload["path"] != path:
            raise PermissionError("GitHub capability method or path does not match")
        self._authorize(str(payload["action"]), method, path)
        binding = get_identity_binding(self.ledger, str(payload["identity_binding_id"]))
        if binding["status"] != "active" or binding["owner_id"] != payload["owner_id"]:
            raise PermissionError("GitHub identity binding is revoked or conflicting")
        with self.ledger._connect() as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO github_capability_uses
                   (capability_id, changeset_id, identity_binding_id, action,
                    repository_slug, used_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    payload["id"],
                    payload["changeset_id"],
                    payload["identity_binding_id"],
                    payload["action"],
                    payload["repository"],
                    utc_now_iso(),
                ),
            )
        if cursor.rowcount != 1:
            raise PermissionError("GitHub capability has already been used")
        try:
            token = self.token_provider(str(payload["identity_binding_id"]))
            request_kwargs: dict[str, Any] = {
                "headers": {
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": self.api_version,
                },
                "timeout": 20,
            }
            if json_body is not None:
                request_kwargs["json"] = dict(json_body)
            response = self.request(
                method,
                f"{self.api_url}{path}",
                **request_kwargs,
            )
            status_code = int(response.status_code)
            permission_denied = status_code in {401, 403} or (
                status_code == 404 and payload["action"] == "branch.write"
            )
            if permission_denied and status_code not in expected_statuses:
                raise GitHubPermissionError(
                    f"GitHub denied {payload['action']}", status_code=status_code
                )
            if status_code not in expected_statuses:
                response.raise_for_status()
            try:
                response_body = response.json()
            except Exception:
                response_body = None
            result = {"status_code": status_code, "body": _redact(response_body)}
            self._audit(payload, result="success")
            return result
        except GitHubPermissionError:
            self._audit(payload, result="failed")
            raise
        except Exception:
            self._audit(payload, result="failed")
            raise RuntimeError(f"GitHub {payload['action']} request failed") from None

    def _verify(self, capability: str) -> dict[str, Any]:
        try:
            encoded, supplied = capability.split(".", 1)
            expected = _b64(
                hmac.new(self.signing_key, encoded.encode(), hashlib.sha256).digest()
            )
            if not hmac.compare_digest(expected, supplied):
                raise ValueError("signature")
            payload = json.loads(_unb64(encoded))
        except Exception as exc:
            raise PermissionError("GitHub capability signature is invalid") from exc
        if payload.get("version") != 1 or payload.get("repository") not in self.repository_slugs:
            raise PermissionError("GitHub capability repository or version is invalid")
        if int(payload.get("expires_at") or 0) < int(time.time()):
            raise PermissionError("GitHub capability expired")
        return payload

    def _authorize(self, action: str, method: str, path: str) -> str:
        if "?" in path or "#" in path or "\\" in path or "%" in path or ".." in path.split("/"):
            raise PermissionError("GitHub capability path is ambiguous")
        repository = next(
            (
                slug
                for slug in self.repository_slugs
                if path == f"/repos/{slug}" or path.startswith(f"/repos/{slug}/")
            ),
            None,
        )
        if repository is None:
            raise PermissionError("GitHub capability is bound to another repository")
        if action == "repository.fork" and repository != self.repository_slug:
            raise PermissionError("only the canonical repository may be forked")
        rules = _ACTION_RULES.get(action, ())
        if not any(rule_method == method and pattern.fullmatch(path) for rule_method, pattern in rules):
            raise PermissionError("GitHub capability action does not allow this method and path")
        if self.installation_authorizer is not None:
            self.installation_authorizer(self.repository_slug, action)
        return repository

    def _audit(self, payload: Mapping[str, Any], *, result: str) -> None:
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_action_audit (
                       id, changeset_id, correlation_id, human_owner, github_actor,
                       agent_instance, agent_persona, actor_kind, action,
                       repository_slug, result, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"ghaudit_{uuid.uuid4().hex[:16]}",
                    payload["changeset_id"],
                    payload["id"],
                    payload["owner_id"],
                    payload["github_user_id"],
                    payload["agent_instance_id"],
                    payload["agent_persona"],
                    payload["actor_kind"],
                    payload["action"],
                    payload["repository"],
                    result,
                    utc_now_iso(),
                ),
            )


class CapabilityGitHubClient:
    """Bind every publisher call to one changeset and delegated identity."""

    def __init__(
        self,
        broker: GitHubCapabilityBroker,
        *,
        changeset_id: str,
        identity_binding_id: str,
        actor_kind: str,
    ) -> None:
        self.broker = broker
        self.changeset_id = changeset_id
        self.identity_binding_id = identity_binding_id
        self.actor_kind = actor_kind

    def call(
        self,
        action: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        expected_statuses: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        capability = self.broker.issue(
            changeset_id=self.changeset_id,
            identity_binding_id=self.identity_binding_id,
            actor_kind=self.actor_kind,
            action=action,
            method=method,
            path=path,
        )
        return self.broker.execute(
            capability,
            method=method,
            path=path,
            json_body=body,
            expected_statuses=expected_statuses,
        )


class GitHubPermissionError(PermissionError):
    """A redacted GitHub authorization failure suitable for fallback decisions."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _SECRET.sub("[REDACTED]", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if str(key).lower() in {"token", "access_token", "refresh_token", "authorization"}
            else _redact(item)
            for key, item in value.items()
        }
    return value


__all__ = ["CapabilityGitHubClient", "GitHubCapabilityBroker", "GitHubPermissionError"]
