"""Resume selection works beyond a bounded internal-session backlog."""
from types import SimpleNamespace

import pytest

from superforecasting_agent.application.sessions import list_resumable_sessions
from superforecasting_agent.storage.session import SessionDB


def test_cli_and_tui_resume_find_human_history_beyond_internal_backlog(tmp_path, monkeypatch):
    db = SessionDB(tmp_path / 'sessions.db')
    db.create_session('human', source='new-platform')
    for index in range(220):
        db.create_session(f'noise-{index}', source=' TOOL ')
    db.create_session('active', source='tui')
    rows = list_resumable_sessions(db, limit=1, exclude_ids={'active'})
    assert [row['id'] for row in rows] == ['human']

    from tui_gateway import server
    monkeypatch.setattr(server, '_get_db', lambda: db)
    monkeypatch.setattr(server._host, 'sessions', {'live': {'session_key': 'active'}})
    for method in ('session.list', 'session.most_recent'):
        response = server.handle_request({'id': 'test', 'method': method, 'params': {'limit': 1}})['result']
        assert (response['sessions'][0]['id'] if method == 'session.list' else response['session_id']) == 'human'

    from cli import ForecastCLI
    caller = SimpleNamespace(_session_db=db, session_id='active')
    assert [row['id'] for row in ForecastCLI._list_recent_sessions(caller, limit=1)] == ['human']
    assert list_resumable_sessions(db, source=' TOOL ', limit=1)[0]['source'] == ' TOOL '


@pytest.mark.parametrize('limit', [True, 0, -1, 10001, '10'])
def test_session_selection_rejects_invalid_limits_before_access(limit):
    class NoAccess:
        def list_sessions_rich(self, **kwargs):
            pytest.fail('invalid input reached storage')
    with pytest.raises(ValueError, match='session limit'):
        list_resumable_sessions(NoAccess(), limit=limit)
