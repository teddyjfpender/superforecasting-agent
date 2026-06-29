"""Harness immutability wall for the forecast-desk AGENT's file-write tools.

The desk agent (the ``AIAgent`` the user runs — *not* Claude Code, *not* the
harness internals) is encouraged to freely write and run data-science code:
forecasting models, backtests, research scratchpads, scripts. It MUST NOT,
however, edit the harness source tree it is running inside. Letting the agent
patch its own code is a self-modification footgun: a single bad write to
``tools/file_tools.py`` or ``hermes_cli/`` could brick the running process,
silently disable a calibration gate, or exfiltrate behaviour.

This module is the single decision point for that wall. It answers one
question — *"is this resolved write target inside the harness source tree?"* —
and, if so, returns a clear, actionable error string for the agent's file-WRITE
tools (``write_file`` / ``patch``) to surface as the tool result. It NEVER
raises and NEVER blocks reads.

Scope (read this before touching the gate):

  * This guards the desk agent's ``file`` toolset write path in
    ``tools/file_tools.py`` (``check_harness_write`` — ENFORCED: write_file /
    patch hard-reject a harness target) and provides a BEST-EFFORT terminal
    redirect guard (``check_harness_command_write``). It does NOT touch Claude
    Code's own Edit/Write (a different tool layer), the harness's own internal
    file IO, or normal Python ``open(...,'w')`` calls anywhere in the codebase.
  * ALLOWED write zones: the sanctioned WORKSPACE
    (``<agent home>/workspace``), the existing scripts dir
    (``<agent home>/scripts``), anywhere under the agent home
    (``~/.superforecasting-agent``), and the system temp dir. These are the
    agent's sandbox for models/backtests/scratch.
  * REJECTED write zone: the harness SOURCE TREE — the installed package /
    repo root that contains this very module (detected via
    ``get_project_root()``), plus the directory tree that holds the package
    and its ``.git`` (the editable-install repo root).

HONEST residual gap — the terminal tool is not airtight:

  * The file TOOLS (``write_file`` / ``patch``) are genuinely gated: a write
    resolving into the harness source tree is hard-rejected.
  * The TERMINAL tool is NOT a sandbox. It is mitigated by THREE layers — (1)
    its default cwd is relocated OUT of the harness into the workspace when the
    process cwd would otherwise land in-tree (``tools/terminal_tool.py``), (2)
    a best-effort command guard here refuses the OBVIOUS shell write patterns
    (``echo … > <harness file>``, ``tee``), and (3) the soul / SKILL guidance
    tells the agent not to. But a determined script can still mutate the
    harness via Python ``open()``, ``cp``/``dd``/``install``, an env var, a
    sub-shell, or process substitution. We do NOT pretend command-parsing makes
    this airtight; closing it fully needs OS-level sandboxing.
  * By contrast, the forecast LEDGER is FULLY gated — at the SQLite-connection
    level (a ``set_authorizer`` in ``forecasting.ledger._connect``) — so even a
    terminal script that imports ``ForecastLedger`` or opens a raw connection
    CANNOT fabricate a forecast outside a recognised commit context. That is the
    high-value target; the harness-source wall is defence-in-depth around it.

The wall is a config flag (``harness_wall.enabled``, default ON) so it is
tunable for deployments that genuinely need the agent to edit harness source
(e.g. a self-improving dev loop running under explicit human supervision).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# Cache the resolved harness-source roots. They are fixed for the life of the
# process (the installed package does not move), so resolving once avoids a
# realpath walk on every single write.
_harness_roots_cache: Optional[tuple[Path, ...]] = None
_workspace_dir_cache: Optional[Path] = None


def _project_root() -> Optional[Path]:
    """Resolve the harness installation / repo root, or None on failure."""
    try:
        from hermes_cli.config import get_project_root  # local import, avoid cycles

        return get_project_root().resolve()
    except Exception:
        # Fall back to this file's package root: agent/ -> repo root.
        try:
            return Path(__file__).resolve().parent.parent
        except Exception:
            return None


def get_harness_source_roots() -> tuple[Path, ...]:
    """Return the set of directory roots that constitute the harness SOURCE TREE.

    A write whose resolved target lands inside any of these is rejected.
    We include:

      * ``get_project_root()`` — the canonical install/repo root.
      * The directory that physically contains this module's package, walked
        up to the nearest ancestor holding a ``.git`` (the editable-install
        repo root), so an editable ``pip install -e .`` checkout living
        somewhere other than ``get_project_root()`` is still covered.
    """
    global _harness_roots_cache
    if _harness_roots_cache is not None:
        return _harness_roots_cache

    roots: list[Path] = []

    pr = _project_root()
    if pr is not None:
        roots.append(pr)

    # Walk up from this file to the repo root (dir containing .git). This
    # catches editable installs whose source tree differs from the configured
    # project root.
    try:
        here = Path(__file__).resolve()
        for ancestor in here.parents:
            if (ancestor / ".git").exists():
                roots.append(ancestor)
                break
    except Exception:
        pass

    # Deduplicate while preserving order.
    seen: set[str] = set()
    deduped: list[Path] = []
    for r in roots:
        key = str(r)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    _harness_roots_cache = tuple(deduped)
    return _harness_roots_cache


def get_workspace_dir() -> Path:
    """Return the sanctioned WORKSPACE dir for the desk agent.

    This is ``<agent home>/workspace`` — the allowed write zone where the
    agent builds forecasting models, runs backtests, and keeps scratch
    calculations. The directory is created lazily here so callers (and the
    error message) can always point at a real path.
    """
    global _workspace_dir_cache
    if _workspace_dir_cache is not None:
        return _workspace_dir_cache
    try:
        from hermes_constants import get_hermes_home  # local import, avoid cycles

        home = get_hermes_home()
    except Exception:
        home = Path(os.path.expanduser("~/.superforecasting-agent"))
    ws = (home / "workspace").resolve()
    _workspace_dir_cache = ws
    return ws


def _agent_home() -> Path:
    """Resolve the agent home, with a stable fallback."""
    try:
        from hermes_constants import get_hermes_home

        return get_hermes_home().resolve()
    except Exception:
        return Path(os.path.expanduser("~/.superforecasting-agent")).resolve()


def _priority_allowed_roots() -> tuple[Path, ...]:
    """Write zones that win even over a harness-root reject.

    The workspace, the scripts dir, and the system temp dir. These are the
    agent's genuine model/backtest/scratch sandboxes; a harness repo checkout
    would never live INSIDE ``workspace/`` or ``scripts/``, so allowing them
    unconditionally is safe even when the agent home (pathologically) contains a
    harness checkout. ORDERING MATTERS: these are consulted BEFORE the
    harness-root reject (see ``_target_is_in_harness``).
    """
    home = _agent_home()
    roots = [home / "workspace", home / "scripts"]
    try:
        import tempfile

        roots.append(Path(tempfile.gettempdir()).resolve())
    except Exception:
        pass
    return tuple(roots)


def _broad_allowed_roots() -> tuple[Path, ...]:
    """The whole agent home — a BROAD allow that YIELDS to the harness reject.

    If a harness repo is checked out UNDER the agent home, a write into that
    checkout must be REJECTED (it is harness source), so the agent-home allow is
    consulted only AFTER the harness-root reject. (On the normal layout the
    agent home and the harness source tree are disjoint, so this ordering is
    invisible; it only matters for the nested-checkout pathology.)
    """
    return (_agent_home(),)


def _allowed_write_roots() -> tuple[Path, ...]:
    """All directory roots the agent MAY write to (priority + broad combined).

    Retained for callers/tests that just want the full allow set. The
    precedence between these and the harness reject is enforced in
    ``_target_is_in_harness`` (priority allows win, the broad agent-home allow
    yields to the harness reject).
    """
    return _priority_allowed_roots() + _broad_allowed_roots()


def _is_under(path: Path, root: Path) -> bool:
    """Return True if *path* equals *root* or is nested beneath it."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_harness_wall_enabled() -> bool:
    """Return True if the harness wall is active (config flag, default ON).

    Tunable via ``config.yaml``::

        harness_wall:
          enabled: false   # allow the agent to edit harness source

    Defaults to ON when the config is missing or unreadable — fail closed.
    """
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        section = cfg.get("harness_wall")
        if isinstance(section, dict) and "enabled" in section:
            return bool(section["enabled"])
        # Flat fallback: harness_wall_enabled: false
        if "harness_wall_enabled" in cfg:
            return bool(cfg["harness_wall_enabled"])
    except Exception:
        pass
    return True


