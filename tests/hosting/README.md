# Hosting tests

Exercises hosting behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                     | Responsibility                                                               |
| ---------------------------------------- | ---------------------------------------------------------------------------- |
| [test_background.py](test_background.py) | Deterministic background ownership through failures, stop and session close. |
| [test_desk_agent.py](test_desk_agent.py) | Hosted launch policy works without an RPC server or terminal runtime.        |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/hosting/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
