"""Baseline / benchmark / backtest scoring domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the offline-evaluation table families:

* BASELINE COMPARISONS: ``add_baseline_comparison`` / ``get_`` / ``list_`` and
  ``score_baseline_comparisons``;
* BENCHMARK DATASETS: ``import_benchmark_dataset`` / ``get_`` / ``list_`` /
  ``_row_to_benchmark_dataset``;
* BACKTESTS: ``run_backtest_dataset`` (the dataset driver) and per-case execution
  (``_run_backtest_case`` / ``_run_leak_judge`` / ``_backtest_case_baselines`` /
  ``_has_baseline`` / ``_disable_backtest_calibration``), the run/case readers
  (``get_backtest_run`` / ``list_backtest_runs`` / ``list_backtest_cases`` /
  ``get_backtest_case`` / ``_row_to_backtest_case`` / ``_backtest_snapshot_components``
  / ``_backtest_snapshot_metadata`` / ``_optional_unit_float`` /
  ``_backtest_case_question_key``), rescoring (``rescore_backtest_run`` /
  ``_rescore_brier_summary`` / ``_build_leak_robustness_summary``), and the
  performance reports (``backtest_performance_report`` / ``live_performance_report``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. The three shared scoring
constants (``BRIER_COIN_FLIP_FLOOR`` / ``LEAK_ROBUSTNESS_REL_TOLERANCE`` /
``WORST_CASE_FLAG_THRESHOLD``) stay in core and are reached via the ``_core.``
call-time hop; the ``LeakJudgeRunner`` and every cross-domain read resolve
through the ``ledger`` INSTANCE."""

from __future__ import annotations

from typing import TYPE_CHECKING

from forecasting.ledger import core as _core
from typing import Any
from forecasting.models import ForecastQuestion
from forecasting.models import LedgerNotFoundError
from forecasting.models import OutcomeSpace
from pathlib import Path
from forecasting.models import ScoreRecord
from forecasting.models import ValidationError
from forecasting.benchmark_evidence import build_benchmark_evidence_profile
from collections import defaultdict
from forecasting.models import json_dumps
from forecasting.models import json_loads
from forecasting.models import lookup_model_pretraining_cutoff
from forecasting.models import parse_timestamp
import sqlite3
from forecasting.models import timestamp_to_datetime
from forecasting.models import utc_now_iso
import uuid

if TYPE_CHECKING:  # ``LeakJudgeRunner`` is a core-defined type alias used only in
    # string annotations (PEP 563); import it for the type checker without a
    # load-time cycle against the partially-initialized ``core`` module.
    from forecasting.ledger.core import LeakJudgeRunner  # noqa: F401


def add_baseline_comparison(
    ledger,
    *,
    question_id: str,
    source: str,
    baseline_type: str,
    probability_or_distribution: Any,
    as_of: str | None = None,
    forecast_id: str | None = None,
    backtest_case_id: str | None = None,
    score_record_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    question = ledger.get_question(question_id)
    payload = ledger._validate_probability_payload(probability_or_distribution, question.outcome_space)
    if score_record_id is not None:
        ledger.get_score(score_record_id)
    baseline_id = f"bc_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO baseline_comparisons (
                id, question_id, forecast_id, backtest_case_id, source,
                baseline_type, as_of, probability_or_distribution,
                score_record_id, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                baseline_id,
                question_id,
                forecast_id,
                backtest_case_id,
                source,
                baseline_type,
                parse_timestamp(as_of, field_name="as_of") or utc_now_iso(),
                json_dumps(payload),
                score_record_id,
                json_dumps(metadata or {}),
            ),
        )
        if score_record_id is not None:
            conn.execute(
                "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                (baseline_id, score_record_id),
            )
    return ledger.get_baseline_comparison(baseline_id)


