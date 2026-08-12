"""Forecast-refresh + update-trigger domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns the REFRESH pipeline and its change
detection:

* REFRESH: ``refresh_forecast`` (re-pool a question's live sources into a fresh
  snapshot) with its helpers (``_refresh_source_keys`` / ``_refresh_reading_value``
  / ``_apply_fresh_market_probabilities`` / ``_default_refresh_rationale``);
* SOURCE SNAPSHOTS: ``_record_source_snapshot`` / ``list_source_snapshots`` /
  ``_row_to_source_snapshot``;
* UPDATE TRIGGERS: ``check_update_triggers`` / ``_derive_trigger_observations``.

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. The classmethod
``_refresh_pool_method`` (reads the ``_REFRESH_POOL_METHODS`` class attribute)
stays in core and, like every cross-domain read, is reached through the
``ledger`` INSTANCE, so no sibling leaf is imported here."""

from __future__ import annotations

import hashlib
from forecasting.models import AlertEvent
from typing import Any
from forecasting.models import ValidationError
from forecasting.models import evaluate_update_triggers
from forecasting.models import json_dumps
from forecasting.models import json_loads
from forecasting.models import parse_timestamp
import sqlite3
from forecasting.models import utc_now_iso
import uuid


def refresh_forecast(
    ledger,
    question_id: str,
    *,
    fetcher: Any,
    now: str | None = None,
    re_estimate: str = "deterministic",
    extremize: float = 1.0,
    correlation: Any | None = None,
    dry_run: bool = False,
    commit: bool = True,
    proposal_only: bool = False,
    trigger_reason: str = "manual_refresh",
    skill_weights: bool | None = None,
) -> dict[str, Any]:
    """Pull the latest watched-source readings, import the new values as
    evidence, deterministically re-pool the forecast, and (by default)
    commit a new live snapshot. ``proposal_only`` persists the evidence and
    model run but requires an explicit proposal approval before the probability
    changes; unattended callers must use that mode.
    ``fetcher(specs) -> [{source_type, source, success, payloads, error}]``
    is injected by the caller (CLI / tool layer) so the ledger never imports
    the adapter/tool layer; ``payloads`` are kwargs for :meth:`add_evidence`.
    ``re_estimate="deterministic"`` re-pools the prior snapshot's
    probability-bearing components after refreshing market/crowd readings;
    ``"carry_forward"`` keeps the prior probability only as a preview and flags
    that agent/manual re-reasoning is needed (also the automatic fallback for
    non-binary questions or raw-data-only sources). Persisted evidence and its
    model-run audit are retained, but an unchanged probability is never presented
    as a newly committed forecast.
    """
    if re_estimate not in {"deterministic", "carry_forward"}:
        raise ValidationError("re_estimate must be 'deterministic' or 'carry_forward'")
    if commit and proposal_only:
        raise ValidationError("commit and proposal_only are mutually exclusive")
    question = ledger.get_question(question_id)
    current = ledger.get_current_snapshot(question_id)
    if current is None:
        raise ValidationError("refresh requires a baseline forecast snapshot")
    run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
    persist = bool(commit or proposal_only) and not dry_run
    watches = ledger.list_watched_sources(
        scope_type="question", scope_ref=question_id, status="active"
    )
    if not watches:
        return {
            "status": "no_watched_sources",
            "committed": None,
            # NOT a completed update: a deterministic re-pool cannot collect
            # evidence, so a sourceless question gets none. The caller owns
            # closing this gap (import_source_evidence per driver, or re-run
            # with --agent so the LLM update stage gathers it) — never treat
            # this as "refreshed" or borrow a linked forecast's evidence.
            "evidence_required": True,
            "message": (
                "NO active watched sources — this is NOT a completed update. Collect "
                "evidence for THIS question (import_source_evidence per driver, then "
                "`forecast watch add` so it can refresh next time), or re-run with --agent "
                "to collect evidence via the LLM update stage. Do not borrow another "
                "forecast's evidence as a substitute."
            ),
        }
    prior_observations = ledger._derive_trigger_observations(question_id)
    # 1) Re-fetch every active watched source (parallel, injected fetcher).
    specs = []
    for watch in watches:
        control_keys = {"autopilot_policy_id", "required", "auto_watch", "from_action", "source_ref"}
        adapter_args = {
            key: value
            for key, value in (watch.get("metadata") or {}).items()
            if key not in control_keys
        }
        specs.append(
            {"source_type": watch["source_type"], "source": watch["source"], "args": adapter_args}
        )
    fetched = fetcher(specs)
    # 2) Reduce each fetched reading to its latest numeric value + keys, and
    #    decide which readings actually changed vs the last imported value.
    fresh_market_readings: list[dict[str, Any]] = []
    fresh_values: dict[str, float] = {}
    changed_readings: list[dict[str, Any]] = []
    fetch_failures: list[dict[str, str]] = []
    new_evidence_ids: list[str] = []
    for result in fetched or []:
        if not result.get("success"):
            fetch_failures.append(
                {"source": f"{result.get('source_type')}:{result.get('source')}", "error": result.get("error") or "fetch failed"}
            )
            continue
        stype = str(result.get("source_type") or "")
        source = str(result.get("source") or "")
        keys = ledger._refresh_source_keys(stype, source)
        for payload in result.get("payloads") or []:
            item = (payload.get("metadata") or {}).get("adapter_item") or {}
            market_p = ledger._numeric_probability(item.get("probability"))
            raw_value = ledger._refresh_reading_value(item)
            reading = market_p if market_p is not None else raw_value
            if market_p is not None:
                # One reading, one entry (with all its identity keys) so the
                # same reading is never double-counted as matched + unmatched.
                fresh_market_readings.append(
                    {"keys": set(keys), "probability": market_p, "label": f"{stype}:{source}"}
                )
            for key in keys:
                if reading is not None:
                    fresh_values[key] = reading
            # A reading is "changed" if new or different from the last import.
            is_changed = reading is None or any(
                key not in prior_observations or abs(prior_observations[key] - reading) > 1e-9
                for key in keys
            )
            if is_changed:
                changed_readings.append({"source_type": stype, "source": source, "value": reading, "payload": payload})
                if persist:
                    # Stamp the imported reading as available AS OF run_at —
                    # the refresh moment, which is exactly this snapshot's
                    # evidence_cutoff below. Without this, add_evidence defaults
                    # available_at to a FRESH utc_now_iso() (truncated to whole
                    # seconds); if the wall clock ticks a second between run_at
                    # and this write on a slow worker, the new evidence lands
                    # after the cutoff and _validate_evidence_refs rejects the
                    # commit. A payload-supplied available_at still wins (a real
                    # adapter reading's true observation time).
                    evidence = ledger.add_evidence(
                        question_id=question_id,
                        archive_url_snapshot=False,
                        **{"available_at": run_at, **payload},
                    )
                    new_evidence_ids.append(evidence.id)
    # 3) Re-estimate.
    prior_rows = ledger._ensemble_component_rows(current.ensemble_components)
    binary = question.outcome_space.type == "binary" and isinstance(
        current.probability_or_distribution, (int, float)
    )
    updated_components, unmatched_sources = ledger._apply_fresh_market_probabilities(
        current.ensemble_components, fresh_market_readings
    )
    can_repool = (
        re_estimate == "deterministic"
        and binary
        and bool(prior_rows)
        and bool(updated_components["matched"])
    )
    prior_prob = float(current.probability_or_distribution) if binary else None
    new_prob: Any = current.probability_or_distribution
    new_components = current.ensemble_components
    diff_dict: dict[str, Any] | None = None
    reasons_up: list[str] = []
    reasons_down: list[str] = []
    needs_agent = not can_repool
    skill_multipliers_applied: list[dict[str, Any]] = []
    if can_repool:
        from forecasting.bayes_toolkit import (  # local import avoids cycle / heavy import at module load
            combine_forecasts,
            ensure_industry_backends,
            forecast_diff,
        )
        ensure_industry_backends()
        method = ledger._refresh_pool_method(current.method)
        # R4 Living Models: scale each model-sourced component's weight by its
        # Market Model's measured skill multiplier BEFORE pooling. The persisted
        # component weights stay the ORIGINAL (unscaled) values, so the
        # multiplier is re-derived fresh from current skill on every refresh and
        # never compounds. Config-gated (forecasting.models.skill_weights, default
        # ON) and identity on cold start — the pooled number is unchanged until a
        # model earns a measured skill.
        use_skill_weights = (
            ledger._skill_weights_enabled() if skill_weights is None else bool(skill_weights)
        )
        pool_rows = updated_components["rows"]
        if use_skill_weights:
            pool_rows, skill_multipliers_applied = ledger._apply_model_skill_weights(pool_rows)
        pool = combine_forecasts(
            pool_rows,
            method=method,
            extremize=extremize,
            correlation_matrix=correlation,
        )
        new_prob = pool.probability
        new_components = {"components": updated_components["rows"]}
        diff = forecast_diff(
            previous=prior_prob,
            current=float(new_prob),
            components=updated_components["diff_components"],
        )
        diff_dict = diff.to_dict()
        for driver in diff.drivers:
            pts = driver.get("contribution_pts")
            if pts is None:
                continue
            label = f"{driver.get('name', 'component')} ({pts:+.1f} pts)"
            (reasons_up if pts >= 0 else reasons_down).append(label)
    prob_changed = (
        binary
        and isinstance(new_prob, (int, float))
        and abs(float(new_prob) - prior_prob) > 1e-9
    )
    # 4) No-op guard: nothing fetched-changed and probability unchanged.
    if not changed_readings and not prob_changed:
        return {
            "status": "no_change",
            "committed": None,
            "message": "no new readings and probability unchanged — nothing committed.",
            "prior_probability": current.probability_or_distribution,
            "fetch_failures": fetch_failures,
            "unmatched_sources": unmatched_sources,
        }
    # 5) Fire executable update_triggers against the fresh values (idempotent).
    trigger_alerts: list[AlertEvent] = []
    if persist:
        trigger_alerts = ledger.check_update_triggers(
            question_id=question_id, observations=fresh_values or None, now=run_at
        )
    # 6) Auto rationale (no human in the loop).
    rationale = ledger._default_refresh_rationale(
        changed_readings=changed_readings,
        unmatched_sources=unmatched_sources,
        new_prob=new_prob,
        prior_prob=current.probability_or_distribution,
        re_estimate="deterministic" if can_repool else "carry_forward",
        needs_agent=needs_agent,
    )
    preview = {
        "status": "carry_forward" if needs_agent else "re_pooled",
        "committed": None,
        "prior_probability": current.probability_or_distribution,
        "proposed_probability": new_prob,
        "diff": diff_dict,
        "reasons_up": reasons_up,
        "reasons_down": reasons_down,
        "rationale": rationale,
        "changed_readings": [
            {"source_type": r["source_type"], "source": r["source"], "value": r["value"]}
            for r in changed_readings
        ],
        "unmatched_sources": unmatched_sources,
        "fetch_failures": fetch_failures,
        "needs_agent": needs_agent,
        "triggers_fired": [alert.reason for alert in trigger_alerts],
        "skill_multipliers": skill_multipliers_applied,
    }
    if not persist:
        preview["message"] = "preview only — re-run without --dry-run/--no-commit to commit."
        return preview
    # 7) Record a model run as the audit + citation anchor. A deterministic
    # re-pool may commit; a carry-forward may not impersonate fresh judgment.
    change_my_mind = [
        "A reversal in the strongest refreshed driver would move this back",
        "A watched source going stale or failing on the next refresh",
    ]
    model_run = ledger.record_model_run(
        question_id=question_id,
        model_type="forecast_refresh",
        inputs={
            "trigger_reason": trigger_reason,
            "prior_forecast_id": current.forecast_id,
            "new_evidence_ids": new_evidence_ids,
        },
        parameters={
            "re_estimate": "deterministic" if can_repool else "carry_forward",
            "method": ledger._refresh_pool_method(current.method),
            "extremize": extremize,
        },
        output={"proposed_probability": new_prob, "diff": diff_dict},
        diagnostics={"changed_readings": len(changed_readings), "fetch_failures": fetch_failures},
    )
    if needs_agent:
        alert = ledger.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=question_id,
            reason=f"forecast_estimation_required:{model_run['id']}",
            recommended_action=(
                "New source evidence was imported, but it cannot be deterministically "
                "re-pooled. Re-estimate the forecast before committing a new snapshot."
            ),
            now=run_at,
        )
        with ledger._connect() as conn:
            source_task = conn.execute(
                """
                SELECT task.id FROM operational_tasks AS task
                LEFT JOIN alert_events AS alert ON alert.id = task.alert_id
                WHERE task.question_id = ? AND task.status IN ('pending', 'leased')
                  AND (
                    task.task_type = 'process_source_change'
                    OR (task.task_type = 'resolve_warning'
                        AND alert.reason LIKE 'forecast_estimation_required:%')
                  )
                ORDER BY CASE WHEN task.task_type = 'process_source_change' THEN 0 ELSE 1 END,
                         task.utility_score DESC, task.available_at, task.id
                LIMIT 1
                """,
                (question_id,),
            ).fetchone()
        estimator_task_id = (
            source_task["id"]
            if source_task is not None
            else ledger.enqueue_alert_operational_task(
                alert, lane="normal_reforecast", now=run_at
            )["id"]
        )
        return {
            **preview,
            "status": "needs_estimation",
            "committed": None,
            "forecast_id": None,
            "model_run": model_run,
            "new_evidence_ids": new_evidence_ids,
            "alerts": [alert],
            "estimator_task_id": estimator_task_id,
            "message": "evidence imported; estimation required — no forecast committed.",
        }
    if proposal_only:
        proposal = ledger.create_forecast_update_proposal(
            question_id=question_id,
            run_id=None,
            prior_forecast_id=current.forecast_id,
            proposed_probability_or_distribution=new_prob,
            rationale=rationale,
            evidence_refs=new_evidence_ids,
            model_run_refs=[model_run["id"]],
        )
        alert = ledger.create_alert(
            severity="info",
            scope_type="question",
            scope_ref=question_id,
            reason=f"autopilot_update_proposed:{proposal['id']}",
            recommended_action=(
                f"Review with `forecast autopilot approve {proposal['id']}` or reject it."
            ),
            now=run_at,
        )
        return {
            **preview,
            "status": "proposal_created",
            "proposal": proposal,
            "model_run": model_run,
            "new_evidence_ids": new_evidence_ids,
            "alerts": [*trigger_alerts, alert],
            "message": "evidence imported and proposal created; no forecast committed.",
        }
    snapshot = ledger.create_snapshot(
        question_id=question_id,
        probability_or_distribution=new_prob,
        rationale=rationale,
        method=current.method,
        ensemble_components=new_components,
        forecast_origin="live",
        evidence_refs=new_evidence_ids,
        model_run_refs=[model_run["id"]],
        reasons_up=reasons_up or ["Refreshed watched-source readings"],
        reasons_down=reasons_down or ["Counter-signals in the refreshed sources"],
        change_my_mind=change_my_mind,
        require_citations=True,
        style_autofix=True,  # programmatic re-pool: mechanically clean generated prose, never block
        distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
        panel_skipped_reason=(
            "automated forecast refresh — deterministic re-pool of existing components; "
            "panel not required for a programmatic re-estimate"
        ),
        evidence_cutoff=run_at,
        metadata={
            "refresh": {
                "trigger_reason": trigger_reason,
                "re_estimate": "deterministic" if can_repool else "carry_forward",
                "prior_forecast_id": current.forecast_id,
                "needs_agent": needs_agent,
                "diff": diff_dict,
            },
            # R4 audit trail: the skill multipliers applied to model-sourced
            # components in this re-pool (empty when none applied / cold start),
            # mirroring how calibration_adjustment records its applied factors.
            **({"skill_multipliers": skill_multipliers_applied} if skill_multipliers_applied else {}),
            # Provenance only — the deterministic re-pool does NOT derive its
            # number from siblings, so cross_refs are advisory.
            **({"cross_refs": cross_refs} if (cross_refs := ledger.build_cross_refs(question_id, advisory_only=True)) else {}),
        },
    )
    return {
        **preview,
        "status": "committed",
        "committed": snapshot.__dict__,
        "forecast_id": snapshot.forecast_id,
        "model_run": model_run,
        "new_evidence_ids": new_evidence_ids,
        "message": None,
    }


