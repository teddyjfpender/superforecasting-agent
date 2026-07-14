"""Provenance bundles, decision records, and publication consent."""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Mapping

from forecasting.change_control.models import content_digest
from forecasting.change_control.store import get_changeset
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


def ensure_bundle(ledger: Any, changeset_id: str) -> dict[str, Any]:
    changeset = get_changeset(ledger, changeset_id)
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM provenance_bundles WHERE changeset_id = ?", (changeset_id,)
        ).fetchone()
        if row is None:
            bundle_id = f"prov_{uuid.uuid4().hex[:16]}"
            now = utc_now_iso()
            digest = content_digest(
                {
                    "version": 1,
                    "changeset_id": changeset_id,
                    "changeset_digest": changeset["digest"],
                    "session_links": [],
                    "decisions": [],
                }
            )
            conn.execute(
                """INSERT INTO provenance_bundles
                   (id, changeset_id, changeset_digest, digest, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (bundle_id, changeset_id, changeset["digest"], digest, now),
            )
            row = conn.execute(
                "SELECT * FROM provenance_bundles WHERE id = ?", (bundle_id,)
            ).fetchone()
    return dict(row)


def get_bundle(ledger: Any, *, changeset_id: str | None = None, bundle_id: str | None = None):
    if not changeset_id and not bundle_id:
        raise ValidationError("changeset_id or bundle_id is required")
    field, value = ("changeset_id", changeset_id) if changeset_id else ("id", bundle_id)
    with ledger._connect() as conn:
        row = conn.execute(
            f"SELECT * FROM provenance_bundles WHERE {field} = ?", (value,)
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"provenance bundle not found: {value}")
    return dict(row)


def link_session(
    ledger: Any,
    changeset_id: str,
    *,
    source_type: str,
    session_id: str | None = None,
    run_id: str | None = None,
    scope: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not session_id and not run_id:
        raise ValidationError("a provenance link requires session_id or run_id")
    if source_type not in {"session_db", "execution_store", "external"}:
        raise ValidationError(f"unsupported provenance source_type: {source_type}")
    bundle = ensure_bundle(ledger, changeset_id)
    link_id = f"plink_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO provenance_session_links
               (id, bundle_id, source_type, session_id, run_id, scope, metadata, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                link_id,
                bundle["id"],
                source_type,
                session_id or "",
                run_id or "",
                json.dumps(dict(scope or {}), sort_keys=True),
                json.dumps(dict(metadata or {}), sort_keys=True),
                utc_now_iso(),
            ),
        )
        row = conn.execute(
            """SELECT * FROM provenance_session_links
               WHERE bundle_id = ? AND source_type = ? AND session_id = ? AND run_id = ?""",
            (bundle["id"], source_type, session_id or "", run_id or ""),
        ).fetchone()
    _refresh_bundle_digest(ledger, bundle["id"])
    return _json_row(row, "scope", "metadata")


def add_decision_record(
    ledger: Any,
    changeset_id: str,
    *,
    conclusion: str,
    alternatives: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
    assumptions: Iterable[str] = (),
    probability_changes: Iterable[Mapping[str, Any]] = (),
    unresolved_uncertainty: Iterable[str] = (),
    model: str | None = None,
    prompt_version: str | None = None,
    tools: Iterable[str] = (),
    tests: Iterable[str] = (),
) -> dict[str, Any]:
    conclusion = str(conclusion or "").strip()
    if not conclusion:
        raise ValidationError("decision conclusion is required")
    bundle = ensure_bundle(ledger, changeset_id)
    record = {
        "conclusion": conclusion,
        "alternatives": list(alternatives),
        "evidence_refs": list(evidence_refs),
        "assumptions": list(assumptions),
        "probability_changes": [dict(value) for value in probability_changes],
        "unresolved_uncertainty": list(unresolved_uncertainty),
        "model": model,
        "prompt_version": prompt_version,
        "tools": list(tools),
        "tests": list(tests),
    }
    record_id = f"decision_{uuid.uuid4().hex[:16]}"
    digest = content_digest(record)
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO provenance_decision_records
               (id, bundle_id, conclusion, alternatives, evidence_refs, assumptions,
                probability_changes, unresolved_uncertainty, model, prompt_version,
                tools, tests, digest, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                bundle["id"],
                conclusion,
                json.dumps(record["alternatives"], sort_keys=True),
                json.dumps(record["evidence_refs"], sort_keys=True),
                json.dumps(record["assumptions"], sort_keys=True),
                json.dumps(record["probability_changes"], sort_keys=True),
                json.dumps(record["unresolved_uncertainty"], sort_keys=True),
                model,
                prompt_version,
                json.dumps(record["tools"], sort_keys=True),
                json.dumps(record["tests"], sort_keys=True),
                digest,
                utc_now_iso(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM provenance_decision_records WHERE id = ?", (record_id,)
        ).fetchone()
    _refresh_bundle_digest(ledger, bundle["id"])
    return _json_row(
        row,
        "alternatives",
        "evidence_refs",
        "assumptions",
        "probability_changes",
        "unresolved_uncertainty",
        "tools",
        "tests",
    )


def record_transcript(
    ledger: Any,
    changeset_id: str,
    *,
    format: str,
    status: str,
    digest: str,
    byte_size: int,
    locator: str | None = None,
    safety_findings: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if status not in {"safe", "withheld", "unsafe"}:
        raise ValidationError(f"unsupported transcript status: {status}")
    bundle = ensure_bundle(ledger, changeset_id)
    transcript_id = f"transcript_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO provenance_transcripts
               (id, bundle_id, format, status, digest, locator, byte_size,
                safety_findings, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                transcript_id,
                bundle["id"],
                format,
                status,
                digest,
                locator,
                max(0, int(byte_size)),
                json.dumps([dict(value) for value in safety_findings], sort_keys=True),
                utc_now_iso(),
            ),
        )
        row = conn.execute(
            "SELECT * FROM provenance_transcripts WHERE id = ?", (transcript_id,)
        ).fetchone()
    return _json_row(row, "safety_findings")


def record_consent(
    ledger: Any,
    changeset_id: str,
    *,
    transcript_digest: str,
    repository_slug: str,
    owner_id: str,
    decision: str,
) -> dict[str, Any]:
    if decision not in {"include", "omit"}:
        raise ValidationError("transcript consent decision must be include or omit")
    ensure_bundle(ledger, changeset_id)
    consent_id = f"consent_{uuid.uuid4().hex[:16]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO provenance_consents
               (id, changeset_id, transcript_digest, repository_slug, owner_id,
                decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(changeset_id, transcript_digest, repository_slug, owner_id)
               DO UPDATE SET decision = excluded.decision, created_at = excluded.created_at""",
            (
                consent_id,
                changeset_id,
                transcript_digest,
                repository_slug,
                owner_id,
                decision,
                utc_now_iso(),
            ),
        )
        row = conn.execute(
            """SELECT * FROM provenance_consents
               WHERE changeset_id = ? AND transcript_digest = ?
                 AND repository_slug = ? AND owner_id = ?""",
            (changeset_id, transcript_digest, repository_slug, owner_id),
        ).fetchone()
    return dict(row)


