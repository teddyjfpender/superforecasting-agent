"""Tests for `_pin_kanban_board_env` helper invoked by `cmd_chat`.

Regression coverage for #20074: a chat session must export the active kanban
board into kanban board env aliases at boot so subprocess shell-outs (e.g.
`superforecasting-agent kanban …`) inherit the same board the in-process kanban tools resolve.
Without this, a concurrent `hermes kanban boards switch` from another session
can flip the global current-board file mid-turn and silently divert the
shell calls to a different DB.
"""
import importlib
import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_kanban_board_env():
    """Snapshot kanban board env aliases and restore them after the test.

    `_pin_kanban_board_env()` writes to ``os.environ`` directly, bypassing
    any ``monkeypatch.setenv`` tracking. Without this fixture the mutation
    leaks into subsequent tests and breaks anything that resolves a kanban
    path from the env (e.g. ``TestSharedBoardPaths`` in test_kanban_db.py).
    """
    names = (
        "SUPERFORECASTING_AGENT_KANBAN_BOARD",
        "FORECAST_KANBAN_BOARD",
        "HERMES_KANBAN_BOARD",
    )
    prev = {name: os.environ.get(name) for name in names}
    for name in names:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        for name, value in prev.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_pin_writes_resolved_board_when_env_unset(monkeypatch):
    main_mod = importlib.import_module("superforecasting_agent.runtime.main")

    import superforecasting_agent.runtime.kanban_db as kdb
    monkeypatch.setattr(kdb, "get_current_board", lambda: "space")

    main_mod._pin_kanban_board_env()

    assert main_mod.os.environ.get("SUPERFORECASTING_AGENT_KANBAN_BOARD") == "space"
    assert main_mod.os.environ.get("FORECAST_KANBAN_BOARD") == "space"
    assert main_mod.os.environ.get("HERMES_KANBAN_BOARD") == "space"


def test_pin_does_not_overwrite_existing_env(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_KANBAN_BOARD", "preset")
    main_mod = importlib.import_module("superforecasting_agent.runtime.main")

    import superforecasting_agent.runtime.kanban_db as kdb

    def _explode():
        raise AssertionError("get_current_board must not be called when env is set")

    monkeypatch.setattr(kdb, "get_current_board", _explode)

    main_mod._pin_kanban_board_env()

    assert main_mod.os.environ.get("SUPERFORECASTING_AGENT_KANBAN_BOARD") == "preset"
    assert main_mod.os.environ.get("FORECAST_KANBAN_BOARD") == "preset"
    assert main_mod.os.environ.get("HERMES_KANBAN_BOARD") == "preset"


def test_pin_swallows_resolution_failures(monkeypatch):
    main_mod = importlib.import_module("superforecasting_agent.runtime.main")

    import superforecasting_agent.runtime.kanban_db as kdb

    def _boom():
        raise RuntimeError("disk gone")

    monkeypatch.setattr(kdb, "get_current_board", _boom)

    main_mod._pin_kanban_board_env()

    assert "SUPERFORECASTING_AGENT_KANBAN_BOARD" not in main_mod.os.environ
    assert "FORECAST_KANBAN_BOARD" not in main_mod.os.environ
    assert "HERMES_KANBAN_BOARD" not in main_mod.os.environ
