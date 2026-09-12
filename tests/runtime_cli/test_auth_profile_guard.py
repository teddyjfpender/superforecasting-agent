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
