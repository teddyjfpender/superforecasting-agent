# Terminal distribution

Builds the independently installable terminal companion wheel, containing its Python launcher and compiled Ink assets.

## Ownership and boundaries

Do not bundle backend ownership into this distribution. The launcher selects a backend interpreter or remote gateway and checks protocol compatibility.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                 | Responsibility                                                    |
| -------------------- | ----------------------------------------------------------------- |
| [setup.py](setup.py) | Never produce an installable client missing its compiled product. |

## Subdirectories

- [superforecasting_agent_tui/](superforecasting_agent_tui/README.md) — Installed terminal launcher.

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