def get_baseline_comparison(ledger, baseline_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM baseline_comparisons WHERE id = ?",
            (baseline_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"baseline comparison not found: {baseline_id}")
    data = dict(row)
    data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def list_baseline_comparisons(ledger, question_id: str) -> list[dict[str, Any]]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM baseline_comparisons WHERE question_id = ? ORDER BY as_of ASC",
            (question_id,),
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
        data["metadata"] = json_loads(data["metadata"], {})
        result.append(data)
    return result


def score_baseline_comparisons(ledger, question_id: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Score imported baselines for a resolved live question without moving the current forecast."""
    ledger.get_question(question_id)
    if ledger.get_latest_resolution(question_id, confirmed_only=True) is None:
        raise ValidationError(
            "cannot score baseline comparisons until resolution is confirmed, criteria-satisfied, and scoreable"
        )
    scored: list[dict[str, Any]] = []
    for baseline in ledger.list_baseline_comparisons(question_id):
        if baseline.get("score_record_id") and not force:
            scored.append({**baseline, "score": ledger.get_score(baseline["score_record_id"])})
            continue
        forecast_id = baseline.get("forecast_id")
        if not forecast_id:
            snapshot = ledger.create_snapshot(
                question_id=question_id,
                probability_or_distribution=baseline["probability_or_distribution"],
                rationale=f"Imported baseline from {baseline.get('source') or 'unknown source'}.",
                as_of=baseline.get("as_of"),
                method=str(baseline.get("baseline_type") or "imported"),
                forecast_origin="imported_baseline",
                calibration_eligible=False,
                calibration_weight=0.0,
                metadata={
                    "baseline_comparison_id": baseline["id"],
                    "baseline_source": baseline.get("source"),
                },
                set_current=False,
            )
            forecast_id = snapshot.forecast_id
        score = ledger.score_snapshot(forecast_id, force=force)
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE baseline_comparisons
                SET forecast_id = ?, score_record_id = ?
                WHERE id = ?
                """,
                (forecast_id, score.id, baseline["id"]),
            )
            conn.execute(
                "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                (baseline["id"], score.id),
            )
        updated = ledger.get_baseline_comparison(baseline["id"])
        scored.append({**updated, "score": score})
    return scored


def import_benchmark_dataset(
    ledger,
    *,
    source: str,
    cases: list[dict[str, Any]],
    name: str | None = None,
    description: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(cases, list):
        raise ValidationError("benchmark dataset cases must be a list")
    valid_cases = [case for case in cases if isinstance(case, dict)]
    if len(valid_cases) != len(cases):
        raise ValidationError("benchmark dataset cases must be objects")
    dataset_id = f"bd_{uuid.uuid4().hex[:12]}"
    dataset_name = name or Path(str(source)).stem or str(source)
    imported_at = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO benchmark_datasets (
                id, name, source, imported_at, case_count,
                description, cases, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset_id,
                dataset_name,
                source,
                imported_at,
                len(valid_cases),
                description,
                json_dumps(valid_cases),
                json_dumps(metadata or {}),
            ),
        )
    return ledger.get_benchmark_dataset(dataset_id)


def get_benchmark_dataset(ledger, dataset_id: str) -> dict[str, Any]:
    lookup = dataset_id.removeprefix("imported:")
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM benchmark_datasets WHERE id = ?",
            (lookup,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"benchmark dataset not found: {dataset_id}")
    return ledger._row_to_benchmark_dataset(row)


def list_benchmark_datasets(ledger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM benchmark_datasets ORDER BY imported_at DESC",
        ).fetchall()
    return [ledger._row_to_benchmark_dataset(row) for row in rows]


def _row_to_benchmark_dataset(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["cases"] = json_loads(data["cases"], [])
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def run_backtest_dataset(
    ledger,
    *,
    dataset: str,
    cases: list[dict[str, Any]],
    default_forecast_time_cutoff: str | None = None,
    evidence_cutoff_policy: str = "available_at_lte_cutoff",
    calibration_policy: dict[str, Any] | None = None,
    allow_calibration_memory: bool = False,
    leak_judge_runner: "LeakJudgeRunner | None" = None,
    arm: str | None = None,
) -> dict[str, Any]:
    run_id = f"bt_{uuid.uuid4().hex[:12]}"
    default_cutoff = parse_timestamp(
        default_forecast_time_cutoff,
        field_name="default_forecast_time_cutoff",
    )
    created_at = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO backtest_runs (
                id, dataset, created_at, default_forecast_time_cutoff,
                evidence_cutoff_policy, calibration_policy,
                leakage_checks_passed
            )
            VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
            (
                run_id,
                dataset,
                created_at,
                default_cutoff,
                evidence_cutoff_policy,
                json_dumps(
                    calibration_policy
                    or {"allow_calibration_memory": allow_calibration_memory}
                ),
            ),
        )
    case_rows: list[dict[str, Any]] = []
    leakage_passed = True
    for case in cases:
        case_row = ledger._run_backtest_case(
            run_id=run_id,
            case=case,
            default_cutoff=default_cutoff,
            allow_calibration_memory=allow_calibration_memory,
            leak_judge_runner=leak_judge_runner,
        )
        case_rows.append(case_row)
        if case_row["leakage_check_status"] != "passed":
            leakage_passed = False
    result_summary = {
        "case_count": len(case_rows),
        "benchmark_evidence": build_benchmark_evidence_profile(dataset, cases),
        "leakage_checks_passed": leakage_passed,
        "scored_cases": sum(1 for row in case_rows if row.get("score_record_id")),
    }
    # MARKET-HIDDEN ARM label: stamp the experimental arm on the run so later
    # analysis can separate arms (e.g. arm='market_hidden' — the market price was
    # scored as a baseline but withheld from the agent's prompt). Additive: absent
    # by default, so a run with no arm is byte-identical to before.
    if arm:
        result_summary["arm"] = str(arm)
    # AIA P1.2 — surface the content-channel bookkeeping + read-only robustness
    # bounds ONLY when the judge channel ran (a runner was supplied). With the
    # channel OFF these keys are absent, keeping the summary byte-identical.
    if leak_judge_runner is not None:
        content_flagged = sum(
            1 for row in case_rows if int(row.get("content_flag_count") or 0) > 0
        )
        result_summary["leak_judge"] = ledger._build_leak_robustness_summary(
            run_id,
            content_flagged_cases=content_flagged,
        )
    agent_brier_scores = [
        row["score_brier"]
        for row in case_rows
        if row.get("score_brier") is not None
    ]
    if agent_brier_scores:
        result_summary["agent_mean_brier"] = sum(agent_brier_scores) / len(agent_brier_scores)
    probability_sources = sorted(
        {
            str(case.get("probability_source"))
            for case in cases
            if case.get("probability_source")
        }
    )
    if probability_sources:
        result_summary["probability_sources"] = probability_sources
    if not leakage_passed:
        ledger._disable_backtest_calibration(run_id)
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE backtest_runs
            SET result_summary = ?, leakage_checks_passed = ?
            WHERE id = ?
            """,
            (json_dumps(result_summary), 1 if leakage_passed else 0, run_id),
        )
    run = ledger.get_backtest_run(run_id)
    run["cases"] = case_rows
    return run


def get_backtest_run(ledger, run_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"backtest run not found: {run_id}")
    data = dict(row)
    for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
        data[field] = json_loads(data[field], {})
    data["artifact_paths"] = json_loads(data["artifact_paths"], [])
    data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
    return data


def list_backtest_runs(ledger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC",
        ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
            data[field] = json_loads(data[field], {})
        data["artifact_paths"] = json_loads(data["artifact_paths"], [])
        data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
        result.append(data)
    return result


def list_backtest_cases(ledger, run_id: str) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM backtest_cases WHERE backtest_run_id = ? ORDER BY simulated_forecast_time ASC",
            (run_id,),
        ).fetchall()
    return [ledger._row_to_backtest_case(row) for row in rows]


def backtest_performance_report(ledger, run_id: str) -> dict[str, Any]:
    run = ledger.get_backtest_run(run_id)
    cases = ledger.list_backtest_cases(run_id)
    agent_scores: list[ScoreRecord] = []
    baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
    paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
    # Agent-vs-baseline Brier pairs across the FULL baseline set, keyed by the
    # agent SCORE id (NOT question_id) so a question that recurs across rolling
    # cutoffs keeps each agent forecast paired only with ITS OWN baselines —
    # win-rate-vs-best is then "agent <= every baseline" per resolved forecast.
    score_pairs: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
    for case in cases:
        agent_score = ledger.get_score(case["score_record_id"]) if case.get("score_record_id") else None
        if agent_score is not None:
            agent_scores.append(agent_score)
        for baseline_id in case.get("baseline_comparison_refs") or []:
            baseline = ledger.get_baseline_comparison(baseline_id)
            if not baseline.get("score_record_id"):
                continue
            baseline_score = ledger.get_score(baseline["score_record_id"])
            key = (baseline["baseline_type"], baseline["source"])
            baseline_scores[key].append(baseline_score)
            if agent_score is not None:
                paired_scores[key].append((agent_score, baseline_score))
                score_pairs[agent_score.id].append(
                    (agent_score.brier_score, baseline_score.brier_score)
                )
    baselines = []
    for key in sorted(baseline_scores):
        baseline_type, source = key
        pairs = paired_scores.get(key, [])
        paired_brier = ledger._paired_brier_summary(pairs)
        baselines.append(
            {
                "baseline_type": baseline_type,
                "source": source,
                **ledger._score_summary(baseline_scores[key]),
                "paired_count": len(pairs),
                **paired_brier,
                "mean_brier_improvement_vs_baseline": ledger._mean(
                    [
                        baseline.brier_score - agent.brier_score
                        for agent, baseline in pairs
                        if agent.brier_score is not None and baseline.brier_score is not None
                    ]
                ),
                "mean_log_improvement_vs_baseline": ledger._mean(
                    [
                        baseline.log_score - agent.log_score
                        for agent, baseline in pairs
                        if agent.log_score is not None and baseline.log_score is not None
                    ]
                ),
            }
        )
    return {
        "run_id": run["id"],
        "dataset": run["dataset"],
        "case_count": len(cases),
        "leakage_checks_passed": run["leakage_checks_passed"],
        "agent": ledger._score_summary(agent_scores),
        "baselines": baselines,
        "win_rate_vs_best": ledger._win_rate_vs_best(score_pairs),
        "agent_by_domain": ledger._score_breakdown(agent_scores, lambda score: score.domain or "unknown"),
        "agent_by_horizon": ledger._score_breakdown(agent_scores, ledger._score_horizon_bucket),
    }


def live_performance_report(ledger, *, domain: str | None = None) -> dict[str, Any]:
    """Compare scored live forecasts against scored imported baselines."""
    live_scores = ledger.list_scores(
        domain=domain,
        forecast_origin="live",
        calibration_eligible=None,
    )
    baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
    paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
    # Keyed by the agent SCORE id (not question_id) so multiple resolved live
    # scores of the same question stay paired with their own baselines.
    score_pairs: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
    for live_score in live_scores:
        for baseline in ledger.list_baseline_comparisons(live_score.question_id):
            if not baseline.get("score_record_id"):
                continue
            baseline_score = ledger.get_score(baseline["score_record_id"])
            key = (baseline["baseline_type"], baseline["source"])
            baseline_scores[key].append(baseline_score)
            paired_scores[key].append((live_score, baseline_score))
            score_pairs[live_score.id].append(
                (live_score.brier_score, baseline_score.brier_score)
            )
    baselines = []
    for key in sorted(baseline_scores):
        baseline_type, source = key
        pairs = paired_scores.get(key, [])
        baselines.append(
            {
                "baseline_type": baseline_type,
                "source": source,
                **ledger._score_summary(baseline_scores[key]),
                "paired_count": len(pairs),
                **ledger._paired_brier_summary(pairs),
                "mean_brier_improvement_vs_baseline": ledger._mean(
                    [
                        baseline.brier_score - agent.brier_score
                        for agent, baseline in pairs
                        if agent.brier_score is not None and baseline.brier_score is not None
                    ]
                ),
                "mean_log_improvement_vs_baseline": ledger._mean(
                    [
                        baseline.log_score - agent.log_score
                        for agent, baseline in pairs
                        if agent.log_score is not None and baseline.log_score is not None
                    ]
                ),
            }
        )
    return {
        "score_count": len(live_scores),
        "agent": ledger._score_summary(live_scores),
        "baselines": baselines,
        "win_rate_vs_best": ledger._win_rate_vs_best(score_pairs),
        "agent_by_domain": ledger._score_breakdown(live_scores, lambda score: score.domain or "unknown"),
        "agent_by_horizon": ledger._score_breakdown(live_scores, ledger._score_horizon_bucket),
        "claim_status": {
            "verdict": "live_comparison_evidence" if baselines else "no_scored_live_baselines",
            "can_claim_live_superforecasting": False,
            "message": (
                "Resolved live forecasts have scored imported baselines for comparison; "
                "superforecasting claims still require enough prospective volume and coverage."
                if baselines
                else "No scored imported baselines are available for live comparison yet."
            ),
        },
    }


def _disable_backtest_calibration(ledger, run_id: str) -> None:
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE forecast_snapshots
            SET calibration_eligible = 0, calibration_weight = 0
            WHERE backtest_run_id = ? AND forecast_origin = 'backtest'
            """,
            (run_id,),
        )
        conn.execute(
            """
            UPDATE score_records
            SET calibration_eligible = 0, calibration_weight = 0
            WHERE forecast_origin = 'backtest'
              AND forecast_id IN (
                SELECT forecast_id FROM forecast_snapshots WHERE backtest_run_id = ?
              )
            """,
            (run_id,),
        )


