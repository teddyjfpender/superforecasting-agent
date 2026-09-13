# Realtime meeting support

Contains realtime audio and model interaction support for the meeting plugin.

## Ownership and boundaries

Preserve stream identity across cancellation and shutdown. Late audio or model events must not revive a disposed meeting session.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility                                              |
| ------------------------------------ | ----------------------------------------------------------- |
| [**init**.py](__init__.py)           | Realtime speech subpackage for the google_meet plugin (v2). |
| [openai_client.py](openai_client.py) | OpenAI Realtime API WebSocket client + file-queue speaker.  |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
