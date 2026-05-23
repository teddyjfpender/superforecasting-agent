---
sidebar_position: 2
---

# Profiles: Forecast Workspaces

Run multiple independent Superforecasting Agent profiles on the same machine. Each profile has its own config, provider keys, forecast ledger, memory files, sessions, skills, cron jobs, logs, and gateway state.

Use profiles when you want separate forecasting workspaces: for example `macro`, `elections`, `markets`, `biosecurity`, or `client-a`. Keeping those ledgers separate makes calibration, domain error profiles, scheduled self-checks, and source credentials easier to audit.

## What Profiles Are

A profile is a separate agent home directory. New installs use:

```text
~/.superforecasting-agent/profiles/<name>/
```

Existing legacy profiles under `~/.hermes/profiles/<name>/` remain supported during the fork transition. Internally, inherited modules still receive a bridged `HERMES_HOME`, but new docs and commands should prefer `superforecasting-agent`, `forecast`, `SUPERFORECASTING_AGENT_HOME`, and `~/.superforecasting-agent`.

Each profile owns:

- `config.yaml` - model, provider, toolsets, terminal, cron, and gateway settings.
- `.env` - API keys and messaging tokens.
- `SOUL.md` - profile-specific instructions.
- `forecasting/forecasting.db` - the scoreable forecast ledger.
- `forecasting/evidence_snapshots/` and `forecasting/resolution_snapshots/` - audit snapshots.
- `memories/` - ordinary memory files; forecast learning should still be provenance-linked to the ledger.
- `sessions/`, `skills/`, `cron/`, `logs/`, and gateway state.

When you create a profile, the CLI can also create a shell alias with the same name. A profile called `macro` can run `macro forecast status`, `macro model`, `macro gateway start`, and other commands.

## Quick Start

```bash
superforecasting-agent profile create macro \
  --description "Macroeconomic forecasts using FRED, BLS, World Bank, market priors, and horizon-aware calibration."

macro model
macro forecast status
macro forecast new "Will US CPI year-over-year be below 3.0% in December 2026?" \
  --criteria "Resolved from the BLS CPI-U 12-month percentage change for December 2026." \
  --close-time 2026-12-31T23:59:59Z \
  --resolution-time 2027-01-15T23:59:59Z
```

`macro` is now a separate forecast desk with its own ledger, calibration history, scheduled reviews, and provider settings.

## Creating Profiles

### Blank profile

```bash
superforecasting-agent profile create markets
```

Creates a fresh profile with bundled skills seeded. Run `markets setup` or `markets model` to configure provider keys, models, tools, and gateway tokens.

For forecast routing and kanban decomposition, pass a role description when creating the profile:

```bash
superforecasting-agent profile create policy \
  --description "Tracks legislation, regulatory filings, public statements, and policy-resolution criteria."
```

You can also set or auto-generate the description later with:

```bash
superforecasting-agent profile describe policy --text "Policy and legislative forecasts."
superforecasting-agent profile describe policy --auto
```

