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
| [decisions.md](decisions.md) | The design-decision record — 14 ADRs, each with the evidence that drove it (the drift bugs, the event storm, the fabricated zeros…). |
| [reference/](reference/README.md) | **Generated** reference: every RPC/event, tool action, job type, provider, CLI command, hook rule, skill, and env var — always in sync with the code. |

## Deep dives

The guides above are the overview; these carry the system's accumulated
judgment — mechanics, math, doctrine, and the gotchas that used to be tribal
memory. Every claim is verified against named source functions (each doc ends
with a Sources footer).

| Deep dive | What it holds |
| --- | --- |
| [forecasting-pipeline.md](deep-dives/forecasting-pipeline.md) | The commit path in full: the gate battery rule-by-rule, the write-gate architecture (the SQLite authorizer backstop), preview, provenance, saturation, uncertainty bands. |
| [quorum-and-panels.md](deep-dives/quorum-and-panels.md) | Panels, the multi-model Delphi mechanics, autorun decision logic, track-record weighting, judge override + terminal-Platt composition. |
| [learning-loop.md](deep-dives/learning-loop.md) | Resolution → scoring → lesson synthesis → enforced `lesson:*` rules → retrieval → weighting — with the silent-kill gotchas as warning boxes. |
| [thesis-and-factor-math.md](deep-dives/thesis-and-factor-math.md) | The thesis aggregate and the Gaussian-copula event Monte Carlo in plain notation; why seat weights are excluded; factor math; Market Models. |
| [scoring-and-ensembles.md](deep-dives/scoring-and-ensembles.md) | The full calibration/ensemble stack (12 slices) with the ON-vs-OFF activation map as *empirical* decisions. |
| [benchmarking-harnesses.md](deep-dives/benchmarking-harnesses.md) | ForecastBench grounding, the market-hidden arm (the real test), the live-edge study, leakage quarantine. |
| [estimator-honesty.md](deep-dives/estimator-honesty.md) | **The doctrine**: the 10-class fabrication taxonomy — each class the lie it would tell, the guard, the pinning test, and the operator story that forged it. |
| [prediction-markets.md](deep-dives/prediction-markets.md) | Venue adapters, YES-orientation hierarchy, rank-interleaved lanes, the disk tape cache and stale semantics, deep search. |
| [evidence-and-triage.md](deep-dives/evidence-and-triage.md) | Watched sources, evidence lifecycle, the three-way triage rubric, the 80% trust gate, time-travel pinning. |
| [protocol-and-gateway.md](deep-dives/protocol-and-gateway.md) | The registry + codegen design, the two validation strategies and why, the 11-bug drift catalog, version handshake. |
| [jobs-runtime.md](deep-dives/jobs-runtime.md) | JobRecord/store/context contracts, coalescing invariants, cancellation, the five types, the counted-forever bugs. |
| [tui-architecture.md](deep-dives/tui-architecture.md) | The ink fork's real click rule, the design laws (wrap, 2dp, memo-safe animation), skins, keymaps + help. |
| [testing.md](deep-dives/testing.md) | The testing doctrine: exit-codes-never-grep, width pins, fixture-rot vs live probes, the verified flake classes. |

## Where the truth lives

The reference pages under [`docs/reference/`](reference/README.md) are generated
by `python -m scripts.docgen` from the live code — the protocol registry, the
forecast-tool schema, the jobs registry, the provider registries, the CLI
argparse tree, and the built-in hooks. A CI staleness gate
(`python -m scripts.docgen --check`) fails if any is out of date. Do not edit
those files by hand; edit the source and regenerate. The hand-authored guides
above explain the *why* and the *how*; the reference is the exhaustive *what*.
