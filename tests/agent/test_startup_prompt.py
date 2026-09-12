"""Startup skill policy is shared without constructing a model runtime."""

from unittest.mock import Mock

import pytest

from agent.startup_prompt import prepare_startup_prompt


@pytest.mark.parametrize("prompt,skills,expected", [
    (None, [], ""), (" base ", [], "base"),
    ("base", ["research"], "base\n\nskill instructions"),
    (None, ["research"], "skill instructions"),
])
def test_startup_prompt_assembly(monkeypatch, prompt, skills, expected):
    loader = Mock(return_value=("skill instructions", ["research"], []))
    monkeypatch.setattr("agent.skill_commands.build_preloaded_skills_prompt", loader)
    assembled, loaded = prepare_startup_prompt(prompt, skills, session_id="owner")
    assert assembled == expected
    assert loaded == (["research"] if skills else [])
    if skills:
        loader.assert_called_once_with(skills, task_id="owner")
    else:
        loader.assert_not_called()


def test_invalid_prompt_rejected_before_skill_access(monkeypatch):
    loader = Mock()
    monkeypatch.setattr("agent.skill_commands.build_preloaded_skills_prompt", loader)
    with pytest.raises(ValueError, match="system_prompt must be a string"):
        prepare_startup_prompt({"bad": "shape"}, ["research"], session_id="owner")
    loader.assert_not_called()


def test_missing_skill_has_no_partial_startup_result(monkeypatch):
    monkeypatch.setattr("agent.skill_commands.build_preloaded_skills_prompt", lambda *a, **k: ("partial", ["found"], ["missing"]))
    with pytest.raises(ValueError, match=r"Unknown skill\(s\): missing"):
        prepare_startup_prompt("base", ["found", "missing"], session_id="owner")
