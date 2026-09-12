"""Skip policy + hermetic environment for the real-terminal TUI tests.

These tests need three things the ordinary Python suite does not: a POSIX
pseudo-terminal, a ``node`` on PATH, and a built TUI bundle.  When any is
missing they SKIP with the reason spelled out — a contributor without node
must never see a red suite because of this directory.

They are additionally marked ``tui_pty`` so the whole group can be excluded
with ``-m "not tui_pty"``, and can be switched off wholesale with
``HERMES_SKIP_TUI_PTY_TESTS=1``.  The marker is registered here rather than in
``pyproject.toml`` so this directory is self-contained.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# scripts/lib/node-bootstrap.sh pins the same floor: the launcher provisions
# node >= 20 because node 18 rejects `--expose-gc` in NODE_OPTIONS (which the
# TUI sets).  A contributor on distro node 18 should get an honest skip, not a
# baffling child-process failure.
MIN_NODE_MAJOR = 20

# Source-tree tests prefer the current development build. The canonical test
# runner rebuilds it when the local Node toolchain is installed. Packaged-only
# environments can still exercise their supplied distribution artifact.
BUNDLE_CANDIDATES = (
    REPO_ROOT / "ui-tui" / "dist" / "entry.js",
    REPO_ROOT / 'superforecasting_agent/runtime' / "tui_dist" / "entry.js",
)

# ``ui-tui/src/entry.tsx`` prints this and exits 0 when stdin is not a TTY.
NO_TTY_SENTINEL = b"no TTY"

# First paint must land inside this many seconds.  Reference points measured on
# a 2024 laptop: node parses the 4.5MB bundle in 0.09s, ``import
# tui_gateway.server`` takes 0.6s, and the observed first paint (which requires
# BOTH, plus a gateway RPC round trip) is ~0.7s.  15s is ~20x headroom for a
# cold, loaded CI runner while still catching a real regression -- the class of
# bug this guards against (a synchronous ledger read on the boot path) moved
# first paint by seconds, not milliseconds.  Override for slow boxes.
FIRST_PAINT_BUDGET_S = float(os.environ.get("HERMES_TUI_PTY_FIRST_PAINT_BUDGET_S", "15"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "tui_pty: real-terminal TUI tests. Those that boot the bundle need "
        "node + a built ui-tui bundle + POSIX pty and skip cleanly without "
        'them. Exclude the group with -m "not tui_pty" or '
        "HERMES_SKIP_TUI_PTY_TESTS=1.",
    )
    config.addinivalue_line(
        "markers",
        "desk_budget: the Desk load budget. Generates a synthetic ledger "
        "(a few seconds) and needs no node/pty. Exclude on its own with "
        '-m "not desk_budget".',
    )


def find_bundle() -> Path | None:
    return next((p for p in BUNDLE_CANDIDATES if p.is_file()), None)


def node_major(node: str) -> int | None:
    """Major version of *node*, or None if it cannot be determined."""
    try:
        out = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=20
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"v?(\d+)\.", out.strip())
    return int(match.group(1)) if match else None


def skip_reason() -> str | None:
    """Why these tests cannot run here, or None when they can."""
    if os.environ.get("HERMES_SKIP_TUI_PTY_TESTS", "").strip() not in ("", "0"):
        return "HERMES_SKIP_TUI_PTY_TESTS is set"
    if sys.platform == "win32":
        return "pseudo-terminals are POSIX-only (Windows is supported via WSL)"
    if not hasattr(os, "login_tty"):
        return "os.login_tty is unavailable on this platform"
    node = shutil.which("node")
    if node is None:
        return "node is not on PATH (the TUI bundle is a node program)"
    major = node_major(node)
    if major is not None and major < MIN_NODE_MAJOR:
        return (
            f"node {major} is older than the supported floor of "
            f"{MIN_NODE_MAJOR} (see scripts/lib/node-bootstrap.sh)"
        )
    if find_bundle() is None:
        return (
            "no built TUI bundle found at "
            + " or ".join(str(p.relative_to(REPO_ROOT)) for p in BUNDLE_CANDIDATES)
            + " (build it with: cd ui-tui && npm run build)"
        )
    return None


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Mark this directory ``tui_pty``, and skip only what truly needs a bundle.

    Not everything here drives a terminal: ``test_vt_screen.py`` unit-tests the
    screen emulator (it must run everywhere -- a wrong emulator turns every
    other assertion in this directory into a lie) and
    ``test_desk_load_budget.py`` measures SQLite work in-process.  Both must
    keep running on a box with no node.

    Which tests need the bundle is derived from **whether they request the
    ``tui_bundle`` fixture**, rather than from a hand-maintained list of
    filenames or markers.  ``item.fixturenames`` is the full transitive
    closure, so a test that boots the TUI cannot avoid appearing in it -- the
    rule stays correct on its own as files are added, instead of drifting the
    first time someone forgets to mark one.

    Note this hook is handed the WHOLE session's items even though it lives in
    a directory conftest -- hence the cheap prefix test before any real work,
    and the lazily-computed skip reason (which shells out to ``node --version``).
    """
    here = f"{Path(__file__).parent}{os.sep}"
    reason: str | None = None
    resolved = False

    for item in items:
        path = str(getattr(item, "path", "") or item.fspath)
        if not path.startswith(here):
            continue
        item.add_marker(pytest.mark.tui_pty)
        if path.endswith("test_desk_load_budget.py"):
            item.add_marker(pytest.mark.desk_budget)
        if "tui_bundle" not in getattr(item, "fixturenames", ()):
            continue
        if not resolved:
            reason, resolved = skip_reason(), True
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"TUI pty tests: {reason}"))


