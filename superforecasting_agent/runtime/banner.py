"""Welcome banner, ASCII art, skills summary, and update check for the CLI.

Pure display functions with no classic CLI state dependency.
"""

from superforecasting_agent.paths import get_install_root

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from superforecasting_agent.constants import get_agent_home
from typing import Dict, List, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from prompt_toolkit import print_formatted_text as _pt_print
from prompt_toolkit.formatted_text import ANSI as _PT_ANSI
from superforecasting_agent.environment import env_var_alias_value

logger = logging.getLogger(__name__)

_YOLO_MODE_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_YOLO_MODE",
    "FORECAST_YOLO_MODE",
    "HERMES_YOLO_MODE",
)
_REVISION_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_REVISION",
    "FORECAST_REVISION",
    "HERMES_REVISION",
)
_AGENT_LOGO_ENV_NAMES = (
    "SUPERFORECASTING_AGENT_LOGO",
    "FORECAST_AGENT_LOGO",
    "HERMES_AGENT_LOGO",
)


def _yolo_mode_enabled() -> bool:
    truthy = {"1", "true", "yes", "on"}
    return any((os.getenv(name) or "").strip().lower() in truthy for name in _YOLO_MODE_ENV_NAMES)


# =========================================================================
# ANSI building blocks for conversation display
# =========================================================================

_GOLD = "\033[1;38;2;255;215;0m"  # True-color #FFD700 bold
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RST = "\033[0m"


def cprint(text: str):
    """Print ANSI-colored text through prompt_toolkit's renderer."""
    _pt_print(_PT_ANSI(text))


# =========================================================================
# Skin-aware color helpers
# =========================================================================

def _skin_color(key: str, fallback: str) -> str:
    """Get a color from the active skin, or return fallback."""
    try:
        from superforecasting_agent.runtime.skin_engine import get_active_skin
        return get_active_skin().get_color(key, fallback)
    except Exception:
        return fallback


def _skin_branding(key: str, fallback: str) -> str:
    """Get a branding string from the active skin, or return fallback."""
    try:
        from superforecasting_agent.runtime.skin_engine import get_active_skin
        return get_active_skin().get_branding(key, fallback)
    except Exception:
        return fallback


# =========================================================================
# ASCII Art & Branding
# =========================================================================

from superforecasting_agent.runtime import __version__ as VERSION, __release_date__ as RELEASE_DATE

FORECAST_AGENT_LOGO = """[bold #FFD700]┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓[/]
[bold #FFD700]┃ SUPERFORECASTING AGENT                                                           ┃[/]
[#FFBF00]┃ CLI forecasting desk · forecast ledger · calibration · backtests · alerts          ┃[/]
[#CD7F32]┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛[/]"""

FORECAST_DESK_MARK = """[#CD7F32]        as-of timeline          probability[/]
[#FFBF00]   ┌────────────────────┬──────────────────┐[/]
[#FFD700]   │ evidence freshness  │ 0.10 ▁▂▃▅▇ 0.90 │[/]
[#FFD700]   │ reference classes   │ base rate + view │[/]
[#FFBF00]   │ model runs          │ ensemble update │[/]
[#CD7F32]   └────────────────────┴──────────────────┘[/]
[#B8860B]      ledger · score · postmortem · learn[/]"""


def _default_banner_logo() -> str:
    """Return the default banner logo, honoring fork-native env overrides."""
    return env_var_alias_value(_AGENT_LOGO_ENV_NAMES, FORECAST_AGENT_LOGO) or FORECAST_AGENT_LOGO


# =========================================================================
# Skills scanning
# =========================================================================

def get_available_skills() -> Dict[str, List[str]]:
    """Return skills grouped by category, filtered by platform and disabled state.

    Delegates to ``_find_all_skills()`` from ``tools/skills_tool`` which already
    handles platform gating (``platforms:`` frontmatter) and respects the
    user's ``skills.disabled`` config list.
    """
    try:
        from tools.skills_tool import _find_all_skills
        all_skills = _find_all_skills()  # already filtered
    except Exception:
        return {}

    skills_by_category: Dict[str, List[str]] = {}
    for skill in all_skills:
        category = skill.get("category") or "general"
        skills_by_category.setdefault(category, []).append(skill["name"])
    return skills_by_category


# =========================================================================
# Update check
# =========================================================================

# Cache update check results for 6 hours to avoid repeated git fetches
_UPDATE_CHECK_CACHE_SECONDS = 6 * 3600

