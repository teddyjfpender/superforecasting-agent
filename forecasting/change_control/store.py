"""SQLite persistence for ledger changesets and reviews."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any, Iterable, Mapping

from forecasting.change_control.models import (
    ACTOR_KINDS,
    CHANGESET_STATUSES,
    REVIEW_DECISIONS,
    LedgerOperation,
    changeset_digest,
    content_digest,
)
from forecasting.change_control.policy import classify_operations
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


_EMPTY_REVISION_DIGEST = content_digest({"revision": 0, "source": "legacy-baseline"})
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"preview_failed", "ready", "cancelled", "abandoned"}),
    "preview_failed": frozenset({"draft", "ready", "cancelled", "abandoned"}),
    "ready": frozenset({"publishing", "checks_running", "cancelled", "abandoned"}),
    "publishing": frozenset({"review_open", "blocked", "cancelled"}),
    "review_open": frozenset(
        {"checks_running", "review_required", "changes_requested", "held", "abandoned"}
    ),
    "checks_running": frozenset({"blocked", "review_required", "merge_ready"}),
    "review_required": frozenset({"changes_requested", "held", "merge_ready", "rejected"}),
    "changes_requested": frozenset({"draft", "checks_running", "held", "rejected"}),
    "held": frozenset({"draft", "review_open", "review_required", "cancelled"}),
    "blocked": frozenset({"draft", "checks_running", "cancelled", "superseded"}),
    "merge_ready": frozenset({"merge_queued", "merged_apply_pending", "held"}),
    "merge_queued": frozenset({"merged_apply_pending", "held", "blocked"}),
    "merged_apply_pending": frozenset({"applying", "apply_failed"}),
    "applying": frozenset({"applied", "apply_failed"}),
    "apply_failed": frozenset({"applying", "superseded"}),
}


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_revisions (
            revision INTEGER PRIMARY KEY,
            parent_revision INTEGER,
            changeset_id TEXT,
            digest TEXT NOT NULL,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ledger_changesets (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            base_revision INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft',
            digest TEXT NOT NULL,
            risk_tier TEXT NOT NULL DEFAULT 'low',
            risk_reasons TEXT NOT NULL DEFAULT '[]',
            slack_thread_key TEXT,
            branch TEXT,
            pr_number INTEGER,
            head_sha TEXT,
            merge_sha TEXT,
            author_owner_ids TEXT NOT NULL DEFAULT '[]',
            author_identities TEXT NOT NULL DEFAULT '[]',
            affected_question_ids TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            applied_revision INTEGER,
            applied_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_changesets_workspace_status
            ON ledger_changesets(workspace_id, status, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_changesets_applied_digest
            ON ledger_changesets(workspace_id, digest) WHERE status = 'applied';

        CREATE TABLE IF NOT EXISTS ledger_change_operations (
            id TEXT NOT NULL,
            changeset_id TEXT NOT NULL REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            target_ref TEXT NOT NULL,
            version INTEGER NOT NULL,
            preconditions TEXT NOT NULL DEFAULT '{}',
            payload TEXT NOT NULL,
            provenance_refs TEXT NOT NULL DEFAULT '[]',
            author_attestation TEXT NOT NULL DEFAULT '{}',
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (changeset_id, id),
            UNIQUE (changeset_id, sequence)
        );

        CREATE TABLE IF NOT EXISTS ledger_reviews (
            id TEXT PRIMARY KEY,
            changeset_id TEXT NOT NULL REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            changeset_digest TEXT NOT NULL,
            head_sha TEXT,
            decision TEXT NOT NULL,
            actor_kind TEXT NOT NULL,
            owner_id TEXT,
            github_user_id TEXT,
            slack_user_id TEXT,
            agent_instance_id TEXT,
            agent_persona TEXT,
            role TEXT,
            source TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            stale_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_ledger_reviews_changeset
            ON ledger_reviews(changeset_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS ledger_apply_attempts (
            id TEXT PRIMARY KEY,
            changeset_id TEXT NOT NULL REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            merge_sha TEXT,
            state TEXT NOT NULL,
            diagnostic TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS ledger_artifact_links (
            changeset_id TEXT NOT NULL REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            artifact_type TEXT NOT NULL,
            artifact_ref TEXT NOT NULL,
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (changeset_id, artifact_type, artifact_ref)
        );

        CREATE TABLE IF NOT EXISTS provenance_bundles (
            id TEXT PRIMARY KEY,
            changeset_id TEXT NOT NULL UNIQUE REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            changeset_digest TEXT NOT NULL,
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS provenance_session_links (
            id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL REFERENCES provenance_bundles(id) ON DELETE CASCADE,
            source_type TEXT NOT NULL,
            session_id TEXT,
            run_id TEXT,
            scope TEXT NOT NULL DEFAULT '{}',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (bundle_id, source_type, session_id, run_id)
        );

        CREATE TABLE IF NOT EXISTS provenance_decision_records (
            id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL REFERENCES provenance_bundles(id) ON DELETE CASCADE,
            conclusion TEXT NOT NULL,
            alternatives TEXT NOT NULL DEFAULT '[]',
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            assumptions TEXT NOT NULL DEFAULT '[]',
            probability_changes TEXT NOT NULL DEFAULT '[]',
            unresolved_uncertainty TEXT NOT NULL DEFAULT '[]',
            model TEXT,
            prompt_version TEXT,
            tools TEXT NOT NULL DEFAULT '[]',
            tests TEXT NOT NULL DEFAULT '[]',
            digest TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS provenance_transcripts (
            id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL REFERENCES provenance_bundles(id) ON DELETE CASCADE,
            format TEXT NOT NULL,
            status TEXT NOT NULL,
            digest TEXT NOT NULL,
            locator TEXT,
            byte_size INTEGER NOT NULL,
            safety_findings TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS provenance_consents (
            id TEXT PRIMARY KEY,
            changeset_id TEXT NOT NULL REFERENCES ledger_changesets(id) ON DELETE CASCADE,
            transcript_digest TEXT NOT NULL,
            repository_slug TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            decision TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (changeset_id, transcript_digest, repository_slug, owner_id)
        );

        CREATE TABLE IF NOT EXISTS provenance_trace_archives (
            id TEXT PRIMARY KEY,
            bundle_id TEXT NOT NULL REFERENCES provenance_bundles(id) ON DELETE CASCADE,
            object_locator TEXT NOT NULL,
            ciphertext_digest TEXT NOT NULL,
            byte_size INTEGER NOT NULL,
            retention_deadline TEXT NOT NULL,
            key_version TEXT NOT NULL,
            authorization TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'active',
            pin_reason TEXT,
            pin_expires_at TEXT,
            legal_hold INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );

        CREATE TABLE IF NOT EXISTS provenance_access_events (
            id TEXT PRIMARY KEY,
            archive_id TEXT NOT NULL REFERENCES provenance_trace_archives(id) ON DELETE CASCADE,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS provenance_retention_tombstones (
            archive_id TEXT PRIMARY KEY,
            ciphertext_digest TEXT NOT NULL,
            reason TEXT NOT NULL,
            deleted_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        """INSERT OR IGNORE INTO ledger_revisions
           (revision, parent_revision, changeset_id, digest, applied_at)
           VALUES (0, NULL, NULL, ?, ?)""",
        (_EMPTY_REVISION_DIGEST, utc_now_iso()),
    )


def current_revision(ledger: Any) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM ledger_revisions ORDER BY revision DESC LIMIT 1"
        ).fetchone()
    return dict(row)


def create_changeset(
    ledger: Any,
    *,
    workspace_id: str,
    author_owner_ids: Iterable[str] = (),
    author_identities: Iterable[Mapping[str, Any]] = (),
    affected_question_ids: Iterable[str] = (),
    slack_thread_key: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    base_revision: int | None = None,
    changeset_id: str | None = None,
) -> dict[str, Any]:
    workspace_id = str(workspace_id or "").strip()
    if not workspace_id:
        raise ValidationError("workspace_id is required")
    current = current_revision(ledger)
    revision = current["revision"] if base_revision is None else int(base_revision)
    if revision < 0 or revision > current["revision"]:
        raise ValidationError(
            f"base_revision {revision} is outside ledger history 0..{current['revision']}"
        )
    changeset_id = str(changeset_id or f"chg_{uuid.uuid4().hex[:16]}")
    empty_digest = changeset_digest(
        workspace_id=workspace_id, base_revision=revision, operations=[]
    )
    now = utc_now_iso()
    owners = list(dict.fromkeys(str(value) for value in author_owner_ids if str(value)))
    identities = [dict(value) for value in author_identities]
    questions = list(
        dict.fromkeys(str(value) for value in affected_question_ids if str(value))
    )
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO ledger_changesets (
                   id, workspace_id, base_revision, status, digest, risk_tier,
                   risk_reasons, slack_thread_key, author_owner_ids,
                   author_identities, affected_question_ids, metadata,
                   created_at, updated_at
               ) VALUES (?, ?, ?, 'draft', ?, 'low', '[]', ?, ?, ?, ?, ?, ?, ?)""",
            (
                changeset_id,
                workspace_id,
                revision,
                empty_digest,
                slack_thread_key,
                json.dumps(owners, sort_keys=True),
                json.dumps(identities, sort_keys=True),
                json.dumps(questions, sort_keys=True),
                json.dumps(dict(metadata or {}), sort_keys=True),
                now,
                now,
            ),
        )
    return get_changeset(ledger, changeset_id)


