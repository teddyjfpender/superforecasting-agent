# Architecture Delivery Plan — The Spine, Engineered

Companion to `2026-07-03-architecture-review-codex-opencode.md`. That doc says WHAT
and WHY; this one is the buildable HOW: contracts, module layouts, migration
mechanics, test strategy, risks, and slice-by-slice delivery with gates. Four arcs
plus the two supports that sequence with them.

Self-review corrections applied to the original doc's framing:
- Protocol codegen is specified concretely (no new heavy deps, staleness CI gate).
- The jobs migration keeps every existing RPC name working via aliases — zero
  breaking changes for the TUI mid-migration.
- The data-plane migration starts with FX + BEA (their fixed logic + live-probed
  quirks are fresh; port the honesty tests with them).
- The ledger carve has an explicit order, smallest-blast-radius first, with a
  measurable "no caller changed" gate per slice.

---

## ARC A — Protocol-first gateway (`protocol/`)

### Goal
One source of truth for every RPC and event crossing the gateway wire. TS types
GENERATED from it. Drift (the pm.tick.estimate stranding, the AgentJob.question_id
drop) becomes a build error instead of a runtime mystery.

### Design
```
protocol/
  __init__.py          # registry + version
  version.py           # PROTOCOL_VERSION = 1; MIN_SUPPORTED = 1
  types.py             # shared primitives (Probability, IsoInstant, QuestionId…)
  rpc/                 # one module per RPC family, pydantic models
    forecast.py        #   WorkspaceRequest/Response, ReforecastStart/Status…
    pm.py              #   PmList/Detail/Book/History/StreamStart…
    warnings.py, agents.py, markets.py, quorum.py, config.py
  events/              # one module per event family
    pm.py              #   PmTick {venue, market_id, kind, estimate: float|None…}
    jobs.py            #   JobProgress, JobComplete, JobError
    desk.py            #   ReviewSweep…
  codegen.py           # pydantic model_json_schema() -> .ts emitter
```
- **Codegen mechanism (concrete):** `python -m protocol.codegen` walks the registry,
  emits `ui-tui/src/protocol/generated.ts` (interfaces + string-literal event names +
  a `PROTOCOL_VERSION` const). Hand-rolled ~200-line emitter over pydantic's JSON
  Schema — no quicktype/openapi dependency. Deterministic output (sorted keys) so
  the file is diff-stable.
- **Staleness gate:** CI (and the pre-commit path) runs codegen and fails if
  `generated.ts` differs — "generated types are stale" becomes unmissable. The TUI
  imports ONLY from `src/protocol/` for wire shapes; hand-written mirrors in
  `gatewayTypes.ts` are deleted as each family migrates.
- **Version negotiation (minimal):** the gateway's hello/info response carries
  `protocol_version`; the TUI warns (never hard-fails) on mismatch. No per-message
  versioning — the whole wire is one version.
- **Server enforcement:** a `@rpc(model=...)` decorator variant validates params
  against the request model and serializes responses through the response model
  (pydantic `model_dump`). Migration wraps existing handlers one family at a time —
  the JSON on the wire is unchanged, only now VALIDATED.

### Migration mechanics
Family-by-family: define models → wrap handlers → regenerate TS → swap the TUI
imports for that family → delete the hand-written types. The wire never changes
shape, so a half-migrated system is fully functional at every commit.

### Tests
- Conformance: for every registered RPC, a generated test asserts request/response
  round-trip through the models (bad payloads rejected with the field named).
- The codegen emitter: golden-file test.
- One cross-language spot check per family: a captured real frame parses in both.

### Risks
- Pydantic v1/v2 mismatch with existing deps → pin and verify first slice.
- Handlers whose ACTUAL responses violate their intended shape (latent bugs) will
  surface as validation errors — that is the point; migrate a family only with its
  suite green.

### Slices & gates
A1: package + codegen + CI staleness gate + ONE family (pm.*) end-to-end. Gate:
    pm suite green, generated.ts imported by pmData.ts, drift gate red-teams (edit
    a model, verify CI fails).
