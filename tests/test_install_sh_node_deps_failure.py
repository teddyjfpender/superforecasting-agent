"""Installer must not claim success after Node dependency failure."""

from pathlib import Path


INSTALL_SH = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"


def test_node_requires_npm_and_dependency_failures_are_fatal() -> None:
    text = INSTALL_SH.read_text(encoding="utf-8")

    assert "command -v node &> /dev/null && command -v npm &> /dev/null" in text
    assert (
        '[ -x "$HERMES_HOME/node/bin/node" ] && '
        '[ -x "$HERMES_HOME/node/bin/npm" ]' in text
    )
    assert "npm install failed; Node.js dependencies were not installed" in text
    assert "TUI npm install failed; TUI dependencies were not installed" in text
    assert "npm install failed (browser tools may not work)" not in text
    assert "TUI npm install failed (superforecasting-agent --tui may not work)" not in text
