"""Shared constants for Superforecasting Agent.

Import-safe module with no dependencies — can be imported from anywhere
without risk of circular imports.
"""

import os
import re
import sysconfig
from contextvars import ContextVar, Token
from pathlib import Path


_profile_fallback_warned: bool = False
_UNSET = object()
_AGENT_HOME_OVERRIDE: ContextVar[str | object] = ContextVar(
    "_AGENT_HOME_OVERRIDE", default=_UNSET
)
_HOME_ENV_VARS = ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME")
_OPTIONAL_SKILLS_ENV_VARS = (
    "SUPERFORECASTING_AGENT_OPTIONAL_SKILLS",
    "FORECAST_OPTIONAL_SKILLS",
    "HERMES_OPTIONAL_SKILLS",
)
_BUNDLED_SKILLS_ENV_VARS = (
    "SUPERFORECASTING_AGENT_BUNDLED_SKILLS",
    "FORECAST_BUNDLED_SKILLS",
    "HERMES_BUNDLED_SKILLS",
)
_NATIVE_HOME_DIRNAME = ".superforecasting-agent"
_LEGACY_HOME_DIRNAME = ".hermes"


def _configured_home_env() -> tuple[str | None, str | None]:
    """Return the first configured home env var name/value pair.

    ``HERMES_HOME`` remains supported for compatibility, but the fork accepts
    forecast-native aliases first so new deployments do not need a
    Hermes-branded environment variable.
    """
    for name in _HOME_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return name, value
    return None, None


def _first_configured_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


def _native_home() -> Path:
    return Path.home() / _NATIVE_HOME_DIRNAME


def get_native_agent_home() -> Path:
    """Return the fork-native default home directory path."""

    return _native_home()


def _legacy_home() -> Path:
    return Path.home() / _LEGACY_HOME_DIRNAME


def _default_home_candidate() -> Path:
    """Return the no-env home path for this fork.

    New installs default to the fork-native home. Existing Hermes installs
    keep using ``~/.hermes`` until users explicitly migrate or set one of the
    forecast-native home variables.
    """
    native = _native_home()
    if native.exists():
        return native
    legacy = _legacy_home()
    if legacy.exists():
        return legacy
    return native


def set_agent_home_override(path: str | Path | None) -> Token:
    """Set a context-local agent home override and return its reset token.

    This is for in-process, per-task scoping.  It deliberately does not mutate
    ``os.environ`` because that is shared by every thread in the process.
    """
    value: str | object = _UNSET if path is None else str(path)
    return _AGENT_HOME_OVERRIDE.set(value)


def reset_agent_home_override(token: Token) -> None:
    """Restore the previous context-local agent home override."""
    _AGENT_HOME_OVERRIDE.reset(token)


def get_agent_home_override() -> str | None:
    """Return the active context-local agent home override, if any."""
    override = _AGENT_HOME_OVERRIDE.get()
    if override is _UNSET or not override:
        return None
    return str(override)


def get_agent_home() -> Path:
    """Return the agent home directory.

    Reads SUPERFORECASTING_AGENT_HOME, FORECAST_HOME, or HERMES_HOME env vars,
    then falls back to ``~/.superforecasting-agent`` for new installs. Existing
    ``~/.hermes`` directories remain supported as the fallback home during the
    fork transition. This is the single source of truth — all other copies
    should import this.

    When ``HERMES_HOME`` is unset but an ``active_profile`` file indicates
    a non-default profile is active, logs a loud one-shot warning to
    ``errors.log`` so cross-profile data corruption is diagnosable instead
    of silent.  Behavior is unchanged otherwise — we still return
    the selected fallback directory — because raising here would brick 30+
    module-level callers that import this at load time. Subprocess spawners
    are expected to propagate an explicit home env var (see the systemd
    template in ``superforecasting_agent/runtime/gateway.py`` and the kanban dispatcher in
    ``superforecasting_agent/runtime/kanban_db.py``). See
    https://github.com/NousResearch/hermes-agent/issues/18594.
    """
    override = get_agent_home_override()
    if override:
        return Path(override)

    _env_name, val = _configured_home_env()
    if val:
        return Path(val)

    # Guard: if a non-default profile is sticky-active, warn once that
    # the fallback to the default profile is almost certainly wrong.
    global _profile_fallback_warned
    if not _profile_fallback_warned:
        try:
            fallback_home = _default_home_candidate()
            # Inline the default-root resolution from get_default_agent_root()
            # to stay import-safe (this function is called from module scope
            # in 30+ files; we cannot afford to trigger logging setup here).
            active_path = fallback_home / "active_profile"
            active = active_path.read_text().strip() if active_path.exists() else ""
        except (UnicodeDecodeError, OSError):
            active = ""
        if active and active != "default":
            _profile_fallback_warned = True
            # Write directly to stderr.  We intentionally do NOT route this
            # through ``logging`` because (a) this function is called at
            # module-import time from 30+ sites, often before logging is
            # configured, and (b) root-logger propagation would double-emit
            # on consoles where a StreamHandler is already attached.
            import sys
            msg = (
                f"[HERMES_HOME fallback] no explicit agent home env var is "
                f"set but active profile is {active!r}. Falling back to "
                f"{fallback_home}, which is the DEFAULT profile — not "
                f"{active!r}. Any data this process writes will land in the "
                f"wrong profile. The subprocess spawner should pass "
                f"SUPERFORECASTING_AGENT_HOME, FORECAST_HOME, or HERMES_HOME "
                f"explicitly (see issue #18594)."
            )
            try:
                sys.stderr.write(msg + "\n")
                sys.stderr.flush()
            except Exception:
                pass

    return _default_home_candidate()


