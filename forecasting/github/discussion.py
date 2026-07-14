"""Bounded, owner-attributed GitHub discussion for forecast changesets."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from forecasting.change_control.collaboration import get_identity_binding
from forecasting.change_control.models import content_digest
from forecasting.change_control.store import get_changeset, transition_changeset
from forecasting.change_control.transcripts import (
    MARKER_END,
    MARKER_START,
    review_transcript_findings,
)
from forecasting.github.events import record_github_origin
from forecasting.models import ValidationError, utc_now_iso


ALLOWED_TRIGGERS = frozenset({
    "assigned",
    "mentioned",
    "policy_requested",
    "failed_check",
})
_DISCUSSABLE_STATUSES = frozenset({
    "review_open",
    "checks_running",
    "review_required",
    "changes_requested",
    "merge_ready",
    "merge_queued",
})
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


@dataclass(frozen=True)
class DiscussionLimits:
    max_comments: int = 12
    max_rounds: int = 6
    max_tokens: int = 16_000
    max_elapsed_seconds: int = 1_800
    max_concurrent_tasks: int = 2
    agent_loop_threshold: int = 4
    max_comment_bytes: int = 32_768

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in self.__dict__.values()
        ):
            raise ValidationError("GitHub discussion limits must be positive integers")


class AgentDiscussionCoordinator:
    """Post one bounded agent comment through an owner-scoped capability client.

    This service deliberately cannot submit reviews or alter review policy. Branch
    fixes continue through the existing owner-scoped branch capability.
    """

    def __init__(
        self,
        ledger: Any,
        github_client: Any,
        *,
        repository_slug: str,
        limits: DiscussionLimits | None = None,
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        if getattr(github_client, "actor_kind", "agent") != "agent":
            raise PermissionError("autonomous discussion requires an agent capability")
        self.ledger = ledger
        self.github_client = github_client
        self.repository_slug = repository_slug
        self.limits = limits or DiscussionLimits()

    def respond(
        self,
        changeset_id: str,
        *,
        identity_binding_id: str,
        trigger: str,
        body: str,
        model: str,
        run_id: str,
        round_number: int,
        token_count: int,
    ) -> dict[str, Any]:
        """Post an attributed comment, enforcing every limit before network I/O."""

        if trigger not in ALLOWED_TRIGGERS:
            raise PermissionError("agent discussion trigger is not authorized")
        if not _SAFE_ID.fullmatch(str(run_id or "")):
            raise ValidationError("agent discussion run_id is invalid")
        if (
            isinstance(round_number, bool)
            or not isinstance(round_number, int)
            or round_number < 1
        ):
            raise ValidationError("agent discussion round_number must be positive")
        if (
            isinstance(token_count, bool)
            or not isinstance(token_count, int)
            or token_count < 0
        ):
            raise ValidationError("agent discussion token_count must be non-negative")
        if not _line(model, 120):
            raise ValidationError("agent discussion model is required")
        body = str(body or "").strip()
        if not body:
            raise ValidationError("agent discussion body is required")
        binding = get_identity_binding(self.ledger, identity_binding_id)
        if binding["status"] != "active":
            raise PermissionError("agent discussion identity is revoked")
        client_binding = getattr(
            self.github_client, "identity_binding_id", identity_binding_id
        )
        if client_binding != identity_binding_id:
            raise PermissionError(
                "agent discussion capability belongs to another owner"
            )
        changeset = get_changeset(self.ledger, changeset_id)
        if (
            not changeset.get("pr_number")
            or changeset["status"] not in _DISCUSSABLE_STATUSES
        ):
            raise PermissionError(
                "changeset is not open for autonomous GitHub discussion"
            )

        rendered_tokens = max(int(token_count), (len(body) + 3) // 4)
        comment = self._comment(changeset, binding, body, model, run_id, pause=False)
        self._validate_comment(comment)

        lease, will_pause = self._reserve(
            changeset,
            identity_binding_id=identity_binding_id,
            trigger=trigger,
            run_id=run_id,
            round_number=int(round_number),
            token_count=rendered_tokens,
        )
        if lease.get("event_id"):
            return lease
        try:
            if will_pause:
                comment = self._comment(
                    changeset, binding, body, model, run_id, pause=True
                )
                self._validate_comment(comment)
            path = (
                f"/repos/{self.repository_slug}/issues/"
                f"{int(changeset['pr_number'])}/comments"
            )
            response = self.github_client.call(
                "comment.write",
                "POST",
                path,
                {"body": comment},
                expected_statuses=(201,),
            )
            remote = response.get("body") or {}
            remote_id = str(remote.get("id") or "")
            if not remote_id:
                raise RuntimeError("GitHub comment response lacked an ID")
            return self._complete(
                lease["id"],
                changeset_id=changeset_id,
                identity_binding_id=identity_binding_id,
                trigger=trigger,
                remote_id=remote_id,
                model=model,
                run_id=run_id,
                round_number=int(round_number),
                token_count=rendered_tokens,
                body_digest=content_digest(body),
                will_pause=will_pause,
                comment_url=str(remote.get("html_url") or "") or None,
            )
        except Exception:
            with self.ledger._connect() as conn:
                conn.execute(
                    """UPDATE github_agent_discussion_leases
                       SET state = 'failed', finished_at = ? WHERE id = ? AND state = 'active'""",
                    (utc_now_iso(), lease["id"]),
                )
            raise

    def _reserve(
        self,
        changeset: dict[str, Any],
        *,
        identity_binding_id: str,
        trigger: str,
        run_id: str,
        round_number: int,
        token_count: int,
    ) -> tuple[dict[str, Any], bool]:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        now_iso = now.isoformat().replace("+00:00", "Z")
        with self.ledger.transaction(immediate=True):
            with self.ledger._connect() as conn:
                existing = conn.execute(
                    """SELECT id, remote_id FROM github_agent_discussion_events
                       WHERE changeset_id = ? AND identity_binding_id = ? AND run_id = ?
                         AND actor_kind = 'agent'""",
                    (changeset["id"], identity_binding_id, run_id),
                ).fetchone()
                if existing is not None:
                    return {
                        "changeset_id": changeset["id"],
                        "event_id": existing["id"],
                        "remote_id": existing["remote_id"],
                        "state": "already_posted",
                    }, False
                conn.execute(
                    """UPDATE github_agent_discussion_leases
                       SET state = 'expired', finished_at = ?
                       WHERE changeset_id = ? AND state = 'active' AND expires_at <= ?""",
                    (now_iso, changeset["id"], now_iso),
                )
                prior_lease = conn.execute(
                    """SELECT state FROM github_agent_discussion_leases
                       WHERE changeset_id = ? AND identity_binding_id = ? AND run_id = ?""",
                    (changeset["id"], identity_binding_id, run_id),
                ).fetchone()
                if prior_lease is not None:
                    raise PermissionError(
                        f"agent discussion run is already {prior_lease['state']}; start a new run"
                    )
                totals = conn.execute(
                    """SELECT COUNT(*) AS comments, COALESCE(SUM(token_count), 0) AS tokens,
                              MIN(created_at) AS first_at
                       FROM github_agent_discussion_events
                       WHERE changeset_id = ? AND actor_kind = 'agent'""",
                    (changeset["id"],),
                ).fetchone()
                if int(totals["comments"]) >= self.limits.max_comments:
                    raise PermissionError(
                        "agent discussion comment budget is exhausted"
                    )
                if int(totals["tokens"]) + token_count > self.limits.max_tokens:
                    raise PermissionError("agent discussion token budget is exhausted")
                if round_number > self.limits.max_rounds:
                    raise PermissionError("agent discussion round budget is exhausted")
                first_at = totals["first_at"]
                if first_at and now > _timestamp(first_at) + timedelta(
                    seconds=self.limits.max_elapsed_seconds
                ):
                    raise PermissionError(
                        "agent discussion elapsed-time budget is exhausted"
                    )
                active = conn.execute(
                    """SELECT COUNT(*) FROM github_agent_discussion_leases
                       WHERE changeset_id = ? AND state = 'active'""",
                    (changeset["id"],),
                ).fetchone()[0]
                if int(active) >= self.limits.max_concurrent_tasks:
                    raise PermissionError(
                        "agent discussion concurrency budget is exhausted"
                    )
                consecutive = 0
                for row in conn.execute(
                    """SELECT actor_kind FROM github_agent_discussion_events
                       WHERE changeset_id = ? ORDER BY rowid DESC""",
                    (changeset["id"],),
                ):
                    if row["actor_kind"] == "human":
                        break
                    if row["actor_kind"] == "agent":
                        consecutive += 1
                lease_id = f"ghdiscussion_{uuid.uuid4().hex[:16]}"
                deadline = now + timedelta(seconds=self.limits.max_elapsed_seconds)
                if first_at:
                    deadline = min(
                        deadline,
                        _timestamp(first_at)
                        + timedelta(seconds=self.limits.max_elapsed_seconds),
                    )
                conn.execute(
                    """INSERT INTO github_agent_discussion_leases
                       (id, changeset_id, identity_binding_id, trigger_kind, run_id,
                        state, started_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
                    (
                        lease_id,
                        changeset["id"],
                        identity_binding_id,
                        trigger,
                        run_id,
                        now_iso,
                        deadline.isoformat().replace("+00:00", "Z"),
                    ),
                )
        return {"id": lease_id}, consecutive + 1 >= self.limits.agent_loop_threshold

    def _complete(
        self,
        lease_id: str,
        *,
        changeset_id: str,
        identity_binding_id: str,
        trigger: str,
        remote_id: str,
        model: str,
        run_id: str,
        round_number: int,
        token_count: int,
        body_digest: str,
        will_pause: bool,
        comment_url: str | None,
    ) -> dict[str, Any]:
        event_id = f"ghdiscussion_event_{uuid.uuid4().hex[:16]}"
        correlation_id = f"agent-discussion:{changeset_id}:{run_id}"
        paused = False
        with self.ledger.transaction(immediate=True):
            record_github_origin(
                self.ledger,
                remote_kind="comment",
                remote_id=remote_id,
                changeset_id=changeset_id,
                actor_kind="agent",
                identity_binding_id=identity_binding_id,
                correlation_id=correlation_id,
            )
            with self.ledger._connect() as conn:
                conn.execute(
                    """INSERT INTO github_agent_discussion_events
                       (id, changeset_id, actor_kind, identity_binding_id, trigger_kind,
                        remote_kind, remote_id, model, run_id, token_count,
                        round_number, body_digest, created_at)
                       VALUES (?, ?, 'agent', ?, ?, 'comment', ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(remote_kind, remote_id) DO UPDATE SET
                         actor_kind = 'agent', identity_binding_id = excluded.identity_binding_id,
                         trigger_kind = excluded.trigger_kind, model = excluded.model,
                         run_id = excluded.run_id, token_count = excluded.token_count,
                         round_number = excluded.round_number, body_digest = excluded.body_digest""",
                    (
                        event_id,
                        changeset_id,
                        identity_binding_id,
                        trigger,
                        remote_id,
                        _line(model, 120),
                        run_id,
                        token_count,
                        round_number,
                        body_digest,
                        utc_now_iso(),
                    ),
                )
                stored = conn.execute(
                    """SELECT id FROM github_agent_discussion_events
                       WHERE remote_kind = 'comment' AND remote_id = ?""",
                    (remote_id,),
                ).fetchone()
                conn.execute(
                    """UPDATE github_agent_discussion_leases
                       SET state = 'completed', finished_at = ? WHERE id = ?""",
                    (utc_now_iso(), lease_id),
                )
                event_id = stored["id"]
            current = get_changeset(self.ledger, changeset_id)
            if will_pause and current["status"] in _DISCUSSABLE_STATUSES:
                metadata = dict(current.get("metadata") or {})
                metadata["discussion_pause"] = {
                    "reason": "agent_loop_detected",
                    "run_id": run_id,
                    "remote_id": remote_id,
                }
                transition_changeset(
                    self.ledger, changeset_id, "held", fields={"metadata": metadata}
                )
                paused = True
        return {
            "changeset_id": changeset_id,
            "event_id": event_id,
            "remote_id": remote_id,
            "comment_url": comment_url,
            "state": "human_direction_required" if paused else "posted",
            "paused": paused,
        }

    @staticmethod
    def _comment(
        changeset: dict[str, Any],
        binding: dict[str, Any],
        body: str,
        model: str,
        run_id: str,
        *,
        pause: bool,
    ) -> str:
        marker = f"<!-- superforecasting-agent:{changeset['id']}:{changeset['digest']}:{run_id} -->"
        header = (
            f"### Agent review — {_line(binding['agent_persona'], 80)}\n\n"
            f"Owner: `{_line(binding['owner_id'], 80)}` · GitHub: "
            f"`@{_line(binding['github_login'], 80)}` · Model/run: "
            f"`{_line(model, 120)}` / `{run_id}` · Changeset: `{changeset['digest']}`"
        )
        footer = (
            "\n\n> Autonomous discussion is paused: consecutive agent turns reached the "
            "workspace limit. Human direction is required in GitHub or Slack."
            if pause
            else ""
        )
        return f"{marker}\n{header}\n\n{body}{footer}"

    def _validate_comment(self, comment: str) -> None:
        if len(comment.encode("utf-8")) > self.limits.max_comment_bytes:
            raise ValidationError(
                "agent discussion comment exceeds the configured byte limit"
            )
        findings = review_transcript_findings(
            f"{MARKER_START}\n{comment}\n{MARKER_END}", location="github_agent_comment"
        )
        if findings:
            raise PermissionError(
                "agent discussion comment failed the secret-safety scan"
            )


