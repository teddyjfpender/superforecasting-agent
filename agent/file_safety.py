"""Shared file safety rules used by both tools and ACP shims."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_WRITE_SAFE_ROOT_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_WRITE_SAFE_ROOT",
    "FORECAST_WRITE_SAFE_ROOT",
    "HERMES_WRITE_SAFE_ROOT",
)


def _hermes_home_path() -> Path:
    """Resolve the active agent home (profile-aware) without circular imports."""
    try:
        from hermes_constants import get_hermes_home  # local import to avoid cycles
        return get_hermes_home()
    except Exception:
        return Path(os.path.expanduser("~/.superforecasting-agent"))


def _hermes_root_path() -> Path:
    """Resolve the global agent root.

    In profile mode the active home is ``<root>/profiles/<name>``; the root
    holds the shared credential stores. Blocking both home and root means a
    profile run still can't read ``<root>/auth.json`` etc.
    """
    try:
        from hermes_constants import get_default_hermes_root  # local import to avoid cycles
        return get_default_hermes_root()
    except Exception:
        return _hermes_home_path()


def build_write_denied_paths(home: str) -> set[str]:
    """Return exact sensitive paths that must never be written."""
    hermes_home = _hermes_home_path()
    return {
        os.path.realpath(p)
        for p in [
            os.path.join(home, ".ssh", "authorized_keys"),
            os.path.join(home, ".ssh", "id_rsa"),
            os.path.join(home, ".ssh", "id_ed25519"),
            os.path.join(home, ".ssh", "config"),
            str(hermes_home / ".env"),
            os.path.join(home, ".bashrc"),
            os.path.join(home, ".zshrc"),
            os.path.join(home, ".profile"),
            os.path.join(home, ".bash_profile"),
            os.path.join(home, ".zprofile"),
            os.path.join(home, ".netrc"),
            os.path.join(home, ".pgpass"),
            os.path.join(home, ".npmrc"),
            os.path.join(home, ".pypirc"),
            "/etc/sudoers",
            "/etc/passwd",
            "/etc/shadow",
        ]
    }


def build_write_denied_prefixes(home: str) -> list[str]:
    """Return sensitive directory prefixes that must never be written."""
    return [
        os.path.realpath(p) + os.sep
        for p in [
            os.path.join(home, ".ssh"),
            os.path.join(home, ".aws"),
            os.path.join(home, ".gnupg"),
            os.path.join(home, ".kube"),
            "/etc/sudoers.d",
            "/etc/systemd",
            os.path.join(home, ".docker"),
            os.path.join(home, ".azure"),
            os.path.join(home, ".config", "gh"),
        ]
    ]


def get_safe_write_root() -> Optional[str]:
    """Return the resolved write-safe root path, or None if unset."""
    root = ""
    for env_name in _WRITE_SAFE_ROOT_ENV_NAMES:
        root = os.getenv(env_name, "")
        if root:
            break
    if not root:
        return None
    try:
        return os.path.realpath(os.path.expanduser(root))
    except Exception:
        return None


def is_write_denied(path: str) -> bool:
    """Return True if path is blocked by the write denylist or safe root."""
    home = os.path.realpath(os.path.expanduser("~"))
    resolved = os.path.realpath(os.path.expanduser(str(path)))

    if resolved in build_write_denied_paths(home):
        return True
    for prefix in build_write_denied_prefixes(home):
        if resolved.startswith(prefix):
            return True

    safe_root = get_safe_write_root()
    if safe_root and not (resolved == safe_root or resolved.startswith(safe_root + os.sep)):
        return True

    return False


def get_read_block_error(path: str) -> Optional[str]:
    """Return an error message when a read targets a denied agent path.

    Two categories are blocked:

      * Internal cache files under ``<home>/skills/.hub`` — readable metadata
        that an attacker could use as a prompt-injection carrier.
      * Credential / secret stores under the agent home and the global agent
        root: ``auth.json``, ``auth.lock``, ``.anthropic_oauth.json``,
        ``.env``, ``webhook_subscriptions.json``, and anything under
        ``mcp-tokens/``. These hold plaintext provider keys, OAuth tokens,
        and HMAC secrets the agent never needs to read directly — provider
        tools / gateway adapters consume them through internal channels.

    **This is NOT a security boundary.** The terminal tool runs as the same
    OS user with shell access; the agent can still ``cat`` the file. The
    read-deny is defense-in-depth: it returns a clear error to models that
    respect tool denials (which empirically prompts most to stop rather than
    shell out), and it surfaces an audit trail when something tries to read
    credentials. Treat any user-visible framing as "may help," not "stops
    attackers."

    Callers that resolve relative paths against a non-process cwd
    (e.g. ``TERMINAL_CWD`` in ``tools/file_tools.py``) MUST pre-resolve the
    path before calling, since this resolves against the process cwd.
    """
    resolved = Path(path).expanduser().resolve()

    # Resolve BOTH the active home (profile-aware) AND the global agent root
    # so credential stores at ``<root>/auth.json`` etc. are blocked under a
    # profile too (home points at ``<root>/profiles/<name>`` in profile mode).
    agent_dirs: list[Path] = []
    for base in (_hermes_home_path(), _hermes_root_path()):
        try:
            real = base.resolve()
        except Exception:
            continue
        if real not in agent_dirs:
            agent_dirs.append(real)

    # Skills .hub: prompt-injection carriers.
    for hd in agent_dirs:
        for blocked in (hd / "skills" / ".hub" / "index-cache", hd / "skills" / ".hub"):
            try:
                resolved.relative_to(blocked)
            except ValueError:
                continue
            return (
                f"Access denied: {path} is an internal agent cache file "
                "and cannot be read directly to prevent prompt injection. "
                "Use the skills_list or skill_view tools instead."
            )

    # Credential / secret stores — exact-file matches under either dir.
    credential_file_names = (
        "auth.json",
        "auth.lock",
        ".anthropic_oauth.json",
        ".env",
        "webhook_subscriptions.json",
    )
    for hd in agent_dirs:
        for name in credential_file_names:
            try:
                blocked = (hd / name).resolve()
            except Exception:
                continue
            if resolved == blocked:
                return (
                    f"Access denied: {path} is an agent credential store and "
                    "cannot be read directly. Provider tools consume these "
                    "credentials through internal channels. (Defense-in-depth "
                    "— not a security boundary; the terminal tool can still "
                    "bypass.)"
                )

    # mcp-tokens/: directory prefix match — anything inside is OAuth material.
    for hd in agent_dirs:
        try:
            mcp_tokens = (hd / "mcp-tokens").resolve()
        except Exception:
            continue
        if resolved == mcp_tokens:
            return (
                f"Access denied: {path} is the agent MCP token directory and "
                "cannot be read directly. (Defense-in-depth — not a security "
                "boundary; the terminal tool can still bypass.)"
            )
        try:
            resolved.relative_to(mcp_tokens)
        except ValueError:
            continue
        return (
            f"Access denied: {path} is an agent MCP token file and cannot be "
            "read directly. (Defense-in-depth — not a security boundary; the "
            "terminal tool can still bypass.)"
        )

    return None
