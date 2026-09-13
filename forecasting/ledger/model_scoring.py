"""Market-model-run + model-skill domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the model-RUN table family and the
skill-weighting it feeds:

* MODEL RUNS: ``record_model_run`` / ``link_question_market_model`` / ``get_model_run``
  / ``list_model_runs`` / ``_row_to_model_run`` and the run scorers
  (``score_model_runs`` + the ``_model_run_probability`` / ``_model_run_numeric``
  point extractors);
* MODEL SKILL: ``model_skill`` (the per-market-model track record) and the
  refresh-time skill-weight application (``_skill_weights_enabled`` /
  ``_market_model_scored_run_count`` / ``_apply_model_skill_weights``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. ``_component_market_model_id``
(a classmethod reading the ``_MARKET_MODEL_ID_RE`` class attribute) stays in core
and is reached through the ``ledger`` INSTANCE, as are all cross-domain reads."""

from __future__ import annotations

from typing import Any
from forecasting.models import ForecastQuestion
from forecasting.models import LedgerNotFoundError
from forecasting.models import ValidationError
from forecasting.models import json_dumps
from forecasting.models import json_loads
import math
from forecasting.models import parse_timestamp
import sqlite3
from forecasting.models import utc_now_iso
import uuid


def record_model_run(
    ledger,
    *,
    question_id: str,
    model_type: str,
    status: str = "success",
    inputs: dict[str, Any] | None = None,
    parameters: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
    code_ref: str | None = None,
    artifact_paths: list[str] | None = None,
    model_version: str | None = None,
    prompt_version: str | None = None,
    data_version: str | None = None,
    evidence_cutoff: str | None = None,
    market_model_id: str | None = None,
) -> dict[str, Any]:
    ledger.get_question(question_id)
    if not model_type.strip():
        raise ValidationError("model_type is required")
    if status not in {"success", "failure"}:
        raise ValidationError("model run status must be success or failure")
    model_run_id = f"mr_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO model_runs (
                id, question_id, created_at, model_type, status, inputs, parameters,
                output, diagnostics, code_ref, artifact_paths, model_version,
                prompt_version, data_version, evidence_cutoff, market_model_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_run_id,
                question_id,
                utc_now_iso(),
                model_type.strip(),
                status,
                json_dumps(inputs or {}),
                json_dumps(parameters or {}),
                json_dumps(output or {}),
                json_dumps(diagnostics or {}),
                code_ref,
                json_dumps(artifact_paths or []),
                model_version,
                prompt_version,
                data_version,
                parse_timestamp(evidence_cutoff, field_name="evidence_cutoff"),
                market_model_id,
            ),
        )
    return ledger.get_model_run(model_run_id)


def link_question_market_model(ledger, question_id: str, market_model_id: str) -> ForecastQuestion:
    """Record the question<->market-model edge on the QUESTION side.
    Writes ``metadata['source_market_model']`` (the reciprocal of the model
    spec's ``forecast_question_id``), so a question built/seeded from a Market
    Model carries the link both ways. Idempotent — re-linking the same model is
    a no-op. The spec side is written by the caller via
    :meth:`update_market_model_spec`."""
    question = ledger.get_question(question_id)
    meta = dict(question.metadata) if isinstance(question.metadata, dict) else {}
    if meta.get("source_market_model") == market_model_id:
        return question
    meta["source_market_model"] = market_model_id
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
            (json_dumps(meta), question_id),
        )
    return ledger.get_question(question_id)


def get_model_run(ledger, model_run_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (model_run_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"model run not found: {model_run_id}")
    return ledger._row_to_model_run(row)


def list_model_runs(ledger, question_id: str) -> list[dict[str, Any]]:
    ledger.get_question(question_id)
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM model_runs WHERE question_id = ? ORDER BY created_at ASC",
            (question_id,),
        ).fetchall()
    return [ledger._row_to_model_run(row) for row in rows]


