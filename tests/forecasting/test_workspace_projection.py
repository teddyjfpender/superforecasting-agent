from __future__ import annotations

from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.change_control import ChangeControl, LedgerOperation
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
