"""Tests for the harness immutability wall (agent.harness_wall).

The desk agent's file-WRITE tools (write_file / patch) must HARD-REJECT a
write whose resolved target lands inside the harness SOURCE TREE, while
freely allowing writes to the sanctioned workspace, the agent home, and the
system temp dir. These tests pin both the pure decision function and its
integration through ``tools.file_tools``.

They must NOT exercise (and so must not break) the harness's own internal
file IO, Claude Code's Edit/Write, or normal Python ``open()``.
"""

import os
from pathlib import Path

import pytest

from agent import harness_wall


@pytest.fixture(autouse=True)
def _reset_wall_caches():
    harness_wall.reset_caches()
    yield
    harness_wall.reset_caches()


@pytest.fixture
def _fake_home(tmp_path, monkeypatch):
    """Point the agent home at a tmp dir so workspace/home exemptions are
    isolated from the developer's real ~/.superforecasting-agent."""
    home = tmp_path / "agent-home"
    home.mkdir()
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
    # Drop the compatibility env vars so the override is unambiguous.
    monkeypatch.delenv("FORECAST_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    harness_wall.reset_caches()
    return home


class TestHarnessRootDetection:
    def test_project_root_is_a_harness_root(self):
        from hermes_cli.config import get_project_root

        roots = {str(r) for r in harness_wall.get_harness_source_roots()}
        assert str(get_project_root().resolve()) in roots

    def test_at_least_one_root(self):
        assert len(harness_wall.get_harness_source_roots()) >= 1


class TestRejectHarnessWrites:
    def test_write_into_tools_package_rejected(self):
        from hermes_cli.config import get_project_root

        target = str(get_project_root() / "tools" / "file_tools.py")
        err = harness_wall.check_harness_write(target)
        assert err is not None
        assert "harness is immutable" in err
        # Actionable: must name the workspace and the human-review path.
        assert "workspace" in err
        assert "human review" in err

    def test_write_into_hermes_cli_rejected(self):
        from hermes_cli.config import get_project_root

        target = str(get_project_root() / "hermes_cli" / "config.py")
        assert harness_wall.check_harness_write(target) is not None

    def test_new_file_in_harness_root_rejected(self):
        """A not-yet-existent leaf inside the harness root is still rejected."""
        from hermes_cli.config import get_project_root

        target = str(get_project_root() / "tools" / "evil_new_module.py")
        assert harness_wall.check_harness_write(target) is not None

    def test_relative_resolved_path_arg_is_honored(self):
        """tools/file_tools.py passes a pre-resolved abs path; we trust it."""
        from hermes_cli.config import get_project_root

        resolved = str(get_project_root() / "agent" / "harness_wall.py")
        err = harness_wall.check_harness_write("harness_wall.py", resolved=resolved)
        assert err is not None


class TestAllowWorkspaceWrites:
    def test_workspace_write_allowed(self, _fake_home):
        ws = harness_wall.get_workspace_dir()
        target = str(ws / "model.py")
        assert harness_wall.check_harness_write(target) is None

    def test_scripts_dir_write_allowed(self, _fake_home):
        target = str(_fake_home / "scripts" / "backtest.py")
        assert harness_wall.check_harness_write(target) is None

    def test_agent_home_write_allowed(self, _fake_home):
        target = str(_fake_home / "scratch" / "notes.md")
        assert harness_wall.check_harness_write(target) is None

    def test_temp_dir_write_allowed(self, tmp_path):
        target = str(tmp_path / "experiment.py")
        assert harness_wall.check_harness_write(target) is None

    def test_workspace_dir_under_home(self, _fake_home):
        assert harness_wall.get_workspace_dir() == (_fake_home / "workspace").resolve()


class TestConfigFlag:
    def test_disabled_flag_allows_harness_write(self, monkeypatch):
        from hermes_cli.config import get_project_root

        monkeypatch.setattr(
            harness_wall, "is_harness_wall_enabled", lambda: False
        )
        target = str(get_project_root() / "tools" / "file_tools.py")
        assert harness_wall.check_harness_write(target) is None

    def test_enabled_by_default_when_config_missing(self, monkeypatch):
        # load_config raising -> fail closed (enabled).
        import agent.harness_wall as hw

        def _boom():
            raise RuntimeError("no config")

        monkeypatch.setattr(
            "hermes_cli.config.load_config", _boom, raising=False
        )
        assert hw.is_harness_wall_enabled() is True

    def test_section_flag_disables(self, monkeypatch):
        import agent.harness_wall as hw

        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"harness_wall": {"enabled": False}},
            raising=False,
        )
        assert hw.is_harness_wall_enabled() is False

    def test_flat_flag_disables(self, monkeypatch):
        import agent.harness_wall as hw

        monkeypatch.setattr(
            "hermes_cli.config.load_config",
            lambda: {"harness_wall_enabled": False},
            raising=False,
        )
        assert hw.is_harness_wall_enabled() is False


