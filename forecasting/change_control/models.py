"""Versioned, deterministic ledger changeset models."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from forecasting.models import ValidationError


OPERATION_VERSION = 1
OPERATION_KINDS = frozenset(
    {
        "forecast.create",
        "forecast.update",
        "evidence.attach",
        "assumption.upsert",
        "reference_class.upsert",
        "question.criteria.update",
        "resolution.create",
        "thesis.update",
        "document.update",
        "lesson.activate",
    }
)
CHANGESET_STATUSES = frozenset(
    {
        "draft",
        "preview_failed",
        "ready",
        "publishing",
        "review_open",
        "checks_running",
        "review_required",
        "changes_requested",
        "held",
        "blocked",
        "merge_ready",
        "merge_queued",
        "merged_apply_pending",
        "applying",
        "apply_failed",
        "applied",
        "rejected",
        "cancelled",
        "abandoned",
        "superseded",
    }
)
RISK_TIERS = frozenset({"low", "medium", "high"})
REVIEW_DECISIONS = frozenset({"approve", "request_changes", "reject", "hold", "resume"})
ACTOR_KINDS = frozenset({"human", "agent", "app"})

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REQUIRED_PAYLOAD_KEYS: dict[str, frozenset[str]] = {
    "forecast.create": frozenset({"title", "resolution_criteria", "probability_or_distribution"}),
    "forecast.update": frozenset({"probability_or_distribution", "rationale"}),
    "evidence.attach": frozenset({"source_type", "claim"}),
    "assumption.upsert": frozenset({"text"}),
    "reference_class.upsert": frozenset({"name"}),
    "question.criteria.update": frozenset({"resolution_criteria"}),
    "resolution.create": frozenset({"outcome"}),
    "thesis.update": frozenset({"title"}),
    "document.update": frozenset({"path", "content"}),
    "lesson.activate": frozenset({"lesson_id"}),
}


def canonical_json(value: Any) -> str:
    """Return the canonical UTF-8 JSON representation used for all digests."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"value is not canonical JSON: {exc}") from exc


def content_digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_id(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not _ID_RE.fullmatch(value):
        raise ValidationError(
            f"{field_name} must match {_ID_RE.pattern} and be at most 128 characters"
        )
    return value


def _string_list(values: Sequence[Any] | None, field_name: str) -> tuple[str, ...]:
    result: list[str] = []
    for value in values or ():
        item = str(value or "").strip()
        if not item:
            raise ValidationError(f"{field_name} entries must be non-empty strings")
        result.append(item)
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True)
class LedgerOperation:
    """One immutable proposed mutation in a ledger changeset."""

    id: str
    kind: str
    target_ref: str
    payload: Mapping[str, Any]
    preconditions: Mapping[str, Any] = field(default_factory=dict)
    provenance_refs: tuple[str, ...] = ()
    author_attestation: Mapping[str, Any] = field(default_factory=dict)
    version: int = OPERATION_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _validate_id(self.id, "operation id"))
        kind = str(self.kind or "").strip()
        if kind not in OPERATION_KINDS:
            raise ValidationError(f"unsupported operation kind: {kind or '<empty>'}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "target_ref", _validate_id(self.target_ref, "target_ref"))
        if self.version != OPERATION_VERSION:
            raise ValidationError(
                f"unsupported operation version {self.version}; expected {OPERATION_VERSION}"
            )
        if not isinstance(self.payload, Mapping):
            raise ValidationError("operation payload must be an object")
        if not isinstance(self.preconditions, Mapping):
            raise ValidationError("operation preconditions must be an object")
        if not isinstance(self.author_attestation, Mapping):
            raise ValidationError("operation author_attestation must be an object")
        payload = dict(self.payload)
        missing = sorted(_REQUIRED_PAYLOAD_KEYS[kind] - payload.keys())
        if missing:
            raise ValidationError(f"{kind} payload missing required keys: {', '.join(missing)}")
        object.__setattr__(self, "payload", payload)
        object.__setattr__(self, "preconditions", dict(self.preconditions))
        object.__setattr__(self, "author_attestation", dict(self.author_attestation))
        object.__setattr__(
            self,
            "provenance_refs",
            _string_list(self.provenance_refs, "provenance_refs"),
        )
        canonical_json(self.as_dict())

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LedgerOperation":
        if not isinstance(value, Mapping):
            raise ValidationError("operation must be an object")
        return cls(
            id=value.get("id", ""),
            kind=value.get("kind", ""),
            target_ref=value.get("target_ref", ""),
            payload=value.get("payload") or {},
            preconditions=value.get("preconditions") or {},
            provenance_refs=tuple(value.get("provenance_refs") or ()),
            author_attestation=value.get("author_attestation") or {},
            version=value.get("version", OPERATION_VERSION),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "id": self.id,
            "kind": self.kind,
            "target_ref": self.target_ref,
            "preconditions": dict(self.preconditions),
            "payload": dict(self.payload),
            "provenance_refs": list(self.provenance_refs),
            "author_attestation": dict(self.author_attestation),
        }

    @property
    def digest(self) -> str:
        return content_digest(self.as_dict())


def changeset_digest(
    *,
    workspace_id: str,
    base_revision: int,
    operations: Sequence[LedgerOperation],
) -> str:
    if base_revision < 0:
        raise ValidationError("base_revision must be non-negative")
    return content_digest(
        {
            "version": 1,
            "workspace_id": _validate_id(workspace_id, "workspace_id"),
            "base_revision": int(base_revision),
            "operations": [operation.as_dict() for operation in operations],
        }
    )


__all__ = [
    "ACTOR_KINDS",
    "CHANGESET_STATUSES",
    "LedgerOperation",
    "OPERATION_KINDS",
    "OPERATION_VERSION",
    "REVIEW_DECISIONS",
    "RISK_TIERS",
    "canonical_json",
    "changeset_digest",
    "content_digest",
]
