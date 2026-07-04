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

### D1 findings (watches carve — SHIPPED, the pattern-prover)
`forecasting/ledger.py` (18,562 lines) is now the package `forecasting/ledger/`
(`__init__` 69 · `watches` 989 · `core` 17,699). Gates all met: full
`tests/forecasting` green before (2,271 pass + 1 pre-existing flaky
`test_smoke_script` 60s-subprocess timeout) AND after (2,272 pass, 0 fail — the
flake passed on the after-run); import-time `import forecasting.cli` 0.11s→0.10s
(no regression); ~928 lines relocated (well under the 1,200 cap); core diff
mechanically verified = only moved-out bodies + 11 one-line delegates + import
edits (0 unexpected added/removed lines by difflib categorization).

Coupling patterns discovered (advice for D2+):
- **Module-global monkeypatch reach is THE trap.** Tests patch
  `forecasting.ledger.urlopen` (and `.ForecastLedger`) and expect the patch to
  reach call sites. Post-carve the bodies live in `core`, a distinct namespace,
  so a plain re-export breaks those tests. Fix: `__init__` installs a tiny
  façade (`_LedgerPackage.__setattr__/__delattr__` forwarding writes to `core`
  when `core` has the attr). This reproduces the old single-module semantics
  EXACTLY, zero test/caller edits. **D2+ must keep this façade** — every future
  slice inherits monkeypatch-safety for free.
