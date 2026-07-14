from __future__ import annotations

from pathlib import Path
import hashlib
import json

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
from forecasting.change_control.transcripts import render_review_transcript
from forecasting.ledger import allow_ledger_writes
from forecasting.models import ValidationError
from forecasting.workspace import bootstrap_workspace, export_workspace, validate_workspace
from forecasting.workspace.manifest import WorkspaceManifest


def _ledger(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    with allow_ledger_writes("workspace projection test"):
        question = ledger.create_question(
            title="Will the policy launch this quarter?",
            resolution_criteria="Resolve Yes after the official production launch.",
            metadata={
                "public_note": "Track the official launch announcement.",
                "api_key": "must-not-be-exported",
                "source_file_path": "/Users/alice/private/source.txt",
            },
        )
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.62,
            rationale="The published implementation schedule supports a launch this quarter.",
            require_style=False,
            require_output_structure=False,
        )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note="The official schedule names this quarter.",
        claim="The implementation schedule remains on track.",
    )
    return ledger, question


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_workspace_projection_is_deterministic_and_valid(tmp_path):
    ledger, question = _ledger(tmp_path)
    first, second = tmp_path / "first", tmp_path / "second"

    first_manifest = export_workspace(ledger, first, workspace_id="desk_1")
    second_manifest = export_workspace(ledger, second, workspace_id="desk_1")

    assert first_manifest.content_digest == second_manifest.content_digest
    assert _tree(first) == _tree(second)
    report = validate_workspace(first)
    assert report.valid is True
    packet = (first / f"ledger/questions/{question.id}.json").read_text()
    assert "must-not-be-exported" not in packet
    assert "/Users/alice" not in packet
    assert not any(path.suffix == ".db" for path in first.rglob("*"))
    parsed = WorkspaceManifest.from_yaml((first / "forecast-workspace.yaml").read_text())
    assert parsed.ledger_revision == 0


def test_validator_reports_tampering_unexpected_secrets_and_databases(tmp_path):
    ledger, question = _ledger(tmp_path)
    root = tmp_path / "workspace"
    export_workspace(ledger, root, workspace_id="desk_1")
    packet = root / f"ledger/questions/{question.id}.json"
    packet.write_text(packet.read_text() + "\n")
    (root / "notes.txt").write_text("ghp_abcdefghijklmnopqrstuvwxyz123456")
    (root / "ledger" / "live.db").write_bytes(b"SQLite format 3\x00private")

    report = validate_workspace(root)

    assert report.valid is False
    assert any("digest mismatch" in error for error in report.errors)
    assert any("unexpected top-level path" in error for error in report.errors)
    assert any("github_token" in error for error in report.errors)
    assert any("forbidden repository file" in error for error in report.errors)


def test_validator_ignores_managed_git_metadata(tmp_path):
    ledger, _ = _ledger(tmp_path)
    root = tmp_path / "workspace"
    export_workspace(ledger, root, workspace_id="desk_1")
    (root / ".git" / "objects").mkdir(parents=True)
    (root / ".git" / "config").write_text("token=local-only-git-config")
    assert validate_workspace(root).valid is True


def test_bootstrap_reconstructs_in_staging_with_digest_parity(tmp_path):
    ledger, question = _ledger(tmp_path)
    root = tmp_path / "workspace"
    manifest = export_workspace(ledger, root, workspace_id="desk_1")
    target = tmp_path / "restored" / "forecasting.db"

    result = bootstrap_workspace(root, target)

    restored = ForecastLedger(target)
    restored_question = restored.get_question(question.id)
    assert restored_question.title == question.title
    assert restored.get_current_snapshot(question.id).probability_or_distribution == 0.62
    assert result["content_digest"] == manifest.content_digest
    assert not list(target.parent.glob("*.staging-*"))


def test_bootstrap_never_overwrites_existing_ledger(tmp_path):
    ledger, _ = _ledger(tmp_path)
    root = tmp_path / "workspace"
    export_workspace(ledger, root, workspace_id="desk_1")
    target = tmp_path / "existing.db"
    target.write_bytes(b"existing-ledger")
    with pytest.raises(ValidationError, match="already exists"):
        bootstrap_workspace(root, target)
    assert target.read_bytes() == b"existing-ledger"


def test_bootstrap_preserves_generalized_changesets(tmp_path):
    ledger, _ = _ledger(tmp_path)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_1"]
    )
    control.add_operation(
        changeset["id"],
        LedgerOperation(
            id="document_1",
            kind="document.update",
            target_ref="brief_1",
            payload={"path": "documents/brief.md", "content": "Current thesis."},
        ),
    )
    root = tmp_path / "workspace"
    export_workspace(ledger, root, workspace_id="desk_1")
    target = tmp_path / "restored.db"

    bootstrap_workspace(root, target)

    restored = ChangeControl(ForecastLedger(target))
    restored_changeset = restored.get_changeset(changeset["id"])
    assert restored_changeset["digest"] == control.get_changeset(changeset["id"])["digest"]
    assert restored.list_operations(changeset["id"])[0].as_dict() == control.list_operations(
        changeset["id"]
    )[0].as_dict()


