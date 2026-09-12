"""Messaging retries use shared preparation before persistent mutation or send."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from gateway.run import GatewayRunner


def runner_with(history):
    entry = SimpleNamespace(session_id='durable', last_prompt_tokens=42)
    runner = SimpleNamespace(
        session_store=SimpleNamespace(
            get_or_create_session=Mock(return_value=entry),
            load_transcript=Mock(return_value=history),
            rewrite_transcript=Mock(),
        ),
        _handle_message=AsyncMock(return_value='sent'),
    )
    event = SimpleNamespace(source=object(), raw_message=object(), channel_prompt='policy')
    return runner, entry, event


@pytest.mark.asyncio
async def test_gateway_retry_rejects_attachments_before_rewrite():
    runner, entry, event = runner_with([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'image'}}]}])
    result = await GatewayRunner._handle_retry_command(runner, event)
    assert 'attachments' in result
    runner.session_store.rewrite_transcript.assert_not_called()
    runner._handle_message.assert_not_called()
    assert entry.last_prompt_tokens == 42


@pytest.mark.asyncio
async def test_gateway_rewrite_failure_cannot_resend_or_reset_tokens():
    runner, entry, event = runner_with([{'role': 'user', 'content': 'retry'}])
    runner.session_store.rewrite_transcript.side_effect = OSError('disk unavailable')
    with pytest.raises(OSError, match='disk unavailable'):
        await GatewayRunner._handle_retry_command(runner, event)
    runner._handle_message.assert_not_called()
    assert entry.last_prompt_tokens == 42


@pytest.mark.asyncio
async def test_gateway_retry_commits_prepared_history_before_send():
    history = [{'role': 'system', 'content': 'policy'}, {'role': 'user', 'content': [{'type': 'text', 'text': 'retry'}]}]
    runner, entry, event = runner_with(history)
    async def send(retry):
        runner.session_store.rewrite_transcript.assert_called_once_with('durable', history[:1])
        assert entry.last_prompt_tokens == 0
        assert retry.text == 'retry'
        assert retry.source is event.source
        return 'sent'
    runner._handle_message.side_effect = send
    assert await GatewayRunner._handle_retry_command(runner, event) == 'sent'
