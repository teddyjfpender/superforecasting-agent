# Forecast ledger

Owns durable questions, evidence, resolutions, scores, lessons and workflow state through the ledger facade and focused storage modules.

## Ownership and boundaries

This is the admission boundary for persistent forecasting state. Enforce semantic contracts before writes, preserve provenance, and make lifecycle retries atomic and idempotent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                                        |
| -------------------------------- | --------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)   | Public ledger facade composed from the focused operations below.      |
| [core.py](core.py)               | Connection and ledger initialization shared by persistent operations. |
| [questions.py](questions.py)     | Question creation and retrieval at the durable admission boundary.    |
| [evidence.py](evidence.py)       | Timestamped evidence records and their provenance.                    |
| [resolutions.py](resolutions.py) | Resolution persistence and semantic admission.                        |
| [scoring.py](scoring.py)         | Score persistence and computation for resolved questions.             |
| [workflow.py](workflow.py)       | Lifecycle progression and recoverable handoffs.                       |
| [lessons.py](lessons.py)         | Calibration lesson storage and applicability history.                 |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/forecasting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

Portfolio/question exports and calibration row collection use a shared read
transaction so concurrent writers cannot mix revisions within a result.
`list_scores(question_id=...)` filters at the storage query; exports retain
invalidated score history without scanning unrelated questions.
