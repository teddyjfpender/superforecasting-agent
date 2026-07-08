"""Forecast-panel domain (D5 carve — panel runs + track-record weighting).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade: the panel-run lifecycle (``record_panel_run`` — the
third gated forecast-producing write — plus ``get_panel_run`` /
``list_panel_runs`` / ``attach_panel_to_snapshot`` and the batched
``latest_panel_run_by_question`` read), the panel serializers
(``_panel_run_dict`` / ``_panel_estimate_dict``), and the advisory track-record
weighting helpers the quorum opts into: ``component_track_record`` /
``recommended_component_weights`` (ensemble-component + panel-perspective Brier
edge) and ``model_track_record`` / ``recommended_model_weights`` (per-panelist-
model quorum weighting). Each function takes the ``ForecastLedger`` instance
first; ``core`` keeps a one-line delegate per method so no caller changed.

Dependency direction (no cycle, per the D1 finding): this leaf imports only
``forecasting.models`` + stdlib + the ``gate`` leaf at load time. The gated write
``record_panel_run`` reaches ``_enforce_write_gate`` straight from
:mod:`forecasting.ledger.gate` (the gate-leaf payoff — no ``_core.`` hop).
Everything else the moved bodies need is reached through the ``ledger`` INSTANCE
at call time: the shared scoring helper ``_score_forecast_payload``, the shared
``_chunk_ids`` batcher, ``get_question`` / ``get_snapshot`` / ``list_snapshots`` /
``list_model_runs`` / ``get_latest_resolution``, and the shared CLASS constant
``MODEL_WEIGHT_MIN_SAMPLE`` (kept in ``core`` because the NON-panel ``model_skill``
and a core method also read it, and a test reads ``ledger.MODEL_WEIGHT_MIN_SAMPLE``).
``model_skill`` itself is NOT panel domain — it reads ``model_runs`` (the R4
living-models path), so it and ``_MODEL_SKILL_BASELINE_BRIER`` stay in ``core``.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Any

from forecasting.ledger.gate import _enforce_write_gate

logger = logging.getLogger(__name__)
from forecasting.models import (
    LedgerNotFoundError,
    ValidationError,
    json_dumps,
    json_loads,
    utc_now_iso,
)


def record_panel_run(
    ledger,
    *,
    question_id: str,
    estimates: list[dict[str, Any]],
    aggregation_method: str = "trimmed_geomean_odds",
    trim: int = 1,
    snapshot_id: str | None = None,
    triggered_by: str | None = None,
    perspectives: list[str] | None = None,
    judge: Any = None,
    final_probability: float | None = None,
    final_source: str | None = None,
    research_rounds: int = 0,
    supervisor_evidence: list[dict[str, Any]] | None = None,
    delphi_rounds: int = 0,
    delphi_audit: dict[str, Any] | None = None,
    supervisor_search_enabled: bool = False,
    market_anchor: dict[str, Any] | None = None,
    pseudo_diversity_caveat: str | None = None,
    panel_resolution_note: str | None = None,
    blind_pool: float | None = None,
    reconciled_pool: float | None = None,
    pool_shrinkage: dict[str, Any] | None = None,
    specialist_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate a panel of perspective estimates and persist the artifact.

    ``judge`` (a JudgeSynthesis dict: consensus / contradictions / blind_spots /
    judge_model / directional_confidence) is stored so a quorum's judge synthesis
    has a durable home and the quorum-judged gate can see it — instead of being
    dropped on the floor.

    ``final_probability`` / ``final_source`` (AIA P0.3): the ALREADY-resolved
    committed number and the branch that produced it (``'pool'`` or
    ``'judge_high'``). When supplied, the persisted ``aggregate_probability`` is
    this exact number — NOT a freshly re-pooled one — so the in-memory
    :class:`~forecasting.quorum.QuorumResult` and the durable panel_run can never
    diverge (the P0.1 divergence: this method used to silently re-pool the
    estimates WITH the per-question alpha while the QuorumResult showed the bare
    pool). The terminal Platt calibration has therefore already been applied
    upstream exactly once; we must NOT re-apply it here. When ``final_probability``
    is ``None`` (the perspective-panel path), we fall back to pooling-with-alpha as
    before so non-quorum callers are unchanged.

    Returns the panel-run record dict (including aggregate_probability,
    spread_summary, trimmed flags, and per-estimate ids). The caller
    typically passes the resulting ``aggregate_probability`` into
    :meth:`create_snapshot` and the panel run id into the snapshot's
    ``ensemble_components`` or ``metadata``.
    """

    _enforce_write_gate("record_panel_run")

    from forecasting.hooks.thresholds import resolve_alpha_extremize
    from forecasting.panel import aggregate_panel_estimates  # local import to avoid cycle

    question = ledger.get_question(question_id)
    if snapshot_id is not None:
        ledger.get_snapshot(snapshot_id)
    # Terminal Platt calibration (AIA P0.1): resolve the per-question slope
    # from the question's forecast-hooks config (default 1.0 = byte-identical
    # no-op for an un-configured question).
    alpha_extremize = resolve_alpha_extremize(
        question.metadata if isinstance(question.metadata, dict) else None
    )
    # Always aggregate WITH the real per-question slope so the persisted
    # calibration markers (applied_alpha, pre_extremize, terminal_calibration_
    # applied) and pool_probability are accurate on the quorum path too. Platt
    # is still applied EXACTLY ONCE to the committed number: when the caller
    # supplies an already-resolved value (the quorum path — run_quorum has
    # already applied alpha + the P0.3 override), we overwrite the committed
    # scalar with it below and never re-derive it from the aggregation, so the
    # aggregation's calibrated scalar is used only for the audit markers / the
    # pool the override beat — never double-Platt'd.
    resolved = final_probability is not None
    aggregation = aggregate_panel_estimates(
        estimates,
        method=aggregation_method,
        trim=trim,
        alpha_extremize=alpha_extremize,
    )
    committed_probability = (
        float(final_probability)
        if resolved
        else float(aggregation.aggregate_probability)
    )
    # Constrain to the known source domain (defensive against a future caller).
    committed_source = final_source if final_source in {"pool", "judge_high"} else "pool"
    # AIA P1.1 — agentic-supervisor fresh-search loop. Default to the no-loop
    # state so the perspective-panel path and any pre-P1.1 quorum caller
    # persist unchanged (0 rounds, no fresh evidence).
    research_rounds = max(0, int(research_rounds or 0))
    supervisor_evidence = list(supervisor_evidence or [])
    # Delphi v1 — additive audit fields. Default to the no-Delphi state so the
    # delphi_rounds==0 path (and every pre-Delphi caller) persists unchanged.
    delphi_rounds = max(0, int(delphi_rounds or 0))
    delphi_audit = dict(delphi_audit or {})
    now = utc_now_iso()
    run_id = f"pr_{uuid.uuid4().hex[:12]}"
    requested = perspectives if perspectives is not None else [
        row["perspective"] for row in aggregation.estimates
    ]
    # Fold the P0.3 override outcome into the persisted spread so it is
    # observable alongside the P0.1 calibration markers without a second
    # schema migration. ``final_source`` is also a first-class column.
    spread = dict(aggregation.spread)
    spread["final_source"] = committed_source
    if resolved:
        # The committed number is the resolved one; surface the CALIBRATED pool
        # (the value a high-confidence judge actually overrode) for audit.
        spread["pool_probability"] = round(
            float(aggregation.aggregate_probability), 6
        )
    # ARTIFACT STAMPING: the columns store research_rounds/delphi_rounds/supervisor
    # evidence, but the human-facing spread_summary (and notes) lost them — stamp
    # them here so a quorum's process provenance travels with the artifact the desk
    # reads, not just the raw columns. Additive keys; a perspective panel with no
    # quorum machinery stamps the no-op defaults.
    spread["research_rounds"] = research_rounds
    spread["delphi_rounds"] = delphi_rounds
    spread["supervisor_search"] = bool(supervisor_search_enabled) or research_rounds > 0
    if market_anchor:
        spread["market_anchor"] = dict(market_anchor)
    # Blind-then-reconcile pools (UPGRADE 1): stamp the market-INDEPENDENT blind
    # pool alongside the reconciled pool + market price so blind-vs-market
    # divergence (the orthogonality signal) travels with the artifact the desk
    # reads. Only present on a market question; None ⇒ omitted (byte-compatible).
    if blind_pool is not None:
        spread["blind_pool"] = round(float(blind_pool), 6)
    if reconciled_pool is not None:
        spread["reconciled_pool"] = round(float(reconciled_pool), 6)
    # BLF gate-wiring RETROACTIVITY MARKER — stamp the panel process version on EVERY
    # run recorded from now on. A run without it predates the BLF gates, so the BLF
    # rules (belief_trajectory_present / pool_shrinkage_recorded / specialist_seat_
    # considered) never bind it. This is the whole guard; do not gate it on a caller flag.
    from forecasting.hooks.blf_signals import PANEL_PROCESS_VERSION

    spread["process_version"] = PANEL_PROCESS_VERSION
    # BLF A3 — variance-adaptive pool-shrinkage provenance (α + inputs), so the shrink
    # toward the outside-view anchor is reconstructable + validatable at the gate. None
    # on an anchorless / perspective-panel run (byte-compatible — the key is simply absent).
    if pool_shrinkage is not None:
        spread["pool_shrinkage"] = dict(pool_shrinkage)
    # BLF A5 — the specialist-seat summary ({ran:[...], declined:[{seat, reason}]}) so a
    # honestly-declined seat is visible to the gate (a decline PASSES) and never mistaken
    # for a seat that was never offered. Absent on a panel with no specialist seats.
    if specialist_summary is not None:
        spread["specialist_seats"] = dict(specialist_summary)
    if pseudo_diversity_caveat:
        spread["pseudo_diversity_caveat"] = pseudo_diversity_caveat
    if panel_resolution_note:
        spread["panel_resolution"] = panel_resolution_note
    # Mirror the process provenance into the readable notes list too.
    notes_out = list(aggregation.notes)
    provenance = [f"research_rounds={research_rounds}", f"delphi_rounds={delphi_rounds}"]
    if spread["supervisor_search"]:
        provenance.append("supervisor_search=on")
    notes_out.append("quorum provenance: " + ", ".join(provenance))
    if panel_resolution_note:
        notes_out.append(f"panel resolution: {panel_resolution_note}")
    if pseudo_diversity_caveat:
        notes_out.append(pseudo_diversity_caveat)
    if market_anchor and market_anchor.get("pull_applied"):
        notes_out.append(
            "market-anchor discipline: "
            + str(market_anchor.get("justification") or "verdict pulled toward market")
        )
    estimate_records: list[dict[str, Any]] = []
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO panel_runs (
                id, question_id, created_at, snapshot_id,
                aggregation_method, trim, aggregate_probability,
                perspectives, spread_summary, notes, triggered_by, judge,
                final_source, research_rounds, supervisor_evidence,
                delphi_rounds, delphi_audit
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                question_id,
                now,
                snapshot_id,
                aggregation.method,
                aggregation.trim,
                committed_probability,
                json_dumps(list(requested)),
                json_dumps(spread),
                json_dumps(notes_out),
                triggered_by,
                json_dumps(judge) if judge is not None else None,
                committed_source,
                research_rounds,
                json_dumps(supervisor_evidence),
                delphi_rounds,
                json_dumps(delphi_audit),
            ),
        )
        for row in aggregation.estimates:
            estimate_id = f"pe_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO panel_estimates (
                    id, panel_run_id, question_id, created_at, perspective,
                    probability, weight, trimmed, confidence_low, confidence_high,
                    rationale, reasons_up, reasons_down, change_my_mind, crux,
                    agent_model, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    estimate_id,
                    run_id,
                    question_id,
                    now,
                    row["perspective"],
                    float(row["probability"]),
                    float(row["weight"]),
                    1 if row.get("trimmed") else 0,
                    row.get("confidence_low"),
                    row.get("confidence_high"),
                    row.get("rationale") or "",
                    json_dumps(row.get("reasons_up") or []),
                    json_dumps(row.get("reasons_down") or []),
                    json_dumps(row.get("change_my_mind") or []),
                    row.get("crux"),
                    row.get("agent_model"),
                    json_dumps(row.get("metadata") or {}),
                ),
            )
            estimate_records.append({"id": estimate_id, **row})

    # CRUX PROMOTION (finding #4): lift each panelist's free-text crux into the
    # first-class question_cruxes table so it is queryable + re-checkable across
    # updates, instead of dying inside this panel blob. Runs inside the same commit
    # gate as record_panel_run; best-effort — a promotion hiccup never fails the
    # panel write.
    try:
        ledger.promote_panel_cruxes(
            question_id=question_id,
            panel_run_id=run_id,
            estimates=[dict(r) for r in aggregation.estimates],
        )
    except Exception as exc:  # noqa: BLE001 — promotion is additive, never blocks the panel
        logger.debug("crux promotion skipped for panel %s: %r", run_id, exc)

    return ledger.get_panel_run(run_id)


