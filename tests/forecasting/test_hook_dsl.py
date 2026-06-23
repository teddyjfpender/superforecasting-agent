"""Phase 5 tests: the safe user-rule DSL (validation that teaches, evaluation,
commit-time enforcement) + the `forecast hooks` CLI handlers."""

from __future__ import annotations

import argparse

from forecasting import ForecastLedger
from forecasting.hooks import SaturationBlocked
from forecasting.hooks.dsl import (
    RuleSpec,
    compile_rule,
    evaluate_predicate,
    signal_glossary,
    validate_rule,
)
from forecasting.hooks.spec import HookContext, Severity


def _spec(**over):
    base = dict(id="min-drivers", description="d", category="custom", severity="error",
                check={"all": [{"signal": "components.count", "op": ">=", "value": 3}]},
                message="needs >=3 drivers ({components.count} present)", remediation_hint="decompose")
    base.update(over)
    return RuleSpec.from_dict(base)


def test_valid_rule_has_no_errors():
    assert [i for i in validate_rule(_spec()) if i.severity == "error"] == []


def test_unknown_signal_error_lists_vocabulary():
    issues = validate_rule(_spec(check={"signal": "evidence.kount", "op": ">=", "value": 1}))
    err = next(i for i in issues if i.severity == "error")
    assert "unknown signal" in err.message
    assert "evidence.count" in err.fix  # the error teaches the valid names


def test_bad_operator_for_bool_signal_errors():
    issues = validate_rule(_spec(check={"signal": "style.clean", "op": ">", "value": 1}))
    assert any(i.severity == "error" and "invalid for boolean" in i.message for i in issues)


def test_id_collision_with_builtin_rejected():
    issues = validate_rule(_spec(id="require_components"))
    assert any(i.severity == "error" and "built-in" in i.message for i in issues)


def test_error_severity_without_remediation_warns():
    issues = validate_rule(_spec(remediation_hint="none"))
    assert any(i.severity == "warn" and "no auto-fix" in i.message for i in issues)


def test_evaluate_predicate_all_any_not():
    ctx = HookContext(question_id="q", forecast_origin="live", event="update", component_count=4, evidence_count=0)
    assert evaluate_predicate({"all": [{"signal": "components.count", "op": ">=", "value": 3}]}, ctx) is True
    assert evaluate_predicate({"any": [{"signal": "components.count", "op": ">", "value": 9},
                                       {"signal": "evidence.count", "op": "==", "value": 0}]}, ctx) is True
    assert evaluate_predicate({"not": {"signal": "components.count", "op": ">=", "value": 9}}, ctx) is True


def test_compiled_rule_passes_and_fails():
    rule = compile_rule(_spec())
    ok = HookContext(question_id="q", forecast_origin="live", event="update", component_count=5)
    bad = HookContext(question_id="q", forecast_origin="live", event="update", component_count=1)
    assert rule.evaluate(ok, Severity.ERROR).passed is True
    v = rule.evaluate(bad, Severity.ERROR)
    assert v.passed is False
    assert "1 present" in v.message  # {components.count} interpolated


def test_signal_glossary_nonempty():
    g = signal_glossary()
    assert any(n == "components.count" for n, _kind, _doc in g)


def test_user_rule_blocks_commit(tmp_path, monkeypatch):
    # Configure a user rule requiring >=5 drivers; a 2-driver commit must block.
    import forecasting.hooks.engine as eng
    import forecasting.hooks.loader as loader
    loader.clear_cache()
    cfg = {"profile": "standard", "rules": [{
        "id": "needs-five-drivers", "severity": "error", "remediation_hint": "decompose",
        "check": {"signal": "components.count", "op": ">=", "value": 5},
        "message": "this desk requires >=5 pooled drivers",
    }]}
    monkeypatch.setattr(eng, "load_hook_config", lambda: cfg)

    lg = ForecastLedger(db_path=str(tmp_path / "u.db"))
    lg.initialize_schema()
    q = lg.create_question(title="Will the indicator exceed target by close?",
                           resolution_criteria="Resolves yes if the indicator exceeds target by close; otherwise no.")
    comps = {"components": [{"name": "a", "probability": 0.4, "weight": 1}, {"name": "b", "probability": 0.6, "weight": 1}]}
    try:
        import pytest
        with pytest.raises(SaturationBlocked) as ei:
            lg.create_snapshot(question_id=q.id, probability_or_distribution=0.5, rationale="clean prose",
                               method="m", ensemble_components=comps, reasons_up=["a"], reasons_down=["b"],
                               change_my_mind=["c"], require_panel=False)
        assert any(v.rule_id == "needs-five-drivers" for v in ei.value.report.blocking_failures())
    finally:
        loader.clear_cache()


def test_cli_hooks_explain_and_profiles(capsys):
    from forecasting.cli import _cmd_hooks_explain, _cmd_hooks_profiles
    _cmd_hooks_explain(argparse.Namespace(signal="components.count"))
    assert "pooled drivers" in capsys.readouterr().out
    _cmd_hooks_profiles(argparse.Namespace())
    out = capsys.readouterr().out
    assert "standard" in out and "strict" in out


def test_cli_hooks_list(tmp_path, capsys):
    from forecasting.cli import _cmd_hooks_list
    db = str(tmp_path / "l.db")
    ForecastLedger(db_path=db).initialize_schema()
    _cmd_hooks_list(argparse.Namespace(db=db, question_id=None, json=True))
    out = capsys.readouterr().out
    assert "require_components" in out and "style_clean" in out