def get_changeset(ledger: Any, changeset_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM ledger_changesets WHERE id = ?", (changeset_id,)
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"ledger changeset not found: {changeset_id}")
    return _changeset_row(row)


def list_changesets(
    ledger: Any,
    *,
    workspace_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id:
        clauses.append("workspace_id = ?")
        params.append(workspace_id)
    if status:
        if status not in CHANGESET_STATUSES:
            raise ValidationError(f"unknown changeset status: {status}")
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, int(limit)))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""SELECT * FROM ledger_changesets {where}
                ORDER BY created_at DESC, id DESC LIMIT ?""",
            params,
        ).fetchall()
    return [_changeset_row(row) for row in rows]


def list_operations(ledger: Any, changeset_id: str) -> list[LedgerOperation]:
    get_changeset(ledger, changeset_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            """SELECT * FROM ledger_change_operations
               WHERE changeset_id = ? ORDER BY sequence, id""",
            (changeset_id,),
        ).fetchall()
    return [_operation_row(row) for row in rows]


def add_operation(
    ledger: Any,
    changeset_id: str,
    operation: LedgerOperation | Mapping[str, Any],
) -> dict[str, Any]:
    operation = (
        operation if isinstance(operation, LedgerOperation) else LedgerOperation.from_dict(operation)
    )
    changeset = get_changeset(ledger, changeset_id)
    if changeset["status"] not in {"draft", "preview_failed", "changes_requested", "held"}:
        raise ValidationError(
            f"cannot edit changeset {changeset_id} in status {changeset['status']}"
        )
    now = utc_now_iso()
    with ledger._connect() as conn:
        sequence = conn.execute(
            """SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
               FROM ledger_change_operations WHERE changeset_id = ?""",
            (changeset_id,),
        ).fetchone()["next_sequence"]
        conn.execute(
            """INSERT INTO ledger_change_operations (
                   id, changeset_id, sequence, kind, target_ref, version,
                   preconditions, payload, provenance_refs, author_attestation,
                   digest, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                operation.id,
                changeset_id,
                sequence,
                operation.kind,
                operation.target_ref,
                operation.version,
                json.dumps(dict(operation.preconditions), sort_keys=True),
                json.dumps(dict(operation.payload), sort_keys=True),
                json.dumps(list(operation.provenance_refs), sort_keys=True),
                json.dumps(dict(operation.author_attestation), sort_keys=True),
                operation.digest,
                now,
            ),
        )
    _refresh_changeset(ledger, changeset_id, stale_reviews=True)
    return get_changeset(ledger, changeset_id)


