"""The CLI report and advisory lookup must use one component inventory."""

import argparse
import json
from unittest.mock import Mock

from superforecasting_agent.runtime import security_audit as audit


def test_cli_audits_the_same_inventory_it_counts(monkeypatch, capsys, tmp_path):
    first = audit.Component("first", "1.0", "PyPI", "venv")
    second = audit.Component("later", "2.0", "PyPI", "venv")
    discover = Mock(side_effect=[[first], [second]])
    query = Mock(return_value={first: ["FIXTURE-1"]})
    monkeypatch.setattr(audit, "get_agent_home", lambda: tmp_path)
    monkeypatch.setattr(audit, "_discover_venv", discover)
    monkeypatch.setattr(audit, "_osv_query_batch", query)
    monkeypatch.setattr(audit, "_osv_fetch_details", lambda _: {
        "FIXTURE-1": audit.Vulnerability("FIXTURE-1", "LOW"),
    })
    args = argparse.Namespace(skip_venv=False, skip_plugins=True, skip_mcp=True, json=True, fail_on="critical")

    assert audit.cmd_security_audit(args) == 0

    discover.assert_called_once_with()
    query.assert_called_once_with([first])
    report = json.loads(capsys.readouterr().out)
    assert report["total_components_scanned"] == 1
    assert report["findings"][0]["package"] == "first"
