"""Windows qualification contains console mutations and preserves failures."""

import json
import subprocess

import pytest

from scripts import verify_profiles


@pytest.mark.parametrize("returncode", [0, 7])
def test_windows_terminal_probe_isolated_with_visible_diagnostics(
    tmp_path, monkeypatch, capsys, returncode
):
    monkeypatch.setattr(verify_profiles.platform, "system", lambda: "Windows")

    def run(argv, **kwargs):
        assert argv[-1] == "--terminal-worker"
        assert kwargs["capture_output"] is True
        assert kwargs["timeout"] == 180
        request = json.loads(kwargs["input"])
        assert request["question"] == "question-123"
        assert request["env"] == {"PROFILE": str(tmp_path)}
        assert request["gateway_url"] == "ws://localhost:1234"
        return subprocess.CompletedProcess(
            argv, returncode, "terminal output\n", "diagnostic\n"
        )

    monkeypatch.setattr(verify_profiles.subprocess, "run", run)
    args = (
        tmp_path / "terminal",
        tmp_path / "backend",
        tmp_path,
        {"PROFILE": str(tmp_path)},
        "question-123",
    )
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as error:
            verify_profiles.verify_installed_terminal(
                *args, gateway_url="ws://localhost:1234"
            )
        assert error.value.returncode == returncode
    else:
        verify_profiles.verify_installed_terminal(
            *args, gateway_url="ws://localhost:1234"
        )
    captured = capsys.readouterr()
    assert captured.out == "terminal output\n"
    assert captured.err == "diagnostic\n"


@pytest.mark.parametrize("returncode", [0, 3])
def test_host_shutdown_requires_completed_lifespan_even_for_expected_exit(returncode):
    from scripts.verify_headless_host import verify_shutdown

    with pytest.raises(AssertionError):
        verify_shutdown(returncode, "Waiting for application shutdown.", signal_exit=3)
    verify_shutdown(returncode, "Application shutdown complete.", signal_exit=3)


def test_completed_lifespan_does_not_allow_unrelated_exit_failure():
    from scripts.verify_headless_host import verify_shutdown

    with pytest.raises(AssertionError, match="Host exit 1"):
        verify_shutdown(1, "Application shutdown complete.", signal_exit=3)