def _resolve_target(filepath: str) -> Optional[Path]:
    """Resolve *filepath* to an absolute path without requiring it to exist.

    ``Path.resolve()`` handles non-existent leaves fine on modern Python; we
    still guard against exotic failures and return None so the caller falls
    through to allow (the wall never crashes a write).
    """
    try:
        return Path(os.path.expanduser(filepath)).resolve()
    except Exception:
        return None


def _target_is_in_harness(target: Optional[Path]) -> bool:
    """Return True iff *target* resolves into the harness source tree.

    Shared predicate for the file-tool wall (:func:`check_harness_write`) and the
    best-effort terminal redirect guard (:func:`check_harness_command_write`).

    Precedence (ordering is load-bearing — see the root helpers):

      1. PRIORITY allow zones (workspace / scripts / temp) win unconditionally —
         a harness checkout never lives inside these.
      2. Otherwise, a target under any harness SOURCE root is REJECTED. This is
         checked BEFORE the broad agent-home allow, so a harness repo checked
         out UNDER the agent home is still treated as immutable source (the
         harness reject takes precedence over the agent-home allow).
      3. Finally, the broad agent-home allow exempts the rest of the home.
    """
    if target is None:
        return False
    for allowed in _priority_allowed_roots():
        if _is_under(target, allowed):
            return False
    for root in get_harness_source_roots():
        if _is_under(target, root):
            return True
    for allowed in _broad_allowed_roots():
        if _is_under(target, allowed):
            return False
    return False


