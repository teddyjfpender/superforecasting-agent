# TUI / Agent Design-Adoption Plan — opencode & grok-cli → Hermes Ink+Gateway

**Audience:** us (Hermes maintainers), deciding which opencode / grok-cli design
mechanisms to adopt into our Ink/React TUI + Python JSON-RPC gateway.

**Date:** 2026-06-28 · **Branch context:** `superforecasting-agent-snapshot`

## Why this doc exists

opencode (SolidJS + OpenTUI) and grok-cli (@opentui/react + Vercel AI SDK)
solve a handful of problems we've hit in our own TUI: modal collision, streaming
thrash, durable/replayable sessions, plugin extensibility, and clean streaming
lifecycle. This doc evaluates **five Tier-B ideas** against our actual stack and
returns a ranked build-now shortlist plus a deferred design backlog.

The hard constraint colouring every verdict: **we are Ink/React + a Python
gateway**, not Solid. opencode's nicest wins (reactive `batch()`, Solid slot
registry) are *Solid-runtime* primitives that don't transfer 1:1. grok-cli is
React+OpenTUI — much closer to us — but its agent core is TypeScript/Vercel AI
SDK, whereas **our agent lives in Python behind the gateway**. So "streaming
observer" for us is a *gateway/protocol* shape, not a TS class. We keep that
front of mind throughout.

Verdict vocabulary:
- **BUILD-NOW-BOUNDED** — small, isolated, high-value. Implement immediately.
- **DESIGN-PLAN** — valuable but architectural. Sketch the plan, defer the build.
- **SKIP** — don't adopt (Solid-specific, or we already have it, cite why).

---

## Idea 1 — Durable session + context-epoch architecture (opencode)

### What it is (their mechanism)
Event-sourced sessions in SQLite with two tables: `SessionMessageTable`
(`id, session_id, seq, type, data`) and `SessionContextEpochTable`
(`session_id PK, baseline, snapshot JSON, baseline_seq`). On load,
`SessionHistory.load()` reconstructs via OR-logic against `compaction.seq` /
`epoch.baselineSeq`: load messages `>= compaction.seq OR (system > baseline_seq)`.
Context recovery is a state machine — `SessionContextEpoch.prepare()` dispatches
to `initialize()` (fresh), `reconcile(snapshot)` (incremental sync), or
`replace()` (full bootstrap when `compaction.seq > baseline_seq`). `advance()`
checkpoints after each context update. The whole point: a **baseline +
baseline_seq checkpoint makes compaction atomic and replay-safe** — you never
re-apply messages that compaction already folded in.
Files: `context-epoch.ts`, `sql.ts`, `history.ts`, `store.ts`.

### Our current equivalent + its weakness
We have `_sessions` (in-memory dict: `agent, history, history_lock,
history_version, session_key`) and `_compress_session_history()` guarded by a
`history_version` CAS (`server.py:1408-1461`). Weaknesses from the baseline:
- **Compaction work is silently dropped** on a concurrent mutation
  (`history_version` mismatch → discard the compressed result, no merge,
  no tombstone). The CAS protects correctness but throws away real work.
- **No durability**: history is in-process only. A gateway restart loses
  everything; two concurrent sessions (TUI + Slack) share the same process with
  no persistence boundary.
- **session_key rotation after compaction** is manual
  (`_sync_session_key_after_compress`, `server.py:1461`); a failed re-anchor
  silently breaks the slash_worker.
- **No replay/undo.** There is no seq-indexed event log to reconstruct from.

### How it maps to our stack
This is a *gateway/Python* change, zero Ink involvement. It maps cleanly because
our `history_version` int is **already a primitive seq counter** — opencode's
`baseline_seq` is the same idea, just persisted. The mapping:
- Add a SQLite event store under `tui_gateway/` (e.g. `session_store.py`):
  `messages(session_id, seq, type, data_json)` +
  `context_epoch(session_id PK, baseline_text, snapshot_json, baseline_seq)`.
  We already have `appendCompletedTurn`-style seq tracking conceptually in
  `history_version`; promote it to a persisted `seq`.
- Reframe `_compress_session_history`'s CAS as **`epoch.advance()`**: instead of
  *discarding* on version mismatch, fold the concurrent tail (`messages >
  baseline_seq`) onto the new baseline — opencode's OR-logic merge. That kills
  the "silently drop compressed work" pain point directly.
