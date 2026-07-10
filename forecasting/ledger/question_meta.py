"""Question-metadata domain (links + reference classes + assumptions + cruxes +
desk state + analyst notes) — carved from core.

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the per-question analytical metadata
table families that hang off a question but are not its forecast history:

* FORECAST LINKS: ``add_forecast_link`` / ``get_`` / ``remove_`` / ``list_`` /
  ``_forecast_link_to_dict`` plus the cross-forecast views (``shared_sources`` /
  ``related_forecast_views`` / ``build_cross_refs``);
* REFERENCE CLASSES: ``add_reference_class`` / ``delete_`` / ``update_`` / ``get_`` /
  ``list_`` / ``active_reference_class_counts``;
* ASSUMPTIONS: ``add_assumption`` / ``update_`` / ``get_`` / ``list_``;
* CRUXES: ``add_crux`` / ``get_`` / ``list_`` / ``set_crux_status`` and the panel
  promotion engine (``promote_panel_cruxes`` / ``backfill_panel_cruxes`` /
  ``crux_promotion_stats``);
* DESK STATE: ``get_desk_state`` / ``set_`` / ``transition_desk_state``;
* ANALYST NOTES: ``add_analyst_note`` / ``get_`` / ``list_`` / ``latest_analyst_note``
  / ``analyst_notes_by_question`` / ``_analyst_note_to_dict``.

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. Core-owned enum constants
(``ANALYST_NOTE_*`` / ``CRUX_*`` / ``FORECAST_LINK_TYPES`` / ``_MAX_CRUX_VARIABLE_LEN``)
and the ``_crux_text_hash`` helper are reached via the ``_core.`` call-time hop;
``_chunk_ids`` and every cross-domain read resolve through the ``ledger`` INSTANCE."""

from __future__ import annotations

import logging
from forecasting.ledger import core as _core
from forecasting.models import ASSUMPTION_STATUSES
from typing import Any
from forecasting.models import LedgerNotFoundError
from forecasting.models import REFERENCE_CLASS_STATUSES
from forecasting.models import ValidationError
from forecasting.ledger.watches import WATCH_SOURCE_ROLES
from collections import defaultdict
from forecasting.models import json_dumps
from forecasting.models import json_loads
from forecasting.models import parse_timestamp
import sqlite3
from forecasting.models import utc_now_iso
import uuid

logger = logging.getLogger(__name__)


def _forecast_link_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = json_loads(data.get("metadata"), {})
    return data


