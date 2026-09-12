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
