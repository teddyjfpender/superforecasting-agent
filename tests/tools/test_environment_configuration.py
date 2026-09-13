"""Terminal and file entrypoints must construct the same configured sandbox."""

from unittest.mock import Mock

import pytest

from tools import file_tools, terminal_tool
from tools.environments.configuration import environment_creation_options


@pytest.mark.parametrize('kind', ['local', 'ssh', 'docker', 'singularity', 'modal', 'daytona', 'vercel_sandbox'])
def test_creation_options_match_across_file_and_terminal(monkeypatch, tmp_path, kind):
    config = {
        'env_type': kind, 'cwd': str(tmp_path), 'timeout': 19,
        'docker_image': 'docker-default', 'singularity_image': 'singularity-default',
        'modal_image': 'modal-default', 'daytona_image': 'daytona-default',
        'modal_mode': 'image', 'docker_env': {'FIXTURE': 'value'},
        'docker_extra_args': ['--read-only'], 'docker_volumes': ['/fixture:/fixture:ro'],
        'ssh_host': 'fixture-host', 'ssh_persistent': True, 'local_persistent': True,
    }
    overrides = {f'{kind}_image': 'override-image', 'cwd': str(tmp_path / 'override')}
    monkeypatch.setattr(terminal_tool, '_resolve_container_task_id', lambda task: task)
    monkeypatch.setattr(terminal_tool, '_get_env_config', lambda: config)
    monkeypatch.setattr(terminal_tool, '_task_env_overrides', {'task': overrides})
    monkeypatch.setattr(terminal_tool, '_active_environments', {})
    monkeypatch.setattr(terminal_tool, '_last_activity', {})
    monkeypatch.setattr(terminal_tool, '_creation_locks', {})
    monkeypatch.setattr(file_tools, '_file_ops_cache', {})
    monkeypatch.setattr(terminal_tool, '_start_cleanup_thread', lambda: None)
    monkeypatch.setattr(terminal_tool, '_check_disk_usage_warning', lambda: None)
    factory = Mock(side_effect=RuntimeError('fixture captured creation'))
    monkeypatch.setattr(terminal_tool, '_create_environment', factory)
    terminal_tool.terminal_tool('echo fixture', task_id='task', force=True)
    factory.assert_called_once()
    terminal_options = factory.call_args.kwargs
    with pytest.raises(RuntimeError, match='fixture captured creation'):
        file_tools._get_file_ops('task')
    assert factory.call_count == 2
    assert factory.call_args.kwargs == terminal_options
    assert terminal_options['cwd'] == overrides['cwd']
    if kind in {'docker', 'singularity', 'modal', 'daytona', 'vercel_sandbox'}:
        assert terminal_options['container_config']['modal_mode'] == 'image'
        assert terminal_options['container_config']['docker_env'] == {'FIXTURE': 'value'}
        assert terminal_options['container_config']['docker_extra_args'] == ['--read-only']


def test_creation_options_do_not_share_mutable_settings():
    config = {'env_type': 'docker', 'docker_image': 'fixture', 'cwd': '/workspace',
              'timeout': 10, 'docker_env': {'FIXTURE': 'old'}, 'docker_extra_args': []}
    options = environment_creation_options(config, {}, task_id='task', timeout=3)
    options['container_config']['docker_env']['FIXTURE'] = 'changed'
    options['container_config']['docker_extra_args'].append('--read-only')
    assert config['docker_env'] == {'FIXTURE': 'old'}
    assert config['docker_extra_args'] == []
    assert options['timeout'] == 3
