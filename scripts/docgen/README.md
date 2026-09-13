# Reference documentation generation

Builds reference pages from configuration, command, provider, protocol, skill and job registries.

## Ownership and boundaries

Update the source registry before regenerating documentation. Keep output deterministic and avoid documenting unsupported commands or capabilities.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                         | Responsibility                                                             |
| -------------------------------------------- | -------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                   | Living reference-doc generator for the Superforecasting Agent.             |
| [\_\_main\_\_.py](__main__.py)                   | `python -m scripts.docgen` — generate (or `--check`) the reference docs.   |
| [cli_reference_doc.py](cli_reference_doc.py) | Render `docs/reference/cli-reference.md` by walking the CLI argparse tree. |
| [common.py](common.py)                       | Shared rendering helpers for the reference-doc generators.                 |
| [config_env_doc.py](config_env_doc.py)       | Render `docs/reference/config-and-env.md` from the source itself.          |
| [hooks_rules_doc.py](hooks_rules_doc.py)     | Render `docs/reference/hooks-rules.md` from the built-in forecast hooks.   |
| [job_types_doc.py](job_types_doc.py)         | Render `docs/reference/job-types.md` from the jobs registry.               |
| [protocol_doc.py](protocol_doc.py)           | Render `docs/reference/protocol.md` from the protocol registry.            |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/scripts/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
