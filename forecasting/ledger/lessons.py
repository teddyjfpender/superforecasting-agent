"""Calibration-lesson + error-profile domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns two learning-side table families:

* CALIBRATION LESSONS: the lesson CRUD (``create_calibration_lesson`` /
  ``get_`` / ``update_`` / ``apply_lesson`` / ``list_`` / ``_row_to_calibration_lesson``),
  the coverage/correcting-lens readers (``lesson_coverage`` /
  ``calibration_correcting_lessons`` / ``_calibration_lessons_for_question``), and the
  bias-lesson synthesis engine (``synthesize_bias_lessons`` / ``_prior_bias_lessons``
  / ``_apply_bias_disposition``);
* DOMAIN ERROR PROFILES: the profile write+recompute (``update_domain_error_profile``
  / ``_write_error_profile``) with its aggregation helpers (``_postmortems_for_error_profile``
  / ``_error_counts_for_profile`` / ``_recurring_error_tags`` /
  ``_recommended_adjustments_for_errors``), the readers (``get_``/``list_``/
  ``_row_to_domain_error_profile`` / ``_domain_error_profile_id`` /
  ``_domain_error_profiles_for_question``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. Cross-domain reads (scoring,
postmortems, calibration derivation) resolve through the ``ledger`` INSTANCE, so
no sibling leaf is imported here (leaf independence preserved)."""

from __future__ import annotations

from typing import Any
from forecasting.models import CALIBRATION_LESSON_STATUSES
from collections import Counter
from forecasting.models import ForecastQuestion
from forecasting.models import LedgerNotFoundError
from forecasting.models import ScoreRecord
from forecasting.models import ValidationError
from collections import defaultdict
from forecasting.models import json_dumps
from forecasting.models import json_loads
import sqlite3
from forecasting.models import utc_now_iso
import uuid


def _validate_supersession(ledger, lesson_id, supersedes):
    seen = {lesson_id} if lesson_id else set()
    while supersedes:
        if supersedes in seen:
            raise ValidationError("calibration lesson supersession must not contain a cycle")
        seen.add(supersedes)
        supersedes = ledger.get_calibration_lesson(supersedes).get("supersedes_lesson_id")


def create_calibration_lesson(
    ledger,
    *,
    scope_type: str,
    scope_ref: str | None,
    lesson: str,
    confidence: float | None = None,
    recommended_adjustment: dict[str, Any] | None = None,
    source_postmortem_refs: list[str] | None = None,
    source_score_record_refs: list[str] | None = None,
    status: str = "tentative",
    supersedes_lesson_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if scope_type not in {"domain", "topic", "domain_topic", "horizon", "question_type", "model_component", "global"}:
        raise ValidationError("invalid calibration lesson scope_type")
    if scope_type == "domain_topic" and ":" not in (scope_ref or ""):
        # Stored + matched colon-joined ("politics:nyc-primaries"), the form both
        # active_lessons_for_question and lesson_scope_to_applies_to expect.
        raise ValidationError("domain_topic calibration lessons require a 'domain:topic' scope_ref")
    if status not in CALIBRATION_LESSON_STATUSES:
        raise ValidationError(
            f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
        )
    if not lesson.strip():
        raise ValidationError("calibration lesson text is required")
    if confidence is not None and not (0 <= confidence <= 1):
        raise ValidationError("calibration lesson confidence must be between 0 and 1")
    # Lazy-operator hook: a lesson with a recognized enforcement pattern AUTO-
    # compiles to a hook rule at creation (WARN — observe-then-flip), so a learning
    # becomes strict, formal enforcement without anyone hand-authoring a RuleSpec.
    # An explicit `rule` always wins; no recognized pattern leaves it advisory.
    if isinstance(recommended_adjustment, dict) and "rule" not in recommended_adjustment:
        from forecasting.lesson_templates import build_lesson_rule
        _auto_rule = build_lesson_rule({"recommended_adjustment": recommended_adjustment}, severity="warn")
        if _auto_rule is not None:
            recommended_adjustment = {**recommended_adjustment, "rule": _auto_rule}
    # Authoring gate: a lesson that carries an enforceable `rule` must compile.
    # Refuse a broken rule at write time (so it can't silently fail to bite at
    # commit) — the rule's check predicate is validated against the signal DSL.
    _rule = (recommended_adjustment or {}).get("rule") if isinstance(recommended_adjustment, dict) else None
    if isinstance(_rule, dict):
        from forecasting.hooks.dsl import RuleSpec, validate_rule
        _spec = RuleSpec.from_dict({**_rule, "id": "lesson:_validate", "applies_to": {}})
        _rule_errs = [issue for issue in validate_rule(_spec) if issue.severity == "error"]
        if _rule_errs:
            raise ValidationError(f"calibration lesson rule is invalid: {_rule_errs[0].message}")
    _validate_supersession(ledger, None, supersedes_lesson_id)
    now = utc_now_iso()
    lesson_id = f"cl_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO calibration_lessons (
                id, scope_type, scope_ref, created_at, updated_at, status,
                confidence, lesson, recommended_adjustment,
                source_postmortem_refs, source_score_record_refs,
                supersedes_lesson_id, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lesson_id,
                scope_type,
                scope_ref,
                now,
                now,
                status,
                confidence,
                lesson.strip(),
                json_dumps(recommended_adjustment or {}),
                json_dumps(source_postmortem_refs or []),
                json_dumps(source_score_record_refs or []),
                supersedes_lesson_id,
                json_dumps(metadata or {}),
            ),
        )
    return ledger.get_calibration_lesson(lesson_id)


