"""Shared forecast-stage orchestration for tools, jobs and command adapters."""

from __future__ import annotations

from typing import Any, Callable, Sequence

from forecasting.ledger import ForecastLedger
from forecasting.protocol import build_pipeline_status


def _truncate_response(value: str) -> str:
    return value if len(value) <= 200 else value[:197] + "..."


# The default stage chain a lazy prompter's "just forecast this" runs through:
# gather evidence (research) → set an outside view (base_rate) → commit (update).
# `parse` is skipped — commit_spec already structured the question — and the later
# resolve/postmortem stages only run once the world resolves.
AUTO_FORECAST_STAGES: tuple[str, ...] = ("research", "base_rate", "update")


def auto_forecast_stages(question: Any) -> tuple[str, ...]:
    """Resolve the autonomous stage chain for THIS question's outcome shape.

    Numeric/distribution questions get the optional ``model`` stage between
    base_rate and update — a deterministic quant model (time-series trend,
    monte-carlo fan) is exactly what anchors a level/path forecast, and the
    lazy path must not silently skip the leg the machinery supports
    (``OPTIONAL_PIPELINE_STAGES`` already marks ``model`` optional, so a stage
    agent that finds no usable series simply moves on — the chain captures a
    non-committing stage without aborting). Binary/categorical keep the lighter
    3-stage chain: their outside view IS the base_rate stage."""

    outcome = getattr(getattr(question, "outcome_space", None), "type", None)
    if (outcome or "").strip().lower() in {"numeric", "distribution"}:
        return ("research", "base_rate", "model", "update")
    return AUTO_FORECAST_STAGES


def _snapshot_summary(snapshot: Any) -> dict[str, Any] | None:
    """Compact, JSON-safe view of a committed snapshot for chain results."""
    if snapshot is None:
        return None
    return {
        "forecast_id": getattr(snapshot, "forecast_id", None),
        "question_id": getattr(snapshot, "question_id", None),
        "probability_or_distribution": getattr(
            snapshot, "probability_or_distribution", None
        ),
        "rationale": getattr(snapshot, "rationale", None),
        "created_at": getattr(snapshot, "created_at", None),
    }


def _format_research_gaps(audit: dict[str, Any]) -> str:
    """Render a research_audit result's gap list into the supplemental note the
    chain injects when it re-runs the research stage. Prose only."""
    gaps = audit.get("gaps") or []
    lines = [
        f"Your research is not yet adequate (score {audit.get('score')}/100, "
        f"threshold {audit.get('threshold')}). Close these specific gaps with fresh "
        "research + import_source_evidence, then finish:",
    ]
    for gap in gaps:
        detail = str(gap.get("detail") or gap.get("kind") or "").strip()
        queries = gap.get("suggested_queries") or []
        line = f"- {detail}"
        if queries:
            line += (
                " Suggested searches: " + "; ".join(str(q) for q in queries[:3]) + "."
            )
        lines.append(line)
    return "\n".join(lines)