def add_forecast_link(
    ledger,
    from_question_id: str,
    to_question_id: str,
    *,
    link_type: str = "related",
    weight: float = 1.0,
    rationale: str = "",
    created_by: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a typed edge between two forecasts. Idempotent on (from, to, type).
    `related` is symmetric (the endpoints are normalized so A-B == B-A);
    `component_of` is directed (from=child, to=parent).
    """
    ledger.get_question(from_question_id)
    ledger.get_question(to_question_id)
    if from_question_id == to_question_id:
        raise ValidationError("a forecast cannot link to itself")
    if link_type not in _core.FORECAST_LINK_TYPES:
        raise ValidationError(
            f"link_type must be one of {', '.join(sorted(_core.FORECAST_LINK_TYPES))}"
        )
    if link_type == "related" and from_question_id > to_question_id:
        from_question_id, to_question_id = to_question_id, from_question_id
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM forecast_links WHERE from_question_id = ? AND to_question_id = ? AND link_type = ?",
            (from_question_id, to_question_id, link_type),
        ).fetchone()
        if existing is not None:
            return ledger.get_forecast_link(existing["id"])
        link_id = f"fl_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO forecast_links (
                id, from_question_id, to_question_id, link_type, weight,
                rationale, created_by, created_at, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                link_id,
                from_question_id,
                to_question_id,
                link_type,
                float(weight),
                rationale,
                created_by,
                utc_now_iso(),
                json_dumps(metadata or {}),
            ),
        )
    return ledger.get_forecast_link(link_id)


def get_forecast_link(ledger, link_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM forecast_links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"forecast link not found: {link_id}")
    return ledger._forecast_link_to_dict(row)


def remove_forecast_link(
    ledger,
    from_question_id: str,
    to_question_id: str,
    *,
    link_type: str | None = None,
) -> int:
    """Delete the edge(s) between two questions (either ordering). Returns the count."""
    sql = (
        "DELETE FROM forecast_links WHERE "
        "((from_question_id = ? AND to_question_id = ?) OR (from_question_id = ? AND to_question_id = ?))"
    )
    params: list[Any] = [from_question_id, to_question_id, to_question_id, from_question_id]
    if link_type is not None:
        sql += " AND link_type = ?"
        params.append(link_type)
    with ledger._connect() as conn:
        cur = conn.execute(sql, params)
        return int(cur.rowcount or 0)


def list_forecast_links(
    ledger,
    question_id: str,
    *,
    link_type: str | None = None,
    direction: str = "both",
    status: str | None = None,  # accepted for signature parity; links have no status
) -> list[dict[str, Any]]:
    if direction == "outgoing":
        clause, params = "from_question_id = ?", [question_id]
    elif direction == "incoming":
        clause, params = "to_question_id = ?", [question_id]
    else:
        clause, params = "(from_question_id = ? OR to_question_id = ?)", [question_id, question_id]
    sql = f"SELECT * FROM forecast_links WHERE {clause}"
    if link_type is not None:
        sql += " AND link_type = ?"
        params.append(link_type)
    sql += " ORDER BY created_at DESC"
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [ledger._forecast_link_to_dict(row) for row in rows]


def shared_sources(ledger, question_id: str, other_id: str) -> list[dict[str, Any]]:
    """Overlapping watched sources / evidence between two questions (read-only).
    Used purely to FLAG possible non-independence; never merges or imports.
    """
    def _signatures(qid: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for ws in ledger.list_watched_sources(scope_type="question", scope_ref=qid, status="active"):
            source = str(ws.get("source") or "").strip().lower()
            stype = str(ws.get("source_type") or "").strip().lower()
            if source:
                out[f"{stype}:{source}"] = {"source_type": stype, "source": source, "kind": "watched_source"}
        for item in ledger.list_evidence(qid):
            stype = str(getattr(item, "source_type", "") or "").strip().lower()
            ident = str(getattr(item, "source_url", None) or getattr(item, "source_name", None) or "").strip().lower()
            if ident:
                out.setdefault(f"{stype}:{ident}", {"source_type": stype, "source": ident, "kind": "evidence"})
        return out
    mine = _signatures(question_id)
    theirs = _signatures(other_id)
    shared: list[dict[str, Any]] = []
    for signature in mine.keys() & theirs.keys():
        shared.append({"signature": signature, "shared_with": other_id, **mine[signature]})
    shared.sort(key=lambda s: s["signature"])
    return shared


def related_forecast_views(
    ledger,
    question: Any,
    *,
    # Display default: the links/show surfaces use this and must show ALL
    # explicit links (e.g. a 7-child component_of master), so the default is
    # generous. The agent cross-pollination CONTEXT passes an explicit
    # limit=5 (protocol.py) to stay within its context budget.
    limit: int = 25,
    overlap_threshold: float = 0.2,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve the forecasts related to `question` and pull their world-views.
    Unions explicit links with auto matches (same domain + topic Jaccard
    overlap). Each entry carries only the relative's current forecast, latest
    analyst-note view, and top drivers. Also returns the de-duplicated list of
    overlapping source signatures for the independence flag. Never merges
    evidence — world-views only.
    """
    if isinstance(question, str):
        question = ledger.get_question(question)
    question_id = question.id
    base_topics = {str(t).lower() for t in (question.topics or [])}
    # relationship from the perspective of `question`.
    relatives: dict[str, dict[str, Any]] = {}
    def _record(other_id: str, *, relationship: str, link_type: str, overlap: float,
                link_id: str | None = None, rationale: str = "") -> None:
        if other_id == question_id or other_id in relatives:
            return
        relatives[other_id] = {
            "id": other_id,
            "relationship": relationship,
            "link_type": link_type,
            "link_label": link_type if link_type != "auto" else None,
            "direction": "auto" if link_type == "auto" else "explicit",
            "overlap_score": round(overlap, 3),
            "link_id": link_id,
            "rationale": rationale,
        }
    for link in ledger.list_forecast_links(question_id, direction="both"):
        outgoing = link["from_question_id"] == question_id
        other_id = link["to_question_id"] if outgoing else link["from_question_id"]
        if link["link_type"] == "component_of":
            # from=child, to=parent. If we are `from`, the other is our parent.
            relationship = "parent" if outgoing else "child"
        else:
            relationship = "correlated_sibling"
        _record(
            other_id,
            relationship=relationship,
            link_type=link["link_type"],
            overlap=1.0,
            link_id=link["id"],
            rationale=link.get("rationale", ""),
        )
    explicit_ids = set(relatives.keys())
    if question.domain and base_topics:
        for candidate in ledger.list_questions(domain=question.domain):
            if candidate.id == question_id or candidate.id in explicit_ids:
                continue
            other_topics = {str(t).lower() for t in (candidate.topics or [])}
            union = base_topics | other_topics
            jaccard = len(base_topics & other_topics) / len(union) if union else 0.0
            if jaccard >= overlap_threshold:
                _record(candidate.id, relationship="correlated_sibling", link_type="auto", overlap=jaccard)
    # Explicit first, then auto by overlap; truncate.
    ordered = sorted(
        relatives.values(),
        key=lambda r: (r["link_type"] == "auto", -r["overlap_score"]),
    )[: max(0, limit)]
    shared_labels: list[str] = []
    seen_labels: set[str] = set()
    for rel in ordered:
        other_id = rel["id"]
        try:
            other_q = ledger.get_question(other_id)
            rel["title"] = other_q.title
        except LedgerNotFoundError:
            rel["title"] = other_id
        snap = ledger.get_current_snapshot(other_id)
        rel["probability_or_distribution"] = snap.probability_or_distribution if snap else None
        rel["as_of"] = snap.as_of if snap else None
        rel["reasons_up"] = list(snap.reasons_up or [])[:3] if snap else []
        rel["reasons_down"] = list(snap.reasons_down or [])[:3] if snap else []
        note = ledger.latest_analyst_note(other_id)
        rel["headline"] = note.get("headline") if note else None
        rel["be_aware"] = note.get("be_aware") if note else None
        rel["stance"] = note.get("stance") if note else None
        rel["verdict"] = note.get("verdict") if note else None
        for shared in ledger.shared_sources(question_id, other_id):
            if shared["signature"] not in seen_labels:
                seen_labels.add(shared["signature"])
                shared_labels.append(shared["signature"])
    return ordered, shared_labels


def build_cross_refs(ledger, question: Any, *, advisory_only: bool = False) -> dict[str, Any]:
    """The provenance record stamped onto a snapshot: which related forecasts
    informed it (server-side, never trusting model echo). Empty when there are
    no relatives. ``advisory_only`` marks the deterministic-refresh case where
    the number is NOT derived from siblings."""
    related, shared = ledger.related_forecast_views(question, limit=5)
    if not related and not shared:
        return {}
    return {
        "informed_by": [rel["id"] for rel in related],
        "explicit_links": [rel["id"] for rel in related if rel.get("link_type") != "auto"],
        "auto_related": [rel["id"] for rel in related if rel.get("link_type") == "auto"],
        "shared_sources": [{"source": s, "note": "may not be independent"} for s in shared],
        "as_of": utc_now_iso(),
        "advisory_only": bool(advisory_only),
    }


def add_reference_class(
    ledger,
    *,
    question_id: str,
    name: str,
    inclusion_criteria: str,
    exclusion_criteria: str = "",
    base_rate: float | None = None,
    base_rate_uncertainty: float | None = None,
    source_refs: list[str] | None = None,
    check_cadence: str | None = None,
    notes: str | None = None,
    sample_size: int | None = None,
) -> dict[str, Any]:
    ledger.get_question(question_id)
    if not name.strip():
        raise ValidationError("reference class name is required")
    if not inclusion_criteria.strip():
        raise ValidationError("reference class inclusion criteria are required")
    if base_rate is not None and not (0 <= base_rate <= 1):
        raise ValidationError("base_rate must be between 0 and 1")
    if base_rate_uncertainty is not None and base_rate_uncertainty < 0:
        raise ValidationError("base_rate_uncertainty must be non-negative")
    if sample_size is not None and int(sample_size) < 0:
        raise ValidationError("sample_size (n observations behind the base rate) must be non-negative")
    reference_class_id = f"rc_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO reference_classes (
                id, question_id, name, inclusion_criteria, exclusion_criteria,
                base_rate, base_rate_uncertainty, source_refs, created_at,
                check_cadence, notes, sample_size
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_class_id,
                question_id,
                name.strip(),
                inclusion_criteria.strip(),
                exclusion_criteria,
                base_rate,
                base_rate_uncertainty,
                json_dumps(source_refs or []),
                utc_now_iso(),
                check_cadence,
                notes,
                int(sample_size) if sample_size is not None else None,
            ),
        )
    return ledger.get_reference_class(reference_class_id)


