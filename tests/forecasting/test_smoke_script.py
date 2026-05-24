from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.forecast_smoke_test import EXPECTED_SOURCE_ADAPTERS


def test_forecast_smoke_required_source_catalog_includes_fiscal_adapter():
    assert "treasury" in EXPECTED_SOURCE_ADAPTERS
    assert "socrata" in EXPECTED_SOURCE_ADAPTERS
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
        timeout=90,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "[forecast-smoke] source_adapters:" in result.stdout
    assert "[forecast-smoke] benchmark_datasets: 4" in result.stdout
    assert "[forecast-smoke] question_id: fq_" in result.stdout
    assert "[forecast-smoke] backtest_run_id: bt_" in result.stdout
    assert "[forecast-smoke] agent_protocol_backtest_run_id: bt_" in result.stdout
    assert "[forecast-smoke] pilot_report_checks: 7/7" in result.stdout
    assert "[forecast-smoke] pilot_cohort_dry_run_questions: 1" in result.stdout
    assert "[forecast-smoke] pilot_aggregate_live_scores: 1" in result.stdout
    assert "[forecast-smoke] readiness_verdict:" in result.stdout
    assert "[forecast-smoke] readiness_gaps: 2" in result.stdout
    assert "[forecast-smoke] forecast smoke test passed" in result.stdout
    assert db_path.exists()
