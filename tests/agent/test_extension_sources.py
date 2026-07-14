import json
import subprocess

import pytest

from agent.extension_sources import load_extension_prompts, sync_extension_sources


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_syncs_exact_revision_and_writes_lock(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init")
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test")
    (source / "skills" / "desk").mkdir(parents=True)
    (source / "skills" / "desk" / "SKILL.md").write_text("# Desk\n")
    (source / "prompts").mkdir()
    (source / "prompts" / "forecasting.md").write_text(
        "Use the ACME source registry.\n"
    )
    _git(source, "add", ".")
    _git(source, "commit", "-m", "initial")
    revision = _git(source, "rev-parse", "HEAD")

    home = tmp_path / "home"
    monkeypatch.setattr("agent.extension_sources.get_hermes_home", lambda: home)
    config = {
        "extensions": {"sources": [{"repo": source.as_uri(), "ref": revision}]}
    }
    checkouts = sync_extension_sources(config)

    assert checkouts[0].revision == revision
    assert checkouts[0].surface("skills").joinpath("desk/SKILL.md").is_file()
    assert "Use the ACME source registry." in load_extension_prompts(config)
    assert not checkouts[0].root.joinpath(".git").exists()
    lock = json.loads((home / "extensions/extensions.lock.json").read_text())
    assert lock["sources"][0]["revision"] == revision


def test_rejects_option_like_git_ref(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr("agent.extension_sources.get_hermes_home", lambda: home)
    with pytest.raises(ValueError, match="invalid extension ref"):
        sync_extension_sources({
            "extensions": {"sources": [{"repo": "example/repo", "ref": "--help"}]}
        })


def test_rejects_credentials_embedded_in_repo_url(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.extension_sources.get_hermes_home", lambda: tmp_path)
    with pytest.raises(ValueError, match="must not contain credentials"):
        sync_extension_sources({
            "extensions": {"sources": [{
                "repo": "https://token:secret@example.com/repo.git", "ref": "main",
            }]}
        })


def test_rejects_unsafe_scp_style_repo(tmp_path, monkeypatch):
    monkeypatch.setattr("agent.extension_sources.get_hermes_home", lambda: tmp_path)
    with pytest.raises(ValueError, match="invalid extension repo"):
        sync_extension_sources({
            "extensions": {"sources": [{"repo": "git@host:repo name", "ref": "main"}]}
        })
