"""Forecast Hooks — a git-hook-style saturation + style enforcement framework.

A set of rules ("hooks") evaluated at every live commit (and a finish sweep) that
score how saturated a forecast is, block under-saturated commits, and (Phase 2/3)
auto-orchestrate remediation so forecasts get fully informed without the user
re-prompting. ``create_snapshot`` is the single fail-closed chokepoint.
"""

from __future__ import annotations

from forecasting.hooks.builtins import BUILTIN_RULE_IDS, BUILTIN_RULES, style_message
from forecasting.hooks.distribution import DistributionAssessment, assess_distribution, autofix_distribution
from forecasting.hooks.reasoning import REASONING_METHODS, normalize_methods
from forecasting.hooks.engine import (
    Policy,
    load_hook_config,
    policy_from_require_flags,
    resolve_severities,
    run_hooks,
)
from forecasting.hooks.profiles import DEFAULT_PROFILE, HOOK_PROFILES
from forecasting.hooks import store
from forecasting.hooks.store import HookWriteError
from forecasting.hooks.signals import (
    build_commit_context,
    build_context_from_ledger,
    detect_style_offenders,
    style_clean_for_rationale,
)
from forecasting.hooks.sweep import finish_sweep, lint_forecast
from forecasting.hooks.spec import (
    Category,
    HookContext,
    RemediationDescriptor,
    SaturationBlocked,
    SaturationReport,
    Severity,
    SimpleRule,
    Verdict,
    single_block,
)

__all__ = [
    "BUILTIN_RULES",
    "BUILTIN_RULE_IDS",
    "Category",
    "HookContext",
    "Policy",
    "RemediationDescriptor",
    "SaturationBlocked",
    "SaturationReport",
    "Severity",
    "SimpleRule",
    "Verdict",
    "DEFAULT_PROFILE",
    "HOOK_PROFILES",
    "build_commit_context",
    "build_context_from_ledger",
    "detect_style_offenders",
    "finish_sweep",
    "lint_forecast",
    "load_hook_config",
    "policy_from_require_flags",
    "resolve_severities",
    "run_hooks",
    "single_block",
    "style_clean_for_rationale",
    "style_message",
]