def publication_decision(
    ledger: Any,
    changeset_id: str,
    *,
    transcript_digest: str,
    repository_slug: str,
    owner_id: str,
) -> str | None:
    with ledger._connect() as conn:
        row = conn.execute(
            """SELECT decision FROM provenance_consents
               WHERE changeset_id = ? AND transcript_digest = ?
                 AND repository_slug = ? AND owner_id = ?""",
            (changeset_id, transcript_digest, repository_slug, owner_id),
        ).fetchone()
    return None if row is None else str(row["decision"])


def _refresh_bundle_digest(ledger: Any, bundle_id: str) -> None:
    with ledger._connect() as conn:
        bundle = dict(
            conn.execute("SELECT * FROM provenance_bundles WHERE id = ?", (bundle_id,)).fetchone()
        )
        links = [
            dict(row)
            for row in conn.execute(
                """SELECT source_type, session_id, run_id, scope, metadata
                   FROM provenance_session_links WHERE bundle_id = ?
                   ORDER BY source_type, session_id, run_id""",
                (bundle_id,),
            ).fetchall()
        ]
        decisions = [
            row["digest"]
            for row in conn.execute(
                """SELECT digest FROM provenance_decision_records
                   WHERE bundle_id = ? ORDER BY digest""",
                (bundle_id,),
            ).fetchall()
        ]
        digest = content_digest(
            {
                "version": 1,
                "changeset_id": bundle["changeset_id"],
                "changeset_digest": bundle["changeset_digest"],
                "session_links": links,
                "decisions": decisions,
            }
        )
        conn.execute("UPDATE provenance_bundles SET digest = ? WHERE id = ?", (digest, bundle_id))


def _json_row(row: Any, *fields: str) -> dict[str, Any]:
    result = dict(row)
    for field in fields:
        result[field] = json.loads(result[field])
    return result


__all__ = [
    "add_decision_record",
    "ensure_bundle",
    "get_bundle",
    "link_session",
    "publication_decision",
    "record_consent",
    "record_transcript",
]
