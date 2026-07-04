"""Question domain (D2 carve — CRUD + spec-quality + per-forecast config).

Carved verbatim out of ``forecasting/ledger/core.py``: the question lifecycle
(create / get / list / rename), decision-card + per-forecast settings
(cadence / hooks) update and resolution, scoreability validation, the row->
``ForecastQuestion`` reader and its dict serializer, plus the ``_GATE_LABELS``
map the settings modal resolves against. Each function takes the
``ForecastLedger`` instance as its first argument; ``ForecastLedger`` keeps
one-line delegates so no caller changed.

Dependency direction (no cycle, per the D1 finding): this leaf owns
``_GATE_LABELS`` and imports only ``forecasting.models`` + stdlib at load time.
The sole ``core`` dependency — the module-level write gate ``_enforce_write_gate``
(create_question is a gated write) — is reached via the module handle ``_core``
at CALL time, so importing ``core`` here binds a (possibly partial) module object
without touching its attributes during load.
"""

from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import timedelta
from typing import Any

from forecasting.ledger import core as _core
from forecasting.models import (
    QUESTION_STATUSES,
    ForecastQuestion,
    LedgerNotFoundError,
    OutcomeSpace,
    ValidationError,
    json_dumps,
    json_loads,
    normalize_update_triggers,
    parse_timestamp,
    question_decision_readiness_issues,
    timestamp_to_datetime,
    utc_now_iso,
)


# Friendly labels for the built-in hook gates, surfaced in the per-forecast
# settings modal (resolve_question_config). A missing id falls back to a
# title-cased rule id, so this never has to enumerate every future gate.
_GATE_LABELS: dict[str, str] = {
    "require_structured_reasoning": "Structured reasoning (up/down/change-my-mind)",
    "require_components": "Ensemble decomposition",
    "require_fresh_evidence": "Fresh evidence on re-run",
    "stale_evidence_justified": "Stale-evidence reason recorded",
    "require_decision_readiness": "Decision card complete",
    "require_panel": "Deliberative panel",
    "require_citations": "Citations attached",
    "require_evidence": "At least one evidence record",
    "require_outside_view_anchor": "Outside-view anchor (reference class)",
    "require_outcome_paths": "Named path for each outcome",
    "style_clean": "House style (no em-dashes)",
    "lessons_applied": "Active calibration lessons applied",
    "output_renderable": "Distribution renderable",
    "uncertainty_well_formed": "Interval bounds well-formed",
    "uncertainty_width_sane": "Interval width sane",
    "quorum_participation": "Enough panel/quorum perspectives",
    "quorum_required": "Panel/quorum actually ran",
    "quorum_judged": "Quorum judge synthesis",
    "tails_justified": "No-path tails justified",
    "calibration_bias_applied": "Calibration bias correction",
    "confidence_committed": "Committed (not a coin flip)",
    "reasoning_composition": "Reasoning method breadth",
    "thesis_aggregate_fresh": "Thesis aggregate fresh",
}


