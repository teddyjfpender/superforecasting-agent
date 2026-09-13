# Observability integrations

Contains optional tracing and observability exporters for agent execution.

## Ownership and boundaries

Observability failures must not corrupt forecast or session state. Redact credentials and sensitive transport parameters before export.

## Subdirectories

- [langfuse/](langfuse/README.md) — langfuse integration.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/plugins/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