A2: events (pm.tick, jobs.*, review.sweep) + the TUI event handler consuming
    generated event names. Gate: the stringly-typed names are gone from ui-tui.
A3: forecast.* + warnings.* families. A4: agents/markets/config + hello version.
Done = `gatewayTypes.ts` deleted; every wire shape generated.

---

## ARC B — One detached-job runtime (`forecasting/jobs/`)

### Goal
Quorum, reforecast/task, warning-automode, and registry procs become TYPES on one
runtime. Every future background capability arrives pre-integrated with progress,
throttling, cancellation, the agents chip, and desk re-attach.

### Design
```
forecasting/jobs/
  model.py       # JobRecord {job_id, type, status: queued|running|done|error|cancelled,
                 #   spec, created_at, done_count, total, current, progress[], result,
                 #   error, cancel_requested}
  store.py       # JSON-file-per-job under {home}/jobs/ (atomic writes — the proven
                 #   quorum_jobs pattern), list/read/write/active(), id validation
  runtime.py     # run(job_id): resolves the TYPE, executes with a JobContext
  context.py     # JobContext {progress(phase, done, total, **extra), should_cancel(),
                 #   annotate(k,v)} — progress has BUILT-IN coalescing (declarative
                 #   min_interval per type, default 125ms; first/last/phase-change
                 #   always pass) — the 1,300-event storm becomes impossible by
                 #   construction, not by patch
  types/         # registrations: quorum.py, reforecast.py, task.py, warnings.py
                 #   each: TYPE name, execute(spec, ctx), spec validator, rate policy
  __main__.py    # python -m forecasting.jobs run <job_id>
```
- **RPCs:** `jobs.start {type, spec}`, `jobs.status {job_id}`, `jobs.active {types?}`,
  `jobs.cancel {job_id}`. Events: `jobs.progress`, `jobs.complete`, `jobs.error`
  (protocol/events/jobs.py — Arc A models).
- **Backward compatibility (hard requirement):** the existing RPC names
  (`forecast.reforecast.start/status/active`, `forecast.warnings.automode.run`,
  quorum RPCs) become thin ALIASES over the jobs runtime returning the exact
  current response shapes. The TUI migrates to `jobs.*` at leisure; nothing breaks
  mid-arc. Old on-disk job files: a read-shim maps rf_*/wj_* records into JobRecord
  for status queries; new jobs write the new shape.
- **Cancellation:** `cancel_requested` flag in the record + the stop-event file the
  warning jobs already use; ctx.should_cancel() polls both.
- **Spend/approval hook (Arc-9 seam):** JobContext carries the run-mode policy
  object; types declare their spend class. Wired now as a pass-through so the
  policy layer lands without another migration.

### Migration mechanics
One type per slice: implement the type on the runtime → alias the old RPCs → delete
the old module (quorum_jobs.py, reforecast_jobs.py, the automode _run body) → suites
green. The TUI's three pollers collapse to one `useJobAttach(types)` hook LAST,
after all types are on the runtime.

### Tests
Lifecycle per type (existing suites re-pointed), coalescing contract (burst of 200
progress calls → bounded emissions, final value always lands), cancellation, the
read-shim over real legacy job files, alias parity (old RPC name == new response).

### Risks
The reforecast type runs run_forecast_chain with ledger gates — the runtime must
preserve the exact contextvars/allow-writes environment (copy the current
_run wrapper verbatim; it is already correct).

### Slices & gates
B1: runtime + store + context + coalescing tests + WARNINGS type (the simplest,
    and it deletes the hand-written throttle from the gateway). Gate: alerts view
    works unchanged against the alias; storm test green.
B2: REFORECAST + TASK types; reforecast_jobs.py deleted. B3: QUORUM type;
    quorum_jobs.py deleted (keep maybe_autorun_quorum as the decision function —
    it *starts* a job). B4: the TUI's single useJobAttach hook + agents.active
    reads one store. Done = three modules deleted, one runtime, chip unchanged.

