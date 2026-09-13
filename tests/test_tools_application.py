"""The CLI and terminal share tool inventory display semantics."""
from superforecasting_agent.application.tools import describe_tools


def test_tool_description_order_and_empty_inventory():
    assert describe_tools([], lambda name: None) == "No tools available"
    rows = [{'function': {'name': 'zebra', 'description': 'One sentence. More.'}},
            {'function': {'name': 'alpha', 'description': 'First line\nSecond line'}}]
    text = describe_tools(rows, lambda name: None)
    assert text.index('alpha') < text.index('zebra')
    assert '[unknown]' in text
    assert 'Total: 2 tools' in text
    assert 'More.' not in text and 'Second line' not in text


def test_configuration_view_reports_disabled_servers_and_both_filters():
    from superforecasting_agent.application.tools import describe_tool_configuration

    text = describe_tool_configuration(set(), {
        'off': {'enabled': False},
        'filtered': {'tools': {'include': ['read', 'write'], 'exclude': ['write']}},
    })
    assert 'off  disabled' in text
    assert '[include only: read, write] [excluded: write]' in text
    assert 'all tools enabled' not in text


def test_configuration_view_rejects_string_tool_filters():
    import pytest
    from superforecasting_agent.application.tools import describe_tool_configuration

    with pytest.raises(ValueError, match='list of tool names'):
        describe_tool_configuration(set(), {'source': {'tools': {'exclude': 'read'}}})
