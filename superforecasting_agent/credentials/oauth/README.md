# OAuth credential lifecycle

Implements token storage, refresh, routing, callback and device-flow behavior for supported OAuth providers.

## Ownership and boundaries

Preserve credential ownership during refresh and concurrent writes. Callback validation and token persistence are security boundaries; interactive rendering belongs outside this package.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                   | Responsibility                                                           |
| -------------------------------------- | ------------------------------------------------------------------------ |
| [**init**.py](__init__.py)             | Provider-specific OAuth operations behind the credential service facade. |
| [api_keys.py](api_keys.py)             | Api keys operations; shared state belongs to credentials.auth.           |
| [callbacks.py](callbacks.py)           | Callbacks operations; shared state belongs to credentials.auth.          |
| [codex.py](codex.py)                   | Codex operations; shared state belongs to credentials.auth.              |
| [common.py](common.py)                 | Common operations; shared state belongs to credentials.auth.             |
| [device_flow.py](device_flow.py)       | Device flow operations; shared state belongs to credentials.auth.        |
| [external_oauth.py](external_oauth.py) | External oauth operations; shared state belongs to credentials.auth.     |
| [minimax.py](minimax.py)               | Minimax operations; shared state belongs to credentials.auth.            |

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
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