---

## ARC C — Server-side data plane (`forecasting/marketdata/`)

### Goal
Every market provider lives server-side behind one interface: agent parity (the
agent can finally read the tape the operator sees), one key store, and the
estimator-honesty test discipline covering ALL quote math (the BEA 0.0000 lived in
client TS precisely because the taxonomy tests could not see it).

### Design
```
forecasting/marketdata/
  model.py       # Quote {symbol, provider, value|None, change|None, changePct|None,
                 #   prevClose|None, history[], asOf, unit…} — None NEVER 0 (the law)
  provider.py    # Provider protocol: fetch(series: list[SeriesRef]) -> list[Quote];
                 #   declares needs_key, batch semantics, rate limits
  providers/     # yahoo.py, frankfurter.py, coingecko.py, fred.py, bls.py, bea.py,
                 #   stooq.py… — ported ONE-TO-ONE from marketFetch.ts including the
                 #   fixed FX-range and BEA quirks (Year=LAST5 invalid; LineNumber
                 #   filter; comma parsing) and their contract tests
  service.py     # MarketDataService: TTL + stale-while-revalidate (the pm pattern),
                 #   parallel provider fan-out, per-provider failure isolation
  keys.py        # server-side key resolution (the existing api_keys store)
```
- **RPC:** `market.quotes {series: [{provider, symbol, …}]} -> {quotes}` +
  `market.search` (moves the symbol search server-side too). Protocol models in
  Arc A's markets.py.
- **Agent action:** `market_query {providers?, symbols?}` on the forecasting tool —
  structured quotes with the same honesty guarantees; the deterministic refresh's
  market components can later consume the same service (follow-up, not this arc).
- **TUI:** marketFetch.ts shrinks to a gw.request wrapper + the quote cache;
  providers/parsers deleted as each ports. The Add-data key flow points at the
  server store (the TUI stops reading env keys).

### Migration mechanics
Provider-by-provider, FX + BEA FIRST (fresh fixes, live-probed quirks, tests ready
to port). Per provider: port parser + tests (fixtures carried over) → service wires
it → TUI routes that provider's series through market.quotes → delete the TS
parser. A config flag (`marketdata.server_side: [providers]`) lets the TUI fall
back per-provider for one release.

### Tests
Ported contract tests per provider (the FX range shapes, the BEA error/line/comma
cases), service cache + isolation (one provider down ≠ blank tape), RPC conformance
(Arc A), and the scheduled LIVE contract check (Arc-7c: a cron job hitting each
provider's cheapest endpoint weekly, alerting on shape drift — fixtures rot; Peru,
RFK, and BEA were all found live).

### Risks
Yahoo is the highest-volume provider with informal rate tolerance — port it LAST,
after the pattern is proven on five smaller providers. Latency: server adds a hop;
the pm section proves the cost is negligible against cached service reads.

### Slices & gates
C1: package + service + FX (frankfurter) + BEA end-to-end with the flag. Gate:
    tape renders identically (component tests), agent market_query returns FX/BEA.
C2: coingecko + fred + bls + stooq. C3: yahoo + search + key-flow rehome + delete
    marketFetch providers. Done = zero fetch logic in the TUI; one honesty suite.

---

## ARC D — Megafile decomposition behind façades

### Goal
ledger.py (~16k), cli.py (~15k), forecasting_tool.py (109 actions in one dispatch)
become domain modules behind unchanged façades. No caller changes, ever, in any
slice — the gate is mechanical.

