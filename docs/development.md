# Development

This page orients a contributor to the moving parts and the gates. The canonical
contributor process — environment setup, PR conventions, code style, review
expectations — lives in [`CONTRIBUTING.md`](../CONTRIBUTING.md) at the repo root;
start there. This guide covers what is specific to *this* system: how to build and
release it, and the gates that must stay green.

## Environment

```bash
python3 scripts/dev.py bootstrap
python3 scripts/dev.py check
```

Bootstrap uses the frozen Python lockfile, installs the development and web
extras needed by host tests, builds Ink, installs Git hooks, and runs the same
quality checks as CI. These contributor dependencies do not change the minimal
backend distribution. Use `check --python-only` for the Python and contract gates.
Run behavior tests through `scripts/run_tests.sh`.

## The map

| Area | Where |
| --- | --- |
| CLI entry point | `superforecasting_agent/cli.py` → the `forecasting/cli/` package (`register_cli`; the old single-module `forecasting/cli.py` was carved into subcommand modules behind an unchanged façade) |
| Forecast engine + domains | `forecasting/` (ledger, hooks, jobs, marketdata, pm, quorum, triage, learning…) |
| The agent's forecast tool | `tools/forecasting_tool.py` (`FORECAST_LEDGER_SCHEMA`) |
| Wire protocol (source of truth) | `protocol/` — pydantic models + registry |
| Python gateway | `tui_gateway/`, `gateway/` |
| TUI (TypeScript + Ink) | `ui-tui/src/` |
| Runtime foundations | `superforecasting_agent/{bootstrap,constants,clock,logging}.py` |
| Session persistence | `superforecasting_agent/storage/session.py` (`SessionDB`) with focused storage modules |
| Agent runtime | `run_agent.py`, `agent/`, `tools/` |
| Docs generator | `scripts/docgen/` |

See [architecture.md](architecture.md) for how these fit together.
For renamed Python modules and extension imports, see the
[runtime layout and migration guide](architecture/runtime-layout.md).

## The gates (keep these green)

Two codegen staleness gates enforce that generated artifacts never drift from
their sources. Both fail loudly in CI and both have a one-command fix.

### 1. Protocol → TypeScript

The TUI's wire types (`ui-tui/src/protocol/generated.ts`) are generated from the
`protocol/` pydantic models. After changing a wire model:

```bash
python -m protocol.codegen            # regenerate ui-tui/src/protocol/generated.ts
scripts/check-protocol.sh             # the gate (CI runs this)
```

Enforced by `.github/workflows/tests.yml`.

### 2. Code → reference docs

The pages under `docs/reference/` are generated from the protocol registry, the
forecast-tool schema, the jobs registry, the provider registries, the CLI argparse
tree, and the built-in hooks. After changing any of those sources (adding an RPC,
a tool action, a job type, a provider, a CLI command, or a hook rule):

```bash
python -m scripts.docgen              # regenerate docs/reference/*.md
python -m scripts.docgen --check      # the gate (CI runs this)
```

Enforced by `.github/workflows/docs.yml`. This is what keeps the documentation
*living*: the reference regenerates from the same sources the code compiles from,
so it evolves automatically as the codebase does. **Do not hand-edit anything
under `docs/reference/`** — edit the source and regenerate.

#### Extending the generator

To add a new reference page, write a module under `scripts/docgen/` exposing a
deterministic `render() -> str` (sort your output; no timestamps — a generated
file must be byte-identical run-to-run) and append one `Generated(...)` entry to
`GENERATORS` in `scripts/docgen/registry.py`. The writer, the `--check` gate, and
the generated index (`docs/reference/README.md`) pick it up automatically.

### Tests

```bash
scripts/run_tests.sh                          # full suite (matches CI settings)
scripts/run_tests.sh tests/forecasting -q     # one area
```

Run `scripts/run_tests.sh` rather than bare `pytest` — it pins the xdist worker
count, timezone/locale/hash seed, and blanks credential env vars so your local run
matches CI. Test config lives in `pyproject.toml` (`[tool.pytest.ini_options]`).

**What CI blocks on** (`.github/workflows/tests.yml` + `lint.yml`):

- `test` — the pytest suite plus the protocol staleness gate, on every PR.
- `e2e` — the end-to-end suite.
- `tui` — the TUI suite is **blocking, not advisory**: `npm run type-check`
  (tsc), the **full** vitest suite (`npm run test`), and the lint warning
  ratchet (`npm run lint -- --max-warnings 54` — the pinned count may only
  ever go *down*; fix a warning, lower the number in `tests.yml` **and** in
  `production-release.yml`'s tui job). Runs on Node 22, matching the release
  build jobs. The release pipeline declares `needs: [gate, test, python-compat, tui]`, so
  **a red TUI suite blocks a release**.
- `lint.yml` — blocking `ruff check .` enforcement plus a blocking, pinned
  `actionlint` pass over everything in `.github/workflows/` (`needs:` edges,
  `${{ }}` expressions, shellcheck on `run:` scripts), alongside an advisory
  ruff + ty diff comment.

**Local hooks vs CI.** `.githooks/pre-push` is the bounded (~2–3 min) local
gate: targeted pytest for the changed Python domains, `vitest --changed` when
`ui-tui/` was touched, and the codegen staleness checks again. It is
deliberately weaker than CI on the TUI — changed-file vitest only, no
type-check, no lint ratchet — so a green push does not guarantee a green `tui`
job. CI is the authority.

## Build and release

The release path bundles a **prebuilt TUI** so the agent installs and launches
without a git checkout, a hand-rolled venv, or an npm install:

```bash
scripts/build-release.sh                       # → a wheel in dist/
pipx install dist/superforecasting_agent-*.whl
superforecasting-agent --tui
```

The launcher finds the bundled TUI, runs it on Node (auto-provisioning Node via
fnm/nvm/brew if needed), and spawns the gateway from the installed package's own
Python. `scripts/build-release.sh` mirrors `.github/workflows/production-release.yml`
so a local build matches CI; `SKIP_NPM=1` reuses an existing
`ui-tui/dist/entry.js`.

## Docs structure

- `docs/*.md` — hand-authored guides (this set). Edit freely.
- `docs/reference/` — **generated**; never hand-edit (see the gate above).
- `docs/plans/`, `docs/research/` — design plans and research write-ups; preserved
  as historical record.
