"""Persistent host behavior through real child interpreters and RPC sockets."""

import contextvars
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from tools.code_kernel import KernelOwner


@pytest.fixture
def owner(tmp_path, monkeypatch):
    import tools.code_execution_tool as execution

    monkeypatch.setattr(execution, "_resolve_child_python", lambda mode: sys.executable)
    instance = KernelOwner(tmp_path)
    try:
        yield instance
    finally:
        instance.close()


def run(owner, code, *, tools=frozenset(), timeout=3, reset=False, budget=2):
    return owner.run(
        code, "task-1", tools, "proposal_only", "strict", timeout, budget, reset
    )


def test_persistent_state_receipts_errors_and_explicit_reset(owner):
    first = run(owner, "samples = [2, 4, 6]\nprint(sum(samples))")
    assert first["stdout"] == "12\n"
    second = run(owner, 'samples.append(8)\nraise ValueError("bad observation")')
    assert second["error"] and second["state_preserved"]
    third = run(owner, "print(sum(samples))")
    assert third["stdout"] == "20\n"
    records = [
        json.loads(Path(result["calculation_record"]).read_text())
        for result in (first, second, third)
    ]
    assert [record["status"] for record in records] == [
        "completed",
        "failed",
        "completed",
    ]
    assert records[2]["previous_result_sha256"] == records[1]["result_sha256"]
    fresh = run(owner, "print('samples' in globals())", reset=True)
    assert fresh["kernel_id"] != first["kernel_id"]
    assert fresh["stdout"] == "False\n"
    assert Path(first["calculation_record"]).exists()


def test_startup_descendants_are_retained_but_cell_descendants_retire(owner, monkeypatch):
    """A venv launcher child is runtime state, but later children remain unsafe."""
    from unittest.mock import Mock

    from tools.code_kernel import LocalKernel

    startup = Mock()
    startup.is_running.return_value = True
    startup.kill.side_effect = lambda: setattr(startup.is_running, 'return_value', False)
    spawned = Mock()
    spawned.is_running.return_value = True
    spawned.kill.side_effect = lambda: setattr(spawned.is_running, 'return_value', False)
    capture = LocalKernel._capture_children
    def with_launcher(kernel):
        capture(kernel)
        if startup.is_running():
            kernel.children[(123, 1.0)] = startup
    monkeypatch.setattr(LocalKernel, '_capture_children', with_launcher)
    first = run(owner, 'value = 7')
    assert first['state_preserved']
    assert run(owner, 'print(value)')['stdout'] == '7\n'
    # A reused PID has a different creation identity and is not exempted.
    owner.kernel.children[(123, 2.0)] = spawned
    leaked = run(owner, 'print(value)')
    assert leaked['retirement_reason'] == 'cell_left_running_processes'
    assert not leaked['state_preserved']
    owner.close()
    startup.kill.assert_called_once()
    spawned.kill.assert_called_once()


@pytest.mark.parametrize("failure", ["cancel", "deadline"])
def test_interrupted_admission_never_sends_code_to_interpreter(owner, monkeypatch, failure):
    from superforecasting_agent.tooling.interrupts import cancellation_scope

    run(owner, "value = 1")
    kernel = owner.kernel
    original = kernel._start_rpc
    cancellation = threading.Event()

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        if failure == "cancel":
            cancellation.set()
        else:
            time.sleep(0.1)
        return result

    monkeypatch.setattr(kernel, "_start_rpc", delayed)
    monkeypatch.setattr(kernel, "_send_cell", lambda *_: pytest.fail("expired cell executed"))
    with cancellation_scope(cancellation):
        with pytest.raises((InterruptedError, TimeoutError), match="before dispatch"):
            run(owner, "value = 2", timeout=0.05 if failure == "deadline" else 3)


