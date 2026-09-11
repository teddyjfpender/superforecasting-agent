"""Evidence + information-triage domain (D3 carve).

Carved verbatim out of ``forecasting/ledger/core.py``: the evidence lifecycle
(add / get / list / dedup keys / staleness helper / batch read / crux evidence
map + the row reader and dict serializer) and the information-triage glue
(desk-authored rubrics + the cheap auto-labeler's three-way staging labels + the
held-out trust-gate graduation alerter). Each function takes the
``ForecastLedger`` instance as its first argument; ``ForecastLedger`` keeps
one-line delegates so no caller changed.

Dependency direction (no cycle, per the D1/D2 findings): this leaf imports only
``forecasting.models`` / ``forecasting.leak_domains`` / stdlib at load time and
touches NOTHING in ``core`` at import. The evidence/triage domain has no gated
write, so — unlike D2 — the leaf needs no ``_core`` handle at all: every ``core``
dependency (``_connect``, ``get_question``, the ``_archive_*`` snapshot helpers
that stay in core, ``list_cruxes``/``list_watched_sources``, desk-state + alert
helpers, ``build_triage_trust_gate``) is reached through the ``ledger`` instance
(``ledger.<method>``) at call time, so the class's delegates keep every call site
byte-for-byte unchanged and monkeypatch-safe.

Snapshot-commit evidence GATES (``_validate_evidence_refs``) and the shared,
``urlopen``-coupled snapshot-archival helpers (``_archive_file_evidence_snapshot``
/ ``_archive_url_evidence_snapshot`` — tests patch ``forecasting.ledger.urlopen``,
which the façade forwards to ``core``) deliberately STAY in core: keeping the
``urlopen`` call sites in core preserves the module-global monkeypatch surface
without extending the façade (the D2 grep for package-level patches of every name
this leaf re-imports came back empty).
"""

from __future__ import annotations

import atexit
from collections import Counter
import logging
import sqlite3  # noqa: F401  (row type hints on the carved readers)
import uuid
from pathlib import Path
from typing import Any

from forecasting.leak_domains import leak_reason
from forecasting.models import (
    EVIDENCE_CLAIM_TYPES,
    AlertEvent,
    EvidenceItem,
    LedgerNotFoundError,
    ValidationError,
    json_dumps,
    json_loads,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)

logger = logging.getLogger(__name__)
_LEAK_WARNING_KEYS: set[tuple[str, str]] = set()
_LEAK_WARNING_COUNTS: Counter[tuple[str, str]] = Counter()


def _log_leak_domain_tally() -> None:
    total = sum(_LEAK_WARNING_COUNTS.values())
    if total:
        logger.info(
            "leak-domain evidence tally: %s item(s), %s normalized source/reason pair(s)",
            total,
            len(_LEAK_WARNING_COUNTS),
        )


atexit.register(_log_leak_domain_tally)

# Triage rubric scopes (leaf-owned; the D1 "constants to the leaf" rule) — the
# desk-authored "interesting vs merely relevant" taste is scoped like a
# calibration lesson.
_TRIAGE_RUBRIC_SCOPES = {"global", "domain", "topic", "domain_topic", "question_type"}

# Desk-state key for the last-observed triage trust-gate mode.
_TRIAGE_GATE_MODE_KEY = "triage_gate_mode"


# ── Evidence lifecycle ───────────────────────────────────────────────────────


