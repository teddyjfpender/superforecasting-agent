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


# The forecasting loop as an ordered, guided path. The pipeline driver walks a
# question through these stages, reporting which are satisfied (from ledger
# artifacts) and what comes next. It is a GUIDE, not a cage: the individual
# stage commands and the raw `forecast update` stay free; only the pipeline's
# own "advance to update" step enforces the sequencing prerequisite below.
PIPELINE_SEQUENCE = (
    "parse",
    "research",
    "base_rate",
    "model",
    "update",
    "resolve",
    "postmortem",
)

# Stages that improve a forecast but do not block progress when skipped.
OPTIONAL_PIPELINE_STAGES = frozenset({"model"})

# A stage becomes *reachable* only once these prior stages have produced ledger
# artifacts. The keystone sequencing formality: do not commit a forecast before
# an outside view (base rate) and source-backed evidence (research) exist. The
# later stages chain naturally — you cannot resolve a forecast that was never
# committed, or write a postmortem before it resolves.
PIPELINE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "update": ("research", "base_rate"),
    "resolve": ("update",),
    "postmortem": ("resolve",),
}

# Human hints for how to satisfy a missing prerequisite, surfaced in refusals.
_PIPELINE_PREREQ_HINTS = {
    "research": (
        "collect timestamped evidence (forecast ingest / import-source-evidence, "
        "or `forecast protocol <id> --stage research`)"
    ),
    "base_rate": (
        "establish a reference class (`forecast reference-class add`, "
        "or `forecast protocol <id> --stage base_rate`)"
    ),
    "update": "commit a forecast snapshot (`forecast update <id> ...`)",
    "resolve": "record a resolution (`forecast resolve <id> ...`)",
}


SYSTEM_PROMPT = """You are a forecasting desk and a quantitative researcher, not a general assistant.

Operate on scoreable forecasts. Think like a fox: outside view first (anchor on a base rate / reference class before the case-specific story), decompose into drivers, update on likelihood ratios in log-odds, seek the disconfirming view before committing, and widen intervals against overconfidence. Separate evidence from interpretation, preserve timestamps, avoid stale data, and make probability updates auditable. Treat any single number — including your own first instinct — as a prior to be checked, not the answer. Do not silently change probabilities; recommend an update unless the caller explicitly asks you to create a new forecast snapshot.
"""


