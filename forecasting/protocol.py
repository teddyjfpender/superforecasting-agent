"""Forecasting protocol prompt builder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastQuestion, ForecastSnapshot


PROTOCOL_STAGES = {
    "parse",
    "research",
    "base_rate",
    "model",
    "update",
    "resolve",
    "postmortem",
    "self_check",
}


SYSTEM_PROMPT = """You are a forecasting desk, not a general assistant.

Operate on scoreable forecasts. Use base rates first, separate evidence from interpretation, preserve timestamps, avoid stale data, and make probability updates auditable. Do not silently change probabilities; recommend an update unless the caller explicitly asks you to create a new forecast snapshot.
"""


FORECAST_CHAT_SYSTEM_PROMPT = """You are Superforecasting Agent, a command-line forecasting desk.

Treat free-form chat as forecast-scoped work. When the user asks about the future, uncertain outcomes, research, markets, policy, science, business, or decisions under uncertainty, help convert the topic into scoreable forecasts with clear resolution criteria, as-of timestamps, evidence, base rates, assumptions, and auditable probability updates.

If the user asks for general assistance, keep the answer brief and ephemeral unless it improves forecasting work. Do not present raw LLM intuition as the final probability engine. Prefer reference classes, source-backed evidence, explicit model or baseline components, and calibration lessons from the forecast ledger.

