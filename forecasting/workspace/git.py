"""Conservative argv-only Git operations for managed forecast workspaces."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from hermes_constants import get_hermes_home

from forecasting.models import ValidationError


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str
    returncode: int


class ManagedGit:
    def __init__(self, *, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str | Path | None = None,
        check: bool = True,
    ) -> GitResult:
        if not args or any(not isinstance(value, str) for value in args):
            raise ValidationError("git arguments must be a non-empty string sequence")
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        completed = subprocess.run(
            ["git", *args],
            cwd=None if cwd is None else Path(cwd),
            env=env,
            text=True,
            capture_output=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        result = GitResult(completed.stdout, completed.stderr, completed.returncode)
        if check and completed.returncode:
            diagnostic = (completed.stderr or completed.stdout).strip().splitlines()
            message = diagnostic[-1] if diagnostic else "git command failed"
            raise ValidationError(f"git {args[0]} failed: {message[:500]}")
        return result

    def clone(
        self,
        source: str,
        destination: str | Path,
        *,
        branch: str | None = None,
    ) -> Path:
        destination = Path(destination).expanduser()
        if destination.exists() and any(destination.iterdir()):
            raise ValidationError(f"clone destination is not empty: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--no-tags"]
        if branch:
            args.extend(["--branch", branch])
        args.extend([source, str(destination)])
        self.run(args)
        return destination

    def status(self, checkout: str | Path) -> dict[str, object]:
        result = self.run(["status", "--porcelain=v2", "--branch"], cwd=checkout)
        lines = result.stdout.splitlines()
        branch = next(
            (line.removeprefix("# branch.head ") for line in lines if line.startswith("# branch.head ")),
            None,
        )
        upstream = next(
            (
                line.removeprefix("# branch.upstream ")
                for line in lines
                if line.startswith("# branch.upstream ")
            ),
            None,
        )
        changes = [line for line in lines if not line.startswith("# ")]
        return {"branch": branch, "upstream": upstream, "dirty": bool(changes), "changes": changes}

    def pull_ff_only(self, checkout: str | Path, *, remote: str = "origin") -> dict[str, object]:
        status = self.status(checkout)
        if status["dirty"]:
            raise ValidationError("managed checkout is dirty; regenerate or reconcile before pulling")
        self.run(["fetch", "--prune", "--no-tags", remote], cwd=checkout)
        upstream = status.get("upstream")
        if not upstream:
            raise ValidationError("managed checkout has no upstream branch")
        ancestor = self.run(
            ["merge-base", "--is-ancestor", "HEAD", str(upstream)],
            cwd=checkout,
            check=False,
        )
        if ancestor.returncode != 0:
            raise ValidationError("managed checkout diverged or remote history was rewritten")
        self.run(["merge", "--ff-only", str(upstream)], cwd=checkout)
        return self.status(checkout)


def managed_checkout_path(workspace_id: str) -> Path:
    if not _SAFE_ID.fullmatch(str(workspace_id or "")):
        raise ValidationError("workspace_id contains unsafe path characters")
    return get_hermes_home() / "workspaces" / workspace_id / "repository"


__all__ = ["GitResult", "ManagedGit", "managed_checkout_path"]
