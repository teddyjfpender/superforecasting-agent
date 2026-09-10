"""Build-update checks belong to an active transport, not module import."""

import subprocess
import sys
from unittest.mock import patch


def test_importing_server_does_not_start_update_check():
    result = subprocess.run(
        [sys.executable, "-c", """
from unittest.mock import patch
with patch('superforecasting_agent.runtime.banner.prefetch_update_check') as check:
    import tui_gateway.server
    check.assert_not_called()
"""],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_start_schedules_check_and_tolerates_failure():
    from tui_gateway import server

    with patch("superforecasting_agent.runtime.banner.prefetch_update_check") as check:
        server.start_build_check()
        check.assert_called_once_with()
    with patch("superforecasting_agent.runtime.banner.prefetch_update_check", side_effect=RuntimeError("offline")):
        server.start_build_check()