def get_panel_run(ledger, run_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM panel_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"panel run not found: {run_id}")
        estimates = conn.execute(
            """
            SELECT * FROM panel_estimates
            WHERE panel_run_id = ?
            ORDER BY perspective ASC
            """,
            (run_id,),
        ).fetchall()
    return ledger._panel_run_dict(row, estimates)


def list_panel_runs(
    ledger,
    question_id: str | None = None,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM panel_runs {where} ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            estimates = conn.execute(
                """
                SELECT * FROM panel_estimates
                WHERE panel_run_id = ?
                ORDER BY perspective ASC
                """,
                (row["id"],),
            ).fetchall()
            results.append(ledger._panel_run_dict(row, estimates))
    return results


def attach_panel_to_snapshot(ledger, panel_run_id: str, snapshot_id: str) -> dict[str, Any]:
    ledger.get_panel_run(panel_run_id)
    ledger.get_snapshot(snapshot_id)
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE panel_runs SET snapshot_id = ? WHERE id = ?",
            (snapshot_id, panel_run_id),
        )
    return ledger.get_panel_run(panel_run_id)


def _panel_run_dict(
    ledger,
    row: sqlite3.Row,
    estimates_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    data = dict(row)
    data["perspectives"] = json_loads(data["perspectives"], [])
    data["spread_summary"] = json_loads(data["spread_summary"], {})
    data["notes"] = json_loads(data["notes"], [])
    if "supervisor_evidence" in data:
        data["supervisor_evidence"] = json_loads(data["supervisor_evidence"], [])
    if "delphi_audit" in data:
        data["delphi_audit"] = json_loads(data.get("delphi_audit"), {})
    data["estimates"] = [ledger._panel_estimate_dict(e) for e in estimates_rows]
    return data


def _panel_estimate_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["trimmed"] = bool(data["trimmed"])
    data["reasons_up"] = json_loads(data["reasons_up"], [])
    data["reasons_down"] = json_loads(data["reasons_down"], [])
    data["change_my_mind"] = json_loads(data["change_my_mind"], [])
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def component_track_record(
    ledger,
    *,
    forecast_origin: str | None = "live",
    min_count: int | None = None,
    shrink_n0: float | None = None,
    edge_scale: float | None = None,
) -> list[dict[str, Any]]:
    """Measure each ensemble component's and panel perspective's Brier edge
    over the committed aggregate across resolved binary questions, and map
    it to an ADVISORY recommended weight (see :mod:`forecasting.track_record`
    for the shrinkage/clipping gates).

    Pairing rule — one observation per (question, component): the latest
    matching-origin snapshot that carries ``ensemble_components`` supplies
    the ensemble pairs (component probability vs that snapshot's committed
    probability); the latest panel run supplies the perspective pairs
    (estimate probability vs that run's aggregate). Non-binary questions
    and non-numeric payloads are skipped — the math is only proper for
    binary Brier.
    """
    from forecasting.ensembles import _component_rows
    from forecasting.track_record import (
        DEFAULT_EDGE_SCALE,
        DEFAULT_MIN_COUNT,
        DEFAULT_SHRINK_N0,
        ComponentObservation,
        summarize_components,
    )

    observations: list[ComponentObservation] = []
    for question in ledger.list_questions(status="resolved"):
        if question.outcome_space.type != "binary":
            continue
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            continue

        def _brier(probability: Any) -> float | None:
            try:
                payload = ledger._score_forecast_payload(
                    float(probability), resolution.outcome, question.outcome_space
                )
            except (TypeError, ValueError, ValidationError):
                return None
            value = payload.get("brier_score")
            return float(value) if isinstance(value, (int, float)) else None

        # Ensemble components: latest matching-origin snapshot that has them.
        snapshots = [
            snap
            for snap in ledger.list_snapshots(question.id)
            if forecast_origin is None or snap.forecast_origin == forecast_origin
        ]
        for snapshot in reversed(snapshots):
            rows = _component_rows(
                snapshot.ensemble_components
                if isinstance(snapshot.ensemble_components, dict)
                else {}
            )
            if not rows:
                continue
            aggregate_brier = _brier(snapshot.probability_or_distribution)
            if aggregate_brier is None:
                continue
            for row in rows:
                name = str(row.get("name") or "").strip()
                component_brier = _brier(row.get("probability"))
                if not name or component_brier is None:
                    continue
                observations.append(
                    ComponentObservation(
                        name=name,
                        kind="ensemble",
                        question_id=question.id,
                        component_brier=component_brier,
                        aggregate_brier=aggregate_brier,
                    )
                )
            break  # one snapshot per question — newest with components

        # Panel perspectives: latest run, paired against its own aggregate.
        runs = ledger.list_panel_runs(question.id, limit=1)
        if runs:
            run = runs[0]
            aggregate_brier = _brier(run.get("aggregate_probability"))
            if aggregate_brier is not None:
                for estimate in run.get("estimates", []):
                    perspective = str(estimate.get("perspective") or "").strip()
                    component_brier = _brier(estimate.get("probability"))
                    if not perspective or component_brier is None:
                        continue
                    observations.append(
                        ComponentObservation(
                            name=perspective,
                            kind="panel",
                            question_id=question.id,
                            component_brier=component_brier,
                            aggregate_brier=aggregate_brier,
                        )
                    )

    records = summarize_components(
        observations,
        min_count=min_count if min_count is not None else DEFAULT_MIN_COUNT,
        shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
        edge_scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
    )
    return [record.to_dict() for record in records]


def recommended_component_weights(
    ledger,
    *,
    kind: str = "panel",
    forecast_origin: str | None = "live",
    min_count: int | None = None,
) -> dict[str, float]:
    """``{name: weight}`` for measured components only — advisory, never
    silently applied; callers opt in (e.g. ``forecast panel record
    --track-record-weights``)."""
    records = ledger.component_track_record(
        forecast_origin=forecast_origin, min_count=min_count
    )
    return {
        row["name"]: float(row["recommended_weight"])
        for row in records
        if row["kind"] == kind and row["status"] == "measured"
    }


def model_track_record(
    ledger,
    *,
    min_count: int | None = None,
    shrink_n0: float | None = None,
    edge_scale: float | None = None,
) -> list[dict[str, Any]]:
    """Measure each PANELIST MODEL's Brier edge over the cross-model panel
    average across resolved binary questions, and map it to a shrunk,
    clipped weight (reuses :mod:`forecasting.track_record` — the same math
    as :meth:`component_track_record`, but keyed on the panelist ``model``
    and scored against the OUTCOME with the per-question cross-model mean as
    the reference).

    One observation per (question, model): the latest panel run supplies
    each panelist's probability; its Brier vs the confirmed outcome is paired
    against the mean panelist Brier on that same question (positive edge ⇒
    the model beat the pack). Non-binary questions and non-numeric payloads
    are skipped — binary Brier only. A model that repeats within one run (the
    ``self`` preset) is averaged to a single per-question observation so it
    cannot double-count.

    There is deliberately no ``forecast_origin`` filter: quorum ``panel_runs``
    are not origin-tagged per estimate (a run's ``snapshot_id`` is often unset
    at record time), so an origin argument could not honestly restrict pairing
    and would silently mix backtest+live panelist performance. Strata-aware
    weighting is a schema change (tag panel runs with an origin) — not a
    parameter — and is left for when that need is real.
    """
    from forecasting.track_record import (
        DEFAULT_EDGE_SCALE,
        DEFAULT_SHRINK_N0,
        ComponentObservation,
        summarize_components,
    )

    observations: list[ComponentObservation] = []
    for question in ledger.list_questions(status="resolved"):
        if question.outcome_space.type != "binary":
            continue
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            continue

        def _brier(probability: Any) -> float | None:
            try:
                payload = ledger._score_forecast_payload(
                    float(probability), resolution.outcome, question.outcome_space
                )
            except (TypeError, ValueError, ValidationError):
                return None
            value = payload.get("brier_score")
            return float(value) if isinstance(value, (int, float)) else None

        runs = ledger.list_panel_runs(question.id, limit=1)
        if not runs:
            continue
        run = runs[0]
        # Group each panelist model's Brier(s) on THIS question, then average
        # within model so a repeated model (self preset) is one observation.
        per_model: dict[str, list[float]] = {}
        for estimate in run.get("estimates", []):
            model = str(estimate.get("agent_model") or estimate.get("perspective") or "").strip()
            brier = _brier(estimate.get("probability"))
            if not model or brier is None:
                continue
            per_model.setdefault(model, []).append(brier)
        model_briers = {
            model: sum(values) / len(values)
            for model, values in per_model.items()
            if values
        }
        if not model_briers:
            continue
        # Reference: the cross-model mean Brier on this question (difficulty-
        # normalised — a model is rewarded/penalised only relative to the pack).
        reference_brier = sum(model_briers.values()) / len(model_briers)
        for model, brier in model_briers.items():
            observations.append(
                ComponentObservation(
                    name=model,
                    kind="model",
                    question_id=question.id,
                    component_brier=brier,
                    aggregate_brier=reference_brier,
                )
            )

    records = summarize_components(
        observations,
        min_count=min_count if min_count is not None else ledger.MODEL_WEIGHT_MIN_SAMPLE,
        shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
        edge_scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
    )
    return [record.to_dict() for record in records]


def recommended_model_weights(
    ledger,
    *,
    min_sample: int | None = None,
) -> dict[str, float]:
    """``{model: weight}`` for MEASURED panelist models only (those clearing
    the resolved-sample gate). A model below the gate is absent — the quorum
    dispatcher defaults it to weight 1.0, so a cold-start panel is equal-
    weighted by construction and no model can dominate early. Shrinkage
    toward 1.0 lives in :func:`forecasting.track_record.edge_to_weight`."""
    records = ledger.model_track_record(
        min_count=min_sample if min_sample is not None else ledger.MODEL_WEIGHT_MIN_SAMPLE,
    )
    return {
        row["name"]: float(row["recommended_weight"])
        for row in records
        if row["status"] == "measured"
    }


def latest_panel_run_by_question(ledger, question_ids: list[str]) -> dict[str, dict[str, Any]]:
    """question_id -> its most-recent panel run dict (mirrors
    list_panel_runs(qid, limit=1)[0]); absent when a question has no panel."""
    out: dict[str, dict[str, Any]] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM panel_runs WHERE question_id IN ({placeholders}) "
                "ORDER BY question_id ASC, created_at DESC",
                chunk,
            ).fetchall()
            # Keep only the latest run per question (first row per id, since
            # created_at DESC), then fetch each run's estimates.
            latest_rows: list[sqlite3.Row] = []
            seen: set[str] = set()
            for row in rows:
                qid = row["question_id"]
                if qid not in seen:
                    seen.add(qid)
                    latest_rows.append(row)
            for row in latest_rows:
                estimates = conn.execute(
                    "SELECT * FROM panel_estimates WHERE panel_run_id = ? "
                    "ORDER BY perspective ASC",
                    (row["id"],),
                ).fetchall()
                out[row["question_id"]] = ledger._panel_run_dict(row, estimates)
    return out
