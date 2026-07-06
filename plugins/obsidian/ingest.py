"""Vault → agent: operator note deltas ingested AS EVIDENCE, triage-gated.

The other half of the collaboration loop. The operator annotates the synced
concept pages in Obsidian; this module detects the deltas (via the manifest's
operator-layer signatures), routes each to its question (the page's
``question_id`` frontmatter), and pushes the note through the SAME triage
machinery any other reading passes:

* every delta is labeled by :func:`forecasting.triage.triage_candidates`
  (runner injected — tests use a fake, the tool wires the real cheap model)
  and persisted as ``triage_labels`` staging rows;
* the held-out trust gate decides FILTER authority: in ``suggest_only`` mode a
  skip-labeled note is surfaced for review (never silently dropped, never
  imported); in trusted ``auto`` mode skips are filtered (still staged);
* keep/skim verdicts land through ``ledger.add_evidence`` — the one gated
  entry point — with provenance ``operator-note:<page>`` and the page's REAL
  modified time as the epistemic timestamp (``published_at``/``available_at``;
  ``captured_at`` stays ledger-capture time by schema contract, and the mtime
  additionally rides ``metadata.page_modified_at``).

Nothing here bypasses a gate: no direct SQL, no snapshot writes, no rubric
override. ``ingested_operator_sha`` in the manifest is the high-water mark so
an already-ingested note is not re-ingested until the operator edits again.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Callable

from plugins.obsidian.manifest import (
    compute_deltas,
    load_manifest,
    mark_ingested,
    save_manifest,
    split_note,
)

OPERATOR_SOURCE_TYPE = "operator_note"
_MIN_DELTA_CHARS = 12  # ignore whitespace-level noise

_FRONT_KEY_RE = re.compile(r"^(question_id):\s*(\S+)\s*$", re.MULTILINE)


def _mtime_iso(mtime: float) -> str:
    return _dt.datetime.fromtimestamp(mtime, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _page_question_id(text: str) -> str | None:
    layers = split_note(text)
    match = _FRONT_KEY_RE.search(layers["frontmatter"])
    return match.group(2) if match else None


def collect_operator_deltas(
    vault: Path, manifest: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Operator-authored deltas awaiting ingestion, routed by question_id.

    Skips deltas already ingested (``ingested_operator_sha`` high-water mark)
    and whitespace-level noise. Pages with no question mapping are returned
    with ``question_id=None`` — the caller REPORTS them, never guesses.
    """
    manifest = manifest if manifest is not None else load_manifest(vault)
    pages: dict[str, Any] = manifest.get("pages") or {}
    deltas = compute_deltas(vault, manifest)
    out: list[dict[str, Any]] = []
    from plugins.obsidian.wiki import is_tombstone_text

    for kind in ("operator_edited", "operator_created"):
        for record in deltas[kind]:
            rel = record["path"]
            path = vault / rel
            text = path.read_text(encoding="utf-8", errors="replace")
            if is_tombstone_text(text):
                continue  # a prune artifact, never operator evidence
            layers = split_note(text)
            operator_text = layers["operator"]
            if len(operator_text.strip()) < _MIN_DELTA_CHARS:
                continue
            entry = pages.get(rel) or {}
            if entry.get("ingested_operator_sha") == record["operator_sha"]:
                continue
            out.append(
                {
                    "path": rel,
                    "kind": kind,
                    "question_id": _page_question_id(text),
                    "operator_text": operator_text,
                    "operator_sha": record["operator_sha"],
                    "mtime": record["mtime"],
                    "modified_at": _mtime_iso(record["mtime"]),
                }
            )
    return out


def _delta_candidate(delta: dict[str, Any]) -> dict[str, Any]:
    ref = f"operator-note:{delta['path']}"
    title = Path(delta["path"]).stem
    return {
        "candidate_ref": ref,
        "id": ref,
        "title": f"Operator note on {title}",
        "summary": delta["operator_text"][:1200],
        "source_type": OPERATOR_SOURCE_TYPE,
        "source": ref,
    }