def get_calibration_lesson(ledger, lesson_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM calibration_lessons WHERE id = ?",
            (lesson_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"calibration lesson not found: {lesson_id}")
    return ledger._row_to_calibration_lesson(row)


def update_calibration_lesson(
    ledger,
    lesson_id: str,
    *,
    status: str | None = None,
    confidence: float | None = None,
    recommended_adjustment: dict[str, Any] | None = None,
    supersedes_lesson_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current = ledger.get_calibration_lesson(lesson_id)
    new_status = status or current["status"]
    if new_status not in CALIBRATION_LESSON_STATUSES:
        raise ValidationError(
            f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
        )
    if confidence is not None and not (0 <= confidence <= 1):
        raise ValidationError("calibration lesson confidence must be between 0 and 1")
    # Same authoring gate as create: a `rule` must compile, so an enforceable
    # lesson can never be saved in a broken state that silently fails to bite.
    _rule = (recommended_adjustment or {}).get("rule") if isinstance(recommended_adjustment, dict) else None
    if isinstance(_rule, dict):
        from forecasting.hooks.dsl import RuleSpec, validate_rule
        _spec = RuleSpec.from_dict({**_rule, "id": "lesson:_validate", "applies_to": {}})
        _rule_errs = [issue for issue in validate_rule(_spec) if issue.severity == "error"]
        if _rule_errs:
            raise ValidationError(f"calibration lesson rule is invalid: {_rule_errs[0].message}")
    if current.get("invalidated_by_correction_id") and new_status == "active":
        raise ValidationError("invalidated calibration lessons cannot be activated")
    if supersedes_lesson_id:
        _validate_supersession(ledger, lesson_id, supersedes_lesson_id)
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE calibration_lessons
            SET status = ?, confidence = COALESCE(?, confidence),
                recommended_adjustment = ?,
                supersedes_lesson_id = COALESCE(?, supersedes_lesson_id),
                metadata = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                new_status,
                confidence,
                json_dumps(recommended_adjustment if recommended_adjustment is not None else current["recommended_adjustment"]),
                supersedes_lesson_id,
                json_dumps(metadata if metadata is not None else current["metadata"]),
                utc_now_iso(),
                lesson_id,
            ),
        )
    return ledger.get_calibration_lesson(lesson_id)


