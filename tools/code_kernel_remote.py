"""Persistent analysis over the existing remote shell transport.

Transport failures retain the exact remote directory/environment owner. No PID
files are used to signal processes, and reset cannot replace uncertain work.
"""

from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import shlex
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from superforecasting_agent.tooling.call_context import CallContext
from superforecasting_agent.tooling.interrupts import cancellation_scope, is_interrupted
from tools.code_calculations import InputRecorder
from tools.code_execution_rpc import _rpc_poll_loop, prepare_remote_rpc
from tools.code_kernel import COMPAT_TOOLS_FILENAME, LocalKernel


class RemoteKernel(LocalKernel):
    def __init__(
        self, home: Path, tools: frozenset[str], policy: str | None, mode: str, env: Any
    ) -> None:
        # The local directory owns receipts and the exact shipped runner source.
        # Interpreter and working-directory selection happen inside the backend.
        super().__init__(home, tools, policy, "strict")
        from tools.code_execution_tool import _env_temp_dir

        self.env = env
        self.remote_directory = f"{_env_temp_dir(env)}/forecast_kernel_{self.id}"
        self.remote_mode = mode
        self.remote_workers: list[tuple[CallContext, threading.Thread]] = []
        self.heartbeat_stop = threading.Event()
        self.heartbeat: threading.Thread | None = None
        self.heartbeat_sequence = 0
        self.transport_error: Exception | None = None
        self.remote_created = False
        self.launch_attempted = False
        self.environment_lease: Any = None
        self.current_timeout = 300.0
        self.expected_request_hash = ""

    def _command(self, command: str, timeout: int = 10) -> str:
        result = self.execute(command, cwd="/", timeout=timeout)
        if result.get("returncode") != 0 or result.get("interrupted"):
            raise RuntimeError("Remote kernel control failed; ownership is retained")
        return str(result.get("output", "")).strip()

    def execute(self, command: str, **kwargs: Any) -> dict:
        """Borrow the backend for control I/O without changing its user CWD."""
        return self.env.execute(command, **kwargs, update_cwd=False)

    def _upload(self, name: str, content: str) -> None:
        path = shlex.quote(f"{self.remote_directory}/{name}")
        data = content.encode()
        # Keep each shell argument well below OS limits, including remote SSH
        # shims. Authentication tokens are generated remotely, never uploaded.
        for offset in range(0, max(1, len(data)), 24000):
            chunk = base64.b64encode(data[offset : offset + 24000]).decode()
            operation = "wb" if offset == 0 else "ab"
            source = f"import base64,sys; open(sys.argv[1], {operation!r}).write(base64.b64decode(sys.argv[2]))"
            self._command(
                f"python3 -c {shlex.quote(source)} {path} {shlex.quote(chunk)}"
            )

    def _control(self, action: str, *arguments: str) -> str:
        command = [
            "python3",
            f"{self.remote_directory}/supervisor.py",
            action,
            self.remote_directory,
            *arguments,
        ]
        return self._command(shlex.join(command))

    def _publish(
        self, name: str, payload: dict[str, Any], action: str = "publish"
    ) -> str:
        seed = f"seed_{uuid.uuid4().hex}.json"
        self._upload(seed, json.dumps(payload))
        return self._control(action, name, seed)

    def _read(self, name: str) -> dict[str, Any] | None:
        value = json.loads(self._control("read", name))
        if value is not None and not isinstance(value, dict):
            raise RuntimeError("Invalid remote kernel status")
        return value

    def start(self) -> None:
        from tools.code_execution_tool import (
            _SAFE_ENV_PREFIXES,
            _SECRET_SUBSTRINGS,
            _timezone_env_value,
            generate_forecast_tools_module,
        )
        from tools.env_passthrough import get_all_passthrough

        # Mark allocation as uncertain BEFORE submitting the first mutation.
        self.remote_created = True
        self._command(f"umask 077 && mkdir {shlex.quote(self.remote_directory)}")
        prepare_remote_rpc(self, self.remote_directory)
        self._upload(
            "supervisor.py",
            Path(__file__).with_name("code_kernel_supervisor.py").read_text(),
        )
        self._upload("runner.py", self.runner.read_text())
        self._upload(
            "forecast_tools.py",
            generate_forecast_tools_module(list(self.tools), transport="file"),
        )
        self._upload(
            COMPAT_TOOLS_FILENAME, (self.directory / COMPAT_TOOLS_FILENAME).read_text()
        )
        options = {
            "passthrough": sorted(get_all_passthrough()),
            "safe_prefixes": _SAFE_ENV_PREFIXES,
            "secret_substrings": _SECRET_SUBSTRINGS,
            "timezone": _timezone_env_value(),
            "policy": self.policy,
            "lease_seconds": 30,
            "cwd": getattr(self.env, "cwd", None)
            if self.remote_mode == "project"
            else self.remote_directory,
        }
        info = json.loads(self._publish("config.json", options, action="configure"))
        self.python, self.cwd = info["python"], info["cwd"]
        self.environment = dict.fromkeys(info["environment_keys"], "")
        context = contextvars.copy_context()
        self.heartbeat = threading.Thread(
            target=lambda: context.run(self._renew), daemon=True
        )
        self.heartbeat.start()
        command = shlex.join([
            "python3",
            f"{self.remote_directory}/supervisor.py",
            "run",
            self.remote_directory,
        ])
        self.launch_attempted = True
        self._command(
            f"nohup {command} >{shlex.quote(self.remote_directory + '/supervisor.log')} 2>&1 </dev/null &"
        )
        ready = self._receive(time.monotonic() + 15)
        if ready.get("ready") is not True or ready.get("version") != 1:
            raise RuntimeError("Remote kernel did not acknowledge protocol version")
        self.runtime = ready["runtime"]

    def _renew(self) -> None:
        # The kernel outlives the starting cell; profile routing survives, but
        # retirement of that cell's authority must not cancel owner maintenance.
        with cancellation_scope(self.heartbeat_stop, inherit=False):
            self._renew_owned()

    def _renew_owned(self) -> None:
        while not self.heartbeat_stop.is_set():
            try:
                self.heartbeat_sequence += 1
                self._control("heartbeat", str(self.heartbeat_sequence))
            except Exception as exc:
                self.transport_error = exc
                # Expiry on the remote owner is the fallback. Do not restart or
                # delete a kernel because its transport is temporarily unavailable.
                return
            self.heartbeat_stop.wait(5)

    def _capture_children(self) -> None:
        # Only the supervisor owns the remote Popen/process-group identity.
        return

    def _start_rpc(
        self,
        context: CallContext,
        task_id: str,
        budget: int,
        timeout: float,
        recorder: InputRecorder,
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        directory = f"{self.remote_directory}/rpc_{uuid.uuid4().hex}"
        self._command(f"umask 077 && mkdir {shlex.quote(directory)}")
        token = prepare_remote_rpc(self, directory)
        self.current_timeout = timeout
        log: list[dict[str, Any]] = []

        def serve() -> None:
            try:
                context.run(
                    _rpc_poll_loop,
                    self,
                    directory,
                    task_id,
                    log,
                    [0],
                    budget,
                    self.tools,
                    self.policy,
                    context.cancelled,
                    token,
                    recorder,
                )
            except InterruptedError:
                pass

        worker = threading.Thread(target=serve, daemon=True)
        self.remote_workers.append((context, worker))
        worker.start()
        return {"endpoint": directory, "transport": "file", "token": token}, log

    def _send_cell(self, cell: dict[str, Any]) -> None:
        payload = {"cell": cell, "timeout": self.current_timeout}
        # Hash the actual request, but let the remote helper read the RPC token
        # privately instead of putting it in an upload command argument.
        from tools.code_kernel_supervisor import canonical

        self.expected_request_hash = hashlib.sha256(canonical(payload)).hexdigest()
        copied = {**payload, "cell": {**cell, "rpc": {**cell["rpc"]}}}
        copied["cell"]["rpc"].pop("token", None)
        self._publish(f"request_{self.sequence + 1:06d}.json", copied)

    def _receive(self, deadline: float) -> dict[str, Any]:
        while time.monotonic() < deadline:
            if self.cancelled.is_set() or is_interrupted():
                raise InterruptedError("Remote kernel execution cancelled")
            if self.transport_error is not None:
                raise RuntimeError(
                    "Remote kernel lease transport is uncertain"
                ) from self.transport_error
            name = (
                "ready.json"
                if not self.runtime
                else f"result_{self.sequence + 1:06d}.json"
            )
            response = self._read(name)
            if response is not None:
                if (
                    name != "ready.json"
                    and response.get("request_sha256") != self.expected_request_hash
                ):
                    raise RuntimeError("Remote kernel request provenance mismatch")
                return response["frame"]
            stopped = self._read("stopped.json")
            if stopped is not None:
                raise RuntimeError(
                    f"Remote kernel stopped: {stopped.get('reason', 'unknown')}"
                )
            time.sleep(0.05)
        raise TimeoutError("Remote kernel execution deadline exceeded")

    def _finish_rpc(self) -> None:
        retained = []
        for context, worker in self.remote_workers:
            context.retire()
            if worker.ident is not None:
                worker.join(timeout=2)
            if worker.is_alive():
                retained.append((context, worker))
        self.remote_workers = retained
        if retained:
            raise RuntimeError("Remote kernel tool cleanup is pending")

    def close(self) -> None:
        # Stopping an interrupted call still requires bounded control I/O to
        # confirm termination. User cancellation cannot cancel that cleanup.
        with cancellation_scope(threading.Event(), inherit=False):
            self._close_owned()

    def _close_owned(self) -> None:
        self.cancelled.set()
        self.heartbeat_stop.set()
        if self.heartbeat is not None and self.heartbeat.ident is not None:
            self.heartbeat.join(timeout=12)
            if self.heartbeat.is_alive():
                raise RuntimeError("Remote kernel heartbeat cleanup is pending")
        if not self.lock.acquire(timeout=5):
            raise RuntimeError("Remote kernel execution cleanup is pending")
        try:
            if self.remote_created and not self.launch_attempted:
                self._command(f"rm -rf {shlex.quote(self.remote_directory)}")
                self.remote_created = False
            if self.remote_created:
                self._control("stop")
                deadline = time.monotonic() + 10
                while True:
                    receipt = self._read("stopped.json")
                    if (
                        receipt is not None
                        and receipt.get("process_exit_confirmed") is True
                    ):
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Remote kernel termination is unconfirmed; ownership retained"
                        )
                    time.sleep(0.05)
                self._finish_rpc()
                self._command(f"rm -rf {shlex.quote(self.remote_directory)}")
                self.remote_created = False
        finally:
            self.lock.release()
        super().close()
        if self.environment_lease is not None:
            self.environment_lease.release()