class TestHarnessRootUnderAgentHome:
    """Pathology: the harness repo is checked out UNDER the agent home.

    The harness-root REJECT must take precedence over the broad agent-home
    allow, while the priority zones (workspace / scripts / temp) still win.
    """

    def test_harness_checkout_under_home_is_rejected(self, tmp_path, monkeypatch):
        home = tmp_path / "agent-home"
        (home / "workspace").mkdir(parents=True)
        checkout = home / "hermes-checkout"  # harness repo nested under home
        (checkout / "tools").mkdir(parents=True)
        (checkout / ".git").mkdir()
        monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(home))
        monkeypatch.delenv("FORECAST_HOME", raising=False)
        monkeypatch.delenv("HERMES_HOME", raising=False)
        harness_wall.reset_caches()
        # Force the harness roots to be the nested checkout.
        monkeypatch.setattr(
            harness_wall, "get_harness_source_roots", lambda: (checkout.resolve(),)
        )
        # The pytest tmp dir lives UNDER the system temp dir, which is itself a
        # priority-allowed root; that would (in this fixture only) swallow the
        # whole home. Restrict the priority zones to workspace+scripts so the
        # ORDERING under test — harness reject vs the broad agent-home allow —
        # is what actually decides. (In production the home is not under temp.)
        monkeypatch.setattr(
            harness_wall,
            "_priority_allowed_roots",
            lambda: ((home / "workspace").resolve(), (home / "scripts").resolve()),
        )

        # A write into the nested harness checkout must be REJECTED even though
        # it is also under the (broadly-allowed) agent home.
        target = str(checkout / "tools" / "evil.py")
        assert harness_wall.check_harness_write(target) is not None

        # But the workspace (priority zone) still wins.
        ws_target = str(home / "workspace" / "model.py")
        assert harness_wall.check_harness_write(ws_target) is None

        # And a plain home path NOT under the checkout is still allowed.
        home_target = str(home / "scratch.md")
        assert harness_wall.check_harness_write(home_target) is None


class TestTerminalCommandGuard:
    """Best-effort terminal redirect guard (check_harness_command_write)."""

    def test_redirect_into_harness_refused(self):
        from hermes_cli.config import get_project_root

        root = get_project_root()
        cmd = f"echo evil > {root / 'tools' / 'file_tools.py'}"
        assert harness_wall.check_harness_command_write(cmd) is not None

    def test_append_redirect_into_harness_refused(self):
        from hermes_cli.config import get_project_root

        root = get_project_root()
        cmd = f"cat payload >> {root / 'hermes_cli' / 'config.py'}"
        assert harness_wall.check_harness_command_write(cmd) is not None

    def test_tee_into_harness_refused(self):
        from hermes_cli.config import get_project_root

        root = get_project_root()
        cmd = f"echo hi | tee {root / 'agent' / 'harness_wall.py'}"
        assert harness_wall.check_harness_command_write(cmd) is not None

    def test_relative_redirect_resolves_against_cwd(self):
        from hermes_cli.config import get_project_root

        root = str(get_project_root())
        # Relative path that resolves into the harness when cwd is the repo root.
        assert (
            harness_wall.check_harness_command_write(
                "echo x > tools/file_tools.py", cwd=root
            )
            is not None
        )

    def test_redirect_to_temp_allowed(self, tmp_path):
        cmd = f"echo ok > {tmp_path / 'out.txt'}"
        assert harness_wall.check_harness_command_write(cmd) is None

    def test_dev_null_and_fd_dup_allowed(self):
        assert harness_wall.check_harness_command_write("ls > /dev/null") is None
        assert harness_wall.check_harness_command_write("cmd 2>&1") is None

    def test_no_redirect_allowed(self):
        assert harness_wall.check_harness_command_write("python train.py") is None

    def test_disabled_wall_allows(self, monkeypatch):
        from hermes_cli.config import get_project_root

        monkeypatch.setattr(harness_wall, "is_harness_wall_enabled", lambda: False)
        root = get_project_root()
        cmd = f"echo evil > {root / 'tools' / 'file_tools.py'}"
        assert harness_wall.check_harness_command_write(cmd) is None


