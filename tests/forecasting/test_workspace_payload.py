"""Tests for the forecasts-workspace payload builder + gateway RPC."""

from __future__ import annotations

import json

import pytest

from forecasting.dashboard import _headline_numeric, build_workspace_payload
from forecasting.ledger import ForecastLedger


def _ledger(tmp_path) -> ForecastLedger:
    ledger = ForecastLedger(db_path=str(tmp_path / "workspace.db"))
    ledger.initialize_schema()
    return ledger


def _seed_texas(ledger) -> str:
    q = ledger.create_question(
        title="Will the Republican win the Texas Senate seat?",
        resolution_criteria="Official certified 2026 Texas US Senate result names the Republican winner.",
        domain="us-politics",
        topics=["elections", "senate"],
        impact="high",
        close_time="2026-11-03T00:00:00Z",
        decision_owner="Desk lead",
        action_threshold="If P(R) < 0.45, flag as competitive",
        update_triggers=["FEC filing update", {"mechanism": "270towin rating", "threshold": "toss-up"}],
    )
    for prob, as_of, up in [
        (0.55, "2026-05-01T00:00:00Z", ["red state base rate"]),
        (0.50, "2026-05-15T00:00:00Z", ["poll tightened"]),
        (0.52, "2026-05-29T00:00:00Z", ["turnout model"]),
    ]:
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=prob,
            rationale="update",
            as_of=as_of,
            confidence=0.65,
            reasons_up=up,
            reasons_down=["incumbent edge"],
            change_my_mind=["poll lead > 5pts"],
        )
    ledger.add_evidence(
        question_id=q.id,
        source_or_note="https://www.fec.gov/data",
        claim="FEC Q1 filing shows fundraising gap",
        stance="increases",
        reliability_rating=0.8,
        relevance_rating=0.7,
        source_type="url",
        archive_url_snapshot=False,
    )
    ledger.record_panel_run(
        question_id=q.id,
        estimates=[
            {"perspective": "outside", "probability": 0.5, "crux": "base rate"},
            {"perspective": "inside", "probability": 0.58, "crux": "fundraising"},
            {"perspective": "market", "probability": 0.54},
            {"perspective": "red_team", "probability": 0.42, "crux": "retirement"},
            {"perspective": "sanity", "probability": 0.52},
        ],
        trim=1,
        triggered_by="first_forecast",
    )
    return q.id


# ── _headline_numeric ────────────────────────────────────────────────────────


def test_headline_numeric_float_passthrough():
    assert _headline_numeric(0.42) == 0.42


def test_headline_numeric_bool_is_none():
    assert _headline_numeric(True) is None


def test_headline_numeric_probability_dict_takes_max():
    assert _headline_numeric({"a": 0.2, "b": 0.5, "c": 0.3}) == 0.5


def test_headline_numeric_mean_distribution():
    assert _headline_numeric({"mean": 3.1, "sd": 0.4}) == 3.1


def test_headline_numeric_non_probability_dict_takes_first_numeric():
    assert _headline_numeric({"value": 1200.0}) == 1200.0


def test_headline_numeric_empty_or_textual_is_none():
    assert _headline_numeric({}) is None
    assert _headline_numeric("nonsense") is None
    assert _headline_numeric(None) is None


def test_headline_numeric_rejects_non_finite_values():
    # NaN/Inf would corrupt the time-series chart — they must be dropped.
    assert _headline_numeric(float("nan")) is None
    assert _headline_numeric(float("inf")) is None
    assert _headline_numeric(float("-inf")) is None
    assert _headline_numeric({"mean": float("inf")}) is None
    assert _headline_numeric({"a": float("nan"), "b": float("inf")}) is None


def test_headline_numeric_keeps_finite_out_of_range_numeric():
    # A CPI-style mean of 3.1 is a legitimate numeric outcome, not a probability.
    assert _headline_numeric(3.1) == 3.1
    assert _headline_numeric({"mean": 3.1, "sd": 0.4}) == 3.1
    assert _headline_numeric(-2.0) == -2.0


# ── build_workspace_payload ──────────────────────────────────────────────────


