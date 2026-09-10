"""Agent identity (M1) — name/instance persistence + stability, soul name
injection, and the sfp/1 sender dict."""

from __future__ import annotations

import json

import pytest

from forecasting import identity
from forecasting.appconfig import AppConfig


def _cfg(**environ) -> AppConfig:
    return AppConfig(environ=dict(environ), config_file={})


# ── name resolution ──────────────────────────────────────────────────────────

def test_default_name_is_bernard(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    assert identity.resolve_agent_name(_cfg()) == "Bernard"
    assert identity.configured_agent_name(_cfg()) is None


def test_configured_name_wins(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    assert identity.resolve_agent_name(_cfg(AGENT_NAME="Ada")) == "Ada"
    assert identity.configured_agent_name(_cfg(AGENT_NAME="Ada")) == "Ada"


def test_persisted_name_is_fallback_when_config_unset(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    (tmp_path / "identity.json").write_text(json.dumps({"name": "Ada", "instance_id": "x"}))
    # No AGENT_NAME configured → persisted name is used, not the Bernard default.
    assert identity.resolve_agent_name(_cfg()) == "Ada"
    # Config still outranks the persisted fallback.
    assert identity.resolve_agent_name(_cfg(AGENT_NAME="Bo")) == "Bo"


# ── instance id: persistence + stability ─────────────────────────────────────

def test_instance_id_minted_once_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    first = identity.resolve_instance_id(_cfg(), home=tmp_path)
    assert first
    # Persisted to identity.json.
    data = json.loads((tmp_path / "identity.json").read_text())
    assert data["instance_id"] == first
    # Stable across restarts (a fresh resolve reads the same file).
    assert identity.resolve_instance_id(_cfg(), home=tmp_path) == first


def test_instance_id_is_a_uuid(monkeypatch, tmp_path):
    import uuid

    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    val = identity.resolve_instance_id(_cfg(), home=tmp_path)
    uuid.UUID(val)  # raises if not a valid uuid


def test_configured_instance_id_pins_and_does_not_write(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    val = identity.resolve_instance_id(_cfg(AGENT_INSTANCE_ID="fixed-123"), home=tmp_path)
    assert val == "fixed-123"
    assert not (tmp_path / "identity.json").exists()  # a pin never mints/persists


def test_corrupt_identity_file_is_tolerated(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    (tmp_path / "identity.json").write_text("{not json")
    val = identity.resolve_instance_id(_cfg(), home=tmp_path)
    assert val  # regenerated cleanly


# ── team resolution (offline) ────────────────────────────────────────────────

def test_team_from_tokens_file(tmp_path):
    (tmp_path / "slack_tokens.json").write_text(json.dumps({"T042": {"token": "xoxb", "team_name": "Acme"}}))
    assert identity.resolve_team(home=tmp_path) == "T042"


def test_team_explicit_wins(tmp_path):
    assert identity.resolve_team("T999", home=tmp_path) == "T999"


def test_team_none_when_no_tokens(tmp_path):
    assert identity.resolve_team(home=tmp_path) is None


# ── full identity + sfp sender ───────────────────────────────────────────────

def test_resolve_identity_and_sfp_sender(monkeypatch, tmp_path):
    monkeypatch.setattr("superforecasting_agent.constants.get_agent_home", lambda: tmp_path)
    (tmp_path / "slack_tokens.json").write_text(json.dumps({"T1": {"token": "x"}}))
    ident = identity.resolve_identity(
        cfg=_cfg(AGENT_NAME="Ada", AGENT_PERSONA="dry wit"), home=tmp_path
    )
    assert ident.name == "Ada"
    assert ident.instance_id
    assert ident.team == "T1"
    assert ident.persona == "dry wit"
    assert ident.sfp_sender() == {"agent": "Ada", "instance_id": ident.instance_id, "team": "T1"}


# ── soul name injection ──────────────────────────────────────────────────────

def test_apply_name_rewrites_default_soul_opener():
    from superforecasting_agent.runtime.default_soul import DEFAULT_SOUL_MD

    out = identity.apply_agent_name(DEFAULT_SOUL_MD, "Ada")
    assert out.startswith("You are Ada, the superforecasting agent:")
    assert "You are Bernard," not in out


def test_apply_name_bernard_is_byte_identical():
    from superforecasting_agent.runtime.default_soul import DEFAULT_SOUL_MD

    assert identity.apply_agent_name(DEFAULT_SOUL_MD, "Bernard") == DEFAULT_SOUL_MD
    assert identity.apply_agent_name(DEFAULT_SOUL_MD, "") == DEFAULT_SOUL_MD
    assert identity.apply_agent_name(DEFAULT_SOUL_MD, None) is not None  # resolves, no crash


def test_apply_name_no_double_injection():
    soul = "You are Ada, the best.\n\nMore text."
    assert identity.apply_agent_name(soul, "Ada") == soul  # already named → untouched


def test_apply_name_graceful_prepend_for_custom_soul():
    soul = "A custom soul with no default marker."
    out = identity.apply_agent_name(soul, "Ada")
    assert out.startswith("You are Ada, the superforecasting agent.")
    assert soul in out


def test_apply_name_empty_content_passthrough():
    assert identity.apply_agent_name("", "Ada") == ""
    assert identity.apply_agent_name(None, "Ada") is None


# ── appconfig additive keys are registered ───────────────────────────────────

def test_identity_keys_registered():
    from forecasting.appconfig import REGISTRY

    for key in ("AGENT_NAME", "AGENT_INSTANCE_ID", "AGENT_PERSONA"):
        assert key in REGISTRY
        assert REGISTRY[key].category == "identity"
        assert REGISTRY[key].secret is False  # a name/id is not a secret
