# Repository tests

Exercises repository behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                     | Responsibility                                                                                                                                                    |
| -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [**init**.py](__init__.py)                               | init .                                                                                                                                                            |
| [\_platform_mocks.py](_platform_mocks.py)                | Single source of truth for the platform-library test doubles.                                                                                                     |
| [conftest.py](conftest.py)                               | conftest.                                                                                                                                                         |
| [run_interrupt_test.py](run_interrupt_test.py)           | Run a real interrupt test with actual AIAgent + delegate child.                                                                                                   |
| [runtime_session_cleanup.py](runtime_session_cleanup.py) | Retire isolated test sessions without invoking unrelated memory/plugin hooks.                                                                                     |
| [test_account_usage.py](test_account_usage.py)           | Checks: account usage.                                                                                                                                            |
| [test_agent_factory.py](test_agent_factory.py)           | build_agent() — the single resolve->construct path for an AIAgent. Tested without importing the heavy run_agent module by patching the \_aiagent_cls indirection. |
| [test_agent_turn_budget.py](test_agent_turn_budget.py)   | Every product interprets configured execution budgets as positive integers.                                                                                       |

## Subdirectories

- [acp/](acp/README.md) — acp.
- [acp_adapter/](acp_adapter/README.md) — acp adapter.
- [agent/](agent/README.md) — agent.
- [application/](application/README.md) — application.
- [cli/](cli/README.md) — cli.
- [cron/](cron/README.md) — cron.
- [deploy/](deploy/README.md) — deploy.
- [e2e/](e2e/README.md) — e2e.
- [fakes/](fakes/README.md) — fakes.
- [fixtures/](fixtures/README.md) — fixtures.
- [forecasting/](forecasting/README.md) — forecasting.
- [gateway/](gateway/README.md) — gateway.
- [honcho_plugin/](honcho_plugin/README.md) — honcho plugin.
- [hosting/](hosting/README.md) — hosting.
- [integration/](integration/README.md) — integration.
- [openviking_plugin/](openviking_plugin/README.md) — openviking plugin.
- [plugins/](plugins/README.md) — plugins.
- [providers/](providers/README.md) — providers.
- [run_agent/](run_agent/README.md) — run agent.
- [runtime_cli/](runtime_cli/README.md) — runtime cli.
- [scripts/](scripts/README.md) — scripts.
- [skills/](skills/README.md) — skills.
- [storage/](storage/README.md) — storage.
- [stress/](stress/README.md) — stress.
- [tooling/](tooling/README.md) — tooling.
- [tools/](tools/README.md) — tools.
- [trajectories/](trajectories/README.md) — trajectories.
- [tui_gateway/](tui_gateway/README.md) — tui gateway.
- [tui_pty/](tui_pty/README.md) — tui pty.
- [website/](website/README.md) — website.

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
