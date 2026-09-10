# Architecture

This is the honest shape of the system as it stands in the tree. Four arcs carry
the weight; everything else is either an entry point onto them or an inherited
runtime the fork keeps but demotes.

```
                         ┌──────────────────────────────────────────────┐
   you ── keystrokes ──▶ │  TUI  (ui-tui/, TypeScript + Ink)            │
                         │  desk · markets · alerts · agents · calendar │
                         └───────────────┬──────────────────────────────┘
                                         │  JSON-RPC over stdio
                                         │  (typed by protocol/, ARC A)
                         ┌───────────────▼──────────────────────────────┐
   you ── `forecast` ──▶ │  Python gateway  (tui_gateway/, gateway/)    │
        (CLI, cli.py)    │  validates + serializes every wire message   │
                         └───┬───────────────┬───────────────┬──────────┘
                             │               │               │
                    ┌────────▼───────┐ ┌─────▼─────────┐ ┌───▼─────────────┐
                    │ agent runtime  │ │ job runtime   │ │ market data     │
                    │ run_agent.py   │ │ (ARC B)       │ │ plane (ARC C)   │
                    │ + tools/       │ │ forecasting/  │ │ marketdata/, pm/│
                    │ forecast_ledger│ │ jobs/         │ │                 │
                    └───────┬────────┘ └──────┬────────┘ └───┬─────────────┘
                            │                 │              │
                            └────────┬────────┴──────────────┘
                                     ▼
                    ┌────────────────────────────────────────┐
                    │  Forecast ledger  (ARC D)               │
                    │  forecasting/ledger/  — SQLite + gate   │
                    │  domain leaves behind one façade        │
                    └────────────────────────────────────────┘
```

Two entry points reach the same core: the **CLI** (`forecast` /
`superforecasting-agent`, dispatched by `superforecasting_agent/cli.py` into the
big argparse tree in the `forecasting/cli/` package) and the **TUI** (an Ink/TypeScript app
in `ui-tui/` talking to a Python gateway over stdio). The agent runtime
(`run_agent.py`, `agent/`, the tools in `tools/`) is what actually drives a
forecast when you ask in natural language; it operates the ledger through the one
`forecast_ledger` tool (see [tool actions](reference/tool-actions.md)).

---

## Arc A — Protocol-first gateway

**One source of truth for every RPC and event crossing the gateway wire, with the
TUI's TypeScript types generated from it.** The registry lives in
`protocol/__init__.py`: `RPC_SPECS` (**101 RPCs**) and `EVENT_SPECS` (**46
events**), each binding a wire method/name to pydantic request/response/payload
models under `protocol/rpc/` and `protocol/events/`.

```
protocol/
  __init__.py     RPC_SPECS / EVENT_SPECS registry + registered_models()
  version.py      PROTOCOL_VERSION = 1   (whole wire is one version)
  types.py        WireModel base + shared primitives (Probability, IsoInstant…)
  rpc/            one module per family: forecast, pm, jobs, markets, agents…
  events/         one module per family: pm, jobs, desk, turn, tools, voice…
  codegen.py      pydantic models ──▶ ui-tui/src/protocol/generated.ts
```

The mechanism that makes this *living*: `python -m protocol.codegen` walks the
registry and emits `ui-tui/src/protocol/generated.ts` (interfaces + string-literal
event names + the `PROTOCOL_VERSION` const), deterministically (sorted) so the
file is diff-stable. `scripts/check-protocol.sh` (which runs
`python -m protocol.codegen --check`) is a CI staleness gate: change a model
without regenerating and the build fails with "generated types are stale" instead
of a runtime mystery. Server-side, `tui_gateway/server.py` wraps handlers to
validate params against the request model and serialize responses through the
response model — the JSON on the wire is unchanged, only now validated. The
forecast family is wrapped VALIDATE-ONLY (it logs drift and returns the original
payload untouched, so the big partial responses can never regress).

This same pattern is what the reference docs mirror: see
[reference/protocol.md](reference/protocol.md), generated from the same registry.

---

## Arc B — One detached-job runtime

**Every long-running background capability is a TYPE on one runtime**, so it
arrives pre-integrated with progress, coalescing, cancellation, persistence, and
desk re-attach. The runtime is `forecasting/jobs/runtime.py`; the registry is
`forecasting/jobs/types/` (`registered_types()` / `resolve()`).

```
jobs.start ─▶ JobStore (persist) ─▶ runtime.run(job_id)
                                        │ resolve(record.type) ─▶ JobType.execute(spec, ctx)
                                        │ progress coalesced at JobType.min_interval_s
                                        ▼
              jobs.progress / jobs.complete / jobs.error  (events, ARC A)
```