def run_forecast_chain(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
    stages: Sequence[str] | None = None,
    commit_policy: str | None = "commit_material",
    on_stage: Callable[[str, dict[str, Any]], None] | None = None,
    stage_runner: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Drive one question through a sequence of pipeline stages, each via the same
    gated execution adapter (:func:`agent.forecast_stage.run_stage`) a manual ``forecast agent --stage S``
    run uses. This is ORCHESTRATION ONLY — every stage runs the identical
    protocol/toolset/commit path, so the panel gate, analyst brief, and
    scheduled-review side-effects fire unchanged; nothing here weakens or bypasses a
    gate. The chain is what turns a lazy prompter's one committed question row into a
    researched, base-rated, committed forecast.

    A stage that raises is captured (``status="error"``) and the chain CONTINUES: a
    flaky research stage must not abort the run, and the update stage's own commit
    gate still refuses if prerequisites are genuinely missing (so a skipped/failed
    prerequisite surfaces as an un-committed, still-gated result — never a fabricated
    number). ``on_stage(stage, outcome)`` fires after each stage for progress
    reporting.

    Returns ``{question_id, stages:[per-stage outcome], committed, snapshot,
    update_ready, update_blockers}``.
    """
    if stage_runner is None:
        from agent.forecast_stage import run_stage

        stage_runner = run_stage
    if stages is None:
        # Outcome-shape-aware default: numeric/distribution questions include the
        # optional `model` stage so the lazy path gets the deterministic quant leg.
        stages = auto_forecast_stages(ledger.get_question(question_id))
    stage_results: list[dict[str, Any]] = []
    research_audit_final: dict[str, Any] | None = None
    research_audit_rounds = 0
    for stage in stages:
        prior = ledger.get_current_snapshot(question_id)
        outcome: dict[str, Any] = {"stage": stage, "status": "ran", "committed": False}
        try:
            result = stage_runner(
                ledger,
                question_id,
                model=model,
                provider=provider,
                max_iterations=max_iterations,
                stage=stage,
                commit_policy=commit_policy,
            )
        except Exception as exc:  # one bad stage must not abort the chain
            outcome["status"] = "error"
            outcome["detail"] = str(exc)[:200]
        else:
            post = ledger.get_current_snapshot(question_id)
            committed = post is not None and (
                prior is None or post.forecast_id != prior.forecast_id
            )
            outcome["committed"] = committed
            if committed and post is not None:
                outcome["forecast_id"] = post.forecast_id
            response = (
                result.get("final_response") if isinstance(result, dict) else None
            )
            if response:
                outcome["detail"] = _truncate_response(str(response).strip())
        stage_results.append(outcome)
        if on_stage is not None:
            on_stage(stage, outcome)

        # VOI-directed research adequacy loop: after the research stage completes for
        # a LIVE (active) question, audit whether the evidence set covers the levers
        # that would move the forecast (deterministic — NO LLM runner, cheap). If it
        # is inadequate and rounds remain, re-run the research stage ONCE per round
        # with the concrete gap list injected. This is BOUNDED (max_audit_rounds
        # counts EXTRA passes) and fail-open: any audit error simply stops the loop.
        if stage == "research":
            research_audit_rounds, research_audit_final = _run_research_audit_loop(
                ledger,
                question_id,
                model=model,
                provider=provider,
                max_iterations=max_iterations,
                commit_policy=commit_policy,
                on_stage=on_stage,
                stage_results=stage_results,
                stage_runner=stage_runner,
            )

    final = ledger.get_current_snapshot(question_id)
    status = build_pipeline_status(ledger, question_id)
    return {
        "question_id": question_id,
        "stages": stage_results,
        "committed": any(s.get("committed") for s in stage_results),
        "snapshot": _snapshot_summary(final),
        "update_ready": status.get("update_ready"),
        "update_blockers": status.get("update_blockers") or [],
        "research_audit_rounds": research_audit_rounds,
        "research_audit": research_audit_final,
    }


def _run_research_audit_loop(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None,
    provider: str | None,
    max_iterations: int,
    commit_policy: str | None,
    on_stage: Callable[[str, dict[str, Any]], None] | None,
    stage_results: list[dict[str, Any]],
    stage_runner: Callable[..., dict[str, Any]],
) -> tuple[int, dict[str, Any] | None]:
    """Deterministic research-adequacy re-run loop (see run_forecast_chain). Returns
    ``(extra_rounds_run, final_audit)``. Fully fail-open: never raises."""
    from forecasting.research_audit import audit_research, research_stage_incomplete

    try:
        question = ledger.get_question(question_id)
    except Exception:
        return 0, None
    # Only live (active) questions get the extra research passes.
    if getattr(question, "status", None) != "active":
        try:
            return 0, audit_research(ledger, question)
        except Exception:
            return 0, None

    from agent.forecast_stage import research_audit_round_limit

    max_rounds = research_audit_round_limit()

    def _safe_audit(q: Any) -> dict[str, Any] | None:
        try:
            return audit_research(ledger, q)
        except Exception:
            return None

    audit = _safe_audit(question)
    rounds = 0
    # Re-run RESEARCH only for research-stage-controllable gaps (evidence floor,
    # independence, disconfirming, recency, trigger coverage). reference_class is the
    # base_rate stage's job (it runs after this checkpoint), so it never drives a
    # research re-run here.
    while (
        audit is not None and research_stage_incomplete(audit) and rounds < max_rounds
    ):
        rounds += 1
        prev_score = audit.get("score")
        supplemental = _format_research_gaps(audit)
        re_outcome: dict[str, Any] = {
            "stage": "research",
            "status": "ran",
            "committed": False,
            "audit_round": rounds,
            "audit_score": prev_score,
        }
        try:
            result = stage_runner(
                ledger,
                question_id,
                model=model,
                provider=provider,
                max_iterations=max_iterations,
                stage="research",
                commit_policy=commit_policy,
                supplemental=supplemental,
            )
        except Exception as exc:
            re_outcome["status"] = "error"
            re_outcome["detail"] = str(exc)[:200]
        else:
            response = (
                result.get("final_response") if isinstance(result, dict) else None
            )
            if response:
                re_outcome["detail"] = _truncate_response(str(response).strip())
        stage_results.append(re_outcome)
        if on_stage is not None:
            on_stage("research", re_outcome)
        try:
            question = ledger.get_question(question_id)
        except Exception:
            break
        audit = _safe_audit(question)
        # No-progress guard (spend bound): a re-run that did not RAISE the adequacy
        # score won't be helped by another identical pass — stop rather than burn the
        # remaining rounds on research that isn't finding anything.
        if (
            audit is not None
            and research_stage_incomplete(audit)
            and isinstance(audit.get("score"), (int, float))
            and isinstance(prev_score, (int, float))
            and audit["score"] <= prev_score
        ):
            break
    return rounds, audit
