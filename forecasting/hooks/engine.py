"""Forecast Hooks engine — evaluate the rule set against a HookContext and return
a SaturationReport (0-100 score + per-rule verdicts).

Phase 1 wires this into ``create_snapshot`` in OBSERVE mode (compute + store the
report); the inline gates remain the enforcement until the parity test green-lights
the flip. Phase 4 replaces ``policy_from_require_flags`` with config-resolved
severities (profiles + overrides + per-question).
"""

from __future__ import annotations

from forecasting.hooks.builtins import BUILTIN_RULE_IDS, BUILTIN_RULES
from forecasting.hooks.profiles import DEFAULT_PROFILE, profile_severities, scaled_profile
from forecasting.hooks.spec import (
    Category,
    HookContext,
    SaturationReport,
    Severity,
    SimpleRule,
    Verdict,
)

Policy = dict[str, Severity]


def _sev(value, default: Severity = Severity.WARN) -> Severity:
    try:
        return Severity(str(value).strip().lower())
    except Exception:
        return default


def load_hook_config() -> dict:
    """Read ``forecasting.hooks`` from the global config (defaults if absent)."""
    try:
        from superforecasting_agent.configuration import cfg_get
        from superforecasting_agent.storage.configuration import read_configuration

        hooks = cfg_get(read_configuration(), "forecasting", "hooks", default=None)
        return hooks if isinstance(hooks, dict) else {}
    except Exception:
        return {}


def resolve_severities(question, *, forecast_origin: str = "live", hooks_config: dict | None = None) -> Policy:
    """Resolve the effective severity per rule for a commit, applying the
    precedence: per-question override > config override > profile (after impact +
    origin scaling) > default profile. Returns {rule_id: Severity}."""
    hooks_config = hooks_config if hooks_config is not None else load_hook_config()
    # Master switch: everything advisory (nothing blocks).
    if hooks_config.get("enabled") is False:
        return {rid: Severity.WARN for rid in BUILTIN_RULE_IDS}

    qmeta = {}
    if question is not None:
        qmeta = (getattr(question, "metadata", None) or {}).get("forecast_hooks") or {}

    profile = qmeta.get("profile") or hooks_config.get("profile") or DEFAULT_PROFILE
    # Impact scaling: bump the profile along the strictness ladder.
    impact = (getattr(question, "impact", None) or "").strip().lower() if question else ""
    scaling = hooks_config.get("impact_scaling") or {}
    delta = 0
    if isinstance(scaling.get(impact), dict):
        try:
            delta = int(scaling[impact].get("delta") or 0)
        except (TypeError, ValueError):
            delta = 0
    sev = dict(profile_severities(scaled_profile(profile, ladder_delta=delta)))

    # User-defined rules carry their own default severity; add them so config /
    # per-question overrides can also retune them by id.
    try:
        from forecasting.hooks.loader import load_user_rules

        for rule in load_user_rules(hooks_config):
            sev.setdefault(rule.id, rule.default_severity)
    except Exception:
        pass

    # Origin scaling: a hard floor — non-live origins never block (mirrors the
    # legacy forecast_origin=="live" guard).
    origin_scaling = hooks_config.get("origin_scaling") or {}
    if str(origin_scaling.get(forecast_origin, "inherit")).strip().lower() == "off":
        return {rid: Severity.WARN for rid in sev}

    # Override floor: a compiled calibration-lesson rule (id `lesson:*`) enforces a
    # learning the desk already paid for in a miss; it must NOT be silently demotable
    # by a per-question or global override (that would re-open the "acknowledge then
    # ignore" hole at the config layer). Lesson rules carry + keep their own declared
    # severity; everything else is overridable as before.
    for rid, s in (hooks_config.get("overrides") or {}).items():
        if rid in sev and not rid.startswith("lesson:"):
            sev[rid] = _sev(s, sev[rid])
    for rid, s in (qmeta.get("overrides") or {}).items():
        if rid in sev and not rid.startswith("lesson:"):
            sev[rid] = _sev(s, sev[rid])
    return sev