def get_default_agent_root() -> Path:
    """Return the root agent directory for profile-level operations.

    In new standard deployments this is ``~/.superforecasting-agent``. Existing
    ``~/.hermes`` directories remain the fallback root during migration.

    In Docker or custom deployments where SUPERFORECASTING_AGENT_HOME,
    FORECAST_HOME, or HERMES_HOME points outside ``~/.hermes`` (e.g.
    ``/opt/data``), returns that directory directly — that IS the root.

    In profile mode where the configured home is ``<root>/profiles/<name>``,
    returns ``<root>`` so that ``profile list`` can see all profiles.
    Works for standard fork-native, legacy Hermes, and Docker
    (``/opt/data/profiles/coder``) layouts.

    Import-safe — no dependencies beyond stdlib.
    """
    roots = (_native_home(), _legacy_home())
    fallback_root = _default_home_candidate()
    _env_name, env_home = _configured_home_env()
    if not env_home:
        return fallback_root
    env_path = Path(env_home)
    for root in roots:
        try:
            env_path.resolve().relative_to(root.resolve())
            # Configured home is under the standard fork or legacy root.
            return root
        except ValueError:
            pass

    # Docker / custom deployment.
    # Check if this is a profile path: <root>/profiles/<name>
    # If the immediate parent dir is named "profiles", the root is
    # the grandparent — this covers Docker profiles correctly.
    if env_path.parent.name == "profiles":
        return env_path.parent.parent

    # Not a profile path — HERMES_HOME itself is the root
    return env_path


