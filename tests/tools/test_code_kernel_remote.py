"""Real POSIX shell transport exercises persistent remote protocol and RPC."""

import json
import os
import subprocess
import threading
from pathlib import Path

import pytest

from tools.code_kernel_remote import RemoteKernel

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Remote shell contract")


class ShellEnvironment:
    def __init__(self, directory):
        self.cwd = str(directory)
        self.temp_dir = str(directory)
        self.failed = False
        self.commands = []

    def execute(self, command, cwd="/", timeout=10, **kwargs):
        self.commands.append(command)
        if self.failed:
            raise OSError("simulated disconnected transport")
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {"output": result.stdout, "returncode": result.returncode}


@pytest.fixture
def kernel(tmp_path):
    remote = tmp_path / "remote"
    remote.mkdir()
    env = ShellEnvironment(remote)
    instance = RemoteKernel(
        tmp_path / "profile", frozenset({"read_file"}), "proposal_only", "strict", env
    )
    try:
        instance.start()
        yield instance, env
    finally:
        env.failed = False
        instance.close()


def test_remote_state_retained_and_fresh_rpc_budgets(kernel, monkeypatch):
    from tools import code_execution_rpc

    instance, _ = kernel
    calls = []

    def dispatch(name, args):
        calls.append(args["path"])
        return json.dumps({"path": args["path"]})

    monkeypatch.setattr(code_execution_rpc, "_dispatcher", lambda *args: dispatch)
    first = instance.run(
        'from forecast_tools import read_file\nvalue = 6\nprint(read_file(path="first"))',
        "one",
        10,
        1,
    )
    second = instance.run(
        'print(value * 2)\nprint(read_file(path="second"))\nprint(read_file(path="denied"))',
        "two",
        10,
        1,
    )
    assert "first" in first["stdout"]
    assert "12" in second["stdout"] and "second" in second["stdout"]
    assert "limit reached" in second["stdout"]
    assert calls == ["first", "second"]
    assert first["kernel_id"] == second["kernel_id"]
    assert Path(second["calculation_record"]).exists()


def test_disconnected_cleanup_retains_directory_until_confirmed(kernel):
    instance, env = kernel
    instance.run("value = 1", "one", 10, 0)
    remote = Path(instance.remote_directory)
    env.failed = True
    with pytest.raises(OSError, match="disconnected"):
        instance.close()
    assert instance.remote_created and remote.exists()
    env.failed = False
    instance.close()
    assert not remote.exists() and not instance.remote_created
    instance.close()


def test_owner_maintenance_and_cleanup_survive_retired_call_scope(kernel, monkeypatch):
    from superforecasting_agent.tooling.interrupts import cancellation_scope, is_interrupted

    instance, env = kernel
    cancellation = threading.Event()
    cancellation.set()
    execute = env.execute

    def checked(*args, **kwargs):
        assert not is_interrupted(), "caller cancellation leaked into owner cleanup"
        return execute(*args, **kwargs)

    monkeypatch.setattr(env, "execute", checked)
    with cancellation_scope(cancellation):
        instance.close()
        assert is_interrupted(), "cleanup must restore the caller's cancellation"
    assert not instance.remote_created


def test_heartbeat_has_its_own_cancellation_authority(kernel, monkeypatch):
    from superforecasting_agent.tooling.interrupts import cancellation_scope, is_interrupted

    instance, _ = kernel
    instance.heartbeat_stop.set()
    instance.heartbeat.join(timeout=12)
    assert not instance.heartbeat.is_alive()
    instance.heartbeat_stop.clear()
    cancellation = threading.Event()
    cancellation.set()
    seen = []

    def heartbeat(*args):
        seen.append(is_interrupted())
        instance.heartbeat_stop.set()

    with monkeypatch.context() as scoped:
        scoped.setattr(instance, "_control", heartbeat)
        with cancellation_scope(cancellation):
            instance._renew()
            assert is_interrupted()
    assert seen == [False]


