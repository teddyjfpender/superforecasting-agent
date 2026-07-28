# Deep dive: the protocol registry and the gateway

This is the internals of **Arc A** — the protocol-first gateway. The
[architecture overview](../architecture.md#arc-a--protocol-first-gateway) states
the thesis (one source of truth for every wire message, with the TUI's types
generated from it); this page is the mechanism: how the registry is shaped, how
the codegen walks it, why there are *two* different validation strategies on the
server, and the drift-bug catalog the migration surfaced. For the generated
per-message reference, see [reference/protocol.md](../reference/protocol.md) —
it is emitted from the same registry described here.

---

## The registry

`protocol/__init__.py` holds two lists — `RPC_SPECS` (**101 RPCs**) and
`EVENT_SPECS` (**46 events**) — plus `EXTRA_MODELS` (a handful of models that must
reach the codegen but aren't a single RPC's primary request/response). Each entry
is a frozen dataclass:

```python
@dataclass(frozen=True)
class RpcSpec:
    method: str                 # the wire method name, e.g. "pm.list"
    request: type[WireModel]
    response: type[WireModel]
    exclude_none: bool = False  # drop None keys on serialize (venue conditional keys)

@dataclass(frozen=True)
class EventSpec:
    name: str                   # the wire event name, e.g. "jobs.progress"
    model: type[WireModel]
```

Models live one module per family under `protocol/rpc/` (forecast, pm, jobs,
markets, session, config, agents, …) and `protocol/events/` (turn, tools,
prompts, subagents, voice, desk, markets, warnings, gateway, pm, jobs). Every
model inherits `WireModel` (`protocol/types.py`). `registered_models()` returns
each spec's request/response/payload plus `EXTRA_MODELS`; the codegen collector
discovers nested models transitively from there.

`exclude_none` exists for the venue models that emit *conditional* keys —
`pm.stream.start` omits an empty `subscribed`, `pm.stream.stop` emits one of
`closed`/`remaining`. Everything else keeps `null` on the wire.

### The tolerant-model pattern

`WireModel` sets `model_config = ConfigDict(extra="ignore")`. This is deliberate
and load-bearing: **unknown request keys are dropped, never rejected**, so
wrapping a handler in validation changes no wire behaviour — a client sending an
extra field still works exactly as before. The core fields a handler actually
reads stay required; the tolerance is only at the edges. A field the server emits
additively but the model doesn't declare survives via an explicit whitelist
(`_PASSTHROUGH_RESULT_KEYS = ("stale", "catalog")` in `pm_rpc.py`) so
`model_dump` can't silently swallow it.

`wire_optional()` (in `types.py`) is the field helper for keys the server emits
*conditionally*: it defaults to `None`, sets `wireOptional` in
`json_schema_extra`, and the response serialises with `exclude_none=True` so the
key is **absent** (not `null`). `wire_optional(nullable=True)` marks a field that
may be absent *and*, when present, `null` — codegen renders `name?: null | T`.
This mirrors the many forecast-family fields the old hand-written mirrors typed as
`field?: null | string`.

---

## The codegen

`python -m protocol.codegen` emits `ui-tui/src/protocol/generated.ts`. It is a
hand-rolled, dependency-free emitter (`protocol/codegen.py`, ~230 lines) that
walks `model_fields` **directly** — no pydantic JSON-Schema / `$ref` juggling.
The output is **deterministic**: interfaces sorted by TS name, fields sorted by
name, union members sorted (TS unions are order-independent), so the file is
diff-stable and a staleness gate can assert byte-equality.

What it produces:

- `export const PROTOCOL_VERSION = 1`
- `WireEventName` (a string-literal union of all 46 event names) and
  `WIRE_EVENT_NAMES` (the readonly array)
- `WireEvent` — a `SCREAMING_SNAKE`-keyed const object. This is the **only** place
  a raw event-name string literal is allowed to live; every `gw.on`/`emit`/switch
  in the TUI references `WireEvent.X`, so a renamed or removed event is a compile
  error, never a silent miss.
- one `export interface` per collected model (**399** interfaces at last count,
  from 252 top-level models plus nested discovery; the count was 370 when the
  arc closed at A4 and grows as models are added)

The type mapping (`_ts_scalar`) handles `Literal` → string-literal union (sorted),
`tuple[...]` → positional TS tuple (**never** sorted — a tuple's order is
significant), `list[X]` → `X[]`, `dict[str, V]` → `Record<string, V>` (bare
`dict` → `Record<string, unknown>`), and the scalar aliases. `_split_optional`
strips a trailing `| None`; a genuine multi-member union
(`float | dict | str | None`) becomes a sorted joined type. `_collect` walks
every field — unwrapping `list[Model]` / `dict[str, Model]` and every union
member — so a model referenced only inside a container or a union is still
emitted.

### The gate

`python -m protocol.codegen --check` re-renders and compares; a mismatch exits
nonzero with a teaching error (`generated TypeScript types are STALE … run
python -m protocol.codegen`). It runs as `scripts/check-protocol.sh` in
`.github/workflows/tests.yml`, in the `pre-commit` and `pre-push` git hooks, and
is mirrored by the pytest golden-file test `tests/test_protocol_codegen.py`.
Change a model without regenerating and the build fails loudly instead of drifting
into a runtime mystery. (See [testing.md](testing.md) for the exit-code-gate
doctrine this is an instance of.)

---

## Two validation strategies (and why)

The server validates wire messages two different ways, on purpose.

### Strategy 1 — re-dump (pm.* and market.*)

`tui_gateway/pm_rpc.py` and `tui_gateway/market_rpc.py` wrap each handler with a
local `_rpc_model(method, handler)`:

1. validate the request against `spec.request` — a `ValidationError`
   short-circuits to the existing `_err` path with the offending field named
   (`ValidationError` subclasses `ValueError`, so the code stays `-32602`);
2. on success, round-trip the result through `spec.response` and **re-serialise**
   via `model_dump(mode="json", exclude_none=spec.exclude_none)`.

For a well-formed venue payload the re-dump is byte-identical to the handler's own
`to_dict`. A payload that does **not** validate (a test stub, or genuine latent
drift) **passes through unchanged and is logged** — so the wire can never regress
mid-migration. Whitelisted out-of-model markers (`stale`) are re-attached after
the dump.

### Strategy 2 — validate-only (forecast.* family)

`tui_gateway/server.py`'s `rpc_validated(name)` decorator is deliberately safer:
it validates the request and the success result against their models, **logs any
drift**, and **always returns the handler's original result unchanged**. The
request is validated-and-logged but **never short-circuits**.

Two reasons this family gets the weaker guarantee:

- **Re-serialise risk.** These are the big partial builder payloads (dashboard,
  workspace, question packet). Re-dumping them through a model would risk dropping
  or adding keys on a shape the model imperfectly captures. Validate-only means
  the JSON on the wire is byte-for-byte what the handler emitted.
- **A richer error taxonomy.** The forecast handlers own their own error codes —
  **4003** (bad/insufficient arguments, e.g. `triage.relabel` needs
  `label_id + label`), **4004**, **5008** (the general forecast-handler error —
  most forecast `_err` calls), **5009**. `pm`/`market` collapse everything to a
  uniform `-32602`. Short-circuiting the request would replace the handler's own
  field checks and change error codes, so the handler stays the sole gate.

Both strategies fall back to a plain `@method` registration if a method has no
registered spec (every wrapped method has one).

---

## The drift-bug catalog (all 11)

The arc's thesis — *transcribing the real wire will expose latent
client/server disagreements* — was proven by the disagreements it found. Eleven,
all resolved toward the server's actual behaviour, documented in-model:

**A1 (pm.*, found day one):**

1. `total_volume` typed nullable on the TUI; the server **always** emits it.
2. `pm.history` `range` narrowed to 3 literals on the TUI; the server accepts any
   string (the suite uses `"1m"`).
3. `pm.tick` `estimate`/`payload` marked optional; both are **always** present.
4. a `count` field the server emits but no TUI reader consumed.

**A2 (events, tally → 9):**

5. `tool.complete.error` was **read** by the handler but **never emitted** —
   failed tools rendered as unflagged successes. (The most consequential bug.)
6. `subagent.iteration` was always `undefined`.
7. `message.complete` dropped `status` + `warning`.
8. `skin` dropped `name`.
9. `"voice.command"` was never a wire event at all.

**A3 (forecast family, tally → 11):**

10. `forecast.calibration` emits an operator practice-loop key the mirror never
    declared.
11. `forecast.reforecast.status`'s mirror **over-declared** `progress[]` /
    `task_summary` that the handler never emits.

**A4 — the close.** A DEBUG validator scan over every one of the 56 validate-only
wrapped handlers found **zero** further mismatches. The tally closes at 11.

---

## The version handshake

`protocol/version.py`: `PROTOCOL_VERSION = 1`, `MIN_SUPPORTED = 1`. There is **no
per-message versioning** — the whole wire is one version, bumped only on a
breaking change.

The gateway advertises it on the `gateway.ready` hello frame
(`tui_gateway/entry.py` emits `{"skin": …, "protocol_version": PROTOCOL_VERSION,
"build": …}`) and on `session.info`. The TUI's `GatewayClient.checkProtocolVersion`
(`ui-tui/src/gatewayClient.ts`) compares the advertised value against the
`PROTOCOL_VERSION` baked into its generated module and **warns once** (to the
startup-log channel the status line drains) on a mismatch. A **missing** field (an
older gateway predating the handshake) is silently tolerated; a mismatch **never
hard-fails**. The point is to make protocol evolution *observable* rather than a
silent shape-drift mystery.

### The build-info rider

The hello frame (and `session.info`) also carries a typed **`BuildInfo`**
(`protocol/events/gateway.py`; declared `wire_optional()` on `session.info` in
`protocol/rpc/session.py`): the running **application** version — deliberately
distinct from `protocol_version`, which only versions the wire — plus, when the
cached update check has landed, the newest published release and a staleness
verdict. `tui_gateway.server.build_info()` fills it from the already-scheduled,
6-hour-cached background update check — never its own network call, so it can
neither delay `gateway.ready` nor fail offline; `version` is the only guaranteed
key. The TUI consumes it through `ui-tui/src/lib/buildInfo.ts`: the version
renders on the Home hero's context line (`branding.tsx`, `buildVersionLabel`)
and as the first line of the `h` help overlay (`buildSummaryLine`), and
`forecast doctor` prints the same verdict in its `◆ Build Version` section. The
model exists because a pipx-installed build freezes its own TUI bundle inside
its venv — a repo-side rebuild never reaches it, and the operator previously
had no way to tell which binary they were in.

### The client lifecycle: respawn and the reap

Gateway death is recoverable, bounded, and visible
(`ui-tui/src/gatewayClient.ts`). An unexpected exit triggers a respawn ladder —
exponential backoff from 500 ms to an 8 s cap, at most
`GATEWAY_MAX_RESTARTS = 5` attempts — with the attempt budget **earned back by
uptime**: the stability clock starts at `gateway.ready`, not at spawn, so
"crashes right after ready" still exhausts the ladder instead of looping
forever. While reconnecting, the desk shows a reconnecting state; when the
ladder is exhausted a **terminal** state renders the captured stderr tail plus
the `/reconnect` · `/logs` · `/quit` escape hatches
(`ui-tui/src/content/gatewayLost.ts`), and a successful respawn **resumes the
prior session** on the ready path (`createGatewayEventHandler.ts`,
`resumeById`) rather than landing in a blank one. A *deliberate* stop — quit,
or the OOM guard — sets the one flag that separates a quit from a crash and
never respawns.

The reap is real: `kill()` was historically fire-and-forget — a bare SIGTERM
with no await, so node exited in ~0.1 s while the gateway (whose own SIGTERM
handler logs thread stacks first) took 0.6–1.1 s to die and was reparented to
init: one leaked process per clean exit. `reapChild()` now EOFs stdin, sends
SIGTERM, and escalates to SIGKILL after a bounded grace
(`GATEWAY_KILL_GRACE_MS`, default 1500 ms, with a 500 ms hard floor); the
terminal is restored first so the wait is never visible, and the OOM path stops
the gateway the same way instead of orphaning it.

---

## The gateway shape

The gateway is a **stdio JSON-RPC** server. `tui_gateway/entry.py` writes the
`gateway.ready` event, then loops over newline-delimited JSON on `stdin`, calling
`server.dispatch(req)` and writing each response to `stdout`. Malformed input
yields a `-32700` parse error; a broken stdout pipe logs to the crash log and
exits `0`. Signals (`SIGTERM`/`SIGHUP`) are logged with full thread stacks;
`SIGPIPE` is ignored so a background thread writing to a quiet pipe can't silently
kill the process (`BrokenPipeError` is handled on the offending write instead).

### Method registration

`server.py` keeps a module-level `_methods` dict. Handlers register three ways,
all routing through one `register_method(name, fn)`:

- `@method(name)` — the static decorator;
- `@rpc_validated(name)` — `@method` plus the validate-only wrapper (forecast
  family);
- `register_method(name, fn)` at import time — the plugin/extension path.

`dispatch` normalises the request, then either handles it inline or, for a method
in `_LONG_HANDLERS`, submits it to a thread pool (the worker writes its own
response via the bound transport when done).

### The `*_rpc.py` module pattern

Families that are large or self-contained live in their own module that exposes a
single `register(server)`; `server.py` only imports and calls it. **Fifteen**
family modules register today (`tui_gateway/*_rpc.py`): `jobs`, `pm`, `market`,
`obsidian`, `market_models`, `forecast`, `rollback`, `agents`, `subagents`,
`completion`, `voice`, `browser`, `commands`, `tools`, and `cron_skills`.
Each module's handlers are thin: they drive the one service (`PMService`,
`MarketDataService`, the jobs `JobStore`/`runtime`) and never call a venue client
directly. This is what keeps `server.py` (~6.3k lines after the carve) from
owning every family's logic and makes each family unit-testable against its
service.

