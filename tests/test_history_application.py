"""History edits preserve content and agree across product adapters."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.application.history import prepare_undo


def test_undo_plan_removes_complete_exchange_and_detaches_prefix():
    history = [{'role': 'system', 'content': [{'text': 'policy'}]},
               {'role': 'user', 'content': [{'type': 'image_url'}]},
               {'role': 'system', 'content': 'context'},
               {'role': 'assistant', 'content': 'response'}]
    original = deepcopy(history)
    plan = prepare_undo(history)
    assert plan.removed == 3
    assert plan.preview == '[attachments]'
    assert plan.history == history[:1]
    plan.history[0]['content'][0]['text'] = 'changed'
    assert history == original


@pytest.mark.parametrize('history', [[], [{'role': 'assistant', 'content': 'preserve'}]])
def test_undo_without_user_is_noop(history):
    original = deepcopy(history)
    assert prepare_undo(history) is None
    assert history == original


def test_cli_undo_handles_long_structured_content(capsys):
    from tests.cli.test_cli_init import _make_cli

    cli = _make_cli()
    cli.conversation_history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'note'}] * 70}]
    cli.undo_last()
    assert cli.conversation_history == []
    assert 'Undid 1 message' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_gateway_undo_prepares_structured_preview_before_mutation():
    from gateway.run import GatewayRunner

    history = [{'role': 'user', 'content': [{'type': 'text', 'text': 'note'}] * 70}]
    entry = SimpleNamespace(session_id='durable', last_prompt_tokens=42)
    store = SimpleNamespace(get_or_create_session=Mock(return_value=entry),
                            load_transcript=Mock(return_value=history), rewrite_transcript=Mock())
    runner = SimpleNamespace(session_store=store)
    event = SimpleNamespace(source=object())
    store.rewrite_transcript.side_effect = OSError('disk unavailable')
    with pytest.raises(OSError, match='disk unavailable'):
        await GatewayRunner._handle_undo_command(runner, event)
    assert entry.last_prompt_tokens == 42
    store.rewrite_transcript.side_effect = None
    result = await GatewayRunner._handle_undo_command(runner, event)
    assert 'note' in result
    store.rewrite_transcript.assert_called_with('durable', [])
    assert entry.last_prompt_tokens == 0
