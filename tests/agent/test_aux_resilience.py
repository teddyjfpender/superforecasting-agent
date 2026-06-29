"""Resilience fixes from the 2026-06-29 provider-flakiness investigation:

(a) compaction defaults to LOW codex reasoning (fast summarization, no 120s timeout →
    flaky-fallback chain), overridable;
(b) unattended/batch runs get a higher stream-retry budget than interactive sessions.
"""

import agent.chat_completion_helpers as cch
from agent.auxiliary_client import _apply_compression_reasoning_default


# ── (a) compaction reasoning default ──────────────────────────────────────────

def test_compression_defaults_to_low_reasoning_on_codex_when_unset():
    assert _apply_compression_reasoning_default("compression", {}, "openai-codex", "codex_responses") == {
        "reasoning": {"effort": "low"}
    }
    # api_mode alone (provider=auto) also triggers it
    assert _apply_compression_reasoning_default("compression", {}, "auto", "codex_responses")["reasoning"] == {
        "effort": "low"
    }


def test_compression_reasoning_is_overridable():
    # explicit caller/config reasoning is never clobbered
    eb = _apply_compression_reasoning_default(
        "compression", {"reasoning": {"effort": "high"}}, "openai-codex", "codex_responses"
    )
    assert eb["reasoning"] == {"effort": "high"}


def test_compression_default_not_applied_for_other_tasks_or_providers():
    # other tasks untouched
    assert "reasoning" not in _apply_compression_reasoning_default("vision", {}, "openai-codex", "codex_responses")
    assert "reasoning" not in _apply_compression_reasoning_default("title_generation", {}, "auto", "codex_responses")
    # non-codex providers untouched (they handle/ignore reasoning differently)
    assert "reasoning" not in _apply_compression_reasoning_default("compression", {}, "openai", "chat")
    assert "reasoning" not in _apply_compression_reasoning_default("compression", {}, "anthropic", None)


# ── (b) unattended retry budget ───────────────────────────────────────────────

def test_unattended_run_gets_higher_retry_budget(monkeypatch):
    monkeypatch.setattr(cch, "_is_unattended_run", lambda: True)
    assert cch.default_stream_retries() == cch._UNATTENDED_STREAM_RETRIES > cch._INTERACTIVE_STREAM_RETRIES
    monkeypatch.setattr(cch, "_is_unattended_run", lambda: False)
    assert cch.default_stream_retries() == cch._INTERACTIVE_STREAM_RETRIES == 2


def test_is_unattended_run_keys_off_tty(monkeypatch):
    class _Out:
        def __init__(self, tty):
            self._tty = tty

        def isatty(self):
            return self._tty

    monkeypatch.setattr("sys.stdout", _Out(True))
    assert cch._is_unattended_run() is False  # interactive terminal
    monkeypatch.setattr("sys.stdout", _Out(False))
    assert cch._is_unattended_run() is True  # cron / batch / piped
