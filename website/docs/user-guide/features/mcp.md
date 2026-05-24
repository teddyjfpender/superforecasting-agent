---
sidebar_position: 4
title: "MCP (Model Context Protocol)"
description: "Connect Superforecasting Agent to external data and tool servers via MCP."
---

# MCP (Model Context Protocol)

MCP lets Superforecasting Agent connect to external tool servers: databases, GitHub, file systems, browser stacks, internal APIs, research corpora, market data services, and other systems that can support forecast research. The forecast ledger remains the source of truth for probabilities, evidence, assumptions, model runs, scores, postmortems, and calibration lessons; MCP tools are supporting connectors.

Use MCP when an existing server can provide source access or workflow automation without writing a native tool first.

## What MCP Gives You

- external data and tool ecosystems for forecast research
- local stdio servers and remote HTTP MCP servers in one config
- automatic tool discovery at startup
- optional resource and prompt wrappers when the server supports them
- per-server filtering so only forecast-relevant tools are exposed
- runtime toolsets such as `mcp-github` that can be enabled or disabled explicitly

## Quick Start

MCP support is included in the standard install. For editable checkouts:

```bash
cd superforecasting-agent
uv pip install -e ".[mcp]"
```

Add a server to `~/.superforecasting-agent/config.yaml`:

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/forecast-research"]
```

Start the CLI:

```bash
superforecasting-agent chat
```

Then ask for a research action, not a silent probability update:

```text
Use the filesystem MCP server to inspect the election-data directory and summarize which files could support question F-142.
```

The runtime discovers the MCP server's tools and makes them available like other tools. Forecast updates still need explicit ledger writes through the forecast workflow.

Legacy `~/.hermes/config.yaml` and `hermes chat` remain compatibility paths where installed.

## Server Types

### Stdio Servers

Stdio servers run as local subprocesses and communicate over stdin/stdout.

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
```

Use stdio when the server is local, low-latency access matters, or upstream MCP docs show `command`, `args`, and `env`.

### HTTP Servers

HTTP MCP servers are remote endpoints:

```yaml
mcp_servers:
  research_api:
    url: "https://mcp.example.com/mcp"
    headers:
      Authorization: "Bearer ***"
```

Use HTTP when your organization hosts the server, the data source is remote, or you do not want the forecast runtime spawning a local subprocess.

## Configuration Reference

Superforecasting Agent reads MCP config from `~/.superforecasting-agent/config.yaml` under `mcp_servers`.

| Key | Type | Meaning |
|---|---|---|
| `command` | string | Executable for a stdio MCP server |
| `args` | list | Arguments for the stdio server |
| `env` | mapping | Environment variables passed to the stdio server |
| `url` | string | HTTP MCP endpoint |
| `headers` | mapping | HTTP headers for remote servers |
| `timeout` | number | Tool call timeout |
| `connect_timeout` | number | Initial connection timeout |
| `enabled` | bool | If `false`, skip the server entirely |
| `supports_parallel_tool_calls` | bool | If `true`, tools from this server may run concurrently |
| `tools` | mapping | Per-server tool filtering and utility policy |

Minimal stdio:

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
```

Minimal HTTP:

```yaml
mcp_servers:
  company_data:
    url: "https://mcp.internal.example.com"
    headers:
      Authorization: "Bearer ***"
```

## Built-In Presets

For known servers, `superforecasting-agent mcp add` accepts `--preset`:

```bash
superforecasting-agent mcp add codex --preset codex
```

The `codex` preset wires the Codex CLI MCP server:

```yaml
mcp_servers:
  codex:
    command: "codex"
    args: ["mcp-server"]
```

The inherited `hermes mcp add ...` command remains a compatibility alias.

## Tool Naming

MCP tools are prefixed to avoid collisions:

```text
mcp_<server_name>_<tool_name>
```

Examples:

| Server | MCP tool | Registered name |
|---|---|---|
| `filesystem` | `read_file` | `mcp_filesystem_read_file` |
| `github` | `create-issue` | `mcp_github_create_issue` |
| `market-data` | `query.prices` | `mcp_market_data_query_prices` |

Most users do not need to call these names manually; the runtime chooses tools during research and review workflows.

## Utility Tools

When the server supports resources or prompts, the runtime can register:

- `list_resources`
- `read_resource`
- `list_prompts`
- `get_prompt`

These are registered per server, for example `mcp_docs_read_resource`. The wrappers appear only when both the server capability and your config allow them.

## Filtering

Filtering is both a product-quality control and a security control. Prefer exposing only the tools that help research, evidence capture, modeling, source monitoring, or alert delivery.

Disable a server:

```yaml
mcp_servers:
  legacy:
    url: "https://mcp.legacy.internal"
    enabled: false
```

Whitelist tools:

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, search_code]
```

Blacklist dangerous actions:

```yaml
mcp_servers:
  billing:
    url: "https://mcp.billing.internal"
    tools:
      exclude: [delete_customer, refund_payment]
```

If both `include` and `exclude` are present, `include` wins.

Disable utility wrappers:

```yaml
mcp_servers:
  docs:
    url: "https://mcp.docs.example.com"
    tools:
      prompts: false
      resources: false
```

If every callable tool and utility wrapper is filtered out, the runtime does not create an empty MCP toolset for that server.

## Runtime Behavior

MCP servers are discovered at startup and registered in the normal tool registry.

When servers send `notifications/tools/list_changed`, Superforecasting Agent re-fetches the tool list and updates the registry. Prompt and resource change notifications are received but not yet acted on.

