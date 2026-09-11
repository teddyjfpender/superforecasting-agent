"""Wire models for the ``forecast.*`` RPC family (Arc A3) — the biggest family.

Transcribed faithfully from the SERVER's actual emission (the handlers in
``tui_gateway/server.py`` and their builders: ``forecasting/dashboard.py``,
``forecasting/readiness_lens.py``, ``forecasting/ledger`` config/export,
``forecasting/jobs/types/quorum.py``) and cross-checked against the hand-written
mirrors in ``ui-tui/src/gatewayTypes.ts``. Each model's ``TS_NAME`` equals the
mirror's interface name so the generated type is a DROP-IN replacement — the TUI
consumers only change their import source, not the type names.

Modelling choices (the arc's pragmatic big-payload rule):
* Response models are ``extra='ignore'`` tolerant (the ``WireModel`` default). The
  server's dict is authoritative; the ``forecast.*`` gateway wrapper VALIDATES and
  logs drift but returns the ORIGINAL result untouched (it never re-serialises this
  family), so a richer real frame validates and the wire can never regress.
* Fields follow the mirrors field-for-field: ``wire_optional()`` for ``field?: T``,
  ``wire_optional(nullable=True)`` for ``field?: null | T``, a bare annotation for a
  required key. Inline object types in the mirrors become NAMED sub-models here
  (pydantic needs a class); the extra generated interfaces are harmless — consumers
  use them structurally.
* Two mirror features are not expressible via codegen (a TS index signature and the
  ``extends``); ``ForecastQuorumStatusResult`` / ``ForecastSnapshotMetadata`` model
  their NAMED fields and ``ForecastCalibrationSummary`` / ``ForecastWarningsAgentTier``
  are flattened. Documented inline where it matters.
* Request models are lenient (all params optional, ``extra='ignore'``): the handlers
  own a richer error taxonomy (4003/4004/5008/5009), so the wrapper validates-and-logs
  the request but NEVER short-circuits — the handler's own field checks stay the sole
  gate and no error code changes.
"""

from __future__ import annotations

from typing import Any

from protocol.types import WireModel, wire_optional

# A headline probability OR a full distribution blob OR a display string — the
# server emits any of these for a "probability" column (binary vs distribution vs
# categorical). Mirrors ``null | number | Record<string, unknown> | string``.
_ProbOrDist = float | dict[str, Any] | str


# ══════════════════════════════════════════════════════════════════════════════
# Shared leaf models (analyst notes, cross-pollination, readiness, tail audit)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastAnalystNote(WireModel):
    TS_NAME = "ForecastAnalystNote"

    as_of: str | None = wire_optional()
    be_aware: str | None = wire_optional()
    body: str | None = wire_optional()
    created_at: str | None = wire_optional()
    forecast_id: str | None = wire_optional(nullable=True)
    generator: str | None = wire_optional()
    headline: str | None = wire_optional()
    how_it_feels: str | None = wire_optional()
    how_it_thinks: str | None = wire_optional()
    kind: str | None = wire_optional()
    looking_for: str | None = wire_optional()
    stance: str | None = wire_optional(nullable=True)
    verdict: str | None = wire_optional(nullable=True)


class ForecastRelatedView(WireModel):
    TS_NAME = "ForecastRelatedView"

    as_of: str | None = wire_optional(nullable=True)
    be_aware: str | None = wire_optional(nullable=True)
    headline_kind: str | None = wire_optional()
    headline_probability: float | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    link_label: str | None = wire_optional(nullable=True)
    link_type: str | None = wire_optional()
    note_headline: str | None = wire_optional(nullable=True)
    probability_display: str | None = wire_optional()
    reasons_down: list[str] | None = wire_optional()
    reasons_up: list[str] | None = wire_optional()
    relationship: str | None = wire_optional()
    stance: str | None = wire_optional(nullable=True)
    title: str | None = wire_optional()
    verdict: str | None = wire_optional(nullable=True)


class ForecastSharedSource(WireModel):
    TS_NAME = "ForecastSharedSource"

    kind: str | None = wire_optional()
    shared_with: list[str] | None = wire_optional()
    source: str | None = wire_optional()


class ForecastRelated(WireModel):
    TS_NAME = "ForecastRelated"

    forecasts: list[ForecastRelatedView] | None = wire_optional()
    informed_by: list[str] | None = wire_optional()
    shared_sources: list[ForecastSharedSource] | None = wire_optional()


class ForecastReadinessGap(WireModel):
    TS_NAME = "ForecastReadinessGap"

    key: str
    label: str
    fix_hint: str


class ForecastReadiness(WireModel):
    TS_NAME = "ForecastReadiness"

    score: float
    gaps: list[ForecastReadinessGap]


class ForecastTailOutcome(WireModel):
    TS_NAME = "ForecastTailOutcome"

    # ``classification`` is a ForecastTailClassification | string in the mirror — a
    # value enum kept client-side; the wire type is just a string.
    classification: str | None = wire_optional(nullable=True)
    evidence_strength: str | None = wire_optional()
    has_path: bool | None = wire_optional()
    name: str | None = wire_optional()
    note: str | None = wire_optional()
    path: str | None = wire_optional()
    probability: float | None = wire_optional()
    unearned: bool | None = wire_optional()


class ForecastTailNullModel(WireModel):
    TS_NAME = "ForecastTailNullModel"

    agent_tail: float | None = wire_optional()
    excess_tail: float | None = wire_optional()
    floor: float | None = wire_optional()
    null_distribution: dict[str, float] | None = wire_optional()
    null_tail: float | None = wire_optional()
    ratio: float | None = wire_optional()
    within_tolerance: bool | None = wire_optional()


class ForecastTailAudit(WireModel):
    TS_NAME = "ForecastTailAudit"

    issues: list[str] | None = wire_optional()
    null_model: ForecastTailNullModel | None = wire_optional(nullable=True)
    outcomes: list[ForecastTailOutcome] | None = wire_optional()
    passes: bool | None = wire_optional()
    residual_cap: float | None = wire_optional()
    threshold: float | None = wire_optional()
    total_mass: float | None = wire_optional()
    unearned_mass: float | None = wire_optional()


class ForecastSnapshotMetadata(WireModel):
    """The snapshot metadata blob. The mirror added a ``[key: string]: unknown``
    index signature that codegen cannot emit; we model the ONE field consumers read
    (``tail_audit``) and stay ``extra='ignore'`` tolerant of the rest on the wire."""

    TS_NAME = "ForecastSnapshotMetadata"

    tail_audit: ForecastTailAudit | None = wire_optional(nullable=True)


# ══════════════════════════════════════════════════════════════════════════════
# forecast.dashboard  (build_dashboard_summary / render_dashboard_text)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastDashboardAlert(WireModel):
    TS_NAME = "ForecastDashboardAlert"

    acknowledged_at: str | None = wire_optional(nullable=True)
    created_at: str | None = wire_optional()
    id: str | None = wire_optional()
    reason: str | None = wire_optional()
    recommended_action: str | None = wire_optional()
    scope_ref: str | None = wire_optional()
    scope_type: str | None = wire_optional()
    severity: str | None = wire_optional()


class ForecastDoctorNextAction(WireModel):
    TS_NAME = "ForecastDoctorNextAction"

    action: str | None = wire_optional()
    requirement_id: str | None = wire_optional()
    source: str | None = wire_optional()


class ForecastDashboardDoctor(WireModel):
    TS_NAME = "ForecastDashboardDoctor"

    claim_live_superforecasting: bool | None = wire_optional()
    doctor_status: str | None = wire_optional()
    next_action: str | None = wire_optional()
    next_actions: list[ForecastDoctorNextAction] | None = wire_optional()
    next_requirement: str | None = wire_optional()
    pilot_gap_count: int | None = wire_optional()
    pilot_passed_checks: int | None = wire_optional()
    pilot_status: str | None = wire_optional()
    pilot_total_checks: int | None = wire_optional()
    readiness_gap_count: int | None = wire_optional()
    readiness_verdict: str | None = wire_optional()
    scheduled_review_run_count: int | None = wire_optional()
    tester_handoff_ready: bool | None = wire_optional()


class ForecastDashboardThesis(WireModel):
    TS_NAME = "ForecastDashboardThesis"

    id: str | None = wire_optional()
    title: str | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    health_probability: float | None = wire_optional(nullable=True)
    health_display: str | None = wire_optional()
    thesis_score: float | None = wire_optional(nullable=True)
    coverage: float | None = wire_optional(nullable=True)
    n_eff: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    member_count: int | None = wire_optional()
    status: str | None = wire_optional()


class ForecastDashboardFactor(WireModel):
    TS_NAME = "ForecastDashboardFactor"

    id: str | None = wire_optional()
    title: str | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    units: str | None = wire_optional(nullable=True)
    mean: float | None = wire_optional(nullable=True)
    sd: float | None = wire_optional(nullable=True)
    q05: float | None = wire_optional(nullable=True)
    q95: float | None = wire_optional(nullable=True)
    downside: float | None = wire_optional(nullable=True)
    cvar: float | None = wire_optional(nullable=True)
    coverage: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    member_count: int | None = wire_optional()
    status: str | None = wire_optional()


class ForecastEvidenceBacktests(WireModel):
    TS_NAME = "ForecastEvidenceBacktests"

    agent_protocol_scored_count: int | None = wire_optional()
    distinct_dataset_count: int | None = wire_optional()
    external_dataset_count: int | None = wire_optional()
    external_source_family_count: int | None = wire_optional()
    leakage_free_run_count: int | None = wire_optional()
    positive_best_baseline_edge_run_count: int | None = wire_optional()
    run_count: int | None = wire_optional()
    source_families: list[str] | None = wire_optional()


