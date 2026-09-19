# Gateway protocol

Python models in this directory own the shared gateway API. The TUI consumes
[`generated.ts`](../ui-tui/src/protocol/generated.ts); edit declarations here and
run `python -m protocol.codegen` instead of editing generated types.

## Requests and results

[`RPC_SPECS`](__init__.py) binds each bundled method to parameter and result models.
The generated `RpcMethods`, `RpcArgs`, and `RpcRequest` types connect those models
to the client, safe RPC wrappers, and shared consumer interfaces. Callers cannot
choose an arbitrary result type or send parameters intended for another method.
Empty parameter objects reject extra fields too. Dispatch outcomes use a Python
root-model union with required fields for each `type` variant.

[`validation.py`](validation.py) wraps both decorator and programmatic
registration. Unknown parameters and wrong JSON value types are rejected before the handler
runs. Missing-field and domain-selector errors retain handler ownership. Handlers
retain their documented domain errors; accepted inputs and successful outputs
must conform to the declared JSON types. Contract disagreement raises in tests
and successful-response disagreement returns a generic JSON-RPC internal error
in production. Diagnostics never include parameter or result values. Known events
are checked before emission. Extension-owned payloads remain explicitly opaque;
this is a transport contract, not a substitute for forecast-ledger validation.

`config.get` and skills management retain their existing polymorphic envelopes.
Their optional fields reflect the selected operation, rather than inventing new
wire methods or breaking older clients.

## Correlated interactive requests

[`server_requests.py`](server_requests.py) declares clarification, sudo, secret,
and approval results. The backend owner is
[`tui_gateway/server_requests.py`](../tui_gateway/server_requests.py).

Hosts advertise `rpc.server_requests`. A supporting client opts in with
`server_requests: true` on session creation or resume. The server sends an ordinary
JSON-RPC request with an `srq-` ID and a session-scoped payload. The client answers
with the same ID and a method-specific `result`, or a JSON-RPC error to cancel.
`request.cancel` withdraws a request after interruption, timeout, or settlement.

Replies are accepted once and only from the owning transport. Reconnecting a
live, detached session transfers outstanding requests to the new connection and
returns them in `session.resume.open_requests`. That server snapshot is authoritative:
an answer sent just before disconnection may not have arrived. Old connections
and stale modal completions cannot answer or dismiss replacement prompts.
Closing/replacing allocations cannot be reattached.

Unanswered prompts survive a **connection** loss while the backend is alive. They
are not persisted across backend process death, and secret answers are never
saved for automatic replay. Durable session recovery remains responsible for
interrupted turns after a backend restart.

Older clients receive the existing prompt notifications and answer through the
legacy `*.respond` adapters. Request-ID-aware approval replies target the exact
queue entry. Older approval clients without IDs retain their FIFO behavior.

## Layout and checks

| Path | Responsibility |
| --- | --- |
| [rpc/](rpc/README.md) | Method parameter and result declarations |
| [events/](events/README.md) | Event payload declarations |
| [types.py](types.py) | Shared wire primitives and optional-field metadata |
| [codegen.py](codegen.py) | Deterministic TypeScript generation |
| [version.py](version.py) | Compatibility versions |
| [collab.py](collab.py) | Forecast collaboration protocol |

The blocking development gate checks formatting, lint, typing, and generated-file
freshness. [Contract tests](../tests/protocol/README.md) require every bundled
method to have a declaration and prove malformed successes fail without replacing
domain errors. TypeScript compile-time examples cover wrong method names, missing
parameters, wrong field types, and mismatched prompt results.

[↑ Repository](../README.md)

Application operations with an existing strict shared request validator can declare
`handler_validates_request` to preserve the same diagnostic across CLI and RPC.
They must validate before effects; their successful input and output still undergo
contract checks. Field-specific exceptions use `handler_validated_parameters`.
The forecast operation parity tests cover both malformed input and absence of writes.

## Data desk

Pure data-desk schemas live in `data_desk.py`; RPC envelopes live in `rpc/markets.py`. They import no application, credential, filesystem or provider owners. TypeScript generation includes nested catalog and selection types.

## Portable feed messages

[`feed_share.py`](feed_share.py) owns the transport-neutral `sfa.feed` v1/v2 snapshot
contract. It is an extra generated model, not a gateway operation. The receiving
TUI validates untrusted JSON before rendering; Python and TypeScript tests consume
[the same fixture](../tests/fixtures/feed_share/README.md). See
[message transport and trust boundaries](../docs/architecture/messaging-docs-desk.md#sharing-a-data-feed)
before adding a transport or presentation type.