def active_rules(hooks_config: dict | None = None) -> tuple[SimpleRule, ...]:
    """The built-in rules plus the configured user-defined rules (compiled)."""
    hooks_config = hooks_config if hooks_config is not None else load_hook_config()
    try:
        from forecasting.hooks.loader import load_user_rules

        return tuple(BUILTIN_RULES) + tuple(load_user_rules(hooks_config))
    except Exception:
        return tuple(BUILTIN_RULES)


def run_hooks(
    ctx: HookContext,
    policy: Policy | None = None,
    *,
    rules: tuple[SimpleRule, ...] = BUILTIN_RULES,
) -> SaturationReport:
    """Evaluate every applicable, non-OFF rule. ``policy`` overrides per-rule
    severity (rule_id -> Severity); rules absent from the policy use their
    default severity. Score = 100 * (1 - failed_weight / applicable_weight)."""
    policy = policy or {}
    verdicts: list[Verdict] = []
    engine_errors: list[str] = []
    applicable_weight = 0.0
    failed_weight = 0.0

    for rule in rules:
        # Per-rule fail-soft: a single throwing rule (buggy applies()/check()) must
        # NOT abort the batch — that would trip the ledger-level fail-open and
        # silently disable ALL lesson + user-rule enforcement for the commit. It
        # degrades to a non-passing WARN (never blocks — bricking commits on a buggy
        # rule is worse than a missed check) but stays VISIBLE via facts + engine_errors.
        try:
            severity = policy.get(rule.id, rule.default_severity)
            if severity is Severity.OFF or not rule.applies(ctx):
                continue
            verdict = rule.evaluate(ctx, severity)
        except Exception as exc:  # noqa: BLE001 — degrade one rule, never the batch
            weight = getattr(rule, "weight", 0.0) or 0.0
            engine_errors.append(f"{rule.id}: {exc!r}")
            verdict = Verdict(
                rule_id=rule.id,
                category=getattr(rule, "category", Category.CUSTOM),
                severity=Severity.WARN,  # degraded — a broken rule must not block
                passed=False,
                score_penalty=weight,
                message=f"hook rule {rule.id!r} raised during evaluation and was degraded to a warning: {exc}",
                facts={"engine_error": repr(exc), "rule_id": rule.id},
            )
            verdicts.append(verdict)
            applicable_weight += weight
            failed_weight += weight
            continue
        verdicts.append(verdict)
        applicable_weight += rule.weight
        if not verdict.passed:
            failed_weight += rule.weight

    score = 100.0 if applicable_weight <= 0 else 100.0 * (1.0 - failed_weight / applicable_weight)
    passed = not any(v.severity.blocks and not v.passed for v in verdicts)
    return SaturationReport(
        question_id=ctx.question_id,
        event=ctx.event,
        score=score,
        passed=passed,
        verdicts=verdicts,
        engine_errors=engine_errors,
    )


def policy_from_require_flags(
    *,
    forecast_origin: str,
    require_structured_reasoning: bool,
    require_components: bool,
    require_fresh_evidence: bool,
    require_decision_readiness: bool,
    require_panel: bool,
    require_citations: bool,
    require_outcome_paths: bool,
) -> Policy:
    """Phase-1 bridge: map the legacy ``require_*`` booleans a caller passed to
    ``create_snapshot`` into a hook policy, so the observe-mode report's pass/block
    mirrors exactly what the inline gates enforce for THIS commit. A flag True ->
    ERROR (blocking); False -> WARN (scored, advisory). Non-live commits get the
    full set as OFF (the legacy gates all key on forecast_origin == 'live')."""
    if forecast_origin != "live":
        return {rule_id: Severity.OFF for rule_id in (
            "require_structured_reasoning", "require_components", "require_fresh_evidence",
            "require_decision_readiness", "require_panel", "require_citations",
            "require_outcome_paths", "style_clean", "lessons_applied",
        )}

    def sev(flag: bool) -> Severity:
        return Severity.ERROR if flag else Severity.WARN

    return {
        "require_structured_reasoning": sev(require_structured_reasoning),
        "require_components": sev(require_components),
        "require_fresh_evidence": sev(require_fresh_evidence),
        "require_decision_readiness": sev(require_decision_readiness),
        "require_panel": sev(require_panel),
        "require_citations": sev(require_citations),
        "require_outcome_paths": sev(require_outcome_paths),
        # Additive rules keep their built-in defaults (style ERROR, lessons WARN).
    }
