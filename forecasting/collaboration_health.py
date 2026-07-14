"""Secret-free collaboration health snapshot for operators and metrics adapters."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable

from forecasting.change_control import ChangeControl


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _oldest_age(rows: Iterable[Any], field: str, now: datetime) -> int | None:
    values = [_time(row[field]) for row in rows]
    timestamps = [value for value in values if value is not None]
    return None if not timestamps else max(0, int((now - min(timestamps)).total_seconds()))


def _heartbeat_expected(value: str | None) -> bool:
    try:
        state = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return True
    return not isinstance(state, dict) or bool(state.get("heartbeat_expected"))


def collaboration_health(ledger: Any, *, now: datetime | None = None) -> dict[str, Any]:
    """Return bounded metrics and safe repair advice without contacting GitHub or Slack."""

    ChangeControl(ledger)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_iso = current.isoformat().replace("+00:00", "Z")
    with ledger._connect() as conn:
        webhooks = conn.execute(
            """SELECT state, redelivery_count, received_at, processed_at
               FROM github_webhook_deliveries"""
        ).fetchall()
        changesets = conn.execute(
            """SELECT id, status, pr_number, merge_sha, created_at, updated_at
               FROM ledger_changesets"""
        ).fetchall()
        cards = conn.execute(
            "SELECT last_heartbeat_at, state FROM slack_changeset_cards"
        ).fetchall()
        mirrors = conn.execute("SELECT state FROM github_slack_mirrors").fetchall()
        transcripts = conn.execute(
            "SELECT status FROM provenance_transcripts"
        ).fetchall()
        traces = conn.execute(
            """SELECT state, retention_deadline, pin_expires_at, legal_hold
               FROM provenance_trace_archives"""
        ).fetchall()
        tokens = conn.execute(
            "SELECT status, expires_at, refresh_expires_at FROM github_user_tokens"
        ).fetchall()
        publication_times = conn.execute(
            """SELECT c.created_at, MIN(a.created_at) AS published_at
               FROM ledger_changesets c
               JOIN github_action_audit a ON a.changeset_id = c.id
               WHERE a.action IN ('branch.write', 'pull_request.write')
               GROUP BY c.id, c.created_at"""
        ).fetchall()

    pending_webhooks = [row for row in webhooks if row["state"] == "pending"]
    pending_apply = [row for row in changesets if row["status"] == "merged_apply_pending"]
    apply_failed = [row for row in changesets if row["status"] == "apply_failed"]
    approval_wait = [
        row for row in changesets if row["status"] in {"review_required", "changes_requested"}
    ]
    unpublished = [
        row
        for row in changesets
        if row["pr_number"] is None
        and row["status"] not in {"applied", "cancelled", "abandoned", "superseded"}
    ]
    stale_cards = [
        row
        for row in cards
        if _heartbeat_expected(row["state"])
        and (
            (stamp := _time(row["last_heartbeat_at"])) is None
            or (current - stamp).total_seconds() > 120
        )
    ]
    overdue_traces = [
        row
        for row in traces
        if row["state"] == "active"
        and row["retention_deadline"] <= now_iso
        and not row["legal_hold"]
        and (not row["pin_expires_at"] or row["pin_expires_at"] <= now_iso)
    ]
    expired_tokens = [
        row
        for row in tokens
        if row["status"] == "active"
        and row["expires_at"]
        and row["expires_at"] <= now_iso
        and (not row["refresh_expires_at"] or row["refresh_expires_at"] <= now_iso)
    ]
    latencies = []
    for row in publication_times:
        created, published = _time(row["created_at"]), _time(row["published_at"])
        if created and published:
            latencies.append(max(0, int((published - created).total_seconds())))

    metrics = {
        "webhook_pending": len(pending_webhooks),
        "webhook_quarantined": sum(row["state"] == "quarantined" for row in webhooks),
        "webhook_redeliveries": sum(int(row["redelivery_count"]) for row in webhooks),
        "webhook_oldest_pending_seconds": _oldest_age(
            pending_webhooks, "received_at", current
        ),
        "publication_unpublished": len(unpublished),
        "publication_oldest_unpublished_seconds": _oldest_age(
            unpublished, "created_at", current
        ),
        "publication_latency_seconds_max": max(latencies) if latencies else None,
        "approval_waiting": len(approval_wait),
        "approval_oldest_wait_seconds": _oldest_age(approval_wait, "updated_at", current),
        "merge_apply_pending": len(pending_apply),
        "merge_apply_oldest_seconds": _oldest_age(pending_apply, "updated_at", current),
        "apply_failures": len(apply_failed),
        "slack_stale_cards": len(stale_cards),
        "slack_mirror_pending": sum(row["state"] == "pending" for row in mirrors),
        "slack_mirror_failed": sum(row["state"] == "failed" for row in mirrors),
        "transcript_safety_failures": sum(row["status"] == "unsafe" for row in transcripts),
        "retention_overdue": len(overdue_traces),
        "github_tokens_expired_unrefreshable": len(expired_tokens),
    }
    alerts: list[dict[str, str]] = []
    for condition, code, action in (
        (
            metrics["webhook_pending"] > 0,
            "webhook_backlog",
            "Inspect gateway health and replay persisted pending deliveries.",
        ),
        (
            metrics["merge_apply_pending"] > 0,
            "merged_unapplied",
            "Run startup reconciliation or changeset retry; never assume merge applied.",
        ),
        (
            metrics["apply_failures"] > 0,
            "apply_failure",
            "Retry only transient failures; supersede semantic conflicts.",
        ),
        (
            metrics["slack_stale_cards"] > 0,
            "stale_slack_card",
            "Verify the run/gateway and refresh the existing card, not a new changeset.",
        ),
        (
            metrics["retention_overdue"] > 0,
            "retention_overdue",
            "Dry-run the retention sweep, then confirm deletion with --yes.",
        ),
        (
            metrics["github_tokens_expired_unrefreshable"] > 0,
            "github_reauthorization_required",
            "Ask the affected owner to reauthorize their immutable GitHub binding.",
        ),
    ):
        if condition:
            alerts.append({"code": code, "safe_operator_action": action})
    return {"generated_at": now_iso, "metrics": metrics, "alerts": alerts}


__all__ = ["collaboration_health"]
