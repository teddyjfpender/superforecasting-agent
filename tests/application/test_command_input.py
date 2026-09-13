"""Shared command admission rejects malformed inputs before dispatch."""

import pytest

from superforecasting_agent.application.command_input import (
    board_invocation,
    command_fields,
    command_text,
)


@pytest.mark.parametrize('name,args', [(None, ''), ([], ''), ('', ''), ('/', ''), ('two words', ''), ('status', None), ('status', 5)])
def test_structured_input_rejects_nontext_and_ambiguous_names(name, args):
    with pytest.raises(ValueError):
        command_fields(name, args)


def test_text_and_structured_commands_preserve_argument_identity():
    assert command_text('/KaNbAn --board Research create "Mixed Case"') == command_fields('KANBAN', '--board Research create "Mixed Case"')


@pytest.mark.parametrize('arguments', ['create "unterminated', '--board', '--board=', '--board ""', '--board --json'])
def test_bad_board_invocation_fails_before_execution(arguments):
    with pytest.raises(ValueError):
        board_invocation(arguments)


def test_board_metadata_matches_execution_tokens():
    result = board_invocation('--board first --board=second create "Title with spaces"')
    assert result.board == 'second'
    assert result.action == 'create'
    assert result.tokens[-1] == 'Title with spaces'
