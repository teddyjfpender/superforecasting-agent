"""Kalshi key flow (store/load + 0600 perms) and the pm doctor fold-in."""

from __future__ import annotations

import os
import stat

import pytest

from forecasting import api_keys
from forecasting.api_keys import (
    KALSHI_KEY_ID_VAR,
    KALSHI_PEM_PATH_VAR,
    load_kalshi_credentials,
    set_kalshi_key,
    unset_kalshi_key,
)
from forecasting.models import ValidationError
from forecasting.pm.health import build_pm_doctor

_PEM = (
    "-----BEGIN PRIVATE KEY-----\n"
    "MIIBVAIBADANBgkqh...fake-body...\n"
    "-----END PRIVATE KEY-----\n"
)


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    pem_path = tmp_path / "kalshi_private_key.pem"
    for var in (KALSHI_KEY_ID_VAR, KALSHI_PEM_PATH_VAR):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(api_keys, "default_env_path", lambda: env_path)
    monkeypatch.setattr(api_keys, "default_kalshi_pem_path", lambda: pem_path)
    return env_path, pem_path


def test_set_kalshi_key_writes_pem_0600_and_records_env(isolated_env):
    env_path, pem_path = isolated_env
    info = set_kalshi_key("key-abc", _PEM)
    assert pem_path.exists()
    mode = stat.S_IMODE(os.stat(pem_path).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    # env activated in-process
    assert os.environ[KALSHI_KEY_ID_VAR] == "key-abc"
    assert os.environ[KALSHI_PEM_PATH_VAR] == str(pem_path)
    # persisted to .env
    body = env_path.read_text()
    assert KALSHI_KEY_ID_VAR in body and KALSHI_PEM_PATH_VAR in body
    assert info["pem_path"] == str(pem_path)


def test_load_kalshi_credentials_roundtrip(isolated_env):
    set_kalshi_key("key-abc", _PEM)
    creds = load_kalshi_credentials()
    assert creds is not None
    key_id, pem = creds
    assert key_id == "key-abc" and "PRIVATE KEY" in pem


def test_load_returns_none_when_absent(isolated_env):
    assert load_kalshi_credentials() is None


def test_load_returns_none_when_pem_file_missing(isolated_env):
    _, pem_path = isolated_env
    set_kalshi_key("key-abc", _PEM)
    pem_path.unlink()
    assert load_kalshi_credentials() is None


def test_set_rejects_non_pem(isolated_env):
    with pytest.raises(ValidationError):
        set_kalshi_key("key-abc", "not-a-pem")


def test_set_rejects_empty_key_id(isolated_env):
    with pytest.raises(ValidationError):
        set_kalshi_key("", _PEM)


def test_unset_removes_key_and_pem(isolated_env):
    _, pem_path = isolated_env
    set_kalshi_key("key-abc", _PEM)
    unset_kalshi_key()
    assert KALSHI_KEY_ID_VAR not in os.environ
    assert not pem_path.exists()


def test_kalshi_provider_listed():
    from forecasting.api_keys import list_api_keys

    names = {row["name"] for row in list_api_keys()}
    assert "kalshi" in names


# ── doctor fold-in ───────────────────────────────────────────────────────────


def test_pm_doctor_reports_venue_readiness(isolated_env, monkeypatch):
    monkeypatch.delenv(KALSHI_KEY_ID_VAR, raising=False)
    report = build_pm_doctor()
    assert set(report["venues"]) == {"polymarket", "kalshi"}
    assert report["venues"]["polymarket"]["market_data"] == "public"
    assert report["kalshi_key_present"] is False
    # kalshi stream not ready without a key; reason is populated
    assert report["venues"]["kalshi"]["stream_ready"] is False
    assert report["venues"]["kalshi"]["stream_reason"]


def test_pm_doctor_flips_kalshi_ready_with_key(isolated_env):
    set_kalshi_key("key-abc", _PEM)
    report = build_pm_doctor()
    assert report["kalshi_key_present"] is True
    # readiness still gated on ws lib + cryptography being importable
    if report["websocket_lib"] and report["cryptography"]:
        assert report["venues"]["kalshi"]["stream_ready"] is True


def test_pm_doctor_includes_cache_counts_when_service_passed(isolated_env):
    from forecasting.pm.service import PMService

    svc = PMService()
    svc._cache._entries["list:all::"] = object()
    svc._cache._entries["detail:kalshi:E1"] = object()
    report = build_pm_doctor(service=svc)
    assert report["cache_counts"]["list"] == 1
    assert report["cache_counts"]["detail"] == 1


def test_pm_doctor_includes_stream_state_when_hub_passed(isolated_env):
    class FakeHub:
        def active(self):
            return {"polymarket": ["tok1"]}

    report = build_pm_doctor(hub=FakeHub())
    assert report["stream_state"] == {"polymarket": ["tok1"]}
