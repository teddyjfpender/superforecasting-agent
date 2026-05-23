from types import SimpleNamespace


def test_uninstall_banner_is_forecast_native(monkeypatch, tmp_path, capsys):
    import hermes_cli.uninstall as uninstall

    home = tmp_path / "home"
    home.mkdir()
    install = tmp_path / "install"
    install.mkdir()

    monkeypatch.setattr(uninstall, "get_project_root", lambda: install)
    monkeypatch.setattr(uninstall, "get_hermes_home", lambda: home)
    monkeypatch.setattr("builtins.input", lambda prompt="": "3")

    uninstall.run_uninstall(SimpleNamespace())

    out = capsys.readouterr().out
    assert "Superforecasting Agent Uninstaller" in out
    assert "Hermes Agent Uninstaller" not in out
    assert "Uninstall cancelled." in out


def test_remove_path_from_shell_configs_removes_fork_and_legacy_markers(monkeypatch, tmp_path):
    import hermes_cli.uninstall as uninstall

    shell_config = tmp_path / ".zshrc"
    shell_config.write_text(
        "\n".join(
            [
                "export KEEP_ME=1",
                "# Superforecasting Agent",
                'export PATH="$HOME/.local/bin/superforecasting-agent:$PATH"',
                "# Hermes Agent",
                'export PATH="$HOME/.local/bin/hermes:$PATH"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(uninstall, "find_shell_configs", lambda: [shell_config])

    removed = uninstall.remove_path_from_shell_configs()

    assert removed == [shell_config]
    content = shell_config.read_text(encoding="utf-8")
    assert "KEEP_ME" in content
    assert "Superforecasting Agent" not in content
    assert "superforecasting-agent" not in content
    assert "Hermes Agent" not in content
    assert ".local/bin/hermes" not in content