class ForecastEvidenceNextAction(WireModel):
    TS_NAME = "ForecastEvidenceNextAction"

    action: str | None = wire_optional()
    requirement_id: str | None = wire_optional()


class ForecastEvidenceRequirement(WireModel):
    TS_NAME = "ForecastEvidenceRequirement"

    description: str | None = wire_optional()
    id: str | None = wire_optional()
    observed: float | None = wire_optional()
    passed: bool | None = wire_optional()
    required: float | None = wire_optional()
    recommended_action: str | None = wire_optional()


class ForecastEvidenceScoreCounts(WireModel):
    TS_NAME = "ForecastEvidenceScoreCounts"

    backtest: int | None = wire_optional()
    imported_baseline: int | None = wire_optional()
    live: int | None = wire_optional()


class ForecastDashboardEvidenceStatus(WireModel):
    TS_NAME = "ForecastDashboardEvidenceStatus"

    backtests: ForecastEvidenceBacktests | None = wire_optional()
    can_claim_live_superforecasting: bool | None = wire_optional()
    gaps: list[str] | None = wire_optional()
    message: str | None = wire_optional()
    next_actions: list[ForecastEvidenceNextAction] | None = wire_optional()
    requirements: list[ForecastEvidenceRequirement] | None = wire_optional()
    score_counts: ForecastEvidenceScoreCounts | None = wire_optional()
    verdict: str | None = wire_optional()


class ForecastLivePerformanceAgent(WireModel):
    TS_NAME = "ForecastLivePerformanceAgent"

    mean_brier: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)


class ForecastDashboardClaimStatus(WireModel):
    TS_NAME = "ForecastDashboardClaimStatus"

    can_claim_live_superforecasting: bool | None = wire_optional()
    case_count: int | None = wire_optional()
    evidence_type: str | None = wire_optional()
    leakage_checks_passed: bool | None = wire_optional()
    message: str | None = wire_optional()
    scored_count: int | None = wire_optional()
    verdict: str | None = wire_optional()


class ForecastDashboardLiveBaseline(WireModel):
    TS_NAME = "ForecastDashboardLiveBaseline"

    baseline_type: str | None = wire_optional()
    mean_brier: float | None = wire_optional(nullable=True)
    mean_brier_improvement_vs_baseline: float | None = wire_optional(nullable=True)
    paired_agent_edge_ci95_high: float | None = wire_optional(nullable=True)
    paired_agent_edge_ci95_low: float | None = wire_optional(nullable=True)
    paired_agent_edge_mean_brier: float | None = wire_optional(nullable=True)
    paired_agent_mean_brier: float | None = wire_optional(nullable=True)
    paired_agent_wins: int | None = wire_optional()
    paired_baseline_mean_brier: float | None = wire_optional(nullable=True)
    paired_baseline_wins: int | None = wire_optional()
    paired_count: int | None = wire_optional()
    paired_ties: int | None = wire_optional()
    source: str | None = wire_optional()


class ForecastDashboardLivePerformance(WireModel):
    TS_NAME = "ForecastDashboardLivePerformance"

    agent: ForecastLivePerformanceAgent | None = wire_optional()
    baselines: list[ForecastDashboardLiveBaseline] | None = wire_optional()
    claim_status: ForecastDashboardClaimStatus | None = wire_optional()
    score_count: int | None = wire_optional()


class ForecastDashboardCalibrationComponent(WireModel):
    TS_NAME = "ForecastDashboardCalibrationComponent"

    count: int | None = wire_optional()
    mean_abs_distance_from_forecast: float | None = wire_optional(nullable=True)
    mean_contribution: float | None = wire_optional(nullable=True)
    mean_probability: float | None = wire_optional(nullable=True)
    mean_weight: float | None = wire_optional(nullable=True)
    mean_weight_share: float | None = wire_optional(nullable=True)
    name: str | None = wire_optional()


class ForecastDashboardQuestionTypeCalibration(WireModel):
    TS_NAME = "ForecastDashboardQuestionTypeCalibration"

    brier_count: int | None = wire_optional()
    count: int | None = wire_optional()
    mean_brier: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)
    mean_proper_score: float | None = wire_optional(nullable=True)
    mean_sharpness: float | None = wire_optional(nullable=True)
    question_type: str | None = wire_optional()
    score_rules: list[str] | None = wire_optional()


class ForecastDashboardCalibration(WireModel):
    TS_NAME = "ForecastDashboardCalibration"

    calibration_eligible: bool | None = wire_optional(nullable=True)
    count: int | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    ensemble_component_contributions: (
        list[ForecastDashboardCalibrationComponent] | None
    ) = wire_optional()
    forecast_origin: str | None = wire_optional(nullable=True)
    horizon: str | None = wire_optional(nullable=True)
    mean_brier: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)
    mean_sharpness: float | None = wire_optional(nullable=True)
    probability_movement_count: int | None = wire_optional()
    mean_probability_movement_before_close: float | None = wire_optional(nullable=True)
    mean_abs_probability_movement_before_close: float | None = wire_optional(nullable=True)
    question_type_breakdown: (
        list[ForecastDashboardQuestionTypeCalibration] | None
    ) = wire_optional()


class ForecastDashboardBacktest(WireModel):
    TS_NAME = "ForecastDashboardBacktest"

    agent_edge: float | None = wire_optional(nullable=True)
    agent_mean_brier: float | None = wire_optional(nullable=True)
    best_baseline: str | None = wire_optional(nullable=True)
    best_baseline_brier: float | None = wire_optional(nullable=True)
    case_count: int | None = wire_optional()
    claim_status: ForecastDashboardClaimStatus | None = wire_optional()
    dataset: str | None = wire_optional()
    id: str | None = wire_optional()
    leakage_checks_passed: bool | None = wire_optional()
    paired_agent_edge: float | None = wire_optional(nullable=True)
    paired_agent_edge_ci95_high: float | None = wire_optional(nullable=True)
    paired_agent_edge_ci95_low: float | None = wire_optional(nullable=True)
    paired_agent_wins: int | None = wire_optional()
    paired_baseline_wins: int | None = wire_optional()
    paired_count: int | None = wire_optional()
    paired_ties: int | None = wire_optional()
    probability_sources: list[str] | None = wire_optional()


class ForecastDashboardScheduleRun(WireModel):
    TS_NAME = "ForecastDashboardScheduleRun"

    alert_count: int | None = wire_optional()
    alert_reasons: list[str] | None = wire_optional()
    auto_postmortem: bool | None = wire_optional()
    auto_score: bool | None = wire_optional()
    cadence: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    learning_review_count: int | None = wire_optional()
    next_run_at: str | None = wire_optional()
    postmortem_count: int | None = wire_optional()
    run_at: str | None = wire_optional()
    scheduled_review_id: str | None = wire_optional()
    scope_ref: str | None = wire_optional(nullable=True)
    scope_type: str | None = wire_optional(nullable=True)
    score_count: int | None = wire_optional()
    status: str | None = wire_optional()


class ForecastDashboardErrorProfile(WireModel):
    TS_NAME = "ForecastDashboardErrorProfile"

    domain: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    mean_brier: float | None = wire_optional(nullable=True)
    question_type: str | None = wire_optional(nullable=True)
    recommended_adjustments: list[str] | None = wire_optional()
    recurring_errors: list[str] | None = wire_optional()
    sample_count: int | None = wire_optional()
    topic: str | None = wire_optional(nullable=True)
    updated_at: str | None = wire_optional(nullable=True)


class ForecastDashboardLesson(WireModel):
    TS_NAME = "ForecastDashboardLesson"

    confidence: float | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    lesson: str | None = wire_optional()
    recommended_adjustment: dict[str, Any] | None = wire_optional()
    scope_ref: str | None = wire_optional(nullable=True)
    scope_type: str | None = wire_optional(nullable=True)
    source_postmortem_count: int | None = wire_optional()
    source_score_count: int | None = wire_optional()
    status: str | None = wire_optional()
    updated_at: str | None = wire_optional(nullable=True)


class ForecastLearningEffectiveness(WireModel):
    status: str | None = wire_optional()
    counts: dict[str, int] | None = wire_optional()
    interpretation: str | None = wire_optional()


class ForecastLifecycleSummary(WireModel):
    counts: dict[str, int] | None = wire_optional()


class ForecastDashboardLearning(WireModel):
    TS_NAME = "ForecastDashboardLearning"

    effectiveness: ForecastLearningEffectiveness | None = wire_optional()
    trials: dict[str, int] | None = wire_optional()

    active_lessons: int | None = wire_optional()
    invalidated_lessons: int | None = wire_optional()
    recent_lessons: list[ForecastDashboardLesson] | None = wire_optional()
    tentative_lessons: int | None = wire_optional()
    top_error_profiles: list[ForecastDashboardErrorProfile] | None = wire_optional()
    total_lessons: int | None = wire_optional()


class ForecastDashboardQuestion(WireModel):
    TS_NAME = "ForecastDashboardQuestion"

    as_of: str | None = wire_optional(nullable=True)
    baseline_count: int | None = wire_optional()
    close_time: str | None = wire_optional(nullable=True)
    confidence: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    domain: str | None = wire_optional(nullable=True)
    evidence_count: int | None = wire_optional()
    id: str | None = wire_optional()
    latest_evidence_at: str | None = wire_optional(nullable=True)
    latest_evidence_claim: str | None = wire_optional(nullable=True)
    latest_evidence_summary: str | None = wire_optional(nullable=True)
    latest_rationale: str | None = wire_optional(nullable=True)
    open_alert_count: int | None = wire_optional()
    operations: dict[str, Any] | None = wire_optional()
    open_assumption_count: int | None = wire_optional()
    open_reference_class_count: int | None = wire_optional()
    probability: _ProbOrDist | None = wire_optional(nullable=True)
    resolution_time: str | None = wire_optional(nullable=True)
    stale_assumption_count: int | None = wire_optional()
    stale_reference_class_count: int | None = wire_optional()
    status: str | None = wire_optional()
    tail_audit: ForecastTailAudit | None = wire_optional(nullable=True)
    title: str | None = wire_optional()
    topics: list[str] | None = wire_optional()


