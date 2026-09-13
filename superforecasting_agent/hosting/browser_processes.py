"""Record daemon identity at acquisition and require confirmed exit at disposal."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

import psutil

from superforecasting_agent.processes import read_pid_file


def record_daemon(directory: Path, session: str) -> None:
    pid_path = directory / f"{session}.pid"
    if not pid_path.exists():
        return
    pid = read_pid_file(pid_path)
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return
    identity = {"version": 1, "pid": pid, "created": created}
    target = directory / f"{session}.daemon_identity.json"
    if target.exists():
        if json.loads(target.read_text(encoding="utf-8")) != identity:
            raise RuntimeError(
                "Browser daemon identity changed; cleanup requires review"
            )
        return
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=".daemon-identity-")
    try:
        stream = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with stream:
            json.dump(identity, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if fd >= 0:
            os.close(fd)
        Path(temporary).unlink(missing_ok=True)


def stop_daemon(directory: Path, session: str, *, timeout: float = 3) -> None:
    """Never signal a PID inferred only from an old file; retain on uncertainty."""
    pid_path = directory / f"{session}.pid"
    if not pid_path.exists():
        return
    pid = read_pid_file(pid_path)
    try:
        process = psutil.Process(pid)
        created = process.create_time()
    except psutil.NoSuchProcess:
        return
    try:
        identity = json.loads(
            (directory / f"{session}.daemon_identity.json").read_text(encoding="utf-8")
        )
        valid = (
            identity.get("version") == 1
            and type(identity.get("pid")) is int
            and identity["pid"] == pid
            and type(identity.get("created")) in (int, float)
            and math.isfinite(identity["created"])
            and identity["created"] == created
        )
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise RuntimeError(
            "Browser daemon identity is unverified; retaining resources"
        ) from exc
    if not valid:
        raise RuntimeError("Browser daemon PID was replaced; refusing to signal it")
    try:
        # psutil's Process.terminate also checks identity before signaling.
        process.terminate()
        process.wait(timeout=timeout)
    except psutil.NoSuchProcess:
        return
    except psutil.TimeoutExpired as exc:
        raise RuntimeError("Browser daemon termination is pending") from exc
