"""Automatic worktree cleanup must preserve local work at every age."""

import os
import subprocess
import time
from pathlib import Path

import pytest


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def worktree(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init')
    git(repo, 'config', 'user.email', 'test@example.test')
    git(repo, 'config', 'user.name', 'Test')
    (repo / 'tracked.txt').write_text('original')
    git(repo, 'add', 'tracked.txt')
    git(repo, 'commit', '-m', 'base')
    git(repo, 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    target = repo / '.worktrees' / 'forecast-preserve'
    git(repo, 'worktree', 'add', '-b', 'forecast/forecast-preserve', str(target))
    return {'repo_root': str(repo), 'path': str(target), 'branch': 'forecast/forecast-preserve'}


@pytest.mark.parametrize('mode', ['tracked', 'untracked', 'staged', 'ignored', 'committed'])
@pytest.mark.parametrize('action', ['exit', 'stale'])
def test_cleanup_preserves_local_work(worktree, mode, action):
    import cli

    target = Path(worktree['path'])
    filename = 'tracked.txt' if mode == 'tracked' else 'local.txt'
    content = target / filename
    content.write_text('keep this work')
    if mode == 'ignored':
        git_dir = Path(git(target, 'rev-parse', '--git-common-dir').stdout.strip())
        (git_dir / 'info' / 'exclude').write_text('local.txt\n')
    if mode in ('staged', 'committed'):
        git(target, 'add', filename)
    if mode == 'committed':
        git(target, 'add', filename)
        git(target, 'commit', '-m', 'local work')
    old = time.time() - 96 * 3600
    os.utime(target, (old, old))
    if action == 'exit':
        cli._cleanup_worktree(worktree)
    else:
        cli._prune_stale_worktrees(worktree['repo_root'])
    assert content.read_text() == 'keep this work'
    git(worktree['repo_root'], 'show-ref', '--verify', 'refs/heads/' + worktree['branch'])


def test_orphan_cleanup_preserves_unmerged_commit(worktree):
    import cli

    target = Path(worktree['path'])
    (target / 'local.txt').write_text('committed work')
    git(target, 'add', 'local.txt')
    git(target, 'commit', '-m', 'local work')
    commit = git(target, 'rev-parse', 'HEAD').stdout.strip()
    git(worktree['repo_root'], 'worktree', 'remove', str(target))
    cli._prune_orphaned_branches(worktree['repo_root'])
    assert git(worktree['repo_root'], 'rev-parse', worktree['branch']).stdout.strip() == commit


@pytest.mark.parametrize('action', ['exit', 'stale'])
def test_clean_worktree_is_removed(worktree, action):
    import cli

    target = Path(worktree['path'])
    old = time.time() - 96 * 3600
    os.utime(target, (old, old))
    if action == 'exit':
        cli._cleanup_worktree(worktree)
    else:
        cli._prune_stale_worktrees(worktree['repo_root'])
    assert not target.exists()


def test_failed_removal_keeps_branch(worktree, monkeypatch, capsys):
    import cli

    real_run = subprocess.run

    def fail_removal(command, **kwargs):
        if command[:3] == ['git', 'worktree', 'remove']:
            return subprocess.CompletedProcess(command, 1, '', 'worktree changed')
        return real_run(command, **kwargs)

    monkeypatch.setattr(subprocess, 'run', fail_removal)
    cli._cleanup_worktree(worktree)
    assert Path(worktree['path']).exists()
    git(worktree['repo_root'], 'show-ref', '--verify', 'refs/heads/' + worktree['branch'])
    assert 'cleaned up' not in capsys.readouterr().out
