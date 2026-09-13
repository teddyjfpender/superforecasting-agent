# Shared meeting integration

Provides common meeting support used by meeting-specific plugins.

## Ownership and boundaries

Keep reusable meeting behavior here and platform credentials, delivery and registration in their respective plugins.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                         | Responsibility                                                                                                                                                                                                                            |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)   | Shared meeting primitives used by both meeting surfaces (Teams pipeline + Google Meet followup): a common MeetingSummary model and a transcript -> summary/action-item summarizer, so action items are extracted the same way everywhere. |
| [summarize.py](summarize.py) | Shared meeting summarizer: transcript -> {summary, key_decisions, action_items, risks}.                                                                                                                                                   |

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