class TestNeverCrashes:
    def test_unresolvable_path_allowed(self):
        # A NUL byte makes resolution fail; the wall must not raise.
        assert harness_wall.check_harness_write("\x00bad") is None

    def test_command_guard_never_crashes(self):
        # Junk input must not raise.
        assert harness_wall.check_harness_command_write("\x00 > \x00") is None
        assert harness_wall.check_harness_command_write("") is None


class TestFileToolsIntegration:
    """End-to-end through tools.file_tools — the real chokepoint."""

    def test_write_file_tool_rejects_harness_path(self):
        from tools.file_tools import write_file_tool
        from hermes_cli.config import get_project_root
        import json

        target = str(get_project_root() / "tools" / "_wall_probe.py")
        out = write_file_tool(target, "print('hijack')")
        data = json.loads(out)
        assert "error" in data
        assert "harness is immutable" in data["error"]
        # The probe file must NOT have been created.
        assert not Path(target).exists()

    def test_patch_tool_rejects_harness_path(self):
        from tools.file_tools import patch_tool
        from hermes_cli.config import get_project_root
        import json

        target = str(get_project_root() / "hermes_cli" / "_wall_probe.py")
        out = patch_tool(
            mode="replace", path=target, old_string="a", new_string="b"
        )
        data = json.loads(out)
        assert "error" in data
        assert "harness is immutable" in data["error"]

    def test_patch_v4a_rejects_harness_path(self):
        from tools.file_tools import patch_tool
        from hermes_cli.config import get_project_root
        import json

        root = get_project_root()
        patch = (
            "*** Begin Patch\n"
            f"*** Update File: {root / 'tools' / 'file_tools.py'}\n"
            "@@\n"
            "-old\n"
            "+new\n"
            "*** End Patch\n"
        )
        out = patch_tool(mode="patch", patch=patch)
        data = json.loads(out)
        assert "error" in data
        assert "harness is immutable" in data["error"]

    def test_write_file_tool_allows_workspace(self, _fake_home, monkeypatch):
        from tools.file_tools import write_file_tool
        import json

        ws = harness_wall.get_workspace_dir()
        ws.mkdir(parents=True, exist_ok=True)
        target = str(ws / "model.py")
        out = write_file_tool(target, "X = 1\n")
        data = json.loads(out)
        # The harness wall must NOT have fired; a real write happened.
        assert "harness is immutable" not in json.dumps(data)
        assert Path(target).exists()
        assert Path(target).read_text() == "X = 1\n"

    def test_write_file_tool_allows_temp(self, tmp_path):
        from tools.file_tools import write_file_tool
        import json

        target = str(tmp_path / "experiment.py")
        out = write_file_tool(target, "Y = 2\n")
        data = json.loads(out)
        assert "harness is immutable" not in json.dumps(data)
        assert Path(target).exists()


class TestInternalIoUnaffected:
    """The wall is scoped to the agent's file tools; plain open() is untouched."""

    def test_plain_open_into_harness_tree_still_works(self, tmp_path):
        # Simulate harness-internal IO: writing a file under the repo tree
        # via plain open() (as the harness itself does for caches, build
        # artifacts, etc.) must NOT be intercepted — the wall only lives in
        # write_file_tool / patch_tool.
        from hermes_cli.config import get_project_root

        probe = get_project_root() / "build" / "_wall_internal_probe.tmp"
        probe.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(probe, "w") as fh:
                fh.write("internal")
            assert probe.read_text() == "internal"
        finally:
            probe.unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
