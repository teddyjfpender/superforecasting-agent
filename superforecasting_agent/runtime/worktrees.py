"""Preserve local work while cleaning up CLI worktrees and branches."""

import logging
from pathlib import Path
from typing import Dict, Optional

from .worktree_setup import (
    _FORECAST_WORKTREE_PREFIX,
    _LEGACY_WORKTREE_PREFIX,
    _FORECAST_WORKTREE_BRANCH_PREFIX,
    _LEGACY_WORKTREE_BRANCH_PREFIX,
)

logger = logging.getLogger("cli")

_active_worktree: Optional[Dict[str, str]] = None


def _worktree_has_unpushed_commits(worktree_path: str, timeout: int = 10) -> bool:
    """Return whether a worktree has commits not reachable from any remote branch.

    ``git log HEAD --not --remotes`` compares against remote-tracking refs under
    ``refs/remotes/*``. If a repo has no remote-tracking refs yet, there is no
    usable remote baseline to compare against, so treat it as having no
    "unpushed" commits.
    """
    import subprocess

    try:
        remote_refs = subprocess.run(
            ["git", "for-each-ref", "--format=%(refname)", "refs/remotes"],
            capture_output=True, text=True, timeout=timeout, cwd=worktree_path,
        )
        if remote_refs.returncode != 0:
            return True
        if not remote_refs.stdout.strip():
            return False

        result = subprocess.run(
            ["git", "log", "--oneline", "HEAD", "--not", "--remotes"],
            capture_output=True, text=True, timeout=timeout, cwd=worktree_path,
        )
        if result.returncode != 0:
            return True
        return bool(result.stdout.strip())
    except Exception:
        return True


def _worktree_has_local_changes(worktree_path: str, timeout: int = 10) -> bool:
    """Preserve dirty or unreadable worktrees, including ignored local files."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--ignored"],
            capture_output=True, text=True, timeout=timeout, cwd=worktree_path,
        )
        return result.returncode != 0 or bool(result.stdout.strip())
    except Exception:
        return True


def _cleanup_worktree(info: Dict[str, str] = None) -> None:
    """Remove a worktree and its branch on exit.

    Preserve unpushed commits and local files. Cleanup failures leave the
    branch intact and must not be reported as successful removal.
    """
    global _active_worktree
    info = info or _active_worktree
    if not info:
        return

    import subprocess

    wt_path = info["path"]
    branch = info["branch"]
    repo_root = info["repo_root"]

    if not Path(wt_path).exists():
        return

    has_unpushed = _worktree_has_unpushed_commits(wt_path, timeout=10)
    has_local_changes = _worktree_has_local_changes(wt_path, timeout=10)

    if has_unpushed or has_local_changes:
        print(f"\n\033[33m⚠ Worktree has local work or could not be checked, keeping: {wt_path}\033[0m")
        print(f"  After reviewing local work: git worktree remove {wt_path}")
        _active_worktree = None
        return

    # Let Git refuse removal if new work appeared after the checks.
    try:
        removed = subprocess.run(
            ["git", "worktree", "remove", wt_path],
            capture_output=True, text=True, timeout=15, cwd=repo_root,
        )
        if removed.returncode != 0:
            logger.warning("Worktree removal failed: %s", removed.stderr.strip())
            return
    except Exception as e:
        logger.debug("Failed to remove worktree: %s", e)
        return

    # Delete the branch
    try:
        subprocess.run(
            ["git", "branch", "-d", branch],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
    except Exception as e:
        logger.debug("Failed to delete branch %s: %s", branch, e)

    _active_worktree = None
    print(f"\033[32m✓ Worktree cleaned up: {wt_path}\033[0m")


def _prune_stale_worktrees(repo_root: str, max_age_hours: int = 24) -> None:
    """Remove stale worktrees and orphaned branches on startup.

    Age-based tiers:
    - Under max_age_hours (24h): skip — session may still be active.
    - Older: remove only clean worktrees without unpushed commits.
    - Age never overrides preservation of local work.

    Also prunes orphaned forecast worktree branches, legacy ``hermes/*``
    worktree branches, and ``pr-*`` local branches that have no corresponding
    worktree.
    """
    import subprocess
    import time

    worktrees_dir = Path(repo_root) / ".worktrees"
    if not worktrees_dir.exists():
        _prune_orphaned_branches(repo_root)
        return

    now = time.time()
    soft_cutoff = now - (max_age_hours * 3600)       # 24h default

    worktree_prefixes = (_FORECAST_WORKTREE_PREFIX, _LEGACY_WORKTREE_PREFIX)
    for entry in worktrees_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith(worktree_prefixes):
            continue

        # Check age
        try:
            mtime = entry.stat().st_mtime
            if mtime > soft_cutoff:
                continue  # Too recent — skip
        except Exception:
            continue

        if (_worktree_has_unpushed_commits(str(entry), timeout=5)
                or _worktree_has_local_changes(str(entry), timeout=5)):
            continue

        # Safe to remove
        try:
            branch_result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, timeout=5, cwd=str(entry),
            )
            branch = branch_result.stdout.strip()

            removed = subprocess.run(
                ["git", "worktree", "remove", str(entry)],
                capture_output=True, text=True, timeout=15, cwd=repo_root,
            )
            if removed.returncode != 0:
                logger.debug("Skipped worktree removal: %s", removed.stderr.strip())
                continue
            if branch:
                subprocess.run(
                    ["git", "branch", "-d", branch],
                    capture_output=True, text=True, timeout=10, cwd=repo_root,
                )
            logger.debug("Pruned stale worktree: %s", entry.name)
        except Exception as e:
            logger.debug("Failed to prune worktree %s: %s", entry.name, e)

    _prune_orphaned_branches(repo_root)


def _prune_orphaned_branches(repo_root: str) -> None:
    """Delete generated worktree and ``pr-*`` branches with no worktree.

    Forecast-prefixed branches are created by ``superforecasting-agent chat --worktree``.
    Legacy ``hermes/hermes-*`` branches are still recognized so existing fork
    transition checkouts do not leak old worktree refs.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        if result.returncode != 0:
            return
        all_branches = [b.strip() for b in result.stdout.strip().split("\n") if b.strip()]
    except Exception:
        return

    # Collect branches that are actively checked out in a worktree
    active_branches: set = set()
    try:
        wt_result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True, text=True, timeout=10, cwd=repo_root,
        )
        for line in wt_result.stdout.split("\n"):
            if line.startswith("branch refs/heads/"):
                active_branches.add(line.split("branch refs/heads/", 1)[-1].strip())
    except Exception:
        return  # Can't determine active branches — bail

    # Also protect the currently checked-out branch and main
    try:
        head_result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5, cwd=repo_root,
        )
        current = head_result.stdout.strip()
        if current:
            active_branches.add(current)
    except Exception:
        pass
    active_branches.add("main")

    orphaned = [
        b for b in all_branches
        if b not in active_branches
        and (
            b.startswith(_FORECAST_WORKTREE_BRANCH_PREFIX)
            or b.startswith(_LEGACY_WORKTREE_BRANCH_PREFIX)
            or b.startswith("pr-")
        )
    ]

    if not orphaned:
        return

    # Delete in batches
    for i in range(0, len(orphaned), 50):
        batch = orphaned[i:i + 50]
        try:
            subprocess.run(
                ["git", "branch", "-d"] + batch,
                capture_output=True, text=True, timeout=30, cwd=repo_root,
            )
        except Exception as e:
            logger.debug("Failed to prune orphaned branches: %s", e)

    logger.debug("Checked %d orphaned branches for safe deletion", len(orphaned))
