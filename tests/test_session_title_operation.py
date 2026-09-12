"""CLI and RPC title changes share canonical values and uniqueness rules."""
from types import SimpleNamespace

import pytest

from superforecasting_agent.application.sessions import set_session_title
from superforecasting_agent.storage.session import SessionDB


@pytest.fixture
def db(tmp_path):
    store = SessionDB(db_path=tmp_path / 'sessions.db')
    yield store
    store.close()


@pytest.mark.parametrize('exists', [False, True])
@pytest.mark.parametrize('surface', ['application', 'cli', 'rpc'])
def test_title_is_canonical_in_storage_response_and_pending_state(db, monkeypatch, exists, surface):
    if exists:
        db.create_session('s1', source='cli')
    raw = '  Forecast\x00   desk  '
    if surface == 'application':
        assert set_session_title(db, 's1', raw) == ('Forecast desk', not exists)
    elif surface == 'cli':
        import cli
        shell = SimpleNamespace(config={}, _session_db=db, session_id='s1', _pending_title='old')
        output = []
        monkeypatch.setattr(cli, '_cprint', output.append)
        assert cli.ForecastCLI.process_command(shell, '/title ' + raw)
        assert shell._pending_title == (None if exists else 'Forecast desk')
        assert any('Forecast desk' in line for line in output)
        assert all('\x00' not in line for line in output)
    else:
        from tui_gateway import server
        session = {'session_key': 's1', 'pending_title': 'old'}
        monkeypatch.setattr(server, '_sess_nowait', lambda *_: (session, None))
        monkeypatch.setattr(server, '_get_db', lambda: db)
        result = server.handle_request({'id': 1, 'method': 'session.title', 'params': {'session_id': 's1', 'title': raw}})
        assert result['result'] == {'title': 'Forecast desk', 'pending': not exists}
        assert session['pending_title'] == (None if exists else 'Forecast desk')
    assert db.get_session_title('s1') == ('Forecast desk' if exists else None)


def test_pending_titles_obey_uniqueness_and_cannot_clear_existing_title(db):
    db.create_session('s1', source='cli')
    db.set_session_title('s1', 'Reserved')
    with pytest.raises(ValueError, match='already in use'):
        set_session_title(db, 'missing', 'Reserved\x00')
    with pytest.raises(ValueError, match='empty after cleanup'):
        set_session_title(db, 's1', '\x00')
    assert db.get_session_title('s1') == 'Reserved'
    assert db.get_session('missing') is None