def delete_reference_class(ledger, reference_class_id: str) -> None:
    """Hard-delete a reference class. Intended for compensating rollback of an inline
    reference class created during a forecast commit that was then rejected — so a
    refused snapshot never orphans an unlinked anchor."""
    with ledger._connect() as conn:
        conn.execute("DELETE FROM reference_classes WHERE id = ?", (reference_class_id,))


def update_reference_class(
    ledger,
    reference_class_id: str,
    *,
    status: str | None = None,
    last_checked_at: str | None = None,
    invalidated_at: str | None = None,
    check_cadence: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    current = ledger.get_reference_class(reference_class_id)
    new_status = status or current["status"]
    if new_status not in REFERENCE_CLASS_STATUSES:
        raise ValidationError(
            f"reference class status must be one of {', '.join(sorted(REFERENCE_CLASS_STATUSES))}"
        )
    checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
    invalidated = (
        parse_timestamp(invalidated_at, field_name="invalidated_at")
        if invalidated_at
        else current["invalidated_at"]
    )
    if new_status == "invalidated" and invalidated is None:
        invalidated = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE reference_classes
            SET status = ?, last_checked_at = ?, invalidated_at = ?,
                check_cadence = COALESCE(?, check_cadence),
                notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (new_status, checked, invalidated, check_cadence, notes, reference_class_id),
        )
    return ledger.get_reference_class(reference_class_id)


