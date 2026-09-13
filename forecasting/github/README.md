# GitHub collaboration integration

Handles GitHub application authentication, installation capabilities, webhook events, discussions, publication and reconciliation.

## Ownership and boundaries

Check installation permissions and publication consent before external writes. Separate received events from verified changes and preserve reconciliation identity on retries.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                 | Responsibility                                                           |
| ------------------------------------ | ------------------------------------------------------------------------ |
| [**init**.py](__init__.py)           | GitHub App control-plane integration.                                    |
| [app.py](app.py)                     | GitHub App installation authentication kept inside the control plane.    |
| [auth.py](auth.py)                   | GitHub App user OAuth with PKCE and encrypted token persistence.         |
| [capabilities.py](capabilities.py)   | Single-use GitHub request capabilities executed by the control plane.    |
| [checks.py](checks.py)               | Publish authoritative ledger promotion and application GitHub checks.    |
| [discussion.py](discussion.py)       | Bounded, owner-attributed GitHub discussion for forecast changesets.     |
| [events.py](events.py)               | Idempotent GitHub webhook projection into reviews and merge/apply state. |
| [installations.py](installations.py) | Durable GitHub App installation and repository permission state.         |

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
