"""RPC policy writes preserve the shared service's input semantics."""
import argparse

import pytest

from forecasting.hooks import store
from tui_gateway import server


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def request(target, value):
    return server.handle_request({
        "id": 1, "method": "forecast.hooks.set",
        "params": {"target": target, "value": value},
    })


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None, [], {}])
def test_invalid_boolean_has_identical_service_and_rpc_error(value, isolated_profile):
    with pytest.raises(store.HookWriteError) as error:
        store.set_enabled(value)
    response = request("enabled", value)
    assert response["error"]["message"] == str(error.value)
    assert not (isolated_profile / "config.yaml").exists()


@pytest.mark.parametrize("value", [False, True])
def test_real_boolean_round_trips_unchanged(value, isolated_profile):
    import yaml

    assert request("enabled", value)["result"]["enabled"] is value
    config = yaml.safe_load((isolated_profile / "config.yaml").read_text(encoding="utf-8"))
    assert config["forecasting"]["hooks"]["enabled"] is value


def test_invalid_profile_is_not_coerced_to_text(isolated_profile):
    assert request("profile", [])["error"]["message"] == "profile must be a string"
    assert not (isolated_profile / "config.yaml").exists()


def test_cli_disable_reports_same_validation_error_without_traceback():
    from forecasting.cli.core import _cmd_hooks_disable

    with pytest.raises(store.HookWriteError) as error:
        store.disable("unknown-rule")
    with pytest.raises(SystemExit) as cli_error:
        _cmd_hooks_disable(argparse.Namespace(rule_id="unknown-rule"))
    assert str(cli_error.value) == str(error.value)


def test_malformed_rule_has_same_field_issue_in_preview_and_save(isolated_profile):
    raw = {"id": "fixture-rule", "check": [["signal", "components.count"]]}
    responses = []
    for method in ("forecast.hooks.preview", "forecast.hooks.save_rule"):
        response = server.handle_request({"id": 1, "method": method, "params": {"rule": raw}})
        assert "result" in response, response
        responses.append(response["result"]["issues"])
    assert responses[0] == responses[1]
    assert responses[0][0]["field"] == "check"
    assert not (isolated_profile / "hooks/rules.yaml").exists()