- `session_key` rotation becomes "write a new epoch row," not "restart a
  subprocess and pray."

### Effort: **HIGH**
New persistence layer, a migration for live sessions, careful concurrency
re-think, and touching the single most load-bearing path in the gateway
(`history_lock` / compaction). This is a multi-day, adversarially-reviewed
change. It also overlaps semantically with ForecastBench/ledger persistence work
already in flight — coordinate, don't collide.

### Risk to the live TUI: **HIGH**
Compaction is on the critical path of every long session. A bug here corrupts or
loses live forecasting context. Must ship behind a flag with the in-memory path
as fallback.

### VERDICT: **DESIGN-PLAN**
The atomic-epoch idea is genuinely better than our throw-away-on-CAS-miss
behaviour and would fix a real data-loss pain point — but it's a persistence-layer
rewrite of the hottest path. Sketch it; don't rush it. **Plan:** (1) introduce
`session_store.py` with the two-table schema behind a `GATEWAY_DURABLE_SESSIONS`
flag, write-through only (in-memory remains source of truth); (2) port the
OR-logic *merge* into `_compress_session_history` so a CAS miss folds rather than
discards — *this sub-step is independently shippable and is the real win*;
(3) flip the flag to read-from-store; (4) build replay/undo on top. Note: step
(2) alone — "fold concurrent tail instead of discarding" — is arguably a
BUILD-NOW-sized correctness fix *within* the existing in-memory model and should
be pulled forward independent of the SQLite work.

---

## Idea 2 — Keymap mode-stack (opencode)

### What it is (their mechanism)
`createOpencodeModeStack()` keeps a `{ id: symbol; mode: string }[]` stack in a
`WeakMap<keymap, stack>`. `push(mode)` mints a **unique `Symbol(mode)` per call**
and appends; returns a cleanup fn that splices **by ID, not by name**.
`current()` returns `stack.at(-1)?.mode ?? BASE_MODE`. A registered layer field
sets `keymap.mode = current()` before each dispatch so OpenTUI's keymap matches
key bindings against the active mode. The collision-safety crux: two dialogs both
pushing `'dialog'` get distinct Symbols, so popping one never disturbs the other.
File: `keymap.tsx`.

### Our current equivalent + its weakness
We have a flat overlay model (`overlayStore.ts`) where prompt overlays —
`approval / clarify / confirm / sudo / secret / pager` — are **mutually exclusive
nullables**, and `$isBlocked` is a giant OR over ~24 fields. `useInputHandlers.ts`
has a single global `useInput` that early-returns on `$isBlocked` but ad-hoc
falls through for scroll via `shouldFallThroughForScroll(key)` (string-matching
`wheelUp/wheelDown/pageUp/pageDown/shift`). Weaknesses from the baseline:
- **Modal collision is a real bug**: a slash command that raises `approval`
  while a `confirm` is pending *clobbers* the pending confirm — exactly the
  problem mode-stack's symbol-scoped push solves. (Verified: `overlayStore.ts`
  stores each as a single nullable; the newer set wins, the old is lost.)
- **No priority / queue** for prompts.
- Scroll fall-through is ad-hoc; new scroll keys mean editing the handler inline.

