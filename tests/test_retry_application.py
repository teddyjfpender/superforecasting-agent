"""Retry preparation preserves request data and never edits caller-owned history."""

from copy import deepcopy

import pytest

from superforecasting_agent.application.retry import RetryUnavailable, prepare_retry


def test_plan_detaches_prefix_and_request_from_original():
    history = [
        {'role': 'user', 'content': 'earlier', 'metadata': {'label': 'original'}},
        {'role': 'assistant', 'content': 'answer'},
        {'role': 'user', 'content': [{'type': 'text', 'text': 'retry'}, {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,test'}}]},
        {'role': 'assistant', 'content': 'partial'},
    ]
    before = deepcopy(history)
    plan = prepare_retry(history, structured_messages=True)
    assert plan.history == history[:2]
    assert plan.message == history[2]['content']
    plan.history[0]['metadata']['label'] = 'changed'
    plan.message[1]['image_url']['url'] = 'changed'
    assert history == before


@pytest.mark.parametrize('content', ['', '  ', None, [], [{'type': 'image_url', 'image_url': {'url': 'image'}}], [{'type': 'text', 'text': 4}]])
def test_text_consumer_rejects_invalid_or_lossy_retry_without_mutation(content):
    history = [{'role': 'user', 'content': content}, {'role': 'assistant', 'content': 'saved'}]
    before = deepcopy(history)
    with pytest.raises(RetryUnavailable):
        prepare_retry(history)
    assert history == before


def test_text_blocks_are_replayed_in_order():
    plan = prepare_retry([{'role': 'user', 'content': [{'type': 'text', 'text': 'one'}, {'type': 'text', 'text': 'two'}]}])
    assert plan.message == 'one two'
    assert plan.history == []


@pytest.mark.parametrize('structured', [False, True])
def test_empty_text_blocks_are_not_retryable(structured):
    with pytest.raises(RetryUnavailable, match='empty'):
        prepare_retry([{'role': 'user', 'content': [{'type': 'text', 'text': ' '}]}], structured_messages=structured)