def test_remote_tokens_never_appear_in_control_command_arguments(kernel):
    instance, env = kernel
    instance.run("value = 2", "one", 10, 0)
    tokens = [
        path.read_text() for path in Path(instance.remote_directory).rglob(".token")
    ]
    assert tokens
    assert all(token not in command for token in tokens for command in env.commands)


def test_remote_timeout_stops_owned_process_before_removing_directory(kernel):
    instance, _ = kernel
    with pytest.raises((TimeoutError, RuntimeError), match="deadline"):
        instance.run("while True: pass", "timeout", 0.3, 0)
    assert instance.cancelled.is_set()
    assert not Path(instance.remote_directory).exists()
    with pytest.raises(RuntimeError, match="retired"):
        instance.run('print("must not restart")', "late", 10, 0)


def test_public_remote_dispatch_pins_exact_environment_until_close(
    tmp_path, monkeypatch
):
    from tools import code_execution_tool as execution, terminal_tool as terminal
    from tools.code_kernel import KernelOwner
    from tools.environments.leases import is_retained

    env = ShellEnvironment(tmp_path)
    cleaned = []
    env.cleanup = lambda: cleaned.append(env)
    monkeypatch.setattr(terminal, "_active_environments", {"default": env})
    monkeypatch.setattr(terminal, "_last_activity", {"default": 0})
    monkeypatch.setattr(terminal, "_resolve_container_task_id", lambda _: "default")
    monkeypatch.setattr(terminal, "_get_env_config", lambda: {"env_type": "ssh"})
    monkeypatch.setattr(execution, "_get_or_create_env", lambda _: (env, False))
    monkeypatch.setattr(
        execution,
        "_load_config",
        lambda: {
            "kernel_mode": "session",
            "timeout": 10,
            "max_tool_calls": 0,
        },
    )
    monkeypatch.setattr(execution, "_get_execution_mode", lambda: "strict")
    owner = KernelOwner(tmp_path / "profile")
    try:
        first = json.loads(
            execution.execute_code(
                "value = 13", task_id="turn-one", enabled_tools=[], kernel_owner=owner
            )
        )
        assert "error" not in first or not first["error"], first
        assert is_retained(env) and terminal.is_persistent_env("default")
        terminal._cleanup_inactive_envs(1)
        assert terminal._active_environments["default"] is env
        with pytest.raises(RuntimeError, match="retained"):
            terminal.cleanup_vm("default")
        second = json.loads(
            execution.execute_code(
                "print(value)", task_id="turn-two", enabled_tools=[], kernel_owner=owner
            )
        )
        assert second["stdout"] == "13\n"
        assert first["kernel_id"] == second["kernel_id"]
        replacement = ShellEnvironment(tmp_path)
        terminal._active_environments["default"] = replacement
        refused = json.loads(
            execution.execute_code(
                "print('unsafe')",
                task_id="turn-three",
                enabled_tools=[],
                kernel_owner=owner,
            )
        )
        assert "environment changed" in str(refused)
        owner.close()
        assert terminal._active_environments["default"] is replacement
        assert not is_retained(env) and not cleaned
        terminal._active_environments["default"] = env
        terminal.cleanup_vm("default")
        assert cleaned == [env]
    finally:
        owner.close()


def test_environment_leases_release_only_their_exact_owner(tmp_path):
    from tools.environments.leases import EnvironmentLease, is_retained

    original = ShellEnvironment(tmp_path)
    replacement = ShellEnvironment(tmp_path)
    first, second = EnvironmentLease(original), EnvironmentLease(original)
    other = EnvironmentLease(replacement)
    try:
        first.release()
        first.release()
        assert is_retained(original) and is_retained(replacement)
        second.release()
        assert not is_retained(original) and is_retained(replacement)
    finally:
        first.release()
        second.release()
        other.release()
