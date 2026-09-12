"""Default auth homes must stay protected when a test forgets its profile."""

from pathlib import Path

import pytest

from superforecasting_agent.runtime import auth


@pytest.mark.parametrize("home_name", [".superforecasting-agent", ".hermes"])
def test_default_auth_home_is_refused_during_tests(tmp_path, monkeypatch, home_name):
    user_home = tmp_path / "user"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    monkeypatch.setattr(auth, "get_agent_home", lambda: user_home / home_name)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "isolated auth guard test")
    with pytest.raises(RuntimeError, match="Refusing to touch real user auth store"):
        auth._auth_file_path()
    assert not user_home.exists()


def test_isolated_auth_home_is_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "user"))
    monkeypatch.setattr(auth, "get_agent_home", lambda: tmp_path / "isolated")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "isolated auth guard test")
    assert auth._auth_file_path() == tmp_path / "isolated" / "auth.json"


@pytest.mark.parametrize("home_name", [".superforecasting-agent", ".hermes"])
def test_global_default_auth_is_not_read_during_tests(tmp_path, monkeypatch, home_name):
    user_home = tmp_path / "user"
    path = user_home / home_name / "auth.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"providers": {"fixture": {"marker": "not-for-tests"}}}', encoding="utf-8")
    monkeypatch.setenv("HOME", str(user_home))
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "isolated global auth guard test")
    monkeypatch.setattr(auth, "_global_auth_file_path", lambda: path)
    assert auth._load_global_auth_store() == {}


def test_global_fallback_does_not_write_corrupt_backup(tmp_path, monkeypatch):
    path = tmp_path / "shared" / "auth.json"
    path.parent.mkdir()
    path.write_text('{broken', encoding="utf-8")
    monkeypatch.setattr(auth, "_global_auth_file_path", lambda: path)
    assert auth._load_global_auth_store() == {"version": 1, "providers": {}}
    assert list(path.parent.iterdir()) == [path]
    assert path.read_text(encoding="utf-8") == '{broken'