def get_reference_class(ledger, reference_class_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM reference_classes WHERE id = ?",
            (reference_class_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"reference class not found: {reference_class_id}")
    data = dict(row)
    data["source_refs"] = json_loads(data["source_refs"], [])
    return data


def list_reference_classes(ledger, question_id: str) -> list[dict[str, Any]]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reference_classes WHERE question_id = ? ORDER BY created_at ASC",
            (question_id,),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["source_refs"] = json_loads(data["source_refs"], [])
        result.append(data)
    return result


def active_reference_class_counts(ledger, question_ids: list[str]) -> dict[str, int]:
    """question_id -> count of its ACTIVE reference classes.
    ONE batched ``GROUP BY`` per id-chunk — the batched equivalent of
    ``len([rc for rc in list_reference_classes(qid) if rc['status']=='active'])``.
    Ids with no active class are absent (caller defaults to 0)."""
    out: dict[str, int] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT question_id, COUNT(*) AS n FROM reference_classes "
                f"WHERE status = 'active' AND question_id IN ({placeholders}) "
                f"GROUP BY question_id",
                chunk,
            ).fetchall()
        for row in rows:
            out[row["question_id"]] = int(row["n"])
    return out


def add_assumption(
    ledger,
    *,
    question_id: str,
    text: str,
    status: str = "active",
    check_cadence: str | None = None,
    evidence_refs: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    ledger.get_question(question_id)
    if not text.strip():
        raise ValidationError("assumption text is required")
    if status not in ASSUMPTION_STATUSES:
        raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
    assumption_id = f"as_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO assumptions (
                id, question_id, text, status, created_at,
                check_cadence, evidence_refs, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assumption_id,
                question_id,
                text.strip(),
                status,
                utc_now_iso(),
                check_cadence,
                json_dumps(evidence_refs or []),
                notes,
            ),
        )
    return ledger.get_assumption(assumption_id)


