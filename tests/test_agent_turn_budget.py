"""Every product interprets configured execution budgets as positive integers."""

import pytest

from superforecasting_agent.configuration.agent_limits import agent_turn_budget
from superforecasting_agent.configuration import _normalize_max_turns_config


@pytest.mark.parametrize('value', [True, False, -2, 0, 2.5, 3.0, 'broken', '', [], {}])
def test_invalid_nested_budget_falls_back_without_coercion(value):
    cfg = {'agent': {'max_turns': value}, 'max_turns': '37'}
    assert agent_turn_budget(cfg) == 37
    assert _normalize_max_turns_config(cfg)['agent']['max_turns'] == 37
    assert cfg['agent']['max_turns'] == value


@pytest.mark.parametrize('section', [None, [], 'bad', False])
def test_malformed_agent_section_uses_legacy_or_default(section):
    assert agent_turn_budget({'agent': section, 'max_turns': 22}) == 22
    assert _normalize_max_turns_config({'agent': section})['agent']['max_turns'] == 90


def test_override_then_nested_then_legacy_then_default():
    cfg = {'agent': {'max_turns': '37'}, 'max_turns': 12}
    assert agent_turn_budget(cfg, override='61') == 61
    assert agent_turn_budget(cfg, override=True) == 37
    assert agent_turn_budget({'max_turns': 12}) == 12
    assert agent_turn_budget(None, default=200) == 200


@pytest.mark.parametrize('default', [True, 0, -1, 3.5, '90'])
def test_invalid_fallback_is_an_error(default):
    with pytest.raises(ValueError):
        agent_turn_budget({}, default=default)


@pytest.mark.parametrize('value', [True, 2.5, 'bad', -1, None, '31'])
def test_tui_uses_shared_budget_interpretation(monkeypatch, value):
    from tui_gateway import server

    monkeypatch.setattr(server, '_tui_env', lambda key: '')
    cfg = {'agent': {'max_turns': value}, 'max_turns': 17}
    assert server._cfg_max_turns(cfg, 90) == agent_turn_budget(cfg)
    monkeypatch.setattr(server, '_tui_env', lambda key: '45')
    assert server._cfg_max_turns(cfg, 90) == 45