def _get_packaged_data_dir(name: str) -> Path | None:
    """Return an installed data-files directory if one exists.

    Used to discover bundled skills/optional-skills when Hermes is installed
    from a wheel that emitted them via setuptools data_files.
    """
    candidates = []
    for scheme in ("data", "purelib", "platlib"):
        raw = sysconfig.get_path(scheme)
        if raw:
            candidates.append(Path(raw) / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def get_optional_skills_dir(default: Path | None = None) -> Path:
    """Return the optional-skills directory, honoring package-manager wrappers.

    Packaged installs may ship ``optional-skills`` outside the Python package
    tree and expose it via ``SUPERFORECASTING_AGENT_OPTIONAL_SKILLS`` or an
    accepted legacy alias.
    """
    override = _first_configured_env_value(_OPTIONAL_SKILLS_ENV_VARS)
    if override:
        return Path(override)
    packaged = _get_packaged_data_dir("optional-skills")
    if packaged is not None:
        return packaged
    if default is not None:
        return default
    return get_agent_home() / "optional-skills"


def get_bundled_skills_dir(default: Path | None = None) -> Path:
    """Return the bundled skills directory for source and packaged installs.

    Resolution order:
        1. ``SUPERFORECASTING_AGENT_BUNDLED_SKILLS`` / ``FORECAST_BUNDLED_SKILLS``
           / legacy ``HERMES_BUNDLED_SKILLS`` env var
        2. Wheel-installed ``<sysconfig data>/skills`` (pip install path)
        3. Caller-supplied ``default`` (typically the source-checkout path)
        4. ``<HERMES_HOME>/skills`` last-resort
    """
    override = _first_configured_env_value(_BUNDLED_SKILLS_ENV_VARS)
    if override:
        return Path(override)
    packaged = _get_packaged_data_dir("skills")
    if packaged is not None:
        return packaged
    if default is not None:
        return default
    return get_agent_home() / "skills"


def get_agent_dir(new_subpath: str, old_name: str) -> Path:
    """Resolve a Hermes subdirectory with backward compatibility.

    New installs get the consolidated layout (e.g. ``cache/images``).
    Existing installs that already have the old path (e.g. ``image_cache``)
    keep using it — no migration required.

    Args:
        new_subpath: Preferred path relative to HERMES_HOME (e.g. ``"cache/images"``).
        old_name: Legacy path relative to HERMES_HOME (e.g. ``"image_cache"``).

    Returns:
        Absolute ``Path`` — old location if it exists on disk, otherwise the new one.
    """
    home = get_agent_home()
    old_path = home / old_name
    if old_path.exists():
        return old_path
    return home / new_subpath


def display_agent_home() -> str:
    """Return a user-friendly display string for the current HERMES_HOME.

    Uses ``~/`` shorthand for readability::

        default:  ``~/.superforecasting-agent``
        legacy:   ``~/.hermes``
        profile:  ``~/.superforecasting-agent/profiles/coder``
        custom:   ``/opt/hermes-custom``

    Use this in **user-facing** print/log messages instead of hardcoding
    ``~/.hermes`` or ``~/.superforecasting-agent``. For code that needs a real ``Path``, use
    :func:`get_agent_home` instead.
    """
    home = get_agent_home()
    try:
        return "~/" + str(home.relative_to(Path.home()))
    except ValueError:
        return str(home)


def get_subprocess_home() -> str | None:
    """Return a per-profile HOME directory for subprocesses, or None.

    When ``{HERMES_HOME}/home/`` exists on disk, subprocesses should use it
    as ``HOME`` so system tools (git, ssh, gh, npm …) write their configs
    inside the Hermes data directory instead of the OS-level ``/root`` or
    ``~/``.  This provides:

    * **Docker persistence** — tool configs land inside the persistent volume.
    * **Profile isolation** — each profile gets its own git identity, SSH
      keys, gh tokens, etc.

    The Python process's own ``os.environ["HOME"]`` and ``Path.home()`` are
    **never** modified — only subprocess environments should inject this value.
    Activation is directory-based: if the ``home/`` subdirectory doesn't
    exist, returns ``None`` and behavior is unchanged.
    """
    hermes_home = get_agent_home_override() or _configured_home_env()[1]
    if not hermes_home:
        return None
    profile_home = os.path.join(hermes_home, "home")
    if os.path.isdir(profile_home):
        return profile_home
    return None


VALID_REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh")


def parse_service_tier(raw) -> str | None:
    """Canonical persisted fast-mode aliases for CLI, gateway and TUI."""
    value = str(raw or "").strip().lower()
    if not value or value in {"normal", "default", "standard", "off", "none"}:
        return None
    if value in {"fast", "priority", "on"}:
        return "priority"
    import logging
    logging.getLogger(__name__).warning("Unknown service_tier '%s', ignoring", raw)
    return None


def parse_fast_mode_command(raw: str, *, current_fast: bool) -> str:
    """Return status/fast/normal; an empty command never changes settings."""
    value = raw.strip().lower()
    if value in {"", "status"}:
        return "status"
    if value == "toggle":
        return "normal" if current_fast else "fast"
    if value in {"fast", "on"}:
        return "fast"
    if value in {"normal", "off"}:
        return "normal"
    raise ValueError(f"unknown fast mode: {raw}")


def parse_reasoning_effort(effort: str) -> dict | None:
    """Parse a reasoning effort level into a config dict.

    Valid levels: "none", "minimal", "low", "medium", "high", "xhigh".
    Returns None when the input is empty or unrecognized (caller uses default).
    Returns {"enabled": False} for "none".
    Returns {"enabled": True, "effort": <level>} for valid effort levels.
    """
    if not effort or not effort.strip():
        return None
    effort = effort.strip().lower()
    if effort == "none":
        return {"enabled": False}
    if effort in VALID_REASONING_EFFORTS:
        return {"enabled": True, "effort": effort}
    return None


def is_termux() -> bool:
    """Return True when running inside a Termux (Android) environment.

    Checks ``TERMUX_VERSION`` (set by Termux) or the Termux-specific
    ``PREFIX`` path.  Import-safe — no heavy deps.
    """
    prefix = os.getenv("PREFIX", "")
    return bool(os.getenv("TERMUX_VERSION") or "com.termux/files/usr" in prefix)


_wsl_detected: bool | None = None


def is_wsl() -> bool:
    """Return True when running inside WSL (Windows Subsystem for Linux).

    Checks ``/proc/version`` for the ``microsoft`` marker that both WSL1
    and WSL2 inject.  Result is cached for the process lifetime.
    Import-safe — no heavy deps.
    """
    global _wsl_detected
    if _wsl_detected is not None:
        return _wsl_detected
    try:
        with open("/proc/version", "r", encoding="utf-8") as f:
            _wsl_detected = "microsoft" in f.read().lower()
    except Exception:
        _wsl_detected = False
    return _wsl_detected


_container_detected: bool | None = None


def is_container() -> bool:
    """Return True when running inside a Docker/Podman container.

    Checks ``/.dockerenv`` (Docker), ``/run/.containerenv`` (Podman),
    and ``/proc/1/cgroup`` for container runtime markers.  Result is
    cached for the process lifetime.  Import-safe — no heavy deps.
    """
    global _container_detected
    if _container_detected is not None:
        return _container_detected
    if os.path.exists("/.dockerenv"):
        _container_detected = True
        return True
    if os.path.exists("/run/.containerenv"):
        _container_detected = True
        return True
    try:
        with open("/proc/1/cgroup", "r", encoding="utf-8") as f:
            cgroup = f.read()
            if "docker" in cgroup or "podman" in cgroup or "/lxc/" in cgroup:
                _container_detected = True
                return True
    except OSError:
        pass
    _container_detected = False
    return False


# ─── Well-Known Paths ─────────────────────────────────────────────────────────


def get_config_path() -> Path:
    """Return the path to ``config.yaml`` under HERMES_HOME.

    Replaces the ``get_agent_home() / "config.yaml"`` pattern repeated
    in 7+ files (skill_utils.py, superforecasting_agent/logging.py, superforecasting_agent/clock.py, etc.).
    """
    return get_agent_home() / "config.yaml"


def get_skills_dir() -> Path:
    """Return the path to the skills directory under HERMES_HOME."""
    return get_agent_home() / "skills"


def get_workspace_dir() -> Path:
    """Return the sanctioned desk-agent WORKSPACE under HERMES_HOME.

    ``<HERMES_HOME>/workspace`` is the allowed write zone where the desk
    agent builds forecasting models, runs backtests, and keeps scratch
    calculations — as opposed to the harness source tree, which the agent's
    file-write tools refuse to touch (see ``agent.harness_wall``).
    """
    return get_agent_home() / "workspace"


def ensure_workspace_dir() -> Path:
    """Create (on demand) and return the desk-agent workspace directory."""
    ws = get_workspace_dir()
    try:
        ws.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return ws



def get_env_path() -> Path:
    """Return the path to the ``.env`` file under HERMES_HOME."""
    return get_agent_home() / ".env"


# ─── Network Preferences ─────────────────────────────────────────────────────


def apply_ipv4_preference(force: bool = False) -> None:
    """Monkey-patch ``socket.getaddrinfo`` to prefer IPv4 connections.

    On servers with broken or unreachable IPv6, Python tries AAAA records
    first and hangs for the full TCP timeout before falling back to IPv4.
    This affects httpx, requests, urllib, the OpenAI SDK — everything that
    uses ``socket.getaddrinfo``.

    When *force* is True, patches ``getaddrinfo`` so that calls with
    ``family=AF_UNSPEC`` (the default) resolve as ``AF_INET`` instead,
    skipping IPv6 entirely.  If no A record exists, falls back to the
    original unfiltered resolution so pure-IPv6 hosts still work.

    Safe to call multiple times — only patches once.
    Set ``network.force_ipv4: true`` in ``config.yaml`` to enable.
    """
    if not force:
        return

    import socket

    # Guard against double-patching
    if getattr(socket.getaddrinfo, "_hermes_ipv4_patched", False):
        return

    _original_getaddrinfo = socket.getaddrinfo

    def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if family == 0:  # AF_UNSPEC — caller didn't request a specific family
            try:
                return _original_getaddrinfo(
                    host, port, socket.AF_INET, type, proto, flags
                )
            except socket.gaierror:
                # No A record — fall back to full resolution (pure-IPv6 hosts)
                return _original_getaddrinfo(host, port, family, type, proto, flags)
        return _original_getaddrinfo(host, port, family, type, proto, flags)

    _ipv4_getaddrinfo._hermes_ipv4_patched = True  # type: ignore[attr-defined]
    socket.getaddrinfo = _ipv4_getaddrinfo  # type: ignore[assignment]


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODELS_URL = f"{OPENROUTER_BASE_URL}/models"

AI_GATEWAY_BASE_URL = "https://ai-gateway.vercel.sh/v1"


def get_active_profile_name() -> str:
    """Infer the current profile name from HERMES_HOME.

    Returns ``"default"`` if HERMES_HOME is not set or points to the default
    runtime root. Returns the profile name if HERMES_HOME points into
    ``<default-root>/profiles/<name>``.
    Returns ``"custom"`` if HERMES_HOME is set to an unrecognized path.
    """
    hermes_home = get_agent_home()
    resolved = hermes_home.resolve()

    default_resolved = get_default_agent_root().resolve()
    if resolved == default_resolved:
        return "default"

    profiles_root = (default_resolved / "profiles").resolve()
    try:
        rel = resolved.relative_to(profiles_root)
        parts = rel.parts
        if len(parts) == 1 and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", parts[0]):
            return parts[0]
    except ValueError:
        pass

    return "custom"
