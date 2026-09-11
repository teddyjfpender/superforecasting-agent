"""Tests for the forecast-hooks WRITE layer (forecasting/hooks/store.py): config
severity/profile/enable-disable round-trips + user-rule add/edit/remove, each
validated and atomic. Every test runs in an isolated agent home."""

from __future__ import annotations

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    # Reset warning suppression between fixtures.
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


def _fixture_rule(name):
    return {
        "id": name, "severity": "error",
        "check": {"signal": "components.count", "op": ">=", "value": 2},
        "message": "More drivers required",
    }


def test_concurrent_rule_edits_read_inside_shared_lock(home, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from forecasting.hooks import store

    read_started, release_read, second_started = (threading.Event() for _ in range(3))
    original = store._read_rules
    reads = []

    def read(path):
        result = original(path)
        reads.append(path)
        if len(reads) == 1:
            read_started.set()
            assert release_read.wait(3)
        return result

    monkeypatch.setattr(store, "_read_rules", read)

    def second():
        second_started.set()
        return store.save_rule(_fixture_rule("second-rule"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(store.save_rule, _fixture_rule("first-rule"))
        try:
            assert read_started.wait(2)
            other = pool.submit(second)
            assert second_started.wait(2)
            assert len(reads) == 1
        finally:
            release_read.set()
        assert first.result(timeout=3)["saved"]
        assert other.result(timeout=3)["saved"]
    assert {rule["id"] for rule in original(store._rules_path())} == {"first-rule", "second-rule"}


@pytest.mark.parametrize("contents", ["not: a-list\n", "- a-scalar\n", "- id: kept\n- false\n"])
def test_malformed_rule_file_is_not_silently_replaced(home, contents):
    from forecasting.hooks import store

    path = home / "hooks/rules.yaml"
    path.parent.mkdir()
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(store.HookWriteError, match="repair"):
        store.save_rule(_fixture_rule("new-rule"))
    assert path.read_text(encoding="utf-8") == contents


def test_failed_atomic_write_does_not_fall_back_to_unowned_temp_file(home, monkeypatch):
    from forecasting.hooks import store

    store.save_rule(_fixture_rule("first-rule"))
    path = home / "hooks/rules.yaml"
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise PermissionError("fixture atomic write refused")

    monkeypatch.setattr(store, "atomic_yaml_write", fail)
    with pytest.raises(PermissionError, match="refused"):
        store.save_rule(_fixture_rule("second-rule"))
    assert path.read_bytes() == before
    assert not path.with_suffix(".yaml.tmp").exists()


def test_hook_setting_edits_preserve_unrelated_raw_config(home):
    import yaml
    from forecasting.hooks import store

    path = home / "config.yaml"
    path.write_text("# Operator settings\nmodel: custom-model\ndisplay:\n  skin: mono\n", encoding="utf-8")
    store.set_profile("strict")
    store.set_enabled(False)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["model"] == "custom-model"
    assert data["display"] == {"skin": "mono"}
    assert data["forecasting"]["hooks"] == {"profile": "strict", "enabled": False}
    assert set(data) == {"model", "display", "forecasting"}


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_enabled_requires_boolean(home, value):
    from forecasting.hooks import store

    with pytest.raises(store.HookWriteError, match="boolean"):
        store.set_enabled(value)
    assert not (home / "config.yaml").exists()


@pytest.mark.parametrize(
    "contents",
    ["forecasting: false\n", "forecasting:\n  hooks: []\n",
     "forecasting:\n  hooks:\n    overrides: false\n"],
)
def test_malformed_config_blocks_fail_without_rewriting(home, contents):
    from forecasting.hooks import store

    path = home / "config.yaml"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(store.HookWriteError, match="mapping"):
        store.clear_override("require_components")
    assert path.read_text(encoding="utf-8") == contents
