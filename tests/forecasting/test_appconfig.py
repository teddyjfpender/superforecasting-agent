"""Tests for the typed layered config loader + `forecast config doctor`.

Covers: precedence order, typed coercion + bad-value errors that NAME the key,
secret redaction, the deprecation shim (warn once), the doctor sections
(unknown/typo var, file-vs-env precedence conflict, kalshi two-var trap +
alias flag), and behaviour-identity of the migrated call sites (env-only,
file-only, both).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecasting import appconfig
from forecasting.appconfig import AppConfig, AppConfigError


@pytest.fixture(autouse=True)
def _reset_warnings():
    appconfig.reset_deprecation_warnings()
    yield
    appconfig.reset_deprecation_warnings()


# ── precedence ───────────────────────────────────────────────────────────────


def test_precedence_default_lt_config_lt_env_lt_override():
    # registry default only
    c = AppConfig(environ={}, config_file={})
    assert c.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 20

    # config file beats default
    c = AppConfig(environ={}, config_file={"FORECAST_TRIAGE_TRUST_MIN_SAMPLE": 5})
    assert c.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 5
    assert c.source_of("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == "config"

    # env beats config file
    c = AppConfig(
        environ={"FORECAST_TRIAGE_TRUST_MIN_SAMPLE": "7"},
        config_file={"FORECAST_TRIAGE_TRUST_MIN_SAMPLE": 5},
    )
    assert c.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 7
    assert c.source_of("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == "env"

    # override beats env
    c.set_override("FORECAST_TRIAGE_TRUST_MIN_SAMPLE", "9")
    assert c.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 9
    assert c.source_of("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == "override"


def test_call_site_default_beats_registry_default():
    c = AppConfig(environ={}, config_file={})
    # explicit default wins over the registry default
    assert c.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE", 99) == 99
    # unregistered key with no default → None (matches os.environ.get)
    assert c.get_str("TOTALLY_UNKNOWN_VAR") is None
    assert c.get_str("TOTALLY_UNKNOWN_VAR", "fallback") == "fallback"


# ── typed coercion + bad-value errors that NAME the key ──────────────────────


def test_typed_coercion():
    c = AppConfig(
        environ={
            "FORECAST_BRIDGE_PORT": "9001",
            "FORECAST_TRIAGE_TRUST_THRESHOLD": "0.65",
            "FORECAST_DISABLE_HOOK_BLOCKING": "yes",
            "FORECAST_LEDGER_DB": "~/db.sqlite",
        },
        config_file={},
    )
    assert c.get_int("FORECAST_BRIDGE_PORT") == 9001
    assert c.get_float("FORECAST_TRIAGE_TRUST_THRESHOLD") == 0.65
    assert c.get_bool("FORECAST_DISABLE_HOOK_BLOCKING") is True
    p = c.get_path("FORECAST_LEDGER_DB")
    assert isinstance(p, Path) and str(p).endswith("db.sqlite") and "~" not in str(p)


def test_bad_int_names_the_key():
    c = AppConfig(environ={"FORECAST_BRIDGE_PORT": "not-a-number"}, config_file={})
    with pytest.raises(AppConfigError) as exc:
        c.get_int("FORECAST_BRIDGE_PORT")
    assert "FORECAST_BRIDGE_PORT" in str(exc.value)


def test_bad_float_names_the_key():
    c = AppConfig(environ={"FORECAST_TRIAGE_TRUST_THRESHOLD": "high"}, config_file={})
    with pytest.raises(AppConfigError) as exc:
        c.get_float("FORECAST_TRIAGE_TRUST_THRESHOLD")
    assert "FORECAST_TRIAGE_TRUST_THRESHOLD" in str(exc.value)


def test_bool_strict_raises_and_names_key_but_lenient_defaults():
    c = AppConfig(environ={"FORECAST_DISABLE_HOOK_BLOCKING": "maybe"}, config_file={})
    # lenient: unrecognised → falls back to the (False) default, matching the
    # historical `.lower() in {"1","true","yes","on"}` idiom.
    assert c.get_bool("FORECAST_DISABLE_HOOK_BLOCKING") is False
    with pytest.raises(AppConfigError) as exc:
        c.get_bool("FORECAST_DISABLE_HOOK_BLOCKING", strict=True)
    assert "FORECAST_DISABLE_HOOK_BLOCKING" in str(exc.value)


def test_bool_recognised_tokens():
    for token in ("1", "true", "TRUE", "yes", "on"):
        c = AppConfig(environ={"FORECAST_DISABLE_THESIS_CASCADE": token}, config_file={})
        assert c.get_bool("FORECAST_DISABLE_THESIS_CASCADE") is True
    for token in ("0", "false", "no", "off", ""):
        c = AppConfig(environ={"FORECAST_DISABLE_THESIS_CASCADE": token}, config_file={})
        assert c.get_bool("FORECAST_DISABLE_THESIS_CASCADE") is False


# ── secret redaction ─────────────────────────────────────────────────────────


def test_secret_returns_value_but_redact_hides_it():
    c = AppConfig(environ={"FRED_API_KEY": "abcd1234efgh5678"}, config_file={})
    assert c.secret("FRED_API_KEY") == "abcd1234efgh5678"  # value available for USE
    red = appconfig.redact(c.secret("FRED_API_KEY"))
    assert "abcd1234efgh5678" not in red
    assert red.startswith("abcd") and red.endswith("chars)")
    assert appconfig.redact(None) == "(not set)"
    assert c.is_secret("FRED_API_KEY") is True
    assert c.is_secret("FORECAST_BRIDGE_PORT") is False


# ── deprecation shim (warn once) ─────────────────────────────────────────────


def test_deprecation_shim_resolves_alias_and_warns_once(caplog):
    # canonical unset, deprecated alias set → alias value used
    c = AppConfig(environ={"FORECAST_HOME": "/tmp/legacy"}, config_file={})
    with caplog.at_level("WARNING", logger="forecasting.appconfig"):
        assert c.get_str("SUPERFORECASTING_AGENT_HOME") == "/tmp/legacy"
        assert c.get_str("SUPERFORECASTING_AGENT_HOME") == "/tmp/legacy"  # second read
    deprecation_warnings = [r for r in caplog.records if "FORECAST_HOME" in r.getMessage()]
    assert len(deprecation_warnings) == 1  # warned exactly once


def test_reading_deprecated_name_directly_redirects_to_canonical(caplog):
    c = AppConfig(environ={"SUPERFORECASTING_AGENT_TIMEZONE": "UTC"}, config_file={})
    with caplog.at_level("WARNING", logger="forecasting.appconfig"):
        # reading the OLD name returns the canonical's value + warns
        assert c.get_str("FORECAST_TIMEZONE") == "UTC"
    assert any("FORECAST_TIMEZONE" in r.getMessage() for r in caplog.records)


def test_canonical_beats_deprecated_alias():
    c = AppConfig(
        environ={"SUPERFORECASTING_AGENT_HOME": "/new", "HERMES_HOME": "/old"},
        config_file={},
    )
    assert c.get_str("SUPERFORECASTING_AGENT_HOME") == "/new"


# ── doctor sections ──────────────────────────────────────────────────────────


def test_doctor_flags_unknown_typo_var():
    c = AppConfig(environ={"FORECST_LEDGER_DB": "/x"}, config_file={})
    report = appconfig.build_doctor_report(c, inventory=set())
    unknown = {r["name"]: r["suggestion"] for r in report["unknown_set"]}
    assert "FORECST_LEDGER_DB" in unknown
    assert unknown["FORECST_LEDGER_DB"] == "FORECAST_LEDGER_DB"


def test_doctor_ignores_genuine_os_var():
    c = AppConfig(environ={"LSCOLORS": "GxFxCxDx", "SHELL": "/bin/zsh"}, config_file={})
    report = appconfig.build_doctor_report(c, inventory=set())
    names = {r["name"] for r in report["unknown_set"]}
    assert "LSCOLORS" not in names and "SHELL" not in names


def test_doctor_reports_file_vs_env_precedence_conflict():
    c = AppConfig(
        environ={"FORECAST_TRIAGE_MODEL": "gpt-x"},
        config_file={"FORECAST_TRIAGE_MODEL": "claude-y"},
    )
    report = appconfig.build_doctor_report(c, inventory=set())
    conflicts = {r["name"]: r["winner"] for r in report["precedence_conflicts"]}
    assert conflicts.get("FORECAST_TRIAGE_MODEL") == "env"


def test_doctor_kalshi_two_var_trap_and_alias_flag():
    # exactly one of the pair set → half-configured
    c = AppConfig(environ={"KALSHI_ACCESS_KEY_ID": "kid"}, config_file={})
    report = appconfig.build_doctor_report(c, inventory=set())
    assert report["kalshi"]["half_configured"] is True
    # bea has no `forecast api-key set` provider → alias mismatch flagged
    slugs = {m["slug"] for m in report["kalshi"]["alias_mismatches"]}
    assert "bea" in slugs


def test_doctor_secret_presence_never_leaks_value():
    c = AppConfig(environ={"OPENAI_API_KEY": "sk-supersecretvalue"}, config_file={})
    report = appconfig.build_doctor_report(c, inventory=set())
    rendered = appconfig.render_doctor_report(report)
    assert "sk-supersecretvalue" not in rendered
    present = {s["name"] for s in report["secrets"] if s["present"]}
    assert "OPENAI_API_KEY" in present


# ── migrated call-site behaviour-identity (env-only, file-only, both) ────────


@pytest.mark.parametrize(
    "environ,config_file,expected",
    [
        ({"FORECAST_LEDGER_DB": "/env/db"}, {}, "/env/db"),          # env-only
        ({}, {"FORECAST_LEDGER_DB": "/file/db"}, "/file/db"),        # file-only
        ({"FORECAST_LEDGER_DB": "/env/db"}, {"FORECAST_LEDGER_DB": "/file/db"}, "/env/db"),  # both → env wins
        ({}, {}, None),                                              # unset → registry default None
    ],
)
def test_migrated_ledger_db_reads_identically(environ, config_file, expected):
    c = AppConfig(environ=environ, config_file=config_file)
    # mirrors the migrated cron_runner site: args.db or get_str(...) or None
    assert (c.get_str("FORECAST_LEDGER_DB") or None) == expected


def test_migrated_gate_mode_identity():
    # mirrors ledger_write_gate_mode(): (get_str(..., "on") or "").strip().lower()
    c = AppConfig(environ={}, config_file={})
    assert (c.get_str("FORECAST_GATE_DIRECT_WRITES", "on") or "").strip().lower() == "on"
    c = AppConfig(environ={"FORECAST_GATE_DIRECT_WRITES": "WARN"}, config_file={})
    assert (c.get_str("FORECAST_GATE_DIRECT_WRITES", "on") or "").strip().lower() == "warn"


def test_module_singleton_configure(monkeypatch):
    appconfig.configure(environ={"FORECAST_TRIAGE_MODEL": "singleton-model"}, config_file={})
    try:
        assert appconfig.get_str("FORECAST_TRIAGE_MODEL") == "singleton-model"
    finally:
        appconfig.configure(environ=None, config_file=None)  # restore live layers


# ── quorum panel keys (config `env:` section + doctor awareness) ──────────────


def test_quorum_panel_models_resolves_from_config_env_section():
    # config.yaml `env:` section (the B5 loader layer) supplies the pin…
    c = AppConfig(
        environ={},
        config_file={"QUORUM_PANEL_MODELS": "openai-codex:gpt-5.5, gemini:gemini-2.5-flash"},
    )
    assert c.get_str("QUORUM_PANEL_MODELS") == "openai-codex:gpt-5.5, gemini:gemini-2.5-flash"
    assert c.source_of("QUORUM_PANEL_MODELS") == "config"
    # …and a shell env var overrides it.
    c2 = AppConfig(
        environ={"QUORUM_PANEL_MODELS": "openai-codex:gpt-5.5"},
        config_file={"QUORUM_PANEL_MODELS": "gemini:gemini-2.5-flash"},
    )
    assert c2.get_str("QUORUM_PANEL_MODELS") == "openai-codex:gpt-5.5"
    assert c2.source_of("QUORUM_PANEL_MODELS") == "env"


def test_doctor_knows_quorum_panel_keys():
    c = AppConfig(environ={}, config_file={"QUORUM_PANEL_MODELS": "openai-codex:gpt-5.5"})
    report = appconfig.build_doctor_report(c, inventory=set())
    known_set = {r["name"] for r in report["known_set"]}
    known_unset = {r["name"] for r in report["known_unset"]}
    assert "QUORUM_PANEL_MODELS" in known_set  # set via config env: section
    assert "QUORUM_JUDGE_MODEL" in known_unset  # registered but unset


def test_live_config_follows_profile_and_content_without_reload(tmp_path, monkeypatch):
    import os

    for name in ("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "FORECAST_IGNORE_USER_CONFIG", "HERMES_IGNORE_USER_CONFIG"):
        monkeypatch.delenv(name, raising=False)
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    path = first / "config.yaml"
    path.write_text("env:\n  FORECAST_TRIAGE_TRUST_MIN_SAMPLE: 31\n", encoding="utf-8")
    (second / "config.yaml").write_text("env:\n  FORECAST_TRIAGE_TRUST_MIN_SAMPLE: 45\n", encoding="utf-8")
    for name in ("SUPERFORECASTING_AGENT_HOME", "HERMES_HOME"):
        monkeypatch.setenv(name, str(first))
    config = AppConfig(environ={})
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 31
    stamp = path.stat()
    path.write_text("env:\n  FORECAST_TRIAGE_TRUST_MIN_SAMPLE: 32\n", encoding="utf-8")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 32
    for name in ("SUPERFORECASTING_AGENT_HOME", "HERMES_HOME"):
        monkeypatch.setenv(name, str(second))
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 45
    monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "1")
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 20
    monkeypatch.setenv("SUPERFORECASTING_AGENT_IGNORE_USER_CONFIG", "0")
    monkeypatch.setenv("HERMES_IGNORE_USER_CONFIG", "1")
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 45
    (second / "config.yaml").unlink()
    assert config.get_int("FORECAST_TRIAGE_TRUST_MIN_SAMPLE") == 20
