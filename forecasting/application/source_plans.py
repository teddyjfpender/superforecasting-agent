"""Side-effect-free provenance planning; settlement admission remains in the ledger."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from forecasting.models import EvidenceItem, parse_timestamp


class SourceRevisionConflict(ValueError):
    """A provider reused an entry identity for a different acquired observation."""

    reason_code = "source_revision_conflict"

    def __init__(self, index: int, entry_id: str) -> None:
        self.index = index
        self.entry_id = entry_id
        super().__init__(
            f"source_revision_conflict: row {index} reuses entry {entry_id!r} with changed provenance; "
            "review the revision before importing it"
        )


def _provenance(metadata: Mapping[str, Any], source_url: Any, published_at: Any) -> str:
    # User ratings and annotations do not revise publisher observations. The raw
    # parsed record and its source identity do. Missing provenance cannot be
    # silently upgraded by an entry-ID-only duplicate decision.
    return json.dumps(
        {
            "source": metadata.get("source"),
            "adapter": metadata.get("adapter"),
            "adapter_item": metadata.get("adapter_item"),
            "source_url": source_url,
            "published_at": parse_timestamp(published_at, field_name="published_at"),
        },
        sort_keys=True,
        allow_nan=False,
    )


@dataclass(frozen=True)
class SourcePlanRow:
    index: int
    disposition: Literal["accepted", "duplicate", "rejected"]
    reason_code: Literal[
        "new_observation", "exact_duplicate", "source_revision_conflict"
    ]
    entry_id: str | None = None


@dataclass(frozen=True)
class SourceImportPlan:
    """Frozen input and provenance decisions, not settlement verification.

    The snapshot is canonical JSON rather than mutable caller-owned mappings.
    Existing evidence is only a supplied observation; commit must plan again in
    its transaction. Accepted rows still require ledger field validation.
    """

    payload_json: str
    digest: str
    rows: tuple[SourcePlanRow, ...]


def prepare_source_import(
    payloads: Sequence[Mapping[str, Any]],
    existing: Sequence[EvidenceItem] = (),
    *,
    dedupe: bool = True,
) -> SourceImportPlan:
    if not isinstance(dedupe, bool):
        raise ValueError("dedupe must be a boolean")
    rows = [dict(payload) for payload in payloads]
    for payload in rows:
        if "question_id" in payload or "archive_url_snapshot" in payload:
            raise ValueError("source payload cannot override import ownership")
    snapshot = json.dumps(rows, sort_keys=True, allow_nan=False)
    rows = json.loads(snapshot)
    seen: dict[tuple[str, str], set[str]] = {}
    if dedupe:
        for item in existing:
            entry_id = item.metadata.get("entry_id")
            if entry_id:
                key = (item.source_type or "", str(entry_id))
                seen.setdefault(key, set()).add(
                    _provenance(item.metadata, item.source_url, item.published_at)
                )
    decisions = []
    for index, payload in enumerate(rows):
        entry_id = (payload.get("metadata") or {}).get("entry_id")
        key = (payload.get("source_type") or "", str(entry_id)) if entry_id else None
        provenance = _provenance(
            payload.get("metadata") or {},
            payload.get("source_url")
            or (
                payload["source_or_note"]
                if isinstance(payload.get("source_or_note"), str)
                and payload["source_or_note"].startswith(("http://", "https://"))
                else None
            ),
            payload.get("published_at"),
        )
        if dedupe and key is not None and key in seen:
            if seen[key] != {provenance}:
                decisions.append(
                    SourcePlanRow(index, "rejected", "source_revision_conflict", key[1])
                )
            else:
                decisions.append(
                    SourcePlanRow(index, "duplicate", "exact_duplicate", key[1])
                )
            continue
        decisions.append(
            SourcePlanRow(index, "accepted", "new_observation", key[1] if key else None)
        )
        if key is not None:
            seen.setdefault(key, set()).add(provenance)
    return SourceImportPlan(
        snapshot, hashlib.sha256(snapshot.encode()).hexdigest(), tuple(decisions)
    )
