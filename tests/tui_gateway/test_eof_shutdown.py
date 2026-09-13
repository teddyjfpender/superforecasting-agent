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
