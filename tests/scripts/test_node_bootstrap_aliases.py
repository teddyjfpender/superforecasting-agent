"""Regression tests for forecast-native Node bootstrap env aliases."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source_bootstrap(script: str, env: dict[str, str]) -> str:
    result = subprocess.run(
        ["bash", "-lc", script],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=15,
        check=True,
    )
    return result.stdout.strip()


def _base_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "SUPERFORECASTING_AGENT_NODE_MIN_VERSION",
        "FORECAST_NODE_MIN_VERSION",
        "HERMES_NODE_MIN_VERSION",
        "SUPERFORECASTING_AGENT_NODE_TARGET_MAJOR",
        "FORECAST_NODE_TARGET_MAJOR",
        "HERMES_NODE_TARGET_MAJOR",
        "SUPERFORECASTING_AGENT_NODE_AVAILABLE",
        "FORECAST_NODE_AVAILABLE",
        "HERMES_NODE_AVAILABLE",
    ):
        env.pop(key, None)
    return env


def test_node_bootstrap_prefers_forecast_native_version_aliases():
    env = _base_env()
    env["SUPERFORECASTING_AGENT_NODE_MIN_VERSION"] = "21"
    env["FORECAST_NODE_MIN_VERSION"] = "20"
    env["HERMES_NODE_MIN_VERSION"] = "19"
    env["SUPERFORECASTING_AGENT_NODE_TARGET_MAJOR"] = "23"
    env["FORECAST_NODE_TARGET_MAJOR"] = "22"
    env["HERMES_NODE_TARGET_MAJOR"] = "21"

    output = _source_bootstrap(
        """
        source scripts/lib/node-bootstrap.sh
        printf '%s,%s,%s,%s,%s,%s' \\
          "$SUPERFORECASTING_AGENT_NODE_MIN_VERSION" \\
          "$FORECAST_NODE_MIN_VERSION" \\
          "$HERMES_NODE_MIN_VERSION" \\
          "$SUPERFORECASTING_AGENT_NODE_TARGET_MAJOR" \\
          "$FORECAST_NODE_TARGET_MAJOR" \\
          "$HERMES_NODE_TARGET_MAJOR"
        """,
        env,
    )

    assert output == "21,21,21,23,23,23"


def test_node_bootstrap_sets_forecast_native_available_aliases():
    output = _source_bootstrap(
        """
        source scripts/lib/node-bootstrap.sh
        _nb_set_node_available true
        printf '%s,%s,%s' \\
          "$SUPERFORECASTING_AGENT_NODE_AVAILABLE" \\
          "$FORECAST_NODE_AVAILABLE" \\
          "$HERMES_NODE_AVAILABLE"
        """,
        _base_env(),
    )

    assert output == "true,true,true"
