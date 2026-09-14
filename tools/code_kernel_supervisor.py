"""Standalone POSIX remote kernel supervisor and authenticated file control.

The supervisor owns the child Popen handle until group shutdown. It never
rediscovers a process from a PID file. Repeated launches fail before allocation;
request admission is durable and never replayed after an uncertain interruption.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, cast

MAX_FRAME = 4 * 1024 * 1024


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=True, allow_nan=False
    ).encode()


def publish(path: Path, value: Any, key: bytes) -> None:
    body = canonical(value)
    envelope = {"payload": value, "signature": hmac.digest(key, body, "sha256").hex()}
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".control-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(envelope))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read(path: Path, key: bytes) -> dict[str, Any] | None:
    try:
        if path.is_symlink():
            raise ValueError("Control files must not be symlinks")
        with path.open("rb") as stream:
            raw = stream.read(MAX_FRAME + 1)
    except FileNotFoundError:
        return None
    if len(raw) > MAX_FRAME:
        raise ValueError("Control frame exceeds limit")
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {"payload", "signature"}:
        raise ValueError("Invalid control envelope")
    body, signature = value["payload"], value["signature"]
    if (
        not isinstance(body, dict)
        or not isinstance(signature, str)
        or len(signature) != 64
        or any(c not in "0123456789abcdef" for c in signature)
    ):
        raise ValueError("Invalid control payload")
    if not hmac.compare_digest(
        hmac.digest(key, canonical(body), "sha256").hex(), signature
    ):
        raise ValueError("Control authentication failed")
    return body


class Supervisor:
    def __init__(self, directory: Path) -> None:
        if os.name != "posix":
            raise RuntimeError("Remote kernel supervisor requires POSIX")
        self.directory = directory.resolve()
        self.key = (self.directory / ".token").read_bytes()
        if len(self.key) < 32:
            raise ValueError("Control authentication key is too short")
        self.process: subprocess.Popen[bytes] | None = None
        self.readers: list[threading.Thread] = []
        self.writer: threading.Thread | None = None
        self.frames: queue.Queue[dict[str, Any] | Exception] = queue.Queue(maxsize=3)
        self.stopping = threading.Event()
        self.diagnostics = bytearray()
        self.diagnostic_lock = threading.Lock()
        self.sequence = 0

    def _frames(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                raw = self.process.stdout.readline(MAX_FRAME + 1)
                if not raw:
                    raise RuntimeError("Kernel control stream closed")
                if len(raw) > MAX_FRAME or not raw.endswith(b"\n"):
                    raise ValueError("Kernel response exceeds limit")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError("Invalid kernel frame")
                self.frames.put(value, timeout=1)
        except Exception as exc:
            try:
                self.frames.put(exc, timeout=1)
            except queue.Full:
                self.stopping.set()

    def _stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while raw := self.process.stderr.read(8192):
            with self.diagnostic_lock:
                self.diagnostics.extend(raw)
                del self.diagnostics[:-50000]

    def _send(self, request: dict[str, Any]) -> None:
        assert self.process is not None and self.process.stdin is not None
        try:
            data = canonical(request) + b"\n"
            if len(data) > 1048576:
                raise ValueError("Kernel cell exceeds limit")
            self.process.stdin.write(data)
            self.process.stdin.flush()
        except Exception as exc:
            try:
                self.frames.put(exc, timeout=1)
            except queue.Full:
                self.stopping.set()

    def _stop(self) -> None:
        self.stopping.set()
        if self.process is None:
            return
        # No poll()/wait() happens before this kill. Even an exited leader is
        # still our unreaped child, so its process-group ID cannot be reused.
        if self.process.returncode is None:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)  # windows-footgun: ok
            except ProcessLookupError:
                pass
        self.process.wait(timeout=5)
        if self.writer is not None and self.writer.ident is not None:
            self.writer.join(timeout=2)
            if self.writer.is_alive():
                raise RuntimeError("Kernel input disposal is pending")
        for reader in self.readers:
            if reader.ident is not None:
                reader.join(timeout=2)
            if reader.is_alive():
                raise RuntimeError("Kernel output disposal is pending")
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            if stream is not None and not stream.closed:
                try:
                    stream.close()
                except BrokenPipeError:
                    pass

    def _has_running_group_children(self) -> bool:
        assert self.process is not None
        procfs = Path("/proc")
        if procfs.is_dir():
            for path in procfs.iterdir():
                if not path.name.isdigit() or int(path.name) == self.process.pid:
                    continue
                try:
                    fields = (path / "stat").read_text().rsplit(")", 1)[1].split()
                    if int(fields[2]) == self.process.pid and fields[0] not in {
                        "Z",
                        "X",
                    }:
                        return True
                except (FileNotFoundError, ProcessLookupError):
                    continue
            return False
        # macOS lacks procfs. Only the still-unreaped child handle authorizes
        # the later killpg; this command merely inventories its group.
        result = subprocess.run(
            ["ps", "-axo", "pid=,pgid=,stat="],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        for line in result.stdout.splitlines():
            pid, group, status = line.split()
            if (
                int(group) == self.process.pid
                and int(pid) != self.process.pid
                and not status.startswith(("Z", "X"))
            ):
                return True
        return False

    def run(self) -> None:
        config = read(self.directory / "config.json", self.key)
        if config is None:
            raise ValueError("Missing authenticated kernel configuration")
        lease = config.get("lease_seconds", 30)
        if (
            type(lease) not in (int, float)
            or not math.isfinite(lease)
            or not 0.2 <= lease <= 300
        ):
            raise ValueError("Invalid kernel lease")
        environment = config.get("environment")
        if not isinstance(environment, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in environment.items()
        ):
            raise ValueError("Invalid kernel environment")
        # O_EXCL admission prevents an uncertain launch retry from creating a
        # second interpreter. A stale claim is evidence for recovery, not permission.
        claim = os.open(
            self.directory / ".started", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        os.close(claim)
        reason = "supervisor_stopped"
        try:
            self.process = subprocess.Popen(
                [
                    config.get("python", sys.executable),
                    str(self.directory / "runner.py"),
                ],
                cwd=config.get("cwd", str(self.directory)),
                env={**environment, "SUPERFORECASTING_AGENT_KERNEL_OWN_GROUP": "1"},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            for target in (self._frames, self._stderr):
                thread = threading.Thread(target=target, daemon=True)
                self.readers.append(thread)
                thread.start()
            heartbeat = 0
            lease_deadline = time.monotonic() + lease
            pending: dict[str, Any] | None = None
            cell_deadline = float("inf")
            ready = False
            while not self.stopping.is_set():
                now = time.monotonic()
                beat = read(self.directory / "heartbeat.json", self.key)
                if (
                    beat is not None
                    and type(beat.get("sequence")) is int
                    and beat["sequence"] > heartbeat
                ):
                    heartbeat = beat["sequence"]
                    lease_deadline = now + lease
                if read(self.directory / "stop.json", self.key) is not None:
                    reason = "requested_stop"
                    break
                if now >= lease_deadline:
                    reason = "owner_lease_expired"
                    break
                if now >= cell_deadline:
                    reason = "cell_deadline_exceeded"
                    break
                try:
                    frame = self.frames.get(timeout=0.02)
                except queue.Empty:
                    frame = None
                if isinstance(frame, Exception):
                    raise frame
                if frame is not None:
                    if not ready:
                        if frame.get("ready") is not True or frame.get("version") != 1:
                            raise ValueError("Invalid kernel ready frame")
                        ready = True
                        publish(
                            self.directory / "ready.json", {"frame": frame}, self.key
                        )
                    elif (
                        pending is not None and frame.get("id") == pending["cell"]["id"]
                    ):
                        if self._has_running_group_children():
                            frame.update(
                                state_preserved=False,
                                retirement_reason="cell_left_running_processes",
                            )
                        publish(
                            self.directory / f"result_{self.sequence:06d}.json",
                            {
                                "request_sha256": hashlib.sha256(
                                    canonical(pending)
                                ).hexdigest(),
                                "frame": frame,
                            },
                            self.key,
                        )
                        pending = None
                        cell_deadline = float("inf")
                        if frame.get("state_preserved") is False:
                            reason = "kernel_retired"
                            break
                    else:
                        raise ValueError("Unsolicited kernel response")
                if ready and pending is None:
                    request = read(
                        self.directory / f"request_{self.sequence + 1:06d}.json",
                        self.key,
                    )
                    if request is not None:
                        duration = cast(Any, request.get("timeout"))
                        if (
                            type(duration) not in (int, float)
                            or not math.isfinite(duration)
                            or not 0 < duration <= 86400
                        ):
                            raise ValueError("Invalid cell deadline")
                        cell = request.get("cell")
                        if not isinstance(cell, dict) or not isinstance(
                            cell.get("id"), str
                        ):
                            raise ValueError("Invalid cell request")
                        self.sequence += 1
                        publish(
                            self.directory / f"admitted_{self.sequence:06d}.json",
                            request,
                            self.key,
                        )
                        pending = request
                        cell_deadline = time.monotonic() + duration
                        self.writer = threading.Thread(
                            target=self._send, args=(cell,), daemon=True
                        )
                        self.writer.start()
        except BaseException as exc:
            reason = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._stop()
            publish(
                self.directory / "stopped.json",
                {
                    "reason": reason,
                    "last_admitted_sequence": self.sequence,
                    "process_exit_confirmed": True,
                },
                self.key,
            )


def control() -> None:
    # Backward-compatible standalone invocation: supervisor.py <directory>.
    if len(sys.argv) == 2:
        Supervisor(Path(sys.argv[1])).run()
        return
    action, directory = sys.argv[1], Path(sys.argv[2]).resolve()
    if action == "run":
        Supervisor(directory).run()
        return
    key = (directory / ".token").read_bytes()
    if action == "heartbeat":
        publish(directory / "heartbeat.json", {"sequence": int(sys.argv[3])}, key)
    elif action == "stop":
        publish(directory / "stop.json", {"command": "stop"}, key)
    elif action == "read":
        name = sys.argv[3]
        if Path(name).name != name or not name.endswith(".json"):
            raise ValueError("Invalid control filename")
        print(json.dumps(read(directory / name, key)))
    elif action in {"publish", "configure"}:
        name, seed = sys.argv[3], sys.argv[4]
        if Path(name).name != name or Path(seed).name != seed:
            raise ValueError("Invalid control filename")
        source = directory / seed
        with source.open("rb") as stream:
            raw = stream.read(MAX_FRAME + 1)
        if len(raw) > MAX_FRAME:
            raise ValueError("Control seed exceeds limit")
        payload = json.loads(raw)
        if action == "configure":
            if (directory / ".started").exists():
                raise ValueError("Kernel configuration is already frozen")
            allowed = set(payload["passthrough"])
            environment = {
                k: v
                for k, v in os.environ.items()
                if k in allowed
                or (
                    not any(part in k.upper() for part in payload["secret_substrings"])
                    and any(k.startswith(prefix) for prefix in payload["safe_prefixes"])
                )
            }
            environment.update(
                PYTHONPATH=str(directory),
                PYTHONUTF8="1",
                PYTHONIOENCODING="utf-8",
                PYTHONDONTWRITEBYTECODE="1",
            )
            if payload.get("timezone"):
                environment["TZ"] = payload["timezone"]
            if payload.get("policy") == "proposal_only":
                environment["FORECAST_COMMIT_POLICY"] = "proposal_only"
            payload = {
                "environment": environment,
                "python": sys.executable,
                "cwd": payload.get("cwd") or str(directory),
                "lease_seconds": payload.get("lease_seconds", 30),
            }
            publish(directory / name, payload, key)
            print(
                json.dumps({
                    "python": payload["python"],
                    "cwd": payload["cwd"],
                    "environment_keys": sorted(environment),
                })
            )
        else:
            cell = payload.get("cell", {})
            rpc = cell.get("rpc")
            if rpc and rpc.get("transport") == "file":
                endpoint = Path(rpc["endpoint"]).resolve()
                if endpoint.parent != directory or not endpoint.name.startswith("rpc_"):
                    raise ValueError("RPC directory belongs to another owner")
                rpc["token"] = (endpoint / ".token").read_text(encoding="utf-8")
            publish(directory / name, payload, key)
        source.unlink()
    else:
        raise ValueError("Unknown kernel control operation")


if __name__ == "__main__":
    control()
