"""Shared goal commands preserve durable transitions and detached results."""

from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from superforecasting_agent.application.goals import execute_goal
from superforecasting_agent.runtime.goals import GoalManager
from superforecasting_agent.storage.session import SessionDB


@pytest.mark.parametrize('clear_alias', ['clear', 'STOP', ' done '])
def test_goal_commands_update_the_same_durable_session(tmp_path, monkeypatch, clear_alias):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    database = SessionDB()
    try:
        with GoalManager('shared', default_max_turns=7, database_provider=lambda: database) as manager:
            with GoalManager('shared', database_provider=lambda: database) as observer:
                assert execute_goal(manager, '  ').action == 'status'
                assert execute_goal(manager, ' PAUSE ').state is None
                result = execute_goal(manager, '  Check publication dates  ')
                assert result.action == 'set'
                assert result.state.goal == 'Check publication dates'
                assert result.state.max_turns == 7
                assert observer.state.goal == result.state.goal
                assert execute_goal(manager, 'Pause').action == 'pause'
                assert observer.state.status == 'paused'
                assert execute_goal(manager, 'RESUME').action == 'resume'
                assert observer.state.status == 'active'
                assert execute_goal(manager, clear_alias).had_goal is True
                assert observer.has_goal() is False
                assert execute_goal(manager, clear_alias).had_goal is False
                # Returned state remains useful after the manager has changed.
                assert result.state.goal == 'Check publication dates'
                with pytest.raises(FrozenInstanceError):
                    result.state.goal = 'changed'
    finally:
        database.close()


def test_failed_goal_mutation_is_not_replayed_or_reported_as_success():
    manager = Mock()
    manager.set.side_effect = RuntimeError('storage unavailable')
    with pytest.raises(RuntimeError, match='storage unavailable'):
        execute_goal(manager, 'Check publication dates')
    manager.set.assert_called_once_with('Check publication dates')
    manager.pause.assert_not_called()
    manager.resume.assert_not_called()
    manager.clear.assert_not_called()


def test_classic_cli_uses_shared_transitions_and_queues_only_goal_creation(tmp_path, monkeypatch):
    import queue
    from types import SimpleNamespace
    from superforecasting_agent.runtime import goal_commands

    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    output = []
    monkeypatch.setattr(goal_commands, '_cprint', output.append)
    database = SessionDB()
    try:
        with GoalManager('classic', database_provider=lambda: database) as manager:
            cli = SimpleNamespace(_get_goal_manager=lambda: manager, _pending_input=queue.Queue())
            goal_commands._handle_goal_command(cli, '/goal Check source revisions')
            assert cli._pending_input.get_nowait() == 'Check source revisions'
            assert manager.state.goal == 'Check source revisions'
            goal_commands._handle_goal_command(cli, '/goal PAUSE')
            assert manager.state.status == 'paused'
            goal_commands._handle_goal_command(cli, '/goal resume')
            assert manager.state.status == 'active'
            goal_commands._handle_goal_command(cli, '/goal done')
            assert not manager.has_goal()
            assert cli._pending_input.empty()
            assert any('Goal cleared' in line for line in output)
    finally:
        database.close()