def create_question(
    ledger,
    *,
    title: str,
    resolution_criteria: str,
    outcome_space: OutcomeSpace | None = None,
    description: str = "",
    resolution_source: str | None = None,
    close_time: str | None = None,
    resolution_time: str | None = None,
    tags: list[str] | None = None,
    domain: str | None = None,
    topics: list[str] | None = None,
    owner: str | None = None,
    impact: str | None = None,
    review_cadence: str | None = None,
    next_review_at: str | None = None,
    metadata: dict[str, Any] | None = None,
    decision_owner: str | None = None,
    decision_deadline: str | None = None,
    action_threshold: str | None = None,
    update_triggers: Any = None,
) -> ForecastQuestion:
    _core._enforce_write_gate("create_question")
    title = title.strip()
    resolution_criteria = resolution_criteria.strip()
    if not title:
        raise ValidationError("forecast title is required")
    if not resolution_criteria:
        raise ValidationError("resolution criteria are required")

    outcome = outcome_space or OutcomeSpace()
    outcome.validate()
    scoreability_issues = ledger._scoreability_issues(title, resolution_criteria, outcome)
    if scoreability_issues:
        raise ValidationError(
            "ambiguous or unscoreable forecast question: " + "; ".join(scoreability_issues)
        )
    created_at = utc_now_iso()
    question_id = f"fq_{uuid.uuid4().hex[:12]}"
    parsed_next_review_at = parse_timestamp(next_review_at, field_name="next_review_at")
    parsed_decision_deadline = parse_timestamp(decision_deadline, field_name="decision_deadline")
    normalized_decision_owner = (decision_owner or "").strip() or None
    normalized_action_threshold = (action_threshold or "").strip() or None
    normalized_triggers = normalize_update_triggers(update_triggers)
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO forecast_questions (
                id, title, description, resolution_criteria, resolution_source,
                created_at, close_time, resolution_time, outcome_space, status,
                tags, domain, topics, owner, impact, review_cadence,
                next_review_at, metadata,
                decision_owner, decision_deadline, action_threshold, update_triggers
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_id,
                title,
                description,
                resolution_criteria,
                resolution_source,
                created_at,
                parse_timestamp(close_time, field_name="close_time"),
                parse_timestamp(resolution_time, field_name="resolution_time"),
                outcome.to_json(),
                json_dumps(tags or []),
                domain,
                json_dumps(topics or []),
                owner,
                impact,
                review_cadence,
                parsed_next_review_at,
                json_dumps(metadata or {}),
                normalized_decision_owner,
                parsed_decision_deadline,
                normalized_action_threshold,
                json_dumps(normalized_triggers),
            ),
        )
    # Default a weekly scheduled review for eligible LIVE questions. Without
    # this, a live question created without a cadence never gets a scheduled
    # review, so it is never auto-re-forecast and shows a blank desk "NEXT"
    # column. An explicitly-passed review_cadence/next_review_at is respected
    # unchanged; only ABSENT values are filled in. Benchmark/foreknowledge-proof
    # questions (market_nightly, forecastbench) stay cadence-less so they are not
    # re-forecast — see _is_auto_review_eligible.
    if not review_cadence and ledger._is_auto_review_eligible(domain, tags):
        review_cadence = "weekly"
        if not parsed_next_review_at:
            parsed_next_review_at = (
                timestamp_to_datetime(created_at) + timedelta(days=7)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
    if review_cadence and parsed_next_review_at:
        ledger.schedule_review(
            scope_type="question",
            scope_ref=question_id,
            cadence=review_cadence,
            next_run_at=parsed_next_review_at,
            trigger_reason="question_review_cadence",
        )
    return ledger.get_question(question_id)


def list_questions(
    ledger,
    *,
    status: str | None = None,
    domain: str | None = None,
    limit: int | None = None,
) -> list[ForecastQuestion]:
    if status and status not in QUESTION_STATUSES:
        raise ValidationError(f"status must be one of {', '.join(sorted(QUESTION_STATUSES))}")
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM forecast_questions {where} ORDER BY created_at DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with ledger._connect() as conn:
        return [ledger._row_to_question(row) for row in conn.execute(sql, params).fetchall()]


def get_question(ledger, question_id: str) -> ForecastQuestion:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM forecast_questions WHERE id = ?", (question_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"forecast question not found: {question_id}")
    return ledger._row_to_question(row)


def update_question_decision(
    ledger,
    question_id: str,
    *,
    decision_owner: str | None = None,
    decision_deadline: str | None = None,
    action_threshold: str | None = None,
    update_triggers: Any = None,
) -> ForecastQuestion:
    """Patch decision-card fields on an existing question.

    Pass ``None`` to leave a field untouched, an empty string to clear it.
    ``update_triggers`` is normalized through :func:`normalize_update_triggers`;
    pass ``[]`` to clear the list.
    """

    existing = ledger.get_question(question_id)
    sets: list[str] = []
    params: list[Any] = []
    if decision_owner is not None:
        value = decision_owner.strip() or None
        sets.append("decision_owner = ?")
        params.append(value)
    if decision_deadline is not None:
        value = parse_timestamp(decision_deadline, field_name="decision_deadline") if decision_deadline else None
        sets.append("decision_deadline = ?")
        params.append(value)
    if action_threshold is not None:
        value = action_threshold.strip() or None
        sets.append("action_threshold = ?")
        params.append(value)
    if update_triggers is not None:
        normalized = normalize_update_triggers(update_triggers)
        sets.append("update_triggers = ?")
        params.append(json_dumps(normalized))
    if not sets:
        return existing
    params.append(question_id)
    with ledger._connect() as conn:
        conn.execute(
            f"UPDATE forecast_questions SET {', '.join(sets)} WHERE id = ?",
            params,
        )
    return ledger.get_question(question_id)


def update_question_config(
    ledger,
    question_id: str,
    *,
    review_cadence: str | None = None,
    decision: dict[str, Any] | None = None,
    hooks: dict[str, Any] | None = None,
) -> ForecastQuestion:
    """Patch the per-forecast settings the desk's settings modal owns, ATOMICALLY:

    * ``review_cadence`` — validated against the cadence grammar (``_cadence_delta``)
      and, when changed, the live per-question scheduled review is re-armed at the
      new cadence (reusing :meth:`schedule_review`), so the desk's NEXT column reflects
      it. Pass ``""`` to clear the cadence (and disable any per-question schedule).
    * ``decision`` — optional ``{decision_owner, decision_deadline, action_threshold,
      update_triggers}`` delegated to :meth:`update_question_decision` (same None=leave
      / ""=clear semantics).
    * ``hooks`` — optional ``{profile, overrides, thresholds}`` merged into
      ``question.metadata['forecast_hooks']``. ``overrides`` is a gate->severity map
      (validated to the allowed severities; ``lesson:*`` ids are NOT writable here so
      the engine's non-demotable floor can't be re-opened at the config layer);
      ``thresholds`` is a key->number map validated + clamped to the registry's sane
      ranges. Pass an empty dict for a sub-key to clear it.
    """
    existing = ledger.get_question(question_id)

    # ── VALIDATE everything up front, BEFORE any write, so a bad value in one
    #    field can never leave another field half-committed (true to the
    #    "ATOMICALLY" contract: all three inputs are vetted, then applied). ──
    if decision:
        allowed = {"decision_owner", "decision_deadline", "action_threshold", "update_triggers"}
        unknown = set(decision) - allowed
        if unknown:
            raise ValidationError(f"unknown decision field(s): {', '.join(sorted(unknown))}")

    hooks_meta: dict[str, Any] | None = None
    if hooks is not None:
        if not isinstance(hooks, dict):
            raise ValidationError("hooks config must be an object")
        unknown = set(hooks) - {"profile", "overrides", "thresholds", "auto_aggregate"}
        if unknown:
            raise ValidationError(f"unknown hooks field(s): {', '.join(sorted(unknown))}")
        meta = dict(existing.metadata) if isinstance(existing.metadata, dict) else {}
        fh = dict(meta.get("forecast_hooks") or {})
        if "profile" in hooks:
            fh.update(ledger._validate_hook_profile_patch(hooks["profile"]))
        if "auto_aggregate" in hooks:
            fh["auto_aggregate"] = bool(hooks["auto_aggregate"])
        if "overrides" in hooks:
            fh["overrides"] = ledger._validate_hook_overrides(hooks["overrides"])
        if "thresholds" in hooks:
            from forecasting.hooks.thresholds import normalize_thresholds

            fh["thresholds"] = normalize_thresholds(hooks["thresholds"])
        # prune empty sub-maps so a cleared config doesn't linger
        for key in ("overrides", "thresholds"):
            if key in fh and not fh[key]:
                fh.pop(key)
        if fh:
            meta["forecast_hooks"] = fh
        else:
            meta.pop("forecast_hooks", None)
        hooks_meta = meta

    cadence_set = review_cadence is not None
    cadence_clean = review_cadence.strip() if cadence_set else None
    if cadence_clean and not ledger._cadence_is_valid(cadence_clean):
        # a bad string would silently fall back to daily — reject it up front.
        raise ValidationError(
            f"unrecognized review cadence '{cadence_clean}' — use daily/weekly, "
            "'every 2 weeks', '3d', '12h', etc."
        )

    # ── APPLY (every input above is now validated) ──
    if decision:
        ledger.update_question_decision(question_id, **{k: decision[k] for k in decision})
    if hooks_meta is not None:
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
                (json_dumps(hooks_meta), question_id),
            )
    if cadence_set:
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE forecast_questions SET review_cadence = ? WHERE id = ?",
                (cadence_clean or None, question_id),
            )
        ledger._rearm_question_cadence(question_id, cadence_clean or None)

    return ledger.get_question(question_id)