Seven job types ship today — `backup`, `quorum`, `reforecast`, `refresh`,
`task`, `warnings`, `wiki_prune` — each declaring a `spend_class` (`agent` jobs
spend model budget; `free` jobs do not). The runtime is transport-agnostic: in the gateway it runs on
a daemon thread with the progress/complete/error hooks wired to event emit; as a
detached process (`python -m forecasting.jobs run <id>`) the persisted record IS
the channel a poller reads. Legacy RPC names (`forecast.reforecast.*`,
`forecast.warnings.automode.*`) are kept as thin aliases so the TUI never broke
during the migration. Full list: [reference/job-types.md](reference/job-types.md).

---

## Arc C — Server-side market data plane

**External numbers become structured data on the server, not scraped in the
agent.** Two services:

- `forecasting/marketdata/` — `MarketDataService` fans out over quote providers
  (FX, econ series, crypto, equities) with a TTL + stale-while-revalidate cache
  and **per-provider failure isolation** (one provider down ≠ blank tape). The
  provider set comes from `_default_providers()`; keys resolve through
  `forecasting/marketdata/keys.py`. Exposed as `market.quotes` / `market.search`.
- `forecasting/pm/` — `PMService` reads prediction-market venues
  (**Polymarket**, **Kalshi**) read-only: events, de-vigged outcome
  distributions, order books, price history, and live streaming. Exposed as the
  `pm.*` RPC family and the `pm.tick` event, and reachable from the agent through
  the `forecast_ledger` tool's `pm_query` action.

Provider + venue registry: [reference/providers.md](reference/providers.md).
(The much larger set of *evidence-import* adapters — FRED, GDELT, arXiv, SEC, and
dozens more (59 at last count) — is a different mechanism, driven by
`forecast import` / `forecast sources` and the tool's `source_type` parameter,
not the quote data plane.)

---

## Arc D — The forecast ledger (domain leaves + a gate)

The ledger is the durable core: a SQLite store behind
`forecasting/ledger/`. What was one monolith is carved into **focused domain
leaves** behind an unchanged façade (`forecasting/ledger/__init__.py` re-exports
`core`'s public surface, so `ForecastLedger` callers never changed). The carve
started at nine leaves and has kept going — 24 modules at last count:

```
forecasting/ledger/
  core.py        the ForecastLedger façade + schema/migrations
  gate.py        the write-gate leaf (shared by every gated write)
  watches.py  questions.py  evidence.py  snapshots.py  panels.py   ┐ the original
  reviews.py  alerts.py  theses.py  scoring.py                     ┘ nine leaves
  anchors.py  autopilot.py  backtest.py  deviation_bets.py  exports.py
  lessons.py  market_models.py  model_scoring.py  question_meta.py
  refresh.py  resolutions.py  source_signatures.py  workflow.py
```

Each leaf owns its tables, CRUD, and invariants.

The **write-gate** (`gate.py`) is the integrity backbone. The desk agent has, in
the past, fabricated forecasts by scripting `ForecastLedger` directly —
`create_snapshot` / `create_question` / `record_panel_run` from an ad-hoc script —
bypassing the calibration/panel/evidence gates the forecast tool enforces on the
commit path. The gate **refuses a forecast-producing write attempted outside a
recognised commit context**: legitimate writers (the tool's commit flow, the
market-nightly + cron jobs, the autonomous cycle, migrations, the CLI's forecast
commands) open that context with `allow_ledger_writes()`; reads are never gated.
Mode is a config flag (`FORECAST_GATE_DIRECT_WRITES`, default `on`), and the
active-commit flag is a contextvar so a gateway thread-pool / asyncio worker each
see their own state.

---

## Inherited runtime (kept, demoted)

The fork keeps but subordinates the Hermes runtime: provider routing, the tool
registry, local storage, the cron scheduler, and the messaging `gateway/` (a
generic multi-platform chat surface, useful as an optional alert/evidence-capture
channel, no longer the centerpiece). Broad chat, general-assistant branding,
generic chat memory, and do-anything tool exposure are the demoted surfaces —
present during the transition, not the product. When you see a `hermes_*` module
or a `HERMES_HOME` env var, that is compatibility residue; the fork prefers
`superforecasting-agent` / `FORECAST_*` names.

## Shared runtime ownership

`runtime/custom_provider_catalog.py` owns the model picker's provider catalog and
raw environment-reference preservation; the picker owns interaction and selection.
`runtime/tui_environment.py` owns launch environment parity for CLI and dashboard.
`runtime/commands.py::expand_quick_alias` owns CLI/gateway alias expansion, argument
preservation and cycle detection; platform dispatch retains access control and hooks.

`forecasting/evidence_quality.py` supplies the shared source/observation identities
used by research adequacy and ledger readiness. URL hosts are conservative source
proxies. Known shared origins belong in evidence metadata as `independence_group`
or `original_source_url`; different hosts alone do not prove independence.
