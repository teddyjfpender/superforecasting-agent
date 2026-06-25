"""P0 #4: per-session runtime-toggle isolation. The model a session switches to is
stored per session and seeded into the tenant_runtime contextvar on each run thread, so
concurrent sessions in one gateway don't clobber each other's model. os.environ stays as
the fallback. (The cross-THREAD behaviour is verified by a manual two-session smoke; the
seed/read/isolation logic is unit-tested here, same-thread.)"""

from __future__ import annotations

import os

import pytest

import tui_gateway.server as srv

_KEYS = [
    "SUPERFORECASTING_AGENT_MODEL", "FORECAST_MODEL", "HERMES_MODEL",
    "SUPERFORECASTING_AGENT_TUI_PROVIDER", "FORECAST_TUI_PROVIDER", "HERMES_TUI_PROVIDER",
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    saved = {k: os.environ.get(k) for k in _KEYS}
    srv._session_toggles.clear()
    yield
    srv._session_toggles.clear()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_store_writes_per_session_and_env_fallback():
    srv._store_session_toggle("A", "MODEL", "model-A")
    assert srv._session_toggles["A"]["MODEL"] == "model-A"
    assert os.environ["SUPERFORECASTING_AGENT_MODEL"] == "model-A"  # fallback alias still written


def test_store_with_no_key_writes_only_env():
    srv._store_session_toggle(None, "MODEL", "m")
    assert srv._session_toggles == {}
    assert os.environ["SUPERFORECASTING_AGENT_MODEL"] == "m"


def test_two_sessions_read_their_own_model():
    srv._store_session_toggle("A", "MODEL", "model-A")
    srv._store_session_toggle("B", "MODEL", "model-B")  # os.environ now globally 'model-B'
    tok = srv._set_session_context("A")
    try:
        assert srv._runtime_env("MODEL") == "model-A"  # A's context wins over the global
        assert srv._runtime_env_value("MODEL") == "model-A"
    finally:
        srv._clear_session_context(tok)
    tok = srv._set_session_context("B")
    try:
        assert srv._runtime_env("MODEL") == "model-B"
    finally:
        srv._clear_session_context(tok)


def test_outside_a_session_context_falls_back_to_env():
    os.environ["SUPERFORECASTING_AGENT_MODEL"] = "env-model"
    assert srv._runtime_env("MODEL") == "env-model"  # nothing seeded -> os.environ


def test_tui_provider_isolated_per_session():
    srv._store_session_toggle("A", "TUI_PROVIDER", "prov-A")
    tok = srv._set_session_context("A")
    try:
        assert srv._tui_env("PROVIDER") == "prov-A"
    finally:
        srv._clear_session_context(tok)
    # cleared -> back to whatever os.environ holds (the alias _store wrote)
    assert srv._tui_env("PROVIDER") == "prov-A"  # os.environ fallback
