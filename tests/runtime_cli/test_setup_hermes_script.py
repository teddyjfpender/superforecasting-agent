from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup-superforecasting-agent.sh"
LEGACY_SETUP_SCRIPT = REPO_ROOT / "setup-hermes.sh"


def test_setup_superforecasting_agent_script_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_setup_hermes_compatibility_wrapper_is_valid_shell():
    result = subprocess.run(["bash", "-n", str(LEGACY_SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    content = LEGACY_SETUP_SCRIPT.read_text(encoding="utf-8")
    assert "setup-superforecasting-agent.sh" in content
    assert "Compatibility wrapper" in content


def test_setup_superforecasting_agent_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux]" in content
    assert "packaging/termux/constraints.txt" in content
    assert "$PREFIX/bin" in content
