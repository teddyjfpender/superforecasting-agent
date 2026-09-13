# Shared application operations

Owns reusable session, history, retry, goal, plugin, tool and configuration-view behavior consumed by CLI, TUI and gateway adapters.

## Ownership and boundaries

Validation, defaults and operation errors belong here. Adapters own prompts and rendering; this layer must not import presentation modules.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                           | Responsibility                                                                 |
| ---------------------------------------------- | ------------------------------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)                     | Interface-independent session and host application operations.                 |
| [command_output.py](command_output.py)         | Request-local command output without replacing process streams.                |
| [configuration_view.py](configuration_view.py) | Read-only configuration reporting shared by terminal and RPC consumers.        |
| [footer.py](footer.py)                         | Shared runtime-footer inspection and atomic configuration transitions.         |
| [goals.py](goals.py)                           | Shared goal command transitions; products own display and kickoff delivery.    |
| [handoff.py](handoff.py)                       | Attempt-scoped handoff observation independent of presentation and gateway IO. |
| [history.py](history.py)                       | Detached history edits shared by conversation interfaces.                      |
| [insights.py](insights.py)                     | Shared argument contract for session usage insights.                           |

## Subdirectories

- [command_catalog/](command_catalog/README.md) — Command catalog.

Command input validation also lives in [command_input.py](command_input.py). It
preserves argument identity and rejects malformed wire values or board quoting
before command execution and gateway notification routing.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/application/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