def _model_run_probability(output: dict[str, Any]) -> float | None:
    """Read a projected PROBABILITY in [0,1] from a model_run output, if one
    is present. Only genuine model projections carry these keys — a
    ``forecast_refresh`` run stores ``proposed_probability`` (deliberately not
    matched here) so the desk's own committed number never masquerades as an
    independent model observation."""
    if not isinstance(output, dict):
        return None
    for key in ("probability", "value", "projected_value", "p", "base_rate"):
        raw = output.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        val = float(raw)
        if math.isfinite(val) and 0.0 <= val <= 1.0:
            return val
    return None


def _model_run_numeric(output: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
    """Read ``(projected_value, lo, hi)`` from a model_run output for numeric
    interval scoring. Any of the three may be None."""
    if not isinstance(output, dict):
        return None, None, None
    def _num(*keys: str) -> float | None:
        for key in keys:
            raw = output.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            val = float(raw)
            if math.isfinite(val):
                return val
        return None
    return _num("projected_value", "value", "mean", "point"), _num("lo", "lower"), _num("hi", "upper")


def score_model_runs(
    ledger,
    question_id: str,
    outcome: Any,
    *,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Score this question's model_runs against a confirmed ``outcome`` and
    persist ``outcome_score`` / ``interval_hit`` / ``scored_at`` on each row.
    * BINARY question — Brier of the model's projected probability (via the
      same :meth:`_score_forecast_payload` path as a snapshot). ``interval_hit``
      stays NULL (the read-side discriminator for a binary-Brier observation).
    * NUMERIC question — coverage: ``interval_hit`` is 1 when the outcome falls
      inside the model's ``[lo, hi]`` (else 0; NULL when the model emitted no
      interval); ``outcome_score`` is the absolute error vs ``projected_value``.
    Only runs whose output carries a usable projection are scored; the rest are
    left untouched. Best-effort per run — never raises (the caller in
    :meth:`resolve_question` is already fail-open, but a malformed single run
    must not skip its siblings). Returns the list of scored-run summaries."""
    question = ledger.get_question(question_id)
    stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
    scored: list[dict[str, Any]] = []
    for run in ledger.list_model_runs(question_id):
        output = run.get("output") if isinstance(run.get("output"), dict) else {}
        outcome_score: float | None = None
        interval_hit: int | None = None
        try:
            if question.outcome_space.type == "binary":
                prob = ledger._model_run_probability(output)
                if prob is None:
                    continue
                payload = ledger._score_forecast_payload(
                    prob, outcome, question.outcome_space
                )
                brier = payload.get("brier_score")
                if not isinstance(brier, (int, float)):
                    continue
                outcome_score = float(brier)
            elif question.outcome_space.type == "numeric":
                projected, lo, hi = ledger._model_run_numeric(output)
                if projected is None and lo is None and hi is None:
                    continue
                outcome_value = ledger._numeric_outcome(outcome)
                if lo is not None and hi is not None:
                    low, high = (lo, hi) if lo <= hi else (hi, lo)
                    interval_hit = 1 if low <= outcome_value <= high else 0
                if projected is not None:
                    outcome_score = abs(projected - outcome_value)
                if outcome_score is None and interval_hit is None:
                    continue
            else:
                continue
        except (TypeError, ValueError, ValidationError):
            continue
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE model_runs SET outcome_score = ?, interval_hit = ?, scored_at = ? WHERE id = ?",
                (outcome_score, interval_hit, stamped, run["id"]),
            )
        scored.append(
            {
                "model_run_id": run["id"],
                "model_type": run.get("model_type"),
                "market_model_id": run.get("market_model_id"),
                "outcome_score": outcome_score,
                "interval_hit": interval_hit,
            }
        )
    return scored


def _row_to_model_run(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field in ("inputs", "parameters", "output", "diagnostics"):
        data[field] = json_loads(data[field], {})
    data["artifact_paths"] = json_loads(data["artifact_paths"], [])
    return data


def model_skill(
    ledger,
    *,
    model_type: str | None = None,
    market_model_id: str | None = None,
    min_count: int | None = None,
    shrink_n0: float | None = None,
    edge_scale: float | None = None,
) -> dict[str, Any]:
    """Compute a model's SKILL on-read from scored ``model_runs`` (R4).
    Mirrors :meth:`model_track_record`: iterate resolved questions, read each
    matching model_run's persisted score, and reuse
    :mod:`forecasting.track_record` (shrink toward 1.0, clip, minimum resolved
    sample before the weight moves — the S7.5 semantics) to map the BINARY
    Brier edge over the uninformative baseline into a ``weight_multiplier``.
    ``model_type`` / ``market_model_id`` narrow the population (both None =
    every scored run, one global skill record). Cold start (fewer than
    ``min_count`` binary-scored runs) returns ``weight_multiplier`` exactly
    1.0 and ``status='insufficient_track_record'`` — harmless by construction.
    Numeric runs contribute ``coverage`` (interval-hit rate) and ``mae`` but do
    not move the binary weight multiplier (the re-pool they weight is
    binary-only)."""
    from forecasting.track_record import (
        DEFAULT_EDGE_SCALE,
        DEFAULT_SHRINK_N0,
        edge_to_weight,
        shrink_edge,
    )
    gate = min_count if min_count is not None else ledger.MODEL_WEIGHT_MIN_SAMPLE
    binary_briers: list[float] = []
    interval_hits: list[int] = []
    abs_errors: list[float] = []
    numeric_run_count = 0
    question_ids: set[str] = set()
    for question in ledger.list_questions(status="resolved"):
        resolution = ledger.get_latest_resolution(question.id, confirmed_only=True)
        if resolution is None:
            continue
        q_type = question.outcome_space.type
        for run in ledger.list_model_runs(question.id):
            if run.get("scored_at") is None:
                continue
            if model_type is not None and run.get("model_type") != model_type:
                continue
            if market_model_id is not None and run.get("market_model_id") != market_model_id:
                continue
            score = run.get("outcome_score")
            hit = run.get("interval_hit")
            # Classify by the QUESTION's type (authoritative), not the NULL-ness
            # of interval_hit — a numeric run may legitimately carry no interval.
            if q_type == "binary":
                if isinstance(score, (int, float)):
                    binary_briers.append(float(score))
                    question_ids.add(question.id)
            elif q_type == "numeric":
                if hit is not None:
                    interval_hits.append(1 if hit else 0)
                if isinstance(score, (int, float)):
                    abs_errors.append(float(score))
                if hit is not None or isinstance(score, (int, float)):
                    numeric_run_count += 1
                    question_ids.add(question.id)
    n_binary = len(binary_briers)
    n_numeric = numeric_run_count
    brier_mean = (sum(binary_briers) / n_binary) if n_binary else None
    coverage = (sum(interval_hits) / len(interval_hits)) if interval_hits else None
    mae = (sum(abs_errors) / len(abs_errors)) if abs_errors else None
    # Weight multiplier: shrink+clip the binary edge over the baseline, gated
    # on the resolved-binary sample (identity below the gate).
    edge_shrunk = 0.0
    weight_multiplier = 1.0
    status = "insufficient_track_record"
    if brier_mean is not None and n_binary >= gate:
        edge_mean = ledger._MODEL_SKILL_BASELINE_BRIER - brier_mean
        edge_shrunk = shrink_edge(
            edge_mean, n_binary,
            shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
        )
        weight_multiplier = edge_to_weight(
            edge_shrunk,
            scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
        )
        status = "measured"
    elif brier_mean is not None:
        # Report direction-of-travel even below the gate (weight stays 1.0).
        edge_mean = ledger._MODEL_SKILL_BASELINE_BRIER - brier_mean
        edge_shrunk = shrink_edge(
            edge_mean, n_binary,
            shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
        )
    return {
        "model_type": model_type,
        "market_model_id": market_model_id,
        "n_scored": n_binary + n_numeric,
        "n_binary": n_binary,
        "n_numeric": n_numeric,
        "brier": brier_mean,
        "coverage": coverage,
        "mae": mae,
        "edge_shrunk": edge_shrunk,
        "weight_multiplier": weight_multiplier,
        "status": status,
        "min_sample": gate,
        "question_ids": sorted(question_ids),
    }


def _skill_weights_enabled(ledger) -> bool:
    """Read ``forecasting.models.skill_weights`` (default TRUE). Best-effort:
    a config-read failure degrades to enabled — the R4 re-pool weighting is
    harmless-by-construction on cold start (every multiplier is 1.0 until a
    model clears the resolved-binary sample gate)."""
    try:
        from superforecasting_agent.storage.configuration import read_configuration
        cfg = read_configuration() or {}
        fc = cfg.get("forecasting", {}) if isinstance(cfg, dict) else {}
        models_cfg = fc.get("models", {}) if isinstance(fc, dict) else {}
        if isinstance(models_cfg, dict) and "skill_weights" in models_cfg:
            return bool(models_cfg["skill_weights"])
    except Exception:
        pass
    return True


def _market_model_scored_run_count(ledger, market_model_id: str) -> int:
    """Cheap COUNT of scored model_runs tagged to a Market Model — an UPPER bound
    on the binary sample :meth:`model_skill` would find (some may be numeric). The
    skill weight can only move once ``n_binary >= MODEL_WEIGHT_MIN_SAMPLE``, so a
    count below the gate proves the multiplier is identity by construction. This
    lets the skill-weighted re-pool skip the O(resolved) skill scan on cold-start /
    lightly-tagged books (a batch sweep would otherwise pay it per question).
    Returns -1 on any read error so the caller falls back to the full scan."""
    try:
        with ledger._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM model_runs WHERE market_model_id = ? AND scored_at IS NOT NULL",
                (market_model_id,),
            ).fetchone()
        return int(row[0]) if row else 0
    except Exception:
        return -1


def _apply_model_skill_weights(
    ledger, rows: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Scale each model-sourced component's weight by its Market Model's skill
    multiplier (R4). Returns ``(scaled_rows, applied)`` where ``applied`` is the
    audit trail of ``{name, market_model_id, multiplier, prior_weight,
    new_weight}`` for every component actually scaled (skill measured +
    multiplier != 1.0). Non-model components and cold-start models pass through
    unchanged (identity multiplier), so the pooled number is byte-identical to
    the unweighted re-pool until a model earns a measured skill."""
    applied: list[dict[str, Any]] = []
    skill_cache: dict[str, dict[str, Any]] = {}
    scaled: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        mmid = ledger._component_market_model_id(row)
        if mmid is not None:
            skill = skill_cache.get(mmid)
            if skill is None:
                # Precheck: if the model has fewer scored runs than the sample gate,
                # its skill is identity by construction — skip the O(resolved) scan
                # (the batch-sweep cost the finding flagged). -1 = read error → do
                # the real scan rather than silently skip.
                n_scored = ledger._market_model_scored_run_count(mmid)
                if 0 <= n_scored < ledger.MODEL_WEIGHT_MIN_SAMPLE:
                    skill = {"weight_multiplier": 1.0, "status": "insufficient_track_record"}
                else:
                    try:
                        skill = ledger.model_skill(market_model_id=mmid)
                    except Exception:
                        skill = {"weight_multiplier": 1.0, "status": "insufficient_track_record"}
                skill_cache[mmid] = skill
            multiplier = float(skill.get("weight_multiplier") or 1.0)
            if skill.get("status") == "measured" and abs(multiplier - 1.0) > 1e-9:
                prior_weight = ledger._numeric_probability(row.get("weight", 1.0)) or 0.0
                new_weight = prior_weight * multiplier
                row["weight"] = new_weight
                applied.append(
                    {
                        "name": str(row.get("name") or row.get("source") or mmid),
                        "market_model_id": mmid,
                        "multiplier": multiplier,
                        "prior_weight": prior_weight,
                        "new_weight": new_weight,
                        "n_scored": skill.get("n_binary"),
                    }
                )
        scaled.append(row)
    return scaled, applied
