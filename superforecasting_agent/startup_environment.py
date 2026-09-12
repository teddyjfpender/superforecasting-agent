"""Helpers for loading Superforecasting Agent env files across entrypoints."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.storage.files import atomic_replace

# Env var name suffixes that indicate credential values.  These are the
# only env vars whose values we sanitize on load — we must not silently
# alter arbitrary user env vars, but credentials are known to require
# pure ASCII (they become HTTP header values).
_CREDENTIAL_SUFFIXES = ("_API_KEY", "_TOKEN", "_SECRET", "_KEY")

# Names we've already warned about during this process, so repeated
# load_forecast_dotenv() calls (user env + project env, gateway hot-reload,
# tests) do not spam the same warning multiple times.
_WARNED_KEYS: set[str] = set()


# Maps env-var name -> origin label (for example "bitwarden") for keys that
# were injected by an external secret source during load_forecast_dotenv().
# Used by setup / `superforecasting-agent model` flows to label detected
# credentials so users understand WHERE a key came from when their .env
# doesn't contain it directly.  This fork does not currently wire an external
# secret manager, so the map stays empty unless a future loader populates it;
# credential-pool persistence reads it only as origin metadata and must never
# treat it as authorization to persist the raw value.
_SECRET_SOURCES: dict[str, str] = {}


def get_secret_source(env_var: str) -> str | None:
    """Return the label of the secret source that supplied ``env_var``, if any.

    Returns ``None`` for keys that came from ``.env``, the shell environment,
    or aren't tracked.  The returned label is metadata only: credential-pool
    persistence may store it to explain the origin of a borrowed secret, but
    must never treat it as authorization to persist the raw value.
    """
    return _SECRET_SOURCES.get(env_var)


def _format_offending_chars(value: str, limit: int = 3) -> str:
    """Return a compact 'U+XXXX ('c'), ...' summary of non-ASCII codepoints."""
    seen: list[str] = []
    for ch in value:
        if ord(ch) > 127:
            label = f"U+{ord(ch):04X}"
            if ch.isprintable():
                label += f" ({ch!r})"
            if label not in seen:
                seen.append(label)
            if len(seen) >= limit:
                break
    return ", ".join(seen)


def _sanitize_loaded_credentials() -> None:
    """Strip non-ASCII characters from credential env vars in os.environ.

    Called after dotenv loads so the rest of the codebase never sees
    non-ASCII API keys.  Only touches env vars whose names end with
    known credential suffixes (``_API_KEY``, ``_TOKEN``, etc.).

    Emits a one-line warning to stderr when characters are stripped.
    Silent stripping would mask copy-paste corruption (Unicode lookalike
    glyphs from PDFs / rich-text editors, ZWSP from web pages) as opaque
    provider-side "invalid API key" errors (see #6843).
    """
    for key, value in list(os.environ.items()):
        if not any(key.endswith(suffix) for suffix in _CREDENTIAL_SUFFIXES):
            continue
        try:
            value.encode("ascii")
            continue
        except UnicodeEncodeError:
            pass
        cleaned = value.encode("ascii", errors="ignore").decode("ascii")
        os.environ[key] = cleaned
        if key in _WARNED_KEYS:
            continue
        _WARNED_KEYS.add(key)
        stripped = len(value) - len(cleaned)
        detail = _format_offending_chars(value) or "non-printable"
        print(
            f"  Warning: {key} contained {stripped} non-ASCII character"
            f"{'s' if stripped != 1 else ''} ({detail}) — stripped so the "
            f"key can be sent as an HTTP header.",
            file=sys.stderr,
        )
        print(
            "  This usually means the key was copy-pasted from a PDF, "
            "rich-text editor, or web page that substituted lookalike\n"
            "  Unicode glyphs for ASCII letters. If authentication fails "
            '(e.g. "API key not valid"), re-copy the key from the\n'
            "  provider's dashboard and run `superforecasting-agent setup` (or edit the "
            ".env file in a plain-text editor).",
            file=sys.stderr,
        )


def _load_dotenv_with_fallback(path: Path, *, override: bool) -> None:
    try:
        load_dotenv(dotenv_path=path, override=override, encoding="utf-8")
    except UnicodeDecodeError:
        load_dotenv(dotenv_path=path, override=override, encoding="latin-1")
    # Strip non-ASCII characters from credential env vars that were just
    # loaded.  API keys must be pure ASCII since they're sent as HTTP
    # header values (httpx encodes headers as ASCII).  Non-ASCII chars
    # typically come from copy-pasting keys from PDFs or rich-text editors
    # that substitute Unicode lookalike glyphs (e.g. ʋ U+028B for v).
    _sanitize_loaded_credentials()


def _sanitize_env_file_if_needed(path: Path) -> None:
    """Pre-sanitize a .env file before python-dotenv reads it.

    python-dotenv does not handle corrupted lines where multiple
    KEY=VALUE pairs are concatenated on a single line (missing newline).
    This produces mangled values — e.g. a bot token duplicated 8×
    (see #8908).

    The shared parser uses built-in and platform-manifest key metadata, without
    importing CLI configuration or executing plugin implementations.
    """
    if not path.exists():
        return
    from superforecasting_agent.configuration.env_lines import sanitize_env_lines
    from superforecasting_agent.configuration.environment_catalog import (
        _EXTRA_ENV_KEYS,
        OPTIONAL_ENV_VARS,
    )
    from superforecasting_agent.paths import get_install_root
    from superforecasting_agent.storage.plugin_environment import (
        read_platform_environment,
    )

    try:
        with open(path, encoding="utf-8-sig", errors="replace") as f:
            original = f.readlines()
        keys = set(OPTIONAL_ENV_VARS) | _EXTRA_ENV_KEYS
        keys.update(
            read_platform_environment(get_install_root() / "plugins" / "platforms")
        )
        sanitized = sanitize_env_lines(original, keys)
        if sanitized != original:
            import tempfile

            fd, tmp = tempfile.mkstemp(
                dir=str(path.parent), suffix=".tmp", prefix=".env_"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.writelines(sanitized)
                    f.flush()
                    os.fsync(f.fileno())
                atomic_replace(tmp, path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
    except Exception:
        pass  # best-effort — don't block gateway startup


def load_forecast_dotenv(
    *,
    hermes_home: str | os.PathLike | None = None,
    project_env: str | os.PathLike | None = None,
) -> list[Path]:
    """Load Superforecasting Agent environment files with user config first.

    Behavior:
    - `~/.superforecasting-agent/.env` overrides stale shell-exported values
      when present. Legacy `~/.hermes/.env` remains readable when the resolved
      home points there.
    - project `.env` acts as a dev fallback and only fills missing values when
      the user env exists.
    - if no user env exists, the project `.env` also overrides stale shell vars.
    """
    loaded: list[Path] = []

    home_path = Path(hermes_home) if hermes_home is not None else get_agent_home()
    user_env = home_path / ".env"
    project_env_path = Path(project_env) if project_env else None

    # Fix corrupted .env files before python-dotenv parses them (#8908).
    if user_env.exists():
        _sanitize_env_file_if_needed(user_env)
    if project_env_path and project_env_path.exists():
        _sanitize_env_file_if_needed(project_env_path)

    if user_env.exists():
        _load_dotenv_with_fallback(user_env, override=True)
        loaded.append(user_env)

    if project_env_path and project_env_path.exists():
        _load_dotenv_with_fallback(project_env_path, override=not loaded)
        loaded.append(project_env_path)

    return loaded


def load_hermes_dotenv(
    *,
    hermes_home: str | os.PathLike | None = None,
    project_env: str | os.PathLike | None = None,
) -> list[Path]:
    """Compatibility wrapper for inherited imports."""

    return load_forecast_dotenv(hermes_home=hermes_home, project_env=project_env)