def test_fresh_call_context_and_budget_for_retained_imports(owner, monkeypatch):
    import tools.code_execution_rpc as rpc

    caller = contextvars.ContextVar("kernel-test-caller", default="missing")
    seen = []

    def dispatcher(task_id, policy):
        def dispatch(name, args):
            seen.append((caller.get(), task_id, policy, name, args))
            return json.dumps({"caller": caller.get()})

        return dispatch

    monkeypatch.setattr(rpc, "_dispatcher", dispatcher)
    caller.set("first")
    first = run(
        owner,
        'from forecast_tools import read_file\nprint(read_file(path="a"))',
        tools=frozenset({"read_file"}),
        budget=1,
    )
    caller.set("second")
    second = run(
        owner,
        'print(read_file(path="b"))\nprint(read_file(path="c"))',
        tools=frozenset({"read_file"}),
        budget=1,
    )
    assert "first" in first["stdout"] and "second" in second["stdout"]
    assert "limit reached" in second["stdout"]
    assert [entry[0] for entry in seen] == ["first", "second"]
    assert all(entry[2] == "proposal_only" for entry in seen)


def test_timeout_retires_exact_process_and_requires_explicit_reset(owner):
    first = run(owner, "x = 1")
    process = owner.kernel.process
    with pytest.raises(TimeoutError):
        run(owner, "while True: pass", timeout=0.15)
    assert process.poll() is not None
    with pytest.raises(RuntimeError, match="retired"):
        run(owner, "print(x)")
    restarted = run(owner, "print('x' in globals())", reset=True)
    assert restarted["kernel_id"] != first["kernel_id"]
    assert restarted["stdout"] == "False\n"
    statuses = [
        json.loads(path.read_text())["status"]
        for path in Path(first["calculation_record"]).parent.glob("*.json")
    ]
    assert "interrupted" in statuses


def test_changed_permissions_cannot_reuse_wider_kernel(owner):
    run(owner, "x = 1", tools=frozenset({"read_file"}))
    with pytest.raises(RuntimeError, match="configuration changed"):
        run(owner, "print(x)", tools=frozenset())
    result = run(
        owner,
        'import forecast_tools\nprint(hasattr(forecast_tools, "read_file"))',
        reset=True,
    )
    assert result["stdout"] == "False\n"


def test_old_owner_cleanup_cannot_close_replacement(owner):
    run(owner, "x = 1")
    replacement = KernelOwner(owner.home)
    try:
        run(replacement, "x = 2")
        owner.close()
        owner.close()
        assert run(replacement, "print(x)")["stdout"] == "2\n"
        with pytest.raises(RuntimeError, match="closed"):
            run(owner, "pass")
    finally:
        replacement.close()


