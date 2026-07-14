"""Fail-closed validation for portable forecast repositories."""

from __future__ import annotations

import re
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from forecasting.models import ValidationError
from forecasting.change_control.models import LedgerOperation, changeset_digest, content_digest
from forecasting.workspace.manifest import WorkspaceManifest


_ALLOWED_TOP_LEVEL = frozenset(
    {
        ".gitignore",
        "forecast-workspace.yaml",
        "ledger",
        "changesets",
        "documents",
        "policies",
        "transcripts",
        "attestations",
        "extensions",
    }
)
_DENIED_NAMES = frozenset({".env", ".git-credentials", "credentials.json", "id_rsa"})
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("authorization", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("session_cookie", re.compile(r"\b(?:_gh_sess|user_session|session_cookie)\b", re.I)),
)


def _validate_generated_json(relative: str, value: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, dict):
        return [f"generated JSON must be an object: {relative}"]
    if relative == "ledger/revisions.json":
        if value.get("version") != 1 or not isinstance(value.get("revisions"), list):
            errors.append(f"invalid ledger revision packet: {relative}")
    elif relative.startswith("ledger/questions/"):
        if not isinstance(value.get("question"), dict) or not value["question"].get("id"):
            errors.append(f"invalid question packet: {relative}")
    elif relative.endswith("/changeset.json"):
        try:
            operations = [LedgerOperation.from_dict(item) for item in value["operations"]]
            actual = changeset_digest(
                workspace_id=str(value["workspace_id"]),
                base_revision=int(value["base_revision"]),
                operations=operations,
            )
            if actual != value.get("digest"):
                errors.append(f"changeset digest mismatch: {relative}")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            errors.append(f"invalid changeset packet {relative}: {exc}")
    elif relative.endswith("/contributors.json"):
        for index, contribution in enumerate(value.get("contributions") or []):
            if not isinstance(contribution, dict) or content_digest(
                contribution.get("attestation")
            ) != contribution.get("digest"):
                errors.append(f"contributor attestation digest mismatch: {relative}#{index}")
    elif relative.endswith("/decisions.json"):
        fields = (
            "conclusion",
            "alternatives",
            "evidence_refs",
            "assumptions",
            "probability_changes",
            "unresolved_uncertainty",
            "model",
            "prompt_version",
            "tools",
            "tests",
        )
        for index, decision in enumerate(value.get("decisions") or []):
            if not isinstance(decision, dict):
                errors.append(f"invalid decision record: {relative}#{index}")
                continue
            body = {field: decision.get(field) for field in fields}
            if content_digest(body) != decision.get("digest"):
                errors.append(f"decision record digest mismatch: {relative}#{index}")
    elif relative.endswith("/provenance.json"):
        for key in ("changeset_digest", "provenance_digest"):
            if not re.fullmatch(r"[a-f0-9]{64}", str(value.get(key) or "")):
                errors.append(f"invalid {key}: {relative}")
    elif relative.endswith("/manifest.json") and relative.startswith("transcripts/"):
        if value.get("version") != 1 or not isinstance(value.get("artifacts"), list):
            errors.append(f"invalid transcript manifest: {relative}")
        allowed_statuses = {
            "transcript_not_available",
            "transcript_consent_required",
            "transcript_withheld_by_owner",
            "transcript_unavailable_safety_failure",
            "transcript_included",
        }
        if value.get("publication_status") not in allowed_statuses:
            errors.append(f"invalid transcript publication status: {relative}")
        if not isinstance(value.get("content_included"), bool):
            errors.append(f"invalid transcript inclusion flag: {relative}")
    elif relative in {"policies/review-policy.json", "extensions/lock.json"}:
        if value.get("version") != 1:
            errors.append(f"unsupported generated record version: {relative}")
    return errors


@dataclass(frozen=True)
class ValidationReport:
    valid: bool
    errors: tuple[str, ...]
    checked_files: int
    content_digest: str | None


