#!/usr/bin/env python3
"""Desk-load performance benchmark for the superforecasting-agent TUI.

This is the "serious" perf harness for the launch -> usable-desk path. It times
each NAMED phase of the desk-load sequence with real numbers, prints a sorted
breakdown + a total, and exits non-zero when any phase blows its budget. It is
safe to re-run and to wire into CI.

The desk loads in three layers:

  1. Python gateway cold-boot   -- importing tui_gateway.entry (which pulls in
     tui_gateway.server + the forecasting stack) and opening the ledger.
  2. forecast.workspace RPC     -- forecasting.dashboard.build_workspace_payload
     against the live ledger DB (the data the desk actually renders).
  3. Ink TUI render             -- node evaluates the prebuilt dist/entry.js and
     React reconciles. (Measured here only as node-startup + bundle size; the
     React render itself is owned by the JS layer and is not timed in-process.)

Phases timed
------------
  gateway-import      cold ``import tui_gateway.entry`` in a fresh subprocess
                      (process spawn + every transitive import).
  ledger-construct    ``ForecastLedger()`` -- connect + schema init/migrate.
  workspace-rpc       ``build_workspace_payload(...)`` with the exact flags the
                      live ``forecast.workspace`` RPC uses (limit=1000,
                      include_related=False, include_lessons=False,
                      history_limit=40).
  ledger-gate         the SQLite write-gate authorizer overhead: workspace-rpc
                      WITH the authorizer installed minus WITHOUT it (delta).
  plugin-discovery    ``superforecasting_agent.runtime.plugins.discover_plugins()`` (only runs on a
                      real desk boot when unresolved explicit TOOLSETS are set;
                      timed here for completeness).
  e2e-gateway-stdio   spawn ``python -m tui_gateway.entry`` and time from spawn
                      to the first ``forecast.workspace`` response over stdio.
                      This is the true Python "boot -> usable data" number.
  esbuild-rebuild     (node phase, --with-node only) ``npm run build`` for the
                      Ink bundle -- the cost paid on every dev `--tui` launch.
  node-startup        (node phase, --with-node only) bare ``node -e 0``.

Usage
-----
    .venv/bin/python scripts/benchmark_tui_perf.py            # python phases
    .venv/bin/python scripts/benchmark_tui_perf.py --with-node
    .venv/bin/python scripts/benchmark_tui_perf.py --json
    .venv/bin/python scripts/benchmark_tui_perf.py --repeat 9

Exit code is non-zero if any measured phase exceeds its budget (see BUDGETS_MS),
so this doubles as a regression gate. Override the DB with FORECAST_LEDGER_DB.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Per-phase budgets (milliseconds). A phase that exceeds its budget fails the
# run. Budgets are deliberately ~2-3x the observed live numbers so this gates
# real regressions, not noise. Tune as the platform changes.
BUDGETS_MS: dict[str, float] = {
    "gateway-import": 1200.0,
    "ledger-construct": 80.0,
    "workspace-rpc": 1500.0,
    "ledger-gate": 80.0,        # authorizer delta should be ~0
    "plugin-discovery": 600.0,
    "e2e-gateway-stdio": 3500.0,
    "esbuild-rebuild": 2500.0,
    "node-startup": 600.0,
}

WORKSPACE_KW = dict(
    limit=1000, include_related=False, include_lessons=False, history_limit=40
)

# Phases that DECOMPOSE a composite phase (they measure a slice of work already
# counted inside e2e-gateway-stdio) and so must NOT be summed into the launch
# total -- they are diagnostic attribution, not additive wall time. ledger-gate
# is a delta (overhead), also non-additive.
DECOMPOSITION_PHASES = frozenset(
    {"gateway-import", "ledger-construct", "workspace-rpc",
     "plugin-discovery", "ledger-gate"}
)


def _median(samples: list[float]) -> float:
    return statistics.median(samples) if samples else float("nan")


def _time(fn, repeat: int, warmup: int = 1) -> float:
    """Return the median wall time (ms) of ``fn`` over ``repeat`` runs."""
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(repeat):
        s = time.perf_counter()
        fn()
        out.append((time.perf_counter() - s) * 1000.0)
    return _median(out)


# --------------------------------------------------------------------------- #
# Phases
# --------------------------------------------------------------------------- #
def phase_gateway_import(repeat: int) -> float:
    """Cold ``import tui_gateway.entry`` in a fresh subprocess (median)."""
    samples = []
    for _ in range(repeat):
        s = time.perf_counter()
        r = subprocess.run(
            [sys.executable, "-c", "import tui_gateway.entry"],
            cwd=str(REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        dt = (time.perf_counter() - s) * 1000.0
        if r.returncode == 0:
            samples.append(dt)
    return _median(samples)


def phase_ledger_construct(repeat: int) -> float:
    from forecasting.ledger import ForecastLedger

    return _time(lambda: ForecastLedger(), repeat)


def phase_workspace_rpc(repeat: int) -> float:
    from forecasting.dashboard import build_workspace_payload
    from forecasting.ledger import ForecastLedger

    led = ForecastLedger()
    return _time(lambda: build_workspace_payload(ledger=led, **WORKSPACE_KW), repeat)


def phase_ledger_gate(repeat: int) -> float:
    """Authorizer overhead = workspace-rpc(with authorizer) - workspace-rpc(without).

    The write-gate installs a per-statement SQLite authorizer on EVERY ledger
    connection (``ForecastLedger._connect``). This isolates its true cost by
    monkeypatching ``_connect`` to skip ``set_authorizer`` and re-timing. The
    delta is the honest number for "what the gate costs a read-heavy boot".
    """
    import sqlite3

    from forecasting.dashboard import build_workspace_payload
    from forecasting.ledger import ForecastLedger

    led = ForecastLedger()
    with_auth = _time(
        lambda: build_workspace_payload(ledger=led, **WORKSPACE_KW), repeat
    )

    orig = ForecastLedger._connect

    def _no_auth(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    try:
        ForecastLedger._connect = _no_auth
        led2 = ForecastLedger()
        without_auth = _time(
            lambda: build_workspace_payload(ledger=led2, **WORKSPACE_KW), repeat
        )
    finally:
        ForecastLedger._connect = orig

    return max(0.0, with_auth - without_auth)


def phase_plugin_discovery(repeat: int) -> float:
    from superforecasting_agent.runtime.plugins import discover_plugins

    # First call does the real work; force=True keeps each sample comparable.
    return _time(lambda: discover_plugins(force=True), repeat, warmup=0)


def phase_e2e_gateway_stdio(repeat: int) -> float:
    """Spawn the gateway and time spawn -> first forecast.workspace response."""
    samples = []
    for _ in range(repeat):
        proc = subprocess.Popen(
            [sys.executable, "-m", "tui_gateway.entry"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            cwd=str(REPO_ROOT),
        )
        spawn = time.perf_counter()
        try:
            req = {"id": "bench-1", "method": "forecast.workspace",
                   "params": {"limit": 1000}}
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            deadline = time.time() + 30
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if obj.get("id") == "bench-1":
                    samples.append((time.perf_counter() - spawn) * 1000.0)
                    break
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
    return _median(samples)


def phase_esbuild_rebuild(repeat: int) -> float:
    tui_dir = REPO_ROOT / "ui-tui"
    npm = _which("npm")
    if npm is None or not (tui_dir / "package.json").is_file():
        return float("nan")
    samples = []
    for _ in range(repeat):
        s = time.perf_counter()
        r = subprocess.run(
            [npm, "run", "build"],
            cwd=str(tui_dir),
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            samples.append((time.perf_counter() - s) * 1000.0)
    return _median(samples)


def phase_node_startup(repeat: int) -> float:
    node = _which("node")
    if node is None:
        return float("nan")
    samples = []
    for _ in range(repeat):
        s = time.perf_counter()
        subprocess.run([node, "-e", "0"], capture_output=True)
        samples.append((time.perf_counter() - s) * 1000.0)
    return _median(samples)


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
PYTHON_PHASES = [
    ("gateway-import", phase_gateway_import),
    ("ledger-construct", phase_ledger_construct),
    ("workspace-rpc", phase_workspace_rpc),
    ("ledger-gate", phase_ledger_gate),
    ("plugin-discovery", phase_plugin_discovery),
    ("e2e-gateway-stdio", phase_e2e_gateway_stdio),
]
NODE_PHASES = [
    ("esbuild-rebuild", phase_esbuild_rebuild),
    ("node-startup", phase_node_startup),
]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", type=int, default=5,
                    help="samples per phase (median reported; default 5)")
    ap.add_argument("--with-node", action="store_true",
                    help="also time the node/esbuild phases")
    ap.add_argument("--json", action="store_true",
                    help="emit machine-readable JSON instead of a table")
    ap.add_argument("--no-budget", action="store_true",
                    help="report only; never exit non-zero on a budget breach")
    args = ap.parse_args(argv)

    phases = list(PYTHON_PHASES)
    if args.with_node:
        phases += NODE_PHASES

    db = os.getenv("FORECAST_LEDGER_DB", "(default ~/.superforecasting-agent/...)")
    results: dict[str, float] = {}
    for name, fn in phases:
        try:
            results[name] = fn(args.repeat)
        except Exception as exc:  # a phase failing must not abort the suite
            print(f"  ! phase {name} errored: {exc}", file=sys.stderr)
            results[name] = float("nan")

    # Launch total = the composite e2e boot + the node phases that run around it.
    # The decomposition phases are slices of e2e and must not be summed in.
    additive = {k: v for k, v in results.items()
                if k not in DECOMPOSITION_PHASES}
    total = sum(v for v in additive.values() if v == v)  # skip NaN

    breaches = []
    for name, val in results.items():
        budget = BUDGETS_MS.get(name)
        if budget is not None and val == val and val > budget:
            breaches.append((name, val, budget))

    if args.json:
        print(json.dumps({
            "db": db,
            "phases_ms": results,
            "total_additive_ms": total,
            "budgets_ms": BUDGETS_MS,
            "breaches": [{"phase": n, "ms": v, "budget_ms": b}
                         for n, v, b in breaches],
        }, indent=2))
    else:
        print(f"\nDesk-load perf benchmark  (DB: {db})")
        print(f"  repeat={args.repeat}  node={'on' if args.with_node else 'off'}\n")
        print(f"  {'phase':<20} {'median ms':>12} {'budget':>10}  status")
        print(f"  {'-'*20} {'-'*12} {'-'*10}  {'-'*6}")
        for name, val in sorted(results.items(), key=lambda kv: (-kv[1] if kv[1] == kv[1] else 0)):
            budget = BUDGETS_MS.get(name)
            disp = f"{val:12.1f}" if val == val else f"{'n/a':>12}"
            bdisp = f"{budget:10.0f}" if budget else f"{'-':>10}"
            status = "ok"
            if val != val:
                status = "skip"
            elif budget and val > budget:
                status = "OVER"
            note = ""
            if name == "ledger-gate":
                note = "  (gate overhead delta)"
            elif name in DECOMPOSITION_PHASES:
                note = "  (decomposes e2e)"
            print(f"  {name:<20} {disp} {bdisp}  {status}{note}")
        print(f"  {'-'*20} {'-'*12}")
        print(f"  {'LAUNCH TOTAL':<20} {total:12.1f} ms"
              "   (e2e boot + node phases; decomposition rows excluded)\n")

    if breaches and not args.no_budget:
        print(f"FAIL: {len(breaches)} phase(s) over budget: "
              f"{', '.join(n for n, _, _ in breaches)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
