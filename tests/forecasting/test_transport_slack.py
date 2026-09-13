"""Slack transport rejects ambiguous credentials and malformed response types."""
import io
import json

import pytest

from forecasting.transports import slack


@pytest.mark.parametrize('response', [[], None, {'ok': 'false'}, {'ok': 1}, {'success': True}])
def test_malformed_wire_response_is_a_structured_failure(monkeypatch, response):
    monkeypatch.setenv('SLACK_BOT_TOKEN', 'fixture-token')
    monkeypatch.setattr(slack.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(json.dumps(response).encode()))
    result = slack.execute_slack_action({'action': 'list_channels'})
    assert result['success'] is False
    assert 'boolean ok' in result['error']


def test_wire_success_field_cannot_override_slack_failure(monkeypatch):
    monkeypatch.setenv('SLACK_BOT_TOKEN', 'fixture-token')
    monkeypatch.setattr(slack, 'api_call', lambda *args, **kwargs: {'ok': False, 'success': True, 'error': 'denied'})
    result = slack.execute_slack_action({'action': 'list_channels'})
    assert result['success'] is False
    assert result['error'] == 'denied'


@pytest.mark.parametrize('entry', [None, {}, {'token': True}, {'token': 42}, {'token': '  '}])
def test_explicit_workspace_never_falls_back_to_another_file_entry(monkeypatch, tmp_path, entry):
    monkeypatch.delenv('SLACK_BOT_TOKEN', raising=False)
    monkeypatch.setattr('superforecasting_agent.constants.get_agent_home', lambda: tmp_path)
    (tmp_path / 'slack_tokens.json').write_text(json.dumps({'wanted': entry, 'other': {'token': 'other-token'}}), encoding='utf-8')
    assert slack.resolve_bot_token('wanted') is None
    assert slack.resolve_bot_token('missing') is None
    assert slack.resolve_bot_token() == 'other-token'
