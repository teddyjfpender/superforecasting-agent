# Auditable forecast changes

Represents proposed ledger operations, previews, reviews, quorum decisions and application of approved changes with provenance.

## Ownership and boundaries

Bind approval to the reviewed revision and operation digest. Preserve history and distinguish proposed changes from applied ledger state.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility                                                         |
| ------------------------------------ | ---------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)           | Authoritative ledger changesets, policy, and review state.             |
| [models.py](models.py)               | Versioned, deterministic ledger changeset models.                      |
| [apply.py](apply.py)                 | Transactional application of reviewed ledger changesets.               |
| [collaboration.py](collaboration.py) | Slack-thread changeset ownership and cross-platform identity bindings. |
| [compatibility.py](compatibility.py) | Compatibility bridge for legacy forecast update proposals.             |
| [policy.py](policy.py)               | Deterministic risk classification and human-review quorum.             |
| [preview.py](preview.py)             | Deterministic, non-mutating changeset previews.                        |
| [provenance.py](provenance.py)       | Provenance bundles, decision records, and publication consent.         |

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
