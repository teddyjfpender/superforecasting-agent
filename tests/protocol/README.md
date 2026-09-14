# Gateway contract regression tests

These tests enforce the protocol owner's declarations at the Python gateway
boundary. They check bundled-method coverage, reject unknown parameters before
side effects, preserve documented domain errors, and ensure malformed successful
responses fail without disclosing payloads or credentials.

The corresponding TypeScript compile-time examples live in
[`rpcContracts.typecheck.ts`](../../ui-tui/src/protocol/rpcContracts.typecheck.ts).
They are included in the normal TUI type check and verify method-specific inputs,
required parameters, inferred results, and correlated prompt answers.

Run `scripts/run_tests.sh tests/protocol` from the repository root. Regenerate
client types with `python -m protocol.codegen` after changing a declaration;
never patch the generated file manually.