def transition_changeset(
    ledger: Any,
    changeset_id: str,
    status: str,
    *,
    expected_status: str | None = None,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in CHANGESET_STATUSES:
        raise ValidationError(f"unknown changeset status: {status}")
    changeset = get_changeset(ledger, changeset_id)
    current = changeset["status"]
    if expected_status is not None and current != expected_status:
        raise ValidationError(
            f"changeset {changeset_id} status is {current}, expected {expected_status}"
        )
    if status != current and status not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise ValidationError(f"invalid changeset transition: {current} -> {status}")
    allowed_fields = {"branch", "pr_number", "head_sha", "merge_sha", "metadata"}
    updates = {key: value for key, value in dict(fields or {}).items() if key in allowed_fields}
    assignments = ["status = ?", "updated_at = ?"]
    params: list[Any] = [status, utc_now_iso()]
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        params.append(json.dumps(value, sort_keys=True) if key == "metadata" else value)
    params.extend([changeset_id, current])
    with ledger._connect() as conn:
        cursor = conn.execute(
            f"""UPDATE ledger_changesets SET {', '.join(assignments)}
                WHERE id = ? AND status = ?""",
            params,
        )
    if cursor.rowcount != 1:
        raise ValidationError(f"changeset {changeset_id} changed concurrently")
    return get_changeset(ledger, changeset_id)


def add_review(
    ledger: Any,
    changeset_id: str,
    *,
    decision: str,
    actor_kind: str,
    source: str,
    owner_id: str | None = None,
    github_user_id: str | None = None,
    slack_user_id: str | None = None,
    agent_instance_id: str | None = None,
    agent_persona: str | None = None,
    role: str | None = None,
    head_sha: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    review_id: str | None = None,
) -> dict[str, Any]:
    if decision not in REVIEW_DECISIONS:
        raise ValidationError(f"unknown review decision: {decision}")
    if actor_kind not in ACTOR_KINDS:
        raise ValidationError(f"unknown review actor_kind: {actor_kind}")
    if actor_kind == "human" and not owner_id:
        raise ValidationError("human reviews require owner_id")
    changeset = get_changeset(ledger, changeset_id)
    if head_sha is not None and changeset.get("head_sha") not in {None, head_sha}:
        raise ValidationError("review head_sha does not match changeset head_sha")
    review_id = review_id or f"rev_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO ledger_reviews (
                   id, changeset_id, changeset_digest, head_sha, decision,
                   actor_kind, owner_id, github_user_id, slack_user_id,
                   agent_instance_id, agent_persona, role, source, metadata,
                   created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                review_id,
                changeset_id,
                changeset["digest"],
                head_sha if head_sha is not None else changeset.get("head_sha"),
                decision,
                actor_kind,
                owner_id,
                github_user_id,
                slack_user_id,
                agent_instance_id,
                agent_persona,
                role,
                str(source or "").strip() or "unknown",
                json.dumps(dict(metadata or {}), sort_keys=True),
                utc_now_iso(),
            ),
        )
    return get_review(ledger, review_id)


