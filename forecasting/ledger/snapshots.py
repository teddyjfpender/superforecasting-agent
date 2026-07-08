"""Snapshot domain — the commit path + snapshot read/serialize (Arc D, slice D4).

Carved from :mod:`forecasting.ledger.core` behind the unchanged ``ForecastLedger``
façade. ``create_snapshot`` (the ~870-line gated commit body: every gate, the
saturation/observe scoring, the preview plumbing) plus its commit-exclusive
helpers, the snapshot readers (``get_snapshot`` / ``get_current_snapshot`` /
``list_snapshots`` / ``snapshots_by_question``), ``annotate_snapshot``, and the
row/dict serializers all live here as module functions taking the ledger
instance first; ``core`` keeps a one-line delegate per method so every caller is
byte-for-byte unchanged.

Following the D1 leaf discipline this module imports ``core`` only as a module
handle (``_core``) and touches ``_core.<attr>`` at CALL time — safe against the
partial-init that ``core``'s bottom-of-file ``import snapshots`` creates. The
write gate comes from the ``gate`` leaf (D-gate slice); everything else is
``forecasting.models`` / stdlib.

Deliberately LEFT in core (reached via the ledger instance at call time): the
shared low-level deps (``_connect``, ``_validate_probability_payload``,
``get_question``…) and three commit-exclusive helpers that belong to FUTURE
domains — ``_cascade_reaggregate_parents`` (thesis re-aggregation, D8),
``_audit_unapplied_lessons`` / ``_record_lesson_applications`` (calibration
lessons, D9), and ``calibration_bias`` (D9). ``create_snapshot`` fires them via
``ledger.<name>`` — the same leaf->delegate->core hop D1/D2/D3 established — so
each future slice inherits them cleanly.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from typing import Any

from forecasting.models import (
    FORECAST_ORIGINS,
    ForecastSnapshot,
    LedgerNotFoundError,
    OutcomeSpace,
    ValidationError,
    json_dumps,
    json_loads,
    parse_timestamp,
    question_decision_readiness_issues,
    timestamp_to_datetime,
    utc_now_iso,
)

from forecasting import appconfig
from forecasting.ledger import core as _core
from forecasting.ledger.gate import _enforce_write_gate, allow_ledger_writes

logger = logging.getLogger(__name__)


def _normalize_reason_list(raw: Any, *, field: str) -> list[str]:
    """Coerce a reasons_up / reasons_down / change_my_mind payload to ``list[str]``.

    ``None`` is treated as empty. Strings are split on newlines when they
    contain them, allowing the CLI to pass either repeated ``--reason-up`` flags
    or a single multi-line block. Whitespace-only entries are dropped.
    """

    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[str] = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValidationError(f"{field} must be a string or list of strings")
    cleaned: list[str] = []
    for entry in items:
        if entry is None:
            continue
        if not isinstance(entry, str):
            raise ValidationError(f"{field} entries must be strings")
        stripped = entry.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def _row_to_snapshot(ledger, row: sqlite3.Row) -> ForecastSnapshot:
    row_keys = row.keys()
    return ForecastSnapshot(
        forecast_id=row["forecast_id"],
        question_id=row["question_id"],
        created_at=row["created_at"],
        as_of=row["as_of"],
        probability_or_distribution=json_loads(row["probability_or_distribution"], None),
        confidence=row["confidence"],
        forecast_horizon_days=row["forecast_horizon_days"],
        method=row["method"],
        ensemble_components=json_loads(row["ensemble_components"], {}),
        rationale=row["rationale"],
        key_assumptions=json_loads(row["key_assumptions"], []),
        assumption_refs=json_loads(row["assumption_refs"], []),
        reference_class_refs=json_loads(row["reference_class_refs"], []),
        evidence_refs=json_loads(row["evidence_refs"], []),
        model_run_refs=json_loads(row["model_run_refs"], []),
        parent_forecast_id=row["parent_forecast_id"],
        forecast_origin=row["forecast_origin"],
        agent_model=row["agent_model"],
        prompt_version=row["prompt_version"],
        forecasting_protocol_version=row["forecasting_protocol_version"],
        toolset_version=row["toolset_version"],
        source_snapshot_refs=json_loads(row["source_snapshot_refs"], []),
        evidence_cutoff=row["evidence_cutoff"],
        backtest_run_id=row["backtest_run_id"],
        calibration_eligible=bool(row["calibration_eligible"]),
        calibration_weight=row["calibration_weight"],
        calibration_lesson_refs=json_loads(row["calibration_lesson_refs"], []),
        calibration_adjustment=json_loads(row["calibration_adjustment"], {}),
        metadata=json_loads(row["metadata"], {}),
        reasons_up=json_loads(row["reasons_up"], []) if "reasons_up" in row_keys else [],
        reasons_down=json_loads(row["reasons_down"], []) if "reasons_down" in row_keys else [],
        change_my_mind=(
            json_loads(row["change_my_mind"], []) if "change_my_mind" in row_keys else []
        ),
    )


def _snapshot_to_dict(ledger, snapshot: ForecastSnapshot) -> dict[str, Any]:
    return snapshot.__dict__.copy()


def get_snapshot(ledger, forecast_id: str) -> ForecastSnapshot:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM forecast_snapshots WHERE forecast_id = ?",
            (forecast_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"forecast snapshot not found: {forecast_id}")
    return ledger._row_to_snapshot(row)


def get_current_snapshot(ledger, question_id: str) -> ForecastSnapshot | None:
    question = ledger.get_question(question_id)
    if not question.current_forecast_id:
        return None
    return ledger.get_snapshot(question.current_forecast_id)


def list_snapshots(ledger, question_id: str) -> list[ForecastSnapshot]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM forecast_snapshots WHERE question_id = ? ORDER BY created_at ASC",
            (question_id,),
        ).fetchall()
    return [ledger._row_to_snapshot(row) for row in rows]


def snapshots_by_question(ledger, question_ids: list[str]) -> dict[str, list[ForecastSnapshot]]:
    """question_id -> snapshots oldest-first (mirrors list_snapshots ordering,
    so current=snapshots[-1] / previous=snapshots[-2] still hold)."""
    out: dict[str, list[ForecastSnapshot]] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM forecast_snapshots WHERE question_id IN ({placeholders}) "
                "ORDER BY question_id ASC, created_at ASC",
                chunk,
            ).fetchall()
        for row in rows:
            out.setdefault(row["question_id"], []).append(ledger._row_to_snapshot(row))
    return out


def annotate_snapshot(ledger, snapshot_id: str, patch: dict[str, Any]) -> None:
    """Merge a small PROVENANCE patch into a snapshot's metadata.

    For decisions made immediately AFTER the commit (e.g. the auto-quorum
    started/skipped record) so audits read the full story from the record
    itself. UPDATE-only — never changes the probability, rationale, or any
    gated field; the method is the blessed writer (validation + scope)."""
    if not patch:
        return
    with allow_ledger_writes("annotate_snapshot"), ledger._connect() as conn:
        row = conn.execute(
            "SELECT metadata FROM forecast_snapshots WHERE forecast_id = ?", (snapshot_id,)
        ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"snapshot not found: {snapshot_id}")
        try:
            current = json.loads(row["metadata"]) if row["metadata"] else {}
        except (TypeError, json.JSONDecodeError):
            current = {}
        current.update(patch)
        conn.execute(
            "UPDATE forecast_snapshots SET metadata = ? WHERE forecast_id = ?",
            (json.dumps(current), snapshot_id),
        )


def _committed_winner_prob(payload: Any, outcome_type: str | None = None) -> float | None:
    """The committed winner probability — defined ONLY for binary (the p) and
    categorical (the leading outcome's mass). For a distribution payload the
    quantiles/mean are NOT probabilities, so this returns None (a vote-share
    model must never be mistaken for a 0.62 'winner probability')."""
    if outcome_type == "binary":
        if isinstance(payload, (int, float)) and not isinstance(payload, bool):
            return float(payload)
        return None
    if outcome_type == "categorical" and isinstance(payload, dict):
        values = [v for v in payload.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
        return max(values) if values else None
    if outcome_type is None and isinstance(payload, (int, float)) and not isinstance(payload, bool):
        return float(payload)  # back-compat: a bare scalar is binary-like
    return None


def _machine_scoreable_payload(payload: Any, outcome_space: OutcomeSpace) -> bool:
    """A candidate-share (vote-share) forecast is born machine-scoreable when it
    carries numeric shares keyed to the question's candidates (the vector scorer
    can then grade it, not the operator by hand). Non-share questions always True."""
    if getattr(outcome_space, "type", None) != "distribution" or not getattr(outcome_space, "choices", None):
        return True
    if not isinstance(payload, dict):
        return False
    choices = {str(c).strip().lower() for c in outcome_space.choices}
    numeric_keys = {
        str(key).strip().lower()
        for key, value in payload.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return bool(choices & numeric_keys)


def _derived_child_present(ledger, question_id: str) -> bool:
    """Whether a derived component child (e.g. a vote-share model linked
    ``component_of`` this question) is present, is a distribution, and has a
    current snapshot — i.e. real downstream modeling actually backs this call.
    (Qualified existence; semantic consistency of the child stays advisory.)"""
    try:
        links = ledger.list_forecast_links(question_id, link_type="component_of", direction="incoming")
    except Exception:
        return False
    for link in links:
        child_id = link.get("from_question_id")
        if not child_id:
            continue
        try:
            child = ledger.get_question(child_id)
            if getattr(child.outcome_space, "type", None) != "distribution":
                continue
            if ledger.get_current_snapshot(child_id) is not None:
                return True
        except Exception:
            continue
    return False


def _forecast_horizon_days(ledger, close_time: str | None, as_of: str) -> float | None:
    close_dt = timestamp_to_datetime(close_time)
    as_of_dt = timestamp_to_datetime(as_of)
    if not close_dt or not as_of_dt:
        return None
    return max((close_dt - as_of_dt).total_seconds() / 86400.0, 0.0)


def _validate_evidence_refs(
    ledger,
    question_id: str,
    evidence_refs: list[str],
    evidence_cutoff: str | None,
) -> None:
    if not evidence_refs:
        return
    cutoff_dt = timestamp_to_datetime(evidence_cutoff)
    for evidence_id in evidence_refs:
        evidence = ledger.get_evidence(evidence_id)
        if evidence.question_id != question_id:
            raise ValidationError(f"evidence {evidence_id} does not belong to question {question_id}")
        if cutoff_dt is None:
            continue
        available_dt = timestamp_to_datetime(evidence.available_at)
        if available_dt and available_dt > cutoff_dt:
            raise ValidationError(
                f"evidence {evidence_id} was available after the evidence cutoff"
            )


def create_snapshot(
    ledger,
    *,
    question_id: str,
    probability_or_distribution: Any,
    rationale: str,
    as_of: str | None = None,
    confidence: float | None = None,
    method: str | None = None,
    ensemble_components: dict[str, Any] | None = None,
    key_assumptions: list[str] | None = None,
    assumption_refs: list[str] | None = None,
    reference_class_refs: list[str] | None = None,
    evidence_refs: list[str] | None = None,
    model_run_refs: list[str] | None = None,
    forecast_origin: str = "live",
    agent_model: str | None = None,
    prompt_version: str | None = None,
    forecasting_protocol_version: str | None = None,
    toolset_version: str | None = None,
    source_snapshot_refs: list[str] | None = None,
    evidence_cutoff: str | None = None,
    backtest_run_id: str | None = None,
    calibration_eligible: bool = True,
    calibration_weight: float = 1.0,
    calibration_lesson_refs: list[str] | None = None,
    calibration_adjustment: dict[str, Any] | None = None,
    stale_evidence_days: int | None = None,
    acknowledge_stale_evidence: bool = False,
    stale_evidence_reason: str | None = None,
    require_citations: bool = False,
    metadata: dict[str, Any] | None = None,
    set_current: bool = True,
    reasons_up: list[str] | None = None,
    reasons_down: list[str] | None = None,
    change_my_mind: list[str] | None = None,
    require_decision_readiness: bool = False,
    require_structured_reasoning: bool = False,
    require_components: bool = False,
    require_fresh_evidence: bool = False,
    require_panel: bool = False,
    panel_run_ref: str | None = None,
    panel_skipped_reason: str | None = None,
    outcome_paths: dict[str, Any] | None = None,
    require_outcome_paths: bool = False,
    style_autofix: bool = False,
    require_style: bool = True,
    reasoning_methods: list[str] | None = None,
    require_output_structure: bool = True,
    distribution_autofix: bool = False,
    enforce_resolved_hooks: bool = False,
    preview: bool = False,
) -> "ForecastSnapshot | dict[str, Any]":
    # PREVIEW (preview=True): run every gate + saturation/observe scoring
    # IDENTICALLY up to the first ledger WRITE, then return a preview record
    # instead of inserting — the caller SEES the saturation score, advisories,
    # and blockers WITHOUT committing, so it fixes them and commits ONCE (this
    # kills the commit-then-remediate churn the Senate-batch audit surfaced). A
    # gate that would REFUSE the commit surfaces as {would_commit: False,
    # blockers:[...]} rather than raising. The write gate is skipped (preview
    # writes nothing; the connection-level authorizer is the backstop for any
    # accidental INSERT). All pre-insert work here is read-only/in-memory and
    # all post-insert machinery is naturally skipped by returning before it.
    if not preview:
        _enforce_write_gate("create_snapshot")
    try:
        question = ledger.get_question(question_id)
        # Forecast hooks: saturation/style gates raise SaturationBlocked (a
        # ValidationError subclass with a byte-identical message) so the report —
        # the failing rule + its remediation — propagates to the interactive tool
        # and the programmatic escalator. Non-saturation ValidationErrors stay plain.
        from forecasting.hooks import SaturationBlocked, single_block
        from forecasting.hooks.spec import Category as _HookCategory

        if forecast_origin not in FORECAST_ORIGINS:
            raise ValidationError(f"forecast_origin must be one of {', '.join(sorted(FORECAST_ORIGINS))}")
        # Exploratory forecasts are scratchpad thinking — never scored, and
        # exempt from the commit-time formalities below (the gates all key on
        # forecast_origin == "live"). Commit a live forecast to put it on the
        # record.
        if forecast_origin == "exploratory":
            calibration_eligible = False
        payload = ledger._validate_probability_payload(probability_or_distribution, question.outcome_space)
        if not rationale.strip():
            raise ValidationError("forecast rationale is required")
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("confidence must be between 0 and 1")
        if calibration_weight < 0:
            raise ValidationError("calibration_weight must be non-negative")
        reasons_up_list = _normalize_reason_list(reasons_up, field="reasons_up")
        reasons_down_list = _normalize_reason_list(reasons_down, field="reasons_down")
        change_my_mind_list = _normalize_reason_list(change_my_mind, field="change_my_mind")
        if require_structured_reasoning and forecast_origin == "live":
            missing_reasoning = []
            if not reasons_up_list:
                missing_reasoning.append("reasons_up")
            if not reasons_down_list:
                missing_reasoning.append("reasons_down")
            if not change_my_mind_list:
                missing_reasoning.append("change_my_mind")
            if missing_reasoning:
                raise single_block(
                    "require_structured_reasoning",
                    "live forecast requires structured reasoning fields: "
                    + ", ".join(missing_reasoning)
                    + ". Provide reasons_up/reasons_down/change_my_mind, rerun with "
                    "require_structured_reasoning=false, or record it as "
                    "forecast_origin='exploratory'.",
                    action="decompose",
                )
        if require_components and forecast_origin == "live":
            # A serious live forecast must show its work: the pooled drivers
            # (base rate, mechanism, market/crowd, case-specific factors) in the
            # structured ensemble_components field, not a bare number. This is
            # the gate that stops snapshots collapsing into an under-specified
            # point estimate.
            component_rows = ensemble_components
            if isinstance(component_rows, dict):
                component_rows = component_rows.get("components", component_rows)
            has_components = bool(component_rows) and (
                len(component_rows) > 0 if isinstance(component_rows, (list, dict)) else False
            )
            if not has_components:
                raise single_block(
                    "require_components",
                    "live forecast requires ensemble_components: decompose the estimate "
                    "into pooled drivers (base rate, mechanism, market/crowd, case-specific "
                    "factors), each with a stable source slug. Provide ensemble_components, "
                    "rerun with require_components=false, or record it as "
                    "forecast_origin='exploratory'.",
                    action="decompose",
                )

        # Re-run discipline: a re-run is not a retrieval. When asked (the agent's
        # update path sets this by default), refuse to commit a new live snapshot
        # if a prior forecast exists and NO fresh evidence was collected since it
        # — stopping the agent from re-estimating off stale ledger evidence and
        # perpetuating a hedge. "Fresh" is measured tie-proof by the evidence
        # count recorded on the prior snapshot (timestamp fallback for snapshots
        # predating this field). The deterministic `forecast refresh` path imports
        # fresh readings first and does not set this; a genuine no-change re-run
        # can acknowledge_stale_evidence or record forecast_origin='exploratory'.
        evidence_count_at_commit: int | None = None
        if forecast_origin == "live":
            # Always count live evidence so the evidence-floor gate (require_evidence)
            # sees the true count; the fresh-evidence RE-RUN check layers on top of it
            # and only applies when require_fresh_evidence is set.
            evidence_now = ledger.list_evidence(question_id)
            evidence_count_at_commit = len(evidence_now)
            if require_fresh_evidence and not acknowledge_stale_evidence:
                prior = ledger.get_current_snapshot(question_id)
                if prior is not None:
                    prior_count = (prior.metadata or {}).get("evidence_count_at_commit")
                    if isinstance(prior_count, int):
                        has_fresh = evidence_count_at_commit > prior_count
                    else:
                        prior_ts = prior.created_at or prior.as_of or ""
                        has_fresh = any((item.captured_at or "") > prior_ts for item in evidence_now)
                    if not has_fresh:
                        raise single_block(
                            "require_fresh_evidence",
                            "re-run blocked: no fresh evidence collected since the prior forecast "
                            f"({prior.forecast_id}, as_of {prior.as_of}). Re-running a forecast must "
                            "start from fresh readings — run `forecast refresh <id>` (re-fetches "
                            "watched sources and re-pools) or import_source_evidence for each driver "
                            "to pull the latest data, THEN update. If you have genuinely checked and "
                            "nothing has changed, set acknowledge_stale_evidence=true (CLI "
                            "--ack-stale-evidence), or record it as forecast_origin='exploratory'.",
                            action="collect_evidence",
                        )

        if require_decision_readiness and forecast_origin == "live":
            readiness_issues = question_decision_readiness_issues(question)
            if readiness_issues:
                raise single_block(
                    "require_decision_readiness",
                    "forecast update blocked by missing decision context: "
                    + "; ".join(readiness_issues)
                    + ". Set decision_owner, action_threshold, and update_triggers "
                    "on the question, or rerun without require_decision_readiness.",
                    category=_HookCategory.DECISION,
                )

        now = utc_now_iso()
        as_of_ts = parse_timestamp(as_of, field_name="as_of") or now
        cutoff_ts = parse_timestamp(evidence_cutoff, field_name="evidence_cutoff")
        effective_cutoff = cutoff_ts or as_of_ts
        ledger._validate_evidence_refs(question_id, evidence_refs or [], effective_cutoff)
        snapshot_metadata = dict(metadata or {})
        # Baseline for the next re-run's fresh-evidence gate (tie-proof count).
        if evidence_count_at_commit is not None:
            snapshot_metadata.setdefault("evidence_count_at_commit", evidence_count_at_commit)

        # Panel formality. A deliberative panel — independent multi-perspective
        # estimates aggregated into a spread — is *indicated* for high-impact
        # questions and for the first forecast on any question (see
        # should_run_panel). For a high-impact live forecast we hard-require
        # evidence one ran (a panel run linked via panel_run_ref) OR an explicit
        # recorded reason for skipping it; the cost of a single-model miss is
        # highest there. For a non-high-impact first forecast the panel is only
        # recommended (recorded as a note), so routine and exploratory research
        # stays unencumbered. Exploratory snapshots are exempt entirely.
        # Read the linked panel run at most ONCE per commit; reused below for the
        # terminal-calibration + quorum-participation signals (no N+1).
        _linked_panel: dict[str, Any] | None = None
        if forecast_origin == "live":
            from forecasting.panel import should_run_panel  # local import avoids cycle

            if panel_run_ref:
                _linked_panel = ledger.get_panel_run(panel_run_ref)
                if _linked_panel["question_id"] != question_id:
                    raise ValidationError("panel_run_ref belongs to a different question")
            panel_skip = (panel_skipped_reason or "").strip()
            high_impact = (question.impact or "").strip().lower() == "high"
            has_prior = bool(question.current_forecast_id)
            panel_indicated = should_run_panel(
                impact=question.impact,
                has_prior_snapshot=has_prior,
            )
            # A re-commitment of an existing live forecast is the highest-risk
            # path for silently inheriting the prior's biases, so it binds the
            # panel just like a high-impact forecast — even though should_run_panel
            # treats a non-high-impact re-run as not-indicated (its rationale is the
            # first-forecast baseline). Scoped to callers that opt into require_panel
            # (the agent's update_forecast tool defaults it True); programmatic
            # re-pools pass a panel_skipped_reason and are exempt below.
            panel_required_here = require_panel and (high_impact or has_prior)
            if (panel_indicated or panel_required_here) and not panel_run_ref and not panel_skip:
                if panel_required_here:
                    why = "high-impact" if high_impact else "re-committed (a prior live snapshot exists)"
                    raise single_block(
                        "require_panel",
                        f"{why} live forecast requires a deliberative panel: run a "
                        "panel or quorum and pass panel_run_ref, record why you skipped it "
                        "with panel_skipped_reason, rerun with require_panel=false, or record "
                        "it as forecast_origin='exploratory'.",
                        action="run_panel",
                    )
                # First-forecast panels on lower-impact questions are recommended,
                # not required — leave a note the agent/guidance can surface.
                snapshot_metadata["panel_recommended"] = True
            if panel_skip:
                snapshot_metadata["panel_skipped_reason"] = panel_skip
            # Mirror the panel-skip escape hatch for the freshness one: if a live
            # forecast acknowledges stale evidence, record WHY so the bypass is
            # explained + auditable (the stale_evidence_justified rule WARNs when
            # acknowledged without a reason).
            stale_reason = (stale_evidence_reason or "").strip()
            if stale_reason:
                snapshot_metadata["stale_evidence_reason"] = stale_reason
            if acknowledge_stale_evidence and has_prior:
                # mark the bypass so a later lint/doctor re-read can surface it even
                # when no reason was given (the WARN state)
                snapshot_metadata["acknowledge_stale_evidence"] = True
        if panel_run_ref:
            # PROVENANCE: the panel that underwrote this commit was previously
            # consumed by the gates and DISCARDED — a post-hoc audit could not
            # verify "committed with panel pr_..." from the record itself (the
            # operator's Senate-batch review hit exactly this). Stamp it.
            snapshot_metadata["panel_run_ref"] = panel_run_ref

        if require_citations and forecast_origin == "live":
            citation_refs = [
                *(evidence_refs or []),
                *(model_run_refs or []),
                *(reference_class_refs or []),
                *(source_snapshot_refs or []),
                *(assumption_refs or []),
                *(calibration_lesson_refs or []),
            ]
            if not citation_refs:
                raise single_block(
                    "require_citations",
                    "live forecast requires citations: add evidence/model/reference/source refs, "
                    "rerun with require_citations=false, or record it as forecast_origin='exploratory'",
                    action="collect_evidence",
                )
            snapshot_metadata["citation_policy"] = "required"
        # Probability-mass audit for CATEGORICAL forecasts: route every
        # material outcome through a named mechanism so mass can't be spread
        # across answer-choice labels by default (outcome-space anchoring).
        # Always recorded for auditability; only ENFORCED when the caller opts
        # in via require_outcome_paths on a live forecast.
        # Extend the audit to candidate-share DISTRIBUTIONS (the Clacton shape), not
        # just categoricals — that scope hole is exactly why a named tail on a
        # vote-share board was never audited. A share distribution is audited over
        # its shares NORMALIZED to fractions (the audit's sum check expects ~1.0).
        _tail_share_map = None
        if isinstance(payload, dict) and question.outcome_space.type != "categorical":
            from forecasting.hooks.distribution import candidate_shares as _cshares

            _tail_share_map = _cshares(payload)
        if isinstance(payload, dict) and (question.outcome_space.type == "categorical" or _tail_share_map is not None):
            from forecasting.tail_audit import audit_outcomes, outcome_paths_from_inputs

            _audit_dist = _tail_share_map if _tail_share_map is not None else payload
            audit = audit_outcomes(outcome_paths_from_inputs(_audit_dist, outcome_paths))
            snapshot_metadata["tail_audit"] = audit.to_dict()
            if require_outcome_paths and forecast_origin == "live" and not audit.passes:
                offenders = [v.name for v in audit.verdicts if v.unearned]
                raise single_block(
                    "require_outcome_paths",
                    "live categorical forecast has unearned tail mass "
                    f"({audit.unearned_mass:.1%}) on outcomes with no named path: "
                    f"{', '.join(offenders)}. Name the mechanism for each (pass "
                    "outcome_paths / --outcome-path), compress the mass onto outcomes "
                    "with a live path, rerun with require_outcome_paths=false, or record "
                    "it as forecast_origin='exploratory'.",
                    action="compress_tails",
                )
        if stale_evidence_days is not None and evidence_refs:
            stale_refs = ledger.find_stale_evidence_refs(
                question_id,
                evidence_refs,
                as_of=as_of_ts,
                stale_days=stale_evidence_days,
            )
            if stale_refs and not acknowledge_stale_evidence:
                refs = ", ".join(item.id for item in stale_refs)
                raise ValidationError(
                    f"stale evidence requires acknowledgement before update: {refs}"
                )
            if stale_refs:
                snapshot_metadata["stale_evidence_acknowledgement"] = {
                    "acknowledged_at": now,
                    "stale_evidence_days": stale_evidence_days,
                    "evidence_refs": [item.id for item in stale_refs],
                }
        ledger._validate_question_scoped_refs(question_id, assumption_refs or [], ledger.get_assumption, "assumption")
        ledger._validate_question_scoped_refs(
            question_id,
            reference_class_refs or [],
            ledger.get_reference_class,
            "reference class",
        )
        ledger._validate_question_scoped_refs(question_id, model_run_refs or [], ledger.get_model_run, "model run")
        for lesson_id in calibration_lesson_refs or []:
            lesson = ledger.get_calibration_lesson(lesson_id)
            if lesson["status"] != "active" or lesson.get("invalidated_by_correction_id"):
                raise ValidationError("calibration lesson refs must be active and non-invalidated")

        # Style gate (Phase 2): a live forecast's prose must be house-clean (no
        # em-dashes / formatting). The interactive AGENT path BLOCKS so the agent
        # rewrites to conform (the user's choice). PROGRAMMATIC system paths
        # (refresh / autopilot / aggregates) pass style_autofix=True: they have no
        # agent to rewrite their generated prose, so the hook mechanically cleans
        # it (the "auto-orchestrate remediation" choice) rather than break
        # automation. Exploratory/backtest/imported work is exempt (not "live").
        if forecast_origin == "live":
            from forecasting.hooks import style_clean_for_rationale, style_message

            _style_ok, _style_offenders = style_clean_for_rationale(rationale)
            if not _style_ok:
                if style_autofix:
                    from forecasting.writeup import sanitize_writeup_text

                    rationale = sanitize_writeup_text(rationale)
                elif require_style:
                    raise single_block(
                        "style_clean",
                        style_message(_style_offenders),
                        action="sanitize_style",
                        category=_HookCategory.STYLE,
                        weight=5.0,
                    )
                # else: style downgraded to warn/off via config — leave the prose;
                # the observe-mode report still records the style verdict.

        # Record the agent's declared reasoning methods (normalized to the taxonomy)
        # in metadata, so the reasoning-composition hook + lint can read them.
        if reasoning_methods:
            from forecasting.hooks.reasoning import normalize_methods as _norm_methods

            _rm, _ = _norm_methods(reasoning_methods)
            if _rm:
                snapshot_metadata["reasoning_methods"] = _rm

        # Distribution structure gate (v2): a live distribution/numeric forecast must
        # be RENDERABLE + WELL-FORMED (ordered / nested / in-bounds), so the Desk chart
        # never draws absurd bounds. The agent path BLOCKS (fix the distribution); a
        # programmatic system path AUTO-FIXES (reorder / clamp / nest / derive). Binary
        # and plain categorical payloads are unaffected (assess returns None).
        if forecast_origin == "live":
            from forecasting.hooks.distribution import assess_distribution, autofix_distribution

            _osp = question.outcome_space
            _bounds = getattr(_osp, "bounds", None)
            _da = assess_distribution(probability_or_distribution, outcome_type=_osp.type, bounds=_bounds, units=getattr(_osp, "units", None))
            if _da and (not _da.renderable or not _da.well_formed or not _da.in_range):
                if distribution_autofix:
                    _fixed, _fxs = autofix_distribution(probability_or_distribution, bounds=_bounds)
                    if _fxs:
                        probability_or_distribution = _fixed
                        payload = ledger._validate_probability_payload(_fixed, _osp)
                        snapshot_metadata["distribution_autofixed"] = _fxs
                        # Re-assess: a clamp can still leave a degenerate/edge interval.
                        # Record what the mechanical fix could not resolve (observability)
                        # rather than silently committing a still-malformed band.
                        _da2 = assess_distribution(_fixed, outcome_type=_osp.type, bounds=_bounds, units=getattr(_osp, "units", None))
                        if _da2 and (not _da2.well_formed or not _da2.renderable):
                            snapshot_metadata["distribution_autofix_incomplete"] = list(_da2.issues)
                elif require_output_structure:
                    if not _da.renderable:
                        raise single_block(
                            "output_renderable",
                            "distribution forecast is not renderable: it needs a central tendency "
                            "(median or mean) AND at least one ordered interval (ci90 or quantiles) "
                            "so the Desk chart can draw a band. Provide them, or record "
                            "forecast_origin='exploratory'.",
                            action="fix_distribution", category=_HookCategory.OUTPUT, weight=12.0,
                        )
                    raise single_block(
                        "uncertainty_well_formed",
                        "forecast uncertainty bounds are malformed: " + ("; ".join(_da.issues) or "ordering/nesting/range")
                        + ". Intervals must be ordered (lo<=hi), nested (ci50 inside ci90), finite, "
                        "non-degenerate, and within the question bounds. Fix the distribution, or "
                        "record forecast_origin='exploratory'.",
                        action="fix_distribution", category=_HookCategory.OUTPUT, weight=12.0,
                    )

        # Lesson-application audit (revives the previously-dead lessons_applied
        # signal): count active in-scope NUMERIC lessons the committed forecast did
        # not actually apply (net-movement, not citation-stapling). Fed into BOTH the
        # user-rule context and the observe-mode score below so the gate can finally
        # see a non-zero value. Best-effort.
        try:
            _active_unapplied = ledger._audit_unapplied_lessons(
                question, probability_or_distribution, calibration_adjustment
            )
        except Exception:
            _active_unapplied = 0
        # Structural-lesson signals (NY-12): the committed winner probability + whether
        # a derived vote-share child model backs it. Fed into both contexts so a lesson
        # rule can require ">X% winner -> a vote-share child exists". Best-effort.
        _winner_prob = ledger._committed_winner_prob(probability_or_distribution, question.outcome_space.type)
        try:
            _has_child = ledger._derived_child_present(question_id)
        except Exception:
            _has_child = False
        _scoreable = ledger._machine_scoreable_payload(probability_or_distribution, question.outcome_space)

        # Terminal Platt-calibration signal (AIA P0.1): when this commit LINKS a
        # panel run, did that run pass through aggregate_panel_estimates' terminal
        # calibration stage (which records `applied_alpha` on the persisted spread)?
        # True when no panel is linked (nothing to skip). Best-effort / fail-open.
        _terminal_calibration_present = True
        # Quorum / panel participation signals (v2) derived from the SAME linked
        # panel run, so the quorum rules (participation / judged) evaluate truthfully
        # at commit instead of defaulting (which false-fired quorum_participation and
        # left quorum_judged indeterminate). Fail-open: defaults on any error.
        _quorum_is = False
        _quorum_persp = 0
        _quorum_models = 0
        _quorum_judged = False
        if panel_run_ref:
            try:
                from forecasting.hooks.signals import quorum_signals_from_panel_run as _quorum_signals

                _pr = _linked_panel if _linked_panel is not None else ledger.get_panel_run(panel_run_ref)
                _terminal_calibration_present = "applied_alpha" in (_pr.get("spread_summary") or {})
                _quorum_is, _quorum_persp, _quorum_models, _quorum_judged = _quorum_signals(_pr)
            except Exception:
                _terminal_calibration_present = True

        # Per-question minimum-requirement THRESHOLD overrides (from the settings
        # modal / forecast.config.set). Fed into both the user-rule context and the
        # observe-mode score so a gate's floor is per-forecast, not a global constant.
        try:
            from forecasting.hooks.thresholds import normalize_thresholds as _norm_thr

            _qthresholds = _norm_thr(((question.metadata or {}).get("forecast_hooks") or {}).get("thresholds"))
        except Exception:
            _qthresholds = {}

        # G1/G2 (P1): candidate-share tail base-rate + interval coherence signals,
        # computed ONCE from what this commit already carries (the payload, the
        # outcome_paths anchors, the candidate_share_intervals_pp metadata) and
        # threaded into every commit context so the gate + the observe report agree.
        # A categorical payload is a named PMF for the anchor audit too; a vote-share
        # DISTRIBUTION is the Clacton shape the old is_categorical scoping missed.
        _g1_is_candidate_share = False
        _g1_share_unanchored: tuple[str, ...] = ()
        _g1_share_unanchored_mass = 0.0
        _g2_present = False
        _g2_coherent = True
        _g2_coverage: float | None = None
        _g2_issues: tuple[str, ...] = ()
        if isinstance(payload, dict):
            try:
                from forecasting.hooks.distribution import (
                    assess_candidate_intervals as _assess_ci,
                    candidate_shares as _g1_cshares,
                )
                from forecasting.hooks.thresholds import (
                    DEFAULT_INTERVAL_MEDIAN_TOLERANCE_PP as _G2_TOL,
                    DEFAULT_NAMED_OUTCOME_ANCHOR_SHARE as _G1_THR,
                )
                from forecasting.tail_audit import (
                    audit_named_anchors as _g1_audit,
                    outcome_paths_from_inputs as _g1_rows,
                )

                _g1_shares = _g1_cshares(payload)
                _g1_is_cat = question.outcome_space.type == "categorical"
                # is_candidate_share is the VOTE-SHARE DISTRIBUTION signal (G1 covers
                # categoricals via is_categorical; G2 is vote-share only). A categorical
                # PMF also parses as shares, so gate the flag on non-categorical.
                _g1_is_candidate_share = _g1_shares is not None and not _g1_is_cat
                if _g1_shares is not None or _g1_is_cat:
                    _g1_dist = _g1_shares if _g1_shares is not None else {
                        str(k): float(v) for k, v in payload.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                    }
                    _g1_share_unanchored, _g1_share_unanchored_mass = _g1_audit(
                        _g1_rows(_g1_dist, outcome_paths),
                        threshold=_qthresholds.get("named_outcome_anchor_share", _G1_THR),
                    )
                if _g1_shares is not None:
                    _g2_raw = snapshot_metadata.get("candidate_share_intervals_pp")
                    _g2_present = isinstance(_g2_raw, dict) and bool(_g2_raw)
                    _g2_coherent, _g2_coverage, _g2_issues_list = _assess_ci(
                        payload, _g2_raw, bounds=getattr(question.outcome_space, "bounds", None),
                        tolerance_pp=_qthresholds.get("interval_median_tolerance_pp", _G2_TOL),
                    )
                    _g2_issues = tuple(_g2_issues_list)
            except Exception:
                logger.debug("forecast-hooks G1/G2 signal computation failed (non-fatal)", exc_info=True)

        # VOI-directed research adequacy (research_audit.py): the DETERMINISTIC checks
        # only (NO LLM at commit), computed against the current evidence/reference/
        # watched state + THIS candidate commit's reasons_down + evidence_refs. Feeds
        # the `research_adequate` hook rule (WARN standard / ERROR strict). Fail-open:
        # any read error yields adequate=True so a commit is never falsely blocked.
        _research_adequate = True
        _research_adequacy_score = None
        if forecast_origin == "live":
            try:
                from forecasting.research_audit import audit_research_for_commit

                _ra = audit_research_for_commit(
                    ledger, question,
                    reasons_down=reasons_down_list, evidence_refs=evidence_refs or [],
                    stale_evidence_days=stale_evidence_days,
                )
                _research_adequate = bool(_ra.get("adequate"))
                _research_adequacy_score = _ra.get("score")
            except Exception:
                _research_adequate, _research_adequacy_score = True, None

        # User-defined rule enforcement (Phase 5). Only runs when the desk has
        # authored custom rules (zero overhead otherwise). A buggy rule engine must
        # never brick a commit (fail-OPEN on evaluation errors), but a legitimately
        # failing error-severity user rule DOES block (that is the point).
        if forecast_origin == "live":
            try:
                import dataclasses as _dc

                from forecasting.hooks import build_commit_context, resolve_severities, run_hooks
                from forecasting.hooks.engine import load_hook_config
                from forecasting.hooks.loader import load_user_rules

                _hcfg = load_hook_config()
                _user_rules = load_user_rules(_hcfg)
            except Exception:
                _user_rules = []
                _hcfg = {}
            # Compile active in-scope calibration lessons that carry a `rule` into
            # enforceable lesson:* rules — this is how a STRUCTURAL lesson (not just a
            # numeric bias) bites at commit. Force-stamped scope; broken rules skipped.
            try:
                from forecasting.learning import compile_lesson_rules as _compile_lessons

                _lesson_rules = _compile_lessons(ledger, question)
            except Exception:
                _lesson_rules = []
            if _user_rules or _lesson_rules:
                _ublocked = None
                try:
                    _ucomp = ensemble_components
                    if isinstance(_ucomp, dict):
                        _ucomp = _ucomp.get("components", _ucomp)
                    _ctx = build_commit_context(
                        question_id=question_id, forecast_origin=forecast_origin, event="update",
                        impact=question.impact, has_prior=bool(question.current_forecast_id),
                        is_categorical=(question.outcome_space.type == "categorical"),
                        reasons_up=reasons_up_list, reasons_down=reasons_down_list, change_my_mind=change_my_mind_list,
                        has_components=bool(_ucomp), component_count=(len(_ucomp) if isinstance(_ucomp, (list, dict)) else 0),
                        citation_refs=[*(evidence_refs or []), *(model_run_refs or [])],
                        panel_run_ref=panel_run_ref, panel_skipped_reason=panel_skipped_reason,
                        stale_evidence_reason=stale_evidence_reason,
                        has_fresh_evidence=True, acknowledge_stale_evidence=acknowledge_stale_evidence,
                        evidence_count=len(evidence_refs or []), prior_forecast_id=None, prior_as_of=None,
                        decision_gaps=question_decision_readiness_issues(question),
                        tail_audit_passes=((snapshot_metadata.get("tail_audit") or {}).get("passes")),
                        tail_unearned_mass=float((snapshot_metadata.get("tail_audit") or {}).get("unearned_mass") or 0.0),
                        tail_offenders=[], rationale=rationale,
                        domain=getattr(question, "domain", None), outcome_type=question.outcome_space.type,
                        is_candidate_share=_g1_is_candidate_share,
                        share_named_unanchored=_g1_share_unanchored,
                        share_named_unanchored_mass=_g1_share_unanchored_mass,
                        candidate_intervals_present=_g2_present,
                        candidate_intervals_coherent=_g2_coherent,
                        candidate_interval_coverage=_g2_coverage,
                        candidate_interval_issues=_g2_issues,
                        thresholds=_qthresholds,
                    )
                    # Augment with the signals user rules may test that the candidate
                    # context does not carry (only fetched when user rules exist) —
                    # including the v2 output/uncertainty/confidence/reasoning signals,
                    # so a user rule that references e.g. bounds.well_formed or
                    # reasoning.method_count enforces against real values, not defaults.
                    from forecasting.hooks.distribution import assess_distribution as _u_assess
                    from forecasting.hooks.profiles import resolve_reasoning_requirement as _u_rrr

                    _uosp = question.outcome_space
                    _uda = _u_assess(probability_or_distribution, outcome_type=_uosp.type, bounds=getattr(_uosp, "bounds", None), units=getattr(_uosp, "units", None))
                    try:
                        _ush = ledger._sharpness(probability_or_distribution)
                    except Exception:
                        _ush = None
                    _uprof = ((question.metadata or {}).get("forecast_hooks") or {}).get("profile") or _hcfg.get("profile") or "standard"
                    _urq, _umin = _u_rrr(_uprof)
                    _uuc = False
                    try:
                        _ub = ledger.calibration_bias(domain=getattr(question, "domain", None))
                        _uuc = (_ub.get("status") not in (None, "insufficient_evidence")) and _ub.get("direction") == "under"
                    except Exception:
                        _uuc = False
                    _utd = snapshot_metadata.get("tail_audit") or {}
                    try:
                        from forecasting.readiness_lens import build_question_readiness as _u_bqr

                        _u_readiness = _u_bqr(ledger, question_id).get("score")
                    except Exception:
                        _u_readiness = None
                    _ctx = _dc.replace(
                        _ctx,
                        reference_class_count=len(ledger.list_reference_classes(question_id)),
                        linked_reference_class_count=len(reference_class_refs or []),
                        is_thesis_or_factor=ledger.is_thesis(question),
                        watched_source_count=len(ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")),
                        readiness_score=_u_readiness,
                        panel_run_count=len(ledger.list_panel_runs(question_id)),
                        reasoning_methods=tuple(snapshot_metadata.get("reasoning_methods") or ()),
                        required_reasoning_methods=tuple(_urq), min_reasoning_methods=_umin,
                        is_distribution=bool(_uda and _uda.is_distribution),
                        distribution_renderable=(_uda.renderable if _uda else True),
                        bounds_well_formed=(_uda.well_formed if _uda else True),
                        bounds_in_range=(_uda.in_range if _uda else True),
                        interval_width_ratio=(_uda.width_ratio if _uda else None),
                        sharpness=_ush,
                        is_quorum=_quorum_is,
                        panel_perspective_count=_quorum_persp,
                        quorum_model_count=_quorum_models,
                        quorum_judged=_quorum_judged,
                        calibration_under_confident=_uuc,
                        tail_null_excess=float(((_utd.get("null_model") or {}).get("excess_tail")) or 0.0),
                        active_lessons_unapplied=_active_unapplied,
                        committed_winner_prob=_winner_prob,
                        derived_child_present=_has_child,
                        machine_scoreable=_scoreable,
                        terminal_calibration_present=_terminal_calibration_present,
                        research_adequate=_research_adequate,
                        research_adequacy_score=_research_adequacy_score,
                    )
                    _upolicy = resolve_severities(question, forecast_origin=forecast_origin, hooks_config=_hcfg)
                    _ureport = run_hooks(_ctx, _upolicy, rules=tuple(_user_rules) + tuple(_lesson_rules))
                    if not _ureport.passed:
                        _ublocked = _ureport
                except Exception:
                    logger.debug("forecast-hooks user-rule eval failed (non-fatal, fail-open)", exc_info=True)
                if _ublocked is not None:
                    raise SaturationBlocked(_ublocked)

        # Forecast hooks (Wave 3): the shared commit context is assembled ONCE below
        # and drives two consumers:
        #   (1) a RESOLVED-POLICY blocking pass (Slice H3) for the built-in rules that
        #       have NO inline gate above — evaluated under resolve_severities (profile
        #       + impact/origin scaling + config/per-question overrides, the SAME
        #       resolution the observe call uses). A failing ERROR-severity rule here
        #       raises SaturationBlocked with the rule's canonical builtin message +
        #       remediation. This is what makes require_evidence (ERROR by default) a
        #       real floor for an agent commit, and lets the strict profile /
        #       impact-scaling actually block the non-inline rules instead of only
        #       colouring the observe report.
        #   (2) the OBSERVE-mode recording (Phase 1): compute the FULL saturation score
        #       + per-rule report and record it on the snapshot.
        # The inline gates above stay the byte-identical, first-failing-wins enforcement
        # for the rules they own; the blocking pass NEVER re-evaluates a rule an inline
        # gate already owns (de-duplicated by rule_id), so precedence + messages are
        # preserved.
        #
        # SCOPE (all must hold for the blocking pass to fire):
        #   * forecast_origin == 'live' (exploratory / backtest / imported stay observe-only);
        #   * enforce_resolved_hooks is True — the OPT-IN the AGENT path (the interactive
        #     forecast tool's update_forecast) sets. This mirrors the codebase's existing
        #     require_* opt-in discipline: the ledger stays lenient for direct callers
        #     (operator seeds, migrations, fixtures, internal recompute) so a raw
        #     create_snapshot never retroactively hard-blocks, while the agent commit —
        #     the path this floor is FOR — enforces the resolved policy. Programmatic
        #     system paths (refresh / aggregate / autopilot / pilot-cohort) commit
        #     directly with their style_autofix / distribution_autofix leniency and do
        #     NOT opt in, so they keep observe + autofix (belt-and-braces: the autofix
        #     flags below are also treated as an exemption);
        #   * neither style_autofix nor distribution_autofix is set (programmatic exemption);
        #   * the env kill-switch FORECAST_DISABLE_HOOK_BLOCKING is not set (it disables
        #     the pass entirely; observe still runs).
        # Everything is fully guarded and must NEVER break a commit; the block report is
        # computed inside the fail-open try (run_hooks returns a report, it does not
        # raise) and RAISED afterwards so SaturationBlocked escapes the fail-open.
        #
        # Built-in rule_ids already owned by an inline gate above (excluded from the
        # blocking pass so nothing is evaluated as blocking twice; their precedence +
        # exact messages are unchanged).
        _INLINE_GATE_RULE_IDS = frozenset({
            "require_structured_reasoning", "require_components", "require_fresh_evidence",
            "require_decision_readiness", "require_panel", "require_citations",
            "require_outcome_paths", "style_clean", "output_renderable",
            "uncertainty_well_formed",
        })
        _resolved_block: SaturationReport | None = None
        try:
            from forecasting.hooks import build_commit_context, policy_from_require_flags, run_hooks

            _comp = ensemble_components
            if isinstance(_comp, dict):
                _comp = _comp.get("components", _comp)
            _has_comp = bool(_comp) and (len(_comp) > 0 if isinstance(_comp, (list, dict)) else False)
            _comp_n = len(_comp) if isinstance(_comp, (list, dict)) else 0
            _cite_refs = [
                *(evidence_refs or []), *(model_run_refs or []), *(reference_class_refs or []),
                *(source_snapshot_refs or []), *(assumption_refs or []), *(calibration_lesson_refs or []),
            ]
            _td = snapshot_metadata.get("tail_audit") or {}
            # v2 signals for the observe score
            from forecasting.hooks.distribution import assess_distribution as _assess_dist
            from forecasting.hooks.profiles import resolve_reasoning_requirement as _resolve_rr

            _osp2 = question.outcome_space
            _oda = _assess_dist(probability_or_distribution, outcome_type=_osp2.type, bounds=getattr(_osp2, "bounds", None), units=getattr(_osp2, "units", None))
            try:
                _osharp = ledger._sharpness(probability_or_distribution)
            except Exception:
                _osharp = None
            try:
                _oprof = ((question.metadata or {}).get("forecast_hooks") or {}).get("profile") or "standard"
                _orq, _omin = _resolve_rr(_oprof)
            except Exception:
                _orq, _omin = (), 0
            # RDY machine-readiness enforcement: the new readiness_floor / no_watched_sources
            # builtins read these off the context. Without them the context would carry the
            # defaults (0 / None) and no_watched_sources would false-fire on EVERY live
            # commit — so compute the real values from the ledger available here.
            try:
                _watched_count = len(ledger.list_watched_sources(scope_type="question", scope_ref=question_id, status="active"))
            except Exception:
                _watched_count = 0
            try:
                from forecasting.readiness_lens import build_question_readiness as _bqr

                _readiness_score = _bqr(ledger, question_id).get("score")
            except Exception:
                _readiness_score = None
            _hook_ctx = build_commit_context(
                question_id=question_id, forecast_origin=forecast_origin, event="update",
                impact=question.impact, has_prior=bool(question.current_forecast_id),
                is_categorical=(question.outcome_space.type == "categorical"),
                reasons_up=reasons_up_list, reasons_down=reasons_down_list, change_my_mind=change_my_mind_list,
                has_components=_has_comp, component_count=_comp_n, citation_refs=_cite_refs,
                panel_run_ref=panel_run_ref, panel_skipped_reason=panel_skipped_reason,
                stale_evidence_reason=stale_evidence_reason,
                # Freshness is treated as satisfied for the advisory SCORE: when the
                # fresh-evidence rule is enforced, a stale re-run is blocked by the
                # gate above and never reaches here; when it is not enforced, the
                # score should not penalize freshness. So a recorded saturation
                # score never reflects a freshness failure (the gate owns that).
                has_fresh_evidence=True, acknowledge_stale_evidence=acknowledge_stale_evidence,
                evidence_count=(evidence_count_at_commit or 0),
                prior_forecast_id=None, prior_as_of=None,
                decision_gaps=question_decision_readiness_issues(question),
                tail_audit_passes=(_td.get("passes") if _td else None),
                tail_unearned_mass=float(_td.get("unearned_mass") or 0.0),
                tail_offenders=[v.get("name") for v in (_td.get("verdicts") or []) if v.get("unearned")],
                rationale=rationale,
                domain=getattr(question, "domain", None),
                outcome_type=question.outcome_space.type,
                reasoning_methods=snapshot_metadata.get("reasoning_methods") or [],
                required_reasoning_methods=tuple(_orq), min_reasoning_methods=_omin,
                reference_class_count=len(ledger.list_reference_classes(question_id)),
                linked_reference_class_count=len(reference_class_refs or []),
                is_thesis_or_factor=ledger.is_thesis(question),
                watched_source_count=_watched_count,
                readiness_score=_readiness_score,
                is_distribution=bool(_oda and _oda.is_distribution),
                distribution_renderable=(_oda.renderable if _oda else True),
                bounds_well_formed=(_oda.well_formed if _oda else True),
                bounds_in_range=(_oda.in_range if _oda else True),
                interval_width_ratio=(_oda.width_ratio if _oda else None),
                sharpness=_osharp,
                panel_run_count=len(ledger.list_panel_runs(question_id)),
                is_quorum=_quorum_is,
                panel_perspective_count=_quorum_persp,
                quorum_model_count=_quorum_models,
                quorum_judged=_quorum_judged,
                active_lessons_unapplied=_active_unapplied,
                committed_winner_prob=_winner_prob,
                derived_child_present=_has_child,
                machine_scoreable=_scoreable,
                terminal_calibration_present=_terminal_calibration_present,
                research_adequate=_research_adequate,
                research_adequacy_score=_research_adequacy_score,
                is_candidate_share=_g1_is_candidate_share,
                share_named_unanchored=_g1_share_unanchored,
                share_named_unanchored_mass=_g1_share_unanchored_mass,
                candidate_intervals_present=_g2_present,
                candidate_intervals_coherent=_g2_coherent,
                candidate_interval_coverage=_g2_coverage,
                candidate_interval_issues=_g2_issues,
                thresholds=_qthresholds,
            )
            # (1) RESOLVED-POLICY blocking pass (Slice H3). Only for a live commit that
            # is NOT a programmatic (autofix) path and has not disabled the pass via the
            # kill-switch. Evaluate ONLY the built-in rules with no inline gate, under the
            # resolved (profile + scaling + override) severities, and stage the block to be
            # raised after this fail-open try. run_hooks preserves builtin order, so the
            # first failing ERROR is the same rule the report's blocking_failures()[0] names.
            _block_disabled = appconfig.get_bool("FORECAST_DISABLE_HOOK_BLOCKING")
            if (
                forecast_origin == "live"
                and enforce_resolved_hooks
                and not style_autofix
                and not distribution_autofix
                and not _block_disabled
            ):
                from forecasting.hooks import resolve_severities as _resolve_sev_block
                from forecasting.hooks.builtins import BUILTIN_RULES as _ALL_BUILTIN_RULES

                _resolved_policy = _resolve_sev_block(
                    question, forecast_origin=forecast_origin, hooks_config=_hcfg,
                )
                _noninline_rules = tuple(
                    r for r in _ALL_BUILTIN_RULES if r.id not in _INLINE_GATE_RULE_IDS
                )
                _block_report = run_hooks(_hook_ctx, _resolved_policy, rules=_noninline_rules)
                if _block_report.blocking_failures():
                    _resolved_block = _block_report

            _hook_policy = policy_from_require_flags(
                forecast_origin=forecast_origin,
                require_structured_reasoning=require_structured_reasoning,
                require_components=require_components, require_fresh_evidence=require_fresh_evidence,
                require_decision_readiness=require_decision_readiness, require_panel=require_panel,
                require_citations=require_citations, require_outcome_paths=require_outcome_paths,
            )
            snapshot_metadata["saturation"] = run_hooks(_hook_ctx, _hook_policy).to_dict()
        except Exception:  # observe-mode is best-effort and must NEVER break a commit
            logger.debug("forecast-hooks observe-mode failed (non-fatal)", exc_info=True)
        # RAISE the resolved-policy block OUTSIDE the fail-open try so SaturationBlocked
        # (a ValidationError) is never swallowed by the observe guard above.
        if _resolved_block is not None:
            raise SaturationBlocked(_resolved_block)
    except ValidationError as _preview_err:
        # A gate refused the commit. In preview, surface the blocker cheaply so
        # the caller can fix it before writing, instead of paying a real commit.
        if preview:
            return {"preview": True, "would_commit": False, "blockers": [str(_preview_err)]}
        raise
    if preview:
        # Every gate passed. Return the SAME saturation score + post-adjustment
        # value + assembled metadata a real commit would stamp — but no INSERT.
        return {
            "preview": True,
            "would_commit": True,
            "saturation": snapshot_metadata.get("saturation"),
            "probability_or_distribution": payload,
            "metadata": snapshot_metadata,
        }

    forecast_id = f"fs_{uuid.uuid4().hex[:12]}"
    horizon_days = ledger._forecast_horizon_days(question.close_time, as_of_ts)
    parent_forecast_id = question.current_forecast_id
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO forecast_snapshots (
                forecast_id, question_id, created_at, as_of,
                probability_or_distribution, confidence, forecast_horizon_days,
                method, ensemble_components, rationale, key_assumptions,
                assumption_refs, reference_class_refs, evidence_refs, model_run_refs,
                parent_forecast_id, forecast_origin, agent_model, prompt_version,
                forecasting_protocol_version, toolset_version, source_snapshot_refs,
                evidence_cutoff, backtest_run_id, calibration_eligible,
                calibration_weight, calibration_lesson_refs, calibration_adjustment,
                metadata, reasons_up, reasons_down, change_my_mind
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                forecast_id,
                question_id,
                now,
                as_of_ts,
                json_dumps(payload),
                confidence,
                horizon_days,
                method,
                json_dumps(ensemble_components or {}),
                rationale.strip(),
                json_dumps(key_assumptions or []),
                json_dumps(assumption_refs or []),
                json_dumps(reference_class_refs or []),
                json_dumps(evidence_refs or []),
                json_dumps(model_run_refs or []),
                parent_forecast_id,
                forecast_origin,
                agent_model,
                prompt_version,
                forecasting_protocol_version or _core.FORECASTING_PROTOCOL_VERSION,
                toolset_version,
                json_dumps(source_snapshot_refs or []),
                cutoff_ts,
                backtest_run_id,
                1 if calibration_eligible else 0,
                calibration_weight,
                json_dumps(calibration_lesson_refs or []),
                json_dumps(calibration_adjustment or {}),
                json_dumps(snapshot_metadata),
                json_dumps(reasons_up_list),
                json_dumps(reasons_down_list),
                json_dumps(change_my_mind_list),
            ),
        )
        if set_current:
            conn.execute(
                "UPDATE forecast_questions SET current_forecast_id = ? WHERE id = ?",
                (forecast_id, question_id),
            )
    if panel_run_ref:
        ledger.attach_panel_to_snapshot(panel_run_ref, forecast_id)
    # A member commit re-freshens its parent thesis/factor aggregates so the
    # desk never shows a thesis that "hasn't moved" while its members have.
    # Runs POST-transaction (the `with conn` block above has closed) so the
    # parent re-aggregate's writes never deadlock the just-committed member
    # write; cycle-guarded + fail-open; a no-op (one indexed lookup) when the
    # question has no parents — i.e. on the common forecast commit.
    if set_current and forecast_origin == "live":
        ledger._cascade_reaggregate_parents(question_id, as_of=as_of_ts)
    # Coverage ledger: record which active lessons were in scope at this live
    # commit, so `forecast lessons audit` can show whether each is actually used.
    if forecast_origin == "live":
        ledger._record_lesson_applications(question, forecast_id, probability_or_distribution, calibration_adjustment)
    # Programmatic escalation (Wave 3 H4): a programmatic commit (refresh /
    # aggregate / autopilot — the lenient autofix paths that never hard-block)
    # whose recorded saturation is under the sweep bar escalates the SAME deduped
    # WARN under-saturation alert the scheduled sweep raises, so the leniency
    # stays but the under-saturation becomes VISIBLE + actionable. Live-only,
    # deduped, fail-open; the AGENT path (no autofix — it sees the tool-result
    # advisory instead) and non-live origins are untouched. Disable with
    # FORECAST_DISABLE_SATURATION_ESCALATION.
    if (
        set_current
        and forecast_origin == "live"
        and (style_autofix or distribution_autofix)
        and not appconfig.get_bool("FORECAST_DISABLE_SATURATION_ESCALATION")
    ):
        try:
            ledger.enqueue_saturation_alert(question_id, snapshot_metadata.get("saturation"))
        except Exception:  # visibility is best-effort and must NEVER break a commit
            logger.debug("saturation escalation failed (non-fatal)", exc_info=True)
    return ledger.get_snapshot(forecast_id)
