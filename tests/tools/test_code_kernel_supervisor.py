"""Real remote-supervisor processes: authentication, durable admission and lease."""

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import psutil
import pytest

from tools.code_kernel_supervisor import Supervisor, canonical, publish, read

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="Remote shell supervisor is POSIX"
)
ROOT = Path(__file__).resolve().parents[2]


def wait_record(directory, name, key, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = read(directory / name, key)
        if value is not None:
            return value
        time.sleep(0.01)
    raise AssertionError(f"No {name} after {timeout}s")


@contextmanager
def supervisor(tmp_path, lease=5):
    directory = tmp_path / secrets.token_hex(8)
    directory.mkdir(mode=0o700)
    key = secrets.token_bytes(32)
    (directory / ".token").write_bytes(key)
    shutil.copyfile(ROOT / "tools/code_kernel_runner.py", directory / "runner.py")
    publish(
        directory / "config.json",
        {
            "lease_seconds": lease,
            "python": sys.executable,
            "cwd": str(directory),
            "environment": {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(directory),
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        },
        key,
    )
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "tools/code_kernel_supervisor.py"), str(directory)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        ready = wait_record(directory, "ready.json", key)
        assert ready["frame"]["ready"]
        yield directory, key, process
    finally:
        publish(directory / "stop.json", {"command": "stop"}, key)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stderr.close()


def submit(directory, key, number, code, timeout=3):
    payload = {
        "timeout": timeout,
        "cell": {"id": f"cell-{number}", "code": code, "reset": False},
    }
    publish(directory / f"request_{number:06d}.json", payload, key)
    return payload


def stopped(pid):
    try:
        return psutil.Process(pid).status() in {
            psutil.STATUS_ZOMBIE,
            psutil.STATUS_DEAD,
        }
    except psutil.NoSuchProcess:
        return True


def test_retained_state_and_duplicate_delivery_never_repeat_effect(tmp_path):
    with supervisor(tmp_path) as (directory, key, _):
        request = submit(directory, key, 1, "value = 10\nprint(value)")
        first = wait_record(directory, "result_000001.json", key)
        assert first["frame"]["stdout"] == "10\n"
        admission = (directory / "admitted_000001.json").read_bytes()
        submit(directory, key, 1, "value = 999")
        submit(directory, key, 2, "print(value + 1)")
        assert (
            wait_record(directory, "result_000002.json", key)["frame"]["stdout"]
            == "11\n"
        )
        assert admission == (directory / "admitted_000001.json").read_bytes()
        import hashlib

        assert first["request_sha256"] == hashlib.sha256(canonical(request)).hexdigest()


def test_uncertain_launch_cannot_allocate_another_kernel(tmp_path):
    with supervisor(tmp_path) as (directory, key, first):
        duplicate = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/code_kernel_supervisor.py"),
                str(directory),
            ],
            capture_output=True,
            timeout=5,
        )
        assert duplicate.returncode != 0
        assert first.poll() is None
        submit(directory, key, 1, 'print("original")')
        assert (
            wait_record(directory, "result_000001.json", key)["frame"]["stdout"]
            == "original\n"
        )


def test_expired_lease_stops_a_running_cell_and_its_process_group(tmp_path):
    with supervisor(tmp_path, lease=1) as (directory, key, process):
        marker = directory / "pids.json"
        submit(
            directory,
            key,
            1,
            "import os, sys, json, subprocess\nfrom pathlib import Path\n"
            'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
            f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\nwhile True: pass",
            timeout=30,
        )
        end = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < end:
            time.sleep(0.01)
        pids = json.loads(marker.read_text())
        receipt = wait_record(directory, "stopped.json", key)
        assert receipt["reason"] == "owner_lease_expired"
        assert receipt["process_exit_confirmed"]
        process.wait(timeout=3)
        assert all(stopped(pid) for pid in pids)


def test_old_heartbeat_replay_does_not_extend_lease(tmp_path):
    with supervisor(tmp_path, lease=0.5) as (directory, key, process):
        publish(directory / "heartbeat.json", {"sequence": 2}, key)
        time.sleep(0.2)
        publish(directory / "heartbeat.json", {"sequence": 1}, key)
        time.sleep(0.2)
        publish(directory / "heartbeat.json", {"sequence": 2}, key)
        assert (
            wait_record(directory, "stopped.json", key)["reason"]
            == "owner_lease_expired"
        )
        process.wait(timeout=3)


def test_supervisor_death_stops_running_kernel_group_but_not_sibling(tmp_path):
    sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    owned = []
    try:
        with supervisor(tmp_path) as (directory, key, process):
            marker = directory / "owned.json"
            submit(
                directory, key, 1,
                "import os, sys, json, subprocess\nfrom pathlib import Path\n"
                'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\n'
                f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n"
                "while True: pass",
                timeout=30,
            )
            end = time.monotonic() + 4
            while not marker.exists() and time.monotonic() < end:
                time.sleep(0.01)
            owned = [psutil.Process(pid) for pid in json.loads(marker.read_text())]
            process.kill()
            process.wait(timeout=3)
            end = time.monotonic() + 4
            while any(p.is_running() and p.status() != psutil.STATUS_ZOMBIE for p in owned):
                assert time.monotonic() < end, "owner EOF left a running descendant"
                time.sleep(0.01)
            assert sibling.poll() is None
            # A dead supervisor cannot fabricate confirmation of its own cleanup.
            assert read(directory / "stopped.json", key) is None
    finally:
        for child in owned:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        sibling.kill()
        sibling.wait(timeout=3)


def test_bad_authentication_never_executes_a_cell(tmp_path):
    with supervisor(tmp_path) as (directory, key, _):
        marker = directory / "forbidden"
        publish(
            directory / "request_000001.json",
            {
                "timeout": 3,
                "cell": {
                    "id": "bad",
                    "code": f'open({str(marker)!r}, "w").close()',
                    "reset": False,
                },
            },
            b"another-private-key",
        )
        receipt = wait_record(directory, "stopped.json", key)
        assert "authentication failed" in receipt["reason"]
        assert not marker.exists()
        assert not (directory / "admitted_000001.json").exists()


def test_repeated_cleanup_never_signals_reaped_pid(tmp_path, monkeypatch):
    directory = tmp_path / "owner"
    directory.mkdir()
    (directory / ".token").write_bytes(b"x" * 32)
    owner = Supervisor(directory)
    owner.process = subprocess.Popen(
        [sys.executable, "-c", "pass"], start_new_session=True
    )
    owner.process.wait(timeout=5)
    monkeypatch.setattr(
        os,
        "killpg",
        lambda *args: pytest.fail("reaped process group must not be signalled"),
    )
    owner._stop()
    owner._stop()
