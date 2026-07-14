"""Signed, durable, idempotent GitHub webhook ingress."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping

from forecasting.models import ValidationError, utc_now_iso


SUPPORTED_EVENTS = frozenset(
    {
        "pull_request",
        "pull_request_review",
        "pull_request_review_comment",
        "issue_comment",
        "check_suite",
        "check_run",
        "push",
        "merge_group",
        "installation",
        "installation_repositories",
        "github_app_authorization",
    }
)


def verify_github_signature(body: bytes, *, secret: str, signature: str) -> None:
    if not secret:
        raise ValidationError("GitHub webhook secret is not configured")
    if not signature.startswith("sha256="):
        raise PermissionError("GitHub webhook signature is missing or invalid")
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise PermissionError("GitHub webhook signature did not match")


def ingest_github_webhook(
    ledger: Any,
    *,
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    repository_slug: str,
    repository_id: str | None = None,
) -> dict[str, Any]:
    normalized = {str(key).lower(): str(value) for key, value in headers.items()}
    verify_github_signature(
        body,
        secret=secret,
        signature=normalized.get("x-hub-signature-256", ""),
    )
    delivery_id = normalized.get("x-github-delivery", "").strip()
    event_type = normalized.get("x-github-event", "").strip()
    if not delivery_id or not event_type:
        raise ValidationError("GitHub delivery and event headers are required")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError("GitHub webhook payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationError("GitHub webhook payload must be an object")
    installation = payload.get("installation") or {}
    repository = payload.get("repository") or {}
    actual_slug = str(repository.get("full_name") or "")
    actual_id = str(repository.get("id") or "")
    authorized = actual_slug.lower() == repository_slug.lower() and (
        repository_id is None or actual_id == str(repository_id)
    )
    quarantine_reason = None
    if event_type not in SUPPORTED_EVENTS:
        quarantine_reason = "unsupported_event"
    elif not authorized and event_type not in {"installation", "github_app_authorization"}:
        quarantine_reason = "unauthorized_repository"
    state = "quarantined" if quarantine_reason else "pending"
    sanitized = _sanitize_payload(event_type, payload)
    with ledger._connect() as conn:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO github_webhook_deliveries (
                   delivery_id, event_type, action, installation_id,
                   repository_id, repository_slug, state, payload,
                   quarantine_reason, received_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                delivery_id,
                event_type,
                payload.get("action"),
                str(installation.get("id") or "") or None,
                actual_id or None,
                actual_slug or None,
                state,
                json.dumps(sanitized, sort_keys=True),
                quarantine_reason,
                utc_now_iso(),
            ),
        )
        if cursor.rowcount == 0:
            conn.execute(
                """UPDATE github_webhook_deliveries
                   SET redelivery_count = redelivery_count + 1
                   WHERE delivery_id = ?""",
                (delivery_id,),
            )
        row = conn.execute(
            "SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


def mark_delivery_processed(ledger: Any, delivery_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        cursor = conn.execute(
            """UPDATE github_webhook_deliveries
               SET state = 'processed', processed_at = ?
               WHERE delivery_id = ? AND state = 'pending'""",
            (utc_now_iso(), delivery_id),
        )
        row = conn.execute(
            "SELECT * FROM github_webhook_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
    if row is None:
        raise ValidationError(f"GitHub delivery not found: {delivery_id}")
    if cursor.rowcount == 0 and row["state"] not in {"processed", "quarantined"}:
        raise ValidationError(f"GitHub delivery cannot be processed from {row['state']}")
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


def _user(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    return {key: value.get(key) for key in ("id", "node_id", "login", "type", "html_url")}


def _sanitize_payload(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "action": payload.get("action"),
        "sender": _user(payload.get("sender")),
    }
    installation = payload.get("installation")
    if isinstance(installation, Mapping):
        result["installation"] = {"id": installation.get("id")}
    repository = payload.get("repository")
    if isinstance(repository, Mapping):
        result["repository"] = {
            key: repository.get(key)
            for key in ("id", "node_id", "full_name", "private", "html_url", "default_branch")
        }
    pull = payload.get("pull_request")
    if isinstance(pull, Mapping):
        result["pull_request"] = {
            "id": pull.get("id"),
            "number": pull.get("number"),
            "state": pull.get("state"),
            "draft": pull.get("draft"),
            "merged": pull.get("merged"),
            "merge_commit_sha": pull.get("merge_commit_sha"),
            "html_url": pull.get("html_url"),
            "head": {
                "ref": (pull.get("head") or {}).get("ref"),
                "sha": (pull.get("head") or {}).get("sha"),
            },
            "base": {
                "ref": (pull.get("base") or {}).get("ref"),
                "sha": (pull.get("base") or {}).get("sha"),
            },
        }
    issue = payload.get("issue")
    if isinstance(issue, Mapping):
        result["issue"] = {
            "id": issue.get("id"),
            "number": issue.get("number"),
            "html_url": issue.get("html_url"),
            "pull_request": bool(issue.get("pull_request")),
        }
    for key in ("review", "comment"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            result[key] = {
                field: value.get(field)
                for field in ("id", "node_id", "state", "commit_id", "html_url", "created_at")
            }
            result[key]["user"] = _user(value.get("user"))
    for key in ("check_run", "check_suite", "merge_group"):
        value = payload.get(key)
        if isinstance(value, Mapping):
            result[key] = {
                field: value.get(field)
                for field in (
                    "id",
                    "node_id",
                    "name",
                    "status",
                    "conclusion",
                    "head_sha",
                    "head_ref",
                )
            }
            app = value.get("app")
            if isinstance(app, Mapping):
                result[key]["app"] = {"id": app.get("id"), "slug": app.get("slug")}
    if event_type == "push":
        result.update({key: payload.get(key) for key in ("ref", "before", "after", "forced")})
    if isinstance(payload.get("authorization"), Mapping):
        result["authorization"] = {
            "id": payload["authorization"].get("id"),
            "user": _user(payload["authorization"].get("user")),
        }
    return result


__all__ = [
    "SUPPORTED_EVENTS",
    "ingest_github_webhook",
    "mark_delivery_processed",
    "verify_github_signature",
]
