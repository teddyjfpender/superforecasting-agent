---
sidebar_position: 11
title: "ACP Editor Integration"
description: "Use the forecast desk inside ACP-compatible editors."
---

# ACP Editor Integration

Superforecasting Agent can run as an [Agent Client Protocol](https://agentclientprotocol.com/) server so ACP-compatible editors can talk to the runtime over stdio and render:

- forecast-scoped chat messages
- tool activity
- file diffs
- terminal commands
- approval prompts
- streamed reasoning and response chunks

ACP is an editor surface, not the primary product. Use it when forecast work naturally happens inside a repository or data workspace, such as source-adapter development, benchmark fixture review, model-script debugging, evidence extraction, or PR/release evidence analysis.

Durable forecast state still belongs in the forecast ledger. Editor chat, file diffs, and terminal output do not become scoreable evidence, model runs, forecast snapshots, resolutions, scores, postmortems, or calibration lessons unless an explicit forecast command or tool writes those records.

## What ACP Exposes

ACP runs with a curated `hermes-acp` toolset name for compatibility with the inherited runtime. The product-facing surface is Superforecasting Agent; the toolset identifier remains legacy.

The ACP toolset is designed for editor workflows and includes:

- file tools: `read_file`, `write_file`, `patch`, `search_files`
- terminal tools: `terminal`, `process`
- web and browser tools when configured
- skills
- memory/session recall for non-scoreable context
- `execute_code`
- `delegate_task`
- vision

ACP intentionally excludes features that do not fit editor UX, such as messaging delivery and cron management. Use the CLI, TUI, dashboard, gateway, or `forecast schedule` for standing forecast review and alerting.

## Installation

Install Superforecasting Agent normally, then add the ACP extra:

```bash
pip install -e '.[acp]'
```

or from the package:

```bash
pip install 'superforecasting-agent[acp]'
```

This installs the `agent-client-protocol` dependency and enables:

- `superforecasting-agent acp`
- `superforecasting-agent-acp` and `superforecast-acp` as fork-native direct scripts
- `hermes-acp` as the inherited compatibility script
- `python -m acp_adapter`

### Registry Compatibility

The current source registry manifest under `acp_registry/agent.json` still targets the inherited ACP Registry entry:

```bash
uvx --from 'hermes-agent[acp]==<version>' hermes-acp
```

That path is kept for compatibility with existing ACP registry clients and release tests. Fork-native manual setup should prefer:

```bash
superforecasting-agent acp
```

When a fork-native public ACP registry entry is published, it should point at `superforecasting-agent[acp]` while preserving a compatibility note for `hermes-acp`.

## Launching the ACP Server

Any of these starts the ACP server:

```bash
superforecasting-agent acp
```

```bash
superforecasting-agent-acp
```

```bash
superforecast-acp
```

```bash
hermes-acp
```

```bash
python -m acp_adapter
```

The adapter logs to stderr so stdout remains reserved for ACP JSON-RPC traffic.

For non-interactive checks:

```bash
superforecasting-agent acp --version
superforecasting-agent acp --check
```

### Browser Tools

Browser tools such as `browser_navigate` and `browser_click` depend on the `agent-browser` npm package and Chromium. They are optional for ACP.

Install them with:

```bash
superforecasting-agent acp --setup-browser
superforecasting-agent acp --setup-browser --yes
```

The Zed registry terminal-auth flow may still invoke the compatibility command `hermes acp --setup`. It offers the same browser bootstrap after provider/model setup.

What browser setup does:

- Installs Node.js 22 LTS into `~/.superforecasting-agent/node/` when missing.
- Installs `agent-browser` and `@askjo/camofox-browser` into that user-writable prefix.
- Installs Playwright Chromium, or uses a detected system Chrome/Chromium.

Legacy installs may use `~/.hermes/node/` during migration.

## Editor Setup

### VS Code

Install an ACP-compatible client, such as the [ACP Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) extension.

Manual settings example:

```json
{
  "acp.agents": {
    "Superforecasting Agent": {
      "command": "superforecasting-agent",
      "args": ["acp"]
    }
  }
}
```

If your editor only has the old built-in entry, select **Hermes Agent** as a compatibility entry and confirm it launches the same local runtime.

### Zed

Zed v0.221.x and newer installs external agents through the ACP Registry.

1. Open the Agent Panel.
2. Click **Add Agent**, or run `zed: acp registry`.
3. Search for the available Superforecasting Agent entry. If only **Hermes Agent** is available, that is the current compatibility registry entry.
4. Install it and start a new external-agent thread.

Prerequisites:

- Configure provider credentials with `superforecasting-agent model`, or set them in `~/.superforecasting-agent/.env` and `~/.superforecasting-agent/config.yaml`.
- Install `uv` if launching from the registry entry.

For local development, use a custom agent server:

```json
{
  "agent_servers": {
    "superforecasting-agent": {
      "type": "custom",
      "command": "superforecasting-agent",
      "args": ["acp"]
    }
  }
}
```

### JetBrains

Use an ACP-compatible plugin and point it at the local ACP adapter command:

```text
superforecasting-agent acp
```

If the plugin expects a registry directory, the inherited source copy currently lives at:

```text
acp_registry/
```

## Registry Manifest

The source copy of ACP Registry metadata lives at:

```text
acp_registry/agent.json
acp_registry/icon.svg
```

At the time of this fork pass, the manifest is still the inherited registry entry and uses:

```text
uvx --from 'hermes-agent[acp]==<version>' hermes-acp
```

That is a compatibility surface, not the desired long-term fork identity. The package-level fork already exposes `superforecasting-agent acp`; the registry manifest should move to `superforecasting-agent[acp]` when the public registry migration is ready and its tests are updated accordingly.

## Configuration and Credentials

ACP mode uses the same runtime configuration as the CLI:

- `~/.superforecasting-agent/.env`
- `~/.superforecasting-agent/config.yaml`
- `~/.superforecasting-agent/skills/`
- forecast ledger state under the active profile
- runtime session/log state under the active profile

Provider resolution uses the same model/provider resolver as the CLI, so ACP inherits configured providers, credentials, fallback settings, and auxiliary model settings. Registry clients can also trigger terminal setup, which runs the same interactive provider/model flow.

Legacy registry clients and migrated homes may still read `~/.hermes/.env`, `~/.hermes/config.yaml`, and `~/.hermes/skills/`.

## Session Behavior

ACP sessions are tracked by the adapter's in-memory session manager while the server is running.

Each session stores:

- session ID
- working directory
- selected model
- current conversation history
- cancel event

The underlying `AIAgent` still uses the shared runtime persistence and logging paths. ACP `list`, `load`, `resume`, and `fork` are scoped to the currently running ACP server process.

Conversation history is not forecast memory. To inspect or change durable forecast state from an editor, use `forecast show`, `forecast review`, `forecast evidence add`, `forecast update`, `forecast resolve`, `forecast score`, or the agent-facing forecast ledger tool.

## Working Directory Behavior

ACP sessions bind the editor's cwd to the task ID so file and terminal tools run relative to the editor workspace, not the server process cwd.

This is useful for:

- editing source adapters
- reviewing benchmark datasets
- maintaining forecast-analysis scripts
- inspecting repository events as evidence
- writing or testing forecast skills

## Approvals

Dangerous terminal commands can be routed back to the editor as approval prompts. ACP approval options are simpler than the CLI flow:

- allow once
- allow for session
- allow always
- deny

On timeout or error, the approval bridge denies the request.

### Session-Scoped Edit Auto-Approval

ACP exposes a middle tier between **allow once** and **allow always**: **Allow for session**.

| Option | Editor label | Scope | Persisted across restarts |
|--------|--------------|-------|---------------------------|
| `allow_once` | Allow once | This tool call | No |
| `allow_session` | Allow for session | Matching calls in this ACP session | No |
| `allow_always` | Allow always | Matching calls in future sessions | Yes |
| `deny` | Deny | This tool call | No |

For forecast work, start with `allow_once` for unfamiliar commands. Promote to `allow_session` after you have seen the same pattern run safely. Reserve `allow_always` for idempotent commands such as `git status` or read-only inspection.

The ACP bridge maps these options onto the runtime's internal approval semantics. `allow_always` writes a permanent allowlist entry, while `allow_session` only affects the current ACP session.

## Troubleshooting

### ACP Agent Does Not Appear in the Editor

Check:

- In Zed, open the ACP Registry with `zed: acp registry`.
- For manual/local development, verify the custom command points to `superforecasting-agent acp`.
- Superforecasting Agent is installed and on your `PATH`.
- The ACP extra is installed with `pip install -e '.[acp]'` or `pip install 'superforecasting-agent[acp]'`.
- `uv` is installed if launching from a registry entry.

### ACP Starts but Immediately Errors

Try:

```bash
superforecasting-agent acp --version
superforecasting-agent acp --check
superforecasting-agent doctor
superforecasting-agent status
```

If the editor launched the compatibility registry entry, also check:

```bash
hermes-acp --version
```

### Missing Credentials

ACP mode uses the existing provider setup. Configure credentials with:

```bash
superforecasting-agent model
```

or by editing `~/.superforecasting-agent/.env`. Registry clients can also trigger terminal setup, which runs the same provider/model flow.

### Zed Registry Launcher Cannot Find `uv`

Install `uv` from the official uv installation docs, then retry the external-agent thread.

## See Also

- [ACP Internals](../../developer-guide/acp-internals.md)
- [Provider Runtime Resolution](../../developer-guide/provider-runtime.md)
- [Tools Runtime](../../developer-guide/tools-runtime.md)
