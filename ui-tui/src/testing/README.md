# Terminal test helpers

Controlled inputs and bounded asynchronous assertions for the Ink client. These
helpers support tests; forecasting policy and durable state remain backend-owned.

## Helpers and ownership

| Helper | Use |
| --- | --- |
| [settle.ts](settle.ts) | Wait for the content under test with a deadline and useful failure output; a quiet stream is not proof that a request finished. |
| [rpcFixtures.ts](rpcFixtures.ts) | Register handlers against generated RPC parameter/result types. Unregistered calls reject instead of returning an empty success. |
| [dataDesk.ts](dataDesk.ts) | Supply the real catalog manifest and a controlled selection backend for desk views. This older fixture still needs migration to typed method handlers. |

Keep every fixture's state local to its test. Explicitly control pending responses,
errors and event ordering. Await `render` before using or disposing its result;
`renderSync` is synchronous. Always release the rendered instance in cleanup.

## Contracts

Use `RpcFixtures.handle(method, handler)` to bind a result to its method. When
passing `request` as a callback, bind it to the fixture instance. See
[the fixture contract tests](../__tests__/rpcFixtures.test.ts) and
[slash capability tests](../__tests__/slashCapabilities.test.ts).

The bundled renderer accepts `TerminalInput`/`TerminalOutput` stream capabilities,
including in-memory `PassThrough` streams. Do not cast them to OS terminal streams
or to `never`. Use only declared render options: the inherited `debug` option is
not implemented by this renderer. Consumers such as the scroll helper should
require the capabilities they actually use, so minimal fixtures remain truthful.

## Validation

Run the affected test files, then production lint/types. From `ui-tui/`:

```sh
npx vitest run src/__tests__/rpcFixtures.test.ts src/__tests__/scroll.test.ts
npm run lint
npm run type-check
npx tsc --noEmit -p tsconfig.tests.json
```

The last command includes test fixtures. It currently reports inherited errors;
production typechecking does not establish test type safety. Do not hide those
errors with broad casts, exclusions or blanket suppressions. The engineering plan
requires the complete test project to become blocking after migration.

Native terminal qualification is separate: controlled streams do not prove PTY,
ConPTY, resize or platform shutdown behavior. See the
[ownership map](../../../docs/architecture/ownership-map.md) and
[implementation specification](../../../docs/plans/2026-09-19-engineering-improvement-specification.md).