def ingest_operator_notes(
    vault: Path,
    *,
    db: str | None = None,
    runner: Callable[[str, str, str], str] | None = None,
    model: str | None = None,
    question_id: str | None = None,
    dry_run: bool = False,
    trust_threshold: float = 0.8,
    trust_min_sample: int = 20,
) -> dict[str, Any]:
    """Ingest operator note deltas as triage-gated evidence. Returns a report.

    ``dry_run`` lists the pending deltas without spending a model call or
    writing anything (ledger or manifest).
    """
    from forecasting import triage as triage_mod
    from forecasting.ledger import ForecastLedger
    from forecasting.models import LedgerNotFoundError

    manifest = load_manifest(vault)
    deltas = collect_operator_deltas(vault, manifest)
    if question_id:
        deltas = [d for d in deltas if d.get("question_id") == question_id]

    report: dict[str, Any] = {
        "vault": str(vault),
        "dry_run": bool(dry_run),
        "pending": len(deltas),
        "ingested": [],
        "needs_review": [],
        "filtered": [],
        "unmapped": [],
    }
    if dry_run or not deltas:
        report["deltas"] = [
            {k: d[k] for k in ("path", "kind", "question_id", "modified_at")}
            for d in deltas
        ]
        return report

    ledger = ForecastLedger(db)
    gate = triage_mod.build_triage_trust_gate(
        ledger, threshold=trust_threshold, min_sample=trust_min_sample
    )
    report["triage_gate_mode"] = gate.get("mode")

    if runner is None:
        raise ValueError(
            "ingest_operator_notes requires a triage runner (the tool wires the "
            "real cheap-model caller; tests inject a fake)"
        )
    resolved_model = model or "triage-default"

    by_question: dict[str | None, list[dict[str, Any]]] = {}
    for delta in deltas:
        by_question.setdefault(delta.get("question_id"), []).append(delta)

    for qid, question_deltas in by_question.items():
        if not qid:
            report["unmapped"] += [
                {"path": d["path"], "reason": "no question_id frontmatter"}
                for d in question_deltas
            ]
            continue
        try:
            question = ledger.get_question(qid)
        except LedgerNotFoundError:
            report["unmapped"] += [
                {"path": d["path"], "reason": f"question not found: {qid}"}
                for d in question_deltas
            ]
            continue

        rubric = triage_mod.active_rubric_for_question(ledger, question)
        candidates = [_delta_candidate(d) for d in question_deltas]
        verdicts = triage_mod.triage_candidates(
            candidates, runner=runner, model=resolved_model, rubric=rubric
        )
        staged = ledger.record_triage_labels(question_id=qid, verdicts=verdicts)
        staged_by_ref = {row.get("candidate_ref"): row for row in staged}

        for delta, verdict in zip(question_deltas, verdicts):
            ref = f"operator-note:{delta['path']}"
            staged_row = staged_by_ref.get(ref) or {}
            entry = {
                "path": delta["path"],
                "question_id": qid,
                "triage_label": verdict.get("triage_label"),
                "verdict": verdict.get("verdict"),
                "label_id": staged_row.get("id"),
            }
            if verdict.get("verdict") in ("keep", "skim"):
                evidence = ledger.add_evidence(
                    question_id=qid,
                    source_or_note=delta["operator_text"],
                    claim=f"Operator note on {Path(delta['path']).stem}",
                    summary=delta["operator_text"][:600],
                    source_name=ref,
                    source_type=OPERATOR_SOURCE_TYPE,
                    published_at=delta["modified_at"],
                    available_at=delta["modified_at"],
                    stance="context",
                    claim_type="opinion",
                    archive_url_snapshot=False,
                    metadata={
                        "provenance": ref,
                        "vault_page": delta["path"],
                        "page_modified_at": delta["modified_at"],
                        "operator_sha": delta["operator_sha"],
                        "triage_label": verdict.get("triage_label"),
                        "triage_gate_mode": gate.get("mode"),
                    },
                )
                entry["evidence_id"] = evidence.id
                report["ingested"].append(entry)
            elif gate.get("can_auto_filter"):
                report["filtered"].append(entry)
            else:
                # suggest_only: the labeler is not trusted to drop a reading —
                # surface it for operator review instead of silently skipping.
                entry["reason"] = (
                    "labeled skip while the triage gate is suggest_only — "
                    "review the staged label (relabel_route) or edit the note"
                )
                report["needs_review"].append(entry)
            mark_ingested(manifest, delta["path"], delta["operator_sha"])

    save_manifest(vault, manifest)
    return report


__all__ = [
    "OPERATOR_SOURCE_TYPE",
    "collect_operator_deltas",
    "ingest_operator_notes",
]
