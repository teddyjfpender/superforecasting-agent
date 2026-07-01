"""Integration tests for the quorum background job runner + ledger persistence."""

from __future__ import annotations

import json

import pytest

import forecasting.quorum as quorum
from forecasting import quorum_jobs as qj
from forecasting.ledger import ForecastLedger


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    # quorum_jobs caches nothing; jobs_dir() re-reads the env each call.
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