### How it maps to our stack
The *concept* (a stack of active input contexts, scoped by unique ID so pushes
don't collide) maps perfectly and is **runtime-agnostic** — it's plain data, not
a Solid/OpenTUI keymap primitive. We don't get to reuse `@opentui/keymap`'s
field-condition machinery (that's their declarative layer system; ours is the
imperative `useInputHandlers` switch), so we port the *data structure and
discipline*, not the library.

Concrete mapping:
- Add a **prompt-overlay queue** to `overlayStore.ts`. Replace the six exclusive
  nullables conceptually with a stack `promptStack: { id: symbol; kind: 'approval'
  | 'clarify' | ...; req: ... }[]`. The *active* prompt is `promptStack.at(-1)`.
  Pushing a new prompt while one is pending **stacks** it instead of clobbering;
  resolving pops by `id`. Keep the existing named getters as thin
  `promptStack.find(kind)` shims so render code doesn't churn.
- `$isBlocked` becomes `promptStack.length > 0 || <toggles>`.
- The scroll fall-through stays, but we can later promote `shouldFallThroughForScroll`
  into a declarative `SCROLL_KEYS` set (separate, smaller win — see backlog).

This is **not** a wholesale OpenTUI keymap port; it's "give our overlay store a
collision-safe stack." That's the high-value 20%.

### Effort: **MED**
`overlayStore.ts` is the focal change plus a handful of call-sites that set/clear
prompts (`createGatewayEventHandler.ts` raises them; the overlay components
resolve them). The render layer can keep its named-overlay API via shims, which
caps the blast radius.

### Risk to the live TUI: **MED**
Input/overlay handling is user-facing and easy to regress (a stuck modal is very
visible). But the change is self-contained to one store + its setters, and is
strictly *more* correct than today (no clobber). Gate with a test that pushes
approval-over-confirm and asserts both survive.

### VERDICT: **DESIGN-PLAN** (with a BUILD-NOW carve-out)
The full stack-and-shim refactor is MED effort / MED risk → design it. **But**
the collision bug is real and the *minimal* fix — a 2-deep prompt queue so a new
prompt defers rather than clobbers a pending one — is BUILD-NOW-sized. Carve that
out: a `pendingPrompts` array in `overlayStore.ts` that holds at most the
displaced prompt and re-raises it on resolve. Ship the carve-out now; design the
full symbol-scoped stack for later.

---

## Idea 3 — 16ms streaming render-batching (opencode)

### What it is (their mechanism)
SSE `handleEvent()` queues events and tracks `elapsed` since the last flush. If
`elapsed < 16ms` and no timer is pending, it schedules `setTimeout(flush, 16)`;
otherwise it flushes immediately. `flush()` swaps the queue, schedules the next
tick, and emits all queued events inside Solid's `batch(() => …)` so reactive
effects run **once** instead of N times. Net: 60Hz SSE bursts collapse into one
render per 16ms window. File: `sdk.tsx`.

### Our current equivalent + its weakness
**We already have this.** `config/timing.ts` defines `STREAM_BATCH_MS = 16`,
`STREAM_IDLE_BATCH_MS = 16`, plus `STREAM_SCROLL_BATCH_MS = 96` and
`STREAM_TYPING_BATCH_MS = 80`. `turnController.ts` schedules flushes via
`streamTimer` at a *dynamic* `streamDelay` (`boostStreamingForTyping` →80,
`boostStreamingForScroll` →≥96, `relaxStreaming` →16) and hard-flushes on
`STREAM_BATCH_MS`. Our system is **strictly more sophisticated** than opencode's
fixed 16ms: we back off under typing/scroll pressure to keep input responsive,
which opencode does not.

The one thing opencode has that we structurally *can't* copy: Solid's `batch()`
coalesces store writes into a single reactive pass. We're on React; our
equivalent is React 18 automatic batching inside event handlers + nanostores'
own change coalescing. We already lean on that. We do **not** get Solid's
fine-grained "one effect run" guarantee, but our render buffer (`bufRef` flushed
on the timer) achieves the same *user-visible* result: one transcript update per
window.

### Effort: **N/A** · ### Risk: **N/A**

### VERDICT: **SKIP — we already have it (and better)**
Our multi-tier adaptive batching (16/80/96ms keyed to idle/typing/scroll) is a
superset of opencode's fixed 16ms. The Solid `batch()` call is a *Solid-runtime*
primitive with no React equivalent to port; our nanostores+timer buffer already
delivers the same coalescing outcome. Nothing to adopt. *(If anything, opencode
could learn the back-off trick from us.)*

---

## Idea 4 — TUI plugin system (opencode)

### What it is (their mechanism)
Plugins are declared in JSON config as `[path, options]` tuples
(`ConfigPlugin.Entry { package, options }`). `PluginLoader` stages
resolve → compat-gate (semver, npm only) → dynamic `import()`. **Zero core
imports in plugins**: `api.{renderer,theme,client,keymap,slot}` are injected at
runtime via `TuiPluginApi`. `PluginRuntimeProvider` (Solid context) owns
lifecycle (activate/deactivate/install) + a `SolidSlotRegistry`. Routes via
`createPluginRoutes()` (`Map<name, [{ key: Symbol, render }]>`, last-registered
wins). Slots via OpenTUI's slot system; plugins export `SolidPlugin<TuiSlotMap,
TuiSlotContext>` — no core-specific types. Disable via `disableDefaultPlugins`.
Files: `loader.ts`, `plugin.ts`, `runtime.tsx`, `api.ts`, `slots.tsx`.

### Our current equivalent + its weakness
**We have none.** From the baseline: zero plugin architecture; new overlays,
keybindings, renderers, or RPC handlers require forking. The gateway's `_methods`
dict is populated statically (`@method(name)` decorator, `server.py:646`) — no
runtime registration / hotload. `hermes_cli.plugins.invoke_hook` exists but lives
*outside* the gateway and can't define session-local hooks. `render.py`'s
`agent.rich_output` delegation has no version negotiation.

### How it maps to our stack
This is the **least portable** opencode idea and the most expensive. The hard
parts are deeply Solid/OpenTUI-coupled:
- `SolidSlotRegistry` + OpenTUI's slot system have **no Ink equivalent**. Ink has
  no slot/portal registry; we'd have to build one (a context-driven
  `Map<slotName, ReactNode[]>` provider) from scratch.
- Their `api.keymap` injection assumes the declarative keymap layer we don't have
  (see Idea 2).
- The dynamic-`import()` loader and semver compat gate *do* port (Node is Node),
  but the *surface* the plugins target (`api.renderer`, `api.slot`) is the
  expensive part.

What's genuinely tractable for us is the **gateway side**: turning `_methods`
from a static decorator dict into a registry that accepts runtime registration,
so a plugin module can add RPC handlers. That's a small, real win
(`method()` already centralizes registration — make it callable at runtime and
expose a `register_method(name, fn)`).

### Effort: **HIGH** (full TUI plugin surface) / **LOW** (gateway `_methods`
runtime registration alone)

### Risk to the live TUI: **MED–HIGH**
A plugin surface is a new public contract — versioning, sandboxing, failure
isolation (the baseline already notes `render.py` crashes on signature drift
before try/except). Getting this wrong destabilizes the whole TUI.

### VERDICT: **DESIGN-PLAN** (TUI surface) **+ BUILD-NOW carve-out (gateway
registry)**
A full Ink plugin/slot system is a from-scratch build with no Solid leverage —
design it, don't start it; and scope it to *our* needs (we are not a general
platform; the realistic plugin surface is "add an RPC + a fullscreen overlay,"
not arbitrary slots). **But** the gateway `_methods` → runtime-registry change is
LOW effort, isolated, and immediately useful (lets us register session-local
hooks and lazy-load handler modules without the static decorator). Carve that
out as BUILD-NOW. Also fold in the baseline's `render.py` defensiveness fix
(wrap the `agent.rich_output` call so a signature drift degrades gracefully
instead of crashing) — that's a one-liner safety win riding the same area.

---

## Idea 5 — grok-cli streaming-observer pattern

### What it is (their mechanism)
`ProcessMessageObserver` decouples agent logic from rendering via four lifecycle
hooks: `onStepStart`, `onStepFinish(finishReason, usage)`, `onToolStart`,
`onToolFinish(result)`. `agent.processMessage(text, observer?)` is an
`AsyncGenerator` yielding **semantic `StreamChunk`s** (a union:
`content | tool_calls | tool_result | tool_approval_request | error | reasoning |
done`). The UI just `for await`s the chunks and switches on `chunk.type`; the
*observer* is a separate, optional sink used for headless JSONL emission and
timing. `notifyObserver()` wraps every callback in try/catch so an observer bug
never breaks generation. Hooks (`fireHook` → `executeEventHooks`) fire at the
same semantic boundaries. Files: `agent.ts`, `headless/output.ts`, `app.tsx`.

### Our current equivalent + its weakness
We have the **shape already, split across the gateway boundary.** The gateway
emits semantic events (`message.*`, `subagent.*`, `voice.*`) and
`createGatewayEventHandler.ts` is exactly grok-cli's "switch on `chunk.type`"
consumer — it routes events into `turnController`. So our *event protocol* is the
analogue of their `StreamChunk` union. Weaknesses:
- **No clean "observer" sink.** grok-cli's second, optional observer (separate
  from the render path) is what powers *headless JSONL* and *tool timing*. We
  have no equivalent decoupled sink — observability (e.g. `cross_refs`,
  delegation status) is interleaved into the render handler with ad-hoc
  rate-limiting (the 5s `delegation.status` throttle in
  `createGatewayEventHandler.ts`).
- **Subagent status is freeform** on both sides — grok-cli's own pain point
  ("`emitSubagentStatus(detail: string)` is freeform text, UI must parse") is
  *our* pain point too (`subagent.*` carries unstructured strings).
- Our boundaries are *transport events*, not a typed union with a `done`
  sentinel; turn finalization is implicit.

### How it maps to our stack
The grok-cli class can't be ported literally — **their agent is in-process TS,
ours is Python behind JSON-RPC.** The observer pattern for *us* is two things:
1. **TS side (Ink):** Formalize the gateway event stream as a typed
   discriminated union (`GatewayStreamEvent`) mirroring grok-cli's `StreamChunk`,
   and split the monolithic `createGatewayEventHandler` into (a) the *render*
   reducer (drives `turnController`) and (b) an *observer* fan-out
   (`registerStreamObserver(obs)`) for headless/telemetry/cross-ref sinks. This
   is a clean refactor of code we already have — it just untangles render from
   observe.
2. **Python side (gateway):** Make subagent/tool status **structured**
   (`{ phase, tool, target, durationMs }`) instead of freeform strings, so both
   the TS observer and any headless emitter get schema'd signals — fixing the
   shared pain point. This is an emit-site change in the gateway's
   `subagent.*` / tool-progress paths.

The *headless JSONL emitter* itself (grok-cli `createHeadlessJsonlEmitter`) is a
natural fit for our gateway: a transport-level observer that writes JSONL — but
that's net-new surface, defer it.

### Effort: **MED**
The TS-side render/observe split is a contained refactor of one well-understood
file; the Python-side structured-status change touches a few emit sites. The full
headless-JSONL surface is the part that pushes it past LOW.

### Risk to the live TUI: **LOW–MED**
The TS refactor preserves existing behaviour (same events, just fanned out); risk
is mostly "don't drop an event during the split." Structured status is additive
(keep the freeform field, add structured fields) so it's safe.

### VERDICT: **BUILD-NOW-BOUNDED** (the observer-split + structured status) /
DESIGN-PLAN (headless JSONL surface)
The render/observe split and structured subagent status are both bounded,
high-value, and fix a *named* pain point we share with grok-cli. The full
headless JSONL emitter is net-new surface → defer. This is the best
effort-to-value ratio of the five because **we already have 80% of the
architecture**; we're just untangling and typing it.

---

## Stack-fit honesty (Ink/React vs Solid) — the through-line

- **opencode is Solid+OpenTUI.** Its two slickest mechanisms — `batch()`
  coalescing (Idea 3) and the `SolidSlotRegistry` (Idea 4) — are *Solid-runtime*
  primitives. We can copy the *outcomes* (we already do for batching) but not the
  *code*. Anything leaning on OpenTUI's declarative keymap layer (Idea 2's field
  conditions) or slot system (Idea 4) is a from-scratch rebuild for us, which is
  why those land as DESIGN-PLAN, not BUILD-NOW.
- **grok-cli is React+OpenTUI** — much closer — **but its agent is in-process
  TS.** Our agent is Python behind the gateway, so grok-cli's `ProcessMessageObserver`
  maps to a *protocol + handler-split*, not a class. That's still a clean fit
  (Idea 5) because the gateway already speaks a semantic event stream.
- **The portable ideas are data-structures and disciplines, not framework code:**
  the context-epoch *merge logic* (Idea 1, Python), the symbol-scoped *stack*
  (Idea 2, plain data), runtime *method registration* (Idea 4 gateway), and the
  *render/observe split* (Idea 5). Those travel. Framework primitives don't.

---

## BUILD-NOW shortlist (ranked — implement first)

Ranked by (value × isolation) ÷ risk. Each is small, bounded, and fixes a named
pain point.

1. **Streaming render/observe split + structured subagent status** (from Idea 5)
   — *highest value/effort ratio; we already have 80%.* Split the monolithic
   event handler into a render reducer + an observer fan-out, and make
   subagent/tool status structured.
   - Files: `ui-tui/src/app/createGatewayEventHandler.ts` (split into render
     reducer + `registerStreamObserver` fan-out), `ui-tui/src/app/interfaces.ts`
     (add `GatewayStreamEvent` discriminated union + observer types),
     `ui-tui/src/gatewayTypes.ts` (typed event payloads),
     `tui_gateway/server.py` (emit structured `subagent.*` / tool-progress
     fields alongside the existing freeform string).
   - Effort: **MED** (contained refactor; additive on the Python side).

2. **Prompt-overlay anti-clobber queue** (carve-out from Idea 2)
   — *fixes a real, user-visible bug: approval clobbers a pending confirm.* Add a
   minimal `pendingPrompts` buffer so a newly-raised prompt defers rather than
   destroying a pending one; re-raise on resolve.
   - Files: `ui-tui/src/app/overlayStore.ts` (add `pendingPrompts` array +
     push/pop helpers; `$isBlocked` already covers it),
     `ui-tui/src/app/createGatewayEventHandler.ts` (route prompt-raises through
     the queue helper instead of direct `patchOverlayState`),
     `ui-tui/src/app/interfaces.ts` (extend `OverlayState`).
   - Effort: **LOW–MED**.

3. **Gateway `_methods` runtime registry + `render.py` defensive degradation**
   (carve-out from Idea 4)
   — *unlocks session-local hooks / lazy handler modules; one-line crash-safety
   win.* Promote the static `@method` decorator dict to a registry with a
   runtime `register_method(name, fn)`, and wrap the `agent.rich_output`
   delegation so a signature drift degrades gracefully.
   - Files: `tui_gateway/server.py` (`_methods` → `register_method` + keep the
     `@method` decorator as a thin wrapper), `tui_gateway/render.py` (guard the
     `agent.rich_output` call in try/except with a plain-text fallback).
   - Effort: **LOW**.

4. **Compaction fold-not-discard** (carve-out from Idea 1)
   — *correctness fix: stop throwing away compressed history on a CAS miss.*
   Within the existing in-memory model, on `history_version` mismatch fold the
   concurrent tail onto the new baseline (opencode's OR-logic merge) instead of
   discarding the compressed result.
   - Files: `tui_gateway/server.py` (`_compress_session_history`,
     ~lines 1408–1461 — replace the discard-on-mismatch branch with a tail-fold).
   - Effort: **MED** (logic is contained, but it's the hot path — test hard).

---

## DESIGN-PLAN backlog (valuable, deferred)

- **Durable session + context-epoch (Idea 1, full).** SQLite event store
  (`session_store.py`) with `messages` + `context_epoch` tables behind a
  `GATEWAY_DURABLE_SESSIONS` flag; write-through → read-from-store → replay/undo.
  Coordinate with in-flight ledger/ForecastBench persistence. (Build-now item #4
  is the first independently-shippable slice of this.)
- **Symbol-scoped keymap mode-stack (Idea 2, full).** Replace the six exclusive
  prompt nullables with a `promptStack: {id: symbol; kind; req}[]`, keep named
  getters as `find(kind)` shims, derive `$isBlocked` from stack length. Also
  promote `shouldFallThroughForScroll` to a declarative `SCROLL_KEYS` set.
  (Build-now item #2 is the minimal anti-clobber slice of this.)
- **Ink plugin/slot system (Idea 4, full TUI surface).** Build an Ink slot
  registry (context-driven `Map<slot, ReactNode[]>`), a `[path, options]` config
  schema, a dynamic-`import()` loader with a semver/compat gate, and a
  `TuiPluginApi` injection surface. Scope to *our* realistic needs (add an RPC +
  a fullscreen overlay), not arbitrary slots. No Solid leverage — from scratch.
- **Headless JSONL emitter (Idea 5, surface).** A transport-level observer in the
  gateway that consumes the (now-split) stream and writes grok-cli-style JSONL —
  rides on build-now item #1's observer fan-out.

---

## Final note

The pattern across all five: **adopt the data-structures and disciplines, skip
the framework primitives.** Our biggest near-term wins (#1, #5-derived) come from
*untangling architecture we already have* into the cleaner shapes opencode and
grok-cli demonstrate — not from importing their Solid/OpenTUI machinery. The
genuinely-new, genuinely-better idea worth a real future investment is opencode's
**atomic context-epoch** (Idea 1): it fixes a real data-loss path, but it's a hot-
path persistence rewrite, so we slice off the correctness win (#4) now and design
the rest.
