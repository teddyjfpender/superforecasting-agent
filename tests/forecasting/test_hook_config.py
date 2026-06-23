"""Phase 4 tests: config-driven severity resolution + precedence."""

from __future__ import annotations

from types import SimpleNamespace

from forecasting.hooks import Severity, resolve_severities


def _q(impact=None, hooks_meta=None):
    return SimpleNamespace(impact=impact, metadata=({"forecast_hooks": hooks_meta} if hooks_meta else {}))


def test_standard_profile_matches_prior_defaults():
    sev = resolve_severities(_q(), forecast_origin="live", hooks_config={"profile": "standard"})
    assert sev["require_structured_reasoning"] is Severity.ERROR
    assert sev["require_components"] is Severity.ERROR
    assert sev["require_panel"] is Severity.ERROR
    assert sev["style_clean"] is Severity.ERROR
    assert sev["require_citations"] is Severity.WARN
    assert sev["require_decision_readiness"] is Severity.WARN


def test_strict_profile_blocks_everything():
    sev = resolve_severities(_q(), forecast_origin="live", hooks_config={"profile": "strict"})
    assert sev["require_citations"] is Severity.ERROR
    assert sev["require_decision_readiness"] is Severity.ERROR
    assert sev["require_outcome_paths"] is Severity.ERROR


def test_exploratory_lenient_blocks_nothing():
    sev = resolve_severities(_q(), forecast_origin="live", hooks_config={"profile": "exploratory-lenient"})
    assert all(v is not Severity.ERROR for v in sev.values())


def test_impact_scaling_bumps_high_to_strict():
    cfg = {"profile": "standard", "impact_scaling": {"high": {"delta": 1}}}
    sev = resolve_severities(_q(impact="high"), forecast_origin="live", hooks_config=cfg)
    assert sev["require_citations"] is Severity.ERROR  # standard -> strict
    # a non-high question with the same config stays standard
    assert resolve_severities(_q(impact="low"), forecast_origin="live", hooks_config=cfg)["require_citations"] is Severity.WARN


def test_origin_scaling_off_makes_everything_advisory():
    cfg = {"profile": "strict", "origin_scaling": {"exploratory": "off"}}
    sev = resolve_severities(_q(), forecast_origin="exploratory", hooks_config=cfg)
    assert all(v is Severity.WARN for v in sev.values())


def test_config_override_promotes_a_rule():
    sev = resolve_severities(_q(), forecast_origin="live",
                             hooks_config={"profile": "standard", "overrides": {"require_citations": "error"}})
    assert sev["require_citations"] is Severity.ERROR


def test_per_question_override_beats_config_override():
    cfg = {"profile": "standard", "overrides": {"require_citations": "error"}}
    sev = resolve_severities(_q(hooks_meta={"overrides": {"require_citations": "off"}}),
                             forecast_origin="live", hooks_config=cfg)
    assert sev["require_citations"] is Severity.OFF  # per-question wins


def test_per_question_profile_overrides_config_profile():
    sev = resolve_severities(_q(hooks_meta={"profile": "strict"}),
                             forecast_origin="live", hooks_config={"profile": "standard"})
    assert sev["require_citations"] is Severity.ERROR


def test_master_switch_off_makes_everything_advisory():
    sev = resolve_severities(_q(), forecast_origin="live", hooks_config={"enabled": False, "profile": "strict"})
    assert all(v is Severity.WARN for v in sev.values())


def test_default_config_block_is_present_and_standard():
    # The shipped DEFAULT_CONFIG must carry forecasting.hooks at the standard
    # profile with no auto-bump, so adopting hooks is a no-op on upgrade.
    from hermes_cli.config import DEFAULT_CONFIG
    hooks = DEFAULT_CONFIG["forecasting"]["hooks"]
    assert hooks["enabled"] is True
    assert hooks["profile"] == "standard"
    assert hooks["impact_scaling"]["high"]["delta"] == 0
