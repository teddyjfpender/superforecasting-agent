"""Tests for the forecast-hooks WRITE layer (forecasting/hooks/store.py): config
severity/profile/enable-disable round-trips + user-rule add/edit/remove, each
validated and atomic. Every test runs in an isolated agent home."""

from __future__ import annotations

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    # the loader caches rules-file reads on mtime; start clean
    from forecasting.hooks.loader import clear_cache

    clear_cache()
    return tmp_path


def _resolved(rule_id: str):
    from forecasting.hooks import resolve_severities

    return resolve_severities(None, forecast_origin="live")[rule_id]


def test_set_severity_round_trips(home):
    from forecasting.hooks import Severity, store

    store.set_severity("require_citations", "error")
    assert _resolved("require_citations") is Severity.ERROR
    store.set_severity("require_citations", "off")
    assert _resolved("require_citations") is Severity.OFF


def test_set_profile_changes_resolution(home):
    from forecasting.hooks import Severity, store

    # require_decision_readiness is WARN in standard, ERROR in strict
    assert _resolved("require_decision_readiness") is Severity.WARN
    store.set_profile("strict")
    assert _resolved("require_decision_readiness") is Severity.ERROR


def test_enable_disable(home):
    from forecasting.hooks import Severity, store

    store.disable("style_clean")
    assert _resolved("style_clean") is Severity.OFF
    store.enable("style_clean")  # revert to profile (standard => ERROR)
    assert _resolved("style_clean") is Severity.ERROR


def test_set_enabled_flag(home):
    from forecasting.hooks import store
    from forecasting.hooks.engine import load_hook_config

    store.set_enabled(False)
    assert load_hook_config().get("enabled") is False


def test_invalid_inputs_raise(home):
    from forecasting.hooks import store

    with pytest.raises(store.HookWriteError):
        store.set_severity("require_citations", "nope")
    with pytest.raises(store.HookWriteError):
        store.set_severity("not_a_rule", "warn")
    with pytest.raises(store.HookWriteError):
        store.set_profile("imaginary")


def test_user_rule_add_edit_remove(home):
    from forecasting.hooks import store
    from forecasting.hooks.engine import load_hook_config
    from forecasting.hooks.loader import load_user_rule_specs

    spec = {
        "id": "min-3-drivers", "severity": "warn", "remediation_hint": "decompose",
        "check": {"signal": "components.count", "op": ">=", "value": 3},
        "message": "need >= 3 drivers",
    }
    store.save_rule(spec)
    ids = {r.get("id") for r in load_user_rule_specs(load_hook_config())}
    assert "min-3-drivers" in ids

    # duplicate id refused
    with pytest.raises(store.HookWriteError):
        store.save_rule(spec)

    # edit replaces the severity
    store.edit_rule("min-3-drivers", {**spec, "severity": "error"})
    edited = next(r for r in load_user_rule_specs(load_hook_config()) if r.get("id") == "min-3-drivers")
    assert edited.get("severity") == "error"

    store.remove_rule("min-3-drivers")
    assert "min-3-drivers" not in {r.get("id") for r in load_user_rule_specs(load_hook_config())}


def test_invalid_rule_refused_with_issues(home):
    from forecasting.hooks import store

    with pytest.raises(store.HookWriteError) as ei:
        store.save_rule({"id": "bad", "severity": "error", "check": {"signal": "nope", "op": ">=", "value": 1}})
    assert ei.value.issues  # carries the teaching issues
    assert any("nope" in i.message or "signal" in i.field for i in ei.value.issues)


def test_remove_missing_rule_raises(home):
    from forecasting.hooks import store

    with pytest.raises(store.HookWriteError):
        store.remove_rule("does-not-exist")


def test_user_rule_on_v2_signal_enforces_at_commit(home, tmp_path):
    """A user rule referencing a v2 signal (reasoning.method_count) must enforce
    against REAL values at commit time, not the context defaults."""
    from forecasting import ForecastLedger
    from forecasting.hooks import SaturationBlocked, store

    store.save_rule({
        "id": "needs-2-methods", "severity": "error", "remediation_hint": "tag_reasoning",
        "check": {"signal": "reasoning.method_count", "op": ">=", "value": 2},
        "message": "declare at least two reasoning methods",
    })
    lg = ForecastLedger(db_path=str(tmp_path / "v2.db"))
    lg.initialize_schema()
    q = lg.create_question(title="Will X happen by year end?", resolution_criteria="Resolves YES if X occurs.")
    common = dict(method="m", require_panel=False, require_components=False, require_structured_reasoning=False)

    with pytest.raises(SaturationBlocked):
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="r",
                           reasoning_methods=["bayesian"], **common)

    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.6, rationale="r",
                              reasoning_methods=["bayesian", "outside_view"], **common)
    assert snap is not None


def _quorum_estimates():
    return [
        {"perspective": p, "probability": 0.5, "rationale": "r", "agent_model": f"m-{p}"}
        for p in ("outside", "inside", "market", "red_team", "sanity")
    ]


def test_user_rule_on_quorum_signal_enforces_at_commit(home, tmp_path):
    """A user rule on a v2 QUORUM signal (quorum.judged) must evaluate against the
    LINKED panel run's real value at commit — an unjudged quorum blocks, a judged one
    commits. This is the H1 fix: quorum signals are populated in build_commit_context
    from panel_run_ref, so they are no longer indeterminate at commit."""
    from forecasting import ForecastLedger
    from forecasting.hooks import SaturationBlocked, store

    store.save_rule({
        "id": "quorum-must-be-judged", "severity": "error", "remediation_hint": "run_quorum",
        "check": {"signal": "quorum.judged", "op": "is_true"},
        "message": "a quorum run must carry a judge synthesis",
    })
    lg = ForecastLedger(db_path=str(tmp_path / "quser.db"))
    lg.initialize_schema()
    q = lg.create_question(title="Will X happen by year end?", resolution_criteria="Resolves YES if X occurs.")
    common = dict(method="m", require_panel=False, require_components=False, require_structured_reasoning=False)

    unjudged = lg.record_panel_run(question_id=q.id, estimates=_quorum_estimates(), triggered_by="quorum")
    with pytest.raises(SaturationBlocked):
        lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                           panel_run_ref=unjudged["id"], **common)

    judged = lg.record_panel_run(question_id=q.id, estimates=_quorum_estimates(), triggered_by="quorum",
                                 judge={"consensus": "c", "judge_model": "j"})
    snap = lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="r",
                              panel_run_ref=judged["id"], **common)
    assert snap is not None
