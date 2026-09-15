"""First-run choices use the same atomic application owner as the TUI."""

import pytest

from superforecasting_agent.application.data_desk import DataDesk
from superforecasting_agent.runtime.data_desk import setup_data_desk
from superforecasting_agent.runtime import setup


@pytest.mark.parametrize(
    "answers,expected", [([1], "empty"), ([0, 0, 0], "preset"), ([0, 0, 2], "empty")]
)
def test_setup_choice_persists_and_does_not_prompt_again(
    tmp_path, monkeypatch, answers, expected
):
    answers = iter(answers)
    monkeypatch.setattr(setup, "prompt_choice", lambda *args: next(answers))
    monkeypatch.setattr(setup, "print_info", lambda *args: None)
    setup_data_desk(tmp_path)
    result = DataDesk(tmp_path).selection()
    assert result.state == expected
    setup_data_desk(tmp_path)
    assert DataDesk(tmp_path).selection() == result


def test_setup_can_inspect_and_keep_only_one_real_series(tmp_path, monkeypatch):
    answers = iter([0, 0, 1])
    monkeypatch.setattr(setup, "prompt_choice", lambda *args: next(answers))
    monkeypatch.setattr(setup, "prompt_checklist", lambda *args: [0])
    monkeypatch.setattr(setup, "print_info", lambda *args: None)
    setup_data_desk(tmp_path)
    result = DataDesk(tmp_path).selection()
    assert result.state == "custom"
    assert len(result.series_ids) == 1