class ForecastDashboardReview(WireModel):
    TS_NAME = "ForecastDashboardReview"

    as_of: str | None = wire_optional(nullable=True)
    close_time: str | None = wire_optional(nullable=True)
    domain: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    latest_evidence_at: str | None = wire_optional(nullable=True)
    latest_evidence_claim: str | None = wire_optional(nullable=True)
    latest_evidence_summary: str | None = wire_optional(nullable=True)
    latest_rationale: str | None = wire_optional(nullable=True)
    next_action: str | None = wire_optional()
    priority: float | None = wire_optional()
    probability: _ProbOrDist | None = wire_optional(nullable=True)
    reasons: list[str] | None = wire_optional()
    resolution_time: str | None = wire_optional(nullable=True)
    title: str | None = wire_optional()


class ForecastDashboardSummary(WireModel):
    TS_NAME = "ForecastDashboardSummary"

    lifecycle: ForecastLifecycleSummary | None = wire_optional()

    active_count: int | None = wire_optional()
    alerts: list[ForecastDashboardAlert] | None = wire_optional()
    calibration: ForecastDashboardCalibration | None = wire_optional()
    doctor: ForecastDashboardDoctor | None = wire_optional()
    evidence_status: ForecastDashboardEvidenceStatus | None = wire_optional()
    live_performance: ForecastDashboardLivePerformance | None = wire_optional()
    learning: ForecastDashboardLearning | None = wire_optional()
    closing_soon_count: int | None = wire_optional()
    open_alert_count: int | None = wire_optional()
    open_assumption_count: int | None = wire_optional()
    open_reference_class_count: int | None = wire_optional()
    product: str | None = wire_optional()
    questions: list[ForecastDashboardQuestion] | None = wire_optional()
    review_queue: list[ForecastDashboardReview] | None = wire_optional()
    review_queue_count: int | None = wire_optional()
    recent_backtests: list[ForecastDashboardBacktest] | None = wire_optional()
    scheduled_review_run_count: int | None = wire_optional()
    scheduled_review_runs: list[ForecastDashboardScheduleRun] | None = wire_optional()
    stale_assumption_count: int | None = wire_optional()
    stale_reference_class_count: int | None = wire_optional()
    question_total: int | None = wire_optional()
    thesis_count: int | None = wire_optional()
    factor_count: int | None = wire_optional()
    entity_count: int | None = wire_optional()
    theses: list[ForecastDashboardThesis] | None = wire_optional()
    factors: list[ForecastDashboardFactor] | None = wire_optional()


class ForecastDashboardRequest(WireModel):
    TS_NAME = "ForecastDashboardRequest"

    limit: int | None = None
    fast: bool | None = None
    summary_only: bool | None = None


class ForecastDashboardResponse(WireModel):
    TS_NAME = "ForecastDashboardResponse"

    output: str | None = wire_optional()
    summary: ForecastDashboardSummary | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.calibration  (ledger.calibration_summary / calibration_bias / lessons)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastCalibrationCurveRow(WireModel):
    TS_NAME = "ForecastCalibrationCurveRow"

    bucket: str | None = wire_optional()
    calibration_gap: float | None = wire_optional(nullable=True)
    count: int | None = wire_optional()
    mean_predicted: float | None = wire_optional(nullable=True)
    observed_frequency: float | None = wire_optional(nullable=True)
    sample_status: str | None = wire_optional()


class ForecastCalibrationBucketRow(WireModel):
    TS_NAME = "ForecastCalibrationBucketRow"

    bucket: str | None = wire_optional()
    count: int | None = wire_optional()
    mean_brier: float | None = wire_optional(nullable=True)
    sample_status: str | None = wire_optional()


class ForecastCalibrationBias(WireModel):
    TS_NAME = "ForecastCalibrationBias"

    advisory_text: str | None = wire_optional(nullable=True)
    ci_high: float | None = wire_optional(nullable=True)
    ci_low: float | None = wire_optional(nullable=True)
    curve_shape: list[dict[str, Any]] | None = wire_optional()
    direction: str | None = wire_optional(nullable=True)
    ece: float | None = wire_optional(nullable=True)
    ess: float | None = wire_optional()
    ess_min: float | None = wire_optional()
    horizon_label: str | None = wire_optional(nullable=True)
    n: int | None = wire_optional()
    notes: list[str] | None = wire_optional()
    pvalue: float | None = wire_optional(nullable=True)
    scope_ref: str | None = wire_optional(nullable=True)
    scope_type: str | None = wire_optional()
    sce_raw: float | None = wire_optional(nullable=True)
    sce_shrunk: float | None = wire_optional(nullable=True)
    status: str | None = wire_optional()


class ForecastCalibrationTrendWindow(WireModel):
    TS_NAME = "ForecastCalibrationTrendWindow"

    brier: float | None = wire_optional(nullable=True)
    n: int | None = wire_optional()
    period: str | None = wire_optional()
    sce: float | None = wire_optional(nullable=True)


class ForecastCalibrationTrend(WireModel):
    TS_NAME = "ForecastCalibrationTrend"

    direction: str | None = wire_optional()
    windows: list[ForecastCalibrationTrendWindow] | None = wire_optional()


class ForecastCalibrationSummary(WireModel):
    """The full unsigned summary. The mirror ``extends ForecastDashboardCalibration``
    (a TS-only feature); we flatten — the shared calibration fields are declared here
    alongside the summary-only ones, so the generated interface is standalone."""

    TS_NAME = "ForecastCalibrationSummary"

    # inherited-from ForecastDashboardCalibration (flattened)
    calibration_eligible: bool | None = wire_optional(nullable=True)
    count: int | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    ensemble_component_contributions: (
        list[ForecastDashboardCalibrationComponent] | None
    ) = wire_optional()
    forecast_origin: str | None = wire_optional(nullable=True)
    horizon: str | None = wire_optional(nullable=True)
    mean_brier: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)
    mean_sharpness: float | None = wire_optional(nullable=True)
    probability_movement_count: int | None = wire_optional()
    mean_probability_movement_before_close: float | None = wire_optional(nullable=True)
    mean_abs_probability_movement_before_close: float | None = wire_optional(nullable=True)
    question_type_breakdown: (
        list[ForecastDashboardQuestionTypeCalibration] | None
    ) = wire_optional()
    # summary-only
    buckets: list[ForecastCalibrationBucketRow] | None = wire_optional()
    calibration_curve: list[ForecastCalibrationCurveRow] | None = wire_optional()
    calibration_curve_sample_count: int | None = wire_optional()
    calibration_trend: ForecastCalibrationTrend | None = wire_optional()
    expected_calibration_error: float | None = wire_optional(nullable=True)
    max_calibration_error: float | None = wire_optional(nullable=True)
    mean_predicted: float | None = wire_optional(nullable=True)
    observed_frequency: float | None = wire_optional(nullable=True)


class ForecastCalibrationLessonCoverage(WireModel):
    TS_NAME = "ForecastCalibrationLessonCoverage"

    application_rate: float | None = wire_optional()
    applied_count: int | None = wire_optional()
    in_scope_count: int | None = wire_optional()
    last_seen: str | None = wire_optional(nullable=True)


class ForecastCalibrationLesson(WireModel):
    TS_NAME = "ForecastCalibrationLesson"

    coverage: ForecastCalibrationLessonCoverage | None = wire_optional()
    dormant: bool | None = wire_optional()
    lesson: str | None = wire_optional(nullable=True)
    lesson_id: str | None = wire_optional()
    recommended_adjustment: dict[str, Any] | None = wire_optional()
    scope: str | None = wire_optional()
    scope_ref: str | None = wire_optional(nullable=True)
    scope_type: str | None = wire_optional()


class ForecastCalibrationBreakdownRow(WireModel):
    TS_NAME = "ForecastCalibrationBreakdownRow"

    bias: ForecastCalibrationBias | None = wire_optional(nullable=True)
    calibration_curve_sample_count: int | None = wire_optional()
    count: int | None = wire_optional()
    domain: str | None = wire_optional()
    expected_calibration_error: float | None = wire_optional(nullable=True)
    mean_brier: float | None = wire_optional(nullable=True)
    mean_predicted: float | None = wire_optional(nullable=True)
    observed_frequency: float | None = wire_optional(nullable=True)
    origin: str | None = wire_optional()


class ForecastContinuousScorecard(WireModel):
    """The ordered/numeric class, scored SEPARATELY by CRPS / log — a Brier
    cannot represent it, so it never joins the binary cohorts."""

    TS_NAME = "ForecastContinuousScorecard"

    n: int | None = wire_optional()
    mean_crps: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)
    live_calibration_eligible_n: int | None = wire_optional()
    domains: list[str] | None = wire_optional()
    by_rule: dict[str, Any] | None = wire_optional()


class ForecastPooledDiagnostic(WireModel):
    """The pooled all-artifact Brier — retained ONLY as an explicitly-labelled
    ledger-wide diagnostic, NEVER a skill claim."""

    TS_NAME = "ForecastPooledDiagnostic"

    label: str | None = wire_optional()
    n: int | None = wire_optional()
    mean_brier: float | None = wire_optional(nullable=True)


class ForecastQuarantineSummary(WireModel):
    TS_NAME = "ForecastQuarantineSummary"

    n: int | None = wire_optional()
    reasons: dict[str, Any] | None = wire_optional()