def _cadence_is_valid(ledger, cadence: str) -> bool:
    """True when ``cadence`` is in the vocabulary :meth:`_cadence_delta` knows
    (so we reject typos instead of silently defaulting to daily)."""
    raw = re.sub(r"\s+", " ", cadence.strip().lower())
    if raw.startswith("every "):
        raw = raw[len("every "):].strip()
    if raw in {"daily", "1d", "weekly", "1w", "hourly", "minutely"}:
        return True
    return bool(re.fullmatch(
        r"(?P<count>\d*)\s*(?P<unit>w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes)",
        raw,
    ))


def _rearm_question_cadence(ledger, question_id: str, cadence: str | None) -> None:
    """Re-arm (or disable) the live per-question scheduled review so the NEXT
    column tracks a cadence change. Reuses :meth:`schedule_review`'s re-arm path:
    an existing per-question schedule is advanced to ``now + cadence``; if none
    exists, one is created. Clearing the cadence disables existing schedules."""
    with ledger._connect() as conn:
        existing = conn.execute(
            "SELECT id FROM scheduled_reviews WHERE scope_type = 'question' AND scope_ref = ?",
            (question_id,),
        ).fetchall()
    if not cadence:
        if existing:
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE scheduled_reviews SET enabled = 0 "
                    "WHERE scope_type = 'question' AND scope_ref = ?",
                    (question_id,),
                )
        return
    next_run_at = ledger._advance_cadence(utc_now_iso(), cadence)
    if existing:
        with ledger._connect() as conn:
            conn.execute(
                "UPDATE scheduled_reviews SET cadence = ?, next_run_at = ?, enabled = 1 "
                "WHERE scope_type = 'question' AND scope_ref = ?",
                (cadence, next_run_at, question_id),
            )
        return
    ledger.schedule_review(
        scope_type="question",
        scope_ref=question_id,
        cadence=cadence,
        next_run_at=next_run_at,
        trigger_reason="question_review_cadence",
    )