def validate_workspace(
    root: str | Path,
    *,
    max_file_bytes: int = 2_000_000,
    raise_on_error: bool = False,
) -> ValidationReport:
    directory = Path(root).expanduser()
    errors: list[str] = []
    manifest_path = directory / "forecast-workspace.yaml"
    manifest: WorkspaceManifest | None = None
    if not manifest_path.is_file():
        errors.append("missing forecast-workspace.yaml")
    else:
        try:
            manifest = WorkspaceManifest.from_yaml(manifest_path.read_text("utf-8"))
        except (OSError, UnicodeDecodeError, ValidationError, ValueError) as exc:
            errors.append(f"invalid forecast-workspace.yaml: {exc}")

    actual: dict[str, Path] = {}
    if directory.exists():
        for path in directory.rglob("*"):
            relative = path.relative_to(directory).as_posix()
            if relative == ".git" or relative.startswith(".git/"):
                continue
            if path.is_symlink():
                errors.append(f"symbolic links are not portable: {relative}")
                continue
            if not path.is_file():
                continue
            actual[relative] = path
            top = relative.split("/", 1)[0]
            if top not in _ALLOWED_TOP_LEVEL:
                errors.append(f"unexpected top-level path: {relative}")
            if path.name in _DENIED_NAMES or path.suffix in {".db", ".sqlite", ".sqlite3"}:
                errors.append(f"forbidden repository file: {relative}")
            if path.stat().st_size > max_file_bytes:
                errors.append(f"oversized repository file: {relative}")
            try:
                text = path.read_text("utf-8")
            except UnicodeDecodeError:
                errors.append(f"binary repository file is not allowed: {relative}")
                continue
            if text.startswith("SQLite format 3"):
                errors.append(f"SQLite database content is forbidden: {relative}")
            for secret_class, pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    errors.append(f"{secret_class} detected in {relative}")
            if path.suffix == ".json":
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    errors.append(f"invalid JSON: {relative}")
                else:
                    errors.extend(_validate_generated_json(relative, value))

    if manifest is not None:
        for relative, path in actual.items():
            if not (
                relative.startswith("transcripts/")
                and relative.endswith("/manifest.json")
            ):
                continue
            try:
                packet = json.loads(path.read_text("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            included = packet.get("content_included") is True
            status = packet.get("publication_status")
            transcript_relative = relative.removesuffix("manifest.json") + "transcript.md"
            transcript_path = actual.get(transcript_relative)
            if included:
                if status != "transcript_included" or transcript_path is None:
                    errors.append(f"included transcript content is missing: {relative}")
                else:
                    try:
                        transcript_text = transcript_path.read_text("utf-8")
                    except (OSError, UnicodeDecodeError):
                        continue
                    if content_digest(transcript_text) != packet.get("published_digest"):
                        errors.append(f"published transcript digest mismatch: {relative}")
            elif transcript_path is not None:
                errors.append(f"withheld transcript content is present: {relative}")

        expected = set(manifest.files)
        missing = sorted(expected - set(actual))
        unexpected = sorted(set(actual) - expected - {"forecast-workspace.yaml"})
        errors.extend(f"manifest file is missing: {path}" for path in missing)
        errors.extend(f"file is not declared by manifest: {path}" for path in unexpected)
        for relative, expected_digest in manifest.files.items():
            path = actual.get(relative)
            if path is None:
                continue
            try:
                actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except UnicodeDecodeError:
                continue
            if actual_digest != expected_digest:
                errors.append(f"digest mismatch: {relative}")
    report = ValidationReport(
        valid=not errors,
        errors=tuple(dict.fromkeys(errors)),
        checked_files=len(actual),
        content_digest=None if manifest is None else manifest.content_digest,
    )
    if raise_on_error and errors:
        raise ValidationError("; ".join(report.errors))
    return report


__all__ = ["ValidationReport", "validate_workspace"]
