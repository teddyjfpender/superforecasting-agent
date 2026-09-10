from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.forecast_smoke_test import EXPECTED_AGENT_PROTOCOL_SUITE_CASES, EXPECTED_SOURCE_ADAPTERS


def test_forecast_smoke_required_source_catalog_includes_fiscal_adapter():
    assert "treasury" in EXPECTED_SOURCE_ADAPTERS
    assert "socrata" in EXPECTED_SOURCE_ADAPTERS
    assert "ckan" in EXPECTED_SOURCE_ADAPTERS
    assert "githubcommits" in EXPECTED_SOURCE_ADAPTERS
    assert "githubactions" in EXPECTED_SOURCE_ADAPTERS
    assert "coingecko" in EXPECTED_SOURCE_ADAPTERS
    assert "yahoo" in EXPECTED_SOURCE_ADAPTERS
    assert "secfacts" in EXPECTED_SOURCE_ADAPTERS
    assert "fivethirtyeight" in EXPECTED_SOURCE_ADAPTERS
    assert "airquality" in EXPECTED_SOURCE_ADAPTERS
    assert "weatherhistory" in EXPECTED_SOURCE_ADAPTERS
    assert "reliefweb" in EXPECTED_SOURCE_ADAPTERS
    assert "bluesky" in EXPECTED_SOURCE_ADAPTERS
    assert "mastodon" in EXPECTED_SOURCE_ADAPTERS
    assert "whogho" in EXPECTED_SOURCE_ADAPTERS
    assert "fema" in EXPECTED_SOURCE_ADAPTERS


# The subprocess drives the full forecast lifecycle (~160s in isolation) and
# spawns its own CPU-heavy child commands. Under xdist load those children
# compete with the worker pool, so the budget must be generous enough that a
# legitimate run never trips it while a genuine hang still surfaces. The pytest
# cap must exceed the subprocess timeout so the subprocess deadline wins first
# with a captured-output assertion instead of an opaque signal kill.
@pytest.mark.timeout(480)
def test_forecast_smoke_script_runs_local_lifecycle(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    db_path = tmp_path / "forecast-smoke.db"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/forecast_smoke_test.py",
            "--db",
            str(db_path),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=420,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[forecast-smoke] snapshot:" in result.stdout
    assert "[forecast-smoke] source_adapters:" in result.stdout
    assert "[forecast-smoke] benchmark_datasets: 5" in result.stdout
    assert "[forecast-smoke] question_id: fq_" in result.stdout
    assert "[forecast-smoke] backtest_run_id: bt_" in result.stdout
    assert "[forecast-smoke] agent_protocol_backtest_run_id: bt_" in result.stdout
    assert f"[forecast-smoke] agent_protocol_prompt_packets: {EXPECTED_AGENT_PROTOCOL_SUITE_CASES}" in result.stdout
    assert f"[forecast-smoke] agent_protocol_suite_scored_cases: {EXPECTED_AGENT_PROTOCOL_SUITE_CASES}" in result.stdout
    assert "[forecast-smoke] pilot_report_checks: 9/9" in result.stdout
    assert "[forecast-smoke] pilot_cohort_dry_run_questions: 1" in result.stdout
    assert "[forecast-smoke] pilot_cohort_example_questions: 5" in result.stdout
    assert "[forecast-smoke] packet_import_questions:" in result.stdout
    assert "[forecast-smoke] pilot_aggregate_live_scores: 1" in result.stdout
    assert "[forecast-smoke] readiness_verdict:" in result.stdout
    assert "[forecast-smoke] readiness_gaps: 1" in result.stdout
    assert f"[forecast-smoke] readiness_agent_protocol_scores: {EXPECTED_AGENT_PROTOCOL_SUITE_CASES}" in result.stdout
    assert "[forecast-smoke] live_baseline_comparisons: 1" in result.stdout
    assert "[forecast-smoke] doctor_status: benchmark_evidence_ready_live_claim_unproven" in result.stdout
    assert "[forecast-smoke] pilot_bundle_export_included: true" in result.stdout
    assert "[forecast-smoke] forecast smoke test passed" in result.stdout
    assert db_path.exists()


@pytest.mark.timeout(480)
def test_lifecycle_without_backtest_preserves_readiness_gaps(tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/forecast_smoke_test.py", "--db", str(tmp_path / "ledger.db"), "--skip-backtest"],
        cwd=repo_root, capture_output=True, text=True, timeout=420,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[forecast-smoke] forecast smoke test passed" in result.stdout
    assert "[forecast-smoke] readiness_agent_protocol_scores: 0" in result.stdout
    assert "live_claim_unproven" in result.stdout