def _run_backtest_case(
    ledger,
    *,
    run_id: str,
    case: dict[str, Any],
    default_cutoff: str | None,
    allow_calibration_memory: bool,
    leak_judge_runner: "LeakJudgeRunner | None" = None,
) -> dict[str, Any]:
    simulated_time = parse_timestamp(
        case.get("simulated_forecast_time") or case.get("as_of") or default_cutoff,
        field_name="simulated_forecast_time",
    )
    if simulated_time is None:
        raise ValidationError("each backtest case needs simulated_forecast_time, as_of, or --as-of")
    evidence_cutoff = parse_timestamp(
        case.get("evidence_cutoff") or simulated_time,
        field_name="evidence_cutoff",
    )
    assert evidence_cutoff is not None
    outcome_data = case.get("outcome_space") or {}
    outcome_space = OutcomeSpace.from_dict(outcome_data) if outcome_data else OutcomeSpace()
    question = ledger.create_question(
        title=str(case.get("title") or "Untitled backtest case"),
        description=str(case.get("description") or ""),
        resolution_criteria=str(case.get("resolution_criteria") or "Backtest dataset supplied resolution criteria."),
        resolution_source=case.get("resolution_source"),
        outcome_space=outcome_space,
        close_time=case.get("close_time"),
        resolution_time=case.get("resolution_time"),
        tags=list(case.get("tags") or ["backtest"]),
        domain=case.get("domain"),
        topics=list(case.get("topics") or []),
        metadata={"backtest_run_id": run_id, "external_id": case.get("id")},
    )
    excluded = 0
    ambiguous = 0
    leak_flagged = 0
    evidence_refs: list[str] = []
    cutoff_dt = timestamp_to_datetime(evidence_cutoff)
    for item in case.get("evidence") or []:
        available_raw = item.get("available_at") or item.get("published_at")
        if not available_raw:
            ambiguous += 1
            continue
        available = parse_timestamp(available_raw, field_name="available_at")
        available_dt = timestamp_to_datetime(available)
        if cutoff_dt and available_dt and available_dt > cutoff_dt:
            excluded += 1
            continue
        source_or_note = str(
            item.get("source")
            or item.get("url")
            or item.get("note")
            or item.get("summary")
            or item.get("claim")
            or "backtest evidence"
        )
        evidence = ledger.add_evidence(
            question_id=question.id,
            source_or_note=source_or_note,
            claim=str(item.get("claim") or ""),
            summary=str(item.get("summary") or ""),
            source_url=item.get("url"),
            source_name=item.get("source_name"),
            source_type=item.get("source_type"),
            published_at=item.get("published_at"),
            available_at=available,
            reliability_rating=item.get("reliability_rating"),
            relevance_rating=item.get("relevance_rating"),
            stance=item.get("stance") or "context",
            claim_type=item.get("claim_type") or "fact",
            metadata={"backtest_run_id": run_id},
        )
        if (evidence.metadata or {}).get("leak_domain"):
            leak_flagged += 1
        evidence_refs.append(evidence.id)
    # AIA P2.4 — model-cutoff gate. If the case's base model has a pretraining
    # cutoff at-or-after the event being predicted (resolution/close time),
    # the model may already "know" the answer; force calibration OFF for this
    # case and raise a readiness flag (mirrors the AIA paper rejecting a too-
    # fresh base model for the liquid-market benchmark). Unknown models and
    # cutoffs strictly before the event are a no-op.
    model_cutoff = lookup_model_pretraining_cutoff(case.get("agent_model"))
    event_time = case.get("resolution_time") or case.get("close_time")
    event_dt = timestamp_to_datetime(event_time) if event_time else None
    cutoff_model_dt = timestamp_to_datetime(model_cutoff) if model_cutoff else None
    model_cutoff_too_fresh = bool(
        cutoff_model_dt is not None and event_dt is not None and cutoff_model_dt >= event_dt
    )
    generated_forecast_id = None
    score_record_id = None
    if "outcome" in case:
        ledger.resolve_question(
            question_id=question.id,
            outcome=case["outcome"],
            resolution_source=case.get("resolution_source"),
            resolver_type="source_adapter",
            resolution_status="confirmed",
            criteria_satisfied=True,
        )
    probability = case.get("probability", case.get("forecast_probability"))
    distribution = case.get("distribution")
    if probability is not None or distribution is not None:
        calibration_eligible = (
            allow_calibration_memory and ambiguous == 0 and not model_cutoff_too_fresh
        )
        snapshot_metadata = ledger._backtest_snapshot_metadata(case)
        if model_cutoff_too_fresh:
            snapshot_metadata["model_cutoff_too_fresh"] = True
            snapshot_metadata["model_pretraining_cutoff"] = model_cutoff
            snapshot_metadata["readiness_flag"] = "model_cutoff_after_event"
        snapshot = ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=distribution if distribution is not None else probability,
            rationale=str(case.get("rationale") or "Backtest dataset forecast replay."),
            as_of=simulated_time,
            confidence=ledger._optional_unit_float(case.get("confidence")),
            method=str(case.get("method") or "backtest_replay"),
            ensemble_components=ledger._backtest_snapshot_components(case),
            evidence_refs=evidence_refs,
            forecast_origin="backtest",
            agent_model=case.get("agent_model"),
            prompt_version=case.get("prompt_version"),
            forecasting_protocol_version=case.get("forecasting_protocol_version"),
            evidence_cutoff=evidence_cutoff,
            backtest_run_id=run_id,
            calibration_eligible=calibration_eligible,
            calibration_weight=1.0 if calibration_eligible else 0.0,
            metadata=snapshot_metadata,
        )
        generated_forecast_id = snapshot.forecast_id
        if "outcome" in case:
            score = ledger.score_question(question.id)
            score_record_id = score.id
    baseline_refs = []
    for baseline in ledger._backtest_case_baselines(case, outcome_space):
        if "probability" not in baseline and "distribution" not in baseline:
            continue
        baseline_forecast_id = None
        baseline_score_id = None
        if "outcome" in case:
            baseline_snapshot = ledger.create_snapshot(
                question_id=question.id,
                probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                rationale=f"Imported baseline from {baseline.get('source') or 'dataset'}.",
                as_of=baseline.get("as_of") or simulated_time,
                method=str(baseline.get("baseline_type") or "imported"),
                forecast_origin="imported_baseline",
                backtest_run_id=run_id,
                calibration_eligible=False,
                calibration_weight=0.0,
                set_current=False,
            )
            baseline_forecast_id = baseline_snapshot.forecast_id
            baseline_score_id = ledger.score_snapshot(baseline_forecast_id).id
        comparison = ledger.add_baseline_comparison(
            question_id=question.id,
            source=str(baseline.get("source") or "dataset"),
            baseline_type=str(baseline.get("baseline_type") or "imported"),
            probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
            as_of=baseline.get("as_of") or simulated_time,
            forecast_id=baseline_forecast_id,
            score_record_id=baseline_score_id,
            metadata={"backtest_run_id": run_id, "generated_forecast_id": generated_forecast_id},
        )
        baseline_refs.append(comparison["id"])
    leakage_status = "passed" if ambiguous == 0 else "ambiguous_evidence"
    # AIA P1.2 — SECOND, content-aware leakage channel. The cheap date
    # pre-filter above already dropped post-cutoff *timestamped* evidence; the
    # judge reads the cited evidence TEXT + rationale for foreknowledge that
    # rides inside admissible text. OPT-IN: with no runner (the default) this
    # block is skipped entirely and the persisted columns keep their unflagged
    # defaults — making the run byte-identical to a pre-P1.2 backtest.
    leakage_verdict: dict[str, Any] = {}
    content_flag_count = 0
    if leak_judge_runner is not None:
        leakage_verdict = ledger._run_leak_judge(
            runner=leak_judge_runner,
            case=case,
            question=question,
            evidence_cutoff=evidence_cutoff,
        )
        if leakage_verdict.get("has_foreknowledge"):
            content_flag_count = 1
            # Never weaken a pre-existing non-passing status (e.g. ambiguous).
            if leakage_status == "passed":
                leakage_status = "content_flagged"
    case_id = f"btc_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO backtest_cases (
                id, backtest_run_id, question_id, simulated_forecast_time,
                evidence_cutoff, generated_forecast_id, baseline_comparison_refs,
                score_record_id, leakage_check_status, excluded_evidence_count,
                ambiguous_evidence_count, leakage_verdicts, content_flag_count, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                case_id,
                run_id,
                question.id,
                simulated_time,
                evidence_cutoff,
                generated_forecast_id,
                json_dumps(baseline_refs),
                score_record_id,
                leakage_status,
                excluded,
                ambiguous,
                json_dumps(leakage_verdict),
                content_flag_count,
                case.get("notes"),
            ),
        )
    row = ledger.get_backtest_case(case_id)
    if score_record_id:
        row["score_brier"] = ledger.get_score(score_record_id).brier_score
    # AIA P2.4 — surface the per-case leak-domain flag count + model-cutoff
    # readiness flag alongside the case row for evidence summaries.
    row["leak_flagged_evidence_count"] = leak_flagged
    row["model_cutoff_too_fresh"] = model_cutoff_too_fresh
    return row


