# Gateway event declarations

Declares typed events for turns, tools, prompts, jobs, markets and desk state sent to product clients.

## Ownership and boundaries

Events must preserve durable identity and ordering information needed for reconnects. Update generation and consumer tests when changing a payload.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                       | Responsibility                                                                  |
| -------------------------- | ------------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py) | Event model families (one module per event family).                             |
| [commands.py](commands.py) | Live native command events, distinct from durable forecast-turn records.        |
| [desk.py](desk.py)         | Wire models for the sessionless forecast-desk events (`tui_gateway/server.py`). |
| [gateway.py](gateway.py)   | Wire models for the gateway lifecycle / session events.                         |
| [jobs.py](jobs.py)         | Wire models for the sessionless `jobs.*` events (Arc B on Arc A).               |
| [markets.py](markets.py)   | Wire models for the Markets "Models" tab streaming events.                      |
| [pm.py](pm.py)             | Wire model for the sessionless `pm.tick` streaming event.                       |
| [prompts.py](prompts.py)   | Wire models for the blocking-prompt events (`tui_gateway/server.py`).           |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
