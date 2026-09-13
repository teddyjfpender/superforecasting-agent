# Cron tests

Exercises cron behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                         | Responsibility                                                          |
| ---------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                                   | init .                                                                  |
| [test_codex_execution_paths.py](test_codex_execution_paths.py)               | Checks: codex execution paths.                                          |
| [test_compute_next_run_last_run_at.py](test_compute_next_run_last_run_at.py) | Test that compute_next_run uses last_run_at for cron jobs.              |
| [test_cron_context_from.py](test_cron_context_from.py)                       | Tests for cron job context_from feature (issue #5439 Option C).         |
| [test_cron_inactivity_timeout.py](test_cron_inactivity_timeout.py)           | Tests for cron job inactivity-based timeout.                            |
| [test_cron_no_agent.py](test_cron_no_agent.py)                               | Tests for cronjob no_agent mode — script-driven jobs that skip the LLM. |
| [test_cron_profile.py](test_cron_profile.py)                                 | Tests for per-job profile support in cron jobs.                         |
| [test_cron_prompt_injection_skill.py](test_cron_prompt_injection_skill.py)   | Regression guard: skill content loaded at cron runtime must be scanned. |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/cron/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