def _run_leak_judge(
    ledger,
    *,
    runner: "LeakJudgeRunner",
    case: dict[str, Any],
    question: ForecastQuestion,
    evidence_cutoff: str | None,
) -> dict[str, Any]:
    """Run the content-aware foreknowledge judge over one case.
    Builds the (pure) prompt, calls the supplied ``runner`` (the only
    network touch in this whole feature), and returns the tolerant-parsed
    verdict. Any runner exception fails CLOSED to the safe default so a flaky
    judge call can never manufacture a leak flag or take down the backtest.
    """
    from forecasting.leak_judge import (
        build_leak_judge_prompt,
        parse_leak_verdict,
    )
    # Assemble the cited evidence text + rationale the judge must read. We use
    # the case's own evidence/rationale (the model output under audit).
    evidence_lines: list[str] = []
    for item in case.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        parts = [
            str(item.get(field) or "")
            for field in ("claim", "summary", "note", "source", "url")
        ]
        text = " | ".join(part for part in parts if part)
        if text:
            evidence_lines.append(f"- {text}")
    rationale = str(case.get("rationale") or "")
    model_output = "\n".join(
        block
        for block in (
            ("Rationale:\n" + rationale) if rationale else "",
            ("Cited evidence:\n" + "\n".join(evidence_lines)) if evidence_lines else "",
        )
        if block
    )
    resolution = case.get("outcome")
    prompt = build_leak_judge_prompt(
        question=question.title,
        cutoff=evidence_cutoff,
        resolution=str(resolution) if resolution is not None else None,
        model_output=model_output,
    )
    try:
        raw = runner(prompt, case)
    except Exception:  # noqa: BLE001 — fail closed, never break the backtest.
        return parse_leak_verdict(None)
    return parse_leak_verdict(raw)


