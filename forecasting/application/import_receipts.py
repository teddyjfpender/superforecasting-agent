"""Transactional source-import receipts, shared by evidence acquisition owners."""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem


@dataclass(frozen=True)
class ImportReceipt:
    evidence: list[EvidenceItem]
    comparisons: list[dict[str, Any]]


def ensure_receipts(conn: sqlite3.Connection) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS forecast_source_import_receipts (
        question_id TEXT NOT NULL, request_id TEXT NOT NULL,
        request_digest TEXT NOT NULL, evidence_ids TEXT NOT NULL,
        comparison_ids TEXT NOT NULL DEFAULT '[]',
        PRIMARY KEY (question_id, request_id)
    )""")
    # Existing FRED receipts are v1 evidence-only records; preserve their digest.
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(forecast_source_import_receipts)")
    }
    if "comparison_ids" not in columns:
        conn.execute(
            "ALTER TABLE forecast_source_import_receipts ADD COLUMN comparison_ids TEXT NOT NULL DEFAULT '[]'"
        )


def read_receipt(
    ledger: ForecastLedger,
    conn: sqlite3.Connection,
    *,
    question_id: str,
    request_id: str,
    digest: str,
) -> ImportReceipt | None:
    row = conn.execute(
        "SELECT request_digest,evidence_ids,comparison_ids FROM forecast_source_import_receipts "
        "WHERE question_id=? AND request_id=?",
        (question_id, request_id),
    ).fetchone()
    if row is None:
        return None
    if row["request_digest"] != digest:
        raise ValueError("import request identifier reused for different input")

    def ids(raw: str) -> list[str]:
        values = json.loads(raw)
        if not isinstance(values, list) or not all(
            isinstance(item, str) for item in values
        ):
            raise ValueError("invalid import receipt")
        return values

    evidence = [ledger.get_evidence(item) for item in ids(row["evidence_ids"])]
    comparisons = [
        ledger.get_baseline_comparison(item) for item in ids(row["comparison_ids"])
    ]
    if any(item.question_id != question_id for item in evidence) or any(
        item["question_id"] != question_id for item in comparisons
    ):
        raise ValueError("import receipt refers to another question")
    return ImportReceipt(evidence, comparisons)


def write_receipt(
    conn: sqlite3.Connection,
    *,
    question_id: str,
    request_id: str,
    digest: str,
    receipt: ImportReceipt,
) -> None:
    conn.execute(
        "INSERT INTO forecast_source_import_receipts "
        "(question_id,request_id,request_digest,evidence_ids,comparison_ids) VALUES (?,?,?,?,?)",
        (
            question_id,
            request_id,
            digest,
            json.dumps([item.id for item in receipt.evidence]),
            json.dumps([item["id"] for item in receipt.comparisons]),
        ),
    )