### Design & carve order (ledger)
```
forecasting/ledger/           # package replaces the module; __init__ re-exports
  core.py                     # connection, gate/authorizer, migrations, _ensure_column
  questions.py  ← slice D2    # create/get/list/config/resolve_ref
  watches.py    ← slice D1    # SMALLEST + freshest tests (the gate arc) — proves the carve
  evidence.py   ← D3          # evidence + triage glue
  snapshots.py  ← D4          # create_snapshot (the 400-line gate body), preview, annotate
  panels.py     ← D5          # panel runs + quorum signal glue
  reviews.py    ← D6          # scheduled reviews, cadence, sweeps
  alerts.py     ← D7          # alert_events + dispatcher glue
  theses.py     ← D8          # thesis members/aggregate/event-MC glue
  scoring.py    ← D9          # resolution scoring, calibration, lessons glue
```
- **The façade rule:** `ForecastLedger` remains THE public class; each slice moves
  method bodies into a domain module's functions taking `(ledger, …)` and the class
  keeps one-line delegates. `from forecasting.ledger import ForecastLedger` never
  breaks; `grep -c "def " ledger/core.py` shrinks measurably per slice.
- **The tool:** `tools/forecast_actions/` — one module per domain registering
  actions into a dict the dispatcher reads; the schema builder composes from
  registrations. Same alias guarantee: the tool's external name/behavior identical.
- **The CLI:** subcommand modules under `forecasting/cli/`, argparse wiring
  composed at import; `forecasting/cli.py` becomes the assembler.

### The gate (every slice, non-negotiable)
1. Full `tests/forecasting` green before AND after.  2. `git diff` shows ONLY moves
+ delegate stubs (reviewer greps for logic edits).  3. Import-time budget unchanged
(the 0.098s cold-start is a measured asset).  4. No slice > ~1,200 moved lines.

### Risks
Hidden intra-file coupling (module-level state, private cross-calls) — the carve
order starts with watches (fewest internal callers, freshest tests) precisely to
surface the coupling pattern cheaply. If a domain resists cleanly, STOP the slice
and split smaller — never force a move.

### Cadence
Background, one slice per work session alongside feature work — D1 first as the
pattern-prover, snapshots.py (D4) only after five clean slices. Done = ledger/core
under 2k lines, tool dispatch under 500, cli.py an assembler.

---

## SUPPORT ARCS (sequenced with the spine)

### E — Typed event bus + session event log (with Arc B)
`EventBus.emit(event_model)` — only protocol/events models are emittable; per-type
rate policy lives on the model (Arc B's coalescing generalized). Every emission
appends to `{home}/sessions/{sid}/events.jsonl` → replay drives session resume and
turns the bespoke re-attach RPCs (agents.active, reforecast.active) into one
generic "replay my subscriptions" path. Lands as B4's follow-on.

### F — Test infrastructure (with Arc A)
(a) Fix the ink harness's useStdout so injected streams report columns — width
logic becomes testable through real mounts (we hand-rolled component pins 3x).
(b) Frame snapshot tests for the layout-regression class ('…', alignment) — a
`expectFrame(name)` helper with golden files, updated via env flag.
(c) CI gates on EXIT CODES only (the vitest|grep red-test escape). SHIPPED with
    A1: the protocol staleness gate is `scripts/check-protocol.sh`
    (`python -m protocol.codegen --check`), wired into `.github/workflows/
    tests.yml` before the pytest run and mirrored by the pytest golden-file test
    `tests/test_protocol_codegen.py` — both exit-code gated.
(d) The weekly live-API contract cron (Arc C's check).

---

## Master sequence
```
Week 1   A1 (protocol+pm family)  ── F(c) exit-code gates same day
Week 1-2 B1 (runtime + warnings type; deletes the storm throttle patch)
Week 2   A2 (events) → E seam ready ; D1 (watches carve — pattern prover)
Week 3   C1 (FX+BEA server-side) ; B2 (reforecast/task types)
Week 4   A3-A4 ; B3-B4 + E ; D2-D3 ; F(a)(b)
Week 5+  C2-C3 ; D4… cadence ; F(d) cron
```
Every slice ships alone, suites green, no breaking wire changes at any commit.
The spine's DONE state: generated types everywhere, one job runtime, zero client-
side fetch logic, ledger/core < 2k lines — and every failure class this plan was
born from (drift, storms, fabricated zeros, unreviewable megafiles) has a
structural guard, not a patch.
