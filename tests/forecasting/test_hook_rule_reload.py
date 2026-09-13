"""Rule edits must reach validation even when identity and timestamps do not change."""
import os

import yaml

from forecasting.hooks import HookContext, Severity
from forecasting.hooks.loader import load_user_rules


def specification():
    return {
        "id": "fixture-drivers",
        "severity": "error",
        "check": {"signal": "components.count", "op": ">=", "value": 2},
        "message": "More drivers required",
    }


def passes(config):
    rule, = load_user_rules(config)
    context = HookContext(
        question_id="fixture", forecast_origin="live", event="update", component_count=3,
    )
    return rule.evaluate(context, Severity.ERROR).passed


def test_in_place_inline_policy_edit_is_not_hidden_by_list_identity():
    rule = specification()
    config = {"rules": [rule]}
    assert passes(config)
    rule["check"]["value"] = 5
    assert not passes(config)


def test_same_size_replacement_with_preserved_timestamp_is_reloaded(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    path = tmp_path / "rules.yaml"
    raw = yaml.safe_dump([specification()])
    path.write_text(raw, encoding="utf-8")
    config = {"rules_file": "rules.yaml"}
    assert passes(config)
    before = path.stat()
    revised = raw.replace("value: 2", "value: 5")
    assert revised != raw and len(revised) == len(raw)
    path.write_text(revised, encoding="utf-8")
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert not passes(config)


def test_switching_profiles_uses_each_profiles_rules(tmp_path, monkeypatch):
    from superforecasting_agent import constants

    homes = [tmp_path / "first", tmp_path / "second"]
    for index, home in enumerate(homes):
        home.mkdir()
        rule = specification()
        rule["check"]["value"] = 2 if index == 0 else 5
        (home / "rules.yaml").write_text(yaml.safe_dump([rule]), encoding="utf-8")
    monkeypatch.setattr(constants, "get_agent_home", lambda: homes[0])
    assert passes({"rules_file": "rules.yaml"})
    monkeypatch.setattr(constants, "get_agent_home", lambda: homes[1])
    assert not passes({"rules_file": "rules.yaml"})
