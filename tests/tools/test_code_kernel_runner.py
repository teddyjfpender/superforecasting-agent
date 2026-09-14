"""Real child-process checks for persistent cell execution and owner EOF."""

import hashlib
import json
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parents[2] / "tools" / "code_kernel_runner.py"


@contextmanager
def running_kernel():
    child = subprocess.Popen(
        [sys.executable, str(RUNNER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        ready = json.loads(child.stdout.readline())
        assert ready["ready"] is True and ready["version"] == 1
        assert ready["runtime"]["python"] == sys.version
        assert isinstance(ready["runtime"]["packages"], list)
        yield child
    finally:
        with suppress(BrokenPipeError):
            child.stdin.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


def cell(child, code, *, reset=False):
    child.stdin.write(
        json.dumps({"id": "test-cell", "code": code, "reset": reset}) + "\n"
    )
    child.stdin.flush()
    return json.loads(child.stdout.readline())


def test_state_errors_reset_and_calculation_chain():
    with running_kernel() as child:
        first = cell(child, "values = [1, 2, 3]\nprint(sum(values))")
        assert first["stdout"] == "6\n"
        failed = cell(child, "values.append(4)\nraise ValueError('bad measurement')")
        assert failed["error"] and failed["state_preserved"]
        assert "bad measurement" in failed["stderr"]
        assert (
            failed["previous_sha256"]
            == hashlib.sha256(
                json.dumps(first, ensure_ascii=True, sort_keys=True).encode()
            ).hexdigest()
        )
        third = cell(child, "print(sum(values))")
        assert third["stdout"] == "10\n" and third["sequence"] == 3
        reset = cell(child, "print('values' in globals())", reset=True)
        assert reset["stdout"] == "False\n"
        assert (
            reset["code_sha256"]
            == hashlib.sha256(b"print('values' in globals())").hexdigest()
        )


def test_bounded_output_native_writes_and_system_exit():
    with running_kernel() as child:
        result = cell(
            child,
            "import os\nos.write(1, b'native diagnostic\\n')\nprint('x' * 300000)",
        )
        assert len(result["stdout"]) == 250000
        assert result["stdout_omitted_chars"] == 50001
        assert child.stderr.readline() == "native diagnostic\n"
        assert cell(child, "raise SystemExit(7)")["error"]
        assert cell(child, "print('still alive')")["stdout"] == "still alive\n"


def test_owner_eof_stops_a_running_cell(tmp_path):
    started = tmp_path / "started"
    with running_kernel() as child:
        code = f"from pathlib import Path\nPath({str(started)!r}).touch()\nwhile True: pass"
        child.stdin.write(
            json.dumps({"id": "busy", "code": code, "reset": False}) + "\n"
        )
        child.stdin.flush()
        import time

        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "cell never started"
        child.stdin.close()
        assert child.wait(timeout=5) == 0


def test_background_thread_retires_interpreter_before_authority_can_change():
    with running_kernel() as child:
        result = cell(
            child,
            "import threading\nthreading.Thread(target=threading.Event().wait).start()",
        )
        assert not result["state_preserved"]
        assert result["retirement_reason"] == "cell_left_running_threads"
        assert child.wait(timeout=5) == 73


@pytest.mark.parametrize(
    "payload",
    ["[]\n", '{"id":"x","code":"pass","reset":1}\n', "x" * 1048577],
    ids=["array", "invalid-reset", "oversized"],
)
def test_malformed_or_oversized_control_frame_fails_closed(payload):
    with running_kernel() as child:
        try:
            child.stdin.write(payload)
            child.stdin.flush()
        except BrokenPipeError:
            pass
        assert child.wait(timeout=5) == 65
