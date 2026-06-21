"""Tests for the Market Models agent tools + toolset registration."""

from __future__ import annotations

import json

import tools.desk_forecast_tool  # noqa: F401 (self-registers)
import tools.market_compute_tool  # noqa: F401
import tools.market_presentation_tool as mpt
import toolsets
from tools.registry import registry


def test_tools_registered_under_market_models_toolset():
    for name in ("market_compute", "emit_market_presentation", "read_desk_forecast"):
        entry = registry._tools.get(name)
        assert entry is not None, f"{name} not registered"
        assert entry.toolset == "market-models"


def test_market_models_toolset_resolves():
    ts = toolsets.get_toolset("market-models")
    assert ts is not None
    for name in ("market_compute", "emit_market_presentation", "read_desk_forecast"):
        assert name in ts["tools"]
    assert "forecasting" in ts["includes"] and "web" in ts["includes"]


def test_market_compute_tool_returns_block():
    out = json.loads(tools.market_compute_tool.market_compute_tool(
        {"model_type": "ols", "payload": {"x": [0, 1, 2], "y": [1, 3, 5]}}
    ))
    assert out["ok"] is True
    assert out["block"]["type"] == "regression"
    assert out["summary"]["slope"] == 2.0


def test_market_compute_tool_requires_model_type():
    out = json.loads(tools.market_compute_tool.market_compute_tool({"payload": {}}))
    assert "error" in out


def test_emit_tool_validates_and_stashes():
    mpt.reset_emitted()
    ok = json.loads(mpt.emit_market_presentation_tool(
        {"presentation": {"title": "t", "blocks": [{"type": "metric", "label": "R2", "value": 0.9}]}}
    ))
    assert ok["valid"] is True
    got = mpt.take_emitted()
    assert got["presentation"]["title"] == "t"

    mpt.reset_emitted()
    bad = json.loads(mpt.emit_market_presentation_tool(
        {"presentation": {"title": "t", "blocks": [{"type": "regression", "id": "r"}]}}
    ))
    assert bad["valid"] is False and bad["errors"]
    # still stashed so the orchestrator can salvage
    assert mpt.take_emitted() is not None
