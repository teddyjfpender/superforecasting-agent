"""Regression guards for the retry/fallback status-buffer CLEAR invariants.

#33816 buffers retry/fallback chatter and surfaces it only on terminal
failure.  The buffer is an instance attribute on the long-lived AIAgent, so
its emptiness must be guaranteed at three points or stale chatter from a
recovered hiccup leaks onto a later, unrelated terminal flush:

  1. Turn start — a backstop so a prior turn that exited without clearing
     (recovered via a tool-call iteration, or broke out of the loop) cannot
     leak into this turn's first flush. (cross-turn leak)
  2. Tool-call success — when valid, executable tool calls are produced, the
     turn is progressing; drop the buffer (intra-turn leak via the tool-call
     path, which bypasses the final-text clear).
  3. Final-text success — the original upstream clear point.

The audit that found gaps (1) and (2) is recorded in docs/upstream-sync.md.
These are structural guards (assert on the loop source) because a true
behavioural test would require driving run_conversation through a full
mocked retry→recover→fail sequence; they pin the three clear sites and
their control-flow roles so a future refactor can't silently drop one.
"""

import inspect

import agent.conversation_loop as cl


def _run_conversation_source() -> str:
    return inspect.getsource(cl.run_conversation)


def test_three_clear_sites_present():
    src = _run_conversation_source()
    n = src.count("_clear_status_buffer()")
    assert n >= 3, (
        f"Expected >=3 _clear_status_buffer() sites (turn-start, tool-call "
        f"success, final-text success); found {n}. A dropped clear re-opens "
        f"the stale-chatter leak #33816's audit fixed."
    )


def test_turn_start_clear_precedes_retry_loop():
    """The backstop clear must run before the retry while-loop, so each turn
    starts with an empty buffer regardless of how the previous turn exited."""
    src = _run_conversation_source()
    first_clear = src.find("_clear_status_buffer()")
    retry_loop = src.find("while retry_count < max_retries")
    assert first_clear != -1 and retry_loop != -1
    assert first_clear < retry_loop, (
        "The turn-start _clear_status_buffer() backstop must precede the "
        "`while retry_count < max_retries` loop (cross-turn leak guard)."
    )


def test_tool_call_success_clears_before_execute():
    """Valid executable tool calls are forward progress — the buffer must be
    cleared before _execute_tool_calls, mirroring the final-text clear."""
    src = _run_conversation_source()
    exec_idx = src.find("_execute_tool_calls(assistant_message")
    assert exec_idx != -1, "tool-call execution site moved — re-anchor this test"
    # A clear must appear in the window just before the execute call (same
    # branch), not only in the unrelated final-text branch far below.
    window = src[max(0, exec_idx - 600):exec_idx]
    assert "_clear_status_buffer()" in window, (
        "No _clear_status_buffer() immediately before _execute_tool_calls — "
        "the tool-call recovery path leaks buffered chatter (audit finding 2)."
    )


def test_buffer_only_touched_by_helpers():
    """The raw buffer attribute must stay encapsulated in the run_agent
    helpers; the loop should only ever go through clear/flush/buffer_* so the
    invariants above are the complete set of mutation points."""
    src = _run_conversation_source()
    assert "_retry_status_buffer" not in src, (
        "run_conversation should manipulate the buffer only via the "
        "_buffer_*/_clear/_flush helpers, never the raw attribute."
    )