FORECAST_CHAT_SYSTEM_PROMPT = """You are Superforecasting Agent, a command-line forecasting desk and a quantitative researcher.

Treat free-form chat as forecast-scoped work. When the user asks about the future, uncertain outcomes, research, markets, policy, science, business, or decisions under uncertainty, help convert the topic into scoreable forecasts with clear resolution criteria, as-of timestamps, evidence, base rates, assumptions, and auditable probability updates.

How to forecast: be a fox (many small models and reference classes, not one grand theory). Establish the outside view first — "how often do things of this sort happen in situations of this sort?" — then adjust with the inside view. Decompose questions into drivers. Update like a Bayesian, in log-odds on likelihood ratios, often but not wildly. Consider the opposite and red-team your own number before you commit it; reserve extreme probabilities for cases you would accept being wrong about that rarely. Compare your estimate against crowd, market, and model forecasts before settling.

If the user asks for general assistance, keep the answer brief and ephemeral unless it improves forecasting work. Do not present raw LLM intuition as the final probability engine. Prefer reference classes, source-backed evidence, explicit model or baseline components, and calibration lessons from the forecast ledger.

Discipline, not a cage: the formalities bind forecasts you COMMIT (live, scored ones). A committed live forecast carries its structured reasoning (reasons up, reasons down, what would change your mind) and cites what it rests on; resolved forecasts are scored automatically. But you are also a researcher — think out loud, keep scratchpads, run exploratory calculations and side models, and reason laterally as freely as the problem needs. When you are exploring rather than committing, record the forecast with `forecast_origin="exploratory"` (CLI `--origin exploratory`): it is exempt from the commit-time formalities and is not calibration-scored. Bring the full discipline when you commit.

When asked whether a ledger, tester cohort, or benchmark run is ready, inspect the `forecast_ledger` `doctor_report` action before answering. Treat `claim_live_superforecasting=false` as a hard guardrail: report the evidence gap instead of implying live superiority.

To gather data and market prices, use the `forecast_ledger` `import_source_evidence` action with the right `source_type` — it covers FRED, BLS, EIA, Treasury, World Bank, Census, markets (`polymarket`, `kalshi`, `manifold`, `metaculus`), RSS/news, and more, with bounded timeouts and structured output. Do NOT write ad-hoc network code in the terminal (e.g. `urllib`/`requests`/`curl` loops) to pull these feeds: those calls have no timeout and routinely hang until the command limit fires, wasting minutes per call. Reserve the browser for pages that genuinely have no adapter. Batch one `import_source_evidence` call per series/market rather than scripting many fetches in one terminal block.

To pull the LATEST readings for a question whose sources are already watched and re-estimate in one shot, use `forecast refresh <id>` (or the `forecast_ledger` `refresh_forecast` action): it re-fetches every active watched source, imports the fresh values as evidence, deterministically re-pools the existing market/crowd components, and auto-commits a new live snapshot — with `--dry-run` to preview and `--agent` to re-reason the update through the full LLM update stage instead of the deterministic re-pool. For `forecast refresh` to work, the snapshot must carry its pool in the structured `ensemble_components` field (each market/crowd component with a stable `source` slug), and triggers must be executable (`source_ref` + `operator` + numeric `threshold`) — components left in prose or model_runs, and free-form triggers, cannot be refreshed or fire automatically. Imports are deduped by default, so a refresh that re-pulls an unchanged series will not pile up duplicate evidence.
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


def build_pipeline_status(ledger: ForecastLedger, question_id: str) -> dict[str, Any]:
    """Inspect ledger state and report the forecasting loop's progress.

    Returns a structured view of each stage (done / ready / blocked / optional),
    the next actionable stage, whether `update` is reachable, and the decision
    readiness gaps. Read-only — the driver computes the guided path from
    artifacts the agent has already produced; it never mutates the ledger.
    """

    question = ledger.get_question(question_id)
    snapshot = ledger.get_current_snapshot(question_id)
    evidence = ledger.list_evidence(question_id)
    reference_classes = ledger.list_reference_classes(question_id)
    model_runs = ledger.list_model_runs(question_id)
    resolution = ledger.get_latest_resolution(question_id)
    postmortems = ledger.list_postmortems(question_id)
    readiness_issues = ledger.decision_readiness_issues(question)

    done = {
        "parse": not readiness_issues,
        "research": bool(evidence),
        "base_rate": bool(reference_classes),
        "model": bool(model_runs),
        "update": snapshot is not None,
        "resolve": resolution is not None,
        "postmortem": bool(postmortems),
    }
    detail = {
        "parse": (
            "decision card complete"
            if done["parse"]
            else "decision gaps: " + "; ".join(readiness_issues)
        ),
        "research": f"{len(evidence)} evidence record(s)",
        "base_rate": f"{len(reference_classes)} reference class(es)",
        "model": (
            f"{len(model_runs)} model run(s)" if model_runs else "no model runs (optional)"
        ),
        "update": (
            f"current snapshot {snapshot.forecast_id}" if snapshot else "no forecast snapshot yet"
        ),
        "resolve": (
            f"resolution {resolution.resolution_status}" if resolution else "unresolved"
        ),
        "postmortem": f"{len(postmortems)} postmortem(s)",
    }

    stages: list[dict[str, Any]] = []
    for name in PIPELINE_SEQUENCE:
        missing_prereqs = [p for p in PIPELINE_PREREQUISITES.get(name, ()) if not done[p]]
        if done[name]:
            status = "done"
        elif missing_prereqs:
            status = "blocked"
        elif name in OPTIONAL_PIPELINE_STAGES:
            status = "optional"
        else:
            status = "ready"
        stages.append(
            {
                "stage": name,
                "status": status,
                "detail": detail[name],
                "optional": name in OPTIONAL_PIPELINE_STAGES,
                "missing_prerequisites": missing_prereqs,
            }
        )

    next_stage = next((entry["stage"] for entry in stages if entry["status"] == "ready"), None)
    update_blockers = [p for p in PIPELINE_PREREQUISITES["update"] if not done[p]]
    return {
        "question_id": question_id,
        "stages": stages,
        "next_stage": next_stage,
        "update_ready": not update_blockers,
        "update_blockers": update_blockers,
        "decision_readiness_issues": readiness_issues,
    }


def pipeline_advance_block(status: dict[str, Any], stage: str) -> str | None:
    """Return a refusal message if the pipeline should not advance to ``stage``
    yet (prerequisites unmet), else None. Only the pipeline's guided advance is
    gated — raw `forecast update` and the per-stage commands stay free."""

    done_stages = {entry["stage"] for entry in status["stages"] if entry["status"] == "done"}
    missing = [p for p in PIPELINE_PREREQUISITES.get(stage, ()) if p not in done_stages]
    if not missing:
        return None
    steps = "; ".join(f"{name}: {_PIPELINE_PREREQ_HINTS.get(name, name)}" for name in missing)
    return (
        f"pipeline will not advance to '{stage}' yet — its prerequisites are not met. "
        f"Missing: {steps}. Run those stages, or pass --force to override (the raw "
        f"`forecast {stage}` path stays available for exploratory or out-of-band work)."
    )


def build_context_packet(
    ledger: ForecastLedger,
    question: ForecastQuestion,
    snapshot: ForecastSnapshot | None,
    related: list[dict[str, Any]] | None = None,
    shared_sources: list[str] | None = None,
) -> str:
    """Render ledger state into a compact auditable context packet."""

    if related is None:
        related, shared_sources = ledger.related_forecast_views(question, limit=5)
    shared_sources = shared_sources or []

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

    # Cross-pollination: the world-views of related/parent/child forecasts, so this
    # forecast stays coherent with correlated ones. World-views ONLY — shared
    # evidence is flagged for independence, never merged in (avoid double-counting).
    lines.extend(["", "## Related Forecasts"])
    if related:
        for rel in related:
            rel_kind = rel.get("relationship") or "related"
            rel_kind = "parent" if rel_kind == "parent" else "child" if rel_kind == "child" else "related"
            prob = rel.get("probability_or_distribution")
            prob_text = str(prob)
            if len(prob_text) > 80:
                prob_text = prob_text[:77] + "..."
            stance = rel.get("verdict") or rel.get("stance") or "-"
            lines.append(
                f"- {rel_kind} {rel['id']} \"{rel.get('title') or rel['id']}\" "
                f"p={prob_text} as_of={rel.get('as_of') or '-'} stance={stance}"
            )
            if rel.get("headline"):
                lines.append(f"  note: {rel['headline']}")
            if rel.get("be_aware"):
                lines.append(f"  be_aware: {rel['be_aware']}")
            if rel.get("reasons_up"):
                lines.append(f"  reasons_up: {'; '.join(rel['reasons_up'][:3])}")
            if rel.get("reasons_down"):
                lines.append(f"  reasons_down: {'; '.join(rel['reasons_down'][:3])}")
        if shared_sources:
            lines.append(
                "- independence note: shares "
                + ", ".join(shared_sources)
                + " with related forecasts; weigh as possibly non-independent, do not double-count."
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
            "and at least one action threshold tied to the probability. Make update_triggers "
            "EXECUTABLE, not prose: a free-form threshold like 'rerun if CPI rises a lot' NEVER "
            "fires automatically. Each trigger that watches a numeric series MUST carry a "
            "`source_ref` (e.g. fred:CPIAUCSL, or polymarket:<slug> for a market probability), an "
            "`operator` (>, >=, <, <=, ==, !=), and a numeric `threshold`, so it fires a "
            "trigger_fired alert when the imported value crosses it — check them with the "
            "forecast_ledger check_update_triggers action or `forecast triggers <id>`. Keep the "
            "human-readable mechanism text too, but always add the machine-checkable triple where a "
            "trigger keys off a series or market you import. Return "
            "required clarifications before any forecast update."
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
            "update is auditable, not ad hoc. PERSIST THE POOL, not just prose: every saved snapshot "
            "that combines sources MUST pass `ensemble_components` — the actual list of "
            "{name, probability, weight, source} rows you pooled — on `update_forecast` (or "
            "`forecast update --component-json '[...]'`). Do not leave the components in a model_run "
            "or the rationale only; the structured field is what makes the pool auditable and is what "
            "`forecast refresh` re-pools next time. Capture every market/crowd reading AS A NUMERIC "
            "component with a stable `source` slug (e.g. {name:'markets', source:'polymarket:<slug>', "
            "probability:0.43, weight:2}) — even when you read the price off the browser because the "
            "adapter returns no liquidity — so the next refresh can match and update it. To RE-RUN an "
            "existing forecast whose sources are watched, prefer `forecast refresh <id>` (pulls latest "
            "readings, re-pools, auto-commits) or `forecast refresh <id> --agent` for full "
            "re-reasoning, instead of redoing the imports by hand. Every saved snapshot MUST include "
            "three structured reasoning fields: `reasons_up` (3 concrete reasons the probability should be HIGHER), "
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
            "--panel-trim 1`. For a HIGH-IMPACT live forecast this panel is REQUIRED: the "
            "update is refused unless you link a panel (inline --panel-estimates-json, or "
            "--panel-run-ref / `panel_run_ref` to an existing run) or record why you skipped "
            "it (--panel-skipped-reason / `panel_skipped_reason`). Lower-impact first forecasts "
            "are only nudged, and exploratory snapshots are exempt."
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