def update_assumption(
    ledger,
    assumption_id: str,
    *,
    status: str | None = None,
    last_checked_at: str | None = None,
    invalidated_at: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    current = ledger.get_assumption(assumption_id)
    new_status = status or current["status"]
    if new_status not in ASSUMPTION_STATUSES:
        raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
    checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
    invalidated = (
        parse_timestamp(invalidated_at, field_name="invalidated_at")
        if invalidated_at
        else current["invalidated_at"]
    )
    if new_status == "invalidated" and invalidated is None:
        invalidated = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE assumptions
            SET status = ?, last_checked_at = ?, invalidated_at = ?, notes = COALESCE(?, notes)
            WHERE id = ?
            """,
            (new_status, checked, invalidated, notes, assumption_id),
        )
    return ledger.get_assumption(assumption_id)


def get_assumption(ledger, assumption_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (assumption_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"assumption not found: {assumption_id}")
    data = dict(row)
    data["evidence_refs"] = json_loads(data["evidence_refs"], [])
    return data


def list_assumptions(ledger, question_id: str) -> list[dict[str, Any]]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM assumptions WHERE question_id = ? ORDER BY created_at ASC",
            (question_id,),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["evidence_refs"] = json_loads(data["evidence_refs"], [])
        result.append(data)
    return result


def add_crux(
    ledger,
    *,
    question_id: str,
    crux_variable: str,
    preferred_roles: list[str] | None = None,
    materiality: str = "medium",
    status: str = "missing",
    notes: str | None = None,
) -> dict[str, Any]:
    """Register a decisive variable the resolution hinges on, with the source
    roles that would satisfy it + its current evidence status. Idempotent on
    (question_id, crux_variable): re-adding updates the existing crux."""
    ledger.get_question(question_id)
    crux_variable = crux_variable.strip()
    if not crux_variable:
        raise ValidationError("crux_variable is required")
    if materiality not in _core.CRUX_MATERIALITY:
        raise ValidationError("materiality must be one of: " + ", ".join(sorted(_core.CRUX_MATERIALITY)))
    if status not in _core.CRUX_STATUS:
        raise ValidationError("status must be one of: " + ", ".join(sorted(_core.CRUX_STATUS)))
    roles = list(preferred_roles or [])
    for role in roles:
        if role not in WATCH_SOURCE_ROLES:
            raise ValidationError("preferred_roles must be drawn from: " + ", ".join(sorted(WATCH_SOURCE_ROLES)))
    now = utc_now_iso()
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM question_cruxes WHERE question_id = ? AND crux_variable = ?",
            (question_id, crux_variable),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE question_cruxes SET preferred_roles = ?, materiality = ?, status = ?, notes = ?, updated_at = ? WHERE id = ?",
                (json_dumps(roles), materiality, status, notes, now, existing["id"]),
            )
            crux_id = existing["id"]
        else:
            crux_id = f"cx_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO question_cruxes (id, question_id, crux_variable, preferred_roles, materiality, status, notes, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (crux_id, question_id, crux_variable, json_dumps(roles), materiality, status, notes, now, now),
            )
    return ledger.get_crux(crux_id)


def get_crux(ledger, crux_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM question_cruxes WHERE id = ?", (crux_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"crux not found: {crux_id}")
    data = dict(row)
    data["preferred_roles"] = json_loads(data["preferred_roles"], [])
    return data


def list_cruxes(ledger, question_id: str) -> list[dict[str, Any]]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM question_cruxes WHERE question_id = ? ORDER BY created_at ASC", (question_id,)
        ).fetchall()
    out = []
    for row in rows:
        data = dict(row)
        data["preferred_roles"] = json_loads(data["preferred_roles"], [])
        out.append(data)
    return out


def set_crux_status(ledger, crux_id: str, status: str) -> dict[str, Any]:
    if status not in _core.CRUX_STATUS:
        raise ValidationError("status must be one of: " + ", ".join(sorted(_core.CRUX_STATUS)))
    ledger.get_crux(crux_id)
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE question_cruxes SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), crux_id),
        )
    return ledger.get_crux(crux_id)


def promote_panel_cruxes(
    ledger,
    *,
    question_id: str,
    panel_run_id: str,
    estimates: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Promote the free-text ``crux`` each panelist named into the first-class,
    queryable ``question_cruxes`` table (finding #4: 271 cruxes died inside panel
    blobs while ``question_cruxes`` had 0 rows).
    Deduped by text-hash BOTH within the panel (many panelists name the same
    uncertainty) AND against cruxes already on the question — an EXISTING crux is
    left untouched (never re-stamped back to ``status='missing'``, so an operator's
    hand-set status/materiality survives a re-run). New cruxes are inserted via the
    idempotent :meth:`add_crux`, linked to the panel run in ``notes``. ``dry_run``
    counts what WOULD be promoted without writing.
    Returns ``{"promoted", "skipped_existing", "candidates", "dry_run",
    "promoted_variables", "panel_run_id"}``.
    """
    if estimates is None:
        estimates = ledger.get_panel_run(panel_run_id).get("estimates") or []
    # 1) distinct candidate cruxes within this panel (text-hash dedupe).
    candidates: list[str] = []
    seen: set[str] = set()
    for est in estimates:
        raw = str((est or {}).get("crux") or "").strip()
        if not raw:
            continue
        key = _core._crux_text_hash(raw)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(raw[:_core._MAX_CRUX_VARIABLE_LEN])
    # 2) skip any already-promoted crux (by text-hash) so a re-run is a no-op.
    try:
        existing_hashes = {
            _core._crux_text_hash(c["crux_variable"]) for c in ledger.list_cruxes(question_id)
        }
    except LedgerNotFoundError:
        existing_hashes = set()
    promoted: list[str] = []
    skipped = 0
    for raw in candidates:
        if _core._crux_text_hash(raw) in existing_hashes:
            skipped += 1
            continue
        if not dry_run:
            ledger.add_crux(
                question_id=question_id,
                crux_variable=raw,
                materiality="medium",
                status="missing",
                notes=f"promoted from panel {panel_run_id}",
            )
        existing_hashes.add(_core._crux_text_hash(raw))
        promoted.append(raw)
    return {
        "question_id": question_id,
        "panel_run_id": panel_run_id,
        "candidates": len(candidates),
        "promoted": len(promoted),
        "skipped_existing": skipped,
        "dry_run": dry_run,
        "promoted_variables": promoted,
    }


def backfill_panel_cruxes(ledger, *, dry_run: bool = True) -> dict[str, Any]:
    """One-shot promotion of EVERY existing panel run's cruxes into
    ``question_cruxes`` (finding #4 backfill of the 271 pre-existing cruxes).
    DRY-RUN by default: it reports the counts that WOULD be promoted without
    writing. Pass ``dry_run=False`` to apply. Idempotent — a second apply run
    promotes nothing new (every crux is already present, so it is counted as
    ``skipped_existing``). Fail-soft per panel: a single bad run is skipped, never
    aborting the whole backfill.
    """
    runs_scanned = 0
    panels_with_cruxes = 0
    promoted = 0
    skipped_existing = 0
    candidates = 0
    for run in ledger.list_panel_runs():
        runs_scanned += 1
        try:
            res = ledger.promote_panel_cruxes(
                question_id=run["question_id"],
                panel_run_id=run["id"],
                estimates=run.get("estimates"),
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 — one bad run never aborts backfill
            logger.debug("crux backfill skipped panel %s: %r", run.get("id"), exc)
            continue
        candidates += res["candidates"]
        promoted += res["promoted"]
        skipped_existing += res["skipped_existing"]
        if res["candidates"]:
            panels_with_cruxes += 1
    return {
        "dry_run": dry_run,
        "runs_scanned": runs_scanned,
        "panels_with_cruxes": panels_with_cruxes,
        "candidate_cruxes": candidates,
        "promoted": promoted,
        "skipped_existing": skipped_existing,
    }


def crux_promotion_stats(ledger) -> dict[str, Any]:
    """Coverage of the crux-promotion path for the doctor/readiness surface:
    promoted rows (``question_cruxes``), how many came from a panel promotion,
    and how many DISTINCT panel-embedded cruxes are still un-promoted."""
    with ledger._connect() as conn:
        promoted_total = int(
            conn.execute("SELECT COUNT(*) FROM question_cruxes").fetchone()[0]
        )
        from_panels = int(
            conn.execute(
                "SELECT COUNT(*) FROM question_cruxes WHERE notes LIKE 'promoted from panel %'"
            ).fetchone()[0]
        )
        panel_crux_rows = conn.execute(
            "SELECT question_id, crux FROM panel_estimates "
            "WHERE crux IS NOT NULL AND TRIM(crux) != ''"
        ).fetchall()
        existing = conn.execute(
            "SELECT question_id, crux_variable FROM question_cruxes"
        ).fetchall()
    existing_by_q: dict[str, set[str]] = defaultdict(set)
    for row in existing:
        existing_by_q[row[0]].add(_core._crux_text_hash(row[1]))
    distinct_panel: dict[str, set[str]] = defaultdict(set)
    for row in panel_crux_rows:
        distinct_panel[row[0]].add(_core._crux_text_hash(row[1]))
    unpromoted = sum(
        len(hashes - existing_by_q.get(qid, set()))
        for qid, hashes in distinct_panel.items()
    )
    return {
        "promoted_total": promoted_total,
        "promoted_from_panels": from_panels,
        "panel_embedded_distinct": sum(len(h) for h in distinct_panel.values()),
        "unpromoted_panel_cruxes": unpromoted,
    }


def get_desk_state(ledger, key: str) -> str | None:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT value FROM desk_state WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row is not None else None


def set_desk_state(ledger, key: str, value: str | None, *, now: str | None = None) -> None:
    stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            "INSERT INTO desk_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, stamped),
        )


def transition_desk_state(
    ledger, key: str, new_value: str | None, *, now: str | None = None
) -> tuple[bool, str | None]:
    """Atomically set ``desk_state[key] = new_value`` under a write lock and
    report whether THIS call performed the change.
    Returns ``(changed, previous)``. ``changed`` is True only for the caller
    that actually moved the value; a concurrent caller that lost the race
    (``BEGIN IMMEDIATE`` serialises writers) — or a steady state where the
    stored value already equals ``new_value`` — gets ``changed=False`` and must
    not re-act. This makes a read-compare-write transition (e.g. the triage
    trust-gate mode) safe under overlapping sweeps: two sweeps can no longer
    both observe the old value and both fire the same transition alert.
    """
    stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
    conn = ledger._connect()
    try:
        conn.isolation_level = None  # take manual control of the transaction
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT value FROM desk_state WHERE key = ?", (key,)
        ).fetchone()
        prev = row["value"] if row is not None else None
        if prev == new_value:
            conn.execute("COMMIT")
            return False, prev
        conn.execute(
            "INSERT INTO desk_state (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, new_value, stamped),
        )
        conn.execute("COMMIT")
        return True, prev
    finally:
        conn.close()