### Transport + contextvars session isolation

`tui_gateway/transport.py` decouples the I/O sink from handler logic so the same
dispatcher drives stdio (`entry.py`) or WebSocket (`ws.py`). The active transport
for the current request is tracked in a `contextvars.ContextVar`, so a handler —
including one dispatched onto the worker pool — routes its writes (and any events
it emits) to the right peer. `dispatch` binds the transport, snapshots the context
with `contextvars.copy_context()` before submitting to the pool, and the worker
runs inside that snapshot. Per-session runtime state (the model a session switched
to) is keyed by `session_key`; `write_json` falls back to the module-level
`StdioTransport` when nothing is bound, so tests that monkeypatch
`server._real_stdout` keep working (the stdio transport resolves the stream lazily
through a callback).

---

## Sources

- `protocol/__init__.py`, `protocol/types.py`, `protocol/version.py`,
  `protocol/codegen.py`
- `tui_gateway/pm_rpc.py`, `tui_gateway/market_rpc.py`, `tui_gateway/server.py`
  (`rpc_validated`, `register_method`, `dispatch`, `_LONG_HANDLERS`),
  `tui_gateway/entry.py`, `tui_gateway/transport.py`
- `ui-tui/src/gatewayClient.ts` (`checkProtocolVersion`, the respawn ladder,
  `reapChild`), `ui-tui/src/protocol/generated.ts`,
  `ui-tui/src/lib/buildInfo.ts`, `ui-tui/src/content/gatewayLost.ts`
- Build info: `protocol/events/gateway.py` (`BuildInfo`),
  `protocol/rpc/session.py`, `tui_gateway/server.py` (`build_info`)
- Drift catalog mined from the ARC A1–A4 commit messages (`80ae3429f`,
  `6b13707a2`, `d69e9e5e4`, `13b9fdf93`) and `docs/plans/2026-07-03-architecture-delivery-plan.md`
- Counts verified live: `RPC_SPECS`=101, `EVENT_SPECS`=46, 399 generated interfaces