# Sentinel returned when we know an update exists but can't count commits
# (e.g. nix-built hermes — no local git history to count against).
UPDATE_AVAILABLE_NO_COUNT = -1

_UPSTREAM_REPO = "teddyjfpender/superforecasting-agent"
_UPSTREAM_REPO_URL = f"https://github.com/{_UPSTREAM_REPO}.git"
_UPSTREAM_BRANCH = "superforecasting-agent-snapshot"
_HOME_REPO_DIR_NAMES = ("superforecasting-agent", "hermes-agent")

# "Latest" resolves against the SAME release ``scripts/install-release.sh`` would
# install, by two paths tried in order:
#
#   1. the machine-readable ``release-manifest.json`` every formal release ships
#      (see scripts/release_manifest.py — the declared contract the one-line
#      installer and the Hetzner bootstrap already resolve against). Served as a
#      plain asset download, so it is NOT subject to the GitHub API's 60-req/hour
#      unauthenticated limit — which a shared or NAT'd network exhausts easily,
#      silently blinding the staleness check exactly when it matters.
#   2. the releases API, for a release older than the manifest.
_LATEST_MANIFEST_URL = (
    f"https://github.com/{_UPSTREAM_REPO}/releases/latest/download/release-manifest.json"
)
_LATEST_RELEASE_API = f"https://api.github.com/repos/{_UPSTREAM_REPO}/releases/latest"
_ONE_LINE_INSTALLER = (
    f"curl -fsSL https://github.com/{_UPSTREAM_REPO}"
    "/releases/latest/download/install.sh | bash"
)
# A git checkout must REBUILD the bundle and reinstall it: a plain `git pull`
# leaves the pipx-installed binary — and the TUI it froze into its own venv at
# superforecasting_agent/runtime/tui_dist/entry.js — completely untouched.
_REBUILD_AND_REINSTALL = "scripts/build-release.sh && pipx install --force dist/*.whl"


