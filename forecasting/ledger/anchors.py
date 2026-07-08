"""Outside-view anchor re-linking — the mechanical orphaned-anchor remediation.

A reference class can EXIST on a question yet be ABSENT from its current
snapshot's ``reference_class_refs`` (the two are separate: the durable class row
vs. the per-snapshot link). That gap is the *orphaned-anchor* defect — the
question carries a real base rate the forecast reasons from, but the snapshot
does not cite it, so the outside-view anchor is invisible to the desk, the
dashboards, and (on the next re-forecast) the anchor gate.

This leaf does the mechanical fix: re-attach a question's EXISTING active
reference classes to its current snapshot's refs. It NEVER creates a class and
NEVER changes a probability — it only links what already exists. Ambiguity is
refused, not guessed: when a question carries active reference classes under more
than one distinct NAME (genuinely different outside views), the mechanical path
cannot know which is *the* anchor, so it SKIPS and reports for a human. Same-name
duplicates are unambiguous (one conceptual class) and are linked.

Gated like every writer (``allow_ledger_writes``); the scan is read-only, the
apply is a single blessed UPDATE per snapshot. Pure-ish (stdlib + the ledger
handle) so the scan is unit-testable against a temp ledger.
"""

from __future__ import annotations

import json
from typing import Any

from forecasting.ledger.gate import allow_ledger_writes
from forecasting.models import LedgerNotFoundError


def _norm_name(name: Any) -> str:
    return str(name or "").strip().lower()


def _active_reference_classes(ledger, question_id: str) -> list[dict[str, Any]]:
    """Active reference classes for a question (status ``active`` or unset)."""
    try:
        rows = ledger.list_reference_classes(question_id)
    except Exception:
        return []
    return [r for r in rows if (r.get("status") or "active") == "active"]


def set_snapshot_reference_class_refs(ledger, snapshot_id: str, refs: list[str]) -> list[str]:
    """Blessed writer: set a snapshot's ``reference_class_refs`` to ``refs``.

    UPDATE-only — never touches the probability, rationale, or any gated field.
    De-duplicates while preserving order and rejects non-string entries. Returns
    the stored list. Raises ``LedgerNotFoundError`` when the snapshot is unknown.
    """
    seen: set[str] = set()
    clean: list[str] = []
    for ref in refs or []:
        rid = str(ref).strip()
        if rid and rid not in seen:
            seen.add(rid)
            clean.append(rid)
    with allow_ledger_writes("set_snapshot_reference_class_refs"), ledger._connect() as conn:
        row = conn.execute(
            "SELECT forecast_id FROM forecast_snapshots WHERE forecast_id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"snapshot not found: {snapshot_id}")
        conn.execute(
            "UPDATE forecast_snapshots SET reference_class_refs = ? WHERE forecast_id = ?",
            (json.dumps(clean), snapshot_id),
        )
    return clean


def _scan_question(ledger, question_id: str) -> dict[str, Any] | None:
    """Classify one question's anchor-link state, or None when it is not a
    candidate (no current snapshot, or no active reference class exists)."""
    try:
        snap = ledger.get_current_snapshot(question_id)
    except Exception:
        snap = None
    if snap is None:
        return None
    active = _active_reference_classes(ledger, question_id)
    if not active:
        return None  # nothing to link — not an orphaned anchor
    active_ids = [r["id"] for r in active]
    active_id_set = set(active_ids)
    current_refs = [str(x) for x in (getattr(snap, "reference_class_refs", None) or [])]
    linked_active = [r for r in current_refs if r in active_id_set]
    distinct_names = sorted({_norm_name(r.get("name")) for r in active})
    title = None
    try:
        title = ledger.get_question(question_id).title
    except Exception:
        title = None
    row: dict[str, Any] = {
        "question_id": question_id,
        "title": title,
        "snapshot_id": getattr(snap, "forecast_id", None),
        "active_rc_ids": active_ids,
        "active_rc_names": [r.get("name") for r in active],
        "distinct_name_count": len(distinct_names),
        "current_refs": current_refs,
    }
    if linked_active:
        row["status"] = "linked"  # already cites an active anchor — nothing to do
        return row
    # Orphaned: active class(es) exist but none are linked on the current snapshot.
    if len(distinct_names) > 1:
        row["status"] = "ambiguous"  # >1 distinct outside view — a human must pick
        return row
    row["status"] = "relinkable"
    # Union of any pre-existing refs with every active class id (same-name dupes
    # included: they are one conceptual anchor, harmless to cite together).
    row["proposed_refs"] = current_refs + active_ids
    return row


def relink_orphaned_anchors(
    ledger,
    *,
    question_ids: list[str] | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    """Scan questions for the orphaned-anchor defect and (optionally) re-link.

    An *orphan* is a question whose current snapshot links NONE of its active
    reference classes though at least one exists. A *relinkable* orphan carries
    active classes under a single distinct name; an *ambiguous* orphan carries
    more than one distinct name and is skipped (reported for a human). With
    ``apply`` the relinkable orphans have their existing active class ids stamped
    onto the current snapshot's refs. Read-only unless ``apply``.
    """
    if question_ids is None:
        try:
            question_ids = [q.id for q in ledger.list_questions(status="active")]
        except Exception:
            question_ids = []
    scanned = 0
    relinkable: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    already: list[dict[str, Any]] = []
    for qid in question_ids or []:
        row = _scan_question(ledger, qid)
        if row is None:
            continue
        scanned += 1
        status = row["status"]
        if status == "relinkable":
            relinkable.append(row)
        elif status == "ambiguous":
            ambiguous.append(row)
        elif status == "linked":
            already.append(row)
    applied = 0
    if apply:
        for row in relinkable:
            try:
                set_snapshot_reference_class_refs(ledger, row["snapshot_id"], row["proposed_refs"])
                row["applied"] = True
                applied += 1
            except Exception as exc:  # keep going; report the failure
                row["applied"] = False
                row["error"] = str(exc)
    return {
        "scanned_with_reference_class": scanned,
        "relinkable": len(relinkable),
        "ambiguous": len(ambiguous),
        "already_linked": len(already),
        "applied": applied,
        "proposals": relinkable,
        "ambiguous_detail": ambiguous,
    }
