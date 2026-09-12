"""All product goal consumers borrow their host's durable session store."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.runtime import goal_commands, goals


@pytest.fixture
def no_standalone(monkeypatch):
    factory = Mock(side_effect=AssertionError('hosted goal opened another database'))
    monkeypatch.setattr(goals, '_get_session_db', factory)
    monkeypatch.setattr('superforecasting_agent.runtime.config.load_config', lambda: {})
    yield factory
    factory.assert_not_called()


def database():
    return Mock(get_meta=Mock(return_value=None))


def test_cli_rebinds_goal_manager_without_closing_host_stores(no_standalone):
    first_db, second_db = database(), database()
    shell = SimpleNamespace(session_id='first', _session_db=first_db)
    first = goal_commands._get_goal_manager(shell)
    assert first._database is first_db
    assert goal_commands._get_goal_manager(shell) is first
    shell.session_id = 'second'
    second = goal_commands._get_goal_manager(shell)
    assert second._database is first_db
    with pytest.raises(RuntimeError, match='closed'):
        first.state
    shell._session_db = second_db
    third = goal_commands._get_goal_manager(shell)
    assert third._database is second_db
    assert third is not second
    first_db.close.assert_not_called()
    second_db.close.assert_not_called()
    shell._session_db = None
    assert goal_commands._get_goal_manager(shell) is None


def test_gateway_goal_lookup_borrows_store_and_fails_closed_without_it(no_standalone):
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner._session_db = database()
    runner._goal_max_turns_from_config = lambda: 7
    entry = SimpleNamespace(session_id='fixture')
    runner.session_store = Mock(get_or_create_session=Mock(return_value=entry))
    event = SimpleNamespace(source=object())
    manager, found = runner._get_goal_manager_for_event(event)
    assert found is entry
    assert manager._database is runner._session_db
    manager.close()
    runner._session_db.close.assert_not_called()
    assert not runner._goal_still_active_for_session('fixture')
    runner._session_db = None
    assert runner._get_goal_manager_for_event(event) == (None, None)
    assert not runner._goal_still_active_for_session('fixture')


@pytest.mark.asyncio
async def test_gateway_post_turn_with_missing_store_never_opens_fallback(no_standalone):
    from gateway.run import GatewayRunner
    runner = object.__new__(GatewayRunner)
    runner._session_db = None
    runner._goal_max_turns_from_config = lambda: 7
    await runner._post_turn_goal_continuation(
        session_entry=SimpleNamespace(session_id='fixture'),
        source=object(), final_response='finished turn',
    )