@pytest.fixture()
def tui_bundle() -> Path:
    bundle = find_bundle()
    assert bundle is not None, "collection should have skipped without a bundle"
    return bundle


@pytest.fixture()
def tui_home(tmp_path: Path) -> Path:
    """A pristine, deterministic agent home for one TUI boot.

    Pristine matters: it is what makes the boot hermetic (no operator ledger,
    no saved provider) AND what makes the first-paint content deterministic --
    with no provider configured the TUI lands on its Setup Required panel.
    """
    home = tmp_path / "tui-home"
    (home / ".superforecasting-agent").mkdir(parents=True)
    return home


@pytest.fixture()
def tui_env(tui_home: Path) -> dict[str, str]:
    """A from-scratch environment for the TUI child process.

    Built by allowlist rather than by copying ``os.environ`` so no operator
    credential, provider key or ``SUPERFORECASTING_AGENT_*`` override can leak
    in and change what the app renders.  That is what makes the Setup Required
    assertion deterministic on a developer laptop as well as on CI.
    """
    agent_home = str(tui_home / ".superforecasting-agent")
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tui_home),
        "TERM": "xterm-256color",
        # All three aliases: superforecasting_agent.constants resolves the first one set.
        "SUPERFORECASTING_AGENT_HOME": agent_home,
        "FORECAST_HOME": agent_home,
        "HERMES_HOME": agent_home,
        # The TUI spawns `python -m tui_gateway.entry`; point it at the
        # interpreter running the tests (which necessarily has this repo
        # importable) rather than letting it guess at .venv/ or python3.
        "SUPERFORECASTING_AGENT_PYTHON": sys.executable,
        "SUPERFORECASTING_AGENT_PYTHON_SRC_ROOT": str(REPO_ROOT),
        "SUPERFORECASTING_AGENT_CWD": str(REPO_ROOT),
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONIOENCODING": "utf-8",
        # Mirrors superforecasting_agent.runtime.main._launch_tui, with a smaller heap: an 8GB
        # max-old-space is pointless for a 2-second boot and antagonises
        # memory-capped CI containers.
        "NODE_OPTIONS": "--max-old-space-size=2048 --expose-gc",
        "AWS_EC2_METADATA_DISABLED": "true",
        "HERMES_DISABLE_LAZY_INSTALLS": "1",
    }


# ── Synthetic ledgers ──────────────────────────────────────────────────────
# Session-scoped because generation goes through the real ledger API and costs
# ~1.7s for the large book. They live under tmp_path_factory and are handed to
# callers by explicit path -- nothing here can reach an operator's real ledger.
#
# Under xdist these are built once per WORKER that needs one (measured: 4 large
# builds with -n auto on an 8-core box), because pytest session scope is
# per-process. That is deliberate. The fix would be a cross-worker cache behind
# a file lock, and a stale lock left by a crashed worker turns a fast test
# directory into a hung one -- a bad trade for ~5s of parallel CPU. Wall clock
# is unaffected: the whole directory runs in ~9s under -n auto, faster than
# serially, because the builds overlap.


def _build_book(tmp_path_factory, name: str, spec) -> dict:
    import time

    from .synthetic_ledger import build_synthetic_ledger

    root = tmp_path_factory.mktemp(f"ledger-{name}")
    started = time.perf_counter()
    built = build_synthetic_ledger(root / "forecasting" / "forecasting.db", spec)
    built["build_seconds"] = round(time.perf_counter() - started, 2)
    return built


@pytest.fixture(scope="session")
def small_book(tmp_path_factory) -> dict:
    from .synthetic_ledger import SMALL_BOOK

    return _build_book(tmp_path_factory, "small", SMALL_BOOK)


@pytest.fixture(scope="session")
def large_book(tmp_path_factory) -> dict:
    from .synthetic_ledger import LARGE_BOOK

    return _build_book(tmp_path_factory, "large", LARGE_BOOK)


@pytest.fixture()
def tui_home_with_large_book(tui_home: Path, large_book: dict) -> dict:
    """Install the large synthetic book as the TUI child's real ledger.

    Copies rather than points at it so a TUI run can never mutate the shared
    session fixture. The ``-wal``/``-shm`` siblings come too: the ledger runs in
    WAL mode, and copying the main file alone can hand over a database missing
    its most recent committed pages.
    """
    source = Path(large_book["db_path"])
    target = tui_home / ".superforecasting-agent" / "forecasting" / "forecasting.db"
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        sibling = Path(str(source) + suffix)
        if sibling.exists():
            shutil.copy2(sibling, str(target) + suffix)
    return large_book
