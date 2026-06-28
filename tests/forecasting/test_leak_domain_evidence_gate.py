"""AIA P2.4 — leak-domain tagging in add_evidence + model-cutoff backtest gate."""

from __future__ import annotations

from forecasting import ForecastLedger
from forecasting.agent_protocol import _ANSWER_SIDE_FIELDS


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "leak.db"))
    lg.initialize_schema()
    return lg


def _q(lg) -> str:
    q = lg.create_question(
        title="Will the indicator exceed target by close?",
        resolution_criteria="Resolves yes if the indicator exceeds target by close.",
    )
    return q.id


def test_leak_domain_url_is_tagged_and_inadmissible(tmp_path):
    lg = _ledger(tmp_path)
    qid = _q(lg)
    ev = lg.add_evidence(
        question_id=qid,
        source_or_note="https://www.macrotrends.net/stocks/charts/AAPL/apple/revenue",
        claim="revenue figure",
    )
    assert ev.admissible_for_backtests is False
    assert (ev.metadata or {}).get("leak_domain") is True
    assert (ev.metadata or {}).get("leak_reason")


def test_normal_url_is_byte_identical_unchanged(tmp_path):
    lg = _ledger(tmp_path)
    qid = _q(lg)
    ev = lg.add_evidence(
        question_id=qid,
        source_or_note="https://www.reuters.com/business/apple-q3-2023-results",
        claim="reuters reported results",
    )
    assert ev.admissible_for_backtests is True
    assert "leak_domain" not in (ev.metadata or {})
    assert "leak_reason" not in (ev.metadata or {})


def test_extra_denylist_param_flags_custom_host(tmp_path):
    lg = _ledger(tmp_path)
    qid = _q(lg)
    ev = lg.add_evidence(
        question_id=qid,
        source_or_note="https://customlive.example.org/board",
        claim="custom widget value",
        extra_leak_denylist=["customlive.example.org"],
    )
    assert ev.admissible_for_backtests is False
    assert (ev.metadata or {}).get("leak_domain") is True


def _backtest_case(*, agent_model, resolution_time, outcome=1):
    return {
        "id": "c1",
        "title": "Will the index exceed 100 by the close date?",
        "resolution_criteria": "Resolves yes if the published index exceeds 100 by the close date; otherwise no.",
        "simulated_forecast_time": "2024-01-01T00:00:00Z",
        "resolution_time": resolution_time,
        "outcome_space": {"type": "binary"},
        "probability": 0.7,
        "outcome": outcome,
        "agent_model": agent_model,
    }


def _calibration_eligible(lg, run_id, case_row):
    fid = case_row["generated_forecast_id"]
    snap = lg.get_snapshot(fid)
    return snap.calibration_eligible, (snap.metadata or {})


def test_model_cutoff_gate_forces_calibration_off(tmp_path):
    lg = _ledger(tmp_path)
    # gpt-4o cutoff is 2023-10-01, which is >= the 2023-06 event => too fresh.
    result = lg.run_backtest_dataset(
        dataset="d",
        cases=[_backtest_case(agent_model="openai/gpt-4o-2024-08-06", resolution_time="2023-06-01T00:00:00Z")],
        allow_calibration_memory=True,
    )
    case_row = result["cases"][0]
    eligible, meta = _calibration_eligible(lg, result["id"], case_row)
    assert eligible is False
    assert meta.get("model_cutoff_too_fresh") is True
    assert meta.get("readiness_flag") == "model_cutoff_after_event"
    assert case_row.get("model_cutoff_too_fresh") is True


def test_model_cutoff_gate_noop_when_cutoff_before_event(tmp_path):
    lg = _ledger(tmp_path)
    # gpt-4o cutoff 2023-10-01 is strictly before a 2025 event => no-op, eligible.
    result = lg.run_backtest_dataset(
        dataset="d",
        cases=[_backtest_case(agent_model="openai/gpt-4o", resolution_time="2025-06-01T00:00:00Z")],
        allow_calibration_memory=True,
    )
    case_row = result["cases"][0]
    eligible, meta = _calibration_eligible(lg, result["id"], case_row)
    assert eligible is True
    assert "model_cutoff_too_fresh" not in meta
    assert case_row.get("model_cutoff_too_fresh") is False


def test_model_cutoff_gate_noop_for_unknown_model(tmp_path):
    lg = _ledger(tmp_path)
    result = lg.run_backtest_dataset(
        dataset="d",
        cases=[_backtest_case(agent_model="totally-unknown-model", resolution_time="2023-06-01T00:00:00Z")],
        allow_calibration_memory=True,
    )
    case_row = result["cases"][0]
    eligible, meta = _calibration_eligible(lg, result["id"], case_row)
    assert eligible is True
    assert "model_cutoff_too_fresh" not in meta


def test_resolution_time_is_answer_side_field():
    assert "resolution_time" in _ANSWER_SIDE_FIELDS