def test_validator_recomputes_nested_contributor_attestations(tmp_path):
    ledger, _ = _ledger(tmp_path)
    control = ChangeControl(ledger)
    binding = control.bind_identity(
        owner_id="owner_1",
        slack_team_id="T1",
        slack_user_id="U1",
        agent_instance_id="agent_1",
        agent_persona="Mira",
        github_user_id="101",
        github_node_id="node-101",
        github_login="octocat",
    )
    changeset = control.create_changeset(workspace_id="desk_1")
    control.record_contribution(
        changeset["id"],
        idempotency_key="contribution-1",
        binding=binding,
        actor_kind="agent",
    )
    root = tmp_path / "workspace"
    export_workspace(ledger, root, workspace_id="desk_1")
    relative = f"attestations/{changeset['id']}/contributors.json"
    path = root / relative
    packet = json.loads(path.read_text())
    packet["contributions"][0]["attestation"]["agent_persona"] = "forged"
    path.write_text(json.dumps(packet, sort_keys=True, indent=2) + "\n")
    manifest = WorkspaceManifest.from_yaml((root / "forecast-workspace.yaml").read_text())
    files = dict(manifest.files)
    files[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "forecast-workspace.yaml").write_text(
        WorkspaceManifest(
            workspace_id=manifest.workspace_id,
            default_branch=manifest.default_branch,
            ledger_revision=manifest.ledger_revision,
            files=files,
        ).to_yaml()
    )

    report = validate_workspace(root)

    assert not report.valid
    assert any("contributor attestation digest mismatch" in error for error in report.errors)


def test_safe_transcript_requires_exact_owner_and_repository_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / "home"))
    ledger, _ = _ledger(tmp_path)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(
        workspace_id="desk_1",
        author_owner_ids=["owner_1"],
        metadata={"goal": "Update q_policy"},
    )
    rendered = render_review_transcript(
        changeset_id=changeset["id"],
        goal="Update q_policy",
        sessions={"session_1": [{"role": "user", "content": "Update q_policy."}]},
        changed_object_ids=["q_policy"],
    )
    control.record_transcript(
        changeset["id"],
        format="markdown",
        status="safe",
        digest=rendered.digest,
        byte_size=len(rendered.markdown.encode("utf-8")),
        content=rendered.markdown,
    )
    control.record_transcript_consent(
        changeset["id"],
        transcript_digest=rendered.digest,
        repository_slug="acme/forecasts",
        owner_id="owner_1",
        decision="include",
    )

    exact = tmp_path / "exact"
    other = tmp_path / "other"
    export_workspace(
        ledger,
        exact,
        workspace_id="desk_1",
        repository_slug="acme/forecasts",
    )
    export_workspace(
        ledger,
        other,
        workspace_id="desk_1",
        repository_slug="other/forecasts",
    )

    relative = f"transcripts/{changeset['id']}"
    exact_manifest = json.loads((exact / relative / "manifest.json").read_text())
    other_manifest = json.loads((other / relative / "manifest.json").read_text())
    assert (exact / relative / "transcript.md").read_text() == rendered.markdown
    assert exact_manifest["publication_status"] == "transcript_included"
    assert exact_manifest["published_digest"] == rendered.digest
    assert other_manifest["publication_status"] == "transcript_consent_required"
    assert not (other / relative / "transcript.md").exists()
    assert validate_workspace(exact).valid


def test_transcript_export_fails_closed_when_private_artifact_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path / "home"))
    ledger, _ = _ledger(tmp_path)
    control = ChangeControl(ledger)
    changeset = control.create_changeset(
        workspace_id="desk_1", author_owner_ids=["owner_1"]
    )
    rendered = render_review_transcript(
        changeset_id=changeset["id"],
        goal="policy",
        sessions={"session_1": [{"role": "user", "content": "Policy update."}]},
    )
    transcript = control.record_transcript(
        changeset["id"],
        format="markdown",
        status="safe",
        digest=rendered.digest,
        byte_size=len(rendered.markdown.encode("utf-8")),
        content=rendered.markdown,
    )
    control.record_transcript_consent(
        changeset["id"],
        transcript_digest=rendered.digest,
        repository_slug="acme/forecasts",
        owner_id="owner_1",
        decision="include",
    )
    Path(transcript["locator"]).write_text("changed after consent")

    root = tmp_path / "workspace"
    export_workspace(
        ledger,
        root,
        workspace_id="desk_1",
        repository_slug="acme/forecasts",
    )

    relative = f"transcripts/{changeset['id']}"
    manifest = json.loads((root / relative / "manifest.json").read_text())
    assert manifest["publication_status"] == "transcript_unavailable_safety_failure"
    assert manifest["content_included"] is False
    assert not (root / relative / "transcript.md").exists()
