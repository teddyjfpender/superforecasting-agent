"""Regression tests for the curses-menu Ctrl+C / cancel behaviour.

A returning user running `superforecasting-agent setup` could get trapped in
the tool-configuration menu: ESC returned the default index (re-opening the
checklist) and Ctrl+C was swallowed into ``cancel_returns`` (same loop), so the
only escape was killing the terminal. The fix adds an opt-in
``raise_on_interrupt`` so Ctrl+C propagates as ``KeyboardInterrupt`` (letting
the caller abort), while leaving every existing caller's behaviour unchanged.
"""

from __future__ import annotations

import pytest

import hermes_cli.curses_ui as cui


# ── Non-TTY plumbing: the new kwarg must not disturb the non-interactive path ──


def test_radiolist_non_tty_returns_cancel(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cui.curses_radiolist("Q", ["a", "b", "c"], selected=0, cancel_returns=2) == 2
    # raise_on_interrupt has no effect on the non-tty short-circuit.
    assert (
        cui.curses_radiolist("Q", ["a", "b"], selected=0, cancel_returns=1, raise_on_interrupt=True)
        == 1
    )


def test_checklist_non_tty_returns_cancel(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cui.curses_checklist("Q", ["a", "b"], {0}, cancel_returns={1}, raise_on_interrupt=True) == {1}


# ── Fallback interrupt semantics: the actual behaviour change, made testable ──
# The curses path cannot be driven headless, but the numbered fallbacks share
# the swallow-vs-propagate decision and run on a normal pipe.


def _raise_kbd(_prompt=""):
    raise KeyboardInterrupt


def test_radio_fallback_swallows_interrupt_by_default(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_kbd)
    # Legacy behaviour: Ctrl+C returns cancel_returns (acts like ESC).
    assert cui._radio_numbered_fallback("T", ["a", "b"], 0, 1) == 1


def test_radio_fallback_propagates_interrupt_when_opted_in(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_kbd)
    with pytest.raises(KeyboardInterrupt):
        cui._radio_numbered_fallback("T", ["a", "b"], 0, 1, raise_on_interrupt=True)


def test_checklist_fallback_swallows_interrupt_by_default(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_kbd)
    assert cui._numbered_fallback("T", ["a", "b"], {0}, {1}) == {1}


def test_checklist_fallback_propagates_interrupt_when_opted_in(monkeypatch):
    monkeypatch.setattr("builtins.input", _raise_kbd)
    with pytest.raises(KeyboardInterrupt):
        cui._numbered_fallback("T", ["a", "b"], {0}, {1}, raise_on_interrupt=True)


def test_checklist_fallback_value_error_still_cancels(monkeypatch):
    # A non-numeric entry still cancels (regression: we split the except).
    monkeypatch.setattr("builtins.input", lambda _prompt="": "not-a-number")
    assert cui._numbered_fallback("T", ["a", "b"], {0}, {1}) == {1}
