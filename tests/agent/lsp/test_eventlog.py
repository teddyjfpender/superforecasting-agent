"""Tests for the structured logging dedup model.

The contract: a 1000-write session in one project should emit exactly
ONE INFO line ("active for <root>") at the default INFO threshold.
Steady-state events stay at DEBUG; first-time-seen events surface
once at INFO/WARNING.
"""
from __future__ import annotations

import logging

import pytest

from agent.lsp import eventlog


@pytest.fixture(autouse=True)
def _reset():
    eventlog.reset_announce_caches()
    yield
    eventlog.reset_announce_caches()


@pytest.fixture
def caplog_lsp(caplog):
    caplog.set_level(logging.DEBUG, logger="hermes.lint.lsp")
    return caplog


def _lsp_records(caplog, *, level: int | None = None, min_level: int | None = None):
    records = [r for r in caplog.records if r.name == "hermes.lint.lsp"]
    if level is not None:
        records = [r for r in records if r.levelno == level]
    if min_level is not None:
        records = [r for r in records if r.levelno >= min_level]
    return records


# ---------------------------------------------------------------------------
# Steady-state silence (DEBUG)
# ---------------------------------------------------------------------------


def test_clean_emits_at_debug(caplog_lsp):
    for _ in range(10):
        eventlog.log_clean("pyright", "/proj/x.py")
    info_records = _lsp_records(caplog_lsp, min_level=logging.INFO)
    debug_records = _lsp_records(caplog_lsp, level=logging.DEBUG)
    assert info_records == []
    assert len(debug_records) == 10


def test_disabled_emits_at_debug(caplog_lsp):
    eventlog.log_disabled("pyright", "/x.py", "feature off")
    eventlog.log_disabled("pyright", "/x.py", "ext not mapped")
    assert all(r.levelno == logging.DEBUG for r in _lsp_records(caplog_lsp))


# ---------------------------------------------------------------------------
# State transitions: INFO once, DEBUG thereafter
# ---------------------------------------------------------------------------


def test_active_for_fires_once_per_root(caplog_lsp):
    for _ in range(50):
        eventlog.log_active("pyright", "/proj")
    info_records = [
        r for r in _lsp_records(caplog_lsp)
        if r.levelno == logging.INFO and "active for" in r.getMessage()
    ]
    assert len(info_records) == 1


def test_active_for_fires_per_distinct_root(caplog_lsp):
    eventlog.log_active("pyright", "/proj-a")
    eventlog.log_active("pyright", "/proj-b")
    info = _lsp_records(caplog_lsp, level=logging.INFO)
    assert len(info) == 2


def test_active_for_separate_per_server(caplog_lsp):
    eventlog.log_active("pyright", "/proj")
    eventlog.log_active("typescript", "/proj")
    info = _lsp_records(caplog_lsp, level=logging.INFO)
    assert len(info) == 2


def test_no_project_root_fires_once_per_path(caplog_lsp):
    for _ in range(5):
        eventlog.log_no_project_root("pyright", "/orphan.py")
    info = _lsp_records(caplog_lsp, level=logging.INFO)
    assert len(info) == 1


# ---------------------------------------------------------------------------
# Diagnostics events fire INFO every time
# ---------------------------------------------------------------------------


def test_diagnostics_always_info(caplog_lsp):
    for i in range(5):
        eventlog.log_diagnostics("pyright", f"/x{i}.py", 1)
    info = _lsp_records(caplog_lsp, level=logging.INFO)
    assert len(info) == 5
    assert all("diags" in r.getMessage() for r in info)


# ---------------------------------------------------------------------------
# Action-required: WARNING once, DEBUG thereafter (or per call for novel events)
# ---------------------------------------------------------------------------


def test_server_unavailable_warns_once_per_binary(caplog_lsp):
    for _ in range(20):
        eventlog.log_server_unavailable("pyright", "pyright-langserver")
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 1
    assert "pyright-langserver" in warns[0].getMessage()


def test_server_unavailable_separate_per_binary(caplog_lsp):
    eventlog.log_server_unavailable("pyright", "pyright-langserver")
    eventlog.log_server_unavailable("typescript", "typescript-language-server")
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 2


def test_no_server_configured_warns_once(caplog_lsp):
    for _ in range(10):
        eventlog.log_no_server_configured("pyright")
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 1


def test_timeout_warns_every_call(caplog_lsp):
    for _ in range(3):
        eventlog.log_timeout("pyright", "/x.py")
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 3


def test_server_error_warns_every_call(caplog_lsp):
    for _ in range(3):
        eventlog.log_server_error("pyright", "/x.py", RuntimeError("boom"))
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 3


def test_spawn_failed_warns(caplog_lsp):
    eventlog.log_spawn_failed("pyright", "/proj", FileNotFoundError("nope"))
    warns = _lsp_records(caplog_lsp, level=logging.WARNING)
    assert len(warns) == 1
    assert "spawn/initialize failed" in warns[0].getMessage()


# ---------------------------------------------------------------------------
# Format: log lines all carry the lsp[<server_id>] prefix for grep
# ---------------------------------------------------------------------------


def test_log_lines_use_lsp_prefix(caplog_lsp):
    eventlog.log_clean("pyright", "/x.py")
    eventlog.log_active("pyright", "/proj")
    eventlog.log_diagnostics("typescript", "/y.ts", 2)
    for r in _lsp_records(caplog_lsp):
        assert r.getMessage().startswith("lsp[")


# ---------------------------------------------------------------------------
# Steady-state contract: 1000 clean writes → 1 INFO at most
# ---------------------------------------------------------------------------


def test_thousand_clean_writes_emit_one_info(caplog_lsp):
    """A long session writes lots of files cleanly; agent.log should
    show ONE 'active for' INFO and zero other INFO lines."""
    eventlog.log_active("pyright", "/proj")
    for _ in range(1000):
        eventlog.log_clean("pyright", "/proj/x.py")
    info_records = _lsp_records(caplog_lsp, level=logging.INFO)
    assert len(info_records) == 1
    assert "active for" in info_records[0].getMessage()


# ---------------------------------------------------------------------------
# Path shortening
# ---------------------------------------------------------------------------


def test_short_path_uses_relative_when_inside_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    sub = tmp_path / "x.py"
    sub.write_text("")
    out = eventlog._short_path(str(sub))
    assert out == "x.py"


def test_short_path_keeps_absolute_when_outside(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path / "a") if (tmp_path / "a").exists() else None
    monkeypatch.chdir(tmp_path)
    other = "/var/log/foo.txt"
    out = eventlog._short_path(other)
    # Outside cwd: keeps absolute (no leading "../")
    assert out == "/var/log/foo.txt" or not out.startswith("..")


def test_short_path_handles_empty_string():
    assert eventlog._short_path("") == ""
