# Model transports

Adapts provider protocols into the agent conversation model, including streaming events, tool calls and subprocess-backed sessions.

## Ownership and boundaries

Keep provider wire formats here and product commands outside this layer. Preserve tool-call identity and interruption state when projecting events.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                       | Responsibility                                                          |
| ---------------------------------------------------------- | ----------------------------------------------------------------------- |
| [**init**.py](__init__.py)                                 | Transport layer types and registry for provider response normalization. |
| [anthropic.py](anthropic.py)                               | Anthropic Messages API transport.                                       |
| [base.py](base.py)                                         | Abstract base for provider transports.                                  |
| [bedrock.py](bedrock.py)                                   | AWS Bedrock Converse API transport.                                     |
| [chat_completions.py](chat_completions.py)                 | OpenAI Chat Completions transport.                                      |
| [codex.py](codex.py)                                       | OpenAI Responses API (Codex) transport.                                 |
| [codex_app_server.py](codex_app_server.py)                 | Codex app-server JSON-RPC client.                                       |
| [codex_app_server_session.py](codex_app_server_session.py) | Session adapter for codex app-server runtime.                           |

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
[ownership map](../../docs/architecture/ownership-map.md)
and [engineering backlog](../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
