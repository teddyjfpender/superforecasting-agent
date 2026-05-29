"""Tests for credential/secret read-blocking in ``agent.file_safety``.

Ported from upstream hermes-agent PR (fix(file-safety): widen read-deny to
.env, mcp-tokens/, webhook secrets, root). ``read_file`` was previously only
sandboxed against the skills/.hub cache, leaving ``auth.json``, ``.env``,
OAuth tokens, and webhook HMAC secrets readable. A prompt-injection reaching
``read_file`` could exfiltrate active credentials.

These verify ``get_read_block_error`` denies the credential stores (under both
the active home and the global root, for profile mode) while leaving arbitrary
files readable, and that the ``skills/.hub`` deny still applies.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Point both home and root resolution at one tmp dir for isolated checks."""
    import agent.file_safety as fs

    home = tmp_path / "agent_home"
    home.mkdir()
    monkeypatch.setattr(fs, "_hermes_home_path", lambda: home)
    monkeypatch.setattr(fs, "_hermes_root_path", lambda: home)
    return home


def _create(home: Path, rel: str | Path) -> Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("dummy", encoding="utf-8")
    return p


def test_auth_json_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, "auth.json")))
    assert err is not None and "credential store" in err and "auth.json" in err


def test_auth_lock_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, "auth.lock")))
    assert err is not None and "credential store" in err


def test_anthropic_oauth_json_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, ".anthropic_oauth.json")))
    assert err is not None and "credential store" in err


def test_dotenv_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, ".env")))
    assert err is not None and "credential store" in err


def test_webhook_subscriptions_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, "webhook_subscriptions.json")))
    assert err is not None and "credential store" in err


def test_mcp_tokens_file_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, Path("mcp-tokens") / "github.json")))
    assert err is not None and "MCP token" in err


def test_mcp_tokens_nested_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, Path("mcp-tokens") / "providers" / "azure.json")))
    assert err is not None and "MCP token" in err


def test_arbitrary_home_file_not_blocked(fake_home):
    from agent.file_safety import get_read_block_error

    assert get_read_block_error(str(_create(fake_home, "session_log.txt"))) is None


def test_subdirectory_named_auth_json_not_blocked(fake_home):
    """Only the top-level auth.json is the credential store; a same-named file
    in a subdirectory (e.g. a skill mock) must remain readable."""
    from agent.file_safety import get_read_block_error

    nested = _create(fake_home, Path("skills") / "my-skill" / "auth.json")
    assert get_read_block_error(str(nested)) is None


def test_skills_hub_block_still_applies(fake_home):
    from agent.file_safety import get_read_block_error

    err = get_read_block_error(str(_create(fake_home, "skills/.hub/manifest.json")))
    assert err is not None and "internal agent cache file" in err


def test_root_credential_blocked_under_profile(tmp_path, monkeypatch):
    """In profile mode (home = <root>/profiles/<name>), <root>/auth.json is
    still blocked because the deny iterates both home and root."""
    import agent.file_safety as fs

    root = tmp_path / "root"
    home = root / "profiles" / "default"
    home.mkdir(parents=True)
    monkeypatch.setattr(fs, "_hermes_home_path", lambda: home)
    monkeypatch.setattr(fs, "_hermes_root_path", lambda: root)
    (root / "auth.json").write_text("dummy", encoding="utf-8")
    err = fs.get_read_block_error(str(root / "auth.json"))
    assert err is not None and "credential store" in err


def test_path_traversal_resolves_to_blocked(fake_home, tmp_path):
    from agent.file_safety import get_read_block_error

    _create(fake_home, "auth.json")
    sibling = tmp_path / "elsewhere"
    sibling.mkdir()
    traversal = sibling / ".." / "agent_home" / "auth.json"
    err = get_read_block_error(str(traversal))
    assert err is not None and "credential store" in err


def test_symlink_to_auth_json_blocked(fake_home, tmp_path):
    from agent.file_safety import get_read_block_error

    target = _create(fake_home, "auth.json")
    link = tmp_path / "shim.json"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform/filesystem")
    err = get_read_block_error(str(link))
    assert err is not None and "credential store" in err


def test_read_file_tool_blocks_relative_path_under_terminal_cwd(fake_home, tmp_path, monkeypatch):
    """A relative path like "auth.json" resolved by read_file_tool against
    TERMINAL_CWD == home must still be blocked, even though the Python process
    cwd is a different directory."""
    import json

    import tools.file_tools as ft

    _create(fake_home, "auth.json")
    monkeypatch.setenv("TERMINAL_CWD", str(fake_home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ft, "_get_live_tracking_cwd", lambda task_id="default": None)

    out = json.loads(ft.read_file_tool("auth.json"))
    assert "error" in out and "credential store" in out["error"]