If you edit MCP config manually, reload from an interactive session:

```text
/reload-mcp
```

Each configured MCP server also creates a runtime toolset when it contributes at least one tool:

```text
mcp-<server>
```

## Security Model

Stdio servers do not receive the full shell environment. Only configured `env` plus a safe baseline are passed through.

Recommended forecast-desk posture:

- expose read-only tools by default
- use `include` lists for sensitive sources
- remove destructive tools from API, billing, cloud, and database servers
- disable prompt/resource wrappers when they are not needed
- keep source reliability and evidence timestamps in the forecast ledger, not in MCP transient output

## Forecast Use Cases

### GitHub Release-Risk Evidence

```yaml
mcp_servers:
  github:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "***"
    tools:
      include: [list_issues, search_code, get_file_contents]
      prompts: false
      resources: false
```

Example:

```text
Find open blockers related to the release branch and summarize evidence for forecast F-203 without changing its probability.
```

### Internal Metrics Source

```yaml
mcp_servers:
  metrics:
    url: "https://mcp.metrics.internal"
    tools:
      include: [query_timeseries, list_dashboards]
```

Example:

```text
Pull the last 30 days of incident counts for forecast F-188 and add them as timestamped evidence if relevant.
```

### Filesystem Research Corpus

```yaml
mcp_servers:
  research_files:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/forecast-research"]
```

Example:

```text
Inspect the stored reports for AI benchmark results and identify which ones are admissible for the current backtest.
```

## Parallel Tool Calls

By default, MCP tools run sequentially. Opt in only when the server tools are safe to run concurrently:

```yaml
mcp_servers:
  docs:
    command: "docs-server"
    supports_parallel_tool_calls: true
```

Parallel calls are appropriate for read-only queries and independent API calls. Avoid them for tools that mutate shared files, ledgers, databases, credentials, or external resources.

## MCP Sampling

MCP servers can request LLM inference through `sampling/createMessage`. This lets a server generate summaries or transformations without owning model credentials.

Sampling is enabled by default when the MCP SDK supports it:

```yaml
mcp_servers:
  my_server:
    command: "my-mcp-server"
    sampling:
      enabled: true
      model: "openai/gpt-4o"
      max_tokens_cap: 4096
      timeout: 30
      max_rpm: 10
      max_tool_rounds: 5
      allowed_models: []
      log_level: "info"
```

Disable it for untrusted servers:

```yaml
mcp_servers:
  untrusted_server:
    url: "https://mcp.example.com"
    sampling:
      enabled: false
```

The sampling handler has rate limits, per-request timeouts, and tool-loop depth limits. Treat sampled text as an intermediate artifact unless it is attached to a forecast ledger record with source and model provenance.

## Running the Runtime as an MCP Server {#running-hermes-as-an-mcp-server}

Superforecasting Agent can also expose a stdio MCP server for other MCP clients. This is an inherited bridge for messaging and approval workflows; it is not the primary forecast product surface.

Use it when:

- a coding or research client needs to read forecast-alert conversations
- an external client needs to send a review note through a connected gateway platform
- you already run the gateway with connected platforms

Start the server:

```bash
superforecasting-agent mcp serve
```

Compatibility installs may still use:

```bash
hermes mcp serve
```

Example MCP client config:

```json
{
  "mcpServers": {
    "superforecasting-agent": {
      "command": "superforecasting-agent",
      "args": ["mcp", "serve"]
    }
  }
}
```

If you are temporarily bridging an inherited Hermes virtualenv during the fork transition:

```json
{
  "mcpServers": {
    "superforecasting-agent": {
      "command": "/home/user/.hermes/hermes-agent/venv/bin/hermes",
      "args": ["mcp", "serve"]
    }
  }
}
```

Available bridge tools:

| Tool | Description |
|------|-------------|
| `conversations_list` | List active messaging conversations |
| `conversation_get` | Get detailed info for one conversation |
| `messages_read` | Read recent message history |
| `attachments_fetch` | Extract non-text attachments from a message |
| `events_poll` | Poll for new conversation events |
| `events_wait` | Wait for the next event |
| `messages_send` | Send a message through a configured platform |
| `channels_list` | List messaging targets |
| `permissions_list_open` | List pending approvals |
| `permissions_respond` | Allow or deny a pending approval |

The bridge reads conversation data from the session store under the active agent home, normally `~/.superforecasting-agent/` with legacy `~/.hermes/` fallback. The gateway must be running for send operations.

Current limits:

- the embedded server is stdio-only
- event polling is in-memory and starts when the bridge connects
- sends are text-only
- no `claude/channel` push notification protocol yet

## Troubleshooting

### MCP server not connecting

Check runtime dependencies and local server CLIs:

```bash
uv pip install -e ".[mcp]"
node --version
npx --version
```

Then verify config, credentials, and server reachability before restarting the CLI or gateway.

### Tools not appearing

Common causes:

- server connection failed
- discovery failed
- filters excluded the tools
- the utility capability does not exist on that server
- `enabled: false` is set

### Resource or prompt utilities are missing

Those wrappers appear only when your config allows them and the MCP session supports the capability.

## Related Docs

- [Use MCP with Superforecasting Agent](/docs/guides/use-mcp-with-hermes)
- [CLI Commands](/docs/reference/cli-commands)
- [Slash Commands](/docs/reference/slash-commands)
- [FAQ](/docs/reference/faq)