def _validate_hook_profile_patch(ledger, profile: Any) -> dict[str, Any]:
    from forecasting.hooks.profiles import HOOK_PROFILES

    if profile in (None, ""):
        return {"profile": None}
    name = str(profile).strip()
    if name not in HOOK_PROFILES:
        raise ValidationError(
            f"unknown hook profile '{name}' — choose one of {', '.join(sorted(HOOK_PROFILES))}"
        )
    return {"profile": name}


def _validate_hook_overrides(ledger, overrides: Any) -> dict[str, str]:
    """Coerce a gate->severity map to the allowed vocabulary. Unknown rule ids
    and ``lesson:*`` ids are rejected (the latter must stay non-demotable)."""
    from forecasting.hooks.builtins import BUILTIN_RULE_IDS
    from forecasting.hooks.spec import Severity

    if not isinstance(overrides, dict):
        raise ValidationError("hook overrides must be an object of gate -> severity")
    allowed_ids = set(BUILTIN_RULE_IDS)
    out: dict[str, str] = {}
    for rule_id, sev in overrides.items():
        rid = str(rule_id)
        if rid.startswith("lesson:"):
            raise ValidationError(
                f"calibration-lesson rule '{rid}' cannot be re-severitied per-forecast "
                "(it enforces a paid-for miss and must stay non-demotable)"
            )
        if rid not in allowed_ids:
            raise ValidationError(f"unknown hook gate '{rid}'")
        try:
            value = Severity(str(sev).strip().lower())
        except Exception:
            raise ValidationError(
                f"severity for '{rid}' must be one of off/warn/error (got {sev!r})"
            )
        out[rid] = value.value
    return out