def add_evidence(
    ledger,
    *,
    question_id: str,
    source_or_note: str,
    claim: str = "",
    summary: str = "",
    source_url: str | None = None,
    source_name: str | None = None,
    source_type: str | None = None,
    published_at: str | None = None,
    available_at: str | None = None,
    reliability_rating: float | None = None,
    relevance_rating: float | None = None,
    stance: str = "context",
    claim_type: str = "fact",
    snapshot_path: str | None = None,
    admissible_for_backtests: bool = True,
    metadata: dict[str, Any] | None = None,
    archive_url_snapshot: bool = True,
    extra_leak_denylist: object = None,
) -> EvidenceItem:
    ledger.get_question(question_id)
    source_or_note = source_or_note.strip()
    if not source_or_note and not source_url:
        raise ValidationError("evidence requires a URL or note")
    if reliability_rating is not None and not (0 <= reliability_rating <= 1):
        raise ValidationError("reliability_rating must be between 0 and 1")
    if relevance_rating is not None and not (0 <= relevance_rating <= 1):
        raise ValidationError("relevance_rating must be between 0 and 1")
    if claim_type not in EVIDENCE_CLAIM_TYPES:
        raise ValidationError(f"claim_type must be one of {', '.join(sorted(EVIDENCE_CLAIM_TYPES))}")

    inferred_url = source_url
    inferred_summary = summary
    inferred_type = source_type
    source_file_path: Path | None = None
    if source_or_note.startswith(("http://", "https://")):
        inferred_url = inferred_url or source_or_note
        inferred_type = inferred_type or "url"
    elif Path(source_or_note).expanduser().is_file():
        evidence_path = Path(source_or_note).expanduser()
        source_file_path = evidence_path
        inferred_type = inferred_type or "file"
        source_name = source_name or str(evidence_path)
        inferred_summary = inferred_summary or f"File evidence: {evidence_path.name}"
    else:
        inferred_summary = inferred_summary or source_or_note
        inferred_type = inferred_type or "manual_note"

    now = utc_now_iso()
    published = parse_timestamp(published_at, field_name="published_at")
    available = (
        parse_timestamp(available_at, field_name="available_at")
        or published
        or now
    )
    if published and timestamp_to_datetime(available) < timestamp_to_datetime(published):
        raise ValidationError("available_at cannot precede the source's published_at")
    evidence_id = f"ev_{uuid.uuid4().hex[:12]}"
    evidence_metadata = dict(metadata or {})
    evidence_metadata.pop("source_capture", None)
    if source_file_path is not None and snapshot_path is None:
        snapshot_path = ledger._archive_file_evidence_snapshot(
            question_id=question_id,
            evidence_id=evidence_id,
            source_file_path=source_file_path,
        )
        evidence_metadata.setdefault("source_file_path", str(source_file_path))
    elif (
        inferred_url
        and snapshot_path is None
        and archive_url_snapshot
        # Structured source adapters (source_type="adapter:fred", etc.) already
        # capture the authoritative observation in metadata; fetching the
        # source's HTML page to archive a snapshot adds ~5s/row of latency and
        # no data value (and on batch imports surfaced as "FRED refresh timed
        # out"). Skip archival for adapter-sourced evidence.
        and not str(inferred_type or "").startswith("adapter:")
    ):
        archived_url_snapshot = ledger._archive_url_evidence_snapshot(
            question_id=question_id,
            evidence_id=evidence_id,
            source_url=inferred_url,
        )
        if archived_url_snapshot is not None:
            snapshot_path = archived_url_snapshot["snapshot_path"]
            evidence_metadata["source_snapshot"] = archived_url_snapshot
            if not archived_url_snapshot.get('blocked') and not archived_url_snapshot.get('redirected') and archived_url_snapshot.get('status') == 200:
                evidence_metadata['source_capture'] = {
                    'url': inferred_url, 'sha256': archived_url_snapshot.get('sha256'),
                    'captured_at': now, 'method': 'https_fetch',
                }
            if archived_url_snapshot.get("blocked"):
                # Surface at top-level so list_evidence / show_question can
                # see "blocked" without opening the snapshot file. The
                # nested source_snapshot keeps the full diagnostic.
                evidence_metadata.setdefault("blocked", True)
                evidence_metadata.setdefault(
                    "block_reason", archived_url_snapshot.get("block_reason")
                )
                evidence_metadata.setdefault(
                    "block_signal", archived_url_snapshot.get("block_signal")
                )
    # AIA P2.4 — leak-domain choke point. A live-widget / live-quote / live-
    # ranking source serves TODAY's value regardless of any historical query,
    # so it silently time-travels. We TAG such items and mark them
    # inadmissible for backtest scoring (a HARD exclusion only on the
    # admissibility path) but NEVER drop them from the live ledger. For non-
    # leak URLs `is_leak_domain` returns False and this block is a no-op,
    # keeping the default add path byte-identical.
    if inferred_url:
        reason = leak_reason(inferred_url, extra_denylist=extra_leak_denylist)
        if reason is not None:
            evidence_metadata["leak_domain"] = True
            evidence_metadata["leak_reason"] = reason
            if admissible_for_backtests:
                admissible_for_backtests = False
            from urllib.parse import urlparse

            warning_key = (urlparse(inferred_url).netloc.lower(), reason)
            _LEAK_WARNING_COUNTS[warning_key] += 1
            if warning_key not in _LEAK_WARNING_KEYS:
                _LEAK_WARNING_KEYS.add(warning_key)
                logger.info(
                    "evidence source flagged as leak domain (inadmissible for backtests): %s — %s",
                    inferred_url,
                    reason,
                )
    # Integrity anchor is code-owned, never accepted from caller metadata.
    evidence_metadata.pop('archive_sha256', None)
    if snapshot_path and Path(snapshot_path).is_file():
        import hashlib
        evidence_metadata['archive_sha256'] = hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest()
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO evidence_items (
                id, question_id, captured_at, available_at, source_url,
                source_name, source_type, published_at, claim, summary,
                reliability_rating, relevance_rating, stance, claim_type, snapshot_path,
                admissible_for_backtests, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                question_id,
                now,
                available,
                inferred_url,
                source_name,
                inferred_type or "manual_note",
                published,
                claim,
                inferred_summary,
                reliability_rating,
                relevance_rating,
                stance,
                claim_type,
                snapshot_path,
                1 if admissible_for_backtests else 0,
                json_dumps(evidence_metadata),
            ),
        )
    return ledger.get_evidence(evidence_id)


