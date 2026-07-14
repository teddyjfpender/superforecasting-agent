"""Deterministic portable projection of the authoritative forecast ledger."""

from __future__ import annotations

import json
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Mapping

from forecasting.change_control.store import current_revision, list_changesets, list_operations, list_reviews
from forecasting.change_control.models import content_digest
from forecasting.change_control.transcripts import review_transcript_findings
from forecasting.workspace.manifest import WorkspaceManifest
from hermes_constants import get_hermes_home


_DROP_KEYS = frozenset(
    {
        "generated_at",
        "reasoning",
        "reasoning_content",
        "reasoning_details",
        "system_prompt",
        "snapshot_path",
        "source_file_path",
        "artifact_paths",
        "api_key",
        "token",
        "secret",
        "cookie",
    }
)
_PACKET_KEYS = (
    "question",
    "forecast_history",
    "evidence",
    "assumptions",
    "reference_classes",
    "resolution",
    "scores",
    "postmortems",
    "calibration_lessons",
    "forecast_links",
    "thesis_members",
    "thesis_entities",
    "analyst_notes",
)


def _portable(value: Any, *, key: str = "") -> Any:
    if key.lower() in _DROP_KEYS:
        return None
    if isinstance(value, Mapping):
        return {
            str(item_key): portable
            for item_key, item_value in sorted(value.items(), key=lambda item: str(item[0]))
            if str(item_key).lower() not in _DROP_KEYS
            if (portable := _portable(item_value, key=str(item_key))) is not None
        }
    if isinstance(value, list):
        return [_portable(item) for item in value]
    return value


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _backup(ledger: Any, path: Path) -> None:
    source = sqlite3.connect(ledger.db_path)
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _question_packet(ledger: Any, question_id: str) -> dict[str, Any]:
    packet = json.loads(ledger.export_question(question_id, fmt="json"))
    return _portable({key: packet.get(key) for key in _PACKET_KEYS})


def _changeset_packet(ledger: Any, changeset: Mapping[str, Any]) -> dict[str, Any]:
    public = {
        key: changeset.get(key)
        for key in (
            "id",
            "workspace_id",
            "base_revision",
            "digest",
            "risk_tier",
            "risk_reasons",
            "author_owner_ids",
            "author_identities",
            "affected_question_ids",
            "created_at",
            "applied_revision",
            "applied_at",
        )
    }
    public["operations"] = [
        operation.as_dict() for operation in list_operations(ledger, str(changeset["id"]))
    ]
    public["reviews"] = [
        {
            key: review.get(key)
            for key in (
                "id",
                "changeset_digest",
                "head_sha",
                "decision",
                "actor_kind",
                "owner_id",
                "github_user_id",
                "agent_instance_id",
                "agent_persona",
                "role",
                "source",
                "created_at",
                "stale_at",
            )
        }
        for review in list_reviews(ledger, str(changeset["id"]))
    ]
    return _portable(public)


def _safe_transcript_bytes(row: Mapping[str, Any]) -> bytes | None:
    locator = row.get("locator")
    if not locator:
        return None
    allowed = (get_hermes_home() / "provenance" / "safe-transcripts").resolve()
    try:
        candidate = Path(str(locator)).expanduser()
        if candidate.is_symlink():
            return None
        path = candidate.resolve(strict=True)
        path.relative_to(allowed)
        if not path.is_file() or path.stat().st_size > 2_000_000:
            return None
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if len(data) != int(row["byte_size"]):
        return None
    if content_digest(text) != row["digest"]:
        return None
    if review_transcript_findings(text, location="safe-transcript-artifact"):
        return None
    return data


