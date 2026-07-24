"""Evidence, baselines, assumptions, reference-classes and forecast-links.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from tools.registry import tool_result
from typing import Any
from tools.forecasting_tool import _adapter_item_dict, _import_source_evidence_batch_payload, _required, _source_adapter_evidence_payload
from tools import forecasting_tool as _ft

def add_evidence(args: dict[str, Any], ledger) -> str:
    item = ledger.add_evidence(
        question_id=_required(args, "question_id"),
        source_or_note=_required(args, "source_or_note"),
        claim=args.get("claim") or "",
        source_url=args.get("source_url"),
        source_name=args.get("source_name"),
        source_type=args.get("source_type"),
        published_at=args.get("published_at"),
        claim_type=args.get("claim_type") or "fact",
        summary=args.get("summary") or "",
        available_at=args.get("available_at"),
        reliability_rating=args.get("reliability_rating"),
        relevance_rating=args.get("relevance_rating"),
        stance=args.get("stance") or "context",
        snapshot_path=args.get("snapshot_path"),
        admissible_for_backtests=bool(args.get("admissible_for_backtests", True)),
        metadata=args.get("metadata") or {},
    )
    try:
        from forecasting.writeup import write_brief

        _qid = args.get("question_id")
        write_brief(
            ledger,
            _qid,
            ledger.get_current_snapshot(_qid),
            evidence_only=True,
            main_runtime=args.get("_main_runtime"),
        )
    except Exception:
        pass
    return tool_result(success=True, evidence=item.__dict__)

def import_source_evidence(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    adapter = _required(args, "source_type")
    source = _required(args, "source")
    dedupe = bool(args.get("dedupe", True))
    seen_keys = ledger.existing_evidence_keys(question_id) if dedupe else set()
    # Inherit the per-source reliability prior set during onboarding when
    # the caller didn't pass an explicit rating, so imported readings
    # carry the user's stated confidence in that source.
    _watch_type = adapter.removeprefix("adapter:").strip().lower()
    _default_prior: float | None = None
    try:
        for _w in ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active"):
            if _w.get("source") == source and (_w.get("source_type") or "").lower() == _watch_type:
                _prior = (_w.get("metadata") or {}).get("reliability_prior")
                if isinstance(_prior, (int, float)):
                    _default_prior = float(_prior)
                break
    except Exception:
        _default_prior = None
    imported = []
    skipped_duplicates = 0
    for item in _ft._load_source_adapter_items(adapter, source, args):
        evidence_payload = _source_adapter_evidence_payload(adapter, source, item, args)
        if _default_prior is not None and evidence_payload.get("reliability_rating") is None:
            evidence_payload["reliability_rating"] = _default_prior
        # Skip a structured reading already imported for this question
        # (same source_type + entry_id) so repeated refreshes don't bloat
        # the evidence table with identical observations.
        entry_id = (evidence_payload.get("metadata") or {}).get("entry_id")
        dedupe_key = (evidence_payload.get("source_type") or "", str(entry_id)) if entry_id else None
        if dedupe and dedupe_key and dedupe_key in seen_keys:
            skipped_duplicates += 1
            continue
        # Structured adapters already capture the observation (the raw
        # series value lives in metadata); fetching the source's HTML
        # page to archive a snapshot adds ~5s/row of latency and no data
        # value, which surfaced to the agent as "FRED refresh timed out".
        # Skip the per-row URL snapshot on this batch import path.
        evidence = ledger.add_evidence(
            question_id=question_id,
            archive_url_snapshot=False,
            **evidence_payload,
        )
        if dedupe_key:
            seen_keys.add(dedupe_key)
        imported.append(
            {
                "evidence": evidence.__dict__,
                "adapter_item": _adapter_item_dict(item),
            }
        )
    watch: dict[str, Any] | None = None
    watch_note: str | None = None
    if imported and bool(args.get("auto_watch")):
        watch_type = adapter.removeprefix("adapter:").strip().lower()
        try:
            existing = ledger.list_watched_sources(
                scope_type="question", scope_ref=question_id, status="active"
            )
        except Exception:
            existing = []
        duplicate = next(
            (
                w
                for w in existing
                if w.get("source") == source and (w.get("source_type") or "").lower() == watch_type
            ),
            None,
        )
        if duplicate:
            watch = duplicate
            watch_note = "already watched (no-op)"
        else:
            try:
                watch = ledger.add_watched_source(
                    scope_type="question",
                    scope_ref=question_id,
                    source=source,
                    source_type=watch_type,
                    metadata={"auto_watch": True, "from_action": "import_source_evidence"},
                )
                watch_note = "attached"
            except Exception as exc:
                # Don't fail the import if watching has constraints we can't meet
                # (e.g. source_type outside WATCH_SOURCE_TYPES); surface a note.
                watch_note = f"auto_watch skipped: {exc}"
    return tool_result(
        success=True,
        source_type=adapter,
        source=source,
        imported_count=len(imported),
        skipped_duplicates=skipped_duplicates,
        imported=imported,
        watched_source=watch,
        auto_watch_note=watch_note,
    )

def import_source_evidence_batch(args: dict[str, Any], ledger) -> str:
    return _import_source_evidence_batch_payload(ledger, args)

def add_baseline_comparison(args: dict[str, Any], ledger) -> str:
    baseline = ledger.add_baseline_comparison(
        question_id=_required(args, "question_id"),
        source=_required(args, "source"),
        baseline_type=args.get("baseline_type") or "imported",
        probability_or_distribution=args.get("probability_or_distribution", args.get("probability")),
        as_of=args.get("as_of"),
        forecast_id=args.get("forecast_id"),
        backtest_case_id=args.get("backtest_case_id"),
        score_record_id=args.get("score_record_id"),
        metadata=args.get("metadata") or {},
    )
    return tool_result(success=True, baseline_comparison=baseline)

def list_baseline_comparisons(args: dict[str, Any], ledger) -> str:
    baselines = ledger.list_baseline_comparisons(_required(args, "question_id"))
    return tool_result(success=True, baseline_comparisons=baselines)

def add_assumption(args: dict[str, Any], ledger) -> str:
    assumption = ledger.add_assumption(
        question_id=_required(args, "question_id"),
        text=_required(args, "text"),
        status=args.get("status") or "active",
        check_cadence=args.get("check_cadence"),
        evidence_refs=args.get("evidence_refs") or [],
        notes=args.get("notes"),
    )
    return tool_result(success=True, assumption=assumption)

def list_assumptions(args: dict[str, Any], ledger) -> str:
    assumptions = ledger.list_assumptions(_required(args, "question_id"))
    return tool_result(success=True, assumptions=assumptions)

def update_assumption(args: dict[str, Any], ledger) -> str:
    assumption = ledger.update_assumption(
        _required(args, "assumption_id"),
        status=args.get("status"),
        last_checked_at=args.get("last_checked_at"),
        invalidated_at=args.get("invalidated_at"),
        notes=args.get("notes"),
    )
    return tool_result(success=True, assumption=assumption)

def add_reference_class(args: dict[str, Any], ledger) -> str:
    reference_class = ledger.add_reference_class(
        question_id=_required(args, "question_id"),
        name=_required(args, "name"),
        inclusion_criteria=_required(args, "inclusion_criteria"),
        exclusion_criteria=args.get("exclusion_criteria") or "",
        base_rate=args.get("base_rate"),
        base_rate_uncertainty=args.get("uncertainty"),
        source_refs=args.get("source_refs") or [],
        check_cadence=args.get("check_cadence"),
        notes=args.get("notes"),
        sample_size=args.get("sample_size"),
    )
    model_run = ledger.record_model_run(
        question_id=_required(args, "question_id"),
        model_type="base_rate",
        inputs={
            "reference_class_id": reference_class["id"],
            "inclusion_criteria": reference_class["inclusion_criteria"],
            "exclusion_criteria": reference_class["exclusion_criteria"],
        },
        output={
            "base_rate": reference_class["base_rate"],
            "uncertainty": reference_class["base_rate_uncertainty"],
        },
        diagnostics={"source_refs": reference_class["source_refs"]},
    )
    return tool_result(success=True, reference_class=reference_class, model_run=model_run)

def list_reference_classes(args: dict[str, Any], ledger) -> str:
    reference_classes = ledger.list_reference_classes(_required(args, "question_id"))
    return tool_result(success=True, reference_classes=reference_classes)

def update_reference_class(args: dict[str, Any], ledger) -> str:
    reference_class = ledger.update_reference_class(
        _required(args, "reference_class_id"),
        status=args.get("status"),
        last_checked_at=args.get("last_checked_at"),
        invalidated_at=args.get("invalidated_at"),
        check_cadence=args.get("check_cadence"),
        notes=args.get("notes"),
    )
    return tool_result(success=True, reference_class=reference_class)

def link_forecasts(args: dict[str, Any], ledger) -> str:
    link = ledger.add_forecast_link(
        _required(args, "from_question_id"),
        _required(args, "to_question_id"),
        link_type=args.get("link_type") or "related",
        rationale=args.get("rationale") or "",
        created_by="agent",
    )
    return tool_result(success=True, link=link)

def list_links(args: dict[str, Any], ledger) -> str:
    related, shared = ledger.related_forecast_views(_required(args, "question_id"))
    links = ledger.list_forecast_links(_required(args, "question_id"))
    return tool_result(success=True, links=links, related=related, shared_sources=shared)

def unlink_forecasts(args: dict[str, Any], ledger) -> str:
    removed = ledger.remove_forecast_link(
        _required(args, "from_question_id"),
        _required(args, "to_question_id"),
        link_type=args.get("link_type"),
    )
    return tool_result(success=True, removed=removed)


HANDLERS = {
    "add_evidence": add_evidence,
    "import_source_evidence": import_source_evidence,
    "import_source_evidence_batch": import_source_evidence_batch,
    "add_baseline_comparison": add_baseline_comparison,
    "list_baseline_comparisons": list_baseline_comparisons,
    "add_assumption": add_assumption,
    "list_assumptions": list_assumptions,
    "update_assumption": update_assumption,
    "add_reference_class": add_reference_class,
    "list_reference_classes": list_reference_classes,
    "update_reference_class": update_reference_class,
    "link_forecasts": link_forecasts,
    "list_links": list_links,
    "unlink_forecasts": unlink_forecasts,
}