def get_evidence(ledger, evidence_id: str) -> EvidenceItem:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM evidence_items WHERE id = ?", (evidence_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"evidence item not found: {evidence_id}")
    return ledger._row_to_evidence(row)


def list_evidence(ledger, question_id: str) -> list[EvidenceItem]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM evidence_items WHERE question_id = ? ORDER BY available_at ASC",
            (question_id,),
        ).fetchall()
    return [ledger._row_to_evidence(row) for row in rows]


# ── Source diversity (the monoculture guard) ─────────────────────────────────
#
# The whole edge rests on ORTHOGONAL signal (beating-the-market-strategy.md:
# 164-172, "Diversity must be engineered and MEASURED, not assumed"). A question
# read off a single source reproduces that source's consensus and has nothing to
# pool; if diversity silently collapses, so does the edge, invisibly. These two
# read-only aggregates make it visible: per-question distinct sources/types (into
# the readiness payload) and a ledger-level monoculture metric (into doctor).


# Audits and readiness use the same conservative source grouping.
from forecasting.evidence_quality import source_domain as _source_domain
from forecasting.evidence_quality import source_identity as _evidence_source_key


def question_source_diversity(ledger, question_id: str) -> dict[str, Any]:
    """Per-question source diversity: distinct source domains + distinct source
    TYPES over the question's evidence, plus the single-source flag. Read-only;
    feeds the readiness payload."""
    items = ledger.list_evidence(question_id)
    domains: set[str] = set()
    types: set[str] = set()
    for item in items:
        key = _evidence_source_key(item)
        if key:
            domains.add(key)
        stype = (item.source_type or "").strip().lower()
        if stype:
            types.add(stype)
    return {
        "evidence_count": len(items),
        "distinct_sources": len(domains),
        "distinct_source_types": len(types),
        "single_source": len(items) > 0 and len(domains) <= 1,
    }


def source_diversity_summary(ledger) -> dict[str, Any]:
    """Ledger-level monoculture metric: the median distinct sources/question and
    the single-source share, over every question carrying ≥1 evidence item. One
    pass over ``evidence_items``; read-only. Feeds doctor."""
    import statistics
    from collections import defaultdict

    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT question_id, source_name, source_type, source_url FROM evidence_items"
        ).fetchall()
    per_question: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        name = (row["source_name"] or "").strip().lower()
        key = name or _source_domain(row["source_url"]) or (row["source_type"] or "").strip().lower()
        if key:
            per_question[row["question_id"]].add(key)
    counts = sorted(len(sources) for sources in per_question.values())
    n = len(counts)
    single = sum(1 for count in counts if count <= 1)
    return {
        "questions_with_evidence": n,
        "median_sources_per_question": (statistics.median(counts) if counts else None),
        "mean_sources_per_question": (sum(counts) / n if n else None),
        "single_source_question_count": single,
        "single_source_pct": (single / n if n else None),
    }


