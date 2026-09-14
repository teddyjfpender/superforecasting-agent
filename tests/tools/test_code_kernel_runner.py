"""Real child-process checks for persistent cell execution and owner EOF."""

import hashlib
import json
import os
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


@pytest.mark.skipif(os.name != "nt", reason="Native Windows job ownership")
@pytest.mark.parametrize("stop", ["owner_eof", "forced_exit"])
def test_windows_runner_exit_stops_descendants_but_preserves_sibling(tmp_path, stop):
    import time

    import psutil

    marker = tmp_path / "descendant.pid"
    sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    descendant = None
    try:
        with running_kernel() as child:
            code = (
                "import subprocess, sys, time\nfrom pathlib import Path\n"
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"marker = Path({str(marker)!r})\n"
                "pending = marker.with_suffix('.tmp')\n"
                "pending.write_text(str(p.pid))\npending.replace(marker)\n"
                "time.sleep(30)"
            )
            child.stdin.write(json.dumps({"id": "owned-tree", "code": code, "reset": False}) + "\n")
            child.stdin.flush()
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert marker.exists(), "descendant never started"
            descendant = psutil.Process(int(marker.read_text()))
            if stop == "owner_eof":
                child.stdin.close()
            else:
                child.kill()
            child.wait(timeout=5)
            descendant.wait(timeout=5)
            assert sibling.poll() is None
    finally:
        if descendant is not None:
            with suppress(psutil.NoSuchProcess):
                descendant.kill()
                descendant.wait(timeout=5)
        sibling.kill()
        sibling.wait(timeout=5)


@pytest.mark.parametrize("failure", ["create", "configure", "assign"])
def test_windows_job_setup_fails_closed_and_releases_unassigned_handle(failure):
    import ctypes
    from unittest.mock import MagicMock, patch

    from tools import code_kernel_runner as runner

    api = MagicMock()
    api.CreateJobObjectW.return_value = 0 if failure == "create" else 123
    api.SetInformationJobObject.return_value = failure != "configure"
    api.AssignProcessToJobObject.return_value = False
    with (
        patch.object(runner.os, "name", "nt"),
        patch.object(ctypes, "WinDLL", return_value=api, create=True),
        patch.object(ctypes, "get_last_error", return_value=5, create=True),
        patch.object(ctypes, "WinError", side_effect=lambda code: OSError(code, "job setup refused"), create=True),
        pytest.raises(OSError, match="job setup refused"),
    ):
        runner.own_windows_process_tree()
    if failure == "create":
        api.CloseHandle.assert_not_called()
    else:
        api.CloseHandle.assert_called_once_with(123)
    if failure != "assign":
        api.AssignProcessToJobObject.assert_not_called()


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
