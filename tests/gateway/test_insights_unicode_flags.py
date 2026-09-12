"""Exercise the actual shared parser used by all insights command consumers."""

import pytest

from superforecasting_agent.application.insights import InsightsQuery, parse_insights_arguments


@pytest.mark.parametrize("dash", ["--", "‒", "–", "—", "―"])
def test_unicode_insights_flags_use_the_shared_contract(dash):
    assert parse_insights_arguments(f'{dash}days 7 {dash}source "team chat"') == InsightsQuery(7, "team chat")


@pytest.mark.parametrize("argument,expected", [("", InsightsQuery()), ("14", InsightsQuery(14)), ("--source cli", InsightsQuery(source="cli"))])
def test_insights_defaults_and_shorthand(argument, expected):
    assert parse_insights_arguments(argument) == expected


@pytest.mark.parametrize("argument", ["--days", "--source", "--days nope", "--days 0", "--days -1", "--source ''", "--typo 7", "--days --source cli"])
def test_invalid_insights_arguments_fail_before_execution(argument):
    with pytest.raises(ValueError):
        parse_insights_arguments(argument)