def _provenance_files(
    ledger: Any,
    changeset: Mapping[str, Any],
    *,
    repository_slug: str | None,
) -> dict[str, bytes]:
    changeset_id = str(changeset["id"])
    files: dict[str, bytes] = {}
    with ledger._connect() as conn:
        bundle = conn.execute(
            "SELECT * FROM provenance_bundles WHERE changeset_id = ?", (changeset_id,)
        ).fetchone()
        contributions = conn.execute(
            """SELECT attestation, attestation_digest, created_at
               FROM collaboration_contributions WHERE changeset_id = ?
               ORDER BY created_at, id""",
            (changeset_id,),
        ).fetchall()
        if contributions:
            files[f"attestations/{changeset_id}/contributors.json"] = _json_bytes(
                {
                    "version": 1,
                    "changeset_id": changeset_id,
                    "contributions": [
                        {
                            "attestation": json.loads(row["attestation"]),
                            "digest": row["attestation_digest"],
                            "created_at": row["created_at"],
                        }
                        for row in contributions
                    ],
                }
            )
        if bundle is None:
            return files
        decisions = conn.execute(
            """SELECT * FROM provenance_decision_records
               WHERE bundle_id = ? ORDER BY created_at, id""",
            (bundle["id"],),
        ).fetchall()
        transcripts = conn.execute(
            """SELECT id, format, status, digest, locator, byte_size, safety_findings, created_at
               FROM provenance_transcripts WHERE bundle_id = ? ORDER BY created_at, id""",
            (bundle["id"],),
        ).fetchall()
        consents = conn.execute(
            """SELECT transcript_digest, repository_slug, owner_id, decision, created_at
               FROM provenance_consents WHERE changeset_id = ?
               ORDER BY transcript_digest, repository_slug, owner_id""",
            (changeset_id,),
        ).fetchall()
    files[f"attestations/{changeset_id}/provenance.json"] = _json_bytes(
        {
            "version": 1,
            "changeset_id": changeset_id,
            "changeset_digest": bundle["changeset_digest"],
            "provenance_digest": bundle["digest"],
        }
    )
    if decisions:
        files[f"attestations/{changeset_id}/decisions.json"] = _json_bytes(
            {
                "version": 1,
                "changeset_id": changeset_id,
                "decisions": [
                    _portable(
                        {
                            **dict(row),
                            **{
                                key: json.loads(row[key])
                                for key in (
                                    "alternatives",
                                    "evidence_refs",
                                    "assumptions",
                                    "probability_changes",
                                    "unresolved_uncertainty",
                                    "tools",
                                    "tests",
                                )
                            },
                        }
                    )
                    for row in decisions
                ],
            }
        )
    if transcripts or consents:
        latest = transcripts[-1] if transcripts else None
        initiating_owners = changeset.get("author_owner_ids") or ()
        initiating_owner = str(initiating_owners[0]) if initiating_owners else None
        publication_status = "transcript_not_available"
        transcript_content: bytes | None = None
        if latest is not None:
            if latest["status"] == "unsafe":
                publication_status = "transcript_unavailable_safety_failure"
            elif latest["status"] == "withheld":
                publication_status = "transcript_withheld_by_owner"
            elif not repository_slug or not initiating_owner:
                publication_status = "transcript_consent_required"
            else:
                decision = next(
                    (
                        row["decision"]
                        for row in consents
                        if row["transcript_digest"] == latest["digest"]
                        and row["repository_slug"] == repository_slug
                        and row["owner_id"] == initiating_owner
                    ),
                    None,
                )
                if decision == "omit":
                    publication_status = "transcript_withheld_by_owner"
                elif decision == "include":
                    transcript_content = _safe_transcript_bytes(dict(latest))
                    publication_status = (
                        "transcript_included"
                        if transcript_content is not None
                        else "transcript_unavailable_safety_failure"
                    )
                else:
                    publication_status = "transcript_consent_required"
        if transcript_content is not None:
            files[f"transcripts/{changeset_id}/transcript.md"] = transcript_content
        files[f"transcripts/{changeset_id}/manifest.json"] = _json_bytes(
            {
                "version": 1,
                "changeset_id": changeset_id,
                "artifacts": [
                    {
                        **{key: value for key, value in dict(row).items() if key != "locator"},
                        "safety_findings": json.loads(row["safety_findings"]),
                    }
                    for row in transcripts
                ],
                "publication_consents": [dict(row) for row in consents],
                "publication_status": publication_status,
                "content_included": transcript_content is not None,
                "published_digest": latest["digest"] if transcript_content is not None else None,
            }
        )
    return files


def export_workspace(
    ledger: Any,
    output_dir: str | Path,
    *,
    workspace_id: str,
    default_branch: str = "main",
    repository_slug: str | None = None,
) -> WorkspaceManifest:
    """Export a read-consistent, secret-resistant repository projection."""

    root = Path(output_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="forecast-workspace-export-") as directory:
        snapshot_path = Path(directory) / "ledger.db"
        _backup(ledger, snapshot_path)
        from forecasting import ForecastLedger

        snapshot = ForecastLedger(snapshot_path)
        files: dict[str, bytes] = {}
        with snapshot._connect() as conn:
            revisions = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM ledger_revisions ORDER BY revision"
                ).fetchall()
            ]
        files["ledger/revisions.json"] = _json_bytes(
            {"version": 1, "revisions": revisions}
        )
        for question in sorted(snapshot.list_questions(), key=lambda item: item.id):
            files[f"ledger/questions/{question.id}.json"] = _json_bytes(
                _question_packet(snapshot, question.id)
            )
        for changeset in sorted(
            list_changesets(snapshot, workspace_id=workspace_id, limit=100_000),
            key=lambda item: item["id"],
        ):
            files[f"changesets/{changeset['id']}/changeset.json"] = _json_bytes(
                _changeset_packet(snapshot, changeset)
            )
            files.update(
                _provenance_files(
                    snapshot,
                    changeset,
                    repository_slug=repository_slug,
                )
            )
        files["policies/review-policy.json"] = _json_bytes(
            {"version": 1, "risk_tiers": ["low", "medium", "high"]}
        )
        files["extensions/lock.json"] = _json_bytes({"version": 1, "overlays": []})
        files[".gitignore"] = (
            b"*.db\n*.db-*\n.env\n.env.*\n!.env.example\nraw-traces/\n"
            b"**/raw-traces/\n__pycache__/\n*.pyc\n.git-credentials\n"
        )
        digests = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
        manifest = WorkspaceManifest(
            workspace_id=workspace_id,
            default_branch=default_branch,
            ledger_revision=current_revision(snapshot)["revision"],
            files=digests,
        )
        files["forecast-workspace.yaml"] = manifest.to_yaml().encode("utf-8")
        for relative, data in files.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    return manifest


__all__ = ["export_workspace"]