def _check_via_rev(local_rev: str) -> Optional[int]:
    """Compare an embedded git revision to the fork snapshot via ls-remote.

    Returns 0 if up-to-date, ``UPDATE_AVAILABLE_NO_COUNT`` if behind,
    or ``None`` on failure.
    """
    try:
        result = subprocess.run(
            ["git", "ls-remote", _UPSTREAM_REPO_URL, f"refs/heads/{_UPSTREAM_BRANCH}"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    upstream_rev = result.stdout.split()[0]
    if not upstream_rev:
        return None
    return 0 if upstream_rev == local_rev else UPDATE_AVAILABLE_NO_COUNT


def _check_via_local_git(repo_dir: Path) -> Optional[int]:
    """Count commits behind the origin snapshot branch in a local checkout."""
    try:
        subprocess.run(
            ["git", "fetch", "origin", "--quiet"],
            capture_output=True, timeout=10,
            cwd=str(repo_dir),
        )
    except Exception:
        pass  # Offline or timeout — use stale refs, that's fine

    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"HEAD..origin/{_UPSTREAM_BRANCH}"],
            capture_output=True, text=True, timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            return int(result.stdout.strip())
    except Exception:
        pass
    return None


def _resolve_home_repo_dir(hermes_home: Path) -> Optional[Path]:
    """Return a profile-scoped git checkout, preferring fork-native names."""
    for dirname in _HOME_REPO_DIR_NAMES:
        repo_dir = hermes_home / dirname
        if (repo_dir / ".git").exists():
            return repo_dir
    return None


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse '0.13.0' into (0, 13, 0) for comparison. Non-numeric segments become 0."""
    parts = []
    for segment in v.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    return tuple(parts)


# The newest version any resolution path (GitHub release / cache) has
# seen this process. Purely a display aid — the authoritative "am I behind?"
# answer stays ``check_for_updates()``'s ``behind`` count.
_latest_version: Optional[str] = None


def _record_latest_version(value: Optional[str]) -> Optional[str]:
    """Remember a resolved "latest" version so the TUI can name it."""
    global _latest_version
    if value:
        _latest_version = value
    return value


def _get_json(url: str, accept: str) -> Optional[dict]:
    """GET a small JSON document. None on ANY failure — offline, DNS, timeout,
    rate limit, non-JSON. Never raises, never retries, never blocks past 5s."""
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"Accept": accept})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _fetch_release_latest() -> Optional[str]:
    """Resolve the newest PUBLISHED release version, or None.

    Returns a bare semver so it compares directly against ``__version__``. Tries
    the shipped release manifest first (no API rate limit), then the releases API
    (``vX.Y.Z`` tag, ``v`` stripped). Silent on every failure.
    """
    manifest = _get_json(_LATEST_MANIFEST_URL, "application/json")
    if manifest and manifest.get("product") == "superforecasting-agent":
        version = str(manifest.get("version") or "").strip()
        if version:
            return version

    release = _get_json(_LATEST_RELEASE_API, "application/vnd.github+json")
    tag = str((release or {}).get("tag_name") or "").strip().lstrip("v")
    return tag or None


def check_via_release() -> Optional[int]:
    """Compare the installed version against the newest published GitHub release.

    The release lane (a pipx-installed wheel, or the one-line installer) has no
    git checkout AND this fork is not published to PyPI, so without this path a
    wheel install can never learn that it is stale — which is exactly how an
    operator ends up running a months-old bundled TUI. Returns 0 if up-to-date,
    ``UPDATE_AVAILABLE_NO_COUNT`` if behind (there are no commits to count), or
    None when the lookup failed.
    """
    latest = _record_latest_version(_fetch_release_latest())
    if not latest:
        return None
    try:
        return UPDATE_AVAILABLE_NO_COUNT if _version_tuple(latest) > _version_tuple(VERSION) else 0
    except Exception:
        return None


def check_for_updates() -> Optional[int]:
    """Check whether a Superforecasting Agent update is available.

    Two paths: if a revision env alias is set (Nix builds embed it), compare
    it to the fork snapshot via ``git ls-remote``. Otherwise look for a local
    git checkout and count commits behind the origin snapshot branch.

    Returns the number of commits behind, ``UPDATE_AVAILABLE_NO_COUNT`` (-1)
    if behind but the count is unknown, ``0`` if up-to-date, or ``None`` if
    the check failed or doesn't apply. Cached for 6 hours.
    """
    hermes_home = get_agent_home()
    cache_file = hermes_home / ".update_check"
    embedded_rev = env_var_alias_value(_REVISION_ENV_NAMES) or None

    # Read cache — invalidate if the embedded rev has changed since last check
    now = time.time()
    try:
        if cache_file.exists():
            cached = json.loads(cache_file.read_text())
            if (
                now - cached.get("ts", 0) < _UPDATE_CHECK_CACHE_SECONDS
                and cached.get("rev") == embedded_rev
            ):
                _record_latest_version(cached.get("latest"))
                return cached.get("behind")
    except Exception:
        pass

    if embedded_rev:
        behind = _check_via_rev(embedded_rev)
    else:
        # Prefer the running code's location over the profile-scoped path.
        # $HERMES_HOME/{superforecasting-agent,hermes-agent}/ may be a stale
        # copy from --clone-all; Path(__file__) resolves to the installed checkout.
        repo_dir = get_install_root()
        if not (repo_dir / ".git").exists():
            repo_dir = _resolve_home_repo_dir(hermes_home)
        if repo_dir is None or not (repo_dir / ".git").exists():
            behind = check_via_release()
        else:
            behind = _check_via_local_git(repo_dir)
        if behind is None:
            # A checkout whose remote isn't named `origin` still falls back to
            # the published GitHub release, the product-version authority.
            behind = check_via_release()

    try:
        cache_file.write_text(
            json.dumps({"ts": now, "behind": behind, "rev": embedded_rev, "latest": _latest_version})
        )
    except Exception:
        pass

    return behind


def _resolve_repo_dir() -> Optional[Path]:
    """Return the active Superforecasting Agent git checkout, or None.

    Prefers the running code's location over the profile-scoped path
    because ``$HERMES_HOME/{superforecasting-agent,hermes-agent}/`` may be a
    stale copy carried over by ``--clone-all``.
    """
    repo_dir = get_install_root()
    if not (repo_dir / ".git").exists():
        hermes_home = get_agent_home()
        repo_dir = _resolve_home_repo_dir(hermes_home)
    if repo_dir is None:
        return None
    return repo_dir if (repo_dir / ".git").exists() else None


def _git_short_hash(repo_dir: Path, rev: str) -> Optional[str]:
    """Resolve a git revision to an 8-character short hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short=8", rev],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    value = (result.stdout or "").strip()
    return value or None


def get_git_banner_state(repo_dir: Optional[Path] = None) -> Optional[dict]:
    """Return upstream/local git hashes for the startup banner."""
    repo_dir = repo_dir or _resolve_repo_dir()
    if repo_dir is None:
        return None

    upstream_ref = f"origin/{_UPSTREAM_BRANCH}"
    upstream = _git_short_hash(repo_dir, upstream_ref)
    local = _git_short_hash(repo_dir, "HEAD")
    if not upstream or not local:
        return None

    ahead = 0
    try:
        result = subprocess.run(
            ["git", "rev-list", "--count", f"{upstream_ref}..HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(repo_dir),
        )
        if result.returncode == 0:
            ahead = int((result.stdout or "0").strip() or "0")
    except Exception:
        ahead = 0

    return {"upstream": upstream, "local": local, "ahead": max(ahead, 0)}


_RELEASE_URL_BASE = "https://github.com/teddyjfpender/superforecasting-agent/releases/tag"
_latest_release_cache: Optional[tuple] = None  # (tag, url) once resolved


def get_latest_release_tag(repo_dir: Optional[Path] = None) -> Optional[tuple]:
    """Return ``(tag, release_url)`` for the latest git tag, or None.

    Local-only — runs ``git describe --tags --abbrev=0`` against the
    Superforecasting Agent checkout. Cached per-process. Release URL always
    points at the canonical fork repo.
    """
    global _latest_release_cache
    if _latest_release_cache is not None:
        return _latest_release_cache or None

    repo_dir = repo_dir or _resolve_repo_dir()
    if repo_dir is None:
        _latest_release_cache = ()  # falsy sentinel — skip future lookups
        return None

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(repo_dir),
        )
    except Exception:
        _latest_release_cache = ()
        return None

    if result.returncode != 0:
        _latest_release_cache = ()
        return None

    tag = (result.stdout or "").strip()
    if not tag:
        _latest_release_cache = ()
        return None

    url = f"{_RELEASE_URL_BASE}/{tag}"
    _latest_release_cache = (tag, url)
    return _latest_release_cache


def format_banner_version_label() -> str:
    """Return the version label shown in the startup banner title."""
    base = f"Superforecasting Agent v{VERSION} ({RELEASE_DATE})"
    state = get_git_banner_state()
    if not state:
        return base

    upstream = state["upstream"]
    local = state["local"]
    ahead = int(state.get("ahead") or 0)

    if ahead <= 0 or upstream == local:
        return f"{base} · upstream {upstream}"

    carried_word = "commit" if ahead == 1 else "commits"
    return f"{base} · upstream {upstream} · local {local} (+{ahead} carried {carried_word})"


# =========================================================================
# Non-blocking update check
# =========================================================================

_update_result: Optional[int] = None
_update_check_done = threading.Event()


def prefetch_update_check():
    """Kick off update check in a background daemon thread."""
    def _run():
        global _update_result
        _update_result = check_for_updates()
        _update_check_done.set()
    t = threading.Thread(target=_run, daemon=True)
    t.start()


def get_update_result(timeout: float = 0.5) -> Optional[int]:
    """Get result of prefetched check. Returns None if not ready."""
    _update_check_done.wait(timeout=timeout)
    return _update_result


# =========================================================================
# Build identity + staleness (the shape the TUI wire carries)
# =========================================================================


def _read_update_cache() -> dict:
    """Read the on-disk update-check cache. ``{}`` when absent or unreadable."""
    try:
        cached = json.loads((get_agent_home() / ".update_check").read_text())
    except Exception:
        return {}
    return cached if isinstance(cached, dict) else {}


def stale_build_remedy(install_method: Optional[str] = None) -> str:
    """The concrete command that REPLACES a stale build, per install lane.

    Deliberately not ``recommended_update_command()``: that answers "how do I
    upgrade the package", which for the git lane is a ``git pull`` that leaves an
    already-pipx-installed binary (and the TUI bundle frozen inside its venv)
    exactly as stale as it was.
    """
    try:
        from superforecasting_agent.runtime.config import (
            detect_install_method,
            get_managed_update_command,
            recommended_update_command_for_method,
        )
    except Exception:
        return _ONE_LINE_INSTALLER

    try:
        managed = get_managed_update_command()
        if managed:
            return managed
        method = install_method or detect_install_method()
    except Exception:
        return _ONE_LINE_INSTALLER

    if method in ("nixos", "homebrew", "docker"):
        try:
            return recommended_update_command_for_method(method)
        except Exception:
            return _ONE_LINE_INSTALLER
    if method == "git" and _resolve_repo_dir() is not None:
        return _REBUILD_AND_REINSTALL
    return _ONE_LINE_INSTALLER


def get_update_state(timeout: float = 0.0) -> dict:
    """The running build's identity plus the (best-effort) staleness verdict.

    NEVER performs a network call of its own. It reads whatever the already
    scheduled background check (``prefetch_update_check`` → ``check_for_updates``,
    itself cached on disk for 6 hours) has produced: the in-process result first,
    then the on-disk cache. So the default ``timeout=0.0`` call is a pure
    memory + one-small-file read and is safe on a startup path.

    Offline, every remote-derived key simply stays ``None``/``False`` — there is
    no error to surface and nothing to hang on.

    Keys: ``version``, ``release_date``, ``install_method``, ``latest_version``,
    ``behind`` (commits behind, ``-1`` when known-behind-but-uncountable),
    ``stale``, ``remedy``.
    """
    behind = get_update_result(timeout=timeout)
    cached = _read_update_cache()

    if behind is None:
        cached_behind = cached.get("behind")
        behind = cached_behind if isinstance(cached_behind, int) else None

    latest = _latest_version or (cached.get("latest") or None)

    stale = bool(behind)
    if not stale and latest:
        try:
            stale = _version_tuple(str(latest)) > _version_tuple(VERSION)
        except Exception:
            stale = False

    try:
        from superforecasting_agent.runtime.config import detect_install_method

        method = detect_install_method()
    except Exception:
        method = None

    return {
        "version": VERSION,
        "release_date": RELEASE_DATE,
        "install_method": method,
        "latest_version": str(latest) if latest else None,
        "behind": behind,
        "stale": stale,
        "remedy": stale_build_remedy(method),
    }


# =========================================================================
# Welcome banner
# =========================================================================

def _format_context_length(tokens: int) -> str:
    """Format a token count for display (e.g. 128000 → '128K', 1048576 → '1M')."""
    if tokens >= 1_000_000:
        val = tokens / 1_000_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}M"
        return f"{val:.1f}M"
    elif tokens >= 1_000:
        val = tokens / 1_000
        rounded = round(val)
        if abs(val - rounded) < 0.05:
            return f"{rounded}K"
        return f"{val:.1f}K"
    return str(tokens)


