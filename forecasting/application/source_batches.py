"""Atomic persistence for one acquired source batch; no fetching or presentation."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem


@dataclass(frozen=True)
class ImportedSourceRow:
    index: int
    evidence: EvidenceItem


@dataclass(frozen=True)
class SourceBatchResult:
    imported: tuple[ImportedSourceRow, ...]
    duplicate_indices: tuple[int, ...]


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
        seen = ledger.existing_evidence_keys(question_id) if dedupe else set()
        for index, payload in enumerate(rows):
            entry_id = (payload.get("metadata") or {}).get("entry_id")
            key = (
                (payload.get("source_type") or "", str(entry_id)) if entry_id else None
            )
            if dedupe and key is not None and key in seen:
                duplicates.append(index)
                continue
            evidence = ledger.add_evidence(
                question_id=question_id, archive_url_snapshot=False, **payload
            )
            imported.append(ImportedSourceRow(index, evidence))
            if key is not None:
                seen.add(key)
    return SourceBatchResult(tuple(imported), tuple(duplicates))