def test_receipt_write_failure_prevents_cell_execution(owner, monkeypatch, tmp_path):
    import tools.code_kernel as kernel_module

    marker = tmp_path / "must-not-exist"

    def fail(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(kernel_module, "atomic_json_write", fail)
    with pytest.raises(OSError, match="disk unavailable"):
        run(owner, f"from pathlib import Path\nPath({str(marker)!r}).touch()")
    assert not marker.exists()


def test_public_dispatch_retains_cells_and_honors_empty_selection(owner, monkeypatch):
    from superforecasting_agent.tooling.dispatch import handle_function_call
    import tools.code_execution_tool as execution
    import tools.terminal_tool as terminal

    monkeypatch.setattr(
        execution,
        "_load_config",
        lambda: {"kernel_mode": "session", "mode": "strict", "timeout": 3},
    )
    monkeypatch.setattr(terminal, "_get_env_config", lambda: {"env_type": "local"})

    def invoke(code, **args):
        return json.loads(
            handle_function_call(
                "execute_code",
                {"code": code, **args},
                task_id="public-task",
                enabled_tools=[],
                kernel_owner=owner,
                main_runtime={"forecast_commit_policy": "proposal_only"},
            )
        )

    first = invoke(
        'value = 7\nimport forecast_tools\nprint(hasattr(forecast_tools, "terminal"))'
    )
    assert first["stdout"] == "False\n"
    assert invoke("print(value * 3)")["stdout"] == "21\n"
    assert invoke("print('value' in globals())", reset=True)["stdout"] == "False\n"


def test_owner_attachment_separates_profile_and_rejects_closed_agent(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from tools.code_kernel import owner_for
    import superforecasting_agent.constants as constants

    home = tmp_path / "first"
    monkeypatch.setattr(constants, "get_agent_home", lambda: home)
    agent = SimpleNamespace(session_id="same-id", _resources_closed=False)
    first = owner_for(agent)
    assert owner_for(agent) is first
    home = tmp_path / "second"
    second = owner_for(agent)
    assert first.closed and second is not first
    agent._resources_closed = True
    with pytest.raises(RuntimeError, match="closed"):
        owner_for(agent)
    second.close()


def test_interrupted_rpc_retains_cleanup_owner_until_dispatch_exits(owner, monkeypatch):
    import tools.code_execution_rpc as rpc
    from superforecasting_agent.tooling.interrupts import cancellation_scope

    entered, release = threading.Event(), threading.Event()
    cancellation = threading.Event()

    def dispatcher(task_id, policy):
        def dispatch(name, args):
            entered.set()
            # Interrupt only after actual RPC entry; cold interpreter startup is
            # not the cleanup-ownership behavior under test.
            cancellation.set()
            release.wait(10)
            return "{}"

        return dispatch

    monkeypatch.setattr(rpc, "_dispatcher", dispatcher)
    try:
        with cancellation_scope(cancellation), pytest.raises(RuntimeError, match="cleanup is pending"):
            run(
                owner,
                'from forecast_tools import read_file\nread_file(path="a")',
                tools=frozenset({"read_file"}),
                timeout=10,
            )
        assert entered.is_set()
        retained = owner.kernel
        assert retained.rpc_workers
        with pytest.raises(RuntimeError, match="cleanup is pending"):
            run(owner, "pass", reset=True)
        assert owner.kernel is retained
    finally:
        release.set()
    owner.close()
    assert not retained.rpc_workers


def test_agent_dispatch_attaches_owner_and_actual_close_disposes_it(
    monkeypatch, tmp_path
):
    from types import SimpleNamespace
    from agent.agent_runtime_helpers import invoke_tool
    from agent import session_lifecycle
    import superforecasting_agent.constants as constants
    import tools.code_execution_tool as execution
    import tools.terminal_tool as terminal

    monkeypatch.setattr(constants, "get_agent_home", lambda: tmp_path)
    monkeypatch.setattr(
        execution,
        "_load_config",
        lambda: {"kernel_mode": "session", "mode": "strict", "timeout": 3},
    )
    monkeypatch.setattr(terminal, "_get_env_config", lambda: {"env_type": "local"})
    agent = SimpleNamespace(
        session_id="agent-session",
        _memory_manager=None,
        valid_tool_names={"execute_code"},
        _current_main_runtime=lambda: {"forecast_commit_policy": "proposal_only"},
    )
    # Other resource owners are independent; exercise real kernel shutdown through
    # the agent close facade while avoiding unrelated provider/browser setup.
    monkeypatch.setattr(session_lifecycle, "_close_resources", lambda agent: None)
    monkeypatch.setattr(
        session_lifecycle, "_require_children_disposed", lambda agent: None
    )
    monkeypatch.setattr(
        session_lifecycle, "_close_children", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        session_lifecycle, "require_client_cleanup_complete", lambda agent: None
    )
    try:
        first = json.loads(
            invoke_tool(agent, "execute_code", {"code": "x = 17"}, "turn-1")
        )
        second = json.loads(
            invoke_tool(agent, "execute_code", {"code": "print(x)"}, "turn-2")
        )
        assert first["kernel_id"] == second["kernel_id"]
        assert second["stdout"] == "17\n"
        process = agent._code_kernel_owner.kernel.process
    finally:
        session_lifecycle.close(agent)
    assert process.poll() is not None
    session_lifecycle.close(agent)


def test_cell_must_join_background_processes_before_next_authority(owner):
    import psutil

    result = run(
        owner,
        'import subprocess, sys\nchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])\nprint(child.pid)',
    )
    assert not result["state_preserved"]
    assert result["retirement_reason"] == "cell_left_running_processes"
    try:
        status = psutil.Process(int(result["stdout"].strip())).status()
    except psutil.NoSuchProcess:
        pass
    else:
        assert status in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}


def test_changed_working_directory_requires_explicit_reset(
    owner, monkeypatch, tmp_path
):
    import tools.code_execution_tool as execution

    directory = tmp_path / "one"
    directory.mkdir()
    monkeypatch.setattr(
        execution, "_resolve_child_cwd", lambda mode, staging: str(directory)
    )
    run(owner, "x = 1")
    directory = tmp_path / "two"
    directory.mkdir()
    with pytest.raises(RuntimeError, match="working directory changed"):
        run(owner, "print(x)")
    assert run(owner, "print('x' in globals())", reset=True)["stdout"] == "False\n"


def test_descendants_are_signalled_before_interpreter_input_closes(owner, monkeypatch):
    import subprocess
    import psutil

    run(owner, 'value = 1')
    kernel = owner.kernel
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    captured = psutil.Process(child.pid)
    kernel.children[(child.pid, captured.create_time())] = captured
    original = captured.kill
    observed = []

    def kill_owned():
        assert kernel.process.poll() is None
        assert not kernel.process.stdin.closed
        observed.append(child.pid)
        original()

    monkeypatch.setattr(captured, 'kill', kill_owned)
    try:
        owner.close()
        child.wait(timeout=3)
        assert observed == [child.pid]
        owner.close()
        assert observed == [child.pid]
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)


