# Language-server integration

Manages language-server processes, workspaces, protocol messages and diagnostic reporting for code-oriented tools.

## Ownership and boundaries

Record the process and workspace actually acquired. Shutdown must not close a replacement server; protocol parsing should be testable without an installed language server.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                         |
| -------------------------------- | ---------------------------------------------------------------------- |
| [**init**.py](__init__.py)       | Language Server Protocol (LSP) integration for Superforecasting Agent. |
| [cli.py](cli.py)                 | cli.                                                                   |
| [client.py](client.py)           | Async LSP client over stdin/stdout.                                    |
| [eventlog.py](eventlog.py)       | Structured logging with steady-state silence for the LSP layer.        |
| [install.py](install.py)         | Auto-installation of LSP server binaries.                              |
| [manager.py](manager.py)         | Service-level orchestration for LSP clients.                           |
| [protocol.py](protocol.py)       | Minimal LSP JSON-RPC 2.0 framer over async streams.                    |
| [range_shift.py](range_shift.py) | Diff-aware line-shift map for cross-edit LSP delta filtering.          |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/agent/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