def add_analyst_note(
    ledger,
    *,
    question_id: str,
    body: str,
    kind: str = "brief",
    headline: str = "",
    how_it_feels: str = "",
    how_it_thinks: str = "",
    looking_for: str = "",
    be_aware: str = "",
    as_of: str | None = None,
    forecast_id: str | None = None,
    resolution_id: str | None = None,
    stance: str | None = None,
    verdict: str | None = None,
    probability_at_write: Any | None = None,
    confidence_at_write: float | None = None,
    agent_model: str | None = None,
    prompt_version: str | None = None,
    forecasting_protocol_version: str | None = None,
    generator: str = "llm",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a time-indexed analyst write-up for a question.
    Append-only: each call is one entry in the question's prose time series.
    ``forecast_id`` chains a brief to the snapshot it annotates;
    ``resolution_id`` chains a retrospective to the resolution. Both use
    ``ON DELETE SET NULL`` so the historical record survives a later purge.
    """
    ledger.get_question(question_id)
    if kind not in _core.ANALYST_NOTE_KINDS:
        raise ValidationError(
            f"analyst note kind must be one of {', '.join(sorted(_core.ANALYST_NOTE_KINDS))}"
        )
    if not body.strip():
        raise ValidationError("analyst note body is required")
    if stance is not None and stance not in _core.ANALYST_NOTE_STANCES:
        raise ValidationError(
            f"analyst note stance must be one of {', '.join(sorted(_core.ANALYST_NOTE_STANCES))}"
        )
    if verdict is not None and verdict not in _core.ANALYST_NOTE_VERDICTS:
        raise ValidationError(
            f"analyst note verdict must be one of {', '.join(sorted(_core.ANALYST_NOTE_VERDICTS))}"
        )
    if forecast_id is not None:
        ledger.get_snapshot(forecast_id)
    now = utc_now_iso()
    as_of_ts = parse_timestamp(as_of, field_name="as_of") or now
    note_id = f"an_{uuid.uuid4().hex[:12]}"
    note_metadata = dict(metadata or {})
    if probability_at_write is not None:
        note_metadata["probability_at_write"] = probability_at_write
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO analyst_notes (
                id, question_id, forecast_id, resolution_id, kind, created_at,
                as_of, headline, body, how_it_feels, how_it_thinks, looking_for,
                be_aware, stance, verdict, confidence_at_write, agent_model,
                prompt_version, forecasting_protocol_version, generator, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note_id,
                question_id,
                forecast_id,
                resolution_id,
                kind,
                now,
                as_of_ts,
                headline,
                body,
                how_it_feels,
                how_it_thinks,
                looking_for,
                be_aware,
                stance,
                verdict,
                confidence_at_write,
                agent_model,
                prompt_version,
                forecasting_protocol_version,
                generator,
                json_dumps(note_metadata),
            ),
        )
    return ledger.get_analyst_note(note_id)


def get_analyst_note(ledger, note_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM analyst_notes WHERE id = ?",
            (note_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"analyst note not found: {note_id}")
    return ledger._analyst_note_to_dict(row)


def list_analyst_notes(
    ledger,
    question_id: str,
    *,
    kind: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return a question's analyst notes oldest-first (a parallel time series
    to ``forecast_history``)."""
    sql = "SELECT * FROM analyst_notes WHERE question_id = ?"
    params: list[Any] = [question_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    # rowid is the insertion-order tiebreaker: utc_now_iso() can tie when
    # several notes are written in the same instant (e.g. resolve writes a
    # brief and a retrospective back to back).
    sql += " ORDER BY created_at ASC, rowid ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [ledger._analyst_note_to_dict(row) for row in rows]


def latest_analyst_note(
    ledger,
    question_id: str,
    *,
    kind: str | None = None,
) -> dict[str, Any] | None:
    """Return the most recent analyst note (powers the desk quick-read)."""
    sql = "SELECT * FROM analyst_notes WHERE question_id = ?"
    params: list[Any] = [question_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
    with ledger._connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return ledger._analyst_note_to_dict(row) if row else None


def _analyst_note_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = json_loads(data.get("metadata"), {})
    return data


def analyst_notes_by_question(ledger, question_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """question_id -> analyst notes oldest-first (mirrors list_analyst_notes,
    same created_at ASC, rowid ASC tiebreaker)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM analyst_notes WHERE question_id IN ({placeholders}) "
                "ORDER BY question_id ASC, created_at ASC, rowid ASC",
                chunk,
            ).fetchall()
        for row in rows:
            out.setdefault(row["question_id"], []).append(ledger._analyst_note_to_dict(row))
    return out
