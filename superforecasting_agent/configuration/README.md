# Configuration interpretation

Owns defaults, provider identity, validation and pure interpretation of configuration and environment values.

## Ownership and boundaries

Keep filesystem writes in storage. Do not persist merged defaults or resolved secrets as if they were raw user configuration.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                             | Responsibility                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------ |
| [**init**.py](__init__.py)                       | Configuration values shared by hosts, services and product adapters.           |
| [agent_limits.py](agent_limits.py)               | Pure selection of positive, whole-number agent execution budgets.              |
| [authentication.py](authentication.py)           | Provider authentication metadata and pure credential selection policy.         |
| [browser.py](browser.py)                         | Browser endpoint validation shared by command and transport adapters.          |
| [codex_catalog.py](codex_catalog.py)             | Offline Codex model defaults and forward-compatible catalog rules.             |
| [defaults.py](defaults.py)                       | Shared product defaults; data only, without profile or runtime initialization. |
| [env_lines.py](env_lines.py)                     | Pure environment-file repair, independent of credential discovery and I/O.     |
| [environment_catalog.py](environment_catalog.py) | Environment-key metadata shared by startup and configuration interfaces.       |

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
