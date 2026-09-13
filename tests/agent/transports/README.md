# Agent / Transports tests

Exercises agent/transports behavior and regressions using the canonical Python test environment. Read the test names and fixtures below to locate the contract closest to a change.

## Ownership and boundaries

Keep test profiles isolated from user state and use controlled providers for failures. Assert durable effects and resource ownership, not private implementation details. Credential-dependent and native-platform tests must report explicit skips when prerequisites are absent.

## Start here

These are entry points and representative modules, not an exhaustive inventory.

| File                                                                   | Responsibility                                                       |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------- |
| [\_\_init\_\_.py](__init__.py)                                             | init .                                                               |
| [test_bedrock_transport.py](test_bedrock_transport.py)                 | Tests for the BedrockTransport.                                      |
| [test_chat_completions.py](test_chat_completions.py)                   | Tests for the ChatCompletionsTransport.                              |
| [test_codex_app_server_runtime.py](test_codex_app_server_runtime.py)   | Tests for the optional codex app-server runtime gate.                |
| [test_codex_app_server_session.py](test_codex_app_server_session.py)   | Tests for CodexAppServerSession — drive turns through a mock client. |
| [test_codex_event_projector.py](test_codex_event_projector.py)         | Checks: codex event projector.                                       |
| [test_codex_transport.py](test_codex_transport.py)                     | Tests for the ResponsesApiTransport (Codex).                         |
| [test_forecast_tools_mcp_server.py](test_forecast_tools_mcp_server.py) | Checks: forecast tools mcp server.                                   |

## Working in this directory

Run checks from the repository root:

```sh
python3 scripts/dev.py check
scripts/run_tests.sh tests/agent/transports/
```

Use the canonical runner for Python tests so isolation and environment settings
match repository policy. Extend a regression around the changed contract; use
controlled failures for retries, cancellation and interrupted writes. The full
Python suite is required before pushing.

Update this guide when entry points or ownership change. See the
[ownership map](../../../docs/architecture/ownership-map.md)
and [engineering backlog](../../../TODO.md) for cross-package context.

[↑ Parent directory](../README.md)
