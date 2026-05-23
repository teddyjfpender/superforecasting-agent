from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_exposes_forecast_first_console_scripts():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]
    scripts = project["scripts"]

    assert project["name"] == "superforecasting-agent"
    assert "command-line forecasting desk" in project["description"]
    assert scripts["forecast"] == "superforecasting_agent.cli:main"
    assert scripts["superforecast"] == "superforecasting_agent.cli:main"
    assert scripts["superforecasting-agent"] == "superforecasting_agent.cli:main"
    assert scripts["superforecasting-agent-acp"] == "acp_adapter.entry:main"
    assert scripts["superforecast-acp"] == "acp_adapter.entry:main"
    assert scripts["hermes"] == "hermes_cli.main:main"
    assert scripts["hermes-agent"] == "superforecasting_agent.cli:main"
    assert scripts["hermes-acp"] == "acp_adapter.entry:main"


def test_pyproject_packages_forecast_benchmark_data():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert "data/*.csv" in package_data["forecasting"]
    assert "data/*.md" in package_data["forecasting"]