def _display_toolset_name(toolset_name: str) -> str:
    """Normalize internal/legacy toolset identifiers for banner display."""
    if not toolset_name:
        return "unknown"
    return (
        toolset_name[:-6]
        if toolset_name.endswith("_tools")
        else toolset_name
    )


def build_welcome_banner(console: Console, model: str, cwd: str,
                         tools: List[dict] = None,
                         enabled_toolsets: List[str] = None,
                         session_id: str = None,
                         get_toolset_for_tool=None,
                         context_length: int = None):
    """Build and print a welcome banner with forecast desk art on the left.

    Args:
        console: Rich Console instance.
        model: Current model name.
        cwd: Current working directory.
        tools: List of tool definitions.
        enabled_toolsets: List of enabled toolset names.
        session_id: Session identifier.
        get_toolset_for_tool: Callable to map tool name -> toolset name.
        context_length: Model's context window size in tokens.
    """
    from superforecasting_agent.tooling.runtime import check_tool_availability, TOOLSET_REQUIREMENTS
    if get_toolset_for_tool is None:
        from superforecasting_agent.tooling.runtime import get_toolset_for_tool

    tools = tools or []
    enabled_toolsets = enabled_toolsets or []

    _, unavailable_toolsets = check_tool_availability(quiet=True)
    disabled_tools = set()
    # Tools whose toolset has a check_fn are lazy-initialized (e.g. honcho,
    # homeassistant) — they show as unavailable at banner time because the
    # check hasn't run yet, but they aren't misconfigured.
    lazy_tools = set()
    for item in unavailable_toolsets:
        toolset_name = item.get("name", "")
        ts_req = TOOLSET_REQUIREMENTS.get(toolset_name, {})
        tools_in_ts = item.get("tools", [])
        if ts_req.get("check_fn"):
            lazy_tools.update(tools_in_ts)
        else:
            disabled_tools.update(tools_in_ts)

    layout_table = Table.grid(padding=(0, 2))
    layout_table.add_column("left", justify="center")
    layout_table.add_column("right", justify="left")

    # Resolve skin colors once for the entire banner
    accent = _skin_color("banner_accent", "#FFBF00")
    dim = _skin_color("banner_dim", "#B8860B")
    text = _skin_color("banner_text", "#FFF8DC")
    session_color = _skin_color("session_border", "#8B8682")

    # Use the skin's custom forecast hero art if provided.
    try:
        from superforecasting_agent.runtime.skin_engine import get_active_skin
        _bskin = get_active_skin()
        _hero = _bskin.banner_hero if hasattr(_bskin, 'banner_hero') and _bskin.banner_hero else FORECAST_DESK_MARK
    except Exception:
        _bskin = None
        _hero = FORECAST_DESK_MARK
    left_lines = ["", _hero, ""]
    model_short = model.split("/")[-1] if "/" in model else model
    if model_short.endswith(".gguf"):
        model_short = model_short[:-5]
    if len(model_short) > 28:
        model_short = model_short[:25] + "..."
    ctx_str = f" [dim {dim}]·[/] [dim {dim}]{_format_context_length(context_length)} context[/]" if context_length else ""
    left_lines.append(f"[{accent}]{model_short}[/]{ctx_str} [dim {dim}]·[/] [dim {dim}]Nous Research[/]")

    if _yolo_mode_enabled():
        left_lines.append(f"[bold red]⚠ YOLO mode[/] [dim {dim}]— all approval prompts bypassed[/]")
    left_lines.append(f"[dim {dim}]{cwd}[/]")
    if session_id:
        left_lines.append(f"[dim {session_color}]Session: {session_id}[/]")
    left_content = "\n".join(left_lines)

    right_lines = [f"[bold {accent}]Available Tools[/]"]
    toolsets_dict: Dict[str, list] = {}

    for tool in tools:
        tool_name = tool["function"]["name"]
        toolset = _display_toolset_name(get_toolset_for_tool(tool_name) or "other")
        toolsets_dict.setdefault(toolset, []).append(tool_name)

    for item in unavailable_toolsets:
        toolset_id = item.get("id", item.get("name", "unknown"))
        display_name = _display_toolset_name(toolset_id)
        if display_name not in toolsets_dict:
            toolsets_dict[display_name] = []
        for tool_name in item.get("tools", []):
            if tool_name not in toolsets_dict[display_name]:
                toolsets_dict[display_name].append(tool_name)

    sorted_toolsets = sorted(toolsets_dict.keys())
    display_toolsets = sorted_toolsets[:8]
    remaining_toolsets = len(sorted_toolsets) - 8

    for toolset in display_toolsets:
        tool_names = toolsets_dict[toolset]
        colored_names = []
        for name in sorted(tool_names):
            if name in disabled_tools:
                colored_names.append(f"[red]{name}[/]")
            elif name in lazy_tools:
                colored_names.append(f"[yellow]{name}[/]")
            else:
                colored_names.append(f"[{text}]{name}[/]")

        tools_str = ", ".join(colored_names)
        if len(", ".join(sorted(tool_names))) > 45:
            short_names = []
            length = 0
            for name in sorted(tool_names):
                if length + len(name) + 2 > 42:
                    short_names.append("...")
                    break
                short_names.append(name)
                length += len(name) + 2
            colored_names = []
            for name in short_names:
                if name == "...":
                    colored_names.append("[dim]...[/]")
                elif name in disabled_tools:
                    colored_names.append(f"[red]{name}[/]")
                elif name in lazy_tools:
                    colored_names.append(f"[yellow]{name}[/]")
                else:
                    colored_names.append(f"[{text}]{name}[/]")
            tools_str = ", ".join(colored_names)

        right_lines.append(f"[dim {dim}]{toolset}:[/] {tools_str}")

    if remaining_toolsets > 0:
        right_lines.append(f"[dim {dim}](and {remaining_toolsets} more toolsets...)[/]")

    # MCP Servers section (only if configured)
    try:
        from tools.mcp_tool import get_mcp_status
        mcp_status = get_mcp_status()
    except Exception:
        mcp_status = []

    if mcp_status:
        right_lines.append("")
        right_lines.append(f"[bold {accent}]MCP Servers[/]")
        for srv in mcp_status:
            if srv["connected"]:
                right_lines.append(
                    f"[dim {dim}]{srv['name']}[/] [{text}]({srv['transport']})[/] "
                    f"[dim {dim}]—[/] [{text}]{srv['tools']} tool(s)[/]"
                )
            else:
                right_lines.append(
                    f"[red]{srv['name']}[/] [dim]({srv['transport']})[/] "
                    f"[red]— failed[/]"
                )

    right_lines.append("")
    right_lines.append(f"[bold {accent}]Available Skills[/]")
    skills_by_category = get_available_skills()
    total_skills = sum(len(s) for s in skills_by_category.values())

    if skills_by_category:
        for category in sorted(skills_by_category.keys()):
            skill_names = sorted(skills_by_category[category])
            if len(skill_names) > 8:
                display_names = skill_names[:8]
                skills_str = ", ".join(display_names) + f" +{len(skill_names) - 8} more"
            else:
                skills_str = ", ".join(skill_names)
            if len(skills_str) > 50:
                skills_str = skills_str[:47] + "..."
            right_lines.append(f"[dim {dim}]{category}:[/] [{text}]{skills_str}[/]")
    else:
        right_lines.append(f"[dim {dim}]No skills installed[/]")

    right_lines.append("")
    mcp_connected = sum(1 for s in mcp_status if s["connected"]) if mcp_status else 0
    summary_parts = [f"{len(tools)} tools", f"{total_skills} skills"]
    if mcp_connected:
        summary_parts.append(f"{mcp_connected} MCP servers")
    summary_parts.append("/help for commands")
    # Indicate when the codex_app_server runtime is active so users
    # understand why tool counts may not match what's actually reachable
    # (codex builds its own tool list inside the spawned subprocess).
    try:
        from superforecasting_agent.runtime.codex_runtime_switch import get_current_runtime
        from superforecasting_agent.runtime.config import load_config as _load_cfg
        if get_current_runtime(_load_cfg()) == "codex_app_server":
            right_lines.append(
                f"[bold {accent}]Runtime:[/] [{text}]codex app-server[/] "
                f"[dim {dim}](terminal/file ops/MCP run inside codex)[/]"
            )
    except Exception:
        pass
    # Show active profile name when not 'default'
    try:
        from superforecasting_agent.runtime.profiles import get_active_profile_name
        _profile_name = get_active_profile_name()
        if _profile_name and _profile_name != "default":
            right_lines.append(f"[bold {accent}]Profile:[/] [{text}]{_profile_name}[/]")
    except Exception:
        pass  # Never break the banner over a profiles.py bug

    right_lines.append(f"[dim {dim}]{' · '.join(summary_parts)}[/]")

    # Update check — use prefetched result if available
    try:
        behind = get_update_result(timeout=0.5)
        if behind is not None and behind != 0:
            from superforecasting_agent.runtime.config import get_managed_update_command, recommended_update_command
            if behind > 0:
                commits_word = "commit" if behind == 1 else "commits"
                right_lines.append(
                    f"[bold yellow]⚠ {behind} {commits_word} behind[/]"
                    f"[dim yellow] — run [bold]{recommended_update_command()}[/bold] to update[/]"
                )
            else:
                # UPDATE_AVAILABLE_NO_COUNT: nix-built hermes; we know an update
                # exists but not by how much, and we don't know how the user
                # installed it (nix run, profile, system flake, home-manager).
                managed_cmd = get_managed_update_command()
                line = "[bold yellow]⚠ update available[/]"
                if managed_cmd:
                    line += f"[dim yellow] — run [bold]{managed_cmd}[/bold][/]"
                right_lines.append(line)
    except Exception:
        pass  # Never break the banner over an update check

    right_content = "\n".join(right_lines)
    layout_table.add_row(left_content, right_content)

    title_color = _skin_color("banner_title", "#FFD700")
    border_color = _skin_color("banner_border", "#CD7F32")
    version_label = format_banner_version_label()
    release_info = get_latest_release_tag()
    if release_info:
        _tag, _url = release_info
        title_markup = f"[bold {title_color}][link={_url}]{version_label}[/link][/]"
    else:
        title_markup = f"[bold {title_color}]{version_label}[/]"
    outer_panel = Panel(
        layout_table,
        title=title_markup,
        border_style=border_color,
        padding=(0, 2),
    )

    console.print()
    term_width = shutil.get_terminal_size().columns
    if term_width >= 95:
        _logo = _bskin.banner_logo if _bskin and hasattr(_bskin, 'banner_logo') and _bskin.banner_logo else _default_banner_logo()
        console.print(_logo)
        console.print()
    console.print(outer_panel)
