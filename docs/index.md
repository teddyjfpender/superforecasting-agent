# Superforecasting Agent — Documentation

**A command-line forecasting desk that compounds judgment over time.**

Superforecasting Agent is a forecasting and quant-research platform built around
one durable primitive: the **scoreable forecast**. A forecast is not a chat
message — it is a persistent question with an append-only probability history,
timestamped evidence, assumptions, reference classes, model runs, resolutions,
scores, postmortems, and calibration lessons. The desk's job is to make good
forecasts, score them honestly, and get measurably better over time.

The project began as a fork of [Hermes Agent](https://github.com/NousResearch/hermes-agent)
and keeps the useful runtime pieces (model-provider routing, tool execution,
local storage, the CLI/TUI foundation). It **demotes** broad chat, gateway-first
messaging, and generic chat memory behind the forecasting workflow. Where legacy
Hermes names still surface in module paths or env vars, that is fork-transition
residue, not the product.

> This documentation describes **what the system actually is** as of the current
> tree — audited against the code, not inherited from upstream. The generated
> [reference](reference/README.md) is regenerated from the same sources the code
> compiles from, so it cannot silently drift.

## What it does

- **Forecast ledger** — create, research, update, resolve, score, and postmortem
  forecasts from the CLI or TUI, with append-only snapshots and auditable source
  trails. This is the product surface.
- **Gated commits** — a forecast snapshot only commits when it passes the hook
  gate (structured reasoning, fresh evidence, decomposition, panel where
  required, calibration). See the [built-in rules](reference/hooks-rules.md).
- **Quorum & Delphi** — high-impact calls run a multi-model panel that debates,
  runs a Delphi revision round, and attaches a judged synthesis to the snapshot.
- **Calibration & lessons** — resolutions auto-score (Brier / log / calibration
  buckets), synthesize calibration lessons, and apply the measured bias
  correction to future commits. The desk scores *you* too (practice mode, drills).
- **A prediction-market data plane** — browse and pull de-vigged Polymarket /
  Kalshi distributions, order books, and price history as structured data, plus a
  market-data provider fan-out (FX, econ series, crypto, equities).
- **Autonomy** — one sentence in, a committed forecast out; nightly self-checks
  re-pull watched sources and re-commit without an LLM; reading is triaged
  keep/skim/skip before it is hoarded.

## Read next

| Guide | For |
| --- | --- |
| [architecture.md](architecture.md) | How the system is built — the four arcs (protocol gateway, job runtime, market data plane, ledger) with diagrams. |
| [operating.md](operating.md) | Driving the TUI desk — views, the help system, the `u`/`U`/`A` desk tiers, mass-select, theses, markets & prediction markets, alerts, the agents chip. |
| [forecasting-methodology.md](forecasting-methodology.md) | The desk process and **how to let it learn** — questions → evidence/triage → panels → quorum/Delphi → commit gates → calibration → lessons. |
| [cli.md](cli.md) | Task-oriented CLI walkthroughs — the laziest path and the hand-driven path. |
| [development.md](development.md) | Contributing, the build/release path, the test and staleness gates. |
| [reference/](reference/README.md) | **Generated** reference: every RPC/event, tool action, job type, provider, CLI command, and hook rule — always in sync with the code. |

## Where the truth lives

The reference pages under [`docs/reference/`](reference/README.md) are generated
by `python -m scripts.docgen` from the live code — the protocol registry, the
forecast-tool schema, the jobs registry, the provider registries, the CLI
argparse tree, and the built-in hooks. A CI staleness gate
(`python -m scripts.docgen --check`) fails if any is out of date. Do not edit
those files by hand; edit the source and regenerate. The hand-authored guides
above explain the *why* and the *how*; the reference is the exhaustive *what*.