def rescore_backtest_run(ledger, run_id: str, mode: str) -> dict[str, Any]:
    """Recompute the agent mean Brier under a leakage-robustness *mode*.
    PURE recompute over STORED cases — it never edits a stored score, never
    touches calibration, never re-runs the judge, and WRITES NOTHING (a
    robustness what-if must be freely repeatable with no side effects).
    Modes:
      * ``baseline``    — every scored case as-scored (the headline).
      * ``filtered``    — DROP every content-flagged case (drop-all-flagged).
      * ``worst_case``  — raise the Brier to AT LEAST 0.25 (the coin-flip floor;
        it NEVER improves an already-worse case, so worst_case is a genuine
        upper bound on our Brier under leakage) on every case belonging to a
        QUESTION that accumulated >= :data:`WORST_CASE_FLAG_THRESHOLD` content
        flags across its cases; all other cases keep their Brier.
    Returns ``{baseline, filtered, worst_case, abs_delta, rel_delta}`` where
    ``baseline``/``filtered``/``worst_case`` are mean-Brier dicts and the
    deltas compare the REQUESTED mode against baseline. Always computes all
    three means so deltas are available regardless of ``mode``.
    """
    if mode not in ledger._RESCORE_MODES:
        raise ValidationError(
            f"rescore mode must be one of {sorted(ledger._RESCORE_MODES)}, got {mode!r}"
        )
    cases = ledger.list_backtest_cases(run_id)
    # Per-question flag tally. A dataset question recurs across rolling cutoffs
    # as MULTIPLE backtest cases, each with its own internal question_id, so we
    # group on the stable LOGICAL key (the dataset external_id stored in the
    # question metadata) and fall back to the internal id when absent.
    case_keys: dict[str, str] = {}
    flags_by_question: dict[str, int] = defaultdict(int)
    for case in cases:
        key = ledger._backtest_case_question_key(case)
        case_keys[case["id"]] = key
        flags_by_question[key] += int(case.get("content_flag_count") or 0)
    worst_case_questions = {
        key
        for key, count in flags_by_question.items()
        if count >= _core.WORST_CASE_FLAG_THRESHOLD
    }
    baseline_briers: list[float] = []
    filtered_briers: list[float] = []
    worst_briers: list[float] = []
    for case in cases:
        brier = case.get("score_brier")
        if brier is None and case.get("score_record_id"):
            brier = ledger.get_score(case["score_record_id"]).brier_score
        if brier is None:
            continue  # unscored case (e.g. no resolution) — not in any mean.
        brier = float(brier)
        baseline_briers.append(brier)
        # filtered: drop the case entirely if it carries any content flag.
        if int(case.get("content_flag_count") or 0) == 0:
            filtered_briers.append(brier)
        # worst_case: raise the Brier to AT LEAST the coin-flip floor for cases
        # of a heavily-flagged question — never improving an already-worse case,
        # so worst_case is a genuine UPPER bound on our Brier under leakage.
        if case_keys.get(case["id"]) in worst_case_questions:
            worst_briers.append(max(brier, _core.BRIER_COIN_FLIP_FLOOR))
        else:
            worst_briers.append(brier)
    baseline = ledger._rescore_brier_summary(baseline_briers)
    filtered = ledger._rescore_brier_summary(filtered_briers)
    worst_case = ledger._rescore_brier_summary(worst_briers)
    chosen = {"baseline": baseline, "filtered": filtered, "worst_case": worst_case}[mode]
    base_mean = baseline.get("mean_brier")
    chosen_mean = chosen.get("mean_brier")
    if base_mean is None or chosen_mean is None:
        abs_delta = None
        rel_delta = None
    else:
        abs_delta = chosen_mean - base_mean
        rel_delta = (abs_delta / base_mean) if base_mean else None
    return {
        "run_id": run_id,
        "mode": mode,
        "worst_case_flag_threshold": _core.WORST_CASE_FLAG_THRESHOLD,
        "worst_case_question_count": len(worst_case_questions),
        "baseline": baseline,
        "filtered": filtered,
        "worst_case": worst_case,
        "abs_delta": abs_delta,
        "rel_delta": rel_delta,
    }


