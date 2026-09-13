# Proxy provider adapters

Translates supported provider request and authentication conventions for the proxy server.

## Ownership and boundaries

Keep provider-specific wire behavior here and shared listener lifecycle in the parent package. Preserve upstream error meaning without exposing credentials.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                             | Responsibility                                        |
| -------------------------------- | ----------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)       | Upstream adapter registry for the local proxy server. |
| [base.py](base.py)               | Abstract base for proxy upstream adapters.            |
| [nous_portal.py](nous_portal.py) | Nous Portal upstream adapter.                         |
| [xai.py](xai.py)                 | xAI Grok OAuth upstream adapter.                      |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/runtime_cli/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