class ForecastDifficultyAdjustment(WireModel):
    """BLF A6 / ABI — the difficulty-adjustment summary. Difficulty = the recorded
    market/crowd anchor's Brier vs the outcome; the per-cohort adjusted column
    re-centres raw Brier by the difficulty of each cohort's own question mix so a
    hard-question desk is not punished. Anchorless rows are shown unadjusted."""

    TS_NAME = "ForecastDifficultyAdjustment"

    method: str | None = wire_optional()
    reference_difficulty: float | None = wire_optional(nullable=True)
    n_eligible: int | None = wire_optional()
    n_no_anchor: int | None = wire_optional()
    provenance: dict[str, Any] | None = wire_optional()
    limits: str | None = wire_optional()


class ForecastCohortScoreboard(WireModel):
    """Score aggregates SEPARATED BY COHORT — the honest default. Never a pooled
    all-artifact Brier as a headline."""

    TS_NAME = "ForecastCohortScoreboard"

    cohorts: dict[str, Any] | None = wire_optional()
    continuous_scorecard: ForecastContinuousScorecard | None = wire_optional()
    pooled_diagnostic: ForecastPooledDiagnostic | None = wire_optional()
    difficulty_adjustment: ForecastDifficultyAdjustment | None = wire_optional()
    quarantined: ForecastQuarantineSummary | None = wire_optional()


class ForecastCalibrationRequest(WireModel):
    TS_NAME = "ForecastCalibrationRequest"

    domain: str | None = None
    origin: str | None = None


class ForecastCalibrationResponse(WireModel):
    TS_NAME = "ForecastCalibrationResponse"

    bias: ForecastCalibrationBias | None = wire_optional(nullable=True)
    cohort_scoreboard: ForecastCohortScoreboard | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    domains: list[ForecastCalibrationBreakdownRow] | None = wire_optional()
    lessons: list[ForecastCalibrationLesson] | None = wire_optional()
    origin: str | None = wire_optional(nullable=True)
    origins: list[ForecastCalibrationBreakdownRow] | None = wire_optional()
    summary: ForecastCalibrationSummary | None = wire_optional()
    # ``operator`` (operator practice-loop calibration) is emitted payload-only and
    # has no mirror; tolerated by extra='ignore'.


# ══════════════════════════════════════════════════════════════════════════════
# forecast.triage.contested / .relabel
# ══════════════════════════════════════════════════════════════════════════════


class ForecastTriageContestedRow(WireModel):
    TS_NAME = "ForecastTriageContestedRow"

    alert_id: str | None = wire_optional(nullable=True)
    auto_label: str | None = wire_optional(nullable=True)
    candidate_ref: str | None = wire_optional(nullable=True)
    created_at: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    materiality: str | None = wire_optional(nullable=True)
    question_id: str | None = wire_optional(nullable=True)
    rationale: str | None = wire_optional()
    relevance: float | None = wire_optional(nullable=True)
    source: str | None = wire_optional(nullable=True)
    summary: str | None = wire_optional()
    title: str | None = wire_optional()
    url: str | None = wire_optional(nullable=True)


class ForecastTriageContestedRequest(WireModel):
    TS_NAME = "ForecastTriageContestedRequest"

    limit: int | None = None
    question_id: str | None = None
    question: str | None = None


class ForecastTriageContestedResponse(WireModel):
    TS_NAME = "ForecastTriageContestedResponse"

    contested: list[ForecastTriageContestedRow] | None = wire_optional()
    count: int | None = wire_optional()


class ForecastTriageRelabelRequest(WireModel):
    TS_NAME = "ForecastTriageRelabelRequest"

    label_id: str | None = None
    label: str | None = None
    adjudications: list[dict[str, Any]] | None = None


class ForecastTriageRelabelResponse(WireModel):
    TS_NAME = "ForecastTriageRelabelResponse"

    count: int | None = wire_optional()
    relabeled: list[dict[str, Any]] | None = wire_optional()
    success: bool | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.schedule.status
# ══════════════════════════════════════════════════════════════════════════════


class ForecastScheduleCronJob(WireModel):
    TS_NAME = "ForecastScheduleCronJob"

    enabled: bool | None = wire_optional()
    errored: bool | None = wire_optional()
    id: str | None = wire_optional(nullable=True)
    last_error: str | None = wire_optional(nullable=True)
    last_run_at: str | None = wire_optional(nullable=True)
    last_status: str | None = wire_optional(nullable=True)
    missed: bool | None = wire_optional()
    name: str | None = wire_optional(nullable=True)
    next_run_at: str | None = wire_optional(nullable=True)
    schedule: str | None = wire_optional(nullable=True)
    script: str | None = wire_optional(nullable=True)


class ForecastScheduleCronHealth(WireModel):
    TS_NAME = "ForecastScheduleCronHealth"

    errored: list[str] | None = wire_optional()
    healthy: bool | None = wire_optional()
    installed: int | None = wire_optional()
    jobs: list[ForecastScheduleCronJob] | None = wire_optional()
    missed: list[str] | None = wire_optional()


class ForecastScheduleReviewRow(WireModel):
    TS_NAME = "ForecastScheduleReviewRow"

    cadence: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    last_run_at: str | None = wire_optional(nullable=True)
    next_run_at: str | None = wire_optional(nullable=True)
    scope_ref: str | None = wire_optional(nullable=True)
    scope_type: str | None = wire_optional(nullable=True)
    trigger_reason: str | None = wire_optional(nullable=True)


class ForecastScheduleStatusRequest(WireModel):
    TS_NAME = "ForecastScheduleStatusRequest"

    limit: int | None = None


class ForecastScheduleStatusResponse(WireModel):
    TS_NAME = "ForecastScheduleStatusResponse"

    cron: ForecastScheduleCronHealth | None = wire_optional()
    healthy: bool | None = wire_optional()
    scheduled_review_count: int | None = wire_optional()
    scheduled_reviews: list[ForecastScheduleReviewRow] | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.quorum.status
# ══════════════════════════════════════════════════════════════════════════════


class ForecastQuorumRunRef(WireModel):
    TS_NAME = "ForecastQuorumRunRef"

    created_at: str | None = wire_optional(nullable=True)
    run_id: str | None = wire_optional()
    status: str | None = wire_optional()


class ForecastQuorumStatusResult(WireModel):
    """The quorum ``result`` summary. The mirror added a ``[key: string]: unknown``
    index signature (codegen can't emit it); we model the named headline fields and
    stay ``extra='ignore'`` tolerant of the richer per-model detail on the wire."""

    TS_NAME = "ForecastQuorumStatusResult"

    aggregate_probability: float | None = wire_optional(nullable=True)
    committed_probability: float | None = wire_optional(nullable=True)
    disagreement: float | None = wire_optional(nullable=True)
    degraded: bool | None = wire_optional()


class ForecastQuorumProgressStep(WireModel):
    TS_NAME = "ForecastQuorumProgressStep"

    at: str | None = wire_optional()
    detail: str | None = wire_optional()
    stage: str | None = wire_optional()


class ForecastQuorumStatusRequest(WireModel):
    TS_NAME = "ForecastQuorumStatusRequest"

    run_id: str | None = None


class ForecastQuorumStatusResponse(WireModel):
    TS_NAME = "ForecastQuorumStatusResponse"

    degraded: bool | None = wire_optional()
    error: str | None = wire_optional(nullable=True)
    panel_run_id: str | None = wire_optional(nullable=True)
    progress: list[ForecastQuorumProgressStep] | None = wire_optional()
    question_id: str | None = wire_optional(nullable=True)
    result: ForecastQuorumStatusResult | None = wire_optional()
    run_id: str | None = wire_optional()
    status: str | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.bench  (build_bench_scoreboard)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastBenchRow(WireModel):
    TS_NAME = "ForecastBenchRow"

    id: str
    title: str | None = wire_optional()
    source: str | None = wire_optional(nullable=True)
    domain: str | None = wire_optional(nullable=True)
    topics: list[str] | None = wire_optional()
    as_of: str | None = wire_optional(nullable=True)
    resolved_at: str | None = wire_optional(nullable=True)
    agent_probability: float | None = wire_optional(nullable=True)
    agent_probability_display: str | None = wire_optional()
    market_probability: float | None = wire_optional(nullable=True)
    market_probability_display: str | None = wire_optional()
    outcome: float | None = wire_optional(nullable=True)
    outcome_label: str | None = wire_optional(nullable=True)
    resolved: bool | None = wire_optional()
    agent_brier: float | None = wire_optional(nullable=True)
    market_brier: float | None = wire_optional(nullable=True)
    brier_edge: float | None = wire_optional(nullable=True)


class ForecastBenchAggregate(WireModel):
    TS_NAME = "ForecastBenchAggregate"

    n: int | None = wire_optional()
    mean_agent_brier: float | None = wire_optional(nullable=True)
    mean_market_brier: float | None = wire_optional(nullable=True)
    mean_brier_edge: float | None = wire_optional(nullable=True)


class ForecastBenchRequest(WireModel):
    TS_NAME = "ForecastBenchRequest"

    limit: int | None = None


class ForecastBenchResponse(WireModel):
    TS_NAME = "ForecastBenchResponse"

    product: str | None = wire_optional()
    generated_at: str | None = wire_optional()
    count: int | None = wire_optional()
    resolved_count: int | None = wire_optional()
    rows: list[ForecastBenchRow] | None = wire_optional()
    aggregate: ForecastBenchAggregate | None = wire_optional()
    output: str | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.workspace / forecast.theses  (thesis + factor + workspace item)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastThesisBadge(WireModel):
    TS_NAME = "ForecastThesisBadge"

    thesis_id: str
    thesis_title: str | None = wire_optional()
    direction: str | None = wire_optional()
    weight: float | None = wire_optional(nullable=True)
    role: str | None = wire_optional(nullable=True)


