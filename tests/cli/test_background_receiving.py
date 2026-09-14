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


def test_resume_exposes_interrupted_receipt_after_database_reopen(tmp_path, monkeypatch):
    """Acknowledged findings remain recoverable even before chat writes a message."""
    path = tmp_path / 'state.db'
    db = SessionDB(path)
    db.create_session('desk', source='cli')
    note = BackgroundNotification({'session_key': 'desk', 'journal_event_id': 'saved'}, '[bold]Evidence[/bold]')
    from superforecasting_agent.hosting.notifications import admit_background_notification
    acknowledged = Mock()
    receipt, created = admit_background_notification(db, note.event, 'desk', note.prompt, acknowledge=acknowledged)
    assert created
    turns.transition(db, receipt, 'running', delta='Partial finding')
    db.close()
    cli = ForecastCLI.__new__(ForecastCLI)
    cli.session_id = 'desk'
    cli._resumed = True
    cli.conversation_history = []
    cli._session_db = SessionDB(path)
    cli._console_print = Mock()
    monkeypatch.setattr(turns, '_owner_alive', lambda row: False)
    try:
        assert cli._preload_resumed_session() is False  # no transcript yet
        shown = '\n'.join(str(call.args[0]) for call in cli._console_print.call_args_list)
        assert receipt in shown
        assert 'interrupted' in shown
        assert note.prompt in shown
        assert 'Partial finding' in shown
        assert 'tools may already have run' in shown
        assert turns.latest(cli._session_db, 'desk')['status'] == 'interrupted'
        assert admit_background_notification(cli._session_db, note.event, 'desk', note.prompt, acknowledge=acknowledged) == (receipt, False)
        assert cli.conversation_history == []  # resume never fabricates a new turn
    finally:
        cli._session_db.close()
