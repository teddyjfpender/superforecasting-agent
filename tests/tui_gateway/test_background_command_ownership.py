"""Native background commands touch only their host session's registry entries."""
from unittest.mock import Mock

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tools import async_delegation, process_registry as processes
from tui_gateway import server


@pytest.fixture
def background(monkeypatch):
    registry = processes.ProcessRegistry()
    monkeypatch.setattr(processes, 'process_registry', registry)
    calls = []
    records = {}
    for owner in ('desk', 'other', ''):
        registry._running[owner] = processes.ProcessSession(
            id=owner, command=f'command-{owner}', session_key=owner,
        )
        records[owner] = {
            'delegation_id': owner, 'session_key': owner, 'status': 'running',
            'goal': f'goal-{owner}', 'interrupt_fn': lambda key=owner: calls.append(key),
        }
    monkeypatch.setattr(async_delegation, '_records', records)
    killed = []
    def kill(pid):
        killed.append(pid)
        registry._running[pid].exited = True
        return {'status': 'killed'}
    monkeypatch.setattr(registry, 'kill_process', kill)
    monkeypatch.setattr(server, '_host', RuntimeHost())
    server._host.sessions.register('runtime', {'session_key': 'desk', 'history': [], 'running': False})
    monkeypatch.setattr(server, '_load_cfg', lambda: {})
    monkeypatch.setattr(server, '_start_agent_build', Mock(side_effect=AssertionError('agent constructed')))
    return registry, records, killed, calls


def slash(command):
    return server.handle_request({'id': 1, 'method': 'slash.exec',
                                 'params': {'session_id': 'runtime', 'command': command}})


def test_native_inspection_and_stop_share_session_scope(background):
    registry, records, killed, interrupted = background
    output = slash('/agents')['result']['output']
    assert 'command-desk' in output and 'goal-desk' in output
    assert 'other' not in output
    assert 'Running processes: 1' in output
    output = slash('/stop')['result']['output']
    assert 'Stopped 1' in output and 'Interrupted 1' in output
    assert killed == ['desk']
    assert interrupted == ['desk']
    assert registry._running['other'].exited is False
    assert registry._running[''].exited is False
    # Signals do not pretend asynchronous work has completed.
    assert records['desk']['status'] == 'running'


def test_missing_session_owner_cannot_expand_to_global_scope(background):
    _, _, killed, interrupted = background
    server._host.sessions['runtime']['session_key'] = ''
    assert slash('/stop')['error']['code'] == 4004
    assert killed == interrupted == []


def test_registry_empty_scope_is_exact_and_none_preserves_global_scope(background):
    registry, _, killed, interrupted = background
    assert len(registry.list_sessions(session_key='')) == 1
    assert len(async_delegation.list_async_delegations(session_key='')) == 1
    assert registry.kill_all(session_key='') == 1
    assert async_delegation.interrupt_all(session_key='') == 1
    assert killed == interrupted == ['']
    assert len(registry.list_sessions()) == 3
    assert len(async_delegation.list_async_delegations()) == 3


def test_failed_interrupt_is_reported_without_false_completion(background):
    _, records, _, _ = background
    records['desk']['interrupt_fn'] = Mock(side_effect=RuntimeError('fixture failure'))
    output = slash('/stop')['result']['output']
    assert 'Interrupted 0' in output
    assert 'could not be interrupted' in output
    assert records['desk']['status'] == 'running'


def test_direct_dispatch_and_alias_inspect_the_live_session(background):
    server._host.sessions['runtime']['running'] = True
    response = server.handle_request({'id': 2, 'method': 'command.dispatch',
                                     'params': {'session_id': 'runtime', 'name': 'tasks'}})
    assert response['result']['type'] == 'exec'
    assert 'Agent: running' in response['result']['output']
    assert response['result']['output'] == slash('/agents')['result']['output']
    assert server._host.sessions['runtime']['running'] is True


def test_classic_cli_uses_shared_operations_with_standalone_scope(background, capsys, monkeypatch):
    import cli as cli_module
    from cli import HermesCLI

    # The process-wide console can retain another test's stdout wrapper. This
    # test checks command ownership/output, not prompt_toolkit capture plumbing.
    monkeypatch.setattr(cli_module, "_cprint", print)

    cli = HermesCLI.__new__(HermesCLI)
    cli._agent_running = False
    cli._handle_agents_command()
    output = capsys.readouterr().out
    assert 'Running processes: 3' in output
    cli._handle_stop_command()
    output = capsys.readouterr().out
    assert 'Stopped 3' in output and 'Interrupted 3' in output
    assert set(background[2]) == set(background[3]) == {'desk', 'other', ''}


def test_legacy_process_stop_requires_and_obeys_session_scope(background):
    _, _, killed, interrupted = background
    denied = server.handle_request({'id': 3, 'method': 'process.stop', 'params': {}})
    assert 'error' in denied
    assert killed == []
    response = server.handle_request({'id': 4, 'method': 'process.stop',
                                     'params': {'session_id': 'runtime'}})
    assert response['result']['killed'] == 1
    assert killed == ['desk']
    assert interrupted == []