def _rescore_brier_summary(briers: list[float]) -> dict[str, Any]:
    return {
        "count": len(briers),
        "mean_brier": (sum(briers) / len(briers)) if briers else None,
    }


def _backtest_case_question_key(ledger, case: dict[str, Any]) -> str:
    """Stable LOGICAL-question key for per-question flag aggregation.
    A dataset question that recurs across rolling cutoffs produces multiple
    backtest cases, each with its own internal ``question_id``. Group them on
    the dataset ``external_id`` carried in the question metadata so a question
    with cases at several cutoffs accumulates ONE flag tally; fall back to the
    internal id when no external id was supplied.
    """
    question_id = case.get("question_id")
    if question_id:
        try:
            metadata = ledger.get_question(question_id).metadata or {}
        except LedgerNotFoundError:
            metadata = {}
        external_id = metadata.get("external_id")
        if external_id:
            return f"ext:{external_id}"
        return f"qid:{question_id}"
    return f"case:{case['id']}"


def _build_leak_robustness_summary(
    ledger,
    run_id: str,
    *,
    content_flagged_cases: int,
) -> dict[str, Any]:
    """Assemble the read-only leak-judge summary for ``result_summary``.
    Carries the three robustness re-scores, the honest true-leak-rate
    back-out, and a graded ``leakage_material`` verdict that REPLACES the old
    binary kill-switch: leakage is non-material iff the worst-case mean Brier
    stays within :data:`LEAK_ROBUSTNESS_REL_TOLERANCE` (relative) of baseline.
    """
    from forecasting.leak_prevalence import (
        LEAK_JUDGE_CALIBRATION,
        estimate_true_leak_rate,
    )
    rescore = ledger.rescore_backtest_run(run_id, "worst_case")
    case_count = int(rescore["baseline"].get("count") or 0)
    prevalence = estimate_true_leak_rate(case_count, content_flagged_cases)
    worst_rel = rescore.get("rel_delta")
    # Non-material iff the worst-case mean Brier did not rise by more than the
    # relative tolerance. A missing delta (no scored cases) fails OPEN to
    # non-material rather than asserting harm we cannot measure.
    leakage_material = bool(worst_rel is not None and worst_rel > _core.LEAK_ROBUSTNESS_REL_TOLERANCE)
    return {
        "channel": "content_aware_judge",
        "prompt_version": "leak-judge-v0",
        "content_flagged_cases": content_flagged_cases,
        "rescore": rescore,
        "true_leak_rate": prevalence,
        "calibration": LEAK_JUDGE_CALIBRATION,
        "rel_tolerance": _core.LEAK_ROBUSTNESS_REL_TOLERANCE,
        "leakage_material": leakage_material,
        "leakage_non_material": not leakage_material,
    }


