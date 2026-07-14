"""Fail-closed validation for portable forecast repositories."""

from __future__ import annotations

import re
import hashlib
from dataclasses import dataclass
from pathlib import Path

from forecasting.models import ValidationError
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

    if manifest is not None:
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