class ForecastThesisComponent(WireModel):
    TS_NAME = "ForecastThesisComponent"

    id: str | None = wire_optional()
    title: str | None = wire_optional(nullable=True)
    direction: str | None = wire_optional()
    role: str | None = wire_optional(nullable=True)
    weight: float | None = wire_optional(nullable=True)
    w_norm: float | None = wire_optional(nullable=True)
    s_raw: float | None = wire_optional(nullable=True)
    s_i: float | None = wire_optional(nullable=True)
    sigma: float | None = wire_optional(nullable=True)
    contribution_pts: float | None = wire_optional(nullable=True)
    marginal_health_delta: float | None = wire_optional(nullable=True)
    status: str | None = wire_optional()
    flags: list[str] | None = wire_optional()
    as_of: str | None = wire_optional(nullable=True)
    outcome_type: str | None = wire_optional(nullable=True)
    latest_belief_display: str | None = wire_optional()
    latest_headline: float | None = wire_optional(nullable=True)


class ForecastThesisHistoryPoint(WireModel):
    TS_NAME = "ForecastThesisHistoryPoint"

    as_of: str | None = wire_optional()
    created_at: str | None = wire_optional()
    headline_probability: float | None = wire_optional(nullable=True)
    # The regime the headline point belongs to: "event" once a joint-threshold
    # event is configured (P(event) is the series), else "health" (the mean-index
    # health). The desk restricts window deltas to a single regime so a delta
    # never straddles the series switch.
    headline_regime: str | None = wire_optional()
    thesis_score: float | None = wire_optional(nullable=True)
    score_low: float | None = wire_optional(nullable=True)
    score_high: float | None = wire_optional(nullable=True)
    # The 90% interval on the P(event) headline for THIS point (second-order MC
    # band); the desk draws the band around the event series in the event regime.
    event_low: float | None = wire_optional(nullable=True)
    event_high: float | None = wire_optional(nullable=True)


class ForecastThesisEntity(WireModel):
    TS_NAME = "ForecastThesisEntity"

    name: str | None = wire_optional()
    label: str | None = wire_optional()
    kind: str | None = wire_optional()
    suitability: float | None = wire_optional(nullable=True)
    suitability_display: str | None = wire_optional()
    score: float | None = wire_optional(nullable=True)
    band: list[float] | None = wire_optional(nullable=True)
    coverage: float | None = wire_optional(nullable=True)
    n_eff: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    stance: str | None = wire_optional()
    trend: str | None = wire_optional()
    action: str | None = wire_optional()
    top_driver: str | None = wire_optional(nullable=True)
    top_driver_id: str | None = wire_optional(nullable=True)
    weight_count: int | None = wire_optional()
    contributions: list[ForecastThesisComponent] | None = wire_optional()


class ForecastThesisTrigger(WireModel):
    TS_NAME = "ForecastThesisTrigger"

    member_id: str | None = wire_optional()
    signal: str | None = wire_optional()
    delta: float | None = wire_optional(nullable=True)
    direction: str | None = wire_optional()
    note: str | None = wire_optional()
    better: list[str] | None = wire_optional()
    less: list[str] | None = wire_optional()


class ForecastThesisScoreBand(WireModel):
    TS_NAME = "ForecastThesisScoreBand"

    q05: float | None = wire_optional(nullable=True)
    q50: float | None = wire_optional(nullable=True)
    q95: float | None = wire_optional(nullable=True)


class ForecastThesisEventBand(WireModel):
    """The 90% interval ON the P(event) headline (second-order MC over the
    member-probability + rho uncertainty). p10/p50/p90 are on the 0..1 event
    scale. Present even for an all-binary thesis (whose mean-index score band is
    honestly withheld); None when no event is configured or none participates."""

    TS_NAME = "ForecastThesisEventBand"

    p10: float | None = wire_optional(nullable=True)
    p50: float | None = wire_optional(nullable=True)
    p90: float | None = wire_optional(nullable=True)


class ForecastThesisSensitivity(WireModel):
    """Per-member ∂P(event)/∂p_i from the thesis event MC — "which race matters".
    ``delta_p_event`` is the P(event) swing across the member's ±2pp bump (already
    event-scaled); the desk reads it as the thesis-lens sensitivity marker."""

    TS_NAME = "ForecastThesisSensitivity"

    member_id: str | None = wire_optional()
    title: str | None = wire_optional(nullable=True)
    direction: str | None = wire_optional()
    p: float | None = wire_optional(nullable=True)
    sensitivity: float | None = wire_optional(nullable=True)
    delta_p_event: float | None = wire_optional(nullable=True)
    p_event_at_plus: float | None = wire_optional(nullable=True)
    p_event_at_minus: float | None = wire_optional(nullable=True)


class ForecastThesis(WireModel):
    TS_NAME = "ForecastThesis"

    id: str | None = wire_optional()
    title: str | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    topics: list[str] | None = wire_optional()
    status: str | None = wire_optional()
    as_of: str | None = wire_optional(nullable=True)
    freshness: str | None = wire_optional()
    health_probability: float | None = wire_optional(nullable=True)
    health_display: str | None = wire_optional()
    # The desk headline: event_probability when an event is configured, else the
    # health pool — the server emits these for thesis rows (the pinned thesis
    # table row reads PROB from here).
    headline_probability: float | None = wire_optional(nullable=True)
    headline_display: str | None = wire_optional()
    event_probability: float | None = wire_optional(nullable=True)
    # The honest 90% interval ON the P(event) headline (second-order MC band).
    # This is the interval an all-binary thesis CAN publish even though its
    # mean-index score_band is withheld (binary members carry no calibrated
    # 0..1-unit dispersion). None when no event is configured / none participates.
    event_band: ForecastThesisEventBand | None = wire_optional(nullable=True)
    thesis_score: float | None = wire_optional(nullable=True)
    score_band: ForecastThesisScoreBand | None = wire_optional(nullable=True)
    coverage: float | None = wire_optional(nullable=True)
    n_eff: float | None = wire_optional(nullable=True)
    rho: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    member_count: int | None = wire_optional()
    aggregate_stale: bool | None = wire_optional()
    components: list[ForecastThesisComponent] | None = wire_optional()
    # The top members whose ±2pp move most swings P(event) — the desk's thesis-lens
    # sensitivity markers (dashboard.py emits these on every thesis payload).
    top_sensitivities: list[ForecastThesisSensitivity] | None = wire_optional()
    spread: dict[str, Any] | None = wire_optional(nullable=True)
    history: list[ForecastThesisHistoryPoint] | None = wire_optional()
    analyst_note: ForecastAnalystNote | None = wire_optional(nullable=True)
    rationale: str | None = wire_optional(nullable=True)
    snapshot_count: int | None = wire_optional()
    entities: list[ForecastThesisEntity] | None = wire_optional()
    triggers: list[ForecastThesisTrigger] | None = wire_optional()
    question_ids: list[str] | None = wire_optional()


class ForecastFactorConstituent(WireModel):
    TS_NAME = "ForecastFactorConstituent"

    id: str | None = wire_optional()
    title: str | None = wire_optional(nullable=True)
    direction: str | None = wire_optional()
    weight: float | None = wire_optional(nullable=True)
    w_norm: float | None = wire_optional(nullable=True)
    mean: float | None = wire_optional(nullable=True)
    sd: float | None = wire_optional(nullable=True)
    contribution: float | None = wire_optional(nullable=True)
    status: str | None = wire_optional()
    flags: list[str] | None = wire_optional()


class ForecastFactorHistoryPoint(WireModel):
    TS_NAME = "ForecastFactorHistoryPoint"

    as_of: str | None = wire_optional()
    created_at: str | None = wire_optional()
    headline_probability: float | None = wire_optional(nullable=True)
    band_low: float | None = wire_optional(nullable=True)
    band_high: float | None = wire_optional(nullable=True)
    volatility: float | None = wire_optional(nullable=True)


class ForecastFactor(WireModel):
    TS_NAME = "ForecastFactor"

    id: str | None = wire_optional()
    title: str | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    topics: list[str] | None = wire_optional()
    units: str | None = wire_optional(nullable=True)
    as_of: str | None = wire_optional(nullable=True)
    freshness: str | None = wire_optional()
    mean: float | None = wire_optional(nullable=True)
    sd: float | None = wire_optional(nullable=True)
    volatility: float | None = wire_optional(nullable=True)
    q05: float | None = wire_optional(nullable=True)
    q50: float | None = wire_optional(nullable=True)
    q95: float | None = wire_optional(nullable=True)
    downside: float | None = wire_optional(nullable=True)
    cvar: float | None = wire_optional(nullable=True)
    coverage: float | None = wire_optional(nullable=True)
    n_eff: float | None = wire_optional(nullable=True)
    delta: float | None = wire_optional(nullable=True)
    member_count: int | None = wire_optional()
    aggregate_stale: bool | None = wire_optional()
    constituents: list[ForecastFactorConstituent] | None = wire_optional()
    question_ids: list[str] | None = wire_optional()
    history: list[ForecastFactorHistoryPoint] | None = wire_optional()
    analyst_note: ForecastAnalystNote | None = wire_optional(nullable=True)
    rationale: str | None = wire_optional(nullable=True)
    snapshot_count: int | None = wire_optional()


class ForecastWorkspacePmfPoint(WireModel):
    TS_NAME = "ForecastWorkspacePmfPoint"

    label: str
    probability: float


class ForecastWorkspaceDistribution(WireModel):
    TS_NAME = "ForecastWorkspaceDistribution"

    ci50: list[float] | None = wire_optional(nullable=True)
    ci90: list[float] | None = wire_optional(nullable=True)
    mean: float | None = wire_optional(nullable=True)
    median: float | None = wire_optional(nullable=True)
    pmf: list[ForecastWorkspacePmfPoint] | None = wire_optional(nullable=True)
    sd: float | None = wire_optional(nullable=True)