def apply_lesson(ledger, lesson_id: str, *, severity: str = "warn") -> dict[str, Any]:
    """Compile a calibration lesson into an enforceable hook rule — the lazy-
    operator path: turn a learning into strict, formal enforcement WITHOUT
    hand-authoring a RuleSpec. Resolves the lesson's enforcement pattern (declared
    or inferred), attaches the built rule to recommended_adjustment['rule']
    (re-validated on update), and returns a summary. No recognized pattern ->
    the lesson stays advisory (reported, never silently no-op). Severity defaults
    to WARN (observe-then-flip)."""
    from forecasting.lesson_templates import build_lesson_rule, resolve_enforcement_pattern
    lesson = ledger.get_calibration_lesson(lesson_id)
    pattern = resolve_enforcement_pattern(lesson.get("recommended_adjustment"))
    rule = build_lesson_rule(lesson, severity=severity)
    if rule is None:
        return {"lesson_id": lesson_id, "applied": False, "pattern": None, "reason": "no enforcement pattern — advisory"}
    adjustment = dict(lesson.get("recommended_adjustment") or {})
    adjustment["rule"] = rule
    ledger.update_calibration_lesson(lesson_id, recommended_adjustment=adjustment)
    return {"lesson_id": lesson_id, "applied": True, "pattern": pattern, "severity": severity, "check": rule["check"]}