def _harness_write_error(filepath: str) -> str:
    """The actionable, agent-facing error for a refused harness write."""
    workspace = get_workspace_dir()
    return (
        "The harness is immutable from inside the agent — you cannot "
        "edit the code you run in. "
        f"Refused write to harness source: {filepath}\n"
        "Write forecasting models / backtests / scratch to your "
        f"workspace ({workspace}). "
        "To PROPOSE a harness change, write a patch + rationale into "
        "the workspace and flag it for human review."
    )


def check_harness_write(filepath: str, resolved: Optional[str] = None) -> Optional[str]:
    """Return an error string if writing *filepath* would edit the harness source.

    Args:
        filepath: The path the agent asked to write (for the error message).
        resolved: Optionally, the already-TERMINAL_CWD-resolved absolute path.
            ``tools/file_tools.py`` resolves against the task's live cwd, so it
            passes the resolved string to avoid a double / divergent resolve.

    Returns:
        ``None`` when the write is allowed. Otherwise a clear, actionable
        error message naming the workspace and the human-review escape hatch.
        The caller surfaces this as the tool result (it does NOT raise).
    """
    if not is_harness_wall_enabled():
        return None

    target: Optional[Path]
    if resolved:
        try:
            target = Path(resolved).resolve()
        except Exception:
            target = _resolve_target(filepath)
    else:
        target = _resolve_target(filepath)
    if target is None:
        return None  # can't resolve — don't block

    if _target_is_in_harness(target):
        return _harness_write_error(filepath)
    return None


# Shell redirect / pipe-to-file operators whose RHS is a write target. NOTE
# (read this before relying on it): this is a BEST-EFFORT guard, not a security
# boundary. The terminal tool is not a sandbox — there is no airtight way to
# block harness writes by parsing arbitrary shell. A determined script can still
# write the harness via Python ``open()``, ``cp``, ``dd``, ``install``, an env
# var, a sub-shell, etc. This catches the OBVIOUS, common cases (``echo … >
# harness_file``) and is layered behind the cwd redirect, the file-tool gate
# (which IS enforced), and soul guidance. The forecast LEDGER, by contrast, is
# FULLY gated at the SQLite-connection level (see forecasting.ledger), so even a
# terminal script cannot fabricate forecasts.
_REDIRECT_RE = re.compile(r"(?:^|\s)(?:\d*>>?|&>>?|>\|)\s*([^\s;|&()<>]+)")
_TEE_RE = re.compile(r"(?:^|[|;&]|\bsudo\s)\s*tee\s+(?:-[a-zA-Z]+\s+)*([^\s;|&()<>]+)")


def _candidate_redirect_targets(command: str) -> list[str]:
    """Extract obvious shell write targets (``>``/``>>``/``tee``) from *command*.

    Deliberately conservative — quoted/escaped exotica and process-substitution
    are out of scope (see the note on ``_REDIRECT_RE``). Returns the raw RHS
    path tokens; the caller resolves + judges them.
    """
    targets: list[str] = []
    if not command or not isinstance(command, str):
        return targets
    for m in _REDIRECT_RE.finditer(command):
        tok = m.group(1).strip().strip("'\"")
        # Skip fd-dup targets (`>&1`, `>&2`) and /dev/* sinks.
        if tok and not tok.startswith("&") and not tok.startswith("/dev/"):
            targets.append(tok)
    for m in _TEE_RE.finditer(command):
        tok = m.group(1).strip().strip("'\"")
        if tok and not tok.startswith("/dev/"):
            targets.append(tok)
    return targets


def check_harness_command_write(command: str, cwd: Optional[str] = None) -> Optional[str]:
    """Best-effort: refuse a terminal command that OBVIOUSLY writes the harness.

    Scans *command* for ``>``/``>>``/``tee`` write targets and, if any resolves
    (relative to *cwd*) into the harness source tree, returns the harness-wall
    error. This is NOT airtight — it cannot be, without a real sandbox — it only
    closes the cheap, obvious ``echo … > tools/file_tools.py`` hole that the cwd
    redirect alone does not (a redirect to an absolute or ``../``-escaping
    harness path ignores cwd). Returns ``None`` when nothing obviously targets
    the harness, or when the wall is disabled.
    """
    if not is_harness_wall_enabled():
        return None
    base = None
    if cwd:
        try:
            base = Path(os.path.expanduser(cwd))
        except Exception:
            base = None
    for tok in _candidate_redirect_targets(command):
        try:
            p = Path(os.path.expanduser(tok))
            if not p.is_absolute() and base is not None:
                p = base / p
            target = p.resolve()
        except Exception:
            continue
        if _target_is_in_harness(target):
            return _harness_write_error(tok)
    return None


def reset_caches() -> None:
    """Clear the module-level path caches. Test hook only."""
    global _harness_roots_cache, _workspace_dir_cache
    _harness_roots_cache = None
    _workspace_dir_cache = None