def _refresh_source_keys(source_type: str, source: str) -> set[str]:
    """The identifiers a fresh reading can match a component / prior
    observation by (same scheme as _derive_trigger_observations)."""
    keys = {source.strip().lower(), f"{source_type}:{source}".strip().lower()}
    keys.discard("")
    return keys


def _refresh_reading_value(ledger, item: dict[str, Any]) -> float | None:
    """Extract the latest numeric reading from an adapter item (the same
    canonical keys the trigger evaluator reads)."""
    for key in ledger._TRIGGER_VALUE_KEYS:
        raw = item.get(key)
        if raw is None or isinstance(raw, bool):
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return None


def _apply_fresh_market_probabilities(
    ledger, components: dict[str, Any], fresh_readings: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[str]]:
    """Update each prior component's probability with a freshly-fetched
    market/crowd reading that matches it. ``fresh_readings`` is a list of
    ``{"keys": set[str], "probability": float, "label": str}``. Returns
    ``{"rows", "diff_components", "matched"}`` and the list of reading
    labels that did not match any component."""
    raw_rows = (
        list(components.get("components"))
        if isinstance(components.get("components"), list)
        else [
            {"name": name, **(value if isinstance(value, dict) else {"probability": value})}
            for name, value in (components or {}).items()
        ]
    )
    rows: list[dict[str, Any]] = []
    diff_components: list[dict[str, Any]] = []
    matched_labels: set[str] = set()
    for index, raw in enumerate(raw_rows, start=1):
        if not isinstance(raw, dict):
            continue
        prior_p = ledger._numeric_probability(raw.get("probability"))
        weight = ledger._numeric_probability(raw.get("weight", 1.0))
        if prior_p is None or weight is None or weight < 0:
            continue
        name = str(raw.get("name") or raw.get("source") or f"component_{index}")
        identity = {str(raw.get("source") or "").lower(), name.lower()}
        identity.discard("")
        new_p = prior_p
        for reading in fresh_readings:
            keys = reading["keys"]
            if keys & identity or any(
                key in token or token in key for key in keys for token in identity
            ):
                new_p = reading["probability"]
                matched_labels.add(reading["label"])
                break
        # Preserve every original component key (esp. `source`) so the
        # component stays matchable on the NEXT refresh; only the probability
        # is overwritten. combine_forecasts ignores the extra keys.
        row = dict(raw)
        row["name"] = name
        row["probability"] = new_p
        row["weight"] = weight
        rows.append(row)
        diff_components.append(
            {"name": name, "previous_p": prior_p, "current_p": new_p, "weight": weight}
        )
    unmatched = sorted({r["label"] for r in fresh_readings} - matched_labels)
    return {"rows": rows, "diff_components": diff_components, "matched": sorted(matched_labels)}, unmatched