class ForecastWorkspaceHistoryPoint(WireModel):
    TS_NAME = "ForecastWorkspaceHistoryPoint"

    as_of: str | None = wire_optional()
    band_high: float | None = wire_optional(nullable=True)
    band_low: float | None = wire_optional(nullable=True)
    confidence: float | None = wire_optional(nullable=True)
    created_at: str | None = wire_optional()
    forecast_id: str | None = wire_optional()
    forecast_origin: str | None = wire_optional()
    headline_probability: float | None = wire_optional(nullable=True)
    method: str | None = wire_optional(nullable=True)
    probability: _ProbOrDist | None = wire_optional(nullable=True)
    rationale: str | None = wire_optional()
    reasons_down_count: int | None = wire_optional()
    reasons_up_count: int | None = wire_optional()


class ForecastWorkspaceEvidence(WireModel):
    TS_NAME = "ForecastWorkspaceEvidence"

    available_at: str | None = wire_optional()
    claim: str | None = wire_optional()
    claim_type: str | None = wire_optional()
    id: str | None = wire_optional()
    published_at: str | None = wire_optional(nullable=True)
    relevance_rating: float | None = wire_optional(nullable=True)
    reliability_rating: float | None = wire_optional(nullable=True)
    source: str | None = wire_optional()
    source_type: str | None = wire_optional()
    stance: str | None = wire_optional()
    summary: str | None = wire_optional()


class ForecastWorkspacePanelEstimate(WireModel):
    TS_NAME = "ForecastWorkspacePanelEstimate"

    # BLF A1 — the compact per-panelist belief arc ("40%→55% · 3 steps · moved by:
    # the CPI print"); null on a legacy / pre-harvest estimate with no trajectory.
    belief: str | None = wire_optional(nullable=True)
    confidence_high: float | None = wire_optional(nullable=True)
    confidence_low: float | None = wire_optional(nullable=True)
    crux: str | None = wire_optional(nullable=True)
    perspective: str | None = wire_optional()
    probability: float | None = wire_optional(nullable=True)
    trimmed: bool | None = wire_optional()
    weight: float | None = wire_optional(nullable=True)


class ForecastWorkspacePanel(WireModel):
    TS_NAME = "ForecastWorkspacePanel"

    aggregate_probability: float | None = wire_optional(nullable=True)
    aggregation_method: str | None = wire_optional()
    created_at: str | None = wire_optional()
    estimates: list[ForecastWorkspacePanelEstimate] | None = wire_optional()
    id: str | None = wire_optional()
    kind: str | None = wire_optional()
    spread: dict[str, float] | None = wire_optional()
    trim: float | None = wire_optional()


class ForecastWorkspaceScores(WireModel):
    TS_NAME = "ForecastWorkspaceScores"

    count: int | None = wire_optional()
    last_bucket: str | None = wire_optional(nullable=True)
    last_scored_at: str | None = wire_optional(nullable=True)
    mean_brier: float | None = wire_optional(nullable=True)
    mean_log_score: float | None = wire_optional(nullable=True)


class ForecastWorkspaceResolution(WireModel):
    TS_NAME = "ForecastWorkspaceResolution"

    outcome: Any | None = wire_optional()
    resolution_status: str | None = wire_optional()
    resolved_at: str | None = wire_optional()
    scoreable: bool | None = wire_optional()


class ForecastWorkspaceTrigger(WireModel):
    TS_NAME = "ForecastWorkspaceTrigger"

    action: str | None = wire_optional()
    mechanism: str | None = wire_optional()
    notes: str | None = wire_optional()
    source_ref: str | None = wire_optional()
    threshold: str | None = wire_optional()
    window: str | None = wire_optional()


class ForecastCandidateInterval(WireModel):
    TS_NAME = "ForecastCandidateInterval"

    hi: float
    lo: float
    mid: float | None = wire_optional()


class ForecastVoiStaleness(WireModel):
    TS_NAME = "ForecastVoiStaleness"

    age_days: float | None = wire_optional(nullable=True)
    cadence_days: float | None = wire_optional()
    ratio: float | None = wire_optional()
    norm: float | None = wire_optional()
    weighted: float | None = wire_optional()


class ForecastVoiProximity(WireModel):
    TS_NAME = "ForecastVoiProximity"

    days_until: float | None = wire_optional(nullable=True)
    resolve_days: float | None = wire_optional(nullable=True)
    horizon_days: float | None = wire_optional()
    norm: float | None = wire_optional()
    weighted: float | None = wire_optional()


class ForecastVoiAlerts(WireModel):
    TS_NAME = "ForecastVoiAlerts"

    count: int | None = wire_optional()
    norm: float | None = wire_optional()
    weighted: float | None = wire_optional()


class ForecastVoiSensitivity(WireModel):
    TS_NAME = "ForecastVoiSensitivity"

    abs_pp: float | None = wire_optional()
    delta_p_event: float | None = wire_optional(nullable=True)
    thesis_id: str | None = wire_optional(nullable=True)
    thesis_title: str | None = wire_optional(nullable=True)


class ForecastVoiReadiness(WireModel):
    TS_NAME = "ForecastVoiReadiness"

    src_count: int | None = wire_optional()
    has_sources: bool | None = wire_optional()
    dampen: float | None = wire_optional()


class ForecastVoiComponents(WireModel):
    TS_NAME = "ForecastVoiComponents"

    base: float | None = wire_optional()
    amplifier: float | None = wire_optional()
    staleness: ForecastVoiStaleness | None = wire_optional()
    proximity: ForecastVoiProximity | None = wire_optional()
    alerts: ForecastVoiAlerts | None = wire_optional()
    sensitivity: ForecastVoiSensitivity | None = wire_optional()
    readiness: ForecastVoiReadiness | None = wire_optional()


class ForecastVoi(WireModel):
    """VOI-driven desk attention: an explainable "touch this next" priority. The
    score is an additive base (cadence-relative staleness + resolution/review
    proximity + open-alert pressure) times a thesis-sensitivity amplifier, dampened
    when the question has no watched sources. ``action`` is the honest next verb."""

    TS_NAME = "ForecastVoi"

    score: float | None = wire_optional()
    rank: int | None = wire_optional()
    action: str | None = wire_optional()
    reason: str | None = wire_optional()
    components: ForecastVoiComponents | None = wire_optional()


class ForecastNextAction(WireModel):
    """One desk-level "next best action" — the workspace payload carries the top-5
    ranked across the whole book so the CLI/agent and the TUI read the SAME list."""

    TS_NAME = "ForecastNextAction"

    question_id: str | None = wire_optional()
    title: str | None = wire_optional(nullable=True)
    action: str | None = wire_optional()
    reason: str | None = wire_optional()
    score: float | None = wire_optional()


class ForecastWorkspaceItem(WireModel):
    TS_NAME = "ForecastWorkspaceItem"

    action_threshold: str | None = wire_optional(nullable=True)
    analyst_note: ForecastAnalystNote | None = wire_optional(nullable=True)
    analyst_notes: list[ForecastAnalystNote] | None = wire_optional()
    as_of: str | None = wire_optional(nullable=True)
    candidate_intervals: dict[str, ForecastCandidateInterval] | None = wire_optional(nullable=True)
    change_my_mind: list[str] | None = wire_optional()
    close_time: str | None = wire_optional(nullable=True)
    closing_soon: bool | None = wire_optional()
    confidence: float | None = wire_optional(nullable=True)
    decision_deadline: str | None = wire_optional(nullable=True)
    decision_owner: str | None = wire_optional(nullable=True)
    decision_readiness_issues: list[str] | None = wire_optional()
    delta: float | None = wire_optional(nullable=True)
    distribution: ForecastWorkspaceDistribution | None = wire_optional(nullable=True)
    domain: str | None = wire_optional(nullable=True)
    evidence: list[ForecastWorkspaceEvidence] | None = wire_optional()
    evidence_count: int | None = wire_optional()
    freshness: str | None = wire_optional()
    next_review_at: str | None = wire_optional(nullable=True)
    review_cadence: str | None = wire_optional(nullable=True)
    headline_kind: str | None = wire_optional()
    headline_probability: float | None = wire_optional(nullable=True)
    history: list[ForecastWorkspaceHistoryPoint] | None = wire_optional()
    id: str | None = wire_optional()
    impact: str | None = wire_optional(nullable=True)
    lessons_count: int | None = wire_optional()
    method: str | None = wire_optional(nullable=True)
    open_alert_count: int | None = wire_optional()
    outcome_choices: list[Any] | None = wire_optional()
    quorum_run: ForecastQuorumRunRef | None = wire_optional(nullable=True)
    relevant_lessons: list[ForecastDashboardLesson] | None = wire_optional()
    outcome_type: str | None = wire_optional()
    panel: ForecastWorkspacePanel | None = wire_optional(nullable=True)
    probability: _ProbOrDist | None = wire_optional(nullable=True)
    probability_display: str | None = wire_optional()
    rationale: str | None = wire_optional(nullable=True)
    reasons_down: list[str] | None = wire_optional()
    reasons_up: list[str] | None = wire_optional()
    related: ForecastRelated | None = wire_optional(nullable=True)
    resolution: ForecastWorkspaceResolution | None = wire_optional(nullable=True)
    resolution_criteria: str | None = wire_optional()
    resolution_time: str | None = wire_optional(nullable=True)
    retrospective: ForecastAnalystNote | None = wire_optional(nullable=True)
    saturation_score: float | None = wire_optional(nullable=True)
    saturation_below_threshold: bool | None = wire_optional()
    src_count: int | None = wire_optional()
    readiness: ForecastReadiness | None = wire_optional(nullable=True)
    scores: ForecastWorkspaceScores | None = wire_optional(nullable=True)
    snapshot_count: int | None = wire_optional()
    status: str | None = wire_optional()
    tail_audit: ForecastTailAudit | None = wire_optional(nullable=True)
    title: str | None = wire_optional()
    topics: list[str] | None = wire_optional()
    units: str | None = wire_optional(nullable=True)
    update_triggers: list[ForecastWorkspaceTrigger] | None = wire_optional()
    thesis_ids: list[ForecastThesisBadge] | None = wire_optional()
    # VOI-driven desk attention: this forecast's explainable "touch next" priority
    # (score + rank + per-component breakdown + the honest next action).
    voi: ForecastVoi | None = wire_optional(nullable=True)