- **Dependency direction is forced by partial-init.** Domain constants
  (`WATCH_*`) MUST live in the leaf (`watches`) and be imported BACK by `core`;
  the reverse deadlocks (core hasn't defined them when the leaf loads). The leaf
  imports `core` only as a module handle (`from forecasting.ledger import core
  as _core`) and touches `_core.<attr>` only at call time — binding a partial
  module object at load is safe.
- **Shared low-level deps stay in core, reached via the instance or `_core`.**
  Only ONE core name (`allow_ledger_writes`, the write gate) was needed by the
  watch domain (one write method) — reached via `_core.`. Everything else the
  moved code needs (`ValidationError`, `json_dumps/loads`, `parse_timestamp`,
  `utc_now_iso`, `AlertEvent`, `Any`) comes from `forecasting.models`/`typing`,
  so the leaf has no load-time core dependency. D4 (snapshots, 400-line gate
  body) will need MORE of core's gate machinery — consider extracting the gate
  (`allow_ledger_writes` + `GATED_LEDGER_TABLES` + authorizer) into its own leaf
  module first so multiple domains share it without the `_core.` hop.
- **`self.`→`ledger.` is the only body edit** (receiver rename; domain fns take
  the instance first). Watch for string literals containing the word (`forecast
  self-check`) — a blind `\bself\b` replace corrupts them; only `self.` +
  signature params are safe to rewrite.
- **Use AST `end_lineno`, not "next `def`", for extents.** A class attribute
  (`_TRIGGER_VALUE_KEYS`) sat between a method's `return` and the next `def`;
  the naïve boundary swallowed it and tests caught the `AttributeError`.
- **Re-export scope:** 20 distinct names are actually imported by callers
  across the repo (`ForecastLedger`, `allow_ledger_writes`,
  `GATED_LEDGER_TABLES`, the WATCH_*/CRUX_*/THESIS_* constants, the gate
  helpers, the bootstrap/leak thresholds, `ValidationError`,
  `LedgerNotFoundError`); `from .core import *` re-exports the full 96-name
  public surface. Prune-then-re-export a constant only when its LAST core user
  moves out (dropped `WATCH_SCOPE_TYPES`/`parse_qsl` from core imports, kept
  `WATCH_SCOPE_TYPES` on the package via an explicit `__init__` re-export).

### D2 findings (questions carve — SHIPPED)
`core` 17,699 → 17,180; new `questions` 673. Moved: the question CRUD cluster
(`create/get/list/rename_question`, `update_question_decision`,
`update_question_config` + its 4 exclusive config helpers, `resolve_question_config`,
`decision_readiness_issues`) plus `_scoreability_issues`, `_row_to_question`,
`_question_to_dict`, and the `_GATE_LABELS` map — 15 methods (15 one-line
delegates) + one constant (~600 relocated lines, well under the 1,200 cap).
Gates all met: full `tests/forecasting` green before (2,288 pass) AND after
(2,304 pass, 0 fail — the +16 is date-sensitive cadence/review tests, the session
date advanced 07-01→07-04; both runs zero failures); repo-wide `--collect-only`
0 import errors; import-time `import forecasting.cli` 0.10s→0.10s (held);
`ruff` (PLW1514) clean. Core diff mechanically verified = 15 delegate lines + 2
import lines + 1 blank added, 537 body/const lines removed — **0 unexpected** by
difflib categorization AND by grep (the non-delegate/non-import added-line grep is
empty).

Coupling patterns discovered (advice for D3-evidence):
- **The domain is NON-CONTIGUOUS.** The CRUD cluster sits at 1825–2344, but
  three members live deep among foreign neighbors — `_scoreability_issues`
  (@14474, between scoring methods), `_row_to_question` (@15684, beside the other
  `_row_to_*`), `_question_to_dict` (@17684, beside the other `_*_to_dict`).
  AST `end_lineno` carve handles scattered members trivially; judge membership by
  **caller-exclusivity, not adjacency** — grep each candidate's callers and pull
  it only when every non-moved caller reaches it via a `ledger.` delegate.
- **The monkeypatch façade needed NO extension.** No test patches a
  `forecasting.ledger.<name>` that the questions leaf re-imports (verified: grep
  for package-level attr-patches of `utc_now_iso`/`parse_timestamp`/`json_dumps`…
  returned zero). **D3 MUST re-run that grep** for the names `evidence.py` will
  re-import — a package-level patch that must reach the leaf is the one thing that
  forces either a façade forward-to-leaf or keeping the name callable via
  `_core.`/`ledger.`.
- **Surface parity by NON-pruning is the safe default for model-owned names.**
  `QUESTION_STATUSES`/`normalize_update_triggers` go unused in `core` post-carve
  but were KEPT in core's `forecasting.models` import so `from .core import *`
  still re-exports `forecasting.ledger.QUESTION_STATUSES` byte-for-byte. Ruff
  enforces only PLW1514 (no F401 gate), so unused imports are harmless; pruning a
  model-owned constant would have forced an explicit `__init__` re-export for no
  gain. The leaf owns ONLY its own constant (`_GATE_LABELS`, private, never on the
  package surface) — the D1 "constants to the leaf" rule applies to leaf-owned
  names, not to re-exported models constants.
- **The write gate resolved exactly as D1 predicted.** `create_question` is the
  domain's ONE gated write; `_core._enforce_write_gate("create_question")` via the
  module handle is the sole `core` dependency. No gate-leaf extraction was needed
  here — **D4 (snapshots, the 400-line gate body + `create_snapshot`) is the slice
  that finally justifies extracting the gate** D1 flagged.
- **Exclusive helpers travel with the domain even when topically "elsewhere."**
  The 4 config helpers (`_cadence_is_valid`, `_rearm_question_cadence`, the two
  `_validate_hook_*`) each had exactly ONE caller (`update_question_config`), so
  they moved with it despite being "cadence"/"hooks" flavored; they call BACK into
  core (`ledger.schedule_review`, `ledger._advance_cadence`) — a leaf→delegate→core
  hop that is correct and mirrors D1's `ledger.` receiver-rename discipline.

### D3 findings (evidence + triage carve — SHIPPED)
`core` 17,180 → 16,711; new `evidence` 689. The FULL domain fit under the cap so
no triage-half split was needed. Moved the evidence lifecycle (`add_evidence`,
`get_evidence`, `list_evidence`, `existing_evidence_keys`, `find_stale_evidence_refs`,
`evidence_by_question`, `evidence_map`, `_row_to_evidence`, `_evidence_to_dict`)
and the information-triage glue (`set/get/list_triage_rubric(s)`,
`record_triage_labels`, `get/list/update_triage_label`, the two `_row_to_triage_*`
readers, `check_triage_gate_graduation`) — 19 methods (19 one-line delegates) + 2
leaf-owned private consts (`_TRIAGE_RUBRIC_SCOPES`, `_TRIAGE_GATE_MODE_KEY`) — 584
moved method/const body lines (well under the 1,200 cap). Gates all met: full
`tests/forecasting` green before (2,319 pass) AND after (2,319 pass on a clean
re-run; one interleaved run flaked 3 *jobs/gateway* RPC tests
— `test_quorum_status_rpc_returns_job` fails on PRISTINE-isolated too, a
pre-existing `panel_run_id=None` gateway-serialization bug that only passes under
full-suite xdist ordering — none touch evidence/ledger); repo-wide
`--collect-only` 0 import errors (28,494 collected, unchanged); import-time
`import forecasting.cli` 0.083s→0.082s (held); `ruff` (PLW1514) clean. Core diff
mechanically verified = 19 delegate lines + the 4-line evidence-import block, 492
body/const lines removed — **0 unexpected** by difflib categorization.

Coupling patterns discovered (advice for the gate-leaf extraction + D4-snapshots):
- **The `urlopen` monkeypatch trap is resolved by KEEPING the coupled helpers in
  core, NOT by extending the façade.** `add_evidence`'s snapshot-archival helpers
  (`_archive_file/url_evidence_snapshot`) use the module-global `urlopen` that tests
  patch at `forecasting.ledger.urlopen` (test_ledger CF/block cases, test_tool). But
  `urlopen` is a SHARED low-level dep (watch-fetch @15697, resolution-source @15453
  also use it), so its call sites belong in core anyway — keeping them there
  preserves the monkeypatch surface with ZERO façade work. `add_evidence` moved to
  the leaf and reaches the archivers via `ledger._archive_*` delegates. The D2-
  mandated grep for package-level patches of EVERY OTHER name the leaf re-imports
  (`leak_reason`, `EvidenceItem`, `json_*`, `parse_timestamp`, `detect_block_page`…)
  came back EMPTY, so those are direct imports and the façade needed no extension.
- **No gated write in the domain → the leaf needs NO `_core` handle at all** (cleaner
  than D1/D2). `evidence_items` + the `triage_*` tables are NOT in
  `GATED_LEDGER_TABLES`; every core dependency (`_connect`, `get_question`, the
  `_archive_*`, `list_cruxes`/`list_watched_sources`, `get_desk_state`/
  `transition_desk_state`/`_has_open_alert`/`create_alert`, `build_triage_trust_gate`)
  is reached through the `ledger` INSTANCE at call time. The leaf imports only
  `forecasting.models`/`forecasting.leak_domains`/stdlib and touches nothing in core
  at load — zero load-time coupling, no cycle, no `_core` import.
- **Membership by caller-exclusivity over a NON-contiguous domain (D2's rule held).**
  The 19 methods scatter (evidence CRUD @3133, `evidence_map` @3775,
  `evidence_by_question` @6002, triage cluster @6599, `check_triage_gate_graduation`
  @7009 wedged between desk-state + saturation-alert methods, `_row_to_evidence`
  @15236 beside the other `_row_to_*`, `_evidence_to_dict` @17173 beside the other
  `_*_to_dict`). AST `end_lineno` handles scatter trivially; `check_triage_gate_
  graduation` moved despite non-triage neighbors because its callers are triage-
  exclusive.
- **Leaf-owned consts were `self.`-ACCESSED class attributes** (unlike D2's
  module-level `_GATE_LABELS`). Moving `_TRIAGE_RUBRIC_SCOPES`/`_TRIAGE_GATE_MODE_KEY`
  to leaf module scope required post-fixing the tokenize `self.`→`ledger.` rename back
  to a BARE `_X` reference (they're module globals now, not instance attrs). Verified
  exclusive callers first.
- **The `self`→`ledger` rewrite used a tokenize NAME-token pass, not a regex** — the
  D1 string-literal trap (`forecast self-check`) plus comment words like "itself"
  never matched; the one bare-`self` arg (`build_triage_trust_gate(self, …)`) renamed
  correctly to `ledger`.
- **Advice for D4 (snapshots — the big one) + the gate-leaf.** Deliberately LEFT in
  core: `_validate_evidence_refs` (the create_snapshot evidence GATE — D4's slice)
  and `_benchmark_evidence_alerts` (alerts domain — D7). D4 pulls `create_snapshot`
  (~700 lines incl the ~400-line gate body) + preview/annotate and is the FIRST slice
  whose domain has a GATED write, so the `_core.`-hop for `_enforce_write_gate` /
  `allow_ledger_writes` / `GATED_LEDGER_TABLES` / the authorizer finally returns (D1/
  D2 both flagged this). Extract the write gate into its own leaf (or keep in core,
  reached via `_core.`) BEFORE D4 so snapshots + future gated domains share it. D4
  reaches this slice's evidence helpers via `ledger.` (`find_stale_evidence_refs`
  moved; `_validate_evidence_refs` stayed), and its snapshot archival (`_archive_
  resolution_source_snapshot` sits beside the two evidence archivers this slice kept
  in core) can finally co-locate as a "snapshot archival" cluster — but WHEREVER those
  land, the `urlopen` call sites must stay reachable by the `forecasting.ledger.
  urlopen` monkeypatch (core, or a leaf that references `_core.urlopen`).

### Gate-leaf extraction (SHIPPED — D1's named prerequisite for D4)
Before D4, the write-gate machinery D1/D2/D3 all flagged was carved to its own
leaf `forecasting/ledger/gate.py` (200 lines; 166 moved out of core): the
commit-active contextvar `_FORECAST_COMMIT_ACTIVE`, `allow_ledger_writes`
(+`_decorator`), `forecast_commit_active`, `ledger_write_gate_mode`, the SQLite
`_ledger_write_authorizer`, `_enforce_write_gate`, and the `GATED_LEDGER_TABLES`/
`GATED_LEDGER_WRITES` constants. `core` imports all nine names BACK (`from
forecasting.ledger.gate import …`) so its call sites keep bare-name references
AND `from .core import *` re-exports the pre-carve public surface byte-for-byte;
`__init__` gained a `_gate` submodule handle. Gates met: import-time held
(0.083s→0.083s); the soul suites (`test_commit_preview`, `test_watch_gate_and_bulk`,
`test_ledger_write_gate`) green; full `tests/forecasting` 2318 pass + the D1
`test_smoke_script` flake (a 60s subprocess timeout under xdist load — passes
isolated in 104s, never touches the gate); core diff = 166 body lines out + a
21-line import block, **0 unexpected added lines** by difflib.
- **The one finding that mattered: NO test patches a gate name at package level.**
  The D1/D2/D3-mandated grep (`forecasting.ledger.<gatename>` and
  `setattr(...gate name...)`) came back EMPTY — the gate is exercised via
  `monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", …)` (env is read live inside
  `ledger_write_gate_mode`, module-independent) and via the public
  `allow_ledger_writes` context, never via attribute-patching. So the monkeypatch
  façade needed **no extension** and the gate could move to a true leaf with zero
  `_core.` hop. **A leaf is the right home for the write gate**: it imports only
  stdlib + `forecasting.models` (`ForecastingError`), owns its own `logger`, and
  every gated write domain (D4 snapshots, D5 panels) now imports the gate directly
  instead of reaching through `_core.`.
- `LedgerWriteRefusedError` does not exist — the gate raises `ForecastingError`
  from `forecasting.models`; `record_panel_run`'s `_enforce_write_gate("record_panel_run")`
  (D5's domain) already resolves against the leaf via core's import-back.

### D4 findings (snapshots carve — SHIPPED, the big one)
`core` 16,566 → 15,573; new `snapshots` 1,161. Moved **1,079 body lines** (13
`ForecastLedger` methods = 1,053 + the module fn `_normalize_reason_list` = 26),
under the ~1,200 cap — the FULL clean domain fit, no read/commit split needed.
Moved: the commit body `create_snapshot` (872 lines — every gate, the
saturation/observe scoring, the preview plumbing), its commit-exclusive helpers
(`_validate_evidence_refs`, `_committed_winner_prob`, `_machine_scoreable_payload`,
`_derived_child_present`, `_forecast_horizon_days`), the readers
(`get_snapshot`/`get_current_snapshot`/`list_snapshots`/`snapshots_by_question`),
`annotate_snapshot`, and the serializers (`_row_to_snapshot`/`_snapshot_to_dict`)
— 13 one-line delegates + `_normalize_reason_list` deleted (no delegate; module
fn with no external caller). Gates met: full `tests/forecasting` 2,319 pass before
AND after (0 fail — smoke flake passed this run); repo-wide `--collect-only` 0
import errors (28,501 collected); import-time held (0.083s); `ruff` (PLW1514)
clean; core diff = 13 delegate returns + a 3-line import block, **0 unexpected
added non-blank lines** / 973 body lines removed by difflib.

Coupling patterns discovered (advice for D5-panels / D6-reviews):
- **Caller-exclusivity ≠ domain membership — the sharpest cut yet.** Three helpers
  are called ONLY by `create_snapshot` yet were deliberately LEFT in core because
  they belong to FUTURE domains: `_cascade_reaggregate_parents` (thesis
  re-aggregation → D8), `_audit_unapplied_lessons` + `_record_lesson_applications`
  (calibration lessons → D9). The task's "parent cascade **trigger points**" read
  as the CALL SITES inside `create_snapshot` (which move with it), NOT the cascade
  engine. `create_snapshot` fires all three via `ledger.<name>` — the leaf→delegate→
  core hop. Pulling them would have hit 1,224 lines (over cap) AND stranded D8/D9
  work in the snapshots module. **D5/D6 rule: an exclusive helper travels with the
  domain only if it IS that domain; when it's a future domain's concern, leave it
  in core and reach it via `ledger.` — the delegate makes the hop free and the
  future slice inherits it cleanly.** (`calibration_bias`, `calibration_summary`'s
  `_snapshot_component_contributions` likewise stayed — calibration, D9.)
- **The gate leaf paid off immediately.** `create_snapshot` reaches the write gate
  by importing `_enforce_write_gate`/`allow_ledger_writes` straight from
  `forecasting.ledger.gate` — no `_core.` hop for the gate. D5's `record_panel_run`
  (the third gated write) does the same. The ONLY `_core.`-hop the snapshots leaf
  needs is one SHARED core constant, `FORECASTING_PROTOCOL_VERSION` (used by both
  `create_snapshot` and a non-snapshot core method @~10.7k, so it stays in core and
  is reached as `_core.FORECASTING_PROTOCOL_VERSION` — one NAME-token rewrite in the
  moved body). Everything else the leaf needs is `forecasting.models`/stdlib/gate.
- **`@staticmethod` needs decorator-aware carve.** Two moved helpers are
  staticmethods; AST `node.lineno` points at `def` (the decorator sits above in
  `decorator_list`). The delegate must re-emit `@staticmethod` and forward WITHOUT
  `self`; the module fn drops the decorator and takes no `ledger`. A naïve carve
  that skipped the decorator line or force-passed `self` broke the categorical/
  binary path — build the delegate's replacement range from
  `min(node.lineno, decorators[0].lineno)`.
- **The delegate forwards `self` positionally + the rest by keyword** (D2 style):
  `_snapshots.create_snapshot(self, question_id=question_id, …)`. Forwarding `self`
  BOTH positionally and as `self=self` (an off-by-one in the arg-skip) is the trap —
  `TypeError: got an unexpected keyword argument 'self'`. Skip the leading `self`
  from the keyword set; static fns skip nothing.
- **Line-based dedent is safe even over the 872-line body** with its triple-quoted
  INSERT SQL and dozens of implicit-concat message strings: SQL is whitespace-
  insensitive, docstring/message dedent is cosmetic, and the pre-scan confirmed
  **no `self` inside any f-string/string literal** (the 3.11 single-STRING-token
  f-string trap), so the tokenize NAME-token `self`→`ledger` pass is complete.
- **`_snapshot_component_contributions` is a decoy** — named "snapshot" but its ONLY
  caller is `calibration_summary`, so it is a calibration-display helper (D9), left
  in core. Judge every `*_snapshot*`-named helper by its caller, not its name.

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