def list_calibration_lessons(
    ledger,
    *,
    scope_type: str | None = None,
    scope_ref: str | None = None,
    active_only: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scope_type:
        clauses.append("scope_type = ?")
        params.append(scope_type)
    if scope_ref:
        clauses.append("scope_ref = ?")
        params.append(scope_ref)
    if active_only:
        clauses.append("status = 'active'")
        clauses.append("invalidated_by_correction_id IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM calibration_lessons {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
    return [ledger._row_to_calibration_lesson(row) for row in rows]


def _row_to_calibration_lesson(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["recommended_adjustment"] = json_loads(data["recommended_adjustment"], {})
    data["source_postmortem_refs"] = json_loads(data["source_postmortem_refs"], [])
    data["source_score_record_refs"] = json_loads(data["source_score_record_refs"], [])
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def lesson_coverage(ledger) -> list[dict[str, Any]]:
    """Per active lesson: how often it has been IN SCOPE at a commit since it was
    created, how often applied, and whether it is DORMANT (never encountered) —
    the honest answer to 'is this learning actually being used?'. A dormant or
    rarely-applied lesson is a review trigger, not silently-trusted machinery."""
    now = utc_now_iso()
    out: list[dict[str, Any]] = []
    with ledger._connect() as conn:
        lessons = conn.execute(
            "SELECT id, scope_type, scope_ref, lesson, created_at, recommended_adjustment "
            "FROM calibration_lessons WHERE status = 'active' ORDER BY created_at"
        ).fetchall()
        for row in lessons:
            apps = conn.execute(
                "SELECT a.applied, a.created_at, s.metadata FROM lesson_applications a "
                "LEFT JOIN forecast_snapshots s ON s.forecast_id = a.snapshot_id "
                "WHERE a.lesson_id = ? ORDER BY a.created_at",
                (row["id"],),
            ).fetchall()
            in_scope = len(apps)
            verified = []
            for app in apps:
                decisions = (json_loads(app["metadata"], {}) or {}).get("lesson_decisions", [])
                decision = next((d for d in decisions if d.get("lesson_id") == row["id"]), None)
                if decision is not None:
                    verified.append(decision)
            applied = sum(bool(d.get("applied")) for d in verified)
            last_seen = apps[-1]["created_at"] if apps else None
            recommended = json_loads(row["recommended_adjustment"], {}) or {}
            if isinstance(recommended.get("rule"), dict):
                kind = "rule"
            elif any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")):
                kind = "numeric"
            else:
                kind = "advisory"
            out.append({
                "lesson_id": row["id"],
                "scope": f"{row['scope_type']}:{row['scope_ref'] or '*'}",
                "kind": kind,
                "lesson": (row["lesson"] or "")[:90],
                "in_scope_count": in_scope,
                "applied_count": applied,
                "verified_count": len(verified),
                "unverified_count": in_scope - len(verified),
                "decision_reasons": {reason: sum(d.get("reason") == reason for d in verified)
                                     for reason in sorted({d.get("reason", "unknown") for d in verified})},
                "application_rate": (applied / in_scope) if in_scope else 0.0,
                "last_seen": last_seen,
                "dormant": in_scope == 0,
                "enforceable": kind in ("numeric", "rule"),
            })
    return out


def calibration_correcting_lessons(ledger, *, domain: str | None = None) -> list[dict[str, Any]]:
    """Active calibration lessons CORRECTING forecasts in scope, each carrying
    its ``recommended_adjustment``, its measured ``coverage`` (from
    :meth:`lesson_coverage` — in-scope/applied counts + application rate), and
    whether it is ``dormant`` (never yet encountered at a commit). When
    ``domain`` is given, domain/domain_topic lessons are restricted to that
    domain (global/topic/question_type lessons still apply broadly). The
    plain-language answer to 'which learning is adjusting my numbers here, and
    is it actually biting?'."""
    coverage_by_id = {row["lesson_id"]: row for row in ledger.lesson_coverage()}
    out: list[dict[str, Any]] = []
    for lesson in ledger.list_calibration_lessons(active_only=True):
        scope_type = lesson.get("scope_type")
        scope_ref = lesson.get("scope_ref")
        if domain is not None and scope_type in ("domain", "domain_topic"):
            # domain_topic scope_ref is colon-joined ("politics:nyc-primaries").
            lesson_domain = str(scope_ref or "").split(":", 1)[0]
            if lesson_domain != domain:
                continue
        cov = coverage_by_id.get(lesson["id"], {})
        out.append({
            "lesson_id": lesson["id"],
            "scope": f"{scope_type}:{scope_ref or '*'}",
            "scope_type": scope_type,
            "scope_ref": scope_ref,
            "lesson": lesson.get("lesson"),
            "recommended_adjustment": lesson.get("recommended_adjustment") or {},
            "coverage": {
                "in_scope_count": cov.get("in_scope_count", 0),
                "applied_count": cov.get("applied_count", 0),
                "application_rate": cov.get("application_rate", 0.0),
                "last_seen": cov.get("last_seen"),
            },
            "dormant": cov.get("dormant", True),
        })
    return out


def _calibration_lessons_for_question(
    ledger,
    scores: list[ScoreRecord],
    postmortems: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    score_ids = {score.id for score in scores}
    postmortem_ids = {postmortem["id"] for postmortem in postmortems}
    lessons = []
    for lesson in ledger.list_calibration_lessons():
        if score_ids & set(lesson["source_score_record_refs"]):
            lessons.append(lesson)
        elif postmortem_ids & set(lesson["source_postmortem_refs"]):
            lessons.append(lesson)
    return lessons


def synthesize_bias_lessons(
    ledger,
    *,
    scope: str = "all",
    domains: list[str] | None = None,
    since: str | None = None,
    recency_halflife_days: float | None = None,
    forecast_origin: str | None = "live",
    enable_mechanical: bool = False,
    activate: bool = True,
    dry_run: bool = False,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """Derive calibration-bias lessons across scopes with FDR control.
    Computes a signed-bias report per scope (global + each domain that has
    scored forecasts), shrinks each domain toward the global estimate,
    applies Benjamini-Hochberg across the family, then writes/activates,
    leaves tentative, or retires lessons per :func:`decide_disposition`.
    ``dry_run`` measures and decides without writing. Returns one result
    dict per scope (report payload + disposition + action taken).
    """
    from forecasting.calibration_bias import (
        assess_bias,
        benjamini_hochberg,
        decide_disposition,
    )
    from dataclasses import replace

    # Resolve the scope family.
    targets: list[tuple[str, str | None]] = []
    if scope in ("all", "global"):
        targets.append(("global", None))
    if scope in ("all", "domain"):
        for name in (domains if domains is not None else ledger._domains_with_scores(forecast_origin=forecast_origin)):
            targets.append(("domain", name))
    if scope not in ("all", "global", "domain"):
        targets = [("domain", scope)]
    # Global estimate first — domains shrink toward it (empirical Bayes).
    global_obs = ledger._bias_observations(
        domain=None,
        since=since,
        recency_halflife_days=recency_halflife_days,
        forecast_origin=forecast_origin,
        now=now,
    )
    global_report = assess_bias(global_obs, scope_type="global", scope_ref=None)
    global_prior = global_report.sce_raw or 0.0
    reports = []
    for scope_type, scope_ref in targets:
        observations = ledger._bias_observations(
            domain=scope_ref,
            since=since,
            recency_halflife_days=recency_halflife_days,
            forecast_origin=forecast_origin,
            now=now,
        )
        prior_lessons = ledger._prior_bias_lessons(scope_type, scope_ref)
        prior_scale = None
        if prior_lessons:
            prior_scale = (prior_lessons[0].get("recommended_adjustment") or {}).get("logit_scale")
        report = assess_bias(
            observations,
            scope_type=scope_type,
            scope_ref=scope_ref,
            lesson_free_only=True,
            enable_mechanical=enable_mechanical,
            prior_scale=prior_scale,
            shrink_prior=0.0 if scope_type == "global" else global_prior,
        )
        if scope_type != "global":
            report = replace(report, shrink_prior_score_record_refs=global_report.source_score_record_refs)
        reports.append((report, prior_lessons))
    # Benjamini-Hochberg FDR across the family of detectable scopes.
    pvalues = [rep.pvalue if rep.has_detectable_bias else None for rep, _ in reports]
    survived = benjamini_hochberg(pvalues, q=0.10)
    results: list[dict[str, Any]] = []
    for (report, prior_lessons), bh_ok in zip(reports, survived):
        trajectory = []
        if prior_lessons:
            trajectory = list((prior_lessons[0].get("metadata") or {}).get("sce_trajectory") or [])
        disposition = decide_disposition(report, bh_survived=bh_ok, trajectory=trajectory)
        status = disposition["lesson_status"]
        if not activate and status == "active":
            status = "tentative"
        action = ledger._apply_bias_disposition(
            report,
            status=status,
            trajectory=trajectory,
            prior_lessons=prior_lessons,
            dry_run=dry_run,
        )
        payload = report.to_payload()
        payload["disposition"] = disposition
        payload["bh_survived"] = bh_ok
        payload["action"] = action
        results.append(payload)
    return results


def _prior_bias_lessons(ledger, scope_type: str, scope_ref: str | None) -> list[dict[str, Any]]:
    """Bias-sourced lessons for a scope, newest first (any status)."""
    lessons = ledger.list_calibration_lessons(scope_type=scope_type, scope_ref=scope_ref)
    return [
        lesson
        for lesson in lessons
        if (lesson.get("metadata") or {}).get("source") == ledger._BIAS_LESSON_SOURCE
    ]


def _apply_bias_disposition(
    ledger,
    report: Any,
    *,
    status: str,
    trajectory: list[float],
    prior_lessons: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    """Write/activate, leave tentative, or retire a scope's bias lesson.
    ``none`` retires any prior active lesson (a bias no longer detected must
    not keep influencing forecasts). ``suppressed`` (trajectory diverging)
    also retires and records an audit-only tentative marker. Otherwise a new
    lesson supersedes the prior one — lessons never accumulate.
    """
    active_priors = [lesson for lesson in prior_lessons if lesson.get("status") == "active"]
    if status == "none":
        if dry_run:
            return {"written": False, "retired": [l["id"] for l in active_priors], "status": "none"}
        for lesson in active_priors:
            ledger.update_calibration_lesson(lesson["id"], status="superseded")
        return {"written": False, "retired": [l["id"] for l in active_priors], "status": "none"}
    # Persist the per-scope |SCE| trajectory (capped history) for the guard.
    magnitude = abs(report.sce_shrunk or 0.0)
    new_trajectory = (trajectory + [round(magnitude, 5)])[-8:]
    metadata = {
        "source": ledger._BIAS_LESSON_SOURCE,
        "sce_shrunk": report.sce_shrunk,
        "sce_raw": report.sce_raw,
        "ci": [report.ci_low, report.ci_high],
        "pvalue": report.pvalue,
        "ess": round(report.ess, 3),
        "n": report.n,
        "direction": report.direction,
        "horizon_label": report.horizon_label,
        "sce_trajectory": new_trajectory,
        "suppressed": status == "suppressed",
        "measurement_score_record_refs": report.source_score_record_refs,
        "shrink_prior_score_record_refs": report.shrink_prior_score_record_refs,
    }
    confidence = None
    if report.pvalue is not None:
        confidence = round(min(max(1.0 - report.pvalue, 0.0), 1.0), 3)
    # Suppressed: retire the active lesson and stop pushing; keep a tentative
    # audit marker so the trajectory stays continuous.
    write_status = "tentative" if status == "suppressed" else status
    lesson_text = report.advisory_text or "Calibration bias detected; see metadata."
    if status == "suppressed":
        lesson_text = (
            "[suppressed: bias trajectory diverging across cycles — not pushing further] "
            + lesson_text
        )
    if dry_run:
        return {
            "written": False,
            "would_write_status": write_status,
            "retired": [l["id"] for l in active_priors],
            "status": status,
        }
    supersedes = active_priors[0]["id"] if active_priors else None
    for lesson in active_priors:
        ledger.update_calibration_lesson(lesson["id"], status="superseded")
    created = ledger.create_calibration_lesson(
        scope_type=report.scope_type,
        scope_ref=report.scope_ref,
        lesson=lesson_text,
        confidence=confidence,
        recommended_adjustment=report.recommended_adjustment or {},
        status=write_status,
        supersedes_lesson_id=supersedes,
        source_score_record_refs=sorted(set(
            report.source_score_record_refs + report.shrink_prior_score_record_refs
        )),
        metadata=metadata,
    )
    return {
        "written": True,
        "lesson_id": created["id"],
        "lesson_status": write_status,
        "retired": [l["id"] for l in active_priors],
        "status": status,
    }


def update_domain_error_profile(ledger, question: ForecastQuestion) -> dict[str, Any] | None:
    domain = question.domain
    if not domain:
        return None
    domain_scores = ledger.list_scores(domain=domain, calibration_eligible=True)
    domain_profile = ledger._write_error_profile(
        domain=domain,
        topic=None,
        question_type=question.outcome_space.type,
        scores=domain_scores,
    )
    for topic in question.topics:
        topic_scores = [
            score
            for score in domain_scores
            if topic in ledger.get_question(score.question_id).topics
        ]
        ledger._write_error_profile(
            domain=domain,
            topic=topic,
            question_type=question.outcome_space.type,
            scores=topic_scores,
        )
    return domain_profile


def _write_error_profile(
    ledger,
    *,
    domain: str,
    topic: str | None,
    question_type: str,
    scores: list[ScoreRecord],
) -> dict[str, Any]:
    brier_values = [score.brier_score for score in scores if score.brier_score is not None]
    postmortems = ledger._postmortems_for_error_profile(domain=domain, topic=topic)
    error_counts = ledger._error_counts_for_profile(scores=scores, postmortems=postmortems)
    summary = {
        "count": len(brier_values),
        "mean_brier": sum(brier_values) / len(brier_values) if brier_values else None,
        "postmortem_count": len(postmortems),
        "error_counts": dict(sorted(error_counts.items())),
    }
    recurring_errors: list[str] = []
    if summary["mean_brier"] is not None and summary["mean_brier"] > 0.25:
        recurring_errors.append("elevated_mean_brier")
    recurring_errors.extend(ledger._recurring_error_tags(error_counts))
    recurring_errors = list(dict.fromkeys(recurring_errors))
    recommended_adjustments = ledger._recommended_adjustments_for_errors(recurring_errors)
    sample_count = len(brier_values)
    profile_id = ledger._domain_error_profile_id(domain, topic, None, question_type)
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO domain_error_profiles (
                id, domain, topic, forecast_horizon_bucket, question_type,
                sample_count, calibration_summary, recurring_errors,
                recommended_adjustments, updated_at
            )
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                domain,
                topic,
                question_type,
                sample_count,
                json_dumps(summary),
                json_dumps(recurring_errors),
                json_dumps(recommended_adjustments),
                utc_now_iso(),
            ),
        )
    return ledger.get_domain_error_profile(profile_id)


def _postmortems_for_error_profile(
    ledger,
    *,
    domain: str,
    topic: str | None,
) -> list[dict[str, Any]]:
    scoped: list[dict[str, Any]] = []
    for postmortem in ledger.list_postmortems():
        if not postmortem.get("calibration_eligible"):
            continue
        try:
            question = ledger.get_question(postmortem["question_id"])
        except LedgerNotFoundError:
            continue
        if question.domain != domain:
            continue
        if topic and topic not in question.topics:
            continue
        scoped.append(postmortem)
    return scoped


def _error_counts_for_profile(
    ledger,
    *,
    scores: list[ScoreRecord],
    postmortems: list[dict[str, Any]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    score_tags_by_id: dict[str, set[str]] = defaultdict(set)
    for score in scores:
        if score.brier_score is not None and score.brier_score > 0.25:
            counts["high_brier_miss"] += 1
            score_tags_by_id[score.id].add("high_brier_miss")
        if score.brier_score is not None and score.brier_score >= 0.36:
            try:
                snapshot = ledger.get_snapshot(score.forecast_id)
            except LedgerNotFoundError:
                snapshot = None
            if snapshot is not None:
                sharpness = ledger._sharpness(snapshot.probability_or_distribution)
                if sharpness is not None and sharpness >= 0.6:
                    counts["overconfidence"] += 1
                    score_tags_by_id[score.id].add("overconfidence")
                for model_run_ref in snapshot.model_run_refs:
                    try:
                        model_run = ledger.get_model_run(model_run_ref)
                    except LedgerNotFoundError:
                        continue
                    if model_run["status"] == "failure":
                        counts["model_family_failure"] += 1
    field_tags = {
        "missed_evidence": "missed_evidence",
        "overweighted_evidence": "overweighted_evidence",
        "base_rate_error": "base_rate_error",
        "inside_view_error": "inside_view_error",
        "resolution_error": "resolution_error",
    }
    for postmortem in postmortems:
        for field, tag in field_tags.items():
            if str(postmortem.get(field) or "").strip():
                counts[tag] += 1
        adjustment = postmortem.get("calibration_adjustment") or {}
        if isinstance(adjustment, dict):
            score_id = str(postmortem.get("score_record_id") or "")
            for tag in adjustment.get("error_tags") or []:
                if not isinstance(tag, str) or not tag.strip():
                    continue
                normalized = tag.strip()
                if normalized in score_tags_by_id.get(score_id, set()):
                    continue
                counts[normalized] += 1
    return counts


def _recurring_error_tags(ledger, error_counts: Counter[str]) -> list[str]:
    ordered = [
        "overconfidence",
        "base_rate_error",
        "missed_evidence",
        "overweighted_evidence",
        "inside_view_error",
        "resolution_error",
        "model_family_failure",
        "late_evidence_update",
        "stale_base_rate",
        "high_brier_miss",
    ]
    ordered_set = set(ordered)
    tags = [tag for tag in ordered if error_counts.get(tag, 0) > 0]
    tags.extend(
        tag
        for tag, count in sorted(error_counts.items())
        if count > 0 and tag not in ordered_set
    )
    return tags


def _recommended_adjustments_for_errors(ledger, recurring_errors: list[str]) -> list[str]:
    recommendations_by_error = {
        "elevated_mean_brier": "Review postmortems before increasing confidence in this scope.",
        "overconfidence": (
            "Temper high-confidence updates in this scope; require explicit outside-view, "
            "base-rate, and counterevidence checks before extreme probabilities."
        ),
        "base_rate_error": "Refresh reference classes and base rates before updating similar questions.",
        "stale_base_rate": "Shorten base-rate refresh cadence and verify stale reference classes before updates.",
        "missed_evidence": "Expand the source checklist and add watched sources for missing evidence classes.",
        "late_evidence_update": "Shorten review cadence for active questions with fast-moving evidence.",
        "overweighted_evidence": "Downweight single-source narratives until checked against base rates and counterevidence.",
        "inside_view_error": "Separate inside-view arguments from outside-view priors and record the reconciliation.",
        "resolution_error": "Re-read resolution criteria and resolver sources before forecasting similar questions.",
        "model_family_failure": "Review failed model runs before relying on that model family in this scope.",
        "high_brier_miss": "Inspect high-Brier misses before making adjacent forecasts.",
    }
    return [
        recommendations_by_error[tag]
        for tag in recurring_errors
        if tag in recommendations_by_error
    ]


def get_domain_error_profile(ledger, profile_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM domain_error_profiles WHERE id = ?",
            (profile_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"domain error profile not found: {profile_id}")
    return ledger._row_to_domain_error_profile(row)


def list_domain_error_profiles(
    ledger,
    *,
    domain: str | None = None,
    topic: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if domain:
        clauses.append("domain = ?")
        params.append(domain)
    if topic:
        clauses.append("topic = ?")
        params.append(topic)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM domain_error_profiles {where} ORDER BY updated_at DESC",
            params,
        ).fetchall()
    return [ledger._row_to_domain_error_profile(row) for row in rows]


def _row_to_domain_error_profile(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["calibration_summary"] = json_loads(data["calibration_summary"], {})
    data["recurring_errors"] = json_loads(data["recurring_errors"], [])
    data["recommended_adjustments"] = json_loads(data["recommended_adjustments"], [])
    return data


def _domain_error_profile_id(
    ledger,
    domain: str | None,
    topic: str | None,
    horizon: str | None,
    question_type: str | None,
) -> str:
    raw = "|".join([domain or "", topic or "", horizon or "", question_type or ""])
    return "dep_" + uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]


def _domain_error_profiles_for_question(ledger, question: ForecastQuestion) -> list[dict[str, Any]]:
    if not question.domain:
        return []
    profiles = []
    for profile in ledger.list_domain_error_profiles(domain=question.domain):
        profile_topic = profile.get("topic")
        if profile_topic and profile_topic not in question.topics:
            continue
        profile_type = profile.get("question_type")
        if profile_type and profile_type != question.outcome_space.type:
            continue
        profiles.append(profile)
    return profiles


def review_learned_error_alerts(
    ledger,
    question_id: str,
    *,
    reviewed_by: str,
    assessment: str,
    decision: str = "reviewed_no_change",
    now: str | None = None,
) -> dict[str, Any]:
    """Persist a substantive profile review before closing its manual alerts."""
    from forecasting.learning import is_learned_error_review_reason, learned_error_profile_id

    reviewer = reviewed_by.strip()
    review_text = assessment.strip()
    if not reviewer:
        raise ValidationError("reviewed_by is required")
    if len(review_text) < 20:
        raise ValidationError("learned-error assessment must be substantive")
    if decision not in {"reviewed_no_change", "update_required"}:
        raise ValidationError("decision must be reviewed_no_change or update_required")
    question = ledger.get_question(question_id)
    current = ledger.get_current_snapshot(question_id)
    if current is None:
        raise ValidationError("learned-error review requires a current forecast")
    alerts = [
        alert
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.scope_type == "question"
        and alert.scope_ref == question_id
        and is_learned_error_review_reason(alert.reason)
    ]
    if not alerts:
        raise ValidationError("question has no open learned-error review alerts")
    profile_ids = list(
        dict.fromkeys(
            profile_id
            for alert in alerts
            if (profile_id := learned_error_profile_id(alert.reason)) is not None
        )
    )
    profiles = [ledger.get_domain_error_profile(profile_id) for profile_id in profile_ids]
    adjustments = list(
        dict.fromkeys(
            adjustment
            for profile in profiles
            for adjustment in profile.get("recommended_adjustments", [])
        )
    )
    references = ledger.list_reference_classes(question_id)
    run = ledger.record_model_run(
        question_id=question_id,
        model_type="learned_error_profile_review",
        inputs={
            "current_forecast_id": current.forecast_id,
            "alert_ids": [alert.id for alert in alerts],
            "profile_ids": profile_ids,
            "recurring_errors": {
                profile["id"]: profile.get("recurring_errors", []) for profile in profiles
            },
        },
        parameters={
            "reviewed_by": reviewer,
            "decision": decision,
            "protocol": "learned-error-review-v1",
        },
        output={
            "assessment": review_text,
            "recommended_adjustments_considered": adjustments,
            "decision": decision,
        },
        diagnostics={
            "evidence_count": len(current.evidence_refs),
            "snapshot_reference_class_refs": list(current.reference_class_refs),
            "active_reference_class_refs": [row["id"] for row in references],
            "calibration_lesson_refs": list(current.calibration_lesson_refs),
        },
        evidence_cutoff=current.evidence_cutoff or current.as_of,
    )
    stamped = now or utc_now_iso()
    closed = [
        ledger.acknowledge_alert(
            alert.id,
            acknowledged_at=stamped,
            ack_note=f"learned_error_review:{run['id']}:{decision}",
            disposition=decision,
        )
        for alert in alerts
    ]
    follow_up = None
    if decision == "update_required":
        follow_up = ledger.create_alert(
            severity="high" if question.impact in {"high", "critical"} else "warning",
            scope_type="question",
            scope_ref=question_id,
            reason=f"learned_error_update_required:{run['id']}",
            recommended_action=review_text,
            now=stamped,
        )
    return {
        "question_id": question_id,
        "decision": decision,
        "model_run": run,
        "closed_alert_ids": [alert.id for alert in closed],
        "follow_up_alert_id": follow_up.id if follow_up else None,
    }