When asked whether a ledger, tester cohort, or benchmark run is ready, inspect the `forecast_ledger` `doctor_report` action before answering. Treat `claim_live_superforecasting=false` as a hard guardrail: report the evidence gap instead of implying live superiority.
"""


@dataclass(frozen=True)
class ProtocolMessage:
    role: str
    content: str


def build_forecast_chat_system_prompt(extra_prompt: str | None = None) -> str:
    """Return the default forecast-scoped chat prompt plus user overlays."""

    extra = (extra_prompt or "").strip()
    if not extra:
        return FORECAST_CHAT_SYSTEM_PROMPT.strip()
    return "\n\n".join(
        [
            FORECAST_CHAT_SYSTEM_PROMPT.strip(),
            "## User Or Session Instructions",
            extra,
        ]
    )


def build_protocol_messages(
    ledger: ForecastLedger,
    question_id: str,
    *,
    stage: str,
) -> list[ProtocolMessage]:
    """Build stage-specific messages for a forecast-native agent pass."""

    if stage not in PROTOCOL_STAGES:
        raise ValueError(f"stage must be one of {', '.join(sorted(PROTOCOL_STAGES))}")
    question = ledger.get_question(question_id)
    snapshot = ledger.get_current_snapshot(question_id)
    context = build_context_packet(ledger, question, snapshot)
    task = _stage_task(stage)
    return [
        ProtocolMessage(role="system", content=SYSTEM_PROMPT.strip()),
        ProtocolMessage(role="user", content=f"{context}\n\n## Stage Task\n{task}"),
    ]


def build_context_packet(
    ledger: ForecastLedger,
    question: ForecastQuestion,
    snapshot: ForecastSnapshot | None,
) -> str:
    """Render ledger state into a compact auditable context packet."""

    evidence = ledger.list_evidence(question.id)
    assumptions = ledger.list_assumptions(question.id)
    reference_classes = ledger.list_reference_classes(question.id)
    model_runs = ledger.list_model_runs(question.id)
    watched_sources = ledger.list_watched_sources(scope_type="question", scope_ref=question.id, status="active")
    open_alerts = [
        alert
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.scope_type == "question" and alert.scope_ref == question.id
    ]
    lessons = (
        ledger.list_calibration_lessons(scope_type="domain", scope_ref=question.domain, active_only=True)
        if question.domain
        else []
    )
    error_profiles = ledger.list_domain_error_profiles(domain=question.domain) if question.domain else []

    lines = [
        "## Forecast Context",
        f"id: {question.id}",
        f"title: {question.title}",
        f"status: {question.status}",
        f"domain: {question.domain or '-'}",
        f"topics: {', '.join(question.topics) if question.topics else '-'}",
        f"close_time: {question.close_time or '-'}",
        f"resolution_time: {question.resolution_time or '-'}",
        f"resolution_criteria: {question.resolution_criteria}",
        f"outcome_space: {question.outcome_space.to_dict()}",
        "",
        "## Current Forecast",
    ]
    if snapshot:
        lines.extend(
            [
                f"forecast_id: {snapshot.forecast_id}",
                f"as_of: {snapshot.as_of}",
                f"probability_or_distribution: {snapshot.probability_or_distribution}",
                f"confidence: {snapshot.confidence if snapshot.confidence is not None else '-'}",
                f"forecast_origin: {snapshot.forecast_origin}",
                f"calibration_eligible: {snapshot.calibration_eligible}",
                f"rationale: {snapshot.rationale}",
            ]
        )
    else:
        lines.append("none")

    lines.extend(["", "## Evidence"])
    if evidence:
        for item in evidence[-10:]:
            source = item.source_url or item.source_name or item.source_type
            lines.append(
                f"- {item.id} available_at={item.available_at} stance={item.stance} "
                f"claim_type={item.claim_type} "
                f"reliability={item.reliability_rating} relevance={item.relevance_rating} "
                f"source={source} claim={item.claim or item.summary}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Assumptions"])
    lines.extend(_render_rows(assumptions, "text", "status"))

    lines.extend(["", "## Reference Classes"])
    if reference_classes:
        for item in reference_classes:
            lines.append(
                f"- {item['id']} {item['name']} base_rate={item['base_rate']} "
                f"uncertainty={item['base_rate_uncertainty']} status={item['status']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Model Runs"])
    if model_runs:
        for item in model_runs[-5:]:
            lines.append(f"- {item['id']} type={item['model_type']} output={item['output']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Watched Sources"])
    if watched_sources:
        for item in watched_sources:
            lines.append(f"- {item['id']} type={item['source_type']} source={item['source']} checked={item['last_checked_at'] or '-'}")
    else:
        lines.append("- none")

    lines.extend(["", "## Open Alerts"])
    if open_alerts:
        for item in open_alerts[-10:]:
            lines.append(f"- {item.id} severity={item.severity} reason={item.reason} action={item.recommended_action}")
    else:
        lines.append("- none")

    lines.extend(["", "## Calibration Lessons"])
    if lessons:
        for item in lessons:
            lines.append(
                f"- {item['id']} status={item['status']} confidence={item['confidence']} "
                f"lesson={item['lesson']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Domain Error Profiles"])
    if error_profiles:
        for item in error_profiles:
            lines.append(
                f"- {item['id']} n={item['sample_count']} "
                f"errors={item['recurring_errors']} adjustments={item['recommended_adjustments']}"
            )
    else:
        lines.append("- none")

    return "\n".join(lines)


def _render_rows(rows: list[dict[str, Any]], primary: str, status: str) -> list[str]:
    if not rows:
        return ["- none"]
    return [f"- {row['id']} {row.get(status, '-')}: {row.get(primary, '')}" for row in rows]


def _stage_task(stage: str) -> str:
    tasks = {
        "parse": (
            "Audit whether the question is scoreable. Identify ambiguities, outcome-space issues, "
            "and missing resolution criteria. Return required clarifications before any forecast update."
        ),
        "research": (
            "Identify evidence gaps and propose timestamped evidence to collect. Distinguish facts, "
            "estimates, rumors, opinions, and assumptions. Do not update the probability."
        ),
        "base_rate": (
            "Propose reference classes with inclusion/exclusion criteria, base-rate estimates, "
            "uncertainty, and source requirements."
        ),
        "model": (
            "Suggest quantitative models or Bayesian updates that would improve the forecast. "
            "Specify inputs, parameters, diagnostics, and evidence cutoff requirements."
        ),
        "update": (
            "Prepare a forecast update preview. Show previous probability, proposed probability, "
            "delta, component weights, key evidence, assumptions, calibration lessons used, and an as-of timestamp."
        ),
        "resolve": (
            "Check whether the resolution criteria are satisfied. Propose resolution status, source snapshot needs, "
            "and whether the outcome is scoreable. Do not score disputed or unconfirmed resolutions."
        ),
        "postmortem": (
            "Diagnose the resolved forecast. Compare expected vs actual outcome, missed or overweighted evidence, "
            "base-rate error, inside-view error, resolution error, and reusable calibration lesson."
        ),
        "self_check": (
            "Inspect stale beliefs, upcoming close/resolution dates, invalidated assumptions, and domain error patterns. "
            "Use the forecast_ledger doctor_report action for tester or benchmark readiness checks, and create review "
            "recommendations without silently changing probabilities or claiming live superiority."
        ),
    }
    return tasks[stage]