def existing_evidence_keys(ledger, question_id: str) -> set[tuple[str, str]]:
    """Return ``{(source_type, entry_id)}`` for evidence already imported for
    the question. Used to skip re-importing identical structured readings
    (e.g. the same FRED observation) on every refresh, which otherwise bloats
    the evidence table. Items without an ``entry_id`` (e.g. free-form notes)
    are never deduped."""
    keys: set[tuple[str, str]] = set()
    for item in ledger.list_evidence(question_id):
        entry_id = (item.metadata or {}).get("entry_id")
        if entry_id:
            keys.add((item.source_type or "", str(entry_id)))
    return keys


def find_stale_evidence_refs(
    ledger,
    question_id: str,
    evidence_refs: list[str],
    *,
    as_of: str | None = None,
    stale_days: int = 30,
) -> list[EvidenceItem]:
    if stale_days < 0:
        raise ValidationError("stale_days must be non-negative")
    as_of_ts = parse_timestamp(as_of, field_name="as_of") or utc_now_iso()
    as_of_dt = timestamp_to_datetime(as_of_ts)
    assert as_of_dt is not None
    stale: list[EvidenceItem] = []
    for evidence_id in evidence_refs:
        evidence = ledger.get_evidence(evidence_id)
        if evidence.question_id != question_id:
            raise ValidationError(f"evidence item {evidence_id} does not belong to question {question_id}")
        available_dt = timestamp_to_datetime(evidence.available_at)
        if available_dt and (as_of_dt - available_dt).days >= stale_days:
            stale.append(evidence)
    return stale


def evidence_by_question(ledger, question_ids: list[str]) -> dict[str, list[EvidenceItem]]:
    """question_id -> evidence oldest-first by available_at (mirrors list_evidence)."""
    out: dict[str, list[EvidenceItem]] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM evidence_items WHERE question_id IN ({placeholders}) "
                "ORDER BY question_id ASC, available_at ASC",
                chunk,
            ).fetchall()
        for row in rows:
            out.setdefault(row["question_id"], []).append(ledger._row_to_evidence(row))
    return out


def evidence_map(ledger, question_id: str) -> dict[str, Any]:
    """Assemble the crux evidence map: each decisive variable, its materiality +
    status, and whether the question actually watches a source in a role that
    could satisfy it. Surfaces 'lots of evidence but the crux is missing' —
    high-materiality cruxes that are missing/stale with no matching source."""
    ledger.get_question(question_id)
    cruxes = ledger.list_cruxes(question_id)
    watched = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    watched_roles = {w.get("role") for w in watched if w.get("role")}

    rank = {"high": 0, "medium": 1, "low": 2}
    status_rank = {"missing": 0, "contradictory": 1, "stale": 2, "current": 3}
    rows = []
    for crux in cruxes:
        preferred = crux.get("preferred_roles") or []
        has_source = bool(set(preferred) & watched_roles) if preferred else bool(watched)
        rows.append({
            "id": crux["id"],
            "crux_variable": crux["crux_variable"],
            "materiality": crux["materiality"],
            "status": crux["status"],
            "preferred_roles": preferred,
            "has_matching_source": has_source,
        })
    rows.sort(key=lambda r: (rank.get(r["materiality"], 1), status_rank.get(r["status"], 0)))
    gaps = [r for r in rows if r["materiality"] == "high" and r["status"] in {"missing", "stale", "contradictory"}]
    return {"question_id": question_id, "cruxes": rows, "high_materiality_gaps": gaps, "gap_count": len(gaps)}


