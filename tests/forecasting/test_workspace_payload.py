"""Tests for the forecasts-workspace payload builder + gateway RPC."""

from __future__ import annotations

import json

import pytest

from forecasting.dashboard import (
    _distribution_headline,
    _distribution_view,
    _headline_numeric,
    _short_candidate_label,
    build_workspace_payload,
    format_probability,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace


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


# ── Distribution / vote-share headline (probability_display) — no more raw JSON ──


def test_short_candidate_label_surname_and_truncation():
    assert _short_candidate_label("Nigel Farage") == "Farage"
    assert _short_candidate_label("Count Binface") == "Binface"
    assert _short_candidate_label("Laurence Fox") == "Fox"
    assert _short_candidate_label("Fox") == "Fox"  # already short
    assert _short_candidate_label("Other official candidates") == "Other offi…"  # 3 words → truncate


def test_distribution_headline_sorts_desc_leader_first_no_json():
    # The Clacton bug: a probability dict rendered as insertion-ordered JSON, which
    # truncated the leader (Farage 67). Now value-sorted, leader first, 1dp, no braces.
    headline = _distribution_headline(
        {
            "Count Binface": 16.5,
            "Laurence Fox": 4.0,
            "Nigel Farage": 67.0,
            "Other official candidates": 12.5,
        }
    )
    assert headline == "Farage 67.0 · Binface 16.5 · Other offi… 12.5 · Fox 4.0"
    assert "{" not in headline and '"' not in headline


def test_distribution_headline_fraction_scale_becomes_percent():
    assert _distribution_headline({"Yes": 0.62, "No": 0.38}) == "Yes 62.0 · No 38.0"


def test_distribution_headline_strips_stat_keys_and_needs_two_candidates():
    # Hybrid payload: candidate shares + a bolted-on leader distribution. Only the
    # candidate entries belong in the headline — never mean/median/q05/interval_*.
    headline = _distribution_headline(
        {
            "Andy Biggs": 64.0,
            "David Schweikert": 27.0,
            "Other": 9.0,
            "mean": 64.0,
            "median": 63.36,
            "q05": 43.29,
            "interval_90_low": 43.29,
        }
    )
    # "Andy Biggs" (10 chars) is already short → kept whole; "David Schweikert" (16)
    # collapses to its surname; stat keys never appear.
    assert headline == "Andy Biggs 64.0 · Schweikert 27.0 · Other 9.0"
    # A pure moment dict is not a categorical PMF → None (falls back).
    assert _distribution_headline({"mean": 3.1, "sd": 0.4}) is None
    assert _distribution_headline({"Yes": 0.62}) is None  # single candidate


def test_distribution_headline_ignores_continuous_distribution_shapes():
    # A CPI-style continuous distribution (moments + intervals + bucket PMF) is NOT a
    # categorical headline — its bucket/equivalent keys must not become "candidates".
    # It falls back to the JSON dump (the TUI renders it via the μ/σ path anyway).
    cpi = {
        "mean": 4.23,
        "sd": 0.1,
        "median": 4.2,
        "interval_90_low": 4.05,
        "interval_90_high": 4.41,
        "equivalent_normal_mean": 4.23,
        "bucket_le_4_0": 0.2,
        "bucket_4_0_4_2": 0.5,
        "bucket_ge_4_2": 0.3,
    }
    assert _distribution_headline(cpi) is None
    assert format_probability(cpi) == json.dumps(cpi, sort_keys=True)


def test_format_probability_dict_uses_headline_not_json():
    formatted = format_probability({"Count Binface": 16.5, "Nigel Farage": 67.0, "Laurence Fox": 4.0})
    assert formatted == "Farage 67.0 · Binface 16.5 · Fox 4.0"
    # Scalars keep their 3-dp form; a non-PMF dict still falls back to JSON.
    assert format_probability(0.52) == "0.520"
    assert format_probability({"mean": 3.1, "sd": 0.4}) == json.dumps({"mean": 3.1, "sd": 0.4}, sort_keys=True)
    assert format_probability(None) == "-"
    assert _headline_numeric(-2.0) == -2.0


# ── _distribution_view (CPI-style payloads) ──────────────────────────────────

CPI_PAYLOAD = {
    "bucket_4_1": 0.1735,
    "bucket_4_2": 0.3789,
    "bucket_4_3": 0.2984,
    "bucket_ge_4_4": 0.1197,
    "bucket_le_4_0": 0.0296,
    "equivalent_normal_mean": 4.23195,
    "equivalent_normal_sd": 0.09819,
    "interval_50_high": 4.297,
    "interval_50_low": 4.166,
    "interval_90_high": 4.398,
    "interval_90_low": 4.071,
    "mean": 4.23195,
    "median": 4.231,
    "sd": 0.09819,
}


def test_distribution_view_splits_moments_intervals_and_pmf():
    view = _distribution_view(CPI_PAYLOAD)
    assert view is not None
    assert view["mean"] == pytest.approx(4.23195)
    assert view["median"] == pytest.approx(4.231)
    assert view["sd"] == pytest.approx(0.09819)
    assert view["ci50"] == [pytest.approx(4.166), pytest.approx(4.297)]
    assert view["ci90"] == [pytest.approx(4.071), pytest.approx(4.398)]
    # PMF contains ONLY the bucket mass, sorted descending, no moments/intervals
    labels = [row["label"] for row in view["pmf"]]
    assert labels[0] == "bucket_4_2"
    assert set(labels) == {"bucket_le_4_0", "bucket_4_1", "bucket_4_2", "bucket_4_3", "bucket_ge_4_4"}
    assert "mean" not in labels and "interval_90_high" not in labels
    assert sum(row["probability"] for row in view["pmf"]) == pytest.approx(1.0, abs=0.01)


def test_distribution_view_derives_intervals_from_sd_when_absent():
    view = _distribution_view({"mean": 4.0, "sd": 0.1})
    assert view is not None
    # 90% ~ mean ± 1.6449 sd ; 50% ~ mean ± 0.6745 sd
    assert view["ci90"][0] == pytest.approx(4.0 - 1.6449 * 0.1, abs=1e-3)
    assert view["ci90"][1] == pytest.approx(4.0 + 1.6449 * 0.1, abs=1e-3)
    assert view["pmf"] is None


def test_distribution_view_uses_equivalent_normal_as_mean_sd_fallback():
    view = _distribution_view({"equivalent_normal_mean": 4.2, "equivalent_normal_sd": 0.1, "bucket_a": 0.4, "bucket_b": 0.6})
    assert view["mean"] == pytest.approx(4.2)
    assert view["sd"] == pytest.approx(0.1)
    assert view["pmf"] is not None and len(view["pmf"]) == 2


def test_distribution_view_categorical_pmf_has_no_mean():
    view = _distribution_view({"Republican": 0.59, "Democratic": 0.4, "Other": 0.01})
    assert view is not None
    assert view["mean"] is None
    assert [row["label"] for row in view["pmf"]][0] == "Republican"


def test_distribution_view_returns_none_for_scalar():
    assert _distribution_view(0.52) is None
    assert _distribution_view(None) is None


def test_distribution_view_ignores_stray_non_pmf_numbers():
    # values that don't sum to ~1 are not treated as a PMF
    view = _distribution_view({"mean": 4.0, "sd": 0.1, "stray": 0.2})
    assert view["pmf"] is None


def test_workspace_payload_marks_distribution_kind_and_band(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="May 2026 CPI-U YoY",
        resolution_criteria="BLS first-published May 2026 CPI-U all-items 12-month percent change.",
        outcome_space=OutcomeSpace(type="distribution", units="percent year-over-year", bounds=[-5, 15]),
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=CPI_PAYLOAD,
        rationale="bucket mixture",
        as_of="2026-05-28T00:00:00Z",
        confidence=0.84,
    )
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["headline_kind"] == "distribution"
    assert forecast["headline_probability"] == pytest.approx(4.23195)
    assert forecast["distribution"]["pmf"] is not None
    # the history band must be the distribution's own 90% interval, NOT a probability
    last = forecast["history"][-1]
    assert last["band_low"] == pytest.approx(4.071)
    assert last["band_high"] == pytest.approx(4.398)
    assert last["headline_probability"] == pytest.approx(4.23195)


def test_workspace_payload_numeric_summary_uses_outcome_units_and_band(tmp_path):
    """A numeric mean below 1 is an outcome value, never a probability."""
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Q2 ECI total compensation QoQ",
        resolution_criteria="BLS first-published Q2 ECI percent change.",
        outcome_space=OutcomeSpace(type="numeric", units="percent QoQ", bounds=[-5, 5]),
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution={
            "mean": 0.93,
            "median": 0.90,
            "standard_deviation": 0.15,
            "interval_50_low": 0.83,
            "interval_50_high": 1.03,
            "interval_90_low": 0.70,
            "interval_90_high": 1.20,
        },
        rationale="component bridge",
        as_of="2026-07-14T00:00:00Z",
    )

    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["outcome_type"] == "numeric"
    assert forecast["headline_kind"] == "distribution"
    assert forecast["headline_probability"] == pytest.approx(0.93)
    assert forecast["distribution"]["ci90"] == [pytest.approx(0.70), pytest.approx(1.20)]
    last = forecast["history"][-1]
    assert last["headline_probability"] == pytest.approx(0.93)
    assert last["band_low"] == pytest.approx(0.70)
    assert last["band_high"] == pytest.approx(1.20)


def test_workspace_payload_categorical_stays_probability_kind(tmp_path):
    ledger = _ledger(tmp_path)
    q = ledger.create_question(
        title="Texas Senate winner",
        resolution_criteria="Certified 2026 Texas US Senate winner by party.",
        outcome_space=OutcomeSpace(type="categorical", choices=["Republican", "Democratic", "Other"]),
    )
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution={"Republican": 0.59, "Democratic": 0.4, "Other": 0.01},
        rationale="polls",
        as_of="2026-05-28T00:00:00Z",
    )
    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["headline_kind"] == "probability"
    assert forecast["headline_probability"] == pytest.approx(0.59)
    # categorical history has no distribution band (falls back to confidence/panel in the UI)
    assert forecast["history"][-1]["band_low"] is None


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
