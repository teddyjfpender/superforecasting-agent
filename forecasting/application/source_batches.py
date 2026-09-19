"""Atomic persistence for one acquired source batch; no fetching or presentation."""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem, parse_timestamp


@dataclass(frozen=True)
class ImportedSourceRow:
    index: int
    evidence: EvidenceItem


@dataclass(frozen=True)
class SourceBatchResult:
    imported: tuple[ImportedSourceRow, ...]
    duplicate_indices: tuple[int, ...]


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


def commit_source_payloads(
    ledger: ForecastLedger,
    question_id: str,
    payloads: Sequence[Mapping[str, Any]],
    *,
    dedupe: bool = True,
) -> SourceBatchResult:
    """Commit all accepted rows or none, using the ledger's evidence validation.

    Acquisition/parsing must finish before entry. Duplicate reads and writes share
    the immediate transaction, so concurrent importers cannot use a stale seen set.
    One batch means one source; callers may independently report other sources.
    This does not verify settlement semantics or manufacture missing provenance.
    """
    if not isinstance(dedupe, bool):
        raise ValueError("dedupe must be a boolean")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id is required")
    rows = [dict(payload) for payload in payloads]
    for payload in rows:
        # Prevent payloads from redirecting ownership or enabling network effects
        # while holding the SQLite write transaction.
        if "question_id" in payload or "archive_url_snapshot" in payload:
            raise ValueError("source payload cannot override import ownership")
    imported = []
    duplicates = []
    with ledger.transaction(immediate=True):
        ledger.get_question(question_id)
        seen: dict[tuple[str, str], set[str]] = {}
        if dedupe:
            for item in ledger.list_evidence(question_id):
                entry_id = item.metadata.get("entry_id")
                if entry_id:
                    key = (item.source_type or "", str(entry_id))
                    seen.setdefault(key, set()).add(
                        _provenance(item.metadata, item.source_url, item.published_at)
                    )
        for index, payload in enumerate(rows):
            entry_id = (payload.get("metadata") or {}).get("entry_id")
            key = (
                (payload.get("source_type") or "", str(entry_id)) if entry_id else None
            )
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
                # Multiple historical revisions sharing a key are ambiguous even
                # when this acquisition happens to match one of those versions.
                if seen[key] != {provenance}:
                    raise SourceRevisionConflict(index, key[1])
                duplicates.append(index)
                continue
            evidence = ledger.add_evidence(
                question_id=question_id, archive_url_snapshot=False, **payload
            )
            imported.append(ImportedSourceRow(index, evidence))
            if key is not None:
                seen.setdefault(key, set()).add(provenance)
    return SourceBatchResult(tuple(imported), tuple(duplicates))
