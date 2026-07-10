# Ownership map + extension-point checklists

The formality layer of the modularization program
(`docs/plans/2026-07-10-modularization-program.md` §W0.4). Two things live here:

1. **The module ownership table** — for each fork-owned package: its layer, its
   public façade, and what it must **not** import (enforced by the import-linter
   contracts in `pyproject.toml [tool.importlinter]`, CI `lint.yml →
   lint-architecture`).
2. **Per-extension-point checklists** — for each common feature shape, the ONE
   module you touch, the registry that auto-wires it, and the test that pins it.
   The goal of the whole program: a new feature touches one small module, never a
   megafile.

---

## 1. Module ownership

| Package | Layer | Public façade | Must NOT import (contract) |
|---|---|---|---|
| `protocol/` | kernel (wire contracts) | pydantic models under `protocol/rpc`, `protocol/events`; `generated.ts` is generated from it | **anything app-side** — `forecasting`, `tools`, `agent`, `gateway`, `tui_gateway`, `hermes_cli`, `run_agent`, `cli` (Tier-1 contract, enforced) |
| `forecasting/` | domain (ledger, scoring, quorum, CLI) | `forecasting.ledger`, `forecasting.cli` (façade packages), `forecasting.models` | `tui_gateway` (Tier-1); `hermes_cli` + `tools` are **ratcheted** (frozen lists in pyproject — may only shrink) |
| `forecasting/ledger/` | domain leaf | `forecasting/ledger/__init__` (monkeypatch-forwarding façade over `core.py` + leaves) | `forecasting.cli` (Tier-1) |
| `forecasting/cli/` | surface (argparse assembler) | `forecasting/cli/__init__` (`_CliPackage` forwarding façade) | — |
| `tools/` | tools | `tools.registry`; `tools.forecast_actions.ACTIONS` | `run_agent` (ratchet) |
| `tui_gateway/` | surface (RPC) | `@rpc_validated` handlers; carved `*_rpc.py` families | `run_agent` (ratchet); imports `forecasting` one-way (clean) |
| `agent/`, `gateway/`, `hermes_cli/` | upstream-shared runtime | — | `run_agent` (ratchet — the inverted entry-script edge) |

**`run_agent.py` / `cli.py` are top-level modules, not packages** (the inverted
`* → run_agent` edge is frozen at 21 direct importers; burn down opportunistically
by hoisting the imported name into `agent/`).

### The façade pattern (every carved package)

`__init__.py` installs a `ModuleType` subclass whose `__getattr__` read-forwards
to `core` and whose `__setattr__`/`__delattr__` write-forward when `core` owns the
name — so `from pkg import _private`, `pkg._private`, and
`monkeypatch.setattr(pkg, "_private", …)` all keep working after a body moves to
`core` or a leaf. See `forecasting/cli/__init__.py` and
`forecasting/ledger/__init__.py`.

---

## 2. Extension-point checklists

Each row of the program's seam audit, written from the "after" column. **One
module, one registry, one test.**

### New gate rule (saturation / style hook)

- **Touch:** `forecasting/hooks/builtins.py` — add the rule + its remediation text
  to `BUILTIN_RULES`. (User-authored rules load from the DSL via
  `forecasting/hooks/loader.py` — no code change.)
- **Auto-wires:** `BUILTIN_RULES` is read by `forecasting/hooks/engine.py`.
- **Test:** `tests/forecasting/test_hooks_*.py` — assert the rule fires + the
  remediation string.

### New tool action (`forecast_ledger` verb)

- **Touch:** `tools/forecast_actions/<domain>.py` — add `action -> handler(args,
  ledger)` to that module's `HANDLERS` (or add a new domain module — it is
  auto-discovered).
- **Auto-wires:** `tools/forecast_actions/__init__.py` aggregates every module's
  `HANDLERS` into `ACTIONS`; `forecast_ledger_tool` dispatches on it. No central
  edit.
- **Test:** `tests/tools/test_forecast_actions*.py` (or the domain's test) — call
  the action through `ACTIONS`.

### New job type (durable background job)

- **Touch:** `forecasting/jobs/types/<name>.py` — define a `JobType` and call
  `register(<NAME>)` at module bottom (the pattern in `backup.py`,
  `reforecast.py`).
- **Auto-wires:** `forecasting/jobs/types.register` + `registered_types`; the job
  store/runtime dispatch on the registered type. Add the module to the package's
  import surface if it is not import-triggered.
- **Test:** `tests/forecasting/test_*_jobs.py` — enqueue + run the type; assert the
  record transitions.

### New CLI domain (`forecast <verb>`)

- **Touch:** `forecasting/cli/<domain>.py` — a module exposing
  `register(forecast_sub)` (add subparsers + `set_defaults(_forecast_handler=…)`)
  and its handlers. Reach `_ledger` via a call-time `_core._ledger` hop; import
  shared helpers bare from `forecasting.cli.core`.
- **Wire once:** one `from forecasting.cli import <domain> as _X` at the bottom of
  `core.py` + one `_X.register(forecast_sub)` call at the intended position inside
  `register_cli` (position = help-tree order; use one hook per contiguous block).
- **Auto-wires:** nothing else — the assembler calls `register()` hooks in order.
- **Test:** `tests/forecasting/test_cli.py`; the `dump_help_tree.py` +
  `dump_order.py` gates confirm byte-identical help.
- Precedents: `jobs_admin.py`, `curate.py`, `thesis.py`, and the Wave-1 eight
  (`doctor_admin`, `reviews`, `quorum_panel`, `markets_pm`, `triage_calibration`,
  `benchmarks`, `questions_admin`, `refresh_cycle`).

### New notify surface (delivery channel)

- **Touch:** `forecasting/notify.py` — add the surface name to `SURFACES` and a
  delivery branch in `NotifyRouter._deliver_one`.
- **Auto-wires:** routes bind by surface name (`routes.json`); `deliver_event` /
  `deliver_digest` fan out to every accepting route.
- **Test:** `tests/forecasting/test_notify*.py` — bind a route on the new surface,
  assert `deliveries.json` records an attempt.

---

## 3. The gates that keep this true

| Concern | Gate | Where |
|---|---|---|
| Import directions | `lint-imports` (import-linter) | `pyproject.toml [tool.importlinter]`, CI `lint.yml → lint-architecture` |
| Moves-only carves | difflib categorizer, help-tree + order dumps | `scripts/carve/` (see its README) |
| Blame through carves | `.git-blame-ignore-revs` | `scripts/install-hooks.sh` sets `blame.ignoreRevsFile` |
| Wire compatibility | protocol codegen staleness | `scripts/check-protocol.sh` |
| Oversize refactor | `MOVES-ONLY` marker gate | `.githooks/lib/checks.sh` |
