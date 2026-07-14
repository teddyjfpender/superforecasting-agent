"""Validated staging reconstruction from a portable forecast workspace."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from hermes_constants import get_hermes_home

from forecasting.change_control.models import LedgerOperation, changeset_digest, content_digest
from forecasting.ledger.gate import allow_ledger_writes
from forecasting.models import ValidationError
from forecasting.workspace.manifest import WorkspaceManifest
from forecasting.workspace.projection import export_workspace
from forecasting.workspace.validation import validate_workspace


class BootstrapError(ValidationError):
    def __init__(self, message: str, staging_path: Path) -> None:
        super().__init__(f"{message}; resumable staging path: {staging_path}")
        self.staging_path = staging_path


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text("utf-8"))


def _import_provenance(conn: Any, ledger: Any, root: Path, packet: dict[str, Any]) -> None:
    changeset_id = str(packet["id"])
    contributor_path = root / f"attestations/{changeset_id}/contributors.json"
    if contributor_path.is_file():
        contributors = _load_json(contributor_path).get("contributions") or []
        for contribution in contributors:
            attestation = dict(contribution["attestation"])
            digest = str(contribution["digest"])
            conn.execute(
                """INSERT INTO collaboration_contributions (
                       id, changeset_id, idempotency_key, owner_id, slack_user_id,
                       github_user_id, agent_instance_id, agent_persona, actor_kind,
                       commit_sha, attestation, attestation_digest, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"contrib_import_{digest[:24]}",
                    changeset_id,
                    f"portable:{changeset_id}:{digest}",
                    str(attestation.get("human_owner") or "portable-owner"),
                    f"portable:{attestation.get('human_owner') or 'owner'}",
                    str(attestation.get("github_actor") or "portable-github-user"),
                    str(attestation.get("agent_instance") or "portable-agent"),
                    str(attestation.get("agent_persona") or "Portable Agent"),
                    str(attestation.get("actor_kind") or "agent"),
                    attestation.get("commit_sha"),
                    json.dumps(attestation, sort_keys=True),
                    digest,
                    contribution["created_at"],
                ),
            )

    provenance_path = root / f"attestations/{changeset_id}/provenance.json"
    if not provenance_path.is_file():
        return
    provenance = _load_json(provenance_path)
    bundle_id = f"prov_import_{changeset_id}"
    conn.execute(
        """INSERT INTO provenance_bundles
           (id, changeset_id, changeset_digest, digest, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            bundle_id,
            changeset_id,
            provenance["changeset_digest"],
            provenance["provenance_digest"],
            packet["created_at"],
        ),
    )
    decisions_path = root / f"attestations/{changeset_id}/decisions.json"
    if decisions_path.is_file():
        for decision in _load_json(decisions_path).get("decisions") or []:
            conn.execute(
                """INSERT INTO provenance_decision_records
                   (id, bundle_id, conclusion, alternatives, evidence_refs, assumptions,
                    probability_changes, unresolved_uncertainty, model, prompt_version,
                    tools, tests, digest, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    decision["id"],
                    bundle_id,
                    decision["conclusion"],
                    json.dumps(decision.get("alternatives") or [], sort_keys=True),
                    json.dumps(decision.get("evidence_refs") or [], sort_keys=True),
                    json.dumps(decision.get("assumptions") or [], sort_keys=True),
                    json.dumps(decision.get("probability_changes") or [], sort_keys=True),
                    json.dumps(
                        decision.get("unresolved_uncertainty") or [], sort_keys=True
                    ),
                    decision.get("model"),
                    decision.get("prompt_version"),
                    json.dumps(decision.get("tools") or [], sort_keys=True),
                    json.dumps(decision.get("tests") or [], sort_keys=True),
                    decision["digest"],
                    decision["created_at"],
                ),
            )
    transcript_manifest_path = root / f"transcripts/{changeset_id}/manifest.json"
    if not transcript_manifest_path.is_file():
        return
    transcript_manifest = _load_json(transcript_manifest_path)
    published_digest = transcript_manifest.get("published_digest")
    safe_content = root / f"transcripts/{changeset_id}/transcript.md"
    locator: str | None = None
    if transcript_manifest.get("content_included") and safe_content.is_file():
        destination = (
            get_hermes_home()
            / "provenance"
            / "safe-transcripts"
            / changeset_id
            / f"{published_digest}.md"
        )
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination.parent.chmod(0o700)
        destination.write_bytes(safe_content.read_bytes())
        destination.chmod(0o600)
        locator = str(destination)
    for artifact in transcript_manifest.get("artifacts") or []:
        conn.execute(
            """INSERT INTO provenance_transcripts
               (id, bundle_id, format, status, digest, locator, byte_size,
                safety_findings, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                artifact["id"],
                bundle_id,
                artifact["format"],
                artifact["status"],
                artifact["digest"],
                locator if artifact["digest"] == published_digest else None,
                artifact["byte_size"],
                json.dumps(artifact.get("safety_findings") or [], sort_keys=True),
                artifact["created_at"],
            ),
        )
    for consent in transcript_manifest.get("publication_consents") or []:
        consent_digest = str(consent["transcript_digest"])
        conn.execute(
            """INSERT INTO provenance_consents
               (id, changeset_id, transcript_digest, repository_slug, owner_id,
                decision, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                f"consent_import_{content_digest(consent)[:24]}",
                changeset_id,
                consent_digest,
                consent["repository_slug"],
                consent["owner_id"],
                consent["decision"],
                consent["created_at"],
            ),
        )


