"""Classic CLI background delivery shares durable admission with other hosts."""
from unittest.mock import Mock

from cli import ForecastCLI
from superforecasting_agent.hosting.notifications import BackgroundNotification
from superforecasting_agent.storage.session import SessionDB
from superforecasting_agent.storage import turns


def test_cli_delivery_runs_chat_once_and_restores_idle_state(tmp_path, monkeypatch):
    from tools import async_delegation

    cli = ForecastCLI.__new__(ForecastCLI)
    cli.session_id = 'desk'
    cli._session_db = SessionDB(tmp_path / 'state.db')
    cli._invalidate = Mock()
    acknowledged = Mock()
    monkeypatch.setattr(async_delegation, 'acknowledge_notification', acknowledged)
    observed = []
    def chat(prompt):
        assert cli._agent_running
        assert turns.latest(cli._session_db, 'desk')['status'] == 'running'
        observed.append(prompt)
        cli._last_turn_outcome = {'completed': True, 'final_response': 'Integrated finding'}
    cli.chat = chat
    note = BackgroundNotification({'session_key': 'desk', 'journal_event_id': 'saved'}, 'Evidence')
    try:
        first = cli._deliver_background_notification(note)
        assert not cli._agent_running
        assert turns.latest(cli._session_db, 'desk')['partial_text'] == 'Integrated finding'
        assert cli._deliver_background_notification(note) == first
        assert observed == ['Evidence']
        assert acknowledged.call_count == 2
    finally:
        cli._session_db.close()
