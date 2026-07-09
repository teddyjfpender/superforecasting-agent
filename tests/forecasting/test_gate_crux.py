"""G7 · CRUX MINIMUM on high-impact — a high-impact commit must carry >=1 registered
crux (question_cruxes) OR name why none exists (crux_skip_reason). PROMOTED to ERROR
standard 2026-07-09 (crux backfill landed; remediation sweep 2 = 0 live fail), ERROR
strict. The check scopes the block to high-impact, so medium-impact is untouched."""

from __future__ import annotations

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.dsl import RuleSpec, compile_rule, evaluate_predicate
from forecasting.hooks.spec import HookContext


def _ctx(**kw) -> HookContext:
    base = dict(question_id="fq", event="update", forecast_origin="live", impact="high",
                is_thesis_or_factor=False)
    base.update(kw)
    return HookContext(**base)


def _verdict(ctx, profile="standard"):
    report = run_hooks(ctx, resolve_severities(_QProfile(profile), forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == "crux_named"), None)


class _QProfile:
    def __init__(self, profile):
        self.metadata = {"forecast_hooks": {"profile": profile}}
        self.impact = "high"


def test_high_impact_no_crux_blocks():
    # PROMOTED 2026-07-09: crux_named is ERROR in standard now (was WARN).
    v = _verdict(_ctx(crux_count=0))
    assert v is not None and v.passed is False and v.severity.value == "error"
    assert "no registered crux" in v.message


def test_crux_present_passes():
    v = _verdict(_ctx(crux_count=2))
    assert v is not None and v.passed is True


def test_crux_skip_reason_passes():
    v = _verdict(_ctx(crux_count=0, crux_skip_reason="a single-variable question with no contested crux"))
    assert v is not None and v.passed is True


def test_does_not_apply_to_medium_impact():
    v = _verdict(_ctx(impact="medium", crux_count=0))
    assert v is None


def test_does_not_apply_to_thesis():
    v = _verdict(_ctx(crux_count=0, is_thesis_or_factor=True))
    assert v is None


def test_strict_blocks():
    from forecasting.hooks.profiles import profile_severities
    from forecasting.hooks.spec import Severity
    assert profile_severities("strict")["crux_named"] is Severity.ERROR


def test_dsl_cruxes_count_signal_usable():
    # cruxes.count is exposed so a user/lesson rule can require it.
    spec = RuleSpec.from_dict({
        "id": "needs_crux", "check": {"signal": "cruxes.count", "op": ">=", "value": 1},
    })
    rule = compile_rule(spec)
    assert rule.check_fn(_ctx(crux_count=1))[0] is True
    assert rule.check_fn(_ctx(crux_count=0))[0] is False
    assert evaluate_predicate(spec.check, _ctx(crux_count=3)) is True


def test_ledger_high_impact_crux_wiring(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")
    from forecasting.ledger import ForecastLedger

    lg = ForecastLedger(db_path=str(tmp_path / "g7.db"))
    lg.initialize_schema()
    q = lg.create_question(title="Will the high-stakes event resolve yes?",
                           resolution_criteria="Resolves yes if the event happens by close; otherwise no.",
                           impact="high")
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.42, rationale="read",
                       require_panel=False, reference_class_refs=[rc["id"]], enforce_resolved_hooks=False)
    # No crux yet -> the lint verdict fails (ERROR in standard since the promotion).
    report = lint_report(lg, q.id)
    v = next((x for x in report.verdicts if x.rule_id == "crux_named"), None)
    assert v is not None and v.passed is False
    # Register a crux -> passes.
    lg.add_crux(question_id=q.id, crux_variable="turnout in the swing district")
    report2 = lint_report(lg, q.id)
    v2 = next((x for x in report2.verdicts if x.rule_id == "crux_named"), None)
    assert v2 is not None and v2.passed is True


def lint_report(lg, qid):
    from forecasting.hooks import lint_forecast
    return lint_forecast(lg, qid, event="lint")
