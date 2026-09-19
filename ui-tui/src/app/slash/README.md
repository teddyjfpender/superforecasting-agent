# Terminal slash routing

This directory owns local terminal commands and their dispatch metadata. Shared
forecast, configuration and job operations remain backend-owned; local handlers
translate user intent into versioned RPC requests and render the results.

## Entry points and contracts

- [`registry.ts`](registry.ts) resolves built-in command names and aliases.
- [`types.ts`](types.ts) defines command handlers and their per-invocation context.
- [`../createSlashHandler.ts`](../createSlashHandler.ts) coordinates catalog aliases,
  backend dispatch, fallback and stale-response admission.
- [`../interfaces.ts`](../interfaces.ts) defines `SlashHandlerContext`. Its gateway
  dependency exposes requests, logs and reconnect capabilities, without access to
  client construction, process handles or destruction.
- [`commands/`](commands/README.md) contains local command behavior.

Use generated method-to-parameter/result mappings through `GatewayRpc` and the
client's typed request function. Do not add caller-selected response casts or
replicate provider validation and persistence here. Unknown backend failures remain
errors; only the documented handoff error permits the slash-execution fallback.

## Execution and recovery

Each user invocation owns a flight identifier and session identity. Late responses
must pass both guards before changing the transcript. A reconnect is requested from
the host; slash handlers do not kill or replace transport resources themselves.

Catalog and backend aliases share a visited-name path. Cycles fail locally; chains
stop after 32 steps, including chains of unique names. This bound belongs to one
invocation and must not prevent a later deliberate retry. Alias errors never become
outgoing chat messages.

## Extending and testing

Add local metadata and behavior together, retaining documented aliases. Add a typed
fixture using `src/testing/rpcFixtures.ts`; unsupported calls must reject instead of
returning an empty success. Cover session replacement while a response is pending,
domain errors and any new state mutation.

From `ui-tui/`, run focused checks:

```sh
npx vitest run src/__tests__/slashCapabilities.test.ts src/__tests__/createSlashHandler.test.ts
npm run type-check
npm run lint
```

The complete test-type project remains a separate migration target. Passing
production TypeScript alone does not qualify legacy fixtures. See the repository
[ownership map](../../../../docs/architecture/ownership-map.md) and
[engineering backlog](../../../../TODO.md).

[Parent directory](../README.md)