def resolve_question_config(ledger, question_id: str) -> dict[str, Any]:
    """Resolve the full per-forecast settings for the desk's settings modal:
    ``{question_id, title, cadence, next_run_at, decision, gates[], thresholds[]}``.

    ``gates`` lists EVERY built-in gate with its resolved severity + source
    ('profile' when it comes from the active profile, 'override' when a
    per-question override set it). ``thresholds`` lists every tunable
    minimum-requirement with its current value, the standard default, and a
    ``looser`` flag (+ source) so an override that RELAXES a requirement is
    visible, never silent. ``lesson:*`` gates are excluded (not user-editable)."""
    from forecasting.hooks.builtins import BUILTIN_RULES, RULE_DOCS
    from forecasting.hooks.engine import load_hook_config
    from forecasting.hooks.profiles import (
        DEFAULT_PROFILE,
        profile_severities,
        resolve_reasoning_requirement,
    )
    from forecasting.hooks.spec import Severity
    from forecasting.hooks.thresholds import THRESHOLD_SPECS, normalize_thresholds

    question = ledger.get_question(question_id)
    meta = question.metadata if isinstance(question.metadata, dict) else {}
    fh = meta.get("forecast_hooks") or {}
    hooks_config = load_hook_config()

    active_profile = fh.get("profile") or hooks_config.get("profile") or DEFAULT_PROFILE
    profile_sev = profile_severities(active_profile)
    standard_sev = profile_severities("standard")
    overrides = fh.get("overrides") or {}

    # severity strictness ladder for the looser-than-standard flag.
    _rank = {Severity.OFF: 0, Severity.WARN: 1, Severity.ERROR: 2}

    gates: list[dict[str, Any]] = []
    for rule in BUILTIN_RULES:
        base = profile_sev.get(rule.id, rule.default_severity)
        ov = overrides.get(rule.id)
        if ov is not None:
            try:
                sev = Severity(str(ov).strip().lower())
                source = "override"
            except Exception:
                sev, source = base, "profile"
        else:
            sev, source = base, "profile"
        std = standard_sev.get(rule.id, rule.default_severity)
        looser = _rank[sev] < _rank[std]
        gates.append({
            "id": rule.id,
            "label": _GATE_LABELS.get(rule.id, rule.id.replace("_", " ")),
            "doc": RULE_DOCS.get(rule.id, ""),
            "category": rule.category.value,
            "severity": sev.value,
            "default": std.value,
            "source": source,
            "looser": looser,
        })

    # thresholds: resolved value + the TRUE baseline + looser flag. Most
    # thresholds baseline at their static spec default, but min_reasoning_methods'
    # real floor is the active profile's reasoning requirement (3 standard / 5
    # strict), NOT the spec's placeholder 0 — otherwise a genuine loosening of a
    # potentially-blocking gate would read as "stricter" and hide.
    _, profile_min_methods = resolve_reasoning_requirement(active_profile)
    thr_over = normalize_thresholds(fh.get("thresholds"))
    thresholds: list[dict[str, Any]] = []
    for spec in THRESHOLD_SPECS:
        has_override = spec.key in thr_over
        baseline = (
            float(profile_min_methods)
            if spec.key == "min_reasoning_methods"
            else float(spec.default)
        )
        value = thr_over.get(spec.key, baseline)
        looser = bool(
            has_override
            and (
                float(value) < baseline
                if spec.direction == "lower_looser"
                else float(value) > baseline
            )
        )
        thresholds.append({
            "key": spec.key,
            "label": spec.label,
            "help": spec.help,
            "value": value,
            "default": baseline,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "integer": spec.integer,
            "direction": spec.direction,
            "rule_ids": list(spec.rule_ids),
            "source": "override" if has_override else "default",
            "looser": looser,
        })

    live = ledger.next_review_by_question().get(question_id) or {}
    return {
        "question_id": question_id,
        "title": question.title,
        "impact": question.impact,
        "profile": active_profile,
        "cadence": question.review_cadence,
        "next_run_at": live.get("next_run_at"),
        "decision": {
            "decision_owner": question.decision_owner,
            "decision_deadline": question.decision_deadline,
            "action_threshold": question.action_threshold,
            "update_triggers": list(question.update_triggers or []),
        },
        "gates": gates,
        "thresholds": thresholds,
    }


