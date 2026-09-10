"""Exercise real worktree creation, cleanup, includes, and branch pruning."""

import os
from pathlib import Path
import subprocess
import time

import pytest

from superforecasting_agent.runtime import worktree_setup as setup
from superforecasting_agent.runtime import worktrees as cleanup


def git(repo, *args):
    return subprocess.run(
        ['git', *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / 'repo'
    target.mkdir()
    git(target, 'init', '-b', 'main')
    git(target, 'config', 'user.email', 'test@example.test')
    git(target, 'config', 'user.name', 'Test')
    (target / 'README.md').write_text('base')
    git(target, 'add', 'README.md')
    git(target, 'commit', '-m', 'base')
    git(target, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    return target


@pytest.mark.parametrize('subdirectory', [False, True])
def test_detects_repository(repo, monkeypatch, subdirectory):
    cwd = repo / 'nested' if subdirectory else repo
    cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(cwd)
    assert Path(setup._git_repo_root()).resolve() == repo.resolve()


def test_outside_repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert setup._git_repo_root() is None
    assert setup._setup_worktree() is None


def test_repository_without_commits(tmp_path):
    git(tmp_path, 'init')
    assert setup._setup_worktree(str(tmp_path)) is None


def test_creation_isolates_files_and_branches(repo):
    first = setup._setup_worktree(str(repo))
    second = setup._setup_worktree(str(repo))
    assert first and second
    assert first['path'] != second['path']
    assert first['branch'] != second['branch']
    assert first['branch'].startswith('forecast/forecast-')
    assert git(first['path'], 'branch', '--show-current') == first['branch']
    assert (Path(first['path']) / 'README.md').read_text() == 'base'
    (Path(first['path']) / 'README.md').write_text('local')
    assert (repo / 'README.md').read_text() == 'base'
    assert (Path(second['path']) / 'README.md').read_text() == 'base'
    assert (repo / '.gitignore').read_text().splitlines().count('.worktrees/') == 1


@pytest.mark.parametrize('remote_state', ['tracking', 'no-remote', 'remote-without-tracking'])
def test_clean_cleanup_removes_worktree_and_branch(repo, remote_state):
    if remote_state != 'tracking':
        git(repo, 'update-ref', '-d', 'refs/remotes/origin/main')
    if remote_state == 'remote-without-tracking':
        git(repo, 'remote', 'add', 'origin', 'https://example.test/repo.git')
    info = setup._setup_worktree(str(repo))
    cleanup._cleanup_worktree(info)
    assert not Path(info['path']).exists()
    assert info['branch'] not in git(repo, 'branch', '--format=%(refname:short)').splitlines()


def test_cleanup_missing_path_is_harmless(repo):
    cleanup._cleanup_worktree({'path': str(repo / 'missing'), 'branch': 'missing', 'repo_root': str(repo)})
    assert git(repo, 'branch', '--show-current') == 'main'


def test_include_copies_nested_files_and_skips_comments(repo):
    (repo / 'config').mkdir()
    (repo / 'config' / 'local.env').write_text('EXAMPLE=value')
    (repo / '.worktreeinclude').write_text('# comment\n\n config/local.env \n# ignored\n')
    info = setup._setup_worktree(str(repo))
    copied = Path(info['path']) / 'config' / 'local.env'
    assert copied.read_text() == 'EXAMPLE=value'
    copied.write_text('changed')
    assert (repo / 'config' / 'local.env').read_text() == 'EXAMPLE=value'


@pytest.mark.skipif(os.name == "nt", reason="Directory symlink privilege is platform-dependent")
def test_include_links_directory(repo):
    directory = repo / 'local-assets'
    directory.mkdir()
    (directory / 'sample.txt').write_text('asset')
    (repo / '.worktreeinclude').write_text('local-assets\n')
    info = setup._setup_worktree(str(repo))
    linked = Path(info['path']) / 'local-assets'
    assert linked.is_symlink()
    assert linked.resolve() == directory.resolve()
    assert (linked / 'sample.txt').read_text() == 'asset'


@pytest.mark.parametrize('age_hours, retained', [(0, True), (30, False), (96, False)])
def test_stale_cleanup_respects_age_for_clean_worktrees(repo, age_hours, retained):
    info = setup._setup_worktree(str(repo))
    target = Path(info['path'])
    timestamp = time.time() - age_hours * 3600
    os.utime(target, (timestamp, timestamp))
    cleanup._prune_stale_worktrees(str(repo))
    assert target.exists() is retained


@pytest.mark.parametrize('branch', ['forecast/forecast-old', 'hermes/hermes-old', 'pr-123'])
def test_orphan_cleanup_removes_merged_generated_branches(repo, branch):
    git(repo, 'branch', branch)
    cleanup._prune_orphaned_branches(str(repo))
    assert branch not in git(repo, 'branch', '--format=%(refname:short)').splitlines()
    assert git(repo, 'branch', '--show-current') == 'main'


def test_orphan_cleanup_preserves_active_and_unrelated_branches(repo):
    info = setup._setup_worktree(str(repo))
    git(repo, 'branch', 'my-work')
    cleanup._prune_orphaned_branches(str(repo))
    branches = git(repo, 'branch', '--format=%(refname:short)').splitlines()
    assert {info['branch'], 'my-work', 'main'} <= set(branches)
