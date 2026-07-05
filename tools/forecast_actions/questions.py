"""Question lifecycle actions (create/spec/decision/config).

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

from forecasting.models import OutcomeSpace
from forecasting.search import match_to_dict, search_forecasts
from tools.registry import tool_error, tool_result
from typing import Any
from tools.forecasting_tool import _DUPLICATE_WARN_SCORE, _find_possible_duplicates, _question_dict, _required, _show_question_payload

def create_question(args: dict[str, Any], ledger) -> str:
    question = ledger.create_question(
        title=args.get("title") or "",
        description=args.get("description") or "",
        resolution_criteria=args.get("resolution_criteria") or "",
        resolution_source=args.get("resolution_source"),
        domain=args.get("domain"),
        outcome_space=OutcomeSpace(
            type=args.get("outcome_type") or "binary",
            choices=args.get("choices") or ["yes", "no"],
            units=args.get("units"),
            bounds=args.get("bounds"),
        ),
        close_time=args.get("close_time"),
        resolution_time=args.get("resolution_time"),
        tags=args.get("tags") or [],
        topics=args.get("topics") or [],
        owner=args.get("owner"),
        impact=args.get("impact"),
        review_cadence=args.get("review_cadence"),
        next_review_at=args.get("next_review_at"),
        decision_owner=args.get("decision_owner"),
        decision_deadline=args.get("decision_deadline"),
        action_threshold=args.get("action_threshold"),
        update_triggers=args.get("update_triggers"),
    )
    return tool_result(
        success=True,
        question=_question_dict(question),
        decision_readiness_issues=ledger.decision_readiness_issues(question),
    )

def propose_spec(args: dict[str, Any], ledger) -> str:
    from forecasting.question_spec import (
        apply_recommended_defaults,
        recommended_clarifications,
        spec_from_dict,
        spec_quality,
        suggest_resolution_rule,
    )

    raw = dict(args.get("spec") or {})
    if not raw.get("title") and args.get("prompt"):
        raw["title"] = str(args.get("prompt"))
    spec = spec_from_dict(raw)

    # Accept-defaults fast path: a vague/casual ask (accept_defaults=true, or a
    # 'full'-autonomy spec) auto-applies the recommended default of every
    # gap/error clarification so the agent commits in one shot instead of
    # interrogating. Error-severity issues still surface below and block.
    accept_defaults = bool(args.get("accept_defaults")) or spec.autonomy == "full"
    applied_defaults: list[dict[str, Any]] = []
    if accept_defaults:
        spec, applied_defaults = apply_recommended_defaults(spec)

    issues = [issue.to_dict() for issue in spec.validate()]

    return tool_result(
        success=True,
        spec=spec.to_dict(),
        issues=issues,
        errors=[i for i in issues if i["severity"] == "error"],
        readiness_gaps=[i for i in issues if i["severity"] == "gap"],
        recommended_clarifications=recommended_clarifications(spec),
        committable=spec.is_committable(),
        spec_quality=spec_quality(spec),
        accept_defaults=accept_defaults,
        applied_defaults=applied_defaults,
        # Reuse the existing ranker to surface near-duplicates so the agent
        # can refresh an existing question instead of forking a rival one.
        possible_duplicates=_find_possible_duplicates(ledger, spec.title),
        suggested_resolution_rule=suggest_resolution_rule(spec),
    )

def commit_spec(args: dict[str, Any], ledger) -> str:
    from forecasting.question_spec import (
        apply_recommended_defaults,
        spec_from_dict,
        spec_quality,
    )

    spec = spec_from_dict(args.get("spec") or {})

    # Accept-defaults fast path (see propose_spec): fill every gap/error
    # clarification's recommended default and commit in one shot. Only
    # error-severity issues still block — the gate below is unchanged.
    accept_defaults = bool(args.get("accept_defaults")) or spec.autonomy == "full"
    applied_defaults: list[dict[str, Any]] = []
    if accept_defaults:
        spec, applied_defaults = apply_recommended_defaults(spec)

    errs = [issue.to_dict() for issue in spec.errors()]
    if errs:
        return tool_error(
            "question spec is not committable: "
            + "; ".join(f"{e['field']}: {e['message']}" for e in errs),
            success=False,
            issues=errs,
            spec_quality=spec_quality(spec),
            applied_defaults=applied_defaults,
        )
    # Surface (never block on) a strong near-duplicate BEFORE committing, so
    # the operator can choose to refresh the existing question instead.
    duplicates = _find_possible_duplicates(ledger, spec.title)
    quality = spec_quality(spec)
    result = spec.commit(ledger)
    result["spec_quality"] = quality
    result["accept_defaults"] = accept_defaults
    result["applied_defaults"] = applied_defaults
    if duplicates:
        result["possible_duplicates"] = duplicates
        top = duplicates[0]
        if top["score"] >= _DUPLICATE_WARN_SCORE:
            result["duplicate_warning"] = (
                f"you already track {top['id']} (\"{top['title']}\") — "
                "consider refreshing that instead of committing a rival question"
            )

    return tool_result(success=True, **result)

def set_decision(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    question = ledger.update_question_decision(
        question_id,
        decision_owner=args.get("decision_owner"),
        decision_deadline=args.get("decision_deadline"),
        action_threshold=args.get("action_threshold"),
        update_triggers=args.get("update_triggers"),
    )
    return tool_result(
        success=True,
        question=_question_dict(question),
        decision_readiness_issues=ledger.decision_readiness_issues(question),
    )

def configure(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    kwargs: dict = {}
    if args.get("review_cadence") is not None:
        kwargs["review_cadence"] = args.get("review_cadence")
    # Decision-card fields (only the ones actually passed, so None=leave).
    decision = {
        k: args[k]
        for k in ("decision_owner", "decision_deadline", "action_threshold", "update_triggers")
        if args.get(k) is not None
    }
    if decision:
        kwargs["decision"] = decision
    if isinstance(args.get("hooks"), dict):
        kwargs["hooks"] = args["hooks"]
    ledger.update_question_config(question_id, **kwargs)
    config = ledger.resolve_question_config(question_id)
    return tool_result(success=True, config=config)

def keep_fresh(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    cadence = str(args.get("cadence") or "daily").strip()
    ledger.update_question_config(question_id, review_cadence=cadence)
    from forecasting.scheduler import ensure_default_routines

    db_path = getattr(ledger, "db_path", None)
    routines = ensure_default_routines(
        db_path=str(db_path) if db_path else None, force=True
    )
    # ensure_default_routines already tells us everything: it INSTALLED the
    # cron this call (created) or found it already PRESENT — no separate
    # pre-check needed.
    cron_state = "installed" if routines.get("created") else "present"
    return tool_result(
        success=True,
        question_id=question_id,
        cadence=cadence,
        cron=cron_state,
        message=f"this question refreshes {cadence}; nightly cron {cron_state}",
        config=ledger.resolve_question_config(question_id),
        default_routines=routines,
    )

def rename_question(args: dict[str, Any], ledger) -> str:
    question_id = _required(args, "question_id")
    new_title = _required(args, "title")
    question = ledger.rename_question(question_id, new_title, actor=args.get("actor"))
    return tool_result(
        success=True,
        question=_question_dict(question),
        renamed_to=question.title,
    )

def list_questions(args: dict[str, Any], ledger) -> str:
    questions = ledger.list_questions(status=args.get("status"), domain=args.get("domain"))
    return tool_result(success=True, questions=[_question_dict(q) for q in questions])

def search_questions(args: dict[str, Any], ledger) -> str:
    matches = search_forecasts(
        ledger,
        _required(args, "query"),
        status=args.get("status") or "active",
        domain=args.get("domain"),
        topic=args.get("topic"),
        limit=int(args["limit"]) if args.get("limit") is not None else 20,
    )
    return tool_result(
        success=True,
        query=args.get("query"),
        matches=[match_to_dict(match) for match in matches],
    )

def show_question(args: dict[str, Any], ledger) -> str:
    return _show_question_payload(ledger, args)

def create_trusted_resolver_policy(args: dict[str, Any], ledger) -> str:
    policy = ledger.create_trusted_resolver_policy(
        resolver_plugin=_required(args, "resolver_plugin"),
        plugin_version=args.get("plugin_version"),
        scope_type=_required(args, "scope_type"),
        scope_ref=args.get("scope_ref"),
        enabled=bool(args.get("enabled", False)),
        approved_by=args.get("approved_by"),
        audit_log_ref=args.get("audit_log_ref"),
    )
    return tool_result(success=True, trusted_resolver_policy=policy)

def list_trusted_resolver_policies(args: dict[str, Any], ledger) -> str:
    policies = ledger.list_trusted_resolver_policies(
        resolver_plugin=args.get("resolver_plugin"),
        scope_type=args.get("scope_type"),
        enabled=args.get("enabled"),
    )
    return tool_result(success=True, trusted_resolver_policies=policies)


HANDLERS = {
    "create_question": create_question,
    "propose_spec": propose_spec,
    "commit_spec": commit_spec,
    "set_decision": set_decision,
    "configure": configure,
    "keep_fresh": keep_fresh,
    "rename_question": rename_question,
    "list_questions": list_questions,
    "search_questions": search_questions,
    "show_question": show_question,
    "create_trusted_resolver_policy": create_trusted_resolver_policy,
    "list_trusted_resolver_policies": list_trusted_resolver_policies,
}
