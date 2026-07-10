# `scripts/carve/` — the moves-only carve toolkit

Versioned tooling for **moves-only refactor slices** (CONTRIBUTING → "Moves-only
refactor slices"; the 2026-07-10 modularization program §W0.3). Arc D proved the
method from session scratch; this directory makes it reproducible so every wave
does not re-derive it from transcripts.

A carve relocates method bodies **verbatim** out of a shrinking megafile into a
sibling module, leaving one-line delegates / imports / façade re-bindings behind.
It changes nothing else — proven *mechanically*, never by eyeball.

## The scripts

| Script | Role |
|---|---|
| `analyze_domain.py` | **Membership by caller-exclusivity** (never adjacency). Given the domain's seed handlers, reports which private helpers are used *only* within the domain closure (MOVABLE) vs. also used outside (SHARED → stay in core, import bare). Propagates "staying" inward: a helper reached only through a shared helper stays too. |
| `deps.py` | **Free-name dependency report** for the moved set: every core-level name the moved bodies reference, split into BARE imports (`from …core import …`) and PATCHED names that must be reached via a call-time `_core.` hop (monkeypatch discipline). |
| `extract.py` | **AST extractor** (decorator-aware `end_lineno`). `--list` prints ranges, `--emit-bodies` slices bodies verbatim, `--strip` writes core with those ranges removed. Never reformats, never regex. |
| `verify_moves.py` | **The difflib gate.** Diffs the shrinking file vs. `--base` (default HEAD) and fails if any *added* line is not a delegate / import / façade re-bind / comment. "Zero unexpected added lines" is checkable, not vibes. |
| `dump_help_tree.py` | Structural dump of the `forecast` parser tree (args, defaults, handler wiring, sorted). The CLI acceptance gate: a carve keeps it **byte-identical**. Robust to help strings containing `%` (which argparse's lazy `help % params` mishandles). |
| `dump_order.py` | The `forecast` subcommand names in **registration order** — catches an accidental reorder that the sorted tree dump would hide (a register hook moved to the wrong position). |

## The per-slice recipe (CLI domain carve)

```bash
# 0. baselines (once per session)
python scripts/carve/dump_help_tree.py > /tmp/help_base.txt
python scripts/carve/dump_order.py     > /tmp/order_base.txt

# 1. membership + deps
python scripts/carve/analyze_domain.py _cmd_foo _cmd_bar        # -> MOVABLE / SHARED
python scripts/carve/deps.py _cmd_foo _cmd_bar _helper          # -> imports + hops

# 2. build the new module: header + imports + _ledger/_core hops +
#    register(forecast_sub) (the reg block, verbatim) + the emitted bodies
python scripts/carve/extract.py forecasting/cli/core.py --emit-bodies <names> > bodies.py

# 3. strip core, replace the reg block with `_domain.register(forecast_sub)`,
#    add the bottom `from forecasting.cli import <domain>` + re-bind any name a
#    TEST imports from the façade (grep tests for cli.<name> / from forecasting.cli import <name>)
python scripts/carve/extract.py forecasting/cli/core.py --strip core_new.py <names>

# 4. gates — all must pass
python -c "import forecasting.cli"                                        # 0 import errors
python scripts/carve/dump_help_tree.py | cmp - /tmp/help_base.txt         # byte-identical
python scripts/carve/dump_order.py     | cmp - /tmp/order_base.txt        # byte-identical
python scripts/carve/verify_moves.py --file forecasting/cli/core.py --moved-into forecasting/cli/<domain>.py
ruff check --select F401,F811,F821,PLW1514 forecasting/cli/<domain>.py    # F821 catches missed imports
pytest tests/forecasting/test_cli.py <domain-specific tests>              # green before AND after
```

## The findings ledger (hard-won rules)

- **Membership is caller-exclusivity, not adjacency.** `analyze_domain.py` is the
  arbiter; a helper reached only through a *staying* helper stays.
- **The monkeypatch surface is the recurring trap — in BOTH forms.** A test may
  `monkeypatch.setattr(cli, "_x", …)` (string form) OR call `cli._x(…)` / `from
  forecasting.cli import _x` (read form). String-form patches that must reach a
  moved call site → keep `_x` in core, hop `_core._x` (e.g. `_ledger`,
  `_load_backtest_cases`, `_draft_resolution_criteria`). Read-form → re-bind
  `_x = _domain._x` at core's bottom (e.g. `_cmd_rerun`, `_build_doctor_report`).
  **Grep tests for every moved name — handlers AND helpers.** (The full suite,
  not the targeted subset, is what caught the `_write_agent_protocol_prompt_jsonl`
  read-form regression in slice 1.6.)
- **Cross-slice coupling:** once a sibling domain is carved, it imports shared
  helpers *from core*. Before moving a helper, grep `forecasting/cli/*.py` (not
  just core) — `_print_panel_summary` / `_resolve_active_model_id` had to stay
  because `quorum_panel`/`markets_pm` import them.
- **Registration order is load-bearing.** `forecast --help` lists subcommands in
  registration order. A domain whose subcommands are non-contiguous exposes
  MULTIPLE register hooks (`register`, `register_config`, …), each called at the
  exact pre-carve position. `dump_order.py` is the gate.
- **`ruff F821` is the safety net for reg-block constants** the body-only
  `deps.py` cannot see (`CALIBRATION_LESSON_STATUSES`, string annotations like
  `"ForecastLedger"`). Always run it on the new module before the test suite.
- **Off-by-one in the reg block breaks the handler wiring silently** — the
  `dump_help_tree.py` gate catches a dropped `set_defaults(...)` line (a node's
  `_forecast_handler` going empty). Trust the gate over the sed line numbers.
