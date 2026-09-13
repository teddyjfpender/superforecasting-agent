# Public backend package

Provides canonical product entrypoints and shared application, configuration, credential, hosting, storage and tool services.

## Ownership and boundaries

The backend must remain usable without Node or dashboard assets. Resolve installed code paths separately from profile data; keep product interfaces as consumers of shared owners.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                               | Responsibility                                                             |
| ---------------------------------- | -------------------------------------------------------------------------- |
| [**init**.py](__init__.py)         | Public Superforecasting Agent API, loaded only when requested.             |
| [**main**.py](__main__.py)         | Run the forecast CLI with `python -m superforecasting_agent`.              |
| [bootstrap.py](bootstrap.py)       | Windows UTF-8 bootstrap for Superforecasting Agent entry points.           |
| [cli.py](cli.py)                   | Fork-native CLI entrypoint for Superforecasting Agent.                     |
| [clock.py](clock.py)               | Timezone-aware clock for Superforecasting Agent.                           |
| [constants.py](constants.py)       | Shared constants for Superforecasting Agent.                               |
| [environment.py](environment.py)   | Environment aliases and typed values shared by runtime entry points.       |
| [installation.py](installation.py) | Installation ownership and managed-configuration policy without CLI setup. |

## Subdirectories

- [application/](application/README.md) — Shared application operations.
- [configuration/](configuration/README.md) — Configuration interpretation.
- [credentials/](credentials/README.md) — Credential services.
- [hosting/](hosting/README.md) — Host and resource ownership.
- [mcp/](mcp/README.md) — Forecast MCP server.
- [runtime/](runtime/README.md) — Product runtime adapters.
- [storage/](storage/README.md) — Durable profile storage.
- [tooling/](tooling/README.md) — Shared tool infrastructure.
- [trajectories/](trajectories/README.md) — Batch trajectories.

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
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