def get_backtest_case(ledger, case_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM backtest_cases WHERE id = ?", (case_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"backtest case not found: {case_id}")
    return ledger._row_to_backtest_case(row)


def _backtest_snapshot_components(case: dict[str, Any]) -> dict[str, Any]:
    components = case.get("ensemble_components")
    if isinstance(components, dict):
        return components
    component_forecasts = case.get("component_forecasts")
    if isinstance(component_forecasts, dict):
        return component_forecasts
    if not isinstance(component_forecasts, list):
        return {}
    normalized: dict[str, Any] = {}
    for index, component in enumerate(component_forecasts, start=1):
        if isinstance(component, dict):
            name = component.get("name") or component.get("source") or f"component_{index}"
            normalized[str(name)] = component
        else:
            normalized[f"component_{index}"] = component
    return normalized


def _backtest_snapshot_metadata(case: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(case.get("forecast_metadata") or {})
    if case.get("probability_source"):
        metadata["probability_source"] = case["probability_source"]
    if case.get("id"):
        metadata["external_case_id"] = case["id"]
    return metadata


def _optional_unit_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    if 0 <= number <= 1:
        return number
    return None


def _backtest_case_baselines(
    ledger,
    case: dict[str, Any],
    outcome_space: OutcomeSpace,
) -> list[dict[str, Any]]:
    baselines = [dict(row) for row in case.get("baselines") or [] if isinstance(row, dict)]
    # MARKET-HIDDEN ARM: ``hidden_from_agent`` is an agent-VISIBILITY marker
    # consumed only by agent_protocol._pre_cutoff_baselines. It must NOT alter
    # scoring — a hidden baseline is still recorded + scored as a
    # baseline_comparison — so strip the marker here before persistence rather
    # than carrying an unknown key into create_snapshot / add_baseline_comparison.
    for row in baselines:
        row.pop("hidden_from_agent", None)
    has_explicit_baselines = bool(baselines)
    if not has_explicit_baselines and outcome_space.type == "binary" and not ledger._has_baseline(baselines, "naive_0_5", "auto"):
        baselines.append(
            {
                "source": "auto",
                "baseline_type": "naive_0_5",
                "probability": 0.5,
                "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
            }
        )
    elif (
        not has_explicit_baselines
        and outcome_space.type == "categorical"
        and outcome_space.choices
        and not ledger._has_baseline(baselines, "uniform", "auto")
    ):
        probability = 1.0 / len(outcome_space.choices)
        baselines.append(
            {
                "source": "auto",
                "baseline_type": "uniform",
                "distribution": {choice: probability for choice in outcome_space.choices},
                "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
            }
        )
    base_rate = case.get("base_rate")
    if base_rate is None:
        base_rate = case.get("base_rate_probability")
    if base_rate is not None and not ledger._has_baseline(baselines, "base_rate", "dataset"):
        baselines.append(
            {
                "source": "dataset",
                "baseline_type": "base_rate",
                "probability": base_rate,
                "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
            }
        )
    return baselines


def _has_baseline(ledger, baselines: list[dict[str, Any]], baseline_type: str, source: str) -> bool:
    return any(
        str(baseline.get("baseline_type") or "") == baseline_type
        and str(baseline.get("source") or "") == source
        for baseline in baselines
    )


def _row_to_backtest_case(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["baseline_comparison_refs"] = json_loads(data["baseline_comparison_refs"], [])
    # AIA P1.2 columns are optional on rows read from pre-migration DBs.
    data["leakage_verdicts"] = json_loads(data.get("leakage_verdicts"), {})
    data["content_flag_count"] = int(data.get("content_flag_count") or 0)
    return data
