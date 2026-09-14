# Research runtime controls

These controls keep forecast-support work predictable without changing scored
calibration lessons or active forecast probabilities. Interactive transport
ownership is documented in the [gateway protocol](../../protocol/README.md).

## Background memory and skill review

`agent/review_options.py` resolves background-review settings before constructing
the fork. Configure the supported controls in `config.yaml`:

```yaml
auxiliary:
  background_review:
    provider: auto
    model: ""
    base_url: ""
    max_iterations: 16
    max_tokens: null
    reasoning_effort: ""
```

| Setting | Meaning |
| --- | --- |
| `provider: auto`, empty model/endpoint | Inherit the active runtime and credentials |
| `model` | Select a review model; a model-only change retains live provider credentials |
| `provider`, `base_url` | Select a separate destination through the shared resolver; requires an explicit model and never borrows the parent's key for that destination |
| `max_iterations` | Review tool-loop budget, from 1 through 90 |
| `max_tokens` | Optional per-response output ceiling, from 1 through 131072; provider/model limits still apply |
| `reasoning_effort` | Canonical reasoning setting; empty preserves existing same-model behavior |

Existing cancellation and disposal ownership still applies. Review forks retain
only memory/skill write capabilities and cannot operate session tools. Changing
routing can lose the parent's cached prompt prefix. The settings provide cost
control; no measured cost saving is claimed without provider usage evidence.

## MCP response limits

`superforecasting_agent/tooling/mcp_http.py` owns the HTTPX factory used by MCP's
SSE, current HTTP, and legacy HTTP transports. HTTPX continues to own TLS, proxies,
authentication, timeouts, and client shutdown.

Finite bodies and individual SSE events are limited to 10 MiB before the SDK
buffers or parses them. A long-lived stream may contain many bounded events.
The stream wrapper handles LF, CRLF, bare CR, and delimiters split between chunks.
Limit failures close the underlying response stream and report an HTTP read error.

Requests advertise `Accept-Encoding: identity`; compressed responses are rejected
so decompression cannot expand beyond the pre-parser bound. An MCP server that
requires compressed responses must be reconfigured to honor identity encoding.
Tool-output truncation remains a separate, later presentation limit.

## Mid-session model changes

Deliberate model selection in CLI, TUI, and messaging shares
`superforecasting_agent/application/model_switch_notice.py`. It uses the context
accounting baseline, including recovered session measurements, and explains that
a large conversation may lose its prompt cache and incur uncached input charges.

`display.model_switch_warning_tokens` defaults to `100000`; `0` disables the
notice. The message is advisory and does not add a confirmation step. Automatic
provider failure recovery does not invoke this manual-selection policy.

## Upstream provenance

These changes adapt existing owners rather than merging unrelated upstream code:

- [Consumer-connected contracts](https://github.com/NousResearch/hermes-agent/commit/f6306d1920039a2fba508fe9d570d68d6a314dd3)
- [Bidirectional requests](https://github.com/NousResearch/hermes-agent/commit/ebe8cda8eac5860cc01d19d5b109da73a0df46a0)
- [Review routing](https://github.com/NousResearch/hermes-agent/commit/47714f9402af9df7ac1f8a4f0c71b8b518a7cd84)
- [MCP bounds](https://github.com/NousResearch/hermes-agent/commit/a6fdadfcee0c503e1ab406f035038261f9d21e86)
- [Model-switch context notice](https://github.com/NousResearch/hermes-agent/commit/8b6931393e5201768e62767abad03c30d2a27a41)
