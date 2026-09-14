"""Real socket/file clients enforce authority and do not retry tool effects."""

import json
import socket
import stat
import subprocess
import threading
from contextlib import contextmanager

import pytest

from superforecasting_agent.tooling.call_context import CallContext
from tools import code_execution_rpc as rpc


@contextmanager
def server(monkeypatch, dispatch, budget=2):
    monkeypatch.setattr("superforecasting_agent.tooling.runtime.handle_function_call", dispatch)
    context = CallContext()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        thread = threading.Thread(target=context.run, args=(rpc._rpc_server_loop, listener, "owner", [], [0], budget, frozenset({"terminal"}), "proposal_only", "secret", context.cancelled))
        thread.start()
        try:
            with socket.create_connection(listener.getsockname(), timeout=2) as client:
                yield client, context, listener
        finally:
            context.retire()
            thread.join(timeout=2)
            assert not thread.is_alive()
            assert listener.fileno() >= 0  # The RPC worker does not own this handle.


def send(client, request):
    client.sendall(json.dumps(request).encode() + b"\n")
    response = b""
    while not response.endswith(b"\n"):
        chunk = client.recv(65536)
        assert chunk
        response += chunk
    return json.loads(response)


@pytest.mark.parametrize("payload", [None, [], True, {}, {"token": "wrong", "tool": "terminal", "args": {}}, {"token": "\ud800", "tool": "terminal", "args": {}}, {"token": "secret", "tool": "terminal", "args": []}, {"token": "secret", "tool": "terminal", "args": {}, "seq": True}])
def test_malformed_and_unauthenticated_frames_never_dispatch(monkeypatch, payload):
    with server(monkeypatch, lambda *a, **kw: pytest.fail("unauthorized effect")) as (client, *_):
        assert "error" in send(client, payload)


def test_budget_and_forecast_policy_cross_the_real_socket(monkeypatch):
    calls = []

    def dispatch(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return json.dumps({"ok": True})

    with server(monkeypatch, dispatch, budget=1) as (client, *_):
        request = {"token": "secret", "tool": "terminal", "args": {"command": "harmless", "background": True}}
        assert send(client, request)["ok"]
        assert "limit" in send(client, request)["error"]
    assert calls == [("terminal", {"command": "harmless"}, {"task_id": "owner", "main_runtime": {"forecast_commit_policy": "proposal_only"}})]


def test_oversized_unterminated_frame_is_bounded(monkeypatch):
    monkeypatch.setattr(rpc, "MAX_REQUEST_BYTES", 128)
    with server(monkeypatch, lambda *a, **kw: pytest.fail("oversized effect")) as (client, *_):
        client.sendall(b"x" * 129)
        assert "frame limit" in json.loads(client.recv(65536))["error"]
        assert client.recv(1) == b""


def test_remote_delivery_retry_reuses_result_without_repeating_effect(monkeypatch):
    stop = threading.Event()
    calls = []
    monkeypatch.setattr(rpc, "_dispatcher", lambda *_: lambda name, args: calls.append(name) or '{"ok": true}')
    request = json.dumps({"token": "secret", "tool": "terminal", "args": {}, "seq": 1})

    class Env:
        writes = 0

        def execute(self, command, **kwargs):
            if command.startswith("ls "):
                return {"output": "/rpc/req_000001\n", "returncode": 0}
            if command.startswith("head "):
                return {"output": request, "returncode": 0}
            if command.startswith("echo "):
                self.writes += 1
                if self.writes == 1:
                    raise OSError("response transport dropped after effect")
            if command.startswith("rm "):
                stop.set()
            return {"output": "", "returncode": 0}

    env = Env()
    rpc._rpc_poll_loop(env, "/rpc", "owner", [], [0], 2, frozenset({"terminal"}), None, stop, "secret")
    assert calls == ["terminal"]
    assert env.writes == 2


class ShellEnv:
    def __init__(self, directory):
        self.directory = directory
        self.commands = []

    def get_temp_dir(self):
        return str(self.directory)

    def execute(self, command, cwd=None, timeout=10):
        self.commands.append(command)
        result = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return {"output": result.stdout, "returncode": result.returncode}


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Remote POSIX shell contract")
def test_remote_token_is_private_and_never_in_command_arguments(tmp_path):
    env = ShellEnv(tmp_path)
    token = rpc.prepare_remote_rpc(env, str(tmp_path))
    assert (tmp_path / ".token").read_text() == token
    assert stat.S_IMODE((tmp_path / ".token").stat().st_mode) == 0o600
    assert all(token not in command for command in env.commands)
    with pytest.raises(RuntimeError, match="authentication"):
        rpc.prepare_remote_rpc(env, str(tmp_path))


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Remote POSIX shell contract")
def test_real_remote_file_rpc_carries_policy_and_rejects_empty_selection(tmp_path, monkeypatch):
    from tools.code_execution_tool import _execute_remote

    env = ShellEnv(tmp_path)
    monkeypatch.setattr("tools.code_execution_tool._get_or_create_env", lambda _: (env, "ssh"))
    calls = []

    def dispatch(name, args, **kwargs):
        calls.append(kwargs)
        return '{"output": "remote-ok"}'

    monkeypatch.setattr("superforecasting_agent.tooling.runtime.handle_function_call", dispatch)
    result = json.loads(_execute_remote('from forecast_tools import terminal\nprint(terminal("harmless"))', "owner", ["terminal"], "proposal_only"))
    assert result["status"] == "success" and "remote-ok" in result["output"]
    assert calls == [{"task_id": "owner", "main_runtime": {"forecast_commit_policy": "proposal_only"}}]
    calls.clear()
    denied = json.loads(_execute_remote('import forecast_tools\nprint(forecast_tools._call("terminal", {}))', "owner", [], "proposal_only"))
    assert "not available" in denied["output"]
    assert not calls


def test_nonfinite_rpc_arguments_never_reach_tools(monkeypatch):
    with server(monkeypatch, lambda *a, **kw: pytest.fail("nonfinite effect")) as (client, *_):
        response = send(client, {"token": "secret", "tool": "terminal", "args": {"timeout": float("nan")}})
        assert "finite JSON" in response["error"]
