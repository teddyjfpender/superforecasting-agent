"""Shared command streaming and retained output have independent ownership."""

import sys
from unittest.mock import Mock

import pytest

from superforecasting_agent.application.command_output import capture_output, emit


def test_stream_delivers_all_writes_but_capture_retains_bounded_tail():
    chunks = []
    original_streams = sys.stdout, sys.stderr
    with capture_output(limit=5, on_output=lambda stream, text: chunks.append((stream, text))) as (out, err):
        emit("abcdef", end="")
        emit("🙂xy", end="")
        emit("error", file=sys.stderr, end="")
        assert (sys.stdout, sys.stderr) == original_streams
        assert out.tell() == 5
    assert out.getvalue() == "[Earlier command output omitted]\nef🙂xy"
    assert err.getvalue() == "error"
    assert "".join(text for stream, text in chunks if stream == "stdout") == "abcdef🙂xy"
    assert "".join(text for stream, text in chunks if stream == "stderr") == "error"


def test_one_large_write_cannot_exceed_retained_limit():
    with capture_output(limit=64) as (out, _):
        emit("x" * 100000 + "end", end="")
        assert out.tell() == 64
    assert out.getvalue().endswith("x" * 61 + "end")


def test_failed_observer_does_not_fail_command_or_retry_delivery(caplog):
    observe = Mock(side_effect=OSError("disconnected"))
    with capture_output(on_output=observe) as (out, _):
        emit("mutation applied", end="")
        emit("; complete", end="")
    assert out.getvalue() == "mutation applied; complete"
    observe.assert_called_once()
    assert "Command output observer failed" in caplog.text


@pytest.mark.parametrize("limit", [0, -1, True, 2.5, "10"])
def test_invalid_output_limits_rejected_before_capture(limit):
    with pytest.raises(ValueError):
        with capture_output(limit=limit):
            pytest.fail("invalid capture admitted")


def test_nested_capture_observers_do_not_cross_requests():
    outer_writes, inner_writes = [], []
    with capture_output(on_output=lambda stream, text: outer_writes.append(text)):
        emit("before", end="")
        with capture_output(on_output=lambda stream, text: inner_writes.append(text)):
            emit("inner", end="")
        emit("after", end="")
    assert outer_writes == ["before", "after"]
    assert inner_writes == ["inner"]