def rename_question(ledger, question_id: str, new_title: str, *, actor: str | None = None) -> ForecastQuestion:
    """Rename a question's display title — the only identity field safe to edit in place
    (id/snapshots/scores/lessons/cross-refs all key off the id, never the title).

    Re-runs the generic-title scoreability check on the NEW title (only the title, so a
    pre-existing criteria gap can't block a clarifying rename), and records the prior
    title in metadata['title_history'] for an audit trail. Scoreability-defining fields
    (resolution_criteria, outcome_space) are intentionally NOT editable here — changing
    them after snapshots exist would retroactively invalidate committed forecasts.
    """
    existing = ledger.get_question(question_id)
    title = (new_title or "").strip()
    if not title:
        raise ValidationError("new title must not be empty")
    if title == existing.title:
        return existing
    issues = ledger._scoreability_issues(title, existing.resolution_criteria, existing.outcome_space)
    title_issues = [i for i in issues if "title" in i.lower()]
    if title_issues:
        raise ValidationError("; ".join(title_issues))
    meta = dict(existing.metadata) if isinstance(existing.metadata, dict) else {}
    history = list(meta.get("title_history") or [])
    history.append({
        "old": existing.title,
        "new": title,
        "at": utc_now_iso(),
        "actor": (actor or "").strip() or None,
    })
    meta["title_history"] = history
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_questions SET title = ?, metadata = ? WHERE id = ?",
            (title, json_dumps(meta), question_id),
        )
    return ledger.get_question(question_id)


def decision_readiness_issues(ledger, question: ForecastQuestion | str) -> list[str]:
    """Return decision-card gaps for ``question`` (id or object)."""

    if isinstance(question, str):
        question = ledger.get_question(question)
    return question_decision_readiness_issues(question)


def _scoreability_issues(
    ledger,
    title: str,
    resolution_criteria: str,
    outcome_space: OutcomeSpace,
) -> list[str]:
    issues: list[str] = []
    criteria = resolution_criteria.strip().lower()
    title_lower = title.strip().lower()
    vague_markers = (
        r"\btbd\b",
        r"\btodo\b",
        r"\bunknown\b",
        r"\bunclear\b",
        r"\bnot\s+sure\b",
        r"\bto\s+be\s+decided\b",
        r"\bfigure\s+out\s+later\b",
    )
    if any(re.search(marker, criteria) for marker in vague_markers):
        issues.append("resolution criteria contain placeholder or vague language")
    if criteria in {"yes", "no", "maybe", "n/a", "na"}:
        issues.append("resolution criteria are too short to audit")
    if len(criteria.split()) < 5:
        issues.append("resolution criteria need an auditable condition")
    if outcome_space.type in {"numeric", "distribution"} and not outcome_space.units:
        issues.append("numeric or distributional forecasts need units")
    if outcome_space.type == "categorical" and len({choice.lower() for choice in outcome_space.choices}) != len(outcome_space.choices):
        issues.append("categorical outcome choices must be unique")
    if title_lower in {"will it happen?", "what will happen?", "forecast"}:
        issues.append("title is too generic")
    return issues


def _row_to_question(ledger, row: sqlite3.Row) -> ForecastQuestion:
    row_keys = row.keys()
    return ForecastQuestion(
        id=row["id"],
        title=row["title"],
        description=row["description"],
        resolution_criteria=row["resolution_criteria"],
        resolution_source=row["resolution_source"],
        created_at=row["created_at"],
        close_time=row["close_time"],
        resolution_time=row["resolution_time"],
        outcome_space=OutcomeSpace.from_json(row["outcome_space"]),
        status=row["status"],
        tags=json_loads(row["tags"], []),
        domain=row["domain"],
        topics=json_loads(row["topics"], []),
        owner=row["owner"],
        impact=row["impact"],
        review_cadence=row["review_cadence"],
        next_review_at=row["next_review_at"],
        current_forecast_id=row["current_forecast_id"],
        metadata=json_loads(row["metadata"], {}),
        decision_owner=row["decision_owner"] if "decision_owner" in row_keys else None,
        decision_deadline=row["decision_deadline"] if "decision_deadline" in row_keys else None,
        action_threshold=row["action_threshold"] if "action_threshold" in row_keys else None,
        update_triggers=(
            json_loads(row["update_triggers"], []) if "update_triggers" in row_keys else []
        ),
    )


def _question_to_dict(ledger, question: ForecastQuestion) -> dict[str, Any]:
    data = question.__dict__.copy()
    data["outcome_space"] = question.outcome_space.to_dict()
    return data
