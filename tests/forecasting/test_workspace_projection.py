from __future__ import annotations

from pathlib import Path

from forecasting import ForecastLedger
from forecasting.ledger import allow_ledger_writes
from forecasting.workspace import export_workspace, validate_workspace
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
