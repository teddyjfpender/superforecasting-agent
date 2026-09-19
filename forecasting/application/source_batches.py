"""Atomic persistence for one acquired source batch; no fetching or presentation."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from forecasting.application.import_receipts import (
    BatchIndices,
    ImportReceipt,
    ensure_receipts,
    read_receipt,
    write_receipt,
)
from forecasting.application.source_plans import (
    SourceRevisionConflict as SourceRevisionConflict,
)
from forecasting.application.source_plans import (
    prepare_source_import,
)
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
    request_id: str | None = None,
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
    if request_id is not None and (
        not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 200
    ):
        raise ValueError(
            "request_id must be a nonempty string of at most 200 characters"
        )
    # Detach nested provenance from caller-owned mappings before digesting or
    # entering the transaction. JSON is the evidence transfer representation.
    rows = json.loads(
        json.dumps([dict(payload) for payload in payloads], allow_nan=False)
    )
    digest = (
        hashlib.sha256(
            json.dumps(
                {
                    "operation": "source_batch_v1",
                    "question_id": question_id,
                    "dedupe": dedupe,
                    "rows": rows,
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        if request_id is not None
        else None
    )
    for payload in rows:
        # Prevent payloads from redirecting ownership or enabling network effects
        # while holding the SQLite write transaction.
        if "question_id" in payload or "archive_url_snapshot" in payload:
            raise ValueError("source payload cannot override import ownership")
    imported = []
    duplicates = []
    with ledger.transaction(immediate=True) as conn:
        ledger.get_question(question_id)
        if request_id is not None and digest is not None:
            ensure_receipts(conn)
            prior = read_receipt(
                ledger,
                conn,
                question_id=question_id,
                request_id=request_id,
                digest=digest,
            )
            if prior is not None:
                indices = prior.batch_indices
                if indices is None or len(indices.imported) + len(
                    indices.duplicates
                ) != len(rows):
                    raise ValueError("invalid source batch receipt")
                return SourceBatchResult(
                    tuple(
                        ImportedSourceRow(index, item)
                        for index, item in zip(indices.imported, prior.evidence)
                    ),
                    indices.duplicates,
                )
        plan = prepare_source_import(
            rows, ledger.list_evidence(question_id) if dedupe else (), dedupe=dedupe
        )
        for decision in plan.rows:
            if decision.disposition == "rejected":
                raise SourceRevisionConflict(decision.index, decision.entry_id or "")
        for decision in plan.rows:
            index = decision.index
            if decision.disposition == "duplicate":
                duplicates.append(index)
                continue
            evidence = ledger.add_evidence(
                question_id=question_id, archive_url_snapshot=False, **rows[index]
            )
            imported.append(ImportedSourceRow(index, evidence))
        if request_id is not None and digest is not None:
            write_receipt(
                conn,
                question_id=question_id,
                request_id=request_id,
                digest=digest,
                receipt=ImportReceipt(
                    [row.evidence for row in imported],
                    [],
                    BatchIndices(
                        tuple(row.index for row in imported), tuple(duplicates)
                    ),
                ),
            )
    return SourceBatchResult(tuple(imported), tuple(duplicates))
