"""Finish sweep + single-forecast lint.

``lint_forecast`` runs the hook engine read-only against a question's CURRENT
snapshot and returns its SaturationReport — the basis of ``forecast lint <id>``
and the dry-run preview. ``finish_sweep`` runs it across a set of touched
questions at the end of an interactive session / pipeline run and returns a
summary so the agent (or the user) sees which forecasts are under-saturated and
should be improved. The sweep is READ-ONLY: it never commits, so it can only
surface gaps, never persist anything under-saturated (the create_snapshot
chokepoint remains the only writer + the fail-closed gate).
"""

from __future__ import annotations

from typing import Any

from forecasting.hooks.engine import Policy, active_rules, resolve_severities, run_hooks
from forecasting.hooks.signals import build_context_from_ledger
from forecasting.hooks.spec import SaturationReport

# The saturation score below which a LIVE forecast is "under-saturated" and worth
# surfacing (the tool result advisory, the desk below-threshold badge, and the
# scheduled/ programmatic WARN alert all read this SAME bar). Config-overridable
# via ``forecasting.hooks.sweep_alert_threshold`` so the desk can tune the floor
# without a code change; 60/100 is the default, matching the observe-mode score
# scale (0-100).
DEFAULT_SWEEP_ALERT_THRESHOLD = 60.0


def sweep_alert_threshold(hooks_config: dict | None = None) -> float:
    """The under-saturation alert/badge threshold (0-100). Reads
    ``forecasting.hooks.sweep_alert_threshold`` from config, falling back to
    :data:`DEFAULT_SWEEP_ALERT_THRESHOLD`. Fail-open: any config error → default."""
    try:
        from forecasting.hooks.engine import load_hook_config

        cfg = hooks_config if hooks_config is not None else load_hook_config()
        value = (cfg or {}).get("sweep_alert_threshold")
        return float(value) if value is not None else DEFAULT_SWEEP_ALERT_THRESHOLD
    except Exception:
        return DEFAULT_SWEEP_ALERT_THRESHOLD


def saturation_summary(saturation: Any) -> dict[str, Any] | None:
    """Compact ``{score, advisories:[{rule_id, message, remediation}]}`` from a
    STORED ``snapshot_metadata['saturation']`` dict (the observe-mode report).

    READ-ONLY — no hook recompute. ``advisories`` are the FAILED verdicts (on a
    successful commit the blocking rules already passed, so these are the WARN
    advisories the agent can self-remediate; the same list drives the desk badge
    and the alert body). Returns ``None`` when no report was recorded / the shape
    is unexpected, so every caller can treat "no saturation" uniformly."""
    if not isinstance(saturation, dict):
        return None
    score = saturation.get("score")
    advisories: list[dict[str, Any]] = []
    verdicts = saturation.get("verdicts")
    if isinstance(verdicts, list):
        for verdict in verdicts:
            if isinstance(verdict, dict) and not verdict.get("passed", True):
                advisories.append(
                    {
                        "rule_id": verdict.get("rule_id"),
                        "message": verdict.get("message") or "",
                        "remediation": verdict.get("remediation"),
                    }
                )
    return {"score": score, "advisories": advisories}


def lint_forecast(ledger, question_id: str, *, policy: Policy | None = None, event: str = "lint") -> SaturationReport | None:
    """Saturation report for a question's current snapshot, or None if it has no
    snapshot yet."""
    try:
        if ledger.get_current_snapshot(question_id) is None:
            return None
    except Exception:
        return None
    ctx = build_context_from_ledger(ledger, question_id, event=event)
    if policy is None:
        policy = resolve_severities(ledger.get_question(question_id), forecast_origin=ctx.forecast_origin)
    return run_hooks(ctx, policy, rules=active_rules())


def adherence_scorecard(ledger, *, question_ids=None) -> dict[str, Any]:
    """Per-rule adherence across active questions — the operator's glanceable trust
    surface. Tallied READ-ONLY from the STORED ``metadata['saturation']`` verdicts on
    each current snapshot (no hook recompute, no schema change), so the doctor can
    show ``{rule_id: {checked, passed, failed_warn, failed_block, pass_rate}}`` per
    gate. The lazy operator's whole check becomes: every ``failed_block`` column is
    zero and the ``failed_warn`` columns are falling.

    ``failed_block`` counts a FAILED verdict whose recorded severity is ``error``
    (it would refuse a commit); ``failed_warn`` counts a failed WARN. Questions with
    no stored saturation report are skipped (not every snapshot carries one)."""
    rules: dict[str, dict[str, int]] = {}
    scored = 0
    if question_ids is None:
        try:
            question_ids = [q.id for q in ledger.list_questions(status="active")]
        except Exception:
            question_ids = []
    for qid in question_ids or []:
        try:
            snap = ledger.get_current_snapshot(qid)
        except Exception:
            snap = None
        if snap is None:
            continue
        sat = (getattr(snap, "metadata", None) or {}).get("saturation")
        if not isinstance(sat, dict):
            continue
        verdicts = sat.get("verdicts")
        if not isinstance(verdicts, list):
            continue
        scored += 1
        for verdict in verdicts:
            if not isinstance(verdict, dict):
                continue
            rid = verdict.get("rule_id")
            if not rid:
                continue
            bucket = rules.setdefault(rid, {"checked": 0, "passed": 0, "failed_warn": 0, "failed_block": 0})
            bucket["checked"] += 1
            if verdict.get("passed", True):
                bucket["passed"] += 1
            elif str(verdict.get("severity")) == "error":
                bucket["failed_block"] += 1
            else:
                bucket["failed_warn"] += 1
    out_rules: dict[str, dict[str, Any]] = {}
    total_block = 0
    for rid, bucket in sorted(rules.items()):
        checked = bucket["checked"] or 1
        total_block += bucket["failed_block"]
        out_rules[rid] = {**bucket, "pass_rate": round(bucket["passed"] / checked, 3)}
    return {
        "questions_scored": scored,
        "rules_tracked": len(out_rules),
        "total_failed_block": total_block,
        "rules": out_rules,
    }


def finish_sweep(ledger, question_ids, *, policy: Policy | None = None) -> dict[str, Any]:
    """Re-lint each touched forecast and summarize. Returns
    {checked, clean, under_saturated:[{question_id, score, blocking, warnings}]}.
    De-duplicates ids; skips questions with no current snapshot."""
    seen: set[str] = set()
    under: list[dict[str, Any]] = []
    clean = 0
    checked = 0
    for qid in question_ids or []:
        if not qid or qid in seen:
            continue
        seen.add(qid)
        report = lint_forecast(ledger, qid, policy=policy, event="finish_sweep")
        if report is None:
            continue
        checked += 1
        d = report.to_dict()
        if report.passed and not report.warnings():
            clean += 1
        else:
            under.append({
                "question_id": qid,
                "score": d["score"],
                "passed": report.passed,
                "blocking": d["blocking"],
                "warnings": d["warnings"],
            })
    return {"checked": checked, "clean": clean, "under_saturated": under}
