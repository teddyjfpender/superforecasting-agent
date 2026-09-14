# Agent execution

Constructs and runs the model/tool conversation that supports forecast research. Provider transports, message preparation, budgets, memory and resource cleanup live here.

## Ownership and boundaries

Keep ledger admission in forecasting and profile persistence in the storage owner. Cancellation must retain ownership of running calls until they exit; a cancelled UI is not proof that a provider stopped.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                 | Responsibility                                                               |
| ---------------------------------------------------- | ---------------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                           | Agent internals -- extracted modules from run_agent.py.                      |
| [runtime.py](runtime.py)                             | AI Agent Runner with Tool Calling                                            |
| [account_usage.py](account_usage.py)                 | account usage.                                                               |
| [agent_factory.py](agent_factory.py)                 | The single resolve->construct path for an AIAgent.                           |
| [agent_init.py](agent_init.py)                       | Implementation of :meth:`AIAgent.__init__` — extracted as a module function. |
| [agent_runtime_helpers.py](agent_runtime_helpers.py) | Assorted AIAgent runtime helpers — moved out of run_agent.py for clarity.    |
| [anthropic_adapter.py](anthropic_adapter.py)         | Anthropic Messages API adapter for Superforecasting Agent.                   |
| [api_errors.py](api_errors.py)                       | Provider error diagnostics and safe display formatting.                      |

## Subdirectories

- [lsp/](lsp/README.md) — Language-server integration.
- [transports/](transports/README.md) — Model transports.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/agent/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../docs/architecture/ownership-map.md)
and [engineering backlog](../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)

## Delegation and provider continuity

[delegation_images.py](delegation_images.py) validates bounded child attachments
and uses [image_routing.py](image_routing.py) for the same vision policy as
interactive turns. The delegation tool owns child allocation and cancellation;
the image helper owns only payload preparation. Batch validation precedes any
allocation. Unreadable files are reported, and inline image bytes never become
ordinary prompt text for a text-only model.

[reasoning_details.py](reasoning_details.py) accumulates structured provider replay
blocks. Compatible text fragments can join, but conflicting identities, signatures
and opaque blocks remain intact. Session storage preserves that metadata for
resume; it is separate from visible reasoning text.

[result_references.py](result_references.py) reduces repeated observation payloads
without suppressing execution. It requires an original tool result still retained
in the transcript and resets on changed or failed observations. Sequential and
concurrent executors use the same helper; references survive normal session replay.
