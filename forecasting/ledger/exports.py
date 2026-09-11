"""Question export / import-packet domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the portable-packet surface:

* EXPORT: ``export_question`` (assemble a question's full packet — snapshots,
  resolution, evidence, panels, notes, links) and ``export_all``;
* IMPORT: ``import_packet`` and its row-insert pipeline
  (``_question_packets_from_import`` / ``_import_question_packet`` /
  ``_import_packet_rows`` / ``_insert_packet_row``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. Every export read resolves
through the ``ledger`` INSTANCE (``get_current_snapshot`` / ``list_evidence`` /
``_validate_question_scoped_refs`` — the shared validator that stays in core);
the ``_PACKET_*`` field maps and the ``_export_metadata`` helper are reached via
the ``_core.`` call-time hop."""

from __future__ import annotations

from forecasting.ledger import core as _core
from typing import Any
from forecasting.branding import NORTH_STAR
from forecasting.branding import PRODUCT_NAME
from forecasting.models import ValidationError
from collections import defaultdict
from forecasting.models import json_dumps
from forecasting.models import json_loads
import sqlite3
from forecasting.models import utc_now_iso


def export_question(ledger, question_id: str, *, fmt: str = "markdown") -> str:
    question = ledger.get_question(question_id)
    snapshots = ledger.list_snapshots(question_id)
    evidence = ledger.list_evidence(question_id)
    assumptions = ledger.list_assumptions(question_id)
    reference_classes = ledger.list_reference_classes(question_id)
    model_runs = ledger.list_model_runs(question_id)
    source_snapshots = ledger.list_source_snapshots(question_id=question_id, limit=1000)
    watched_sources = ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
    scheduled_reviews = [
        row
        for row in ledger.list_scheduled_reviews()
        if row.get("scope_type") == "question" and row.get("scope_ref") == question_id
    ]
    scheduled_review_runs = [
        run
        for review in scheduled_reviews
        for run in ledger.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=100)
    ]
    autopilot_policies = ledger.list_autopilot_policies(question_id=question_id, enabled_only=False)
    autopilot_runs = ledger.list_autopilot_runs(question_id=question_id, limit=100)
    forecast_update_proposals = ledger.list_forecast_update_proposals(question_id=question_id, status=None, limit=100)
    postmortems = ledger.list_postmortems(question_id, include_invalidated=True)
    baselines = ledger.list_baseline_comparisons(question_id)
    resolution = ledger.get_latest_resolution(question_id)
    scores = [s for s in ledger.list_scores(include_invalidated=True) if s.question_id == question_id]
    calibration_lessons = ledger._calibration_lessons_for_question(scores, postmortems)
    domain_error_profiles = ledger._domain_error_profiles_for_question(question)
    corrections = ledger._corrections_for_question(
        question_id=question_id,
        snapshots=snapshots,
        evidence=evidence,
        assumptions=assumptions,
        reference_classes=reference_classes,
        model_runs=model_runs,
        resolution=resolution,
        scores=scores,
        postmortems=postmortems,
        calibration_lessons=calibration_lessons,
    )
    related_forecasts, related_shared_sources = ledger.related_forecast_views(question_id)
    if fmt == "json":
        from forecasting.applicability_facts import evidence_facts
        from forecasting.settlement_reviews import latest_reviews
        return json_dumps(
            {
                "product": _core._export_metadata(),
                "generated_at": utc_now_iso(),
                "question": ledger._question_to_dict(question),
                "applicability_facts": evidence_facts(ledger, question),
                "settlement_review": latest_reviews(ledger).get(question.id),
                "forecast_history": [ledger._snapshot_to_dict(snapshot) for snapshot in snapshots],
                "evidence": [ledger._evidence_to_dict(item) for item in evidence],
                "assumptions": assumptions,
                "reference_classes": reference_classes,
                "model_runs": model_runs,
                "source_snapshots": source_snapshots,
                "watched_sources": watched_sources,
                "scheduled_reviews": scheduled_reviews,
                "scheduled_review_runs": scheduled_review_runs,
                "autopilot_policies": autopilot_policies,
                "autopilot_runs": autopilot_runs,
                "forecast_update_proposals": forecast_update_proposals,
                "baseline_comparisons": baselines,
                "resolution": ledger._resolution_to_dict(resolution) if resolution else None,
                "scores": [ledger._score_to_dict(score) for score in scores],
                "postmortems": postmortems,
                "calibration_lessons": calibration_lessons,
                "domain_error_profiles": domain_error_profiles,
                "corrections": corrections,
                "panel_runs": ledger.list_panel_runs(question_id, limit=20),
                "analyst_notes": ledger.list_analyst_notes(question_id),
                "analyst_note": ledger.latest_analyst_note(question_id, kind="brief"),
                "retrospective": ledger.latest_analyst_note(question_id, kind="retrospective"),
                # forecast_links round-trips the raw edges; related_forecasts /
                # related_shared_sources are the derived audit copy the TUI reads.
                "forecast_links": ledger.list_forecast_links(question_id, direction="both"),
                # Thesis membership + entities round-trip the raw rows; the
                # import orphan-guard skips edges whose endpoint questions
                # aren't also in the packet.
                "thesis_members": ledger.list_thesis_members(question_id),
                "thesis_entities": ledger.list_thesis_entities(question_id),
                "related_forecasts": related_forecasts,
                "related_shared_sources": [{"signature": s} for s in related_shared_sources],
            }
        )
    if fmt != "markdown":
        raise ValidationError("export format must be markdown or json")
    lines = [
        f"# Forecast Packet: {question.title}",
        "",
        f"- Product: {PRODUCT_NAME}",
        f"- North star: {NORTH_STAR}",
        f"- ID: `{question.id}`",
        f"- Generated at: {utc_now_iso()}",
        f"- Status: {question.status}",
        f"- Domain: {question.domain or ''}",
        f"- Close time: {question.close_time or ''}",
        f"- Resolution time: {question.resolution_time or ''}",
        f"- Resolution criteria: {question.resolution_criteria}",
        "",
        "## Current Forecast",
    ]
    current = snapshots[-1] if snapshots else None
    if current:
        lines.extend(
            [
                f"- Forecast ID: `{current.forecast_id}`",
                f"- As of: {current.as_of}",
                f"- Probability/distribution: `{current.probability_or_distribution}`",
                f"- Confidence: {current.confidence if current.confidence is not None else ''}",
                f"- Rationale: {current.rationale}",
                "",
            ]
        )
    else:
        lines.extend(["No forecast snapshot recorded.", ""])
    lines.append("## Forecast History")
    if snapshots:
        for snapshot in snapshots:
            lines.append(
                f"- {snapshot.as_of}: `{snapshot.probability_or_distribution}` "
                f"({snapshot.method or 'unspecified'}) - {snapshot.rationale}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Evidence"])
    if evidence:
        for item in evidence:
            label = item.source_url or item.source_name or "manual note"
            lines.append(f"- {item.available_at}: {label} - {item.claim or item.summary}")
    else:
        lines.append("- None")
    lines.extend(["", "## Assumptions"])
    if assumptions:
        for item in assumptions:
            lines.append(f"- {item['status']}: {item['text']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Reference Classes"])
    if reference_classes:
        for item in reference_classes:
            lines.append(
                f"- {item['name']}: base_rate={item['base_rate']} "
                f"uncertainty={item['base_rate_uncertainty']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Model Runs"])
    if model_runs:
        for item in model_runs:
            lines.append(f"- {item['created_at']}: {item['model_type']} `{item['id']}`")
    else:
        lines.append("- None")
    lines.extend(["", "## Watched Sources"])
    if watched_sources:
        for item in watched_sources:
            lines.append(f"- {item['id']} {item['scope_type']}:{item['scope_ref']} {item['source_type']} {item['source']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Scheduled Self-Checks"])
    if scheduled_reviews:
        for item in scheduled_reviews:
            lines.append(
                f"- {item['id']} {item['scope_type']}:{item['scope_ref']} "
                f"cadence={item['cadence']} next={item['next_run_at']} "
                f"learning=score:{bool(item.get('auto_score'))}/postmortem:{bool(item.get('auto_postmortem'))}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Scheduled Self-Check Runs"])
    if scheduled_review_runs:
        for item in scheduled_review_runs:
            lines.append(
                f"- {item['id']} schedule={item['scheduled_review_id']} "
                f"run_at={item['run_at']} alerts={item['alert_count']} "
                f"scores={item['score_count']} postmortems={item['postmortem_count']} "
                f"learning_reviews={item['learning_review_count']} next={item['next_run_at']}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Autopilot"])
    if autopilot_policies:
        for item in autopilot_policies:
            lines.append(
                f"- {item['id']} mode={item['mode']} cadence={item['cadence']} "
                f"enabled={item['enabled']}"
            )
    else:
        lines.append("- None")
    if forecast_update_proposals:
        lines.append("")
        lines.append("### Update Proposals")
        for item in forecast_update_proposals:
            lines.append(
                f"- {item['id']} {item['status']}: prior={item['prior_forecast_id']} "
                f"run={item['run_id']}"
            )
    lines.extend(["", "## Resolution"])
    if resolution:
        lines.append(
            f"- {resolution.resolved_at}: `{resolution.outcome}` "
            f"({resolution.resolution_status}, criteria_satisfied={resolution.criteria_satisfied})"
        )
    else:
        lines.append("- Unresolved")
    lines.extend(["", "## Scores"])
    if scores:
        for score in scores:
            suffix = f", invalidated_by={score.invalidated_by_correction_id}" if score.invalidated_by_correction_id else ""
            lines.append(
                f"- {score.scored_at}: Brier={score.brier_score}, "
                f"bucket={score.calibration_bucket}, origin={score.forecast_origin}{suffix}"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Postmortems"])
    if postmortems:
        for item in postmortems:
            suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
            lines.append(f"- {item['created_at']}: {item['summary']}{suffix}")
    else:
        lines.append("- None")
    lines.extend(["", "## Calibration Lessons"])
    if calibration_lessons:
        for item in calibration_lessons:
            suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
            lines.append(f"- {item['id']} {item['status']}: {item['lesson']}{suffix}")
    else:
        lines.append("- None")
    lines.extend(["", "## Corrections"])
    if corrections:
        for item in corrections:
            lines.append(f"- {item['id']} {item['status']}: {item['target_type']} `{item['target_id']}` - {item['reason']}")
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def export_all(ledger, *, fmt: str = "markdown") -> str:
    questions = ledger.list_questions()
    if fmt == "json":
        return json_dumps(
            {
                "product": _core._export_metadata(),
                "generated_at": utc_now_iso(),
                "questions": [
                    json_loads(ledger.export_question(question.id, fmt="json"), {})
                    for question in questions
                ],
                "ingest_candidates": ledger.list_ingest_candidates(),
                "source_snapshots": ledger.list_source_snapshots(),
                "watched_sources": ledger.list_watched_sources(status=None),
                "scheduled_reviews": ledger.list_scheduled_reviews(),
                "scheduled_review_runs": ledger.list_scheduled_review_runs(limit=1000),
                "autopilot_policies": ledger.list_autopilot_policies(enabled_only=False),
                "autopilot_runs": ledger.list_autopilot_runs(limit=1000),
                "forecast_update_proposals": ledger.list_forecast_update_proposals(status=None),
                "domain_error_profiles": ledger.list_domain_error_profiles(),
                "alerts": [alert.__dict__ for alert in ledger.list_alerts(unresolved_only=False)],
            }
        )
    if fmt != "markdown":
        raise ValidationError("export format must be markdown or json")
    lines = [
        "# Forecast Portfolio Export",
        "",
        f"- Product: {PRODUCT_NAME}",
        f"- North star: {NORTH_STAR}",
        f"- Generated at: {utc_now_iso()}",
        f"- Questions: {len(questions)}",
        "",
    ]
    for question in questions:
        lines.append(ledger.export_question(question.id, fmt="markdown"))
    return "\n".join(lines)


def import_packet(ledger, packet: dict[str, Any], *, conflict: str = "error") -> dict[str, Any]:
    """Import a JSON packet produced by ``export_question`` or ``export_all``."""
    if conflict not in {"error", "skip", "replace"}:
        raise ValidationError("conflict must be error, skip, or replace")
    if not isinstance(packet, dict):
        raise ValidationError("forecast packet must be a JSON object")
    question_packets = ledger._question_packets_from_import(packet)
    if not question_packets and not any(
        isinstance(packet.get(key), list)
        for key in (
            "ingest_candidates",
            "watched_sources",
            "source_snapshots",
            "scheduled_reviews",
            "scheduled_review_runs",
            "autopilot_policies",
            "autopilot_runs",
            "forecast_update_proposals",
            "domain_error_profiles",
            "alerts",
        )
    ):
        raise ValidationError("forecast packet has no importable records")
    summary: dict[str, Any] = {
        "product": _core._export_metadata(),
        "imported_at": utc_now_iso(),
        "source_product": packet.get("product") if isinstance(packet.get("product"), dict) else None,
        "source_generated_at": packet.get("generated_at"),
        "conflict": conflict,
        "imported": defaultdict(int),
        "skipped_existing": 0,
        "replaced_existing": 0,
        "duplicates_in_packet": 0,
    }
    seen: set[tuple[str, str]] = set()
    with ledger.transaction(immediate=True) as conn:
        for question_packet in question_packets:
            ledger._import_question_packet(conn, question_packet, conflict=conflict, summary=summary, seen=seen)
        ledger._import_packet_rows(
            conn,
            "ingest_candidates",
            packet.get("ingest_candidates"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "watched_sources",
            packet.get("watched_sources"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "source_snapshots",
            packet.get("source_snapshots"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "scheduled_reviews",
            packet.get("scheduled_reviews"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "scheduled_review_runs",
            packet.get("scheduled_review_runs"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "autopilot_policies",
            packet.get("autopilot_policies"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "autopilot_runs",
            packet.get("autopilot_runs"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "forecast_update_proposals",
            packet.get("forecast_update_proposals"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "domain_error_profiles",
            packet.get("domain_error_profiles"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
        ledger._import_packet_rows(
            conn,
            "alert_events",
            packet.get("alerts"),
            conflict=conflict,
            summary=summary,
            seen=seen,
        )
    imported = dict(sorted(summary["imported"].items()))
    summary["imported"] = imported
    summary["imported_total"] = sum(imported.values())
    return summary


def _question_packets_from_import(ledger, packet: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(packet.get("question"), dict):
        return [packet]
    questions = packet.get("questions")
    if questions is None:
        return []
    if not isinstance(questions, list):
        raise ValidationError("forecast packet questions field must be a list")
    result: list[dict[str, Any]] = []
    for index, question_packet in enumerate(questions):
        if not isinstance(question_packet, dict):
            raise ValidationError(f"forecast packet question entry {index} must be an object")
        result.append(question_packet)
    return result


def _import_question_packet(
    ledger,
    conn: sqlite3.Connection,
    packet: dict[str, Any],
    *,
    conflict: str,
    summary: dict[str, Any],
    seen: set[tuple[str, str]],
) -> None:
    question = packet.get("question")
    if not isinstance(question, dict):
        raise ValidationError("question packet must include a question object")
    ledger._insert_packet_row(conn, "forecast_questions", question, conflict=conflict, summary=summary, seen=seen)
    for table, key in (
        ("assumptions", "assumptions"),
        ("reference_classes", "reference_classes"),
        ("model_runs", "model_runs"),
        ("evidence_items", "evidence"),
        ("forecast_snapshots", "forecast_history"),
        ("resolutions", "resolution"),
        ("score_records", "scores"),
        ("postmortems", "postmortems"),
        ("calibration_lessons", "calibration_lessons"),
        ("forecast_corrections", "corrections"),
        ("baseline_comparisons", "baseline_comparisons"),
        ("watched_sources", "watched_sources"),
        ("source_snapshots", "source_snapshots"),
        ("scheduled_reviews", "scheduled_reviews"),
        ("scheduled_review_runs", "scheduled_review_runs"),
        ("autopilot_policies", "autopilot_policies"),
        ("autopilot_runs", "autopilot_runs"),
        ("forecast_update_proposals", "forecast_update_proposals"),
        ("domain_error_profiles", "domain_error_profiles"),
        ("analyst_notes", "analyst_notes"),
        # forecast_links + thesis membership/entities LAST so the endpoint
        # questions are imported first.
        ("forecast_links", "forecast_links"),
        ("thesis_members", "thesis_members"),
        ("thesis_entities", "thesis_entities"),
    ):
        ledger._import_packet_rows(conn, table, packet.get(key), conflict=conflict, summary=summary, seen=seen)


def _import_packet_rows(
    ledger,
    conn: sqlite3.Connection,
    table: str,
    rows: Any,
    *,
    conflict: str,
    summary: dict[str, Any],
    seen: set[tuple[str, str]],
) -> None:
    if rows is None:
        return
    if isinstance(rows, dict):
        rows_to_import = [rows]
    elif isinstance(rows, list):
        rows_to_import = rows
    else:
        raise ValidationError(f"{_core._PACKET_RECORD_LABELS[table]} must be an object or list")
    for index, row in enumerate(rows_to_import):
        if row is None:
            continue
        if not isinstance(row, dict):
            raise ValidationError(f"{_core._PACKET_RECORD_LABELS[table]} entry {index} must be an object")
        ledger._insert_packet_row(conn, table, row, conflict=conflict, summary=summary, seen=seen)


def _insert_packet_row(
    ledger,
    conn: sqlite3.Connection,
    table: str,
    row: dict[str, Any],
    *,
    conflict: str,
    summary: dict[str, Any],
    seen: set[tuple[str, str]],
) -> None:
    pk = _core._PACKET_PRIMARY_KEYS.get(table, "id")
    record_id = str(row.get(pk) or "").strip()
    if not record_id:
        raise ValidationError(f"{_core._PACKET_RECORD_LABELS[table]} import row is missing {pk}")
    seen_key = (table, record_id)
    if seen_key in seen:
        summary["duplicates_in_packet"] += 1
        return
    seen.add(seen_key)
    # A link / membership / entity can reference a question not present in
    # this packet; with foreign_keys=ON that would IntegrityError. Skip the
    # dangling row rather than abort the import.
    _orphan_fk_columns = {
        "forecast_links": ("from_question_id", "to_question_id"),
        "thesis_members": ("thesis_question_id", "member_question_id"),
        "thesis_entities": ("thesis_question_id",),
    }.get(table)
    if _orphan_fk_columns:
        for column in _orphan_fk_columns:
            if conn.execute(
                "SELECT 1 FROM forecast_questions WHERE id = ?", (row.get(column),)
            ).fetchone() is None:
                summary["skipped_existing"] += 1
                return
    existing = conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (record_id,)).fetchone()
    if existing is not None:
        if conflict == "error":
            raise ValidationError(f"{_core._PACKET_RECORD_LABELS[table]} record already exists: {record_id}")
        if conflict == "skip":
            summary["skipped_existing"] += 1
            return
        conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (record_id,))
        summary["replaced_existing"] += 1
    table_columns = [column["name"] for column in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    columns = [column for column in table_columns if column in row]
    if pk not in columns:
        raise ValidationError(f"{_core._PACKET_RECORD_LABELS[table]} import row is missing {pk}")
    json_fields = _core._PACKET_JSON_FIELDS.get(table, set())
    bool_fields = _core._PACKET_BOOL_FIELDS.get(table, set())
    values: list[Any] = []
    for column in columns:
        value = row[column]
        if table == "evidence_items" and column == "metadata" and isinstance(value, dict):
            value = dict(value)
            if "source_capture" in value:
                # Imported metadata is historical provenance, not a receipt
                # produced by this instance's URL fetch boundary.
                value["imported_source_capture"] = value.pop("source_capture")
        if column in json_fields:
            value = json_dumps(value)
        elif column in bool_fields:
            if type(value) is not bool and not (type(value) is int and value in (0, 1)):
                raise ValidationError(f"imported {column} must be a boolean")
            value = int(value)
        values.append(value)
    if table == "forecast_questions":
        from forecasting.models import OutcomeSpace
        OutcomeSpace.from_dict(row.get("outcome_space"))
    if table == "forecast_snapshots":
        space = ledger.get_question(row["question_id"]).outcome_space
        if space.censoring is not None:
            from forecasting.censoring import threshold_probability
            threshold_probability(row.get("probability_or_distribution"), space.censoring)
    if table == "resolutions":
        from forecasting.ledger.resolutions import validate_resolution
        question = ledger.get_question(row["question_id"])
        normalized = validate_resolution(
            ledger, question, row.get("outcome"),
            resolution_source=row.get("resolution_source"),
            resolution_source_snapshot_ref=row.get("resolution_source_snapshot_ref"),
            resolution_status=row.get("resolution_status", "confirmed"),
            criteria_satisfied=bool(row.get("criteria_satisfied", True)),
            scoreable=bool(row.get("scoreable", True)), confidence=row.get("confidence"),
            correction_ref=row.get("correction_ref"),
        )
        if "outcome" in columns:
            values[columns.index("outcome")] = json_dumps(normalized)
    if table == "score_records":
        snapshot = ledger.get_snapshot(row["forecast_id"])
        resolution = ledger.get_resolution(row["resolution_id"])
        if snapshot.question_id != row["question_id"] or resolution.question_id != row["question_id"]:
            raise ValidationError("imported score provenance must refer to the same question")
        import math
        for field in ("brier_score", "log_score", "proper_score", "calibration_weight"):
            value = row.get(field)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise ValidationError(f"imported {field} must be a finite number")
        space = ledger.get_question(row["question_id"]).outcome_space
        if space.censoring is not None:
            expected = ledger._score_forecast_payload(snapshot.probability_or_distribution, resolution.outcome, space)
            if row.get("score_rule") != expected["score_rule"] or row.get("calibration_eligible"):
                raise ValidationError("censored score must retain its threshold rule and calibration exclusion")
            if row.get("proper_score") is None or not math.isclose(row["proper_score"], expected["proper_score"], abs_tol=1e-12):
                raise ValidationError("censored score differs from the declared tail probability")
    placeholders = ", ".join("?" for _ in columns)
    conn.execute(
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
        values,
    )
    summary["imported"][_core._PACKET_RECORD_LABELS[table]] += 1