def test_confirmed_dead_descendant_is_not_signalled_again(owner):
    import psutil
    from unittest.mock import Mock

    run(owner, 'value = 1')
    dead = Mock()
    dead.is_running.return_value = True
    dead.status.return_value = psutil.STATUS_ZOMBIE
    owner.kernel.children[(123, 1.0)] = dead
    owner.close()
    dead.kill.assert_not_called()


@pytest.mark.parametrize("interpreter", ["sys.executable", "getattr(sys, '_base_executable', sys.executable)"])
def test_nested_background_processes_are_stopped_before_their_parents(owner, tmp_path, interpreter):
    import psutil

    trace_path = tmp_path / "nested-process-trace.txt"
    child_trace_path = tmp_path / "nested-child-trace.txt"
    nested = (
        'import subprocess,sys,time,faulthandler; '
        f'trace=open({str(child_trace_path)!r},"w"); '
        'trace.write("started stdout="+repr(sys.stdout)+"\\n"); trace.flush(); '
        'faulthandler.dump_traceback_later(3,file=trace); '
        'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
        'trace.write("spawned grandchild\\n"); trace.flush(); '
        'print(child.pid,flush=True); '
        'trace.write("printed PID\\n"); trace.flush(); time.sleep(30)'
    )
    # This exercises descendant ownership, not execution-budget enforcement.
    # Two nested interpreter/venv launches can exceed the ordinary 3s cell
    # fixture budget on Windows. Keep a bounded budget, below the 30s sleepers.
    code = (
        'import subprocess,sys,faulthandler\n'
        f'_trace=open({str(trace_path)!r},"w")\n'
        'faulthandler.dump_traceback_later(3,file=_trace)\n'
        'try:\n'
        f'    child=subprocess.Popen([{interpreter},"-c",{nested!r}],stdout=subprocess.PIPE,text=True)\n'
        '    print(child.pid, child.stdout.readline().strip())\n'
        'finally:\n'
        '    faulthandler.cancel_dump_traceback_later()\n'
        '    _trace.close()\n'
    )
    try:
        result = run(owner, code, timeout=10)
    except TimeoutError:
        # The owned kernel has been retired before inspecting synthetic-test
        # diagnostics. Preserve the actual wait location in native CI output.
        trace = trace_path.read_text() if trace_path.exists() else 'trace not created'
        diagnostics = bytes(owner.kernel.diagnostics).decode('utf-8', errors='replace')
        child_trace = child_trace_path.read_text() if child_trace_path.exists() else 'child did not start'
        pytest.fail(f'Nested process deadline exceeded\n{trace}\nChild:\n{child_trace}\nNative stderr:\n{diagnostics}')
    assert result['retirement_reason'] == 'cell_left_running_processes'
    assert not result['state_preserved']
    for pid in map(int, result['stdout'].split()):
        try:
            assert psutil.Process(pid).status() in {psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD}
        except psutil.NoSuchProcess:
            pass