def record_human_discussion_activity(
    ledger: Any,
    *,
    changeset_id: str,
    remote_kind: str,
    remote_id: str,
    identity_binding_id: str | None = None,
) -> None:
    """Reset loop detection with metadata only; raw GitHub bodies stay excluded."""

    get_changeset(ledger, changeset_id)
    if remote_kind not in {"comment", "review"} or not str(remote_id or ""):
        raise ValidationError(
            "human discussion activity requires a comment or review ID"
        )
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO github_agent_discussion_events
               (id, changeset_id, actor_kind, identity_binding_id, remote_kind,
                remote_id, token_count, created_at)
               VALUES (?, ?, 'human', ?, ?, ?, 0, ?)
               ON CONFLICT(remote_kind, remote_id) DO NOTHING""",
            (
                f"ghdiscussion_event_{uuid.uuid4().hex[:16]}",
                changeset_id,
                identity_binding_id,
                remote_kind,
                str(remote_id),
                utc_now_iso(),
            ),
        )


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _line(value: Any, limit: int) -> str:
    line = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()[:limit]
    return line.replace("`", "'").replace("<", "[").replace(">", "]")


__all__ = [
    "ALLOWED_TRIGGERS",
    "AgentDiscussionCoordinator",
    "DiscussionLimits",
    "record_human_discussion_activity",
]
