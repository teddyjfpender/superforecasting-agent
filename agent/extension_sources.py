"""Ordered, revision-locked Git extension sources.

Each source is resolved to an immutable checkout under the active forecast
home. Consumers reuse the existing plugin/skill/workflow discovery surfaces;
this module only owns safe synchronization and the revision lock.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from superforecasting_agent.constants import get_agent_home


_GITHUB_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCP_REPO = re.compile(r"^git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+$")
_SYNC_LOCK = threading.Lock()
_CACHE_KEY = ""
_CACHE: list["ExtensionCheckout"] = []


@dataclass(frozen=True)
class ExtensionCheckout:
    repo: str
    requested_ref: str
    revision: str
    root: Path

    def surface(self, name: str) -> Path | None:
        relative = {
            "plugins": "plugins",
            "skills": "skills",
            "workflows": "workflows",
            "prompts": "prompts",
        }.get(name)
        if relative is None:
            return None
        path = self.root / relative
        if name == "skills" and not path.is_dir():
            path = self.root / ".agents" / "skills"
        return path if path.is_dir() else None


def get_extension_surface_paths(
    name: str, config: dict[str, Any] | None = None,
) -> list[Path]:
    """Return ordered existing directories for one extension surface."""
    if name not in {"plugins", "skills", "workflows", "prompts"}:
        raise ValueError(f"unknown extension surface {name!r}")
    return [
        path
        for checkout in sync_extension_sources(config)
        if (path := checkout.surface(name)) is not None
    ]


def load_extension_prompts(config: dict[str, Any] | None = None) -> str:
    """Load ordered Markdown prompt fragments with a bounded total size."""
    blocks: list[str] = []
    remaining = 256 * 1024
    for directory in get_extension_surface_paths("prompts", config):
        for path in sorted(directory.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            encoded = content.encode("utf-8")
            if len(encoded) > remaining:
                raise ValueError("Extension prompts exceed the 256 KiB safety limit")
            remaining -= len(encoded)
            if content.strip():
                blocks.append(f"# Organization guidance: {path.name}\n\n{content.strip()}")
    return "\n\n".join(blocks)


def _repo_url(repo: str) -> str:
    if _GITHUB_REPO.fullmatch(repo):
        return f"https://github.com/{repo}.git"
    if repo.startswith("git@"):
        if not _SCP_REPO.fullmatch(repo):
            raise ValueError(f"invalid extension repo {repo!r}")
        return repo
    if repo.startswith(("https://", "ssh://", "file://")):
        parsed = urlsplit(repo)
        if parsed.password or (parsed.scheme == "https" and parsed.username):
            raise ValueError("extension repo URLs must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError("extension repo URLs must not contain query or fragment data")
        return repo
    raise ValueError(f"invalid extension repo {repo!r}")


def _validate_ref(ref: str) -> str:
    if ref.startswith("-") or len(ref) > 256 or any(ord(char) < 32 for char in ref):
        raise ValueError(f"invalid extension ref {ref!r}")
    return ref


def _run_git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    return result.stdout.strip()


def _source_slug(index: int, repo: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", repo).strip("-")
    return f"{index:02d}-{name or 'extension'}"


def sync_extension_sources(config: dict[str, Any] | None = None) -> list[ExtensionCheckout]:
    """Resolve configured sources in order and atomically update the lockfile."""
    if config is None:
        from superforecasting_agent.runtime.config import load_config

        config = load_config()
    extension_cfg = config.get("extensions") if isinstance(config, dict) else None
    sources = extension_cfg.get("sources", []) if isinstance(extension_cfg, dict) else []
    if not isinstance(sources, list) or not sources:
        return []
    base = get_agent_home() / "extensions"
    cache_key = f"{base}:{json.dumps(sources, sort_keys=True, default=str)}"

    global _CACHE_KEY, _CACHE
    if cache_key == _CACHE_KEY and _CACHE and all(item.root.is_dir() for item in _CACHE):
        return list(_CACHE)

    repos_dir = base / "repos"
    repos_dir.mkdir(parents=True, exist_ok=True)
    resolved: list[ExtensionCheckout] = []

    with _SYNC_LOCK:
        for index, raw in enumerate(sources):
            if not isinstance(raw, dict):
                raise ValueError(f"extensions.sources[{index}] must be a mapping")
            repo = str(raw.get("repo") or "").strip()
            ref = str(raw.get("ref") or "").strip()
            if not repo or not ref:
                raise ValueError(f"extensions.sources[{index}] requires repo and ref")
            ref = _validate_ref(ref)
            url = _repo_url(repo)
            slug = _source_slug(index, repo)
            checkout_root = repos_dir / slug

            with tempfile.TemporaryDirectory(prefix=f".{slug}-", dir=repos_dir) as tmp:
                staging = Path(tmp) / "checkout"
                _run_git("clone", "--no-checkout", "--filter=blob:none", url, str(staging))
                _run_git("checkout", "--detach", ref, cwd=staging)
                revision = _run_git("rev-parse", "HEAD", cwd=staging)
                if not re.fullmatch(r"[0-9a-f]{40}", revision):
                    raise RuntimeError(f"git returned invalid revision for {repo}: {revision!r}")
                _run_git("config", "--unset-all", "remote.origin.url", cwd=staging)
                shutil.rmtree(staging / ".git", ignore_errors=True)
                replacement = repos_dir / f".{slug}.ready"
                if replacement.exists():
                    shutil.rmtree(replacement)
                staging.rename(replacement)
                previous = repos_dir / f".{slug}.previous"
                if previous.exists():
                    shutil.rmtree(previous)
                if checkout_root.exists():
                    checkout_root.rename(previous)
                try:
                    replacement.rename(checkout_root)
                except BaseException:
                    if previous.exists() and not checkout_root.exists():
                        previous.rename(checkout_root)
                    raise
                shutil.rmtree(previous, ignore_errors=True)

            resolved.append(ExtensionCheckout(repo, ref, revision, checkout_root))

        lock_data = {
            "version": 1,
            "sources": [
                {
                    "repo": item.repo,
                    "requested_ref": item.requested_ref,
                    "revision": item.revision,
                    "path": str(item.root),
                }
                for item in resolved
            ],
        }
        base.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".extensions-lock-", dir=base)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(lock_data, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, base / "extensions.lock.json")
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
    _CACHE_KEY = cache_key
    _CACHE = list(resolved)
    return resolved
