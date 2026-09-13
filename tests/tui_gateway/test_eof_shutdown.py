"""EOF cleanup must not depend on atexit reaching a wedged executor."""
import os
from pathlib import Path
import subprocess
import sys


def test_shutdown_deadline_reaps_process_with_blocked_worker(tmp_path):
    env = dict(os.environ)
    env["HERMES_HOME"] = str(tmp_path)
    env["SUPERFORECASTING_AGENT_TUI_GATEWAY_SHUTDOWN_GRACE_S"] = "0.1"
    result = subprocess.run(
        [sys.executable, "-c", """
import threading
from tui_gateway.entry import _arm_shutdown_deadline
threading.Thread(target=threading.Event().wait, daemon=False).start()
_arm_shutdown_deadline()
print('shutdown armed', flush=True)
"""],
        cwd=Path(__file__).resolve().parents[2],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "shutdown armed" in result.stdout  # importing a host does not reserve stdout


def test_dispatch_exit_bounds_cleanup_with_blocked_workers(tmp_path):
    env = dict(os.environ)
    env["SUPERFORECASTING_AGENT_HOME"] = str(tmp_path)
    env["SUPERFORECASTING_AGENT_TUI_GATEWAY_SHUTDOWN_GRACE_S"] = "0.1"
    result = subprocess.run(
        [sys.executable, "-c", """
import sys, threading
from tui_gateway import entry
entry.server.start_runtime = lambda: None
entry.server.shutdown_runtime = lambda timeout: threading.Event().wait()
entry._run_stdio = lambda: sys.exit(0)
print('dispatch will exit without EOF', flush=True)
entry.main()
"""], cwd=Path(__file__).resolve().parents[2], env=env,
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "dispatch will exit without EOF" in result.stdout
