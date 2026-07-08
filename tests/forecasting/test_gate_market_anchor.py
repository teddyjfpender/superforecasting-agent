"""G8 · MARKET-ANCHOR UNIVERSALITY — a commit on a market-linked question must record
the market price + deviation, even outside a quorum job. The rule requires ENGAGEMENT
(record the price and, past threshold, the named edge), never AGREEMENT. WARN standard,
ERROR strict. The commit path records a deviation_bets row for a market-linked
NON-QUORUM commit that stamped metadata.market_comparison — the seam that had 0 rows."""

from __future__ import annotations

import pytest

from forecasting.hooks import resolve_severities, run_hooks
from forecasting.hooks.dsl import RuleSpec, compile_rule
from forecasting.hooks.market_anchor import (
    component_market_source,
    detect_linked_market,
    market_comparison_from_metadata,
)
from forecasting.hooks.spec import HookContext
from forecasting.ledger import ForecastLedger


@pytest.fixture(autouse=True)
def _gate_off(monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "off")


def _ctx(**kw) -> HookContext:
    base = dict(question_id="fq", event="update", forecast_origin="live", is_thesis_or_factor=False)
    base.update(kw)
    return HookContext(**base)


def _verdict(ctx):
    report = run_hooks(ctx, resolve_severities(None, forecast_origin="live"))
    return next((v for v in report.verdicts if v.rule_id == "market_anchor_engaged"), None)


# ── detection helpers ─────────────────────────────────────────────────────────
def test_component_market_source_detected():
    comps = [{"source": "polymarket:will-x", "probability": 0.55}, {"source": "base_rate", "probability": 0.5}]
    assert component_market_source(comps) == "polymarket:will-x"


def test_detect_linked_market_from_watch_and_baseline():
    linked, src = detect_linked_market(watched_source_slugs=["kalshi-abc"], baseline_types=[])
    assert linked and "kalshi" in src.lower()
    linked2, _ = detect_linked_market(baseline_types=["market_price"])
    assert linked2 is True
    assert detect_linked_market(watched_source_slugs=["fred:CPI"], baseline_types=["imported"])[0] is False


def test_market_comparison_from_metadata():
    mc = market_comparison_from_metadata({"market_comparison": {"price": 0.6, "deviation_pp": 12.0, "justification": "edge"}})
    assert mc["price"] == 0.6 and mc["deviation_pp"] == 12.0 and mc["justification"] == "edge"
    assert market_comparison_from_metadata({}) is None
    assert market_comparison_from_metadata({"market_comparison": {"deviation_pp": 5}}) is None  # no price


# ── the rule ──────────────────────────────────────────────────────────────────
def test_market_linked_no_comparison_warns():
    v = _verdict(_ctx(has_linked_market=True, market_comparison_recorded=False, linked_market_source="polymarket:x"))
    assert v is not None and v.passed is False and v.severity.value == "warn"
    assert "live market" in v.message


def test_comparison_recorded_passes():
    v = _verdict(_ctx(has_linked_market=True, market_comparison_recorded=True))
    assert v is not None and v.passed is True


def test_market_skip_reason_passes():
    v = _verdict(_ctx(has_linked_market=True, market_comparison_recorded=False, market_skip_reason="market illiquid / wide spread"))
    assert v is not None and v.passed is True


def test_no_market_not_applicable():
    v = _verdict(_ctx(has_linked_market=False, market_comparison_recorded=False))
    assert v is None


def test_share_board_with_market_still_applies():
    # engagement is outcome-type-agnostic even though the quorum PULL stays binary-only.
    v = _verdict(_ctx(has_linked_market=True, market_comparison_recorded=False, is_candidate_share=True,
                      linked_market_source="metaculus:vote"))
    assert v is not None and v.passed is False


def test_strict_blocks():
    from forecasting.hooks.profiles import profile_severities
    from forecasting.hooks.spec import Severity
    assert profile_severities("strict")["market_anchor_engaged"] is Severity.ERROR


def test_dsl_market_signals_usable():
    spec = RuleSpec.from_dict({"id": "m", "check": {"signal": "market.comparison_recorded", "op": "is_true"}})
    rule = compile_rule(spec)
    assert rule.check_fn(_ctx(market_comparison_recorded=True))[0] is True
    assert rule.check_fn(_ctx(market_comparison_recorded=False))[0] is False


# ── behavioral: non-quorum commit records a deviation_bet ─────────────────────
def _market_question(lg):
    q = lg.create_question(title="Will the market-linked binary resolve yes?",
                           resolution_criteria="Resolves yes if the event happens by close; otherwise no.")
    lg.add_watched_source(scope_type="question", scope_ref=q.id, source="polymarket:will-x-happen")
    lg.add_evidence(question_id=q.id, source_or_note="s", claim="c")
    rc = lg.add_reference_class(question_id=q.id, name="hist", inclusion_criteria="prior cases", base_rate=0.4)
    return q, rc


def test_non_quorum_commit_records_deviation_bet(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "g8.db"))
    lg.initialize_schema()
    q, rc = _market_question(lg)
    # A market-linked NON-QUORUM commit that stamps metadata.market_comparison past the
    # 10pp threshold WITH a named edge records a pre-registered deviation bet.
    lg.create_snapshot(
        question_id=q.id, probability_or_distribution=0.80, rationale="strong conviction read",
        require_panel=False, reference_class_refs=[rc["id"]], enforce_resolved_hooks=False,
        metadata={"market_comparison": {"price": 0.60, "deviation_pp": 20.0,
                                        "justification": "the market underweights the base-rate shift"}},
    )
    bets = lg.list_deviation_bets(q.id)
    assert len(bets) == 1
    assert bets[0]["market_price"] == 0.60
    assert bets[0]["reconciled_verdict"] == 0.80
    assert bets[0]["named_edge"]


def test_within_threshold_or_no_edge_records_no_bet(tmp_path):
    lg = ForecastLedger(db_path=str(tmp_path / "g8b.db"))
    lg.initialize_schema()
    q, rc = _market_question(lg)
    # deviation within the threshold -> not a bet
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.62, rationale="r",
                       require_panel=False, reference_class_refs=[rc["id"]], enforce_resolved_hooks=False,
                       metadata={"market_comparison": {"price": 0.60, "deviation_pp": 2.0, "justification": "edge"}})
    assert lg.list_deviation_bets(q.id) == []
    # past threshold but NO named edge -> not a bet
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.85, rationale="r2",
                       require_panel=False, reference_class_refs=[rc["id"]], enforce_resolved_hooks=False,
                       metadata={"market_comparison": {"price": 0.60, "deviation_pp": 25.0}})
    assert lg.list_deviation_bets(q.id) == []


def test_market_linked_lint_warns_without_comparison(tmp_path):
    from forecasting.hooks import lint_forecast
    lg = ForecastLedger(db_path=str(tmp_path / "g8c.db"))
    lg.initialize_schema()
    q, rc = _market_question(lg)
    lg.create_snapshot(question_id=q.id, probability_or_distribution=0.62, rationale="no comparison",
                       require_panel=False, reference_class_refs=[rc["id"]], enforce_resolved_hooks=False)
    report = lint_forecast(lg, q.id, event="lint")
    v = next((x for x in report.verdicts if x.rule_id == "market_anchor_engaged"), None)
    assert v is not None and v.passed is False  # market watched, no comparison recorded
