"""Conservative argv-only Git operations for managed forecast workspaces."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Sequence
from urllib.parse import urlparse

from hermes_constants import get_hermes_home

from forecasting.models import ValidationError


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
CredentialCallback = Callable[[], tuple[str, str]]
_BLOCKED_LOCAL_CONFIG = re.compile(
    r"^(?:filter\.|merge\.|include\.|includeif\.|core\.hookspath$|"
    r"core\.sshcommand$|credential\.)",
    re.I,
)
_SAFE_CONFIG = (
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.attributesFile=/dev/null",
    "-c", "submodule.recurse=false",
    "-c", "protocol.ext.allow=never",
    "-c", "credential.helper=",
)


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
        credential_callback: CredentialCallback | None = None,
    ) -> GitResult:
        if not args or any(not isinstance(value, str) for value in args):
            raise ValidationError("git arguments must be a non-empty string sequence")
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_SSH_COMMAND": "false",
        }
        with _askpass_env(env, credential_callback) as git_env:
            completed = subprocess.run(
                ["git", *_SAFE_CONFIG, *args],
                cwd=None if cwd is None else Path(cwd),
                env=git_env,
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
        credential_callback: CredentialCallback | None = None,
    ) -> Path:
        _validate_remote(source)
        destination = Path(destination).expanduser()
        if destination.exists() and any(destination.iterdir()):
            raise ValidationError(f"clone destination is not empty: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        args = ["clone", "--no-tags", "--no-recurse-submodules", "--no-checkout"]
        if branch:
            _validate_branch(branch)
            args.extend(["--branch", branch])
        args.extend([source, str(destination)])
        self.run(args, credential_callback=credential_callback)
        self._validate_checkout_config(destination)
        self._validate_origin(destination)
        self.run(
            ["checkout", "--force", branch or "HEAD"],
            cwd=destination,
            credential_callback=credential_callback,
        )
        return destination

    def status(self, checkout: str | Path) -> dict[str, object]:
        self._validate_checkout_config(checkout)
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

    def pull_ff_only(
        self,
        checkout: str | Path,
        *,
        remote: str = "origin",
        credential_callback: CredentialCallback | None = None,
    ) -> dict[str, object]:
        if not _SAFE_ID.fullmatch(remote):
            raise ValidationError("remote name contains unsafe characters")
        self._validate_checkout_config(checkout)
        self._validate_origin(checkout, remote=remote)
        status = self.status(checkout)
        if status["dirty"]:
            raise ValidationError("managed checkout is dirty; regenerate or reconcile before pulling")
        self.run(
            ["fetch", "--prune", "--no-tags", "--no-recurse-submodules", remote],
            cwd=checkout,
            credential_callback=credential_callback,
        )
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

    def _validate_origin(self, checkout: str | Path, *, remote: str = "origin") -> None:
        result = self.run(["remote", "get-url", remote], cwd=checkout)
        _validate_remote(result.stdout.strip())

    def _validate_checkout_config(self, checkout: str | Path) -> None:
        result = self.run(
            ["config", "--local", "--name-only", "--list"],
            cwd=checkout,
            check=False,
        )
        if result.returncode:
            raise ValidationError("managed checkout Git configuration is unreadable")
        blocked = sorted(
            key for key in result.stdout.splitlines() if _BLOCKED_LOCAL_CONFIG.search(key)
        )
        if blocked:
            raise ValidationError(
                "managed checkout contains unsafe Git configuration: " + ", ".join(blocked)
            )


def _validate_branch(branch: str) -> None:
    if not branch or branch.startswith("-") or any(
        marker in branch for marker in ("..", "~", "^", ":", "\\", " ")
    ):
        raise ValidationError("branch contains unsafe Git ref characters")


def _validate_remote(source: str) -> None:
    if not source or "\n" in source or "\r" in source:
        raise ValidationError("Git remote is invalid")
    local = Path(source).expanduser()
    if local.exists():
        return
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValidationError("managed Git remotes must be HTTPS URLs or existing local paths")


@contextmanager
def _askpass_env(
    base: dict[str, str], callback: CredentialCallback | None
) -> Iterator[dict[str, str]]:
    if callback is None:
        yield base
        return
    username, password = callback()
    if not username or not password:
        raise ValidationError("Git credential callback returned an empty credential")
    with tempfile.TemporaryDirectory(prefix="forecast-git-askpass-") as directory:
        script = Path(directory) / "askpass"
        script.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            "prompt = ' '.join(sys.argv[1:]).lower()\n"
            "print(os.environ['SFA_GIT_USERNAME'] if 'username' in prompt else "
            "os.environ['SFA_GIT_PASSWORD'])\n",
            encoding="utf-8",
        )
        script.chmod(0o700)
        yield {
            **base,
            "GIT_ASKPASS": str(script),
            "GIT_ASKPASS_REQUIRE": "force",
            "SFA_GIT_USERNAME": username,
            "SFA_GIT_PASSWORD": password,
        }


def managed_checkout_path(workspace_id: str) -> Path:
    if not _SAFE_ID.fullmatch(str(workspace_id or "")):
        raise ValidationError("workspace_id contains unsafe path characters")
    return get_hermes_home() / "workspaces" / workspace_id / "repository"


__all__ = ["CredentialCallback", "GitResult", "ManagedGit", "managed_checkout_path"]
