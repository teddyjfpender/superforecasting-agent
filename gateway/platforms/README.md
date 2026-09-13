# Messaging platform adapters

Implements external messaging transports, converting platform messages and attachments into gateway events and delivering responses.

## Ownership and boundaries

Enforce transport authentication, payload limits and platform identity here. Session policy and command behavior belong to gateway and application owners.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                              | Responsibility                                               |
| ------------------------------------------------- | ------------------------------------------------------------ |
| [\_\_init\_\_.py](__init__.py)                        | Platform adapters for messaging integrations.                |
| [\_http_client_limits.py](_http_client_limits.py) | Shared HTTP client factory for long-lived platform adapters. |
| [api_server.py](api_server.py)                    | OpenAI-compatible API server platform adapter.               |
| [base.py](base.py)                                | Base platform adapter interface.                             |
| [bluebubbles.py](bluebubbles.py)                  | BlueBubbles iMessage platform adapter.                       |
| [dingtalk.py](dingtalk.py)                        | DingTalk platform adapter using Stream Mode.                 |
| [discord.py](discord.py)                          | discord.                                                     |
| [email.py](email.py)                              | email.                                                       |

## Subdirectories

- [qqbot/](qqbot/README.md) — QQ bot transport.

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/gateway/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
