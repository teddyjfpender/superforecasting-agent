# Architecture Review: What Codex and OpenCode Teach This System

Benchmarked against openai/codex (Rust core, protocol-first, sandboxed exec) and
opencode (client/server, provider abstraction, multi-client). Every item below is
grounded in a failure this codebase actually exhibited in the 2026-07-01..03 sessions
— not imported dogma. Ranked by necessity.

## 1. Protocol-first gateway (the Codex lesson) — NECESSARY
Codex's core insight: the agent core speaks a versioned, TYPED protocol (Op/Event);
the TUI is just one consumer. Ours: hand-mirrored TS types over ad-hoc JSON-RPC
frames. This session's drift bugs were all this class:
- `pm.tick.estimate` shipped python-side but sat uncommitted/unconsumed (streams
  silently dead on restart);
- `AgentJob.current` dropped the `question_id` the server always sent (the working
  row was undeterminable);
- the events are stringly-typed (`review.sweep`, `pm.tick`) with no schema anywhere.
**Do:** a `protocol/` package — pydantic models for every RPC request/response and
event; TS types GENERATED from them (single source); a protocol version exchanged at
hello. Conformance tests generated from the schemas. Kills the drift class forever.

## 2. One detached-job runtime — NECESSARY
We hand-rolled the same subsystem four times: quorum_jobs, reforecast_jobs (+task
mode), warning-automode jobs, process_registry. Each: its own JSON store, lifecycle,
`python -m` entrypoint, status RPC, TUI poller. The agents-chip had to aggregate
three stores fail-safe; the desk re-attach needed a bespoke `.active` RPC; the
warning jobs needed a hand-written progress throttle after the 1,300-event storm.
**Do:** one `jobs/` runtime — single store, one lifecycle (queued/running/done/error),
a progress contract with DECLARATIVE rate policy (the throttle lesson as a default,
not a patch), one `jobs.active`/`jobs.status` RPC family, one TUI attach hook. Each
family registers as a job TYPE. Three implementations get deleted; every future
background capability (backtests, ingestion, exports) arrives pre-integrated with
the chip, the desk markers, and cancellation.

## 3. Server-side data plane everywhere (the OpenCode lesson) — NECESSARY
OpenCode's TUI is a thin client over one server API. Ours is split-brained: the PM
integration went python-service + RPC (correctly — agent parity was the requirement)
while the Markets tape still fetches client-side in TS (yahoo/frankfurter/FRED/BEA).
Consequences we hit: the FX/BEA fetchers escaped the estimator-honesty discipline
(the fabricated 0.0000 lived in TS where the python taxonomy tests can't see it);
the AGENT cannot read the macro tape the operator sees; keys resolve in two places.
**Do:** move all market providers behind the pm-style service/RPC pattern (TTL +
stale-while-revalidate, fixtures, honesty tests), expose one `market_query` tool
action for the agent, thin the TUI to renderers. This is the single biggest
remaining architectural inconsistency.

## 4. Decompose the megafiles behind façades — NECESSARY (staged)
ledger.py ~16k lines, cli.py ~15k, forecasting_tool.py with 109 actions in one
dispatch — 40x over the 400-line rule we enforce on new code. Session cost: every
agent slice pays a read-tax; test collection is slow; merge risk concentrates.
The pm/ package proves the target shape (10 modules, façade, per-module tests).
**Do:** staged extract-with-façade: ledger → domain modules (questions, snapshots,
evidence, panels, watches, reviews, alerts, theses, jobs) re-exported through
ForecastLedger so no caller changes; the tool → per-domain action modules on a
registry; cli → subcommand modules. One domain per slice, suites green each step.
Mechanical but must never be rushed — this is months of small slices, not one PR.

## 5. Typed event bus + replayable event log — HIGH VALUE
The per-alert event storm (1,300 events, strobing backlog) happened because any
code can `_emit` anything at any rate. Codex persists a rollout/event log enabling
resume + forensics.
**Do:** an EventBus where event types declare schema + rate policy (throttle/coalesce
declaratively); a per-session append-only event log (replay = session resume,
debugging, and the TUI re-attach patterns become generic subscriptions instead of
bespoke `.active` RPCs).

## 6. HTTP+SSE server mode — MEDIUM (unlocks multi-client)
The gateway is stdio-only; the web terminal needed a dev-only bridge. OpenCode's
server-first design gets web/mobile/remote + session sharing for free.
**Do:** same protocol over HTTP+SSE alongside stdio. Prereq: #1 (typed protocol),
else we'd fossilize the drift.

## 7. Testing infrastructure — HIGH VALUE, CHEAP
Session evidence: the Ink harness reports no stdout (desk falls back to 80 cols →
we hand-rolled component-level pins three separate times); SGR mouse events cannot
be delivered (click-sort "verified" by type-checking until proven broken); one
keyboard-timing test flakes under load; `vitest | grep` swallowed a red test into
a commit.
**Do:** (a) fix stdout injection in the harness so width-dependent layouts test
through the real mount; (b) frame snapshot tests (codex/insta style) for the
layout-regression class ('…', alignment, columns); (c) CI gate = exit codes, never
grep; (d) a scheduled live-API contract check — fixtures rot (Peru/RFK/BEA were
all invisible to fixtures and found only by live probes).

## 8. Layered typed config — MEDIUM
Keys/flags live across .env, hermes config, markets.json, ui_flags.json; the Kalshi
key needed two env vars by convention. Codex: config.toml + profiles + typed
overrides. **Do:** one typed loader (defaults < file < env < CLI), one `config
doctor`, secrets segregated.

## 9. Approval policies for autonomous tiers — MEDIUM (safety posture)
Codex formalizes sandbox + approval policy per action class. Our ledger writes are
gated (the authorizer arc) but shell/web/spend in autonomous cycles ride informal
conventions (spend caps exist per-cycle; no unified policy object).
**Do:** a policy layer: {ledger writes, network, spend, subprocess} × {auto, ask,
never} per run mode (interactive vs cycle vs cron), logged into the job record.

## 10. Release discipline — LOW/ONGOING
build-release.sh + pipx works; add: CI-verified bundle hash (the tui_dist copy is
a manual invariant today), protocol version in the hello, and a changelog gate.

## Sequencing
1 → 2 → 3 are the necessary spine (each unblocks the next: typed protocol makes the
job runtime's contracts durable; the job runtime carries the data-plane services'
refresh work). 4 runs as a background cadence (one domain per week). 7a/7c land with
#1. 5 lands with #2. 6 after #1. 9 alongside #2 (policies live on the job record).
