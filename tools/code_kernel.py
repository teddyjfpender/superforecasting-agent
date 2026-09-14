"""Owned local analysis interpreter with fresh authority and durable cell receipts.

An owner is attached to an agent object, never recovered by a reusable session
identifier. A failed cleanup retains the exact process, pipes and RPC workers.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil

from agent.redact import redact_sensitive_text
from superforecasting_agent.storage.files import atomic_json_write
from superforecasting_agent.tooling.call_context import CallContext
from superforecasting_agent.tooling.interrupts import is_interrupted
from tools import code_execution_rpc
from tools.code_calculations import InputRecorder, display_output, sealed
from tools.code_execution_rpc import _rpc_server_loop

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
COMPAT_TOOLS_FILENAME = "hermes_tools.py"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="surrogatepass")).hexdigest()


def _redact(value: str) -> str:
    return redact_sensitive_text(value, force=True)


class LocalKernel:
    def __init__(
        self, home: Path, tools: frozenset[str], policy: str | None, mode: str
    ) -> None:
        from tools.code_execution_tool import (
            _resolve_child_cwd,
            _resolve_child_python,
            build_child_env,
            generate_forecast_tools_module,
        )

        self.id = uuid.uuid4().hex
        self.directory = home / "calculations" / self.id
        self.directory.mkdir(parents=True, mode=0o700)
        self.tools, self.policy = tools, policy
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.frames: queue.Queue[dict[str, Any] | Exception] = queue.Queue(maxsize=2)
        self.readers: list[threading.Thread] = []
        self.writer: threading.Thread | None = None
        self.rpc_workers: list[tuple[CallContext, socket.socket, threading.Thread]] = []
        self.diagnostics = bytearray()
        self.diagnostic_lock = threading.Lock()
        self.previous = ""
        self.previous_record = ""
        self.runtime: dict[str, Any] = {}
        self.sequence = 0
        self.process: subprocess.Popen[bytes] | None = None
        self.children: dict[tuple[int, float], psutil.Process] = {}
        self.identity: psutil.Process | None = None
        self.python = _resolve_child_python(mode)
        self.cwd = _resolve_child_cwd(mode, str(self.directory))
        source = generate_forecast_tools_module(list(tools))
        (self.directory / "forecast_tools.py").write_text(source, encoding="utf-8")
        (self.directory / COMPAT_TOOLS_FILENAME).write_text(
            "from forecast_tools import *\n", encoding="utf-8"
        )
        runner = self.directory / "runner.py"
        shutil.copyfile(Path(__file__).with_name("code_kernel_runner.py"), runner)
        self.environment = build_child_env(str(self.directory), "", "", policy)
        if os.name == "posix":
            self.environment["SUPERFORECASTING_AGENT_KERNEL_OWN_GROUP"] = "1"
        self.runner = runner

    def start(self) -> None:
        try:
            self.process = subprocess.Popen(
                [self.python, str(self.runner)],
                cwd=self.cwd,
                env=self.environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name != "nt",
            )
            self.identity = psutil.Process(self.process.pid)
            self.identity.create_time()  # acquire identity before any cleanup
            for target in (self._read_frames, self._read_diagnostics):
                thread = threading.Thread(target=target, daemon=True)
                self.readers.append(thread)
                thread.start()
            ready = self._receive(time.monotonic() + 10)
            if (
                ready.get("ready") is not True
                or ready.get("version") != 1
                or not isinstance(ready.get("runtime"), dict)
            ):
                raise RuntimeError("Kernel did not acknowledge protocol version 1")
            self.runtime = ready["runtime"]
        except BaseException:
            self.cancelled.set()
            self.close()
            raise

    def _read_frames(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                raw = self.process.stdout.readline(MAX_RESPONSE_BYTES + 1)
                if not raw:
                    raise RuntimeError("Kernel control stream closed")
                if len(raw) > MAX_RESPONSE_BYTES or not raw.endswith(b"\n"):
                    raise RuntimeError("Kernel response exceeds frame limit")
                frame = json.loads(raw)
                if not isinstance(frame, dict):
                    raise RuntimeError("Invalid kernel response object")
                self.frames.put(frame, timeout=1)
        except Exception as exc:
            try:
                self.frames.put(exc, timeout=1)
            except queue.Full:
                self.cancelled.set()

    def _read_diagnostics(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while chunk := self.process.stderr.read(8192):
            with self.diagnostic_lock:
                self.diagnostics.extend(chunk)
                del self.diagnostics[:-50_000]

    def _capture_children(self) -> None:
        if self.identity is None:
            return
        try:
            for child in self.identity.children(recursive=True):
                self.children[(child.pid, child.create_time())] = child
        except psutil.NoSuchProcess:
            pass

    def _receive(self, deadline: float) -> dict[str, Any]:
        while True:
            if self.cancelled.is_set() or is_interrupted():
                raise InterruptedError("Kernel execution cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Kernel execution deadline exceeded")
            self._capture_children()
            try:
                frame = self.frames.get(timeout=min(0.05, remaining))
            except queue.Empty:
                continue
            if isinstance(frame, Exception):
                raise frame
            return frame

    def _start_rpc(
        self,
        context: CallContext,
        task_id: str,
        budget: int,
        timeout: float,
        recorder: InputRecorder,
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
        except BaseException:
            listener.close()
            raise
        token = secrets.token_urlsafe(32)
        log: list[dict[str, Any]] = []
        counter = [0]

        def serve() -> None:
            try:
                context.run(
                    _rpc_server_loop,
                    listener,
                    task_id,
                    log,
                    counter,
                    budget,
                    self.tools,
                    self.policy,
                    token,
                    context.cancelled,
                    timeout,
                    recorder,
                )
            except InterruptedError:
                pass

        worker = threading.Thread(target=serve, daemon=True)
        self.rpc_workers.append((context, listener, worker))
        worker.start()
        return {
            "endpoint": f"tcp://127.0.0.1:{listener.getsockname()[1]}",
            "token": token,
        }, log

    def _send_cell(self, cell: dict[str, Any]) -> None:
        request = json.dumps(cell).encode() + b"\n"
        if len(request) > 1_048_576:
            raise ValueError("Kernel cell exceeds request limit")
        assert self.process is not None and self.process.stdin is not None

        def send() -> None:
            assert self.process is not None and self.process.stdin is not None
            try:
                self.process.stdin.write(request)
                self.process.stdin.flush()
            except Exception as exc:
                try:
                    self.frames.put(exc, timeout=1)
                except queue.Full:
                    self.cancelled.set()

        self.writer = threading.Thread(target=send, daemon=True)
        self.writer.start()

    def run(
        self,
        code: str,
        task_id: str,
        timeout: float,
        budget: int,
        dispatch_override: Callable[[str, dict], str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while not self.lock.acquire(timeout=0.05):
            if self.cancelled.is_set() or is_interrupted():
                raise InterruptedError("Kernel execution cancelled while queued")
            if time.monotonic() >= deadline:
                raise TimeoutError("Kernel execution deadline exceeded while queued")
        receipt: dict[str, Any] | None = None
        recorder: InputRecorder | None = None
        context = CallContext()
        try:
            if is_interrupted():
                raise InterruptedError("Kernel execution cancelled before admission")
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Kernel execution deadline exceeded before admission"
                )
            if self.cancelled.is_set():
                raise RuntimeError(
                    "Kernel retired; explicitly reset to start a new interpreter"
                )
            self._finish_rpc()
            call_id = uuid.uuid4().hex
            receipt = {
                "version": 2,
                "previous_record_sha256": self.previous_record,
                "max_tool_calls": budget,
                "runtime": self.runtime,
                "runner_sha256": hashlib.sha256(self.runner.read_bytes()).hexdigest(),
                "environment_keys": sorted(self.environment),
                "kernel_id": self.id,
                "cell_id": call_id,
                "sequence": self.sequence + 1,
                "previous_result_sha256": self.previous,
                "code": _redact(code),
                "code_sha256": _digest(code),
                "code_redacted": _redact(code) != code,
                "status": "running",
                "interpreter": self.python,
                "cwd": self.cwd,
                "tools": sorted(self.tools),
                "forecast_commit_policy": self.policy,
                "created_at": time.time(),
            }
            # Fail before execution if provenance cannot be made durable.
            atomic_json_write(self.directory / f"{call_id}.json", sealed(receipt))
            recorder = InputRecorder(
                self.directory / f"{call_id}.inputs",
                dispatch_override
                or code_execution_rpc._dispatcher(task_id, self.policy),
            )
            rpc, log = self._start_rpc(context, task_id, budget, timeout, recorder)
            if self.cancelled.is_set() or is_interrupted():
                raise InterruptedError("Kernel execution cancelled before dispatch")
            if time.monotonic() >= deadline:
                raise TimeoutError("Kernel execution deadline exceeded before dispatch")
            self._send_cell({"id": call_id, "code": code, "reset": False, "rpc": rpc})
            raw = self._receive(deadline)
            self._capture_children()
            if (
                raw.get("id") != call_id
                or raw.get("sequence") != self.sequence + 1
                or raw.get("previous_sha256") != self.previous
                or raw.get("code_sha256") != _digest(code)
            ):
                raise RuntimeError("Kernel calculation provenance mismatch")
            self.previous = _digest(json.dumps(raw, ensure_ascii=True, sort_keys=True))
            self.sequence += 1
            result = {
                **raw,
                "stdout": _redact(raw["stdout"]),
                "stderr": _redact(raw["stderr"]),
            }
            if any(child.is_running() for child in self.children.values()):
                result.update(
                    state_preserved=False,
                    retirement_reason="cell_left_running_processes",
                )
            receipt.update({
                "status": "failed" if raw.get("error") else "completed",
                "result_sha256": self.previous,
                "finished_at": time.time(),
                "result": result,
                "result_redacted": result["stdout"] != raw["stdout"]
                or result["stderr"] != raw["stderr"],
                "tool_calls": log,
            })
            receipt.update(recorder.snapshot())
            receipt = sealed(receipt)
            atomic_json_write(self.directory / f"{call_id}.json", receipt)
            self.previous_record = receipt["record_sha256"]
            if not result.get("state_preserved"):
                self.cancelled.set()
            stdout, stdout_omitted = display_output(result["stdout"], 50_000)
            stderr, stderr_omitted = display_output(result["stderr"], 10_000)
            return {
                **receipt["result"],
                "stdout": stdout,
                "stderr": stderr,
                "display_stdout_omitted_bytes": stdout_omitted,
                "display_stderr_omitted_bytes": stderr_omitted,
                "kernel_id": self.id,
                "calculation_record": str(self.directory / f"{call_id}.json"),
                "tool_calls": log,
            }
        except BaseException as exc:
            self.cancelled.set()
            if receipt is not None:
                receipt.update(
                    status="interrupted",
                    error=_redact(str(exc)),
                    finished_at=time.time(),
                )
                if recorder is not None:
                    receipt.update(recorder.snapshot())
                atomic_json_write(
                    self.directory / f"{receipt['cell_id']}.json", sealed(receipt)
                )
            raise
        finally:
            context.retire()
            self.lock.release()
            if self.cancelled.is_set():
                self.close()

    def _finish_rpc(self) -> None:
        retained = []
        for context, listener, worker in self.rpc_workers:
            context.retire()
            if worker.ident is not None:
                worker.join(timeout=1)
            if worker.is_alive():
                retained.append((context, listener, worker))
            else:
                listener.close()
        self.rpc_workers = retained
        if retained:
            raise RuntimeError(
                "Kernel tool cleanup is pending; authority cannot advance"
            )

    def close(self) -> None:
        self.cancelled.set()
        if not self.lock.acquire(timeout=5):
            raise RuntimeError("Kernel execution cleanup is pending")
        try:
            self._capture_children()
            if self.process is not None:
                # Closing a buffered stream while its writer is blocked can
                # deadlock. Stop its exact child first, then join the writer.
                if self.writer is not None and self.writer.is_alive():
                    self.process.kill()
                    self.process.wait(timeout=2)
                    self.writer.join(timeout=2)
                    if self.writer.is_alive():
                        raise RuntimeError("Kernel input cleanup is pending")
                if self.process.stdin is not None and not self.process.stdin.closed:
                    try:
                        self.process.stdin.close()
                    except BrokenPipeError:
                        pass
                for child in self.children.values():
                    try:
                        child.kill()  # psutil verifies the captured process identity
                    except psutil.NoSuchProcess:
                        pass
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
                deadline = time.monotonic() + 2
                pending = list(self.children.values())
                while pending:
                    alive = []
                    for child in pending:
                        try:
                            # A reparented grandchild is not waitpid()-owned by
                            # this host. Inspect its acquired identity instead
                            # of falling back to a bare PID existence probe.
                            if child.is_running() and child.status() not in {
                                psutil.STATUS_ZOMBIE,
                                psutil.STATUS_DEAD,
                            }:
                                alive.append(child)
                        except psutil.NoSuchProcess:
                            pass
                    if not alive:
                        break
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Kernel child-process cleanup is pending")
                    pending = alive
                    time.sleep(0.01)
                self.children.clear()
            self._finish_rpc()
            for reader in self.readers:
                if reader.ident is not None:
                    reader.join(timeout=1)
                if reader.is_alive():
                    raise RuntimeError("Kernel pipe cleanup is pending")
            if self.process is not None:
                for stream in (self.process.stdout, self.process.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            # Receipts and code records remain; only ephemeral RPC modules go.
            for name in ("runner.py", "forecast_tools.py", COMPAT_TOOLS_FILENAME):
                (self.directory / name).unlink(missing_ok=True)
        finally:
            self.lock.release()


class KernelOwner:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.kernel: LocalKernel | None = None
        self.key: tuple[Any, ...] | None = None
        self.lock = threading.RLock()
        self.closed = False

    def run(
        self,
        code: str,
        task_id: str,
        tools: frozenset[str],
        policy: str | None,
        mode: str,
        timeout: float,
        budget: int,
        reset: bool,
        *,
        dispatch_override: Callable[[str, dict], str] | None = None,
        backend: str = "local",
    ) -> dict[str, Any]:
        if type(reset) is not bool:
            raise ValueError("reset must be a boolean")
        if (
            type(timeout) not in (int, float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("timeout must be positive and finite")
        if type(budget) is not int or budget < 0:
            raise ValueError("max_tool_calls must be a nonnegative integer")
        key = (tools, policy, mode, backend)
        with self.lock:
            if self.closed:
                raise RuntimeError("Execution owner is closed")
            if self.kernel is not None and reset:
                self.kernel.close()
                self.kernel = None
            if self.kernel is not None and self.key != key:
                raise RuntimeError("Kernel configuration changed; use reset=true")
            if self.kernel is not None and backend == "local":
                from tools.code_execution_tool import (
                    _resolve_child_cwd,
                    _resolve_child_python,
                )

                if self.kernel.python != _resolve_child_python(
                    mode
                ) or self.kernel.cwd != _resolve_child_cwd(
                    mode, str(self.kernel.directory)
                ):
                    raise RuntimeError(
                        "Kernel interpreter or working directory changed; use reset=true"
                    )
            if self.kernel is not None and backend != "local":
                from tools import terminal_tool
                from tools.code_kernel_remote import RemoteKernel

                lookup = terminal_tool._resolve_container_task_id(task_id)
                with terminal_tool._env_lock:
                    current = terminal_tool._active_environments.get(lookup)
                if (
                    not isinstance(self.kernel, RemoteKernel)
                    or current is not self.kernel.env
                ):
                    raise RuntimeError("Kernel environment changed; use reset=true")
                if mode == "project" and self.kernel.cwd != current.cwd:
                    raise RuntimeError(
                        "Kernel working directory changed; use reset=true"
                    )
            if self.kernel is None:
                if backend == "local":
                    self.kernel = LocalKernel(self.home, tools, policy, mode)
                else:
                    from tools.code_kernel_remote import RemoteKernel
                    from tools.environments.leases import acquire

                    environment, lease = acquire(task_id)
                    try:
                        self.kernel = RemoteKernel(
                            self.home, tools, policy, mode, environment
                        )
                        self.kernel.environment_lease = lease
                    except BaseException:
                        lease.release()
                        raise
                self.key = key
                self.kernel.start()
            kernel = self.kernel
        return kernel.run(code, task_id, timeout, budget, dispatch_override)

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.kernel is not None:
                self.kernel.close()
                self.kernel = None


_owner_attachment_lock = threading.RLock()


def owner_for(agent: Any) -> KernelOwner:
    """Bind kernel lifetime to this exact agent and its current profile/session."""
    from superforecasting_agent.constants import get_agent_home

    session = getattr(agent, "session_id", None)
    if not isinstance(session, str) or not session:
        raise RuntimeError("Persistent execution requires a session owner")
    identity = (str(Path(get_agent_home()).resolve()), session)
    with _owner_attachment_lock:
        if getattr(agent, "_resources_closed", False):
            raise RuntimeError("Agent resources are closed")
        owner = getattr(agent, "_code_kernel_owner", None)
        if (
            owner is not None
            and getattr(agent, "_code_kernel_identity", None) != identity
        ):
            owner.close()
            owner = None
        if owner is None:
            owner = KernelOwner(Path(identity[0]))
            agent._code_kernel_owner = owner
            agent._code_kernel_identity = identity
        return owner
