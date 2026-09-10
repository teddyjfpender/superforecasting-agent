# Deep dive: the detached-job runtime

This is the internals of **Arc B** — one runtime for every long-running background
capability. The [architecture overview](../architecture.md#arc-b--one-detached-job-runtime)
states the shape (every background capability is a *type* on one runtime, so it
arrives pre-integrated with progress, coalescing, cancellation, persistence, and
desk re-attach). This page is the mechanism: the record and its store, the
coalescing math, the cancellation cascade, each of the five type contracts, how a
job detaches, and the heartbeat rules that decide what still counts as "running".
The generated per-type reference is [reference/job-types.md](../reference/job-types.md).

```
jobs.start ─▶ JobStore.write(record)  ─▶ runtime.run(job_id)
                                            │  resolve(record.type) → JobType.execute(spec, ctx)
                                            │  ctx.progress(...) coalesced at type.min_interval_s
                                            ▼
              jobs.progress / jobs.complete / jobs.error  (+ optional legacy alias events)
```

---

## The record and the store

`forecasting/jobs/model.py` — `JobRecord` is one dataclass, one shape for every
job. `job_id` is prefixed `job_`; `type` names the registered `JobType`. Key
discipline: **`None` is never `0`** — the accounting fields (`done_count`/`total`/
`current`) stay `None`/`0` until a phase actually sets them, so a mid-flight poll
reads honestly rather than showing a fabricated zero. Terminal states are a small
machine: `STATUSES = ("queued", "running", "done", "error", "cancelled")`, where
`cancelled` is a **graceful** terminal (the run finished after a cooperative
cancel, its partial work durable) and `error` is a crash.

`forecasting/jobs/store.py` — `JobStore` is one JSON file per job under
`{home}/jobs/{job_id}.json`, written **atomically** (temp file + `os.replace`),
with `sort_keys=True` so the file is diff-stable. A sibling `{job_id}.stop` file is
the durable cross-process cancel signal (a cheap `stat` poll, unlike an in-memory
Event). `home` resolves lazily per call from `get_agent_home()`, so a test's
per-test `HERMES_HOME` and a subprocess's propagated home are both honoured.

### The legacy read-shim

`JobRecord.from_dict` ignores unknown keys and **shims the pre-migration record
shapes** onto the canonical fields: a legacy `rf_*`/`qr_*` record keyed its id as
`run_id` (→ `job_id`) and its kind as `mode` or `spec.mode` (→ `type`). The store
scans two legacy dirs (`reforecast_runs/` with prefix `rf_`, `quorum_runs/` with
`qr_`) and shims each file into a `JobRecord`, so the per-type read paths
(`reforecast.list_jobs`, `quorum.list_jobs`) collapse onto **one** store-level
path and a run that was in flight across the migration still answers a
status/active query.

---

## The coalescing math

`forecasting/jobs/context.py` — `JobContext` is the execution-time handle a job
type receives. Its `progress()` accepts a raw payload dict or `phase=`/`done=`/
`total=` keywords. In-memory accounting is updated on **every** call (cheap); only
the **sink** (the gateway's event emit) and **persistence** are time-gated.

The gate is `min_interval_s` per type, with three invariants that **always** pass
regardless of the throttle:

- **FIRST** — the opening event of a run always emits (`_last_emit_at is None`);
- **PHASE-CHANGE** — any change of `phase` always emits;
- **FINAL** — a terminal phase name (`done`/`complete`/`completed`/`error`/
  `cancelled`/`finished`) **or** `done >= total` always emits.

So the final value can never be swallowed. As a belt-and-braces guarantee, a
throttled event is **held** as `_pending` and `flush()`ed at close — the runtime
calls `ctx.flush()` before writing the terminal state, so even a last value that
is neither terminal nor a phase change still lands. This is the structural fix for
the old 1,300-event storm: the per-warning throttle that used to live inline in the
gateway is gone; coalescing is now a property of the runtime, impossible to forget.

`emit_count` is exposed purely as a test hook to assert how many events actually
passed the coalescer.

---

## Cancellation — a three-layer cascade

`ctx.should_cancel()` is polled by a job body before each unit of work and
**latches** once set. It checks, in order:

1. the in-process signal — the gateway's `threading.Event` (`extra_should_cancel`),
   the fast path;
2. the durable stop-file / record flag — `store.is_cancel_requested(job_id)`,
   true if **either** the `.stop` file exists (the cheap cross-process poll) **or**
   the record's `cancel_requested` flag is set.

`store.request_cancel` writes the `.stop` file **and** stamps `cancel_requested`
on the record (for observability via `jobs.status`). The gateway's `jobs.cancel`
handler additionally `.set()`s the in-process Event. A cancel probe that raises is
swallowed — a broken probe must never break the run.

`runtime.run` (`forecasting/jobs/runtime.py`): resolves the type (an unknown type
is an immediate `error`), flips to `running`, executes, `flush()`es, then writes
`cancelled` when the summary carries `cancelled=True` else `done`; any exception
becomes `error` with a `{TypeName}: {message}` string. `clear_stop` runs in a
`finally`. The runtime is **transport-agnostic**: in the gateway it runs on a
daemon thread with progress/complete/error hooks wired to event emit; as a
detached process the persisted record *is* the channel a poller reads.

---

## The five type contracts

`forecasting/jobs/types/` — each `JobType` declares `execute`, a `min_interval_s`
progress policy, an optional `alias_namespace` (a legacy event prefix its aliased
RPCs still emit), and a `spend_class` (`agent` = spends model budget; `free` =
does not — the approval seam, wired now as a pass-through). Registering a type is
the whole cost of adding a background capability.

| Type | `spend` | `min_interval_s` | `alias_namespace` | Contract |
| --- | --- | --- | --- | --- |
| `warnings` | free | `0.125` | `forecast.warnings.automode` | Background sweep of the open `alert_events` backlog; a faithful lift of the gateway's old `_run` body wiring `run_warning_resolution` to `ctx.progress`/`ctx.should_cancel`. `0.125` ≈ the old inline ~8 events/s throttle for the noisy `alert` phase. |
| `reforecast` | agent | `0.0` | `forecast.reforecast` | The Desk "mass LLM re-run" (`A`): the **full formal chain** per question (research → base-rate → model → gated commit) via `run_forecast_chain`, sequentially (one LLM session at a time), **fail-open per question**. Recovers saturation + auto-quorum from the **real** artifacts the commit produced, never fabricated. |
| `task` | agent | `0.0` | `forecast.reforecast` | The Desk free-text "fix loop": one bounded `run_conversation` over a batch, scoped to a composed instruction + the questions (each carrying its readiness gaps). The final summary is the agent's own `final_response`. Shares the reforecast alias namespace. |
| `refresh` | free | `0.0` | *(none)* | The Desk "Update now" (`U`/mass-`U`): the **deterministic** re-pool (`refresh_forecast`), per question sequentially, fail-open. The net-new, no-legacy-family capability — the Arc-B payoff proof. |
| `quorum` | agent | `0.0` | *(none)* | One multi-model Delphi run per job (panelists + judge synthesis), minutes of wall-clock. A faithful lift of `quorum_jobs.execute_job`. Read-only status is served by the `forecast.quorum.status` alias. |

Two contract subtleties worth their own note:

- **The refresh write-gate catch.** The deterministic re-pool commits through the
  **same gate** the CLI `forecast refresh` runs: `execute` opens
  `allow_ledger_writes(reason="forecast_cli")` around each `refresh_forecast` so
  `create_snapshot`'s panel/style/saturation/distribution gates fire **unchanged**.
  Opening the gate does not *weaken* it — it only marks the worker thread as the
  recognised legitimate writer (see the write-gate in
  [architecture.md, Arc D](../architecture.md#arc-d--the-forecast-ledger-nine-domain-leaves--a-gate)).
  The single-row CLI refresh's analyst-brief write-up is **deliberately skipped** —
  that's an LLM call, and the mass deterministic sweep stays LLM-free by contract
  (the `A` reforecast type is the LLM arm).
- **Quorum's `min_interval_s=0.0`.** Nothing is throttled, so every
  `{stage, detail, at}` step lands exactly as the old per-append write did — the
  audit trail is coarse (a panelist/judge/record handful, not a storm), and legacy
  consumers assert specific stages are present. `refresh`/`reforecast`/`task` use
  `0.0` for the same reason: their progress is a few dozen phase-alternating
  events, every one a phase-change that passes the coalescer regardless.

---

## Detached spawn

Heavy work detaches as a **child process**, not a thread: the one-shot CLI/RPC
that enqueues exits as soon as it has the id, so a thread would be killed with it.
`quorum.start_job` / `reforecast.start_job` write a queued `JobRecord`, then
`subprocess.Popen([sys.executable, "-m", "forecasting.jobs", "run", job_id])` with
`start_new_session=True` (fresh session, fresh contextvars, defaults), `cwd` at the
repo root, all stdio to `DEVNULL`. `wait=True` runs `runtime.run` inline instead
(tests, and the CLI's synchronous path).

`forecasting/jobs/__main__.py` is the detached entrypoint. A fresh process has no
plugins, so it **discovers search/extract providers first** (mirroring the legacy
quorum/reforecast workers), then runs the job to its terminal state and exits `0`
on `done`/`cancelled`, `1` otherwise.

---

## Aliases and the byte-compatibility doctrine

The migration's rule: **the desk never broke**. Legacy RPC names are kept as thin
aliases over the runtime that return the **exact** current response shapes.

- `tui_gateway/jobs_rpc.py` registers `jobs.start`/`status`/`active`/`cancel` plus
  the aliases `forecast.warnings.automode.run`/`.cancel`,
  `forecast.reforecast.start`/`.status`/`.active`, and `forecast.desk.task`. Each
  alias validates, caps, enqueues, and reports in the byte-compatible shape the
  desk already speaks.
- Any job whose type declares an `alias_namespace` emits **that legacy event
  family alongside** `jobs.*` — `_emit_progress` fires both `jobs.progress` and
  `{ns}.progress`, so the alerts view keeps working unchanged regardless of which
  entry point started the job.
- New runs carry `job_` ids; a legacy `rf_`/`qr_` run still on disk is answered by
  the type module's read-shim, so a response's `run_id` is simply whatever id the
  record has.

Note the shared read path: `reforecast_start`'s spec has no explicit `mode` (it
defaults to `reforecast`), while `desk_task` sets `mode="task"` — both are read by
the one `forecast.reforecast.status` handler, which also derives `quorums_started`
from results carrying `quorum_autorun`.

The in-process `jobs_rpc._spawn` snapshots the request's contextvars into the
worker thread (home override, tenant runtime, session) — a verbatim lift of the
old gateway `_run` wrapper's `copy_context()` semantics — and tracks a per-job
`threading.Event` in `_running` for the fast in-process cancel path.

---

## The heartbeat cutoff (the counted-forever bugs)

`JobStore.active()` returns `queued`/`running` records, newest first — but a
record only counts as **live while its heartbeat is fresh**. Two real records
would otherwise read as forever-running and keep the Home "✦ N agents running"
chip lit indefinitely:

1. a worker that **crashed or was killed** (OOM, SIGKILL, a segfault in the
   detached child) never reaches the runtime's try/except, so it never writes a
   terminal status — the record is stuck at `running` on disk;
2. a pre-migration legacy `rf_`/`qr_` file with **no `status` key** — the read-shim
   rebuilds it and `JobRecord` **defaults `status` to `queued`** (an active
   status), so a finished/abandoned legacy run scans as in-flight.

The runtime stamps `updated_at` on every progress write, so a live job's heartbeat
advances continuously. `_heartbeat_epoch` reads the freshest of `updated_at` /
`created_at`; a record with no parseable heartbeat **cannot be proven live** and is
treated as stale. `ACTIVE_HEARTBEAT_MAX_STALE_S = 1800` (30 min, mirroring the
process registry's `FINISHED_TTL`) is the cutoff: older than that, or no heartbeat,
and the record is excluded. Pass `max_stale_s=None` to disable the gate.

---

## Client-side: `useJobAttach`

`ui-tui/src/app/useJobAttach.ts` is the **one** detached-job attach hook. Every
Desk background job (the `A`/`T` agent runs, the `U`/mass-`U` refresh) has one
lifecycle, so the Desk's two near-identical poll+re-attach effects collapse onto
this:

- **mount discovery** — `jobs.active {types}` returns newest-first; attach to the
  first live job (unless an explicit `attach()` already won the race);
- **poll** — `jobs.status {job_id}` every `JOB_POLL_MS` (5s); a terminal status
  fires `onComplete` and releases the attachment;
- **event tightening** — a `jobs.progress`/`complete`/`error` for *our* job
  re-polls at once (the 5s interval is the floor), via the same `gw.on('event')`
  channel `createGatewayEventHandler` consumes;
- **cleanup** — `stop()` tears down the interval, unsubscribes, and guards late
  resolves.

The imperative core (`attachJobLoop`) is renderer-free and unit-testable without a
React tree; the caller supplies `onProgress(record)`/`onComplete(record)` and maps
the generic `JobRecord` into its own view state, so nothing in the hook is
job-type-specific.

---

## Sources

- `forecasting/jobs/model.py`, `store.py`, `context.py`, `runtime.py`,
  `__main__.py`, `__init__.py`
- `forecasting/jobs/types/__init__.py`, `warnings.py`, `reforecast.py`, `task.py`,
  `refresh.py`, `quorum.py`
- `tui_gateway/jobs_rpc.py`
- `ui-tui/src/app/useJobAttach.ts`
- Job types verified live: `['quorum', 'reforecast', 'refresh', 'task', 'warnings']`
- Background context: `docs/plans/2026-07-03-architecture-delivery-plan.md` (Arc B)
