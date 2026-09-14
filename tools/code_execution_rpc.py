"""Authenticated, bounded tool RPC shared by local and remote code execution.

The caller owns listeners and call lifetime. This module owns accepted sockets
and request validation; the standard tool dispatcher owns tool semantics. Its
transport loops run under the submitting CallContext, never ambient worker state.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import secrets
import shlex
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

from agent.redact import redact_sensitive_text
from agent.thread_scoped_output import thread_scoped_silence
from superforecasting_agent.tooling.interrupts import is_interrupted
from tools.registry import tool_error

logger = logging.getLogger(__name__)
MAX_REQUEST_BYTES = 8 * 1024 * 1024
_TERMINAL_BLOCKED_PARAMS = frozenset({
    "background",
    "pty",
    "notify",
    "notify_on_complete",
    "watch_patterns",
})


def prepare_remote_rpc(env: Any, directory: str) -> str:
    """Generate a private remote token without putting its value in shell argv."""
    source = (
        "import os, secrets, sys\n"
        "token = secrets.token_urlsafe(32)\n"
        "fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)\n"
        "with os.fdopen(fd, 'w') as stream:\n"
        "    stream.write(token)\n"
        "    stream.flush()\n"
        "    os.fsync(stream.fileno())\n"
        "print(token)\n"
    )
    result = env.execute(
        f"python3 -c {shlex.quote(source)} {shlex.quote(directory + '/.token')}",
        cwd="/",
        timeout=10,
    )
    token = str(result.get("output", "")).strip()
    if result.get("returncode") != 0 or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise RuntimeError("Could not initialize remote RPC authentication")
    return token


def _handle_request(
    request: Any,
    *,
    token: str,
    allowed: frozenset[str],
    counter: list[int],
    budget: int,
    dispatch: Callable[[str, dict], str],
    log: list,
) -> str:
    if not isinstance(request, dict) or set(request) - {"token", "tool", "args", "seq"}:
        return tool_error("Invalid RPC request object")
    supplied = request.get("token")
    if (
        not token
        or not isinstance(supplied, str)
        or not secrets.compare_digest(
            supplied.encode("utf-8", errors="surrogatepass"), token.encode()
        )
    ):
        return tool_error("Unauthorized RPC request")
    try:
        json.dumps(request, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return tool_error("RPC arguments must contain finite JSON values")
    name, args = request.get("tool"), request.get("args")
    if not isinstance(name, str) or not isinstance(args, dict):
        return tool_error("RPC tool must be a name and args must be an object")
    if "seq" in request and (
        type(request["seq"]) is not int or not 0 <= request["seq"] < 2**63
    ):
        return tool_error("RPC sequence must be a nonnegative integer")
    if name not in allowed:
        return tool_error(f"Tool '{name}' is not available in execute_code")
    if is_interrupted():
        return tool_error("Execution call authority has retired")
    if counter[0] >= budget:
        return tool_error(f"Tool call limit reached ({budget})")
    args = dict(args)
    if name == "terminal":
        for parameter in _TERMINAL_BLOCKED_PARAMS:
            args.pop(parameter, None)
    # Admit and charge before the effect, including dispatches that later fail.
    counter[0] += 1
    started = time.monotonic()
    try:
        with thread_scoped_silence():
            result = dispatch(name, args)
        if not isinstance(result, str):
            return tool_error("Tool returned an invalid RPC response type")
        return result
    except Exception as exc:
        logger.debug("Execution RPC tool failed", exc_info=True)
        return tool_error(redact_sensitive_text(str(exc), force=True))
    finally:
        log.append({
            "tool": name,
            "args_preview": redact_sensitive_text(str(args), force=True)[:80],
            "duration": round(time.monotonic() - started, 2),
        })


def _dispatcher(task_id: str, policy: str | None) -> Callable[[str, dict], str]:
    from superforecasting_agent.tooling.runtime import handle_function_call

    def dispatch(name: str, args: dict) -> str:
        kwargs: dict[str, Any] = {"task_id": task_id}
        if policy:
            kwargs["main_runtime"] = {"forecast_commit_policy": policy}
        return handle_function_call(name, args, **kwargs)

    return dispatch


def _rpc_server_loop(
    server_sock: socket.socket,
    task_id: str,
    tool_call_log: list,
    tool_call_counter: list[int],
    max_tool_calls: int,
    allowed_tools: frozenset[str],
    forecast_commit_policy: str | None = None,
    rpc_token: str = "",
    stop_event: threading.Event | None = None,
    accept_timeout: float = 5.0,
    dispatch_override: Callable[[str, dict], str] | None = None,
) -> None:
    """Own one accepted connection, with bounded framing and responsive shutdown."""
    stop = stop_event or threading.Event()
    dispatch = dispatch_override or _dispatcher(task_id, forecast_commit_policy)
    conn = None
    try:
        server_sock.settimeout(0.1)
        accept_deadline = time.monotonic() + accept_timeout
        while not stop.is_set() and not is_interrupted():
            try:
                conn, _ = server_sock.accept()
                break
            except socket.timeout:
                if time.monotonic() >= accept_deadline:
                    return
        if conn is None:
            return
        conn.settimeout(0.1)
        buf = b""
        idle_deadline = time.monotonic() + 300
        while not stop.is_set() and not is_interrupted():
            try:
                chunk = conn.recv(65536)
            except socket.timeout:
                if time.monotonic() >= idle_deadline:
                    return
                continue
            if not chunk:
                return
            idle_deadline = time.monotonic() + 300
            buf += chunk
            if len(buf) > MAX_REQUEST_BYTES:
                conn.sendall(
                    (tool_error("RPC request exceeds the frame limit") + "\n").encode()
                )
                return
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if stop.is_set() or is_interrupted():
                    return
                if not line.strip():
                    continue
                try:
                    request = json.loads(line)
                except (ValueError, UnicodeDecodeError, RecursionError):
                    result = tool_error("Invalid RPC JSON")
                else:
                    result = _handle_request(
                        request,
                        token=rpc_token,
                        allowed=allowed_tools,
                        counter=tool_call_counter,
                        budget=max_tool_calls,
                        dispatch=dispatch,
                        log=tool_call_log,
                    )
                conn.sendall((result + "\n").encode())
    except OSError:
        logger.debug("Execution RPC connection closed", exc_info=True)
    finally:
        if conn is not None:
            conn.close()


def _rpc_poll_loop(
    env: Any,
    rpc_dir: str,
    task_id: str,
    tool_call_log: list,
    tool_call_counter: list[int],
    max_tool_calls: int,
    allowed_tools: frozenset[str],
    forecast_commit_policy: str | None,
    stop_event: threading.Event,
    rpc_token: str = "",
) -> None:
    """Use the same admission rules for bounded remote request files."""
    dispatch = _dispatcher(task_id, forecast_commit_policy)
    quoted_dir = shlex.quote(rpc_dir)
    pending: dict[int, tuple[str, str]] = {}
    settled: set[int] = set()
    while not stop_event.is_set() and not is_interrupted():
        try:
            listed = env.execute(
                f"ls -1 {quoted_dir}/req_* 2>/dev/null || true", cwd="/", timeout=10
            )
            paths = str(listed.get("output", "")).split("\n", 128)[:128]
            for path in sorted(paths):
                if stop_event.is_set() or is_interrupted():
                    return
                # Never let listing output select an unrelated file or shell path.
                basename = path.removeprefix(rpc_dir + "/")
                if path != rpc_dir + "/" + basename or not re.fullmatch(
                    r"req_[0-9]{1,20}", basename
                ):
                    continue
                quoted_path = shlex.quote(path)
                read = env.execute(
                    f"head -c {MAX_REQUEST_BYTES + 1} {quoted_path}",
                    cwd="/",
                    timeout=10,
                )
                text = str(read.get("output", ""))
                try:
                    request = (
                        json.loads(text)
                        if len(text.encode()) <= MAX_REQUEST_BYTES
                        else None
                    )
                except (ValueError, RecursionError):
                    request = None
                seq = request.get("seq") if isinstance(request, dict) else None
                # Invalid sequences cannot select arbitrary response paths.
                if type(seq) is not int or not 0 <= seq < 2**63:
                    env.execute(f"rm -f {quoted_path}", cwd="/", timeout=5)
                    continue
                if basename != f"req_{seq:06d}":
                    env.execute(f"rm -f {quoted_path}", cwd="/", timeout=5)
                    continue
                digest = hashlib.sha256(text.encode()).hexdigest()
                cached = pending.get(seq)
                if seq in settled:
                    result = tool_error(
                        "RPC sequence has already settled; it cannot execute again"
                    )
                elif cached is not None:
                    result = (
                        cached[1]
                        if cached[0] == digest
                        else tool_error(
                            "RPC sequence was reused with different content"
                        )
                    )
                else:
                    before_calls = tool_call_counter[0]
                    result = _handle_request(
                        request,
                        token=rpc_token,
                        allowed=allowed_tools,
                        counter=tool_call_counter,
                        budget=max_tool_calls,
                        dispatch=dispatch,
                        log=tool_call_log,
                    )
                    if tool_call_counter[0] > before_calls:
                        # Keep the result before attempting delivery. A failed
                        # write or remove must retry delivery, never the effect.
                        pending[seq] = (digest, result)
                destination = shlex.quote(f"{rpc_dir}/res_{seq:06d}")
                encoded = base64.b64encode(result.encode()).decode("ascii")
                written = env.execute(
                    f"echo '{encoded}' | base64 -d > {destination}.tmp && mv {destination}.tmp {destination}",
                    cwd="/",
                    timeout=60,
                )
                if written.get("returncode") != 0:
                    continue
                removed = env.execute(f"rm -f {quoted_path}", cwd="/", timeout=5)
                if (
                    removed.get("returncode") == 0
                    and pending.get(seq, (None,))[0] == digest
                ):
                    pending.pop(seq)
                    settled.add(seq)
        except Exception:
            if not stop_event.is_set():
                logger.debug("Remote execution RPC failed", exc_info=True)
        stop_event.wait(0.1)
