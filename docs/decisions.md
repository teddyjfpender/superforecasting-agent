# Design decisions (ADR record)

This file records the load-bearing design decisions behind the Superforecasting
Agent: the choices that shaped the architecture and that a future contributor
must not accidentally undo. Each entry follows the ADR shape (Context, Decision,
Consequences) plus an **Evidence** block naming the commits and files that drove
and implemented it, so a decision can be re-derived from the record, not just
remembered.

These are the decisions with teeth. Unlike the generated pages under
[`reference/`](reference/README.md), this file is written by hand: it captures
*why*, which no registry can generate. When a decision here is reversed, amend
the entry (mark it Superseded) rather than deleting it.

Most of the architecture entries trace to the delivery plan in
[`plans/2026-07-03-architecture-delivery-plan.md`](plans/2026-07-03-architecture-delivery-plan.md),
whose four arcs (A protocol, B jobs, C data plane, D ledger carve) recur below.

## Index

| # | Decision | Status |
| --- | --- | --- |
| [ADR-0001](#adr-0001--protocol-first-with-generated-typescript) | Protocol-first with generated TypeScript (the 11 drift bugs) | Accepted |
| [ADR-0002](#adr-0002--validate-only-vs-re-dump-for-handler-conformance) | VALIDATE-ONLY vs re-dump for handler conformance | Accepted |
| [ADR-0003](#adr-0003--one-detached-job-runtime-coalescing-by-construction) | One detached-job runtime; coalescing by construction | Accepted |
| [ADR-0004](#adr-0004--byte-identical-alias-compatibility-during-migration) | Byte-identical alias compatibility during migration | Accepted |
| [ADR-0005](#adr-0005--the-server-side-data-plane-agent-parity) | The server-side data plane (agent parity) | Accepted |
| [ADR-0006](#adr-0006--the-honesty-doctrine-none-is-never-0) | The honesty doctrine (None is never 0) | Accepted |
| [ADR-0007](#adr-0007--event-monte-carlo-over-mean-walk-for-theses) | Event-Monte-Carlo over mean-walk for theses | Accepted |
| [ADR-0008](#adr-0008--the-ledger-carve-method-facade-moves-only-gate-leaf-first) | The ledger carve method (facade, moves-only, gate-leaf-first) | Accepted |
| [ADR-0009](#adr-0009--incentive-repair-over-blame) | Incentive-repair over blame | Accepted |
| [ADR-0010](#adr-0010--guide-and-make-visible-over-hard-blocking) | Guide-and-make-visible over hard-blocking (ledger discipline) | Accepted |
| [ADR-0011](#adr-0011--the-deliberate-off-gates) | The deliberate OFF gates (sqrt(3) Platt, leak-judge calibration) | Accepted |
| [ADR-0012](#adr-0012--hooks-and-ci-share-one-source) | Hooks and CI share one source | Accepted |
| [ADR-0013](#adr-0013--generated-artifact-oversize-exemption) | Generated-artifact oversize exemption | Accepted |
| [ADR-0014](#adr-0014--disk-cache-stale-marking-paint-then-refresh) | Disk-cache stale-marking (paint-then-refresh) | Accepted |

---

## ADR-0001 — Protocol-first with generated TypeScript

**Status:** Accepted (Arc A).

**Context.** The gateway wire was described in two places at once: pydantic-ish
server handlers and roughly 370 hand-written TypeScript interface mirrors
(`gatewayTypes.ts`, `pmData.ts`). Two hand-maintained descriptions of one wire
drift silently: a field the server always emits gets typed nullable on the
client, an enum narrows on one side, a key is emitted but invisible to the
reader. Nobody notices until a runtime surface misbehaves.

**Decision.** Make the wire a single source of truth. Every request, response,
and event is a pydantic model under `protocol/`; the TUI's TypeScript wire types
are **generated** by `python -m protocol.codegen`; a `--check` staleness gate
turns any divergence into a build error. Server handlers validate params through
the request models (bad payloads name the offending field), and a
`PROTOCOL_VERSION` handshake rides `gateway.ready` and `session.info` so future
evolution is observable rather than silent.

**Consequences.** Transcribing the *real* wire into models is what found the
bugs: 4 latent drift bugs surfaced on day one (A1), the tally moved 9 to 11 by
A3, and A4 closed it at **11 found, all fixed toward the server's truth**, with a
DEBUG validator scan over 56 wrapped handlers showing zero remaining mismatches.
The registry now holds 101 RPCs and 46 events (370 generated interfaces); 104 + 13
hand mirrors were deleted; `gatewayTypes.ts` became a pure re-export shim plus
exactly two TS-only union aliases. The codegen was extended additively (tuples,
Literals, nullable-optional, typed Records) and stayed byte-identical on all
prior output.

**Evidence.** Commits `80ae3429f` (A1, first 4 drift bugs, the gate + red-team),
`d69e9e5e4` (A3, tally 9 to 11, VALIDATE-ONLY reasoned), `13b9fdf93` (A4, closes
at 11, version handshake, shim endgame). Files `protocol/__init__.py`,
`protocol/codegen.py`, `ui-tui/src/protocol/generated.ts`,
`scripts/check-protocol.sh`. Generated: [`reference/protocol.md`](reference/protocol.md).

---

## ADR-0002 — VALIDATE-ONLY vs re-dump for handler conformance

**Status:** Accepted (Arc A). A deliberate, reasoned deviation within ADR-0001.

**Context.** There are two ways to enforce the wire on a handler. Re-dump
serializes the response *through* the model (`model_dump`) so the wire physically
cannot regress. VALIDATE-ONLY validates the handler's result and logs any drift,
but returns the handler's original object untouched. Re-dumping a large,
partially-built payload risks changing it on re-serialize.

**Decision.** Choose per family. The small, fully-typed `pm.*` responses
**re-dump** (with a pass-through-and-log fallback) so the wire can never regress
mid-migration. The forecast family **validates only**: its builder payloads are
large and partial, and its handlers own a rich error taxonomy (4003/4004/5008/
5009) that short-circuiting on re-serialize would change. Validate, log drift,
return the original.

**Consequences.** No regression risk on the big builder payloads; the error
taxonomy is preserved; drift is still detected (the A4 validator scan proved zero
mismatches across every wrapped handler). Conformance tests include real captured
frames and explicit "wire-unchanged" proofs for the VALIDATE-ONLY path.

**Evidence.** Commits `d69e9e5e4` (the VALIDATE-ONLY deviation, stated with its
reasons), `80ae3429f` (the pm re-dump pattern), `13b9fdf93` (56 handlers wrapped,
zero mismatches). See also the wrap law in `CONTRIBUTING.md`.

---

## ADR-0003 — One detached-job runtime; coalescing by construction

**Status:** Accepted (Arc B).

**Context.** Long-running desk work (warnings automode, quorum, reforecast,
tasks) had grown as separate bespoke modules, each with its own spawn, progress,
cancellation, and persistence. Warnings automode in particular carried a
hand-written progress throttle patched into `server.py` after a **1,300-event
progress storm** overwhelmed the alerts view.

**Decision.** Build one runtime and make every capability a registered `JobType`
on it. `JobContext.progress()` has **declarative coalescing built in**
(`min_interval_s`, with first / phase-change / final always passing and `flush()`
landing any trailing event), one atomic JSON store, and one standalone entrypoint
(`python -m forecasting.jobs run <id>`). The throttle stops being a patch and
becomes a property of the substrate.

**Consequences.** The 1,300-event storm is now **impossible by construction** for
every current and future job type. Roughly 110 lines (the throttle, the automode
handlers, the daemon-thread body) were deleted from `server.py`; three bespoke
modules (`quorum_jobs.py`, `reforecast_jobs.py`, the warning handlers) were
deleted. The net-new REFRESH type shipped as one type file plus a rewired
keypress, because `jobs.start` routes any registered type generically. Per-type
rate policy is now an explicit choice (quorum sets `min_interval_s=0` so every
stage event lands).

**Evidence.** Commits `9b311fc53` (B1, the substrate and the storm made
impossible), `c364b8bc2` (B3, quorum rides it, `quorum_jobs.py` deleted),
`6dfe0be0c` (B4, one attach hook, one store), `5925fbdbb` (the REFRESH type as
one file). Files `forecasting/jobs/runtime.py`, `forecasting/jobs/types/`.
Generated: [`reference/job-types.md`](reference/job-types.md).

---

## ADR-0004 — Byte-identical alias compatibility during migration

**Status:** Accepted (Arcs A and B).

**Context.** The arcs renamed RPCs, events, and job identifiers while live TUI
sessions and a large test suite depended on the old names and on old on-disk job
files (`rf_`, `qr_` prefixes).

**Decision.** Keep the legacy names as aliases that return **byte-identical**
shapes and, for events, emit the legacy name *alongside* the new one. Shim legacy
job identifiers at the store via an unknown-key-tolerant `from_dict`
(`run_id` to `job_id`, `mode` to `type`) so the generic `jobs.status` / `jobs.active`
answer for old files.

**Consequences.** All 8 automode tests passed unchanged and the alerts view
needed no edits; old on-disk files are served by the generic job RPCs so the
per-type shims collapse; legitimate callers kept working with zero call-site
churn. Provenance strings (for example `allow_ledger_writes(reason=...)`) were
kept byte-identical so audit parity held across the move.

**Evidence.** Commits `9b311fc53` (alias parity, legacy events emitted
alongside), `6dfe0be0c` (legacy fallback paid at the store), `c364b8bc2` (byte-
identical provenance reason on the quorum path). See the "byte-identical wire
aliases" law in `CONTRIBUTING.md`.

---

## ADR-0005 — The server-side data plane (agent parity)

**Status:** Accepted (Arc C).

**Context.** Market-quote fetching lived in client TypeScript (`marketFetch.ts`).
Two costs followed: the **agent could not read the tape the operator sees** (it
scraped instead of reading structured quotes), and the quote math lived where the
python estimator-honesty tests could not reach it, which is exactly where a
fabricated `0.0000` hid (see ADR-0006).

**Decision.** Move all seven providers server-side behind one `MarketDataService`
(TTL plus stale-while-revalidate, per-provider failure isolation). Expose
`market.quotes` and `market.search` RPCs and a `market_query` agent action. Make
the generated `Quote` structurally assignable to the TUI's `MarketQuote` so no
client mapper is needed.

**Consequences.** Every number on the Markets tape now flows through python
providers covered by the honesty suite; the agent's `market_query` sees exactly
what the operator sees; keys resolve in one place. `marketFetch.ts` collapsed from
237 to 103 lines (-57%). Providers were ported one-to-one with their quirks named
(coingecko's derived change, fred's dual path, the universal error-payload-to-null
pin), each with a live spot-check.

**Evidence.** Commits `56959fa44` (C1, FX + BEA with agent parity), `5101a2c1d`
(C2, four more providers), `633af71eb` (C3, the plane complete). Files
`forecasting/marketdata/service.py`, `forecasting/marketdata/model.py`. Generated:
[`reference/providers.md`](reference/providers.md).

---

## ADR-0006 — The honesty doctrine (None is never 0)

**Status:** Accepted. The single invariant the estimator-honesty tests defend.

**Context.** A fabricated zero is worse than a blank: it looks like a real
reading. This shipped to operators as the BEA `0.0000` wall, born the moment an
API-error payload's empty string parsed as `Number('') === 0` in the client. It
was the 8th entry in a running fabricated-value taxonomy.

**Decision.** A missing measurement is `None`, renders as an em-dash placeholder,
and is **never** `0` / `0.0`. Every value crossing the market-data boundary
(`value`, `change`, `changePct`, `prevClose`, ...) is `float | None`; providers
return an honest null on error payloads. This is codified as the honesty law in
`CONTRIBUTING.md` and lives server-side so the taxonomy tests can finally see all
of the quote math.

**Consequences.** The best proof came from production: stooq served a
bot-challenge HTML page and the provider returned an honest null (absence
rendered as absence) on day one. FRED's `0.0` change is kept when it is *real*
(two equal observations) but never fabricated. New numeric surfaces ship with the
tests that prove they say "no data" rather than "zero".

**Evidence.** `forecasting/marketdata/model.py` docstring ("THE LAW, `None` NEVER
`0`") and its `num()` helper; the honesty law in `CONTRIBUTING.md`. Commits
`a51f954dd` (BEA stops fabricating 0.0000, three stacked bugs), `5101a2c1d` (the
live stooq null), `56959fa44`, `37d9a167b`, `852000392`, `b18af8f27` (degenerate
books yield no estimate).

---

## ADR-0007 — Event-Monte-Carlo over mean-walk for theses

**Status:** Accepted.

**Context.** A macro thesis like "Democrats take back the Senate" was headlined
by a weighted **mean** over 35 individual seat probabilities. A mean is damped
and threshold-insensitive: the index walked forward (+0.10) while battlegrounds
moved only 1.4 to 3.4pp, and correlation only ever entered the uncertainty band,
never the headline number. But a takeover is a **joint threshold event**, not an
average.

**Decision.** Model the event directly with a Gaussian-copula Monte Carlo,
`simulate_thesis_event(members, event, rho|matrix, n_draws, seed)`: draw
correlated latents, set `success_i = z_i < inv-Phi(p_i)`, and read
`P(event) = P(count >= K)`. The draw is deterministic (`seed = sha256(thesis_id |
as_of)`), numpy does 20k draws with a pure-python 2k fallback, and per-member
sensitivities come from re-thresholding the *same* z columns at `p +/- 2pp`
(common random numbers). Seat weights deliberately do not enter the event (a seat
is one Bernoulli); the weighted mean survives only as a diagnostic.

**Consequences.** Correlation now enters the number, not just the band. Validated
against the exact Poisson-binomial at `rho=0` (`|diff| 0.0023` at 20k draws), with
`rho` toward 0.95 collapsing any/all toward a single latent draw. Dashboards
headline `P(event)` when configured; activation is the operator's call on their
own ledger.

**Evidence.** Commit `242aa79e8`. Files `forecasting/thesis.py`
(`simulate_thesis_event`), `forecasting/ledger/theses.py` (the D8 carve,
`_cascade_reaggregate_parents`).

---

## ADR-0008 — The ledger carve method (facade, moves-only, gate-leaf-first)

**Status:** Accepted (Arc D).

**Context.** `ledger.py` had grown to roughly 17.7k lines. It had to be split for
reviewability without changing a single caller and without weakening any commit
gate.

**Decision.** Carve `ledger.py` into a `forecasting/ledger/` package by a
repeatable method: `__init__` re-exports the full public surface behind a
`__setattr__`-forwarding **facade** (so module-global monkeypatch reach, which
tests rely on, is preserved exactly); `core.py` holds the body; each domain
carves to its own **leaf** as `(ledger, ...)` functions behind one-line
delegates. Cut by AST `end_lineno`, never by "next def" (a class attribute once
sat between two defs and the tests caught it). Constants live in the leaf and are
imported back by core. Slices are **moves-only**, verified with difflib to
0-unexpected added lines. Pattern-prover findings are written into a **findings
ledger** in the plan doc for later slices. Critically, extract the write gate
(`allow_ledger_writes`) to its own leaf **first**, because it is the one
cross-domain dependency every other carve needs.

**Consequences.** `core.py` went 17,699 to 11,592 lines (-6,107 across nine
domains) and import time improved (0.11s to 0.09s, better than the monolith).
`tests/forecasting` (2,272 growing to 2,319) passed before and after every slice.
The gate-leaf-first choice paid off directly: D8 theses needed zero new gate code
because D4's boundary analysis had already established that
`_cascade_reaggregate_parents` runs inside `create_snapshot`'s active commit. The
facade solved the monkeypatch trap with zero test edits, and every later slice
inherited it.

**Evidence.** Commits `7c4dac300` (D1, the facade and the 4 pattern-prover
findings), `4302d016b` (the gate leaf plus D4 snapshots), `1ecfcc6a8` (D5+D6,
zero `_core` hops once the gate leaf existed), `00922498b` (D7-D9, carve
complete). Files `forecasting/ledger/gate.py`, `snapshots.py`, `theses.py`. See
the moves-only refactor law in `CONTRIBUTING.md`.

---

## ADR-0009 — Incentive-repair over blame

**Status:** Accepted.

**Context.** Auditing the agent's real Senate-batch work surfaced two behaviors.
It wrote a raw-SQL script (`direct_saturate_senate_sources.py`) to mass-insert
watched sources, because the honest tool alternative was roughly 245 one-per-call
invocations and the table was not gated, so the script worked silently. And every
question got two snapshots a minute apart, because the only way to see the
saturation score or gate blockers was to commit first. The agent's judgment was
excellent; the **mechanism** manufactured the bad behavior.

**Decision.** Repair the incentive, do not blame the operator-agent. Add a bulk
`add_watched_sources` action (up to 400 rows, per-row try/except isolation). Add
`create_snapshot(preview=True)` so the entire gate battery runs and returns
`{would_commit, saturation, blockers[]}` *before* the single INSERT, turning
blockers into data instead of exceptions. Return auditable **skip records** (with
reasons) where the code used to decline with a bare `None`, and stamp
`panel_run_ref` and the quorum decision into snapshot metadata via
`annotate_snapshot` so the record itself tells the full story.

**Consequences.** The 245-insert loop collapses to one call; the commit-then-
remediate double write is killed at the root; audits no longer need source-reading
and temporal joins. The preview path is proven no-write: its test runs the full
gate battery with the write gate *enforcing* and *outside* any allow context, so
an accidental INSERT anywhere in those roughly 400 gate lines would be refused
loudly.

**Evidence.** Commits `c9d84ea37` (bulk watches), `ed57bf7c1` (pre-commit
preview, the no-write proof), `2362fc27f` (commit provenance, skip records).
Files `forecasting/ledger/snapshots.py` (`create_snapshot(preview=...)`),
`forecasting/ledger/core.py` (`annotate_snapshot`, `detect_templated_batches`).

---

## ADR-0010 — Guide-and-make-visible over hard-blocking

**Status:** Accepted.

**Context.** The agent legitimately scripts the ledger directly; for bulk work it
is faster and honest. Hard-blocking all direct access would break real workflows.
But a script that mass-inserts into a table which drives automated data flows is
the same bypass class as a scripted forecast, and silent bypasses corrupt audits.

**Decision.** Guide toward the tool-native path and make any bypass **visible**,
rather than forbidding scripting outright. Gate only the tables that drive
automation: `watched_sources` joins `GATED_LEDGER_TABLES`, and the blessed method
self-wraps in `allow_ledger_writes` (validation earns the write) so every
legitimate caller keeps working while a raw `sqlite3` INSERT is refused at the
connection level. Elsewhere, prefer WARN over BLOCK: an unacknowledged stale-
evidence commit warns unless a written `stale_evidence_reason` is supplied (a
reason makes the bypass auditable), and `detect_templated_batches` surfaces
templated research. The ledger-interaction SKILL and the soul stance teach the
discipline in prose.

**Consequences.** The observed raw-SQL bypass is refused with the gate on, while
the tool, CLI (`--apply-watch`), auto-watch, cron, and gateway paths keep working
with zero call-site churn. Stale-evidence acknowledgement without a reason is
downgraded to a warning that records the reason when given; templated batches are
flagged rather than silently accepted.

**Evidence.** Commit `c9d84ea37` (gate the table, self-wrapping method, SKILL
section). Files `forecasting/hooks/builtins.py` and `forecasting/hooks/signals.py`
(the `stale_evidence_reason` WARN path), `forecasting/ledger/core.py`
(`detect_templated_batches`), `forecasting/cli.py` (templated-batch surfacing).

---

## ADR-0011 — The deliberate OFF gates

**Status:** Accepted. Machinery shipped, activation left off on purpose.

**Context.** The AIA-forecaster roadmap shipped the terminal Platt calibrator,
the content-aware leak judge and a leak-prevalence estimator, a terminal-alpha
sweep, a search/judge ablation, and the live MarketNightly harness. Several of
these either **move the committed number** or **make a trust claim**. Activating
them without justification on our own data would itself be dishonest (the paper's
`sqrt(3)` slope is a prior, not a fit; a raw flag count is not a leak rate).

**Decision.** Ship the machinery, leave the activation gates OFF. `sweep_platt_alpha`
is **read-only and never moves a default**: the per-question `alpha_extremize`
stays `1.0` (a no-op), and `brier_at_sqrt3` is surfaced as "the value one would
activate absent a sweep," not applied. The leak judge and `leak_prevalence`
estimator run only as **opt-in** read-only channels (the hot callers leave them
`None`); they never edit a forecast and never take down readiness, and the true
leak rate is a versioned `LEAK_JUDGE_CALIBRATION` constant rather than a trusted
live number. Baseline-anchored extremization and a help/hurt gate are the safety
guards that must first confirm center-ward hedging on our data before any
`alpha > 1`.

**Consequences.** The single highest-leverage change (terminal Platt, roughly
5.6% Brier in the paper) is available but does not silently move committed
numbers. The headline Brier can be made defensibly leak-proof (filtered and
worst-case re-scores) without a raw flag count masquerading as a rate. Every
read-only AIA row is opt-in, so the hot path pays nothing.

**Evidence.** `forecasting/backtesting.py` (the READ-ONLY sweep at lines ~27-67
with "never moves a default" and `brier_at_sqrt3`; the opt-in leak/ablation/
market-nightly rows at ~496-549), `forecasting/leak_prevalence.py`,
`forecasting/bayes_toolkit.py` (`platt_scale` with `extremize` as a thin alias).
Plan: [`plans/aia-forecaster-improvements.md`](plans/aia-forecaster-improvements.md)
sections P0.1, P1.2, P2.2, P2.3, P2.5.

---

## ADR-0012 — Hooks and CI share one source

**Status:** Accepted.

**Context.** Local git hooks and CI naturally drift: a check passes locally but
fails in CI (or the reverse), which erodes trust in both and trains contributors
to skip the local gate.

**Decision.** The `.githooks/` scripts and the CI workflow
(`contributing-gates.yml`) **source the same `checks.sh`**, so they cannot
diverge. Placement follows capability: the commit-msg hook holds the oversize /
moves-only gate because only it sees both the diff and the message. The escape
hatch `HERMES_HOOKS_SKIP="reason"` is logged to `.githooks/skips.log` with author,
HEAD, and reason, and empty reasons are refused (visible, never silent).

**Consequences.** Hooks and CI enforce an identical set; every gate was
demonstrated firing on a synthetic violation before the commit that added it, and
that commit ran through its own installed hooks. The reference-staleness gate
(`docs.yml`) and the protocol / wire-drift gate are enforced the same way locally
and in CI. The docs generator this record ships alongside rides exactly this
discipline: `python -m scripts.docgen --check`.

**Evidence.** Commit `20742656d`. Files `CONTRIBUTING.md` (The Laws), `.githooks/`,
`.github/workflows/contributing-gates.yml`, `.github/workflows/docs.yml`.

---

## ADR-0013 — Generated-artifact oversize exemption

**Status:** Accepted.

**Context.** The size rules cap new code (~400 lines) and moved code (~1,200
lines) per slice to keep review honest. But generated artifacts legitimately blow
through any line cap: `generated.ts` carries 370 interfaces, `cli-reference.md`
exceeds 100k characters. Gating those by size would punish the very determinism
that makes them safe.

**Decision.** Exempt generated artifacts from the line-count rule and govern them
by a **stronger** invariant: a regenerate-and-diff staleness gate (`--check`)
that fails unless the artifact is byte-identical to a fresh render from its
source. The size discipline is for hand-written code; generated code is bound by
"it must equal what its generator produces from the current source."

**Consequences.** Large generated files are safe to grow because they cannot
drift from their source, and a hand edit to one is caught as staleness rather than
slipping through review. This was demonstrated for the two pages added with this
record: hand-editing `reference/skills.md` and `reference/config-and-env.md` made
`python -m scripts.docgen --check` exit 1 and name both files; regenerating
restored green. The commit-msg MOVES-ONLY marker is for hand moves, not generated
growth.

**Evidence.** Commit `20742656d` (size rules and the moves-only marker); commits
`80ae3429f` and `13b9fdf93` (the codegen `--check` gate, additive and
byte-identical). Files `scripts/docgen/` and the reference-staleness job in
`.github/workflows/docs.yml`. See the size rules and protocol-first laws in
`CONTRIBUTING.md`.

---

## ADR-0014 — Disk-cache stale-marking (paint-then-refresh)

**Status:** Accepted.

**Context.** The prediction-market tape cold-started at 622ms and blank. A naive
disk cache would paint instantly but risk presenting stale rows as if they were
fresh, which violates the honesty doctrine (ADR-0006) one layer down.

**Decision.** Persist the tape to disk (atomic `pm_cache.json`) and on cold start
paint instantly from disk **marked `stale: true`**, running the live revalidate
off-path. The `stale` flag rides the wire (preserved past the validator's
extra-key ignore) and surfaces in the UI as a "refreshing" chip; search results
never persist to the cache; hydration is bounded (12 in-flight) rather than
serial. Never a blank tape, and never a tape that pretends disk rows are fresh.

**Consequences.** Cold tape went 622ms to 4.3ms (disk-served), with the "still
refreshing" state made honest rather than hidden. Profiling the same path revived
a dead Kalshi series-catalog scan that had been raising a swallowed `NameError`
(the series phase of deep search had been silently dead), fixed with a regression
pin.

**Evidence.** Commit `e23252a4e`. Files under `forecasting/pm/` (the disk cache
and bounded hydration) and the TUI `usePmList` / `usePmSection` stale-chip wiring.