def _row_to_evidence(ledger, row: sqlite3.Row) -> EvidenceItem:
    return EvidenceItem(
        id=row["id"],
        question_id=row["question_id"],
        captured_at=row["captured_at"],
        available_at=row["available_at"],
        source_url=row["source_url"],
        source_name=row["source_name"],
        source_type=row["source_type"],
        published_at=row["published_at"],
        claim=row["claim"],
        summary=row["summary"],
        reliability_rating=row["reliability_rating"],
        relevance_rating=row["relevance_rating"],
        stance=row["stance"],
        claim_type=row["claim_type"],
        snapshot_path=row["snapshot_path"],
        admissible_for_backtests=bool(row["admissible_for_backtests"]),
        metadata=json_loads(row["metadata"], {}),
    )


def _evidence_to_dict(ledger, item: EvidenceItem) -> dict[str, Any]:
    return item.__dict__.copy()


# ── Triage rubrics + labels (information triage) ──────────────────────────────
# The desk-authored rubrics + a STAGING surface for the cheap auto-labeler's
# three-way calls, kept OFF the evidence table. The labeler itself lives in
# forecasting/triage.py; the held-out trust gate scores auto_label vs expert_label.


def _row_to_triage_rubric(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["examples"] = json_loads(d.get("examples"), [])
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def _row_to_triage_label(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["contested"] = bool(d.get("contested"))
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def set_triage_rubric(
    ledger,
    *,
    scope_type: str,
    scope_ref: str | None = None,
    interesting_criteria: str,
    uninteresting_criteria: str = "",
    irrelevant_criteria: str = "",
    examples: list[Any] | None = None,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upsert the active rubric for a scope (mirrors calibration-lesson scoping)."""
    if scope_type not in _TRIAGE_RUBRIC_SCOPES:
        raise ValidationError(
            "invalid triage rubric scope_type: must be one of "
            + ", ".join(sorted(_TRIAGE_RUBRIC_SCOPES))
        )
    if scope_type == "global":
        scope_ref = None
    elif not (scope_ref or "").strip():
        raise ValidationError(f"triage rubric scope_type={scope_type} requires a scope_ref")
    if scope_type == "domain_topic" and ":" not in (scope_ref or ""):
        raise ValidationError("domain_topic triage rubric requires a 'domain:topic' scope_ref")
    now = utc_now_iso()
    examples_json = json_dumps(list(examples or []))
    metadata_json = json_dumps(dict(metadata or {}))
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM triage_rubrics WHERE scope_type = ? "
            "AND IFNULL(scope_ref, '') = IFNULL(?, '') AND status = 'active'",
            (scope_type, scope_ref),
        ).fetchone()
        if existing:
            rubric_id = existing["id"]
            conn.execute(
                "UPDATE triage_rubrics SET updated_at=?, interesting_criteria=?, "
                "uninteresting_criteria=?, irrelevant_criteria=?, examples=?, notes=?, "
                "metadata=? WHERE id=?",
                (
                    now, interesting_criteria, uninteresting_criteria, irrelevant_criteria,
                    examples_json, notes, metadata_json, rubric_id,
                ),
            )
        else:
            rubric_id = f"tr_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO triage_rubrics (id, scope_type, scope_ref, created_at, "
                "updated_at, status, interesting_criteria, uninteresting_criteria, "
                "irrelevant_criteria, examples, notes, metadata) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rubric_id, scope_type, scope_ref, now, now, "active",
                    interesting_criteria, uninteresting_criteria, irrelevant_criteria,
                    examples_json, notes, metadata_json,
                ),
            )
    return ledger.get_triage_rubric(rubric_id)


def get_triage_rubric(ledger, rubric_id: str) -> dict[str, Any] | None:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM triage_rubrics WHERE id = ?", (rubric_id,)
        ).fetchone()
    return ledger._row_to_triage_rubric(row) if row else None


def list_triage_rubrics(
    ledger,
    *,
    scope_type: str | None = None,
    scope_ref: str | None = None,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scope_type:
        clauses.append("scope_type = ?")
        params.append(scope_type)
    if scope_ref:
        clauses.append("scope_ref = ?")
        params.append(scope_ref)
    if active_only:
        clauses.append("status = 'active'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM triage_rubrics {where} ORDER BY updated_at DESC", params
        ).fetchall()
    return [ledger._row_to_triage_rubric(row) for row in rows]


def record_triage_labels(
    ledger, *, question_id: str | None = None, verdicts: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Persist the cheap auto-labeler's three-way calls as staging rows."""
    now = utc_now_iso()
    stored: list[str] = []
    with ledger._connect() as conn:
        for verdict in verdicts:
            if not isinstance(verdict, dict):
                continue
            label_id = f"tl_{uuid.uuid4().hex[:12]}"
            auto = verdict.get("triage_label") or verdict.get("auto_label")
            rel_raw = verdict.get("relevance")
            try:
                relevance = float(rel_raw) if rel_raw is not None else None
            except (TypeError, ValueError):
                relevance = None
            conn.execute(
                "INSERT INTO triage_labels (id, question_id, created_at, candidate_ref, "
                "title, summary, source_type, source, url, auto_label, expert_label, "
                "triage_label, label_source, materiality, verdict, relevance, rationale, "
                "rubric_id, model, contested, alert_id, adjudicated_at, metadata) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    label_id, question_id, now, verdict.get("candidate_ref"),
                    verdict.get("title") or "", verdict.get("summary") or "",
                    verdict.get("source_type"), verdict.get("source"), verdict.get("url"),
                    auto, None, auto, "auto",
                    verdict.get("materiality") or "medium",
                    verdict.get("verdict") or "skim", relevance,
                    verdict.get("rationale") or "", verdict.get("rubric_id"),
                    verdict.get("model"), 0, None, None,
                    json_dumps(dict(verdict.get("metadata") or {})),
                ),
            )
            stored.append(label_id)
    return [r for r in (ledger.get_triage_label(i) for i in stored) if r is not None]


def get_triage_label(ledger, label_id: str) -> dict[str, Any] | None:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM triage_labels WHERE id = ?", (label_id,)
        ).fetchone()
    return ledger._row_to_triage_label(row) if row else None


def list_triage_labels(
    ledger,
    *,
    question_id: str | None = None,
    label_source: str | None = None,
    contested: bool | None = None,
    adjudicated: bool | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if label_source:
        clauses.append("label_source = ?")
        params.append(label_source)
    if contested is not None:
        clauses.append("contested = ?")
        params.append(1 if contested else 0)
    if adjudicated is True:
        clauses.append("adjudicated_at IS NOT NULL")
    elif adjudicated is False:
        clauses.append("adjudicated_at IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM triage_labels {where} ORDER BY created_at DESC LIMIT ?",
            params + [int(limit)],
        ).fetchall()
    return [ledger._row_to_triage_label(row) for row in rows]


def update_triage_label(
    ledger,
    label_id: str,
    *,
    expert_label: str | None = None,
    triage_label: str | None = None,
    label_source: str | None = None,
    contested: bool | None = None,
    alert_id: str | None = None,
    adjudicated_at: str | None = None,
    verdict: str | None = None,
    materiality: str | None = None,
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = []
    if expert_label is not None:
        sets.append("expert_label = ?")
        params.append(expert_label)
    if triage_label is not None:
        sets.append("triage_label = ?")
        params.append(triage_label)
    if label_source is not None:
        sets.append("label_source = ?")
        params.append(label_source)
    if contested is not None:
        sets.append("contested = ?")
        params.append(1 if contested else 0)
    if alert_id is not None:
        sets.append("alert_id = ?")
        params.append(alert_id)
    if adjudicated_at is not None:
        sets.append("adjudicated_at = ?")
        params.append(adjudicated_at)
    if verdict is not None:
        sets.append("verdict = ?")
        params.append(verdict)
    if materiality is not None:
        sets.append("materiality = ?")
        params.append(materiality)
    if not sets:
        return ledger.get_triage_label(label_id)
    with ledger._connect() as conn:
        conn.execute(
            f"UPDATE triage_labels SET {', '.join(sets)} WHERE id = ?",
            params + [label_id],
        )
    return ledger.get_triage_label(label_id)


def check_triage_gate_graduation(
    ledger,
    *,
    threshold: float = 0.8,
    min_sample: int = 20,
    demote_margin: float = 0.05,
    now: str | None = None,
) -> dict[str, Any] | None:
    """Detect a triage trust-gate MODE TRANSITION and alert on it once.

    Builds the held-out trust gate, compares its mode ("auto" | "suggest_only")
    to the last-persisted mode in ``desk_state``, and:

    * persists the new mode whenever it changed (ATOMICALLY — see below);
    * opens an INFO "triage labeler graduated" alert the first time the mode
      flips to ``auto`` (auto-filter enabled), and a symmetric demotion alert if
      it later drops back to ``suggest_only`` after having been ``auto``;
    * fires NOTHING on the initial baseline observation of ``suggest_only`` (the
      cold-start default — a labeler that has never cleared the bar is not news).

    HYSTERESIS (anti-flap): once graduated to ``auto``, a dip that is merely
    below the graduate bar but still within ``demote_margin`` of it does NOT
    demote — demotion needs a real drop below ``threshold - demote_margin`` (the
    auto-filter mode itself is decided live by :func:`build_triage_trust_gate`;
    this band governs only the ALERT transition, so a small-sample accuracy
    oscillation across the bar no longer spams graduated/demoted alerts).

    Race- and dedup-safe: the mode is moved with an atomic compare-and-set
    (:meth:`transition_desk_state`) so overlapping sweeps cannot both fire, and
    alert creation is deduped against an already-open alert of the same
    reason/scope. Deterministic + cheap (reads adjudicated labels, no model
    call). Returns the transition dict (or ``None`` when nothing changed).
    """
    from forecasting.triage import build_triage_trust_gate

    gate = build_triage_trust_gate(ledger, threshold=threshold, min_sample=min_sample)
    raw_mode = gate["mode"]
    accuracy = gate.get("observed_accuracy")

    prev_observed = ledger.get_desk_state(_TRIAGE_GATE_MODE_KEY)
    # Hysteresis on the DEMOTE edge only: hold "auto" through a shallow dip.
    demote_threshold = threshold - max(0.0, float(demote_margin))
    if prev_observed == "auto" and raw_mode != "auto":
        holds = isinstance(accuracy, (int, float)) and accuracy >= demote_threshold
        mode = "auto" if holds else "suggest_only"
    else:
        mode = raw_mode

    # Atomic compare-and-set: only the sweep that actually performs the
    # transition proceeds; a concurrent sweep (or a steady state) is silent.
    changed, prev = ledger.transition_desk_state(
        _TRIAGE_GATE_MODE_KEY, mode, now=now
    )
    if not changed:
        return None

    pct = f"{accuracy:.0%}" if isinstance(accuracy, (int, float)) else "n/a"
    alert: AlertEvent | None = None
    transition: str
    if mode == "auto":
        transition = "graduated"
        reason = "triage_labeler_graduated"
        if not ledger._has_open_alert(
            reason=reason, scope_type="global", scope_ref="triage_labeler"
        ):
            alert = ledger.create_alert(
                severity="info",
                scope_type="global",
                scope_ref="triage_labeler",
                reason=reason,
                recommended_action=(
                    f"triage labeler graduated: {gate['n']} adjudications at {pct} — "
                    "auto-filter enabled. The autopilot may now auto-capture keep/skim "
                    "candidates on a material change (previously suggest-only)."
                ),
            )
    elif prev == "auto":
        # Only a DEMOTION from a previously-graduated state is worth an alert; a
        # first-time suggest_only baseline (prev is None) is the cold start.
        transition = "demoted"
        reason = "triage_labeler_demoted"
        if not ledger._has_open_alert(
            reason=reason, scope_type="global", scope_ref="triage_labeler"
        ):
            alert = ledger.create_alert(
                severity="warning",
                scope_type="global",
                scope_ref="triage_labeler",
                reason=reason,
                recommended_action=(
                    f"triage labeler demoted: accuracy {pct} over n={gate['n']} dropped below "
                    f"the {threshold:.0%} bar — auto-filter disabled, back to suggest-only. "
                    "Route disagreements to operator review (relabel_route) to rebuild trust."
                ),
            )
    else:
        transition = "baseline"

    return {
        "transition": transition,
        "mode": mode,
        "previous_mode": prev,
        "gate": gate,
        "alert": alert,
    }