See the [Kanban guide](./features/kanban#auto-vs-manual-orchestration) for the routing model.

### Empty profile without bundled skills

```bash
superforecasting-agent profile create narrow-risk --no-skills
```

Use this for tightly scoped worker profiles where you want minimal skill surface area. The profile writes a `.no-bundled-skills` marker so `superforecasting-agent update` does not re-seed bundled skills later.

### Clone config and identity (`--clone`)

```bash
superforecasting-agent profile create elections --clone
```

Copies the current profile's `config.yaml`, `.env`, `SOUL.md`, and curated `MEMORY.md` / `USER.md` files. It does not copy the full session history or runtime state, so the new profile starts with fresh sessions and a fresh forecast ledger unless you explicitly copy ledger data yourself.

Edit profile-specific files under:

```text
~/.superforecasting-agent/profiles/elections/.env
~/.superforecasting-agent/profiles/elections/SOUL.md
```

Legacy installations may use the same layout under `~/.hermes/profiles/elections/`.

### Clone everything (`--clone-all`)

```bash
superforecasting-agent profile create backup --clone-all
```

Copies config, API keys, profile instructions, memory, sessions, skills, cron jobs, plugins, and most state from the source profile. Use this for backups or forking an already-trained forecast workspace. Runtime process files such as gateway PIDs are stripped.

### Clone from a specific profile

```bash
superforecasting-agent profile create policy-copy --clone --clone-from policy
```

:::tip Honcho memory + profiles
When Honcho is enabled, `--clone` creates a dedicated AI peer for the new profile while sharing the same user workspace. Each profile builds its own observations and identity. See [Honcho -- Multi-agent / Profiles](./features/memory-providers.md#honcho) for details.
:::

## Using Profiles

### Command aliases

Every profile can get a command alias at `~/.local/bin/<name>`:

```bash
macro                         # open the macro forecast desk
macro forecast status          # show macro ledger status
macro forecast review --last 30d
macro model                    # configure macro's model/provider
macro gateway start            # start macro's gateway
macro config set model.default anthropic/claude-sonnet-4-6
```

The wrapper prefers `superforecasting-agent -p <name>` and falls back to the legacy `hermes -p <name>` command only for compatibility.

### The `-p` flag

Target a profile explicitly from the main command:

```bash
superforecasting-agent -p macro forecast status
superforecasting-agent --profile=policy doctor
superforecasting-agent forecast review -p markets --last 14d
```

### Sticky default

```bash
superforecasting-agent profile use macro
superforecasting-agent forecast status    # now targets macro
superforecasting-agent tools              # configures macro's tools
superforecasting-agent profile use default
```

This is like `kubectl config use-context`: plain commands target the sticky profile until you switch back.

### Knowing where you are

The CLI shows the active profile in high-attention surfaces:

- Prompt: profile-aware prompt labels.
- Banner/status: active profile name, path, model, and gateway status.
- `superforecasting-agent profile`: current profile status.

For ledger-specific confirmation, run:

```bash
forecast status
superforecasting-agent -p macro forecast status
```

The status output includes the active ledger path.

## Profiles vs Ledgers, Sessions, and Memory

Profiles isolate whole agent homes. Inside a profile:

- The forecast ledger stores scoreable questions, snapshots, evidence, assumptions, model runs, resolutions, scores, postmortems, calibration lessons, watched sources, and scheduled self-check state.
- Sessions store conversation continuity only. They are not the durable learning substrate.
- Generic memory files can store useful preferences or lessons, but forecast-relevant learning should cite ledger artifacts.

If you want one shared calibration history across domains, use one profile and tag forecasts by `--domain` / `--topic`. If you want separate calibration histories, secrets, cron jobs, and gateway state, use separate profiles.

## Profiles vs Workspaces vs Sandboxing

Profiles are often confused with workspaces or sandboxes, but they are different things:

- A profile gives Superforecasting Agent its own state directory.
- A workspace or working directory is where terminal commands start. That is controlled by `terminal.cwd`.
- A sandbox limits filesystem access. Profiles do not sandbox the agent.

On the default `local` terminal backend, the agent still has the same filesystem access as your user account. A profile does not stop it from accessing folders outside the profile directory.

Set an explicit working directory if a profile should run tools in a specific project:

```bash
macro config set terminal.cwd /absolute/path/to/research-workspace
```

Equivalent YAML:

```yaml
terminal:
  backend: local
  cwd: /absolute/path/to/research-workspace
```

Using `cwd: "."` on the local backend means "the directory the command was launched from", not "the profile directory".

Also note:

- `SOUL.md` can guide the model, but it does not enforce workspace boundaries.
- Changes to `SOUL.md` take effect cleanly in new sessions. Existing sessions may still use old prompt state.
- Asking the model which directory it is in is not a reliable isolation test. If tool start location matters, set `terminal.cwd`.

## Running Gateways

Each profile can run its own gateway process and bot token:

```bash
macro gateway start
policy gateway start
```

### Different bot tokens

Each profile has its own `.env`. Configure separate Telegram, Discord, Slack, WhatsApp, or Signal tokens per profile:

```bash
nano ~/.superforecasting-agent/profiles/macro/.env
nano ~/.superforecasting-agent/profiles/policy/.env
```

Legacy profile homes under `~/.hermes/profiles/<name>/.env` still work.

### Safety: token locks

If two profiles accidentally use the same bot token, the second gateway is blocked with a clear error naming the conflicting profile. This is supported for Telegram, Discord, Slack, WhatsApp, and Signal.

### Persistent services

```bash
macro gateway install
policy gateway install
```

Each profile gets its own service name and runs independently. Some systemd/launchd names still include inherited `hermes-gateway-<profile>` identifiers for compatibility with existing services.

## Configuring Profiles

Each profile has its own:

- `config.yaml` - model, provider, toolsets, terminal, cron, and gateway settings.
- `.env` - API keys and bot tokens.
- `SOUL.md` - profile role and instructions.

```bash
macro config set model.provider anthropic
macro config set model.default claude-sonnet-4-6
macro config set terminal.cwd /absolute/path/to/macro-research
```

For profile identity, keep the instructions forecasting-specific:

```bash
nano ~/.superforecasting-agent/profiles/macro/SOUL.md
```

A useful profile instruction says what evidence the profile should prioritize, how it should treat stale data, and what domain-specific errors it should watch for. It should not replace the forecast ledger's scoring and postmortem loop.

## Updating

`superforecasting-agent update` pulls code once and syncs new bundled skills to all profiles automatically:

```bash
superforecasting-agent update
# Code updated
# Skills synced: default (up to date), macro (+2 new), policy (+1 new)
```

User-modified skills are not overwritten. Profiles created with `--no-skills` are skipped during bundled skill sync.

## Managing Profiles

```bash
superforecasting-agent profile list
superforecasting-agent profile show macro
superforecasting-agent profile rename macro macro-research
superforecasting-agent profile export macro
superforecasting-agent profile import macro.tar.gz
```

## Deleting a Profile

```bash
superforecasting-agent profile delete macro
```

This stops the gateway, removes the systemd/launchd service, removes the command alias, and deletes all profile data. You will be asked to type the profile name to confirm.

Use `--yes` to skip confirmation:

```bash
superforecasting-agent profile delete macro --yes
```

:::note
You cannot delete the default profile (`~/.superforecasting-agent`, or a reused legacy `~/.hermes` home). To remove everything, use `superforecasting-agent uninstall`.
:::

## Tab Completion

```bash
# Bash
eval "$(superforecasting-agent completion bash)"

# Zsh
eval "$(superforecasting-agent completion zsh)"
```

Add the line to your `~/.bashrc` or `~/.zshrc` for persistent completion. Completion includes profile names after `-p`, profile subcommands, and top-level commands.

## How It Works

New default profiles live under `~/.superforecasting-agent`. Existing `~/.hermes` installs are detected and reused during compatibility. Named profiles live under `<agent-home>/profiles/<name>/`.

When you run a profile alias such as `macro forecast status`, the wrapper executes:

```bash
superforecasting-agent -p macro forecast status
```

The startup path resolves the profile directory and sets the inherited internal home variable so modules that still call `get_hermes_home()` read and write inside the profile. Forecast-native env vars are preferred:

- `SUPERFORECASTING_AGENT_HOME`
- `FORECAST_HOME`
- `HERMES_HOME` as legacy compatibility

This is separate from terminal working directory. Tool execution starts from `terminal.cwd`, or from the command launch directory when `cwd: "."` on the local backend.

The default profile is the root agent home itself:

```text
~/.superforecasting-agent/
```

or, for existing installs:

```text
~/.hermes/
```

No migration is required for legacy homes, but new examples should use the fork-native path.

## Sharing Profiles as Distributions

A profile can be packaged as a git repository and installed on another machine. The package can include SOUL instructions, config, skills, cron jobs, and MCP connections. Credentials, memories, sessions, and forecast ledgers should remain per-machine unless you explicitly export them.

```bash
# Install a whole forecast profile from a git repo
superforecasting-agent profile install github.com/you/macro-forecast-desk --alias

# Update later when the author ships a new version
superforecasting-agent profile update macro-forecast-desk
```

See **[Profile Distributions: Share a Forecast Desk](./profile-distributions.md)** for authoring, publishing, update semantics, security model, and examples.
