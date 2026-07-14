"""Canonical forecast workspace manifest."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import yaml

from forecasting.change_control.models import content_digest
from forecasting.models import ValidationError


FORMAT_VERSION = 1


@dataclass(frozen=True)
class WorkspaceManifest:
    workspace_id: str
    default_branch: str
    ledger_revision: int
    files: Mapping[str, str]
    format_version: int = FORMAT_VERSION

    def __post_init__(self) -> None:
        if self.format_version != FORMAT_VERSION:
            raise ValidationError(f"unsupported workspace format version: {self.format_version}")
        if not self.workspace_id.strip():
            raise ValidationError("workspace_id is required")
        if self.ledger_revision < 0:
            raise ValidationError("ledger_revision must be non-negative")
        for path, digest in self.files.items():
            if path.startswith("/") or ".." in path.split("/"):
                raise ValidationError(f"unsafe manifest path: {path}")
            if len(digest) != 64:
                raise ValidationError(f"invalid digest for {path}")

    @property
    def content_digest(self) -> str:
        return content_digest(dict(sorted(self.files.items())))

    def as_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "workspace_id": self.workspace_id,
            "default_branch": self.default_branch,
            "ledger_revision": self.ledger_revision,
            "content_digest": self.content_digest,
            "files": dict(sorted(self.files.items())),
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.as_dict(), sort_keys=False, allow_unicode=True)

    @classmethod
    def from_yaml(cls, text: str) -> "WorkspaceManifest":
        value = yaml.safe_load(text)
        if not isinstance(value, dict):
            raise ValidationError("forecast-workspace.yaml must contain a mapping")
        manifest = cls(
            format_version=int(value.get("format_version", 0)),
            workspace_id=str(value.get("workspace_id") or ""),
            default_branch=str(value.get("default_branch") or ""),
            ledger_revision=int(value.get("ledger_revision", -1)),
            files=dict(value.get("files") or {}),
        )
        if value.get("content_digest") != manifest.content_digest:
            raise ValidationError("workspace manifest content_digest does not match files")
        return manifest


__all__ = ["FORMAT_VERSION", "WorkspaceManifest"]
