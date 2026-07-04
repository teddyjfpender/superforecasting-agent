<p align="center">
  <img src="assets/banner.png" alt="Superforecasting Agent" width="100%">
</p>

# Superforecasting Agent

<p align="center">
  <a href="docs/index.md"><img src="https://img.shields.io/badge/Docs-read%20the%20docs-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://github.com/teddyjfpender/superforecasting-agent/tree/superforecasting-agent-snapshot"><img src="https://img.shields.io/badge/GitHub-superforecasting--agent-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub repository"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

**A command-line forecasting desk that compounds judgment over time.** The core
product primitive is the **scoreable forecast**: a durable question with an
append-only probability history, timestamped evidence, assumptions, reference
classes, model runs, resolutions, scores, postmortems, and calibration lessons.
The desk's job is to make good forecasts, score them honestly, and get measurably
better.

This is a fork of [Hermes Agent](https://github.com/NousResearch/hermes-agent). It
keeps the useful runtime pieces — model-provider routing, tool execution, local
storage, the CLI/TUI foundation — and demotes broad chat, gateway-first messaging,
and generic chat memory behind the forecasting workflow. Use any model and switch
with `superforecasting-agent model` — no code changes, no lock-in.

## Documentation

Full documentation lives in **[`docs/`](docs/index.md)** and is audited against
the code, not inherited from upstream.

| Guide | For |
| --- | --- |
| [Overview](docs/index.md) | What the system is, honestly. |
| [Architecture](docs/architecture.md) | The four arcs — protocol gateway, job runtime, market data plane, ledger — with diagrams. |
| [Operating the desk (TUI)](docs/operating.md) | Views, the help system, the `u`/`U`/`A` desk tiers, mass-select, theses, markets, alerts, the agents chip. |
| [Forecasting methodology](docs/forecasting-methodology.md) | The desk process and how to let it learn. |
| [CLI guide](docs/cli.md) | Task-oriented walkthroughs. |
| [Development](docs/development.md) | Build, release, and the test/staleness gates. |
| [Reference (generated)](docs/reference/README.md) | Every RPC/event, tool action, job type, provider, CLI command, and hook rule — regenerated from code. |

The pages under [`docs/reference/`](docs/reference/README.md) are **generated** by
`python -m scripts.docgen` from the same sources the code compiles from, and a CI
staleness gate keeps them from drifting. That is what makes the documentation
living: add an RPC, action, job type, provider, command, or hook rule, and the
reference regenerates.

## What it does

<table>
<tr><td><b>Forecast ledger</b></td><td>Create, research, update, resolve, score, and postmortem forecasts from the CLI or TUI with append-only snapshots and auditable source trails.</td></tr>
<tr><td><b>Gated commits</b></td><td>A snapshot commits only when it passes the hook gate — structured reasoning, fresh evidence, decomposition, panel where required, well-formed uncertainty, applied calibration lessons.</td></tr>
<tr><td><b>Quorum & Delphi</b></td><td>High-impact calls run a multi-model panel that forecasts independently, runs a Delphi revision round, and attaches a judged synthesis to the snapshot.</td></tr>
<tr><td><b>Calibration loop</b></td><td>Resolutions auto-score (Brier/log/calibration buckets), synthesize calibration lessons, and apply the measured bias correction to future commits. The desk scores you too.</td></tr>
<tr><td><b>Prediction Markets data plane</b></td><td>Browse and pull de-vigged Polymarket + Kalshi distributions, order books, and price history as structured data (the <code>pm_query</code> agent action + the TUI Markets view), plus a market-data provider fan-out (<code>market_query</code>).</td></tr>
<tr><td><b>Autonomy</b></td><td>One sentence in, a committed forecast out; nightly self-checks re-pull watched sources without an LLM; reading is triaged keep/skim/skip before it is hoarded.</td></tr>
</table>

## Quick Install

Installed from the moving tester snapshot branch while packaging finishes:

```bash
git clone --branch superforecasting-agent-snapshot \
  https://github.com/teddyjfpender/superforecasting-agent.git \
  superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
python3 scripts/forecast_smoke_test.py
```

On native Windows, use the PowerShell installer:

```powershell
iex (irm https://raw.githubusercontent.com/teddyjfpender/superforecasting-agent/superforecasting-agent-snapshot/scripts/install.ps1)
```

After install:

```bash
forecast                 # open the forecast desk (TUI)
superforecasting-agent   # fork-native command; forecast workflows are shorthand
forecast status          # desk state, calibration, live baseline comparisons
```

## Getting started

The laziest path is the intended path — one sentence, and the desk structures the
question, attaches watched sources, and runs research → base rate → committed
forecast through the same gated pipeline a hand-driven session uses:

```bash
forecast onboard "Will the Fed cut rates by September?" --auto
```

In chat, the same journey is one tool call: ask the agent to forecast something
and it uses `full_forecast`. Autonomy never buys a weaker forecast — it buys fewer
keystrokes; every gate still applies.

A few common commands (the full, task-oriented guide is [docs/cli.md](docs/cli.md);
the exhaustive command tree is [docs/reference/cli-reference.md](docs/reference/cli-reference.md)):

```bash
forecast new "Will X happen?" --resolution-criteria "Resolved yes if ..."
forecast evidence add <id> <url-or-note>       # attach timestamped evidence
forecast update <id> --probability 0.63 --rationale "..."   # append a gated snapshot
forecast resolve <id> --outcome yes && forecast score <id> --baselines
forecast calibration --by-origin --all          # your reliability curve + trend
forecast drill --n 5                             # practice on resolved binaries
forecast doctor                                  # operational / pilot / readiness gate
```

## Contributing

Start with **[CONTRIBUTING.md](CONTRIBUTING.md)** for the contributor process, and
**[docs/development.md](docs/development.md)** for the build/release path and the
gates. Quick start:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
scripts/run_tests.sh tests/forecasting -q
```

### The two codegen gates

Two staleness gates keep generated artifacts in lockstep with their sources —
change a source, regenerate, commit:

```bash
python -m protocol.codegen && scripts/check-protocol.sh   # protocol → ui-tui/src/protocol/generated.ts
python -m scripts.docgen    && python -m scripts.docgen --check   # code → docs/reference/*.md
```

CI runs both (`.github/workflows/tests.yml`, `.github/workflows/docs.yml`) so a
stale generated file becomes an unmissable build error instead of a runtime or
documentation mystery.

## License

MIT — see [LICENSE](LICENSE).