def get_review(ledger: Any, review_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM ledger_reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"ledger review not found: {review_id}")
    return _review_row(row)


def list_reviews(ledger: Any, changeset_id: str) -> list[dict[str, Any]]:
    get_changeset(ledger, changeset_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            """SELECT * FROM ledger_reviews WHERE changeset_id = ?
               ORDER BY created_at, id""",
            (changeset_id,),
        ).fetchall()
    return [_review_row(row) for row in rows]


def _refresh_changeset(ledger: Any, changeset_id: str, *, stale_reviews: bool) -> None:
    changeset = get_changeset(ledger, changeset_id)
    operations = list_operations(ledger, changeset_id)
    digest = changeset_digest(
        workspace_id=changeset["workspace_id"],
        base_revision=changeset["base_revision"],
        operations=operations,
    )
    assessment = classify_operations(operations)
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """UPDATE ledger_changesets
               SET digest = ?, risk_tier = ?, risk_reasons = ?, updated_at = ?
               WHERE id = ?""",
            (
                digest,
                assessment.tier,
                json.dumps(list(assessment.reasons), sort_keys=True),
                now,
                changeset_id,
            ),
        )
        if stale_reviews:
            conn.execute(
                """UPDATE ledger_reviews SET stale_at = ?
                   WHERE changeset_id = ? AND stale_at IS NULL""",
                (now, changeset_id),
            )


def _changeset_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    for key in (
        "risk_reasons",
        "author_owner_ids",
        "author_identities",
        "affected_question_ids",
        "metadata",
    ):
        result[key] = json.loads(result[key])
    return result


def _operation_row(row: sqlite3.Row) -> LedgerOperation:
    return LedgerOperation(
        id=row["id"],
        kind=row["kind"],
        target_ref=row["target_ref"],
        version=row["version"],
        preconditions=json.loads(row["preconditions"]),
        payload=json.loads(row["payload"]),
        provenance_refs=tuple(json.loads(row["provenance_refs"])),
        author_attestation=json.loads(row["author_attestation"]),
    )


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = json.loads(result["metadata"])
    return result


__all__ = [
    "add_operation",
    "add_review",
    "create_changeset",
    "current_revision",
    "get_changeset",
    "get_review",
    "initialize_schema",
    "list_changesets",
    "list_operations",
    "list_reviews",
    "transition_changeset",
]