class ForecastWorkspaceRequest(WireModel):
    TS_NAME = "ForecastWorkspaceRequest"

    limit: int | None = None


class ForecastWorkspaceResponse(WireModel):
    TS_NAME = "ForecastWorkspaceResponse"

    active_count: int | None = wire_optional()
    bench_count: int | None = wire_optional()
    closing_soon_count: int | None = wire_optional()
    factor_count: int | None = wire_optional()
    factors: list[ForecastFactor] | None = wire_optional()
    forecasts: list[ForecastWorkspaceItem] | None = wire_optional()
    generated_at: str | None = wire_optional()
    # The desk-level VOI ranking: the top-5 highest-value next actions across the
    # whole book (each {question_id, title, action, reason, score}).
    next_actions: list[ForecastNextAction] | None = wire_optional()
    open_alert_count: int | None = wire_optional()
    operations: dict[str, Any] | None = wire_optional()
    output: str | None = wire_optional()
    product: str | None = wire_optional()
    thesis_count: int | None = wire_optional()
    theses: list[ForecastThesis] | None = wire_optional()


class ForecastThesesResponse(WireModel):
    """``forecast.theses`` → ``{theses, factors}`` (a standalone thesis/factor list
    without the whole workspace)."""

    TS_NAME = "ForecastThesesResponse"

    theses: list[ForecastThesis] | None = wire_optional()
    factors: list[ForecastFactor] | None = wire_optional()


class ForecastThesesRequest(WireModel):
    TS_NAME = "ForecastThesesRequest"


# ══════════════════════════════════════════════════════════════════════════════
# forecast.question  (export_question packet + related + lessons)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastOutcomeSpace(WireModel):
    TS_NAME = "ForecastOutcomeSpace"

    choices: list[Any] | None = wire_optional()
    type: str | None = wire_optional()


class ForecastQuestionPacketQuestion(WireModel):
    TS_NAME = "ForecastQuestionPacketQuestion"

    close_time: str | None = wire_optional(nullable=True)
    created_at: str | None = wire_optional()
    description: str | None = wire_optional()
    domain: str | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    impact: str | None = wire_optional(nullable=True)
    next_review_at: str | None = wire_optional(nullable=True)
    outcome_space: ForecastOutcomeSpace | None = wire_optional()
    resolution_criteria: str | None = wire_optional()
    resolution_source: str | None = wire_optional(nullable=True)
    resolution_time: str | None = wire_optional(nullable=True)
    review_cadence: str | None = wire_optional(nullable=True)
    status: str | None = wire_optional()
    tags: list[str] | None = wire_optional()
    title: str | None = wire_optional()
    topics: list[str] | None = wire_optional()


class ForecastQuestionPacketSnapshot(WireModel):
    TS_NAME = "ForecastQuestionPacketSnapshot"

    as_of: str | None = wire_optional()
    change_my_mind: list[str] | None = wire_optional()
    confidence: float | None = wire_optional(nullable=True)
    ensemble_components: dict[str, Any] | None = wire_optional(nullable=True)
    evidence_refs: list[str] | None = wire_optional()
    forecast_id: str | None = wire_optional()
    forecast_origin: str | None = wire_optional()
    metadata: ForecastSnapshotMetadata | None = wire_optional(nullable=True)
    method: str | None = wire_optional(nullable=True)
    probability_or_distribution: _ProbOrDist | None = wire_optional(nullable=True)
    rationale: str | None = wire_optional()
    reasons_down: list[str] | None = wire_optional()
    reasons_up: list[str] | None = wire_optional()


class ForecastQuestionPacketPanelRun(WireModel):
    TS_NAME = "ForecastQuestionPacketPanelRun"

    aggregate_probability: float | None = wire_optional(nullable=True)
    aggregation_method: str | None = wire_optional()
    created_at: str | None = wire_optional()
    estimates: list[ForecastWorkspacePanelEstimate] | None = wire_optional()
    id: str | None = wire_optional()
    spread_summary: dict[str, float] | None = wire_optional()
    trim: float | None = wire_optional()


class ForecastQuestionPacketEvidence(WireModel):
    TS_NAME = "ForecastQuestionPacketEvidence"

    available_at: str | None = wire_optional()
    claim: str | None = wire_optional()
    claim_type: str | None = wire_optional()
    id: str | None = wire_optional()
    published_at: str | None = wire_optional(nullable=True)
    relevance_rating: float | None = wire_optional(nullable=True)
    reliability_rating: float | None = wire_optional(nullable=True)
    source_name: str | None = wire_optional(nullable=True)
    source_type: str | None = wire_optional()
    source_url: str | None = wire_optional(nullable=True)
    stance: str | None = wire_optional()
    summary: str | None = wire_optional()


class ForecastQuestionPacketAssumption(WireModel):
    TS_NAME = "ForecastQuestionPacketAssumption"

    id: str | None = wire_optional()
    status: str | None = wire_optional()
    text: str | None = wire_optional()


class ForecastQuestionPacketReferenceClass(WireModel):
    TS_NAME = "ForecastQuestionPacketReferenceClass"

    base_rate: float | None = wire_optional(nullable=True)
    id: str | None = wire_optional()
    name: str | None = wire_optional()
    status: str | None = wire_optional()


class ForecastQuestionPacket(WireModel):
    TS_NAME = "ForecastQuestionPacket"

    applicability_facts: dict[str, Any] | None = wire_optional()
    settlement_review: dict[str, Any] | None = wire_optional(nullable=True)

    analyst_note: ForecastAnalystNote | None = wire_optional(nullable=True)
    analyst_notes: list[ForecastAnalystNote] | None = wire_optional()
    assumptions: list[ForecastQuestionPacketAssumption] | None = wire_optional()
    baseline_comparisons: list[dict[str, Any]] | None = wire_optional()
    calibration_lessons: list[ForecastDashboardLesson] | None = wire_optional()
    corrections: list[dict[str, Any]] | None = wire_optional()
    domain_error_profiles: list[ForecastDashboardErrorProfile] | None = wire_optional()
    evidence: list[ForecastQuestionPacketEvidence] | None = wire_optional()
    forecast_history: list[ForecastQuestionPacketSnapshot] | None = wire_optional()
    informed_by: list[str] | None = wire_optional()
    model_runs: list[dict[str, Any]] | None = wire_optional()
    panel_runs: list[ForecastQuestionPacketPanelRun] | None = wire_optional()
    postmortems: list[dict[str, Any]] | None = wire_optional()
    question: ForecastQuestionPacketQuestion | None = wire_optional()
    reference_classes: list[ForecastQuestionPacketReferenceClass] | None = wire_optional()
    related_forecasts: list[ForecastRelatedView] | None = wire_optional()
    related_shared_sources: list[ForecastSharedSource] | None = wire_optional()
    resolution: dict[str, Any] | None = wire_optional(nullable=True)
    retrospective: ForecastAnalystNote | None = wire_optional(nullable=True)
    scores: list[dict[str, Any]] | None = wire_optional()
    watched_sources: list[dict[str, Any]] | None = wire_optional()


class ForecastQuestionRequest(WireModel):
    TS_NAME = "ForecastQuestionRequest"

    id: str | None = None


class ForecastQuestionPacketResponse(WireModel):
    TS_NAME = "ForecastQuestionPacketResponse"

    packet: ForecastQuestionPacket | None = wire_optional()
    related: ForecastRelated | None = wire_optional(nullable=True)
    relevant_lessons: list[ForecastDashboardLesson] | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.question.readiness
# ══════════════════════════════════════════════════════════════════════════════


class ForecastQuestionReadinessRequest(WireModel):
    TS_NAME = "ForecastQuestionReadinessRequest"

    question_id: str | None = None


class ForecastQuestionReadinessResponse(WireModel):
    TS_NAME = "ForecastQuestionReadinessResponse"

    question_id: str | None = wire_optional()
    title: str | None = wire_optional()
    score: float
    src_count: int | None = wire_optional()
    gaps: list[ForecastReadinessGap]


# ══════════════════════════════════════════════════════════════════════════════
# forecast.config / forecast.config.set  (resolve_question_config)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastConfigGate(WireModel):
    TS_NAME = "ForecastConfigGate"

    category: str | None = wire_optional()
    default: str | None = wire_optional()
    doc: str | None = wire_optional()
    id: str
    label: str
    looser: bool | None = wire_optional()
    severity: str
    source: str


class ForecastConfigThreshold(WireModel):
    TS_NAME = "ForecastConfigThreshold"

    default: float
    direction: str | None = wire_optional()
    help: str | None = wire_optional()
    integer: bool | None = wire_optional()
    key: str
    label: str
    looser: bool | None = wire_optional()
    maximum: float
    minimum: float
    rule_ids: list[str] | None = wire_optional()
    source: str
    value: float


class ForecastConfigDecision(WireModel):
    TS_NAME = "ForecastConfigDecision"

    action_threshold: str | None = wire_optional(nullable=True)
    decision_deadline: str | None = wire_optional(nullable=True)
    decision_owner: str | None = wire_optional(nullable=True)
    update_triggers: list[Any] | None = wire_optional()


class ForecastConfigRequest(WireModel):
    TS_NAME = "ForecastConfigRequest"

    id: str | None = None
    question_id: str | None = None


