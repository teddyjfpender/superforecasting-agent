"""Goal configuration is interpreted identically without loading a runtime."""

import pytest

from superforecasting_agent.configuration.goals import configured_goal_turn_budget


@pytest.mark.parametrize('value, expected', [
    (7, 7), ('7', 7), (' 12 ', 12), (None, 20), ('', 20),
    (True, 20), (False, 20), (2.5, 20), (3.0, 20), ('2.5', 20),
    (0, 20), (-1, 20), ('-7', 20), ([], 20), ({}, 20), ('invalid', 20),
])
def test_goal_budget_values(value, expected):
    settings = {'max_turns': value}
    assert configured_goal_turn_budget(settings) == expected
    assert settings['max_turns'] is value


@pytest.mark.parametrize('settings', [None, True, 7, 'max_turns', [], {}])
def test_malformed_or_missing_goal_sections(settings):
    assert configured_goal_turn_budget(settings) == 20