def test_workspace_payload_lists_active_forecasts(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    payload = build_workspace_payload(ledger=ledger)
    assert payload["active_count"] == 1
    assert payload["product"]
    assert payload["generated_at"]
    assert len(payload["forecasts"]) == 1


def test_workspace_payload_includes_probability_time_series(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    headlines = [point["headline_probability"] for point in forecast["history"]]
    assert headlines == [0.55, 0.50, 0.52]
    # delta is current - previous
    assert forecast["delta"] == pytest.approx(0.02, abs=1e-9)
    assert forecast["headline_probability"] == 0.52
    assert forecast["confidence"] == 0.65


def test_workspace_payload_includes_decision_card_and_reasons(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["decision_owner"] == "Desk lead"
    assert forecast["action_threshold"].startswith("If P(R)")
    assert len(forecast["update_triggers"]) == 2
    assert forecast["decision_readiness_issues"] == []
    assert forecast["reasons_up"] == ["turnout model"]
    assert forecast["reasons_down"] == ["incumbent edge"]
    assert forecast["change_my_mind"] == ["poll lead > 5pts"]


def test_workspace_payload_includes_panel_with_spread_and_trim(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    panel = forecast["panel"]
    assert panel is not None
    assert panel["aggregate_probability"] == pytest.approx(0.52, abs=0.05)
    assert panel["spread"]["min"] == pytest.approx(0.42)
    assert panel["spread"]["max"] == pytest.approx(0.58)
    trimmed = {e["perspective"] for e in panel["estimates"] if e["trimmed"]}
    assert trimmed == {"inside", "red_team"}


def test_workspace_payload_includes_recent_evidence(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["evidence_count"] == 1
    assert forecast["evidence"][0]["stance"] == "increases"
    assert forecast["evidence"][0]["reliability_rating"] == 0.8


def test_workspace_payload_flags_missing_decision_card(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.create_question(
        title="Will GDP grow above 2% in Q2?",
        resolution_criteria="BEA second estimate of Q2 2026 real GDP annualized growth exceeds 2.0%.",
    )
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert "missing decision_owner" in forecast["decision_readiness_issues"]
    assert forecast["panel"] is None
    assert forecast["history"] == []
    assert forecast["headline_probability"] is None


def test_workspace_payload_passes_distribution_probability_raw(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="May 2026 CPI-U YoY bucket",
        resolution_criteria="BLS May 2026 CPI-U YoY release falls in one of the named buckets.",
        outcome_space=__import__("forecasting.models", fromlist=["OutcomeSpace"]).OutcomeSpace(
            type="categorical", choices=["lt_3_0", "3_0_3_2", "gt_3_2"]
        ),
    )
    dist = {"lt_3_0": 0.25, "3_0_3_2": 0.45, "gt_3_2": 0.30}
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=dist,
        rationale="nowcast",
        as_of="2026-05-28T00:00:00Z",
    )
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["outcome_type"] == "categorical"
    assert forecast["probability"] == dist
    assert forecast["headline_probability"] == 0.45


def test_workspace_payload_is_json_serializable(tmp_path):
    ledger = _ledger(tmp_path)
    _seed_texas(ledger)
    payload = build_workspace_payload(ledger=ledger)
    # Must round-trip cleanly for the JSON-RPC gateway.
    assert json.loads(json.dumps(payload))["active_count"] == 1


def test_workspace_payload_history_capped(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Frequently updated forecast",
        resolution_criteria="Resolves on the named index close on 2026-12-31.",
    )
    for i in range(10):
        ledger.create_snapshot(
            question_id=q.id,
            probability_or_distribution=0.5,
            rationale=f"update {i}",
            as_of=f"2026-05-{i + 1:02d}T00:00:00Z",
        )
    forecast = build_workspace_payload(ledger=ledger, history_limit=4)["forecasts"][0]
    assert len(forecast["history"]) == 4
    assert forecast["snapshot_count"] == 10


def test_export_question_packet_includes_panel_runs(tmp_path):
    ledger = _ledger(tmp_path)
    qid = _seed_texas(ledger)
    packet = json.loads(ledger.export_question(qid, fmt="json"))
    assert "panel_runs" in packet
    assert len(packet["panel_runs"]) == 1
    assert packet["panel_runs"][0]["aggregate_probability"] is not None
