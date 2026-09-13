"""Read-only normalized profile access without CLI lifecycle side effects."""

import json

import pytest
import yaml

from superforecasting_agent.storage.configuration import read_configuration


def test_missing_profile_returns_defaults_without_creating_home(tmp_path):
    from superforecasting_agent.configuration import resolve_config

    home = tmp_path / "missing-home"
    assert read_configuration(home / "config.yaml") == resolve_config({})
    assert not home.exists()


def test_profile_switching_and_returned_mutation_do_not_leak(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    for home, model in [(first, "first-model"), (second, "second-model")]:
        home.mkdir()
        (home / "config.yaml").write_text(json.dumps({"model": model}), encoding="utf-8")

    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(first))
    values = read_configuration()
    assert values["model"] == "first-model"
    values["terminal"]["backend"] = "mutated"
    assert read_configuration()["terminal"]["backend"] == "local"
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(second))
    assert read_configuration()["model"] == "second-model"
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(first))
    assert read_configuration()["model"] == "first-model"


@pytest.mark.parametrize("contents", ["model: [", "- invalid-root", "model: [invalid-model]"])
def test_malformed_profile_uses_defaults_and_recovers(tmp_path, contents):
    from superforecasting_agent.configuration import resolve_config

    path = tmp_path / "config.yaml"
    path.write_text(contents, encoding="utf-8")
    assert read_configuration(path) == resolve_config({})
    path.write_text("model: repaired\n", encoding="utf-8")
    assert read_configuration(path)["model"] == "repaired"


@pytest.mark.parametrize("flag", [
    "SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "FORECAST_IGNORE_USER_CONFIG",
    "HERMES_IGNORE_USER_CONFIG",
])
def test_ignore_config_flags_apply_without_reading_profile(tmp_path, monkeypatch, flag):
    from superforecasting_agent.configuration import resolve_config
    from superforecasting_agent.storage import configuration

    monkeypatch.setenv(flag, "1")
    monkeypatch.setattr(configuration._value_reader, "load",
                        lambda path: pytest.fail("ignored configuration was read"))
    assert read_configuration(tmp_path / "config.yaml") == resolve_config({})


def test_domain_consumers_share_profile_values(tmp_path, monkeypatch):
    from forecasting.hooks.engine import load_hook_config
    from forecasting.ledger.model_scoring import _skill_weights_enabled
    from forecasting.ledger.snapshots import _market_deviation_threshold_pp
    from forecasting.protocol import _estimate_first_enabled

    home = tmp_path / "active-profile"
    home.mkdir()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    path = home / "config.yaml"
    raw = {
        "forecasting": {
            "hooks": {"enabled": False},
            "models": {"skill_weights": False},
            "practice": {"estimate_first": True},
        },
        "quorum": {"market_anchor_deviation_pp": 7.5},
    }
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_hook_config()["enabled"] is False
    assert _skill_weights_enabled(None) is False
    assert _estimate_first_enabled() is True
    assert _market_deviation_threshold_pp() == 7.5
    assert list(home.iterdir()) == [path]


@pytest.mark.parametrize("invalid", [[], ["model"], False, 12])
def test_shared_normalization_rejects_invalid_model_shapes(invalid):
    from superforecasting_agent.configuration import resolve_config

    with pytest.raises(ValueError, match="model configuration must be a string or mapping"):
        resolve_config({"model": invalid})


def test_cached_raw_profile_expands_current_environment(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text('model: "${FORECAST_TEST_PROFILE_MODEL}"\n', encoding="utf-8")
    monkeypatch.setenv("FORECAST_TEST_PROFILE_MODEL", "first")
    assert read_configuration(path)["model"] == "first"
    monkeypatch.setenv("FORECAST_TEST_PROFILE_MODEL", "second")
    assert read_configuration(path)["model"] == "second"
    assert "${FORECAST_TEST_PROFILE_MODEL}" in path.read_text(encoding="utf-8")


def test_background_readers_use_active_profile_without_cli_loading(tmp_path, monkeypatch):
    from forecasting import cron_runner, scheduler
    from forecasting.estimator_worker import build_agent_estimator
    from forecasting.learned_error_worker import build_agent_learned_error_reviewer
    from forecasting.jobs.types import quorum
    from forecasting.research_audit import _resolve_adequacy_threshold
    from superforecasting_agent.runtime import config as cli_config

    monkeypatch.setattr(cli_config, "load_config", lambda: pytest.fail("CLI loader used"))
    monkeypatch.setattr(cli_config, "load_config_readonly", lambda: pytest.fail("CLI loader used"))
    home = tmp_path / "background-profile"
    home.mkdir()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    path = home / "config.yaml"
    path.write_text(yaml.safe_dump({
        "model": {"default": "isolated-test-model"},
        "forecasting": {
            "cron": {"auto_install": False, "warning_automode_auto_install": False},
            "research": {"adequacy_threshold": 0.73},
            "warnings": {"auto_free_tier": False},
            "reviews": {"interval_minutes": 43},
            "calibration": {"derive_alpha": True},
        },
        "cron": {"source_estimator": {"interval_minutes": 37}},
        "quorum": {"supervisor_search": False, "market_anchor": False,
                   "track_record_weights": False, "track_record_min_sample": 23,
                   "market_anchor_deviation_pp": 6.5},
    }), encoding="utf-8")
    assert callable(build_agent_estimator())
    assert callable(build_agent_learned_error_reviewer())
    assert scheduler._auto_install_enabled() is False
    assert scheduler._warning_automode_auto_install_enabled() is False
    assert cron_runner._source_estimator_config()["interval_minutes"] == 37
    assert cron_runner._reviews_config()["interval_minutes"] == 43
    assert cron_runner._warnings_config()["auto_free_tier"] is False
    assert _resolve_adequacy_threshold() == 0.73
    assert quorum._supervisor_search_enabled({}) is False
    assert quorum._market_anchor_enabled({}) is False
    assert quorum._track_record_weights_enabled({}) is False
    assert quorum._track_record_min_sample({}) == 23
    assert quorum._market_anchor_threshold_pp({}) == 6.5
    assert quorum._derive_alpha_enabled() is True
    assert quorum._market_anchor_threshold_pp({"market_anchor_deviation_pp": 8}) == 8
    assert list(home.iterdir()) == [path]
