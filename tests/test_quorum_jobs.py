"""Integration tests for the quorum background job runner + ledger persistence."""

from __future__ import annotations

import json

import pytest

import forecasting.quorum as quorum
from forecasting.jobs.types import quorum as qj
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    # the quorum type caches nothing; jobs_dir() re-reads the env each call.
    return tmp_path


def _stub_runner_factory(table):
    def make(**_kwargs):
        def runner(model, system, user):
            if "JUDGE" in system:
                return json.dumps(
                    {
                        "probability": 0.4,
                        "rationale": "judge synthesis",
                        "blind_spots": ["regime shift unpriced"],
                        "reasons_up": ["u"],
                        "reasons_down": ["d"],
                        "change_my_mind": ["cmm"],
                    }
                )
            return json.dumps(
                {
                    "probability": table.get(model, 0.5),
                    "confidence_low": 0.2,
                    "confidence_high": 0.7,
                    "rationale": "panelist reasoning",
                    "reasons_up": ["up"],
                    "reasons_down": ["down"],
                    "change_my_mind": ["cmm"],
                    "crux": "the crux",
                }
            )

        return runner

    return make


def test_execute_job_records_quorum_panel_with_disagreement(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the central bank cut rates by Q3 2027?",
        resolution_criteria="Resolves YES if a cut is announced before 2027-10-01.",
        impact="high",
    )

    table = {"a/m1": 0.25, "b/m2": 0.55, "c/m3": 0.62}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _stub_runner_factory(table))

    spec = {
        "question_id": q.id,
        "db": db,
        "models": list(table),
        # No judge specified — it must still run (default-on synthesis step).
        "pool_method": "trimmed_geomean_odds",
        "trim": 1,
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    assert job["panel_run_id"], "quorum should record a panel run"
    assert job["result"]["judge_model"], "judge must default on when unspecified"

    # The panel run is persisted, discriminated as a quorum, and carries the
    # disagreement scalar inside spread_summary.
    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["triggered_by"] == "quorum"
    spread = panel["spread_summary"]
    assert "disagreement_index" in spread and "disagreement_band" in spread

    result = job["result"]
    assert 0.0 < result["aggregate_probability"] < 1.0
    assert result["judge"]["blind_spots"] == ["regime shift unpriced"]
    # Progress was streamed.
    stages = [p["stage"] for p in job["progress"]]
    assert "panelist_done" in stages and "judge_done" in stages and "record" in stages


def test_execute_job_records_delphi_audit(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the central bank cut rates by Q3 2027?",
        resolution_criteria="Resolves YES if a cut is announced before 2027-10-01.",
        impact="high",
    )

    table = {"a/m1": 0.25, "b/m2": 0.55, "c/m3": 0.62}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _stub_runner_factory(table))

    spec = {
        "question_id": q.id,
        "db": db,
        "models": list(table),
        "pool_method": "trimmed_geomean_odds",
        "trim": 1,
        # A single anonymous revision round: run_quorum runs the sealed round,
        # reveals the anonymous distribution, then re-synthesises.
        "delphi_rounds": 1,
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")

    # The job result surfaces the Delphi provenance.
    assert job["result"]["delphi_rounds"] == 1

    # The persisted panel run carries the Delphi round count + the audit artifact,
    # so a completed Delphi quorum has a durable, round-trippable record.
    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["delphi_rounds"] == 1
    assert "rounds" in panel["delphi_audit"]
    # Both the sealed round and the revision round are preserved.
    assert len(panel["delphi_audit"]["rounds"]) == 2


def test_quorum_auto_indicated_respects_scope():
    from forecasting.quorum import quorum_auto_indicated

    off = {"default_enabled": False}
    assert quorum_auto_indicated(off, panel_indicated=True, has_prior_snapshot=False) is False

    hi = {"default_enabled": True, "default_scope": "high_impact"}
    assert quorum_auto_indicated(hi, panel_indicated=True, has_prior_snapshot=True) is True
    assert quorum_auto_indicated(hi, panel_indicated=False, has_prior_snapshot=True) is False

    first = {"default_enabled": True, "default_scope": "first_only"}
    assert quorum_auto_indicated(first, panel_indicated=True, has_prior_snapshot=False) is True
    assert quorum_auto_indicated(first, panel_indicated=True, has_prior_snapshot=True) is False

    always = {"default_enabled": True, "default_scope": "always"}
    assert quorum_auto_indicated(always, panel_indicated=False, has_prior_snapshot=True) is True


def test_execute_job_stamps_process_provenance_in_artifact(home, tmp_path, monkeypatch):
    # ARTIFACT STAMPING: research/delphi rounds + supervisor flag must travel in the
    # panel_run's spread_summary + notes, not only the raw columns.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the index close above 5000 by 2027?",
        resolution_criteria="Resolves YES if close > 5000 before 2027-01-01.",
        impact="high",
    )
    table = {"a/m1": 0.3, "b/m2": 0.5}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _stub_runner_factory(table))

    spec = {"question_id": q.id, "db": db, "models": list(table), "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)
    assert job["status"] == "done", job.get("error")

    panel = ledger.get_panel_run(job["panel_run_id"])
    spread = panel["spread_summary"]
    assert spread["research_rounds"] == 0
    assert spread["delphi_rounds"] == 0
    assert "supervisor_search" in spread
    assert any("quorum provenance" in n for n in panel["notes"])


def test_extract_market_anchor_from_snapshot_component():
    from types import SimpleNamespace

    from forecasting.jobs.types.quorum import extract_market_anchor

    binary_q = SimpleNamespace(id="q1", outcome_space=SimpleNamespace(type="binary"))
    snap = SimpleNamespace(
        ensemble_components={
            "components": [
                {"name": "market", "source": "polymarket:abc", "probability": 0.22},
                {"name": "base", "source": "reference_class", "probability": 0.5},
            ]
        }
    )
    assert extract_market_anchor(None, binary_q, snap) == 0.22

    # Non-binary carries no anchor.
    mc_q = SimpleNamespace(id="q2", outcome_space=SimpleNamespace(type="multiple_choice"))
    assert extract_market_anchor(None, mc_q, snap) is None

    # No market component + no ledger baselines -> no anchor.
    plain = SimpleNamespace(ensemble_components={"components": [{"source": "fred:x", "probability": 0.4}]})
    ledger = SimpleNamespace(list_baseline_comparisons=lambda _qid: [])
    assert extract_market_anchor(ledger, binary_q, plain) is None


def _named_edge_runner_factory(table, *, justification="private unpriced signal"):
    """A runner whose JUDGE names a market-deviation edge (so a large deviation is
    KEPT, not pulled) — the setup that turns a deviation into a deviation BET."""

    def make(**_kwargs):
        def runner(model, system, user):
            if "JUDGE" in system:
                return json.dumps(
                    {
                        "probability": 0.55,
                        "rationale": "judge",
                        "directional_confidence": "medium",
                        "market_deviation_justification": justification,
                    }
                )
            return json.dumps(
                {
                    "probability": table.get(model, 0.5),
                    "rationale": "panelist",
                    "reconcile_reason": "held on the named edge",
                }
            )

        return runner

    return make


def test_execute_job_creates_deviation_bet_on_live_named_edge(home, tmp_path, monkeypatch):
    # UPGRADE 2: a LIVE market run whose reconciled verdict deviates past the
    # threshold WITH a named edge (no pull) creates a scored-later deviation bet.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the merger close by Q4 2027?",
        resolution_criteria="Resolves YES if the deal closes before 2028-01-01.",
        impact="high",
    )
    table = {"a/m1": 0.55, "b/m2": 0.56}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _named_edge_runner_factory(table))
    monkeypatch.setattr(qj, "extract_market_anchor", lambda *a, **k: 0.20)

    spec = {"question_id": q.id, "db": db, "models": list(table), "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)
    assert job["status"] == "done", job.get("error")

    result = job["result"]
    assert result["market_pull_applied"] is False  # named edge -> no pull
    assert job["deviation_bet_id"], "a live named-edge deviation must create a bet"

    bets = ledger.list_deviation_bets(only_open=True)
    assert len(bets) == 1
    bet = bets[0]
    assert bet["market_price"] == 0.20
    assert bet["reconciled_verdict"] > 0.30 and bet["deviation_pp"] > 10.0
    assert bet["named_edge"] == "private unpriced signal"
    assert bet["blind_pool"] is not None  # the market-independent signal is stamped
    assert bet["forecast_origin"] == "live"
    # Progress announced the bet.
    assert any(p["stage"] == "deviation_bet" for p in job["progress"])


def test_execute_job_skips_deviation_bet_on_historical_cutoff(home, tmp_path, monkeypatch):
    # UPGRADE 2: bet creation is foreknowledge-gated — a HISTORICAL cutoff (backtest/
    # replay) creates NO bet, even with a named-edge deviation, so a resolved-question
    # replay can never manufacture a fake edge.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the satellite launch by Q1 2027?",
        resolution_criteria="Resolves YES if launched before 2027-04-01.",
        impact="high",
    )
    table = {"a/m1": 0.55, "b/m2": 0.56}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _named_edge_runner_factory(table))
    monkeypatch.setattr(qj, "extract_market_anchor", lambda *a, **k: 0.20)
    # Force the foreknowledge gate CLOSED (historical cutoff / backtest).
    monkeypatch.setattr(qj, "_cutoff_is_live", lambda *a, **k: False)

    spec = {"question_id": q.id, "db": db, "models": list(table), "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)
    assert job["status"] == "done", job.get("error")
    assert job["deviation_bet_id"] is None
    assert ledger.list_deviation_bets() == []


def test_execute_job_pulls_verdict_toward_market_anchor(home, tmp_path, monkeypatch):
    # A market-linked question with an unjustified over-deviation is pulled back
    # toward the market, and the artifact records the pull.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = ledger.create_question(
        title="Will the bill pass by Q2 2027?",
        resolution_criteria="Resolves YES if enacted before 2027-07-01.",
        impact="high",
    )
    # Panel + judge both sit near 0.55; market anchor is 0.20 (35pp away), and the
    # judge supplies NO justification -> the verdict is pulled toward the market.
    table = {"a/m1": 0.55, "b/m2": 0.56}
    monkeypatch.setattr(quorum, "make_aiagent_runner", _stub_runner_factory(table))
    monkeypatch.setattr(qj, "extract_market_anchor", lambda *a, **k: 0.20)

    spec = {"question_id": q.id, "db": db, "models": list(table), "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)
    assert job["status"] == "done", job.get("error")

    result = job["result"]
    assert result["market_price"] == 0.20
    assert result["market_pull_applied"] is True
    assert result["final_probability"] < 0.55  # pulled toward the market

    panel = ledger.get_panel_run(job["panel_run_id"])
    anchor = panel["spread_summary"]["market_anchor"]
    assert anchor["pull_applied"] is True and anchor["market_price"] == 0.20
