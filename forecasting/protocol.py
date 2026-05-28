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

To gather data and market prices, use the `forecast_ledger` `import_source_evidence` action with the right `source_type` — it covers FRED, BLS, EIA, Treasury, World Bank, Census, markets (`polymarket`, `kalshi`, `manifold`, `metaculus`), RSS/news, and more, with bounded timeouts and structured output. Do NOT write ad-hoc network code in the terminal (e.g. `urllib`/`requests`/`curl` loops) to pull these feeds: those calls have no timeout and routinely hang until the command limit fires, wasting minutes per call. Reserve the browser for pages that genuinely have no adapter. Batch one `import_source_evidence` call per series/market rather than scripting many fetches in one terminal block.
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

    readiness_issues = ledger.decision_readiness_issues(question)
    triggers_render = (
        "; ".join(
            t.get("mechanism", "")
            + (f" [{t.get('threshold')}]" if t.get("threshold") else "")
            for t in question.update_triggers
        )
        if question.update_triggers
        else "-"
    )
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
        "## Decision Card",
        f"decision_owner: {question.decision_owner or '-'}",
        f"decision_deadline: {question.decision_deadline or '-'}",
        f"action_threshold: {question.action_threshold or '-'}",
        f"update_triggers: {triggers_render}",
        f"decision_readiness_issues: {', '.join(readiness_issues) if readiness_issues else 'none'}",
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
                f"reasons_up: {'; '.join(snapshot.reasons_up) if snapshot.reasons_up else '-'}",
                f"reasons_down: {'; '.join(snapshot.reasons_down) if snapshot.reasons_down else '-'}",
                f"change_my_mind: {'; '.join(snapshot.change_my_mind) if snapshot.change_my_mind else '-'}",
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
            "Audit whether the question is scoreable AND decision-relevant. Identify "
            "ambiguities, outcome-space issues, and missing resolution criteria. Then audit "
            "the decision card shown above: list any missing decision_owner, decision_deadline, "
            "action_threshold, or update_triggers. A forecast that does not inform a concrete "
            "decision is entertainment, not work — refuse to advance without a decision owner "
            "and at least one action threshold tied to the probability. Return required "
            "clarifications before any forecast update."
        ),
        "research": (
            "Identify evidence gaps and propose timestamped evidence to collect. Distinguish facts, "
            "estimates, rumors, opinions, and assumptions. Do not update the probability. Pull data and "
            "market prices with the forecast_ledger import_source_evidence action (source_type fred/bls/"
            "eia/treasury/polymarket/kalshi/manifold/metaculus/rss/...), which is bounded and structured — "
            "do not write ad-hoc urllib/requests/curl fetches in the terminal, which hang until the command "
            "timeout and waste minutes per call."
        ),
        "base_rate": (
            "Propose reference classes with inclusion/exclusion criteria, base-rate estimates, "
            "uncertainty, and source requirements. When several reference classes compete, blend "
            "them by applicability with the forecast_ledger bayes action "
            "(bayes_action='blend_base_rates') instead of eyeballing a single class. For rare or "
            "high-stakes events, decompose the target into a causal chain "
            "P(A) · P(B|A) · P(C|A,B) and run bayes_action='conditional_chain' — it MUST be "
            "called with an `unconditional_estimate` (a separately-elicited gut/outside-view "
            "probability) so the chain product is sanity-checked instead of accepted on faith."
        ),
        "model": (
            "Suggest quantitative models or Bayesian updates that would improve the forecast. "
            "Specify inputs, parameters, diagnostics, and evidence cutoff requirements. Use the "
            "forecast_ledger bayes action for the auditable building blocks: 'evidence_weight' to "
            "turn a source into a likelihood ratio (separating reliability from relevance and "
            "discounting correlated/biased signal), 'poll_to_prob'/'polls' for poll→probability, "
            "'devig'/'combine_markets' to de-vig prediction markets, and 'evidence_cluster' to "
            "avoid double-counting sources that trace back to one signal."
        ),
        "update": (
            "Prepare a forecast update preview. Show previous probability, proposed probability, "
            "delta, component weights, key evidence, assumptions, calibration lessons used, and an "
            "as-of timestamp. Combine disagreeing sources with the Bayesian toolkit rather than a "
            "naive average: pool in log-odds space (forecast_ledger bayes_action='combine', "
            "method='log_odds_pool', with correlation_matrix='estimate' when sources overlap), or "
            "apply likelihood ratios to the prior (bayes_action='lr_update'). The same pooling is "
            "available natively via `forecast update --method log_odds_pool --extremize <f> "
            "--correlation estimate`. After moving the probability, decompose the change with "
            "bayes_action='forecast_diff' and stress-test it with bayes_action='sensitivity' so the "
            "update is auditable, not ad hoc. Every saved snapshot MUST include three structured "
            "reasoning fields: `reasons_up` (3 concrete reasons the probability should be HIGHER), "
            "`reasons_down` (3 concrete reasons the probability should be LOWER), and "
            "`change_my_mind` (the specific observations/data that would force a material update). "
            "These prevent narrative collapse — pass them as repeated --reason-up / --reason-down / "
            "--change-my-mind flags, or as `reasons_up`/`reasons_down`/`change_my_mind` arrays in "
            "the agent tool. On the CLI, `--require-structured-reasoning` enforces this; on "
            "`update_forecast`, the boolean `require_structured_reasoning` has the same effect. "
            "For high-impact questions or the first forecast on a question, run a forecast PANEL: "
            "use the forecast_ledger `panel_perspectives` action to fetch the 5 constrained "
            "framings (outside, inside, market, red_team, sanity), produce one estimate per "
            "perspective silently, then call `record_panel` to aggregate via trimmed geomean of "
            "odds (default trim=1) and attach the panel artifact to the snapshot. The CLI "
            "equivalent is `forecast update <id> --panel-estimates-json '[...]' "
            "--panel-trim 1`."
        ),
        "resolve": (
            "Check whether the resolution criteria are satisfied. Propose resolution status, source snapshot needs, "
            "and whether the outcome is scoreable. Do not score disputed or unconfirmed resolutions."
        ),
        "postmortem": (
            "Diagnose the resolved forecast. Compare expected vs actual outcome, missed or "
            "overweighted evidence, base-rate error, inside-view error, resolution error, and "
            "reusable calibration lesson. Assign a `failure_class` so the domain error profile "
            "can aggregate the failure mode: one of base_rate, inside_view, definition, timing, "
            "aggregation, motivated_reasoning, tail, noise, other. 'Noise' means the miss was "
            "within expected error of a well-calibrated forecast; everything else is a reusable "
            "lesson. Pass `--failure-class <name>` to the CLI or `failure_class` to the "
            "forecast_ledger postmortem action."
        ),
        "self_check": (
            "Inspect stale beliefs, upcoming close/resolution dates, invalidated assumptions, and domain error patterns. "
            "Use the forecast_ledger doctor_report action for tester or benchmark readiness checks, and create review "
            "recommendations without silently changing probabilities or claiming live superiority."
        ),
    }
    return tasks[stage]