def _default_refresh_rationale(
    *,
    changed_readings: list[dict[str, Any]],
    unmatched_sources: list[str],
    new_prob: Any,
    prior_prob: Any,
    re_estimate: str,
    needs_agent: bool,
) -> str:
    sources = ", ".join(
        sorted({f"{r['source_type']}:{r['source']}" for r in changed_readings})
    ) or "no changed readings"
    if re_estimate == "deterministic":
        head = (
            f"Automated refresh: re-pooled components after refreshing {sources}. "
            f"Probability {prior_prob} -> {new_prob}."
        )
    else:
        head = (
            f"Automated refresh: imported fresh readings from {sources} and carried the prior "
            f"probability {prior_prob} forward"
            + (" — run with --agent for a re-reasoned estimate." if needs_agent else ".")
        )
    if unmatched_sources:
        head += f" Unmatched fresh readings (not wired to a component): {', '.join(unmatched_sources)}."
    return head


def _record_source_snapshot(
    ledger,
    *,
    question_id: str,
    watch: dict[str, Any],
    retrieved_at: str,
    signature: str | None,
    previous_signature: str | None,
    changed: bool,
    status: str,
    error_message: str | None,
    observed_content: Any | None = None,
) -> dict[str, Any]:
    snapshot_id = f"ss_{uuid.uuid4().hex[:12]}"
    parsed_values = {
        "signature": signature,
        "previous_signature": previous_signature,
        "changed": changed,
        "parser_version": "changed-items-v1",
    }
    with ledger._connect() as conn:
        prior_row = conn.execute(
            """
            SELECT parsed_values FROM source_snapshots
            WHERE watched_source_id = ? ORDER BY retrieved_at DESC, rowid DESC LIMIT 1
            """,
            (watch["id"],),
        ).fetchone()
        prior_values = json_loads(prior_row["parsed_values"], {}) if prior_row else {}
        changed_items = _immutable_changed_items(
            observed_content,
            prior_values.get("observation_payload"),
            observed_at=retrieved_at,
        )
        parsed_values["observation_payload"] = observed_content
        parsed_values["changed_items"] = changed_items
        parsed_values["content_available"] = bool(changed_items)
        conn.execute(
            """
            INSERT INTO source_snapshots (
                id, question_id, watched_source_id, source_type, source_url,
                retrieved_at, raw_payload_sha256, parsed_values,
                adapter_version, status, error_message, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                question_id,
                watch["id"],
                watch["source_type"],
                watch["source"],
                retrieved_at,
                signature,
                json_dumps(parsed_values),
                f"{watch['source_type']}-watch-v1",
                status,
                error_message,
                json_dumps(
                    {
                        "autopilot_policy_id": watch.get("metadata", {}).get("autopilot_policy_id"),
                        "required": bool((watch.get("metadata") or {}).get("required")),
                    }
                ),
            ),
        )
    return ledger.list_source_snapshots(watched_source_id=watch["id"], limit=1)[0]


def _immutable_changed_items(
    current: Any,
    previous: Any,
    *,
    observed_at: str,
) -> list[dict[str, Any]]:
    """Produce reviewable item-level deltas from the payload used for hashing."""

    def rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            value = value["items"]
        elif isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value[:50] if isinstance(item, dict)]

    def identity(item: dict[str, Any]) -> str:
        return str(
            item.get("entry_id")
            or item.get("id")
            or item.get("canonical_url")
            or item.get("url")
            or item.get("title")
            or ""
        )

    def value(item: dict[str, Any]) -> Any:
        for key in (
            "value",
            "probability",
            "current_price",
            "close_price",
            "pct",
            "status",
            "title",
            "summary",
        ):
            if item.get(key) not in (None, ""):
                return item[key]
        return item

    previous_by_id = {identity(item): item for item in rows(previous) if identity(item)}
    changed: list[dict[str, Any]] = []
    for item in rows(current):
        item_id = identity(item)
        prior = previous_by_id.get(item_id)
        serialized = json_dumps(item)
        if prior is not None and json_dumps(prior) == serialized:
            continue
        changed.append(
            {
                "entry_id": item.get("entry_id") or item.get("id") or item_id,
                "headline": item.get("headline") or item.get("title"),
                "published_at": item.get("published_at") or item.get("created_at"),
                "canonical_url": item.get("canonical_url") or item.get("url"),
                "summary": item.get("summary")
                or item.get("description")
                or item.get("claim")
                or item.get("text"),
                "old_value": value(prior) if prior is not None else None,
                "new_value": value(item),
                "content_hash": hashlib.sha256(serialized.encode()).hexdigest(),
                "source_observation_time": observed_at,
                "raw": item,
            }
        )
    return changed


def list_source_snapshots(
    ledger,
    *,
    question_id: str | None = None,
    watched_source_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if watched_source_id:
        clauses.append("watched_source_id = ?")
        params.append(watched_source_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit), 1))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM source_snapshots
            {where}
            ORDER BY retrieved_at DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [ledger._row_to_source_snapshot(row) for row in rows]


def _row_to_source_snapshot(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["parsed_values"] = json_loads(data["parsed_values"], {})
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def check_update_triggers(
    ledger,
    *,
    question_id: str,
    observations: dict[str, Any] | None = None,
    now: str | None = None,
) -> list[AlertEvent]:
    """Evaluate a question's executable update_triggers against imported
    values and emit (idempotent) ``trigger_fired`` alerts. ``observations``
    (source_ref -> value) overrides values derived from imported evidence."""
    question = ledger.get_question(question_id)
    merged = dict(ledger._derive_trigger_observations(question_id))
    for key, value in (observations or {}).items():
        merged[str(key)] = value
    fired = evaluate_update_triggers(question.update_triggers, merged)
    if not fired:
        return []
    open_reasons = {
        alert.reason
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.scope_type == "question" and alert.scope_ref == question_id
    }
    alerts: list[AlertEvent] = []
    for entry in fired:
        reason = f"trigger_fired:{entry['source_ref']}"
        if reason in open_reasons:
            continue  # one open alert per source until acknowledged
        alerts.append(
            ledger.create_alert(
                severity="warning",
                scope_type="question",
                scope_ref=question_id,
                reason=reason,
                recommended_action=(
                    f"Update trigger fired: {entry['mechanism']} "
                    f"({entry['source_ref']} {entry['operator']} {entry['threshold']}; "
                    f"observed {entry['observed']}). Re-run the forecast: "
                    f"`forecast pipeline {question_id} --stage update`."
                ),
            )
        )
    return alerts


def _derive_trigger_observations(ledger, question_id: str) -> dict[str, float]:
    """Best-effort map of source_ref -> latest numeric value, derived from the
    question's imported evidence. The newest evidence per source wins. Used
    when the caller does not supply observations explicitly."""
    latest: dict[str, tuple[str, float]] = {}
    for evidence in ledger.list_evidence(question_id):
        meta = evidence.metadata or {}
        item = meta.get("adapter_item")
        if not isinstance(item, dict):
            continue
        value: float | None = None
        for key in ledger._TRIGGER_VALUE_KEYS:
            raw = item.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                value = float(raw)
                break
            except (TypeError, ValueError):
                continue
        if value is None:
            continue
        adapter = meta.get("adapter")
        source = meta.get("source")
        keys = set()
        if source:
            keys.add(str(source))
            if adapter:
                keys.add(f"{adapter}:{source}")
        if meta.get("source_ref"):
            keys.add(str(meta["source_ref"]))
        # Rank by the OBSERVATION date, not the import time: a single batch
        # import stamps every observation in a series with the same
        # available_at, so using available_at would pick an arbitrary
        # mid-series reading (e.g. a stale peak) instead of the latest
        # observation. entry_id ("DCOILWTICO:2026-05-18") and
        # observation_date carry the real series date; fall back to
        # available_at for sources that have neither.
        entry_id = str(meta.get("entry_id") or "")
        obs_date = str(item.get("observation_date") or item.get("date") or "")
        entry_suffix = entry_id.split(":", 1)[1] if ":" in entry_id else ""
        stamp = obs_date or entry_suffix or evidence.available_at or evidence.captured_at or ""
        for key in keys:
            if key not in latest or stamp >= latest[key][0]:
                latest[key] = (stamp, value)
    return {key: value for key, (_, value) in latest.items()}