def _import_changesets(ledger: Any, root: Path, manifest: WorkspaceManifest) -> None:
    paths = sorted(root.glob("changesets/*/changeset.json"))
    with ledger._connect() as conn:
        for path in paths:
            packet = _load_json(path)
            operations = [LedgerOperation.from_dict(value) for value in packet["operations"]]
            digest = changeset_digest(
                workspace_id=packet["workspace_id"],
                base_revision=int(packet["base_revision"]),
                operations=operations,
            )
            if digest != packet["digest"]:
                raise ValidationError(f"changeset digest mismatch in {path.relative_to(root)}")
            conn.execute(
                """INSERT INTO ledger_changesets (
                       id, workspace_id, base_revision, status, digest, risk_tier,
                       risk_reasons, branch, pr_number, head_sha, merge_sha,
                       author_owner_ids, author_identities, affected_question_ids,
                       metadata, created_at, updated_at, applied_revision, applied_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?)""",
                (
                    packet["id"],
                    packet["workspace_id"],
                    packet["base_revision"],
                    "applied" if packet.get("applied_revision") is not None else "draft",
                    packet["digest"],
                    packet["risk_tier"],
                    json.dumps(packet.get("risk_reasons") or [], sort_keys=True),
                    None,
                    None,
                    None,
                    None,
                    json.dumps(packet.get("author_owner_ids") or [], sort_keys=True),
                    json.dumps(packet.get("author_identities") or [], sort_keys=True),
                    json.dumps(packet.get("affected_question_ids") or [], sort_keys=True),
                    packet["created_at"],
                    packet["created_at"],
                    packet.get("applied_revision"),
                    packet.get("applied_at"),
                ),
            )
            for sequence, operation in enumerate(operations):
                conn.execute(
                    """INSERT INTO ledger_change_operations (
                           id, changeset_id, sequence, kind, target_ref, version,
                           preconditions, payload, provenance_refs, author_attestation,
                           digest, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        operation.id,
                        packet["id"],
                        sequence,
                        operation.kind,
                        operation.target_ref,
                        operation.version,
                        json.dumps(dict(operation.preconditions), sort_keys=True),
                        json.dumps(dict(operation.payload), sort_keys=True),
                        json.dumps(list(operation.provenance_refs), sort_keys=True),
                        json.dumps(dict(operation.author_attestation), sort_keys=True),
                        operation.digest,
                        packet["created_at"],
                    ),
                )
            for review in packet.get("reviews") or []:
                conn.execute(
                    """INSERT INTO ledger_reviews (
                           id, changeset_id, changeset_digest, head_sha, decision,
                           actor_kind, owner_id, github_user_id, agent_instance_id,
                           agent_persona, role, source, metadata, created_at, stale_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)""",
                    (
                        review["id"],
                        packet["id"],
                        review["changeset_digest"],
                        review.get("head_sha"),
                        review["decision"],
                        review["actor_kind"],
                        review.get("owner_id"),
                        review.get("github_user_id"),
                        review.get("agent_instance_id"),
                        review.get("agent_persona"),
                        review.get("role"),
                        review["source"],
                        review["created_at"],
                        review.get("stale_at"),
                    ),
                )
            _import_provenance(conn, ledger, root, packet)
        revision_packet = _load_json(root / "ledger/revisions.json")
        conn.execute("DELETE FROM ledger_revisions")
        for revision in revision_packet["revisions"]:
            conn.execute(
                """INSERT INTO ledger_revisions
                   (revision, parent_revision, changeset_id, digest, applied_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    revision["revision"],
                    revision.get("parent_revision"),
                    revision.get("changeset_id"),
                    revision["digest"],
                    revision["applied_at"],
                ),
            )
        current = conn.execute(
            "SELECT MAX(revision) AS revision FROM ledger_revisions"
        ).fetchone()["revision"]
        if current != manifest.ledger_revision:
            raise ValidationError(
                f"reconstructed revision {current} != manifest {manifest.ledger_revision}"
            )


def bootstrap_workspace(
    workspace_root: str | Path,
    target_db: str | Path,
) -> dict[str, Any]:
    """Reconstruct to staging and atomically activate only after digest parity."""

    root = Path(workspace_root).expanduser()
    validate_workspace(root, raise_on_error=True)
    manifest = WorkspaceManifest.from_yaml((root / "forecast-workspace.yaml").read_text("utf-8"))
    target = Path(target_db).expanduser()
    if target.exists():
        raise ValidationError(f"target ledger already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(f"{target.name}.staging-{uuid.uuid4().hex[:10]}")
    try:
        from forecasting import ForecastLedger

        ledger = ForecastLedger(staging)
        question_packets = [
            _load_json(path) for path in sorted(root.glob("ledger/questions/*.json"))
        ]
        with allow_ledger_writes("workspace_bootstrap"), ledger.transaction(immediate=True):
            if question_packets:
                ledger.import_packet({"questions": question_packets}, conflict="error")
            _import_changesets(ledger, root, manifest)
        with ledger._connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        with tempfile.TemporaryDirectory(prefix="forecast-bootstrap-verify-") as temp:
            exported = export_workspace(
                ledger,
                Path(temp),
                workspace_id=manifest.workspace_id,
                default_branch=manifest.default_branch,
                repository_slug=manifest.repository_slug,
            )
            if exported.content_digest != manifest.content_digest:
                raise ValidationError(
                    "reconstructed workspace content digest does not match repository"
                )
        os.replace(staging, target)
        for suffix in ("-wal", "-shm"):
            Path(str(staging) + suffix).unlink(missing_ok=True)
        return {
            "workspace_id": manifest.workspace_id,
            "ledger_revision": manifest.ledger_revision,
            "content_digest": manifest.content_digest,
            "target_db": str(target),
        }
    except Exception as exc:
        if isinstance(exc, BootstrapError):
            raise
        raise BootstrapError(str(exc), staging) from exc


__all__ = ["BootstrapError", "bootstrap_workspace"]
