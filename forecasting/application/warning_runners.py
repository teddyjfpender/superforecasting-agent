"""Shared bounded reforecast and evidence runners for warning workflows."""

from __future__ import annotations

from typing import Any, Callable

from forecasting.application.pipeline import run_forecast_chain
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from forecasting.protocol import build_pipeline_status


def build_cycle_reforecast_runner(
    ledger: ForecastLedger,
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
    max_questions: int | None = None,
    force: bool = False,
    commit_policy: str = "commit_material",
    stage_runner: Callable[..., dict[str, Any]] | None = None,
) -> Callable[[list[str]], list[dict[str, Any]]]:
    """Bound expensive work and report only changes present in durable storage.

    Proposal-only execution admits pending proposals, while explicit material
    execution distinguishes material and marginal committed snapshots.
    """
    _validate_limits(max_iterations, max_questions)
    if type(force) is not bool:
        raise ValidationError("force must be a boolean")
    if not isinstance(commit_policy, str) or commit_policy not in {
        "proposal_only",
        "commit_material",
    }:
        raise ValidationError("commit_policy must be proposal_only or commit_material")
    from forecasting.warnings import is_material_move

    if stage_runner is None:
        from agent.forecast_stage import run_stage

        stage_runner = run_stage
    max_iter = max_iterations
    max_q = max_questions

    def _runner(question_ids: list[str]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        processed = (
            0  # questions an LLM run was actually started for (the expensive bit)
        )
        for qid in question_ids:
            if max_q is not None and processed >= max_q:
                results.append({
                    "question_id": qid,
                    "status": "skipped",
                    "detail": f"--max-questions {max_q} reached",
                })
                continue
            try:
                question = ledger.get_question(qid)
            except Exception:
                question = None
            if question is None or getattr(question, "status", None) != "active":
                results.append({
                    "question_id": qid,
                    "status": "skipped",
                    "detail": "not an active question",
                })
                continue
            counted = False  # whether this question already consumed one of the max_q session budgets
            if not force:
                pstatus = build_pipeline_status(ledger, qid)
                if not pstatus.get("update_ready", True):
                    # BOOTSTRAP instead of skip: drive the missing prerequisite
                    # stages (research, then base_rate) through the SAME gated agent
                    # chain, then re-check the gate. This is what lets the cron sweep
                    # re-forecast a FRESH question an operator just dropped in — not
                    # only ones hand-researched already. Skip stays the honest
                    # fallback when bootstrap fails to satisfy the gate.
                    blockers = pstatus.get("update_blockers") or []
                    prereq_stages = [
                        s for s in ("research", "base_rate") if s in blockers
                    ]
                    errored: list[str] = []
                    if prereq_stages:
                        # A bootstrap runs up to 2 real, multi-minute LLM stages, so it
                        # must COUNT against --max-questions the moment it starts —
                        # otherwise a batch of never-ready questions burns 2N uncounted
                        # sessions (each hits `continue` below without incrementing).
                        # Counting here (not after) bounds the expensive work honestly;
                        # `counted` then suppresses the pre-update increment so a
                        # question that bootstraps AND proceeds to update is charged once.
                        processed += 1
                        counted = True
                        # run_forecast_chain captures a raising stage per-stage (it
                        # never re-raises), so the sweep is not aborted by a flaky
                        # bootstrap; a still-closed gate below is the honest fallback.
                        boot = run_forecast_chain(
                            ledger,
                            qid,
                            model=model,
                            provider=provider,
                            max_iterations=max_iter,
                            stages=prereq_stages,
                            commit_policy=commit_policy,
                            stage_runner=stage_runner,
                        )
                        errored = [
                            s["stage"]
                            for s in boot["stages"]
                            if s.get("status") == "error"
                        ]
                        pstatus = build_pipeline_status(ledger, qid)
                    if not pstatus.get("update_ready", True):
                        still = (
                            ", ".join(pstatus.get("update_blockers") or [])
                            or "prerequisites missing"
                        )
                        detail = f"update gated after bootstrap: {still}"
                        if errored:
                            detail += f" (bootstrap stage error: {', '.join(errored)})"
                        results.append({
                            "question_id": qid,
                            "status": "skipped",
                            "detail": detail,
                        })
                        continue
            prior = ledger.get_current_snapshot(qid)
            prior_proposals = (
                {
                    proposal["id"]
                    for proposal in ledger.list_forecast_update_proposals(
                        question_id=qid, status="pending", limit=100
                    )
                }
                if commit_policy == "proposal_only"
                else set()
            )
            # Count BEFORE the agent runs: the cap bounds expensive multi-minute LLM
            # sessions, so a question that ran but declined to commit still counts.
            # A question that already paid for its budget in the bootstrap above
            # (counted=True) is not charged twice.
            if not counted:
                processed += 1
            try:
                stage_runner(
                    ledger,
                    qid,
                    model=model,
                    provider=provider,
                    max_iterations=max_iter,
                    commit_policy=commit_policy,
                )
            except Exception as exc:  # one failure must not abort the sweep
                results.append({
                    "question_id": qid,
                    "status": "error",
                    "detail": str(exc)[:160],
                })
                continue
            post = ledger.get_current_snapshot(qid)
            if commit_policy == "proposal_only":
                proposal = next(
                    (
                        item
                        for item in ledger.list_forecast_update_proposals(
                            question_id=qid, status="pending", limit=100
                        )
                        if item["id"] not in prior_proposals
                    ),
                    None,
                )
                if proposal is not None:
                    results.append({
                        "question_id": qid,
                        "status": "proposed",
                        "detail": f"pending proposal {proposal['id']}; no snapshot committed",
                    })
                else:
                    results.append({
                        "question_id": qid,
                        "status": "skipped",
                        "detail": "agent created no material proposal; no snapshot committed",
                    })
                continue
            new_commit = post is not None and (
                prior is None or post.forecast_id != prior.forecast_id
            )
            if new_commit and post is not None:
                # Classify the commit by MATERIALITY (the same is_material_move
                # primitive the prompt instructs the agent to apply): a MATERIAL
                # move is the success the auto-reforecast wants; a MARGINAL-delta
                # commit that slipped through the prompt-level policy is reported
                # HONESTLY as "marginal" — it is NOT tallied as a material-move
                # success, so the sweep's status counts and the result detail stay
                # truthful (and surface the Δp that justifies the classification).
                prior_p = (
                    prior.probability_or_distribution if prior is not None else None
                )
                material = is_material_move(prior_p, post.probability_or_distribution)
                delta = None
                if (
                    isinstance(prior_p, (int, float))
                    and not isinstance(prior_p, bool)
                    and isinstance(post.probability_or_distribution, (int, float))
                    and not isinstance(post.probability_or_distribution, bool)
                ):
                    delta = float(post.probability_or_distribution) - float(prior_p)
                if material:
                    detail = f"new snapshot {post.forecast_id}"
                    if delta is not None:
                        detail += f" (Δp {delta:+.3f})"
                    results.append({
                        "question_id": qid,
                        "status": "committed",
                        "detail": detail,
                    })
                else:
                    detail = (
                        f"new snapshot {post.forecast_id} committed at a MARGINAL move"
                    )
                    if delta is not None:
                        detail += f" (Δp {delta:+.3f}, under the |Δp|>=0.03 material-move threshold)"
                    results.append({
                        "question_id": qid,
                        "status": "marginal",
                        "detail": detail,
                    })
            else:
                results.append({
                    "question_id": qid,
                    "status": "skipped",
                    "detail": "agent committed no new snapshot",
                })
        return results

    return _runner


def _validate_limits(max_iterations: int, max_questions: int | None) -> None:
    if (
        isinstance(max_iterations, bool)
        or not isinstance(max_iterations, int)
        or max_iterations < 1
    ):
        raise ValidationError("max_iterations must be a positive integer")
    if max_questions is not None and (
        isinstance(max_questions, bool)
        or not isinstance(max_questions, int)
        or max_questions < 0
    ):
        raise ValidationError("max_questions must be a non-negative integer or None")


def build_evidence_search(
    *,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
    commit_policy: str | None = None,
    stage_runner: Callable[..., dict[str, Any]] | None = None,
) -> Callable[..., Any]:
    """Research evidence; the warning dispatcher separately verifies new rows."""
    _validate_limits(max_iterations, None)
    if stage_runner is None:
        from agent.forecast_stage import run_stage

        stage_runner = run_stage

    def search(ledger: ForecastLedger, warning: Any) -> Any:
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        return stage_runner(
            ledger,
            warning.scope_ref,
            model=model,
            provider=provider,
            max_iterations=max_iterations,
            stage="research",
            commit_policy=commit_policy,
        )

    return search


def build_cron_warning_agent_runners(
    *,
    db_path: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
    now: str | None = None,
    stage_runner: Callable[..., dict[str, Any]] | None = None,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Construct proposal-only scheduled runners; never silently update probability.

    ``now`` is retained for caller compatibility; warning scheduling owns its clock.
    """
    del now
    limit = 12 if max_iterations is None else max_iterations
    _validate_limits(limit, None)
    cycle = build_cycle_reforecast_runner(
        ForecastLedger(db_path),
        model=model,
        provider=provider,
        max_iterations=limit,
        commit_policy="proposal_only",
        stage_runner=stage_runner,
    )

    def reforecast(ledger: ForecastLedger, warning: Any) -> Any:
        if not warning.scope_ref:
            return None
        return next(
            (r for r in cycle([warning.scope_ref]) if r.get("status") == "proposed"),
            None,
        )

    return reforecast, build_evidence_search(
        model=model,
        provider=provider,
        max_iterations=limit,
        commit_policy="proposal_only",
        stage_runner=stage_runner,
    )


def build_operator_warning_runners(
    ledger: ForecastLedger,
    *,
    agent: bool = False,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int = 12,
    max_questions: int | None = None,
    force: bool = False,
    now: str | None = None,
    stage_runner: Callable[..., dict[str, Any]] | None = None,
) -> Any:
    """Wire explicit operator work to the same durable warning acknowledgment gates."""
    from forecasting.cron_runner import build_warning_runners

    # REFORECAST runner: only wired when --agent is set, because the real gated
    # work is an LLM update-stage run. Without --agent we leave REFORECAST alerts
    # OPEN (the dispatcher reports them "skipped") rather than bare-acking them.
    reforecast_runner = None
    evidence_search = None
    triage_runner = None
    triage_model = None
    if agent:
        _inner = build_cycle_reforecast_runner(
            ledger,
            model=model,
            provider=provider,
            max_iterations=max_iterations,
            max_questions=max_questions,
            force=force,
            stage_runner=stage_runner,
        )

        def reforecast_runner(_led, warning):  # noqa: ARG001 — uses the closed-over runner
            if not warning.scope_ref:
                return None
            results = _inner([warning.scope_ref])
            # A landed snapshot is real gated work regardless of materiality, so the
            # alert resolves on either a "committed" (material) OR a "marginal" commit
            # — the material/marginal split is the cycle TALLY's honesty concern, not
            # the alert-ack decision. A gated/declined/errored run lands no snapshot
            # ("skipped"/"error") → falsy → the alert stays open (never bare-acked).
            landed = [
                r for r in results if r.get("status") in {"committed", "marginal"}
            ]
            return landed[0] if landed else None

        # EVIDENCE_COLLECTION search: the LLM/web research-stage pass that
        # bootstraps a question with NO evidence yet (it searches + imports through
        # the gated import_source_evidence path). cron_runner wraps this in the
        # >= 1-new-row gate, so the alert acks ONLY when real evidence landed.
        evidence_search = build_evidence_search(
            model=model,
            provider=provider,
            max_iterations=max_iterations,
            stage_runner=stage_runner,
        )

        # PAID evidence-autopilot (S6.1): the CHEAP auto-labeler for the
        # MATERIAL_CHANGE path. Wired only under --agent so the free continuous tick
        # never spends; bounded to one small labeler call per material change.
        from agent.forecast_stage import build_triage_runner

        triage_runner, triage_model = build_triage_runner(model=model)

    # The autopilot (MATERIAL_CHANGE) + score (POSTMORTEM) runners are the shared,
    # non-LLM gated paths — factored into cron_runner so the CLI, the cron phase,
    # the gateway, and the agent tool all wire identical "real work" semantics.
    return build_warning_runners(
        ledger,
        now=now,
        reforecast_runner=reforecast_runner,
        evidence_search=evidence_search,
        triage_runner=triage_runner,
        triage_model=triage_model,
    )
