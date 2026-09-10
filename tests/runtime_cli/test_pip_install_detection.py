from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def test_pip_install_detected_when_no_git_dir(tmp_path):
    """When PROJECT_ROOT has no .git, detect as pip install."""
    with patch("superforecasting_agent.runtime.config.get_managed_system", return_value=None), \
         patch("superforecasting_agent.runtime.config.get_agent_home", return_value=tmp_path):
        from superforecasting_agent.runtime.config import detect_install_method
        method = detect_install_method(project_root=tmp_path)
        assert method == "pip"


def test_git_install_detected_when_git_dir_exists(tmp_path):
    """When PROJECT_ROOT has .git, detect as git install."""
    (tmp_path / ".git").mkdir()
    with patch("superforecasting_agent.runtime.config.get_managed_system", return_value=None), \
         patch("superforecasting_agent.runtime.config.get_agent_home", return_value=tmp_path):
        from superforecasting_agent.runtime.config import detect_install_method
        method = detect_install_method(project_root=tmp_path)
        assert method == "git"


def test_managed_install_takes_precedence(tmp_path):
    """Managed-install env/state takes precedence over git detection."""
    (tmp_path / ".git").mkdir()
    with patch("superforecasting_agent.runtime.config.get_managed_system", return_value="NixOS"), \
         patch("superforecasting_agent.runtime.config.get_agent_home", return_value=tmp_path):
        from superforecasting_agent.runtime.config import detect_install_method
        method = detect_install_method(project_root=tmp_path)
        assert method == "nixos"


def test_recommended_update_command_pip():
    """Old unstamped wheels are upgraded from the formal GitHub release lane."""
    from superforecasting_agent.runtime.config import recommended_update_command_for_method
    with patch("superforecasting_agent.runtime.config._IS_WINDOWS", False):
        cmd = recommended_update_command_for_method("pip")
    assert "github.com/teddyjfpender/superforecasting-agent/releases/latest" in cmd
    assert "install.sh | bash" in cmd
    assert "hermes-agent" not in cmd


def test_release_stamp_uses_formal_github_installer():
    from superforecasting_agent.runtime.config import recommended_update_command_for_method

    assert recommended_update_command_for_method("release") == recommended_update_command_for_method("pip")


def test_recommended_update_command_windows_uses_powershell_installer():
    from superforecasting_agent.runtime.config import recommended_update_command_for_method

    with patch("superforecasting_agent.runtime.config._IS_WINDOWS", True):
        cmd = recommended_update_command_for_method("release")
    assert "install.ps1" in cmd
    assert "| iex" in cmd


def test_stamp_file_takes_precedence(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".install_method").write_text("docker\n")
    with patch("superforecasting_agent.runtime.config.get_managed_system", return_value=None), \
         patch("superforecasting_agent.runtime.config.get_agent_home", return_value=tmp_path):
        from superforecasting_agent.runtime.config import detect_install_method
        assert detect_install_method(project_root=tmp_path) == "docker"


def test_docker_detected_via_dockerenv(tmp_path):
    with patch("superforecasting_agent.runtime.config.get_managed_system", return_value=None), \
         patch("superforecasting_agent.runtime.config.get_agent_home", return_value=tmp_path), \
         patch("superforecasting_agent.constants.is_container", return_value=True):
        from superforecasting_agent.runtime.config import detect_install_method
        assert detect_install_method(project_root=tmp_path) == "docker"


def test_recommended_update_command_docker():
    from superforecasting_agent.runtime.config import recommended_update_command_for_method
    assert "docker pull" in recommended_update_command_for_method("docker")


def test_release_update_downloads_and_runs_official_installer(monkeypatch):
    import superforecasting_agent.runtime.main as main

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"#!/usr/bin/env bash\nexit 0\n"

    run = MagicMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(main, "_is_windows", lambda: False)
    monkeypatch.setattr(main.shutil, "which", lambda name: "/bin/bash" if name == "bash" else None)
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response())
    monkeypatch.setattr(main.subprocess, "run", run)

    main._cmd_update_release(SimpleNamespace())

    assert run.call_args.args[0][0] == "/bin/bash"
    assert run.call_args.args[0][1].endswith("install.sh")


def test_release_update_uses_native_powershell_installer_on_windows(monkeypatch):
    import superforecasting_agent.runtime.main as main

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"param()\n"

    run = MagicMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(main, "_is_windows", lambda: True)
    monkeypatch.setattr(
        main.shutil,
        "which",
        lambda name: "C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        if name == "powershell"
        else None,
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response())
    monkeypatch.setattr(main.subprocess, "run", run)

    main._cmd_update_release(SimpleNamespace())

    command = run.call_args.args[0]
    assert command[0].endswith("powershell.exe")
    assert command[-2] == "-File"
    assert command[-1].endswith("install.ps1")


def test_release_update_check_uses_github_releases(monkeypatch, capsys):
    import superforecasting_agent.runtime.main as main

    monkeypatch.setattr("superforecasting_agent.runtime.config.detect_install_method", lambda *_args: "release")
    check = MagicMock(return_value=0)
    monkeypatch.setattr("superforecasting_agent.runtime.banner.check_via_release", check)

    main._cmd_update_check()

    assert "Already up to date" in capsys.readouterr().out
    check.assert_called_once_with()