class ForecastConfigSetRequest(WireModel):
    TS_NAME = "ForecastConfigSetRequest"

    id: str | None = None
    question_id: str | None = None
    review_cadence: str | None = None
    decision: dict[str, Any] | None = None
    hooks: dict[str, Any] | None = None


class ForecastConfigResponse(WireModel):
    TS_NAME = "ForecastConfigResponse"

    cadence: str | None = wire_optional(nullable=True)
    decision: ForecastConfigDecision | None = wire_optional()
    gates: list[ForecastConfigGate] | None = wire_optional()
    impact: str | None = wire_optional(nullable=True)
    next_run_at: str | None = wire_optional(nullable=True)
    profile: str | None = wire_optional()
    question_id: str | None = wire_optional()
    thresholds: list[ForecastConfigThreshold] | None = wire_optional()
    title: str | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.reviews.next
# ══════════════════════════════════════════════════════════════════════════════


class ForecastReviewsNightly(WireModel):
    TS_NAME = "ForecastReviewsNightly"

    installed: bool | None = wire_optional()
    last_run_at: str | None = wire_optional(nullable=True)
    next_run_at: str | None = wire_optional(nullable=True)


class ForecastReviewsSweeper(WireModel):
    TS_NAME = "ForecastReviewsSweeper"

    enabled: bool | None = wire_optional()
    interval_minutes: int | None = wire_optional()
    next_tick_at: str | None = wire_optional(nullable=True)
    running: bool | None = wire_optional()


class ForecastReviewsNextRequest(WireModel):
    TS_NAME = "ForecastReviewsNextRequest"


class ForecastReviewsNextResponse(WireModel):
    TS_NAME = "ForecastReviewsNextResponse"

    due_count: int | None = wire_optional()
    next_due_at: str | None = wire_optional(nullable=True)
    nightly: ForecastReviewsNightly | None = wire_optional()
    sweeper: ForecastReviewsSweeper | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.command / forecast.reforecast (singular)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastCommandRequest(WireModel):
    TS_NAME = "ForecastCommandRequest"

    arg: str | None = None
    argv: list[str] | None = None


class ForecastCommandResponse(WireModel):
    TS_NAME = "ForecastCommandResponse"

    code: int | None = wire_optional()
    output: str | None = wire_optional()


class ForecastReforecastRequest(WireModel):
    TS_NAME = "ForecastReforecastRequest"

    id: str | None = None


class ForecastReforecastMarkResponse(WireModel):
    """``forecast.reforecast`` (singular) → ``mark_question_review_due`` re-arm ack."""

    TS_NAME = "ForecastReforecastMarkResponse"

    next_run_at: str | None = wire_optional()
    queued: bool | None = wire_optional()
    scheduled: str | None = wire_optional()


# ── forecast.reforecast.start / .status / forecast.desk.task (Arc-B aliases) ───
# jobs_rpc.py owns these handlers over the detached-job runtime; the responses are
# stable shapes, modelled + registered here so the desk references generated types.


class ForecastReforecastStartRequest(WireModel):
    TS_NAME = "ForecastReforecastStartRequest"

    question_ids: list[str] | None = None
    session_id: str | None = None


class ForecastReforecastStartResponse(WireModel):
    TS_NAME = "ForecastReforecastStartResponse"

    run_id: str
    total: int
    note: str | None = wire_optional()


class ForecastReforecastResultRow(WireModel):
    TS_NAME = "ForecastReforecastResultRow"

    question_id: str
    title: str | None = wire_optional()
    committed: bool | None = wire_optional()
    forecast_id: str | None = wire_optional(nullable=True)
    saturation: float | None = wire_optional(nullable=True)
    quorum_autorun: bool | None = wire_optional(nullable=True)
    error: str | None = wire_optional(nullable=True)


class ForecastReforecastCurrent(WireModel):
    TS_NAME = "ForecastReforecastCurrent"

    question_id: str | None = wire_optional()
    title: str | None = wire_optional()
    stage: str | None = wire_optional()


class ForecastReforecastStatusRequest(WireModel):
    TS_NAME = "ForecastReforecastStatusRequest"

    run_id: str | None = None


class ForecastReforecastStatusResponse(WireModel):
    TS_NAME = "ForecastReforecastStatusResponse"

    run_id: str | None = wire_optional()
    status: str
    total: int | None = wire_optional()
    done_count: int | None = wire_optional()
    current: ForecastReforecastCurrent | None = wire_optional(nullable=True)
    results: list[ForecastReforecastResultRow] | None = wire_optional()
    error: str | None = wire_optional(nullable=True)
    quorums_started: int | None = wire_optional()
    progress: list[str] | None = wire_optional()
    task_summary: str | None = wire_optional()


class ForecastReforecastActiveRequest(WireModel):
    TS_NAME = "ForecastReforecastActiveRequest"

    limit: int | None = None


class ForecastReforecastActiveJob(WireModel):
    TS_NAME = "ForecastReforecastActiveJob"

    run_id: str | None = wire_optional()
    mode: str | None = wire_optional()
    status: str | None = wire_optional()
    question_ids: list[str] | None = wire_optional()
    done_count: int | None = wire_optional()
    total: int | None = wire_optional()
    created_at: str | None = wire_optional(nullable=True)


class ForecastReforecastActiveResponse(WireModel):
    TS_NAME = "ForecastReforecastActiveResponse"

    jobs: list[ForecastReforecastActiveJob] | None = wire_optional()
    error: str | None = wire_optional()


class ForecastDeskTaskRequest(WireModel):
    TS_NAME = "ForecastDeskTaskRequest"

    instruction: str | None = None
    question_ids: list[str] | None = None
    session_id: str | None = None


# ══════════════════════════════════════════════════════════════════════════════
# forecast.onboard_propose / forecast.onboard_commit  (no mirror — loose/tolerant)
# ══════════════════════════════════════════════════════════════════════════════


class ForecastOnboardProposeRequest(WireModel):
    TS_NAME = "ForecastOnboardProposeRequest"

    spec: dict[str, Any] | None = None
    prompt: str | None = None


class ForecastOnboardProposeResponse(WireModel):
    TS_NAME = "ForecastOnboardProposeResponse"

    spec: dict[str, Any] | None = wire_optional()
    issues: list[dict[str, Any]] | None = wire_optional()
    errors: list[dict[str, Any]] | None = wire_optional()
    readiness_gaps: list[dict[str, Any]] | None = wire_optional()
    recommended_clarifications: list[dict[str, Any]] | None = wire_optional()
    committable: bool | None = wire_optional()


class ForecastOnboardCommitRequest(WireModel):
    TS_NAME = "ForecastOnboardCommitRequest"

    spec: dict[str, Any] | None = None


class ForecastOnboardCommitResponse(WireModel):
    TS_NAME = "ForecastOnboardCommitResponse"

    committed: bool | None = wire_optional()
    issues: list[dict[str, Any]] | None = wire_optional()
    question_id: str | None = wire_optional()


# ══════════════════════════════════════════════════════════════════════════════
# forecast.hooks / .set / .save_rule / .remove_rule / .preview  (loose/tolerant)
# ══════════════════════════════════════════════════════════════════════════════
# The Hooks view types these responses inline (no gatewayTypes mirror); the models
# below exist for validation + a generated type, kept intentionally tolerant.


class ForecastHooksRequest(WireModel):
    TS_NAME = "ForecastHooksRequest"

    question_id: str | None = None


class ForecastHooksResponse(WireModel):
    TS_NAME = "ForecastHooksResponse"

    enabled: bool | None = wire_optional()
    profile: str | None = wire_optional()
    resolved: dict[str, Any] | None = wire_optional()
    overrides: dict[str, Any] | None = wire_optional()
    rules: list[dict[str, Any]] | None = wire_optional()
    glossary: list[dict[str, Any]] | None = wire_optional()
    operators: list[str] | None = wire_optional()
    profiles: list[str] | None = wire_optional()
    reasoning_methods: list[dict[str, Any]] | None = wire_optional()
    user_rules: list[dict[str, Any]] | None = wire_optional()


class ForecastHooksSetRequest(WireModel):
    TS_NAME = "ForecastHooksSetRequest"

    target: str | None = None
    value: Any | None = None
    rule_id: str | None = None


class ForecastHooksSetResponse(WireModel):
    TS_NAME = "ForecastHooksSetResponse"

    enabled: bool | None = wire_optional()
    profile: str | None = wire_optional()


class ForecastHooksSaveRuleRequest(WireModel):
    TS_NAME = "ForecastHooksSaveRuleRequest"

    rule: dict[str, Any] | None = None
    edit_id: str | None = None


class ForecastHooksSaveRuleResponse(WireModel):
    TS_NAME = "ForecastHooksSaveRuleResponse"

    ok: bool | None = wire_optional()
    error: str | None = wire_optional()
    issues: list[dict[str, Any]] | None = wire_optional()


class ForecastHooksRemoveRuleRequest(WireModel):
    TS_NAME = "ForecastHooksRemoveRuleRequest"

    id: str | None = None


class ForecastHooksRemoveRuleResponse(WireModel):
    TS_NAME = "ForecastHooksRemoveRuleResponse"

    ok: bool | None = wire_optional()


class ForecastHooksPreviewRequest(WireModel):
    TS_NAME = "ForecastHooksPreviewRequest"

    rule: dict[str, Any] | None = None
    max_scan: int | None = None


class ForecastHooksPreviewResponse(WireModel):
    TS_NAME = "ForecastHooksPreviewResponse"

    valid: bool | None = wire_optional()
    applies: int | None = wire_optional()
    would_block: int | None = wire_optional()
    failing: list[str] | None = wire_optional()
    issues: list[dict[str, Any]] | None = wire_optional()
    capped_at: int | None = wire_optional()


__all__ = [name for name in dir() if name.startswith("Forecast")]
