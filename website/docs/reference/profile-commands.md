---
sidebar_position: 7
---

# Profile Commands Reference

This page covers commands for Superforecasting Agent [profiles](../user-guide/profiles.md). Profiles are separate forecast workspaces with their own config, provider keys, forecast ledger, memory files, sessions, skills, cron jobs, logs, and gateway state.

The primary command is `superforecasting-agent profile`. The legacy `hermes profile` command remains available for inherited runtime compatibility, but new examples should use `superforecasting-agent`.

## `superforecasting-agent profile`

```bash
superforecasting-agent profile <subcommand>
```

Running `superforecasting-agent profile` without a subcommand shows the current profile, path, model, gateway status, and profile help.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use` | Set the sticky default profile. |
| `create` | Create a new profile. |
| `describe` | Read, set, or auto-generate a routing description. |
| `delete` | Delete a profile. |
| `show` | Show profile details. |
| `alias` | Create, update, remove, or rename the shell alias wrapper. |
| `rename` | Rename a profile. |
| `export` | Export a profile to a tar.gz archive. |
| `import` | Import a profile from a tar.gz archive. |
| `install` | Install a profile distribution from a git URL or local directory. |
| `update` | Re-pull and re-apply a distribution-managed profile. |
| `info` | Show distribution metadata for a profile. |

## `profile list`

```bash
superforecasting-agent profile list
```

Lists all profiles. The active profile is marked with `*`.

Example:

```bash
$ superforecasting-agent profile list
  default
* macro
  policy
  markets
```

## `profile use`

```bash
superforecasting-agent profile use <name>
```

Sets `<name>` as the sticky default for `superforecasting-agent` commands. For forecast workflows, prefer `superforecasting-agent forecast ...`, a profile alias such as `macro forecast status`, or `superforecasting-agent -p <name> forecast ...` when profile targeting matters.

| Argument | Description |
|----------|-------------|
| `<name>` | Profile to activate. Use `default` to return to the root profile. |

Examples:

```bash
superforecasting-agent profile use macro
superforecasting-agent forecast status

superforecasting-agent profile use default
```

## `profile create`

```bash
superforecasting-agent profile create <name> [options]
```

Creates a new profile under `~/.superforecasting-agent/profiles/<name>/` for new installs, or under the active legacy root when an existing `~/.hermes` home is reused.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile name. Must be lowercase alphanumeric with optional hyphens or underscores. |
| `--clone` | Copy `config.yaml`, `.env`, `SOUL.md`, and curated `MEMORY.md` / `USER.md` files from the source profile. |
| `--clone-all` | Copy most profile state from the source profile, including sessions, skills, cron jobs, plugins, and ledger state. Runtime process files are stripped. |
| `--clone-from <profile>` | Clone from a specific profile instead of the active one. Used with `--clone` or `--clone-all`. |
| `--no-alias` | Skip wrapper script creation. |
| `--description "<text>"` | One- or two-sentence description used by kanban/decomposition routing. Can be set later with `profile describe`. |
| `--no-skills` | Create an empty profile with no bundled skills and write `.no-bundled-skills` so `superforecasting-agent update` does not re-seed them. Cannot be combined with `--clone` or `--clone-all`. |

Creating a profile does not make that profile directory the default terminal workspace. Set `terminal.cwd` in that profile when tools should start in a specific project or research directory.

Examples:

```bash
# Blank forecast workspace
superforecasting-agent profile create macro

# Profile with a routing description
superforecasting-agent profile create policy \
  --description "Policy forecasts, legislative sources, regulator statements, and resolution criteria."

# Clone config and identity from the active profile
superforecasting-agent profile create elections --clone

# Clone most state from a specific profile
superforecasting-agent profile create macro-backup --clone-all --clone-from macro

# Minimal worker profile
superforecasting-agent profile create narrow-risk --no-skills
```

## `profile describe`

```bash
superforecasting-agent profile describe [<name>] [options]
```

Reads or sets a profile's description. The description is stored in `<profile_dir>/profile.yaml` and used by kanban orchestration to route work based on capability instead of name alone.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to describe. Required unless `--all --auto` is used. |
| `--text "<text>"` | Set the description exactly. Marks it as user-authored. |
| `--auto` | Ask the auxiliary LLM to generate a 1-2 sentence description from the profile name, model, and installed skills. Uses `auxiliary.profile_describer`. |
| `--overwrite` | With `--auto`, replace user-authored descriptions too. Default behavior skips explicit user descriptions. |
| `--all` | With `--auto`, sweep every profile missing a description. |

Examples:

```bash
superforecasting-agent profile describe macro
superforecasting-agent profile describe macro --text "Macroeconomic forecasts using FRED, BLS, World Bank, and horizon-aware calibration."
superforecasting-agent profile describe macro --auto
superforecasting-agent profile describe --all --auto
```

## `profile show`

```bash
superforecasting-agent profile show <name>
```

Shows the profile's home directory, model, provider, gateway status, skill count, env/config status, alias path, and distribution metadata when present.

This shows the profile home, not the terminal working directory. Forecast ledger data normally lives at:

```text
<profile-home>/forecasting/forecasting.db
```

Example:

```bash
$ superforecasting-agent profile show macro
Profile: macro
Path:    ~/.superforecasting-agent/profiles/macro
Model:   claude-sonnet-4-6 (anthropic)
Gateway: stopped
Skills:  12
.env:    exists
SOUL.md: exists
Alias:   ~/.local/bin/macro
```

## `profile delete`

```bash
superforecasting-agent profile delete <name> [options]
```

Deletes a profile and removes its wrapper alias.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to delete. |
| `--yes`, `-y` | Skip confirmation. |

Examples:

```bash
superforecasting-agent profile delete macro
superforecasting-agent profile delete macro --yes
```

:::warning
This permanently deletes the profile directory, including config, secrets, sessions, ordinary memory, skills, forecast ledger, evidence snapshots, scores, postmortems, and scheduled self-check state. You cannot delete the currently active profile.
:::

## `profile alias`

```bash
superforecasting-agent profile alias <name> [options]
```

Creates, updates, removes, or renames the wrapper script at `~/.local/bin/<alias>`.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to create or update the alias for. |
| `--remove` | Remove the wrapper script instead of creating it. |
| `--name <alias>` | Custom alias name. Defaults to the profile name. |

The generated wrapper prefers `superforecasting-agent -p <name>` and falls back to `hermes -p <name>` only when the fork-native command is unavailable.

Examples:

```bash
superforecasting-agent profile alias macro
superforecasting-agent profile alias macro --name macro-desk
superforecasting-agent profile alias macro --remove
```

## `profile rename`

```bash
superforecasting-agent profile rename <old-name> <new-name>
```

Renames a profile, updates its directory, and updates wrapper aliases.

| Argument | Description |
|----------|-------------|
| `<old-name>` | Current profile name. |
| `<new-name>` | New profile name. |

Example:

```bash
superforecasting-agent profile rename macro macro-research
# ~/.superforecasting-agent/profiles/macro -> ~/.superforecasting-agent/profiles/macro-research
# ~/.local/bin/macro -> ~/.local/bin/macro-research
```

## `profile export`

```bash
superforecasting-agent profile export <name> [options]
```

Exports a profile as a compressed tar.gz archive. Use export/import for local backup and restore. Distribution commands are for shareable, versioned git-backed profile packages.

| Argument / Option | Description |
|-------------------|-------------|
| `<name>` | Profile to export. |
| `-o`, `--output <path>` | Output path. Defaults to `<name>.tar.gz`. |

Examples:

```bash
superforecasting-agent profile export macro
superforecasting-agent profile export macro -o ./macro-2026-03-29.tar.gz
```

## `profile import`

```bash
superforecasting-agent profile import <archive> [options]
```

Imports a profile from a tar.gz archive.

| Argument / Option | Description |
|-------------------|-------------|
| `<archive>` | Path to the tar.gz archive. |
| `--name <name>` | Name for the imported profile. Defaults to a name inferred from the archive. |

Examples:

```bash
superforecasting-agent profile import ./macro-2026-03-29.tar.gz
superforecasting-agent profile import ./macro-2026-03-29.tar.gz --name macro-restored
```

## Distribution Commands

:::tip
New to distributions? Start with the [Profile Distributions user guide](../user-guide/profile-distributions.md). It covers authoring, publishing, update semantics, and the security model.
:::

A distribution turns a profile into a shareable git-backed artifact. It can ship SOUL instructions, config, skills, cron jobs, MCP connections, and profile metadata. Recipient-owned data such as `.env`, auth, memories, sessions, and forecast ledgers stays local unless the user explicitly exports or copies it.

`profile export` / `profile import` are still the right commands for local backup and restore. `profile install` / `profile update` / `profile info` are for versioned profile distributions.

### `profile install`

```bash
superforecasting-agent profile install <source> [--name <name>] [--alias] [--force] [--yes]
```

Installs a profile distribution from a git URL or a local directory containing `distribution.yaml`.

| Option | Description |
|--------|-------------|
| `<source>` | Git URL (`github.com/user/repo`, `https://...`, `git@...`, `ssh://`, `git://`) or local directory. |
| `--name NAME` | Override the profile name from the manifest. |
| `--alias` | Also create a shell wrapper, for example `macro-desk -> superforecasting-agent -p macro-desk`. |
| `--force` | Overwrite an existing profile of the same name while preserving user data. |
| `-y`, `--yes` | Skip manifest-preview confirmation. |

Examples:

```bash
superforecasting-agent profile install github.com/you/macro-forecast-desk --alias
superforecasting-agent profile install https://github.com/you/macro-forecast-desk.git
superforecasting-agent profile install git@github.com:your-org/internal-policy-desk.git
superforecasting-agent profile install ./local-profile-distribution/
```

### `profile update`

```bash
superforecasting-agent profile update <name> [--force-config] [--yes]
```

Re-clones the distribution from its recorded source and applies updates. Distribution-owned files are overwritten. User data is preserved.

| Option | Description |
|--------|-------------|
| `<name>` | Distribution-managed profile to update. |
| `--force-config` | Also overwrite `config.yaml`. By default it is preserved to keep local overrides. |
| `-y`, `--yes` | Skip confirmation. |

### `profile info`

```bash
superforecasting-agent profile info <name>
```

Prints distribution manifest metadata: name, version, required runtime spec, author, env var requirements, source URL/path, and install/update timestamp.

`superforecasting-agent profile list` also shows distribution name and version. `superforecasting-agent profile show <name>` and `delete <name>` surface distribution source details when present.

### Private distributions

Private repositories work with the normal `git` authentication available in your shell:

```bash
superforecasting-agent profile install git@github.com:your-org/internal-policy-desk.git
superforecasting-agent profile install https://github.com/your-org/internal-policy-desk.git
```

Set up `git clone` authentication first; the installer shells out to your normal `git` binary.

### Distribution manifest

Every distribution has a `distribution.yaml` at repository root:

```yaml
name: macro-forecast-desk
version: 0.1.0
description: "Macro forecast desk with FRED/BLS/World Bank workflows"
hermes_requires: ">=0.12.0"
author: "Your Name"
license: "MIT"
env_requires:
  - name: OPENAI_API_KEY
    description: "OpenAI API key"
    required: true
  - name: FRED_API_KEY
    description: "FRED data API key"
    required: false
distribution_owned:
  - SOUL.md
  - skills/macro/
  - cron/
```

The manifest field is still named `hermes_requires` for compatibility with the inherited distribution loader. The user-facing error text refers to the Superforecasting Agent runtime. `distribution_owned` is optional; when omitted, sensible defaults apply.

### Publishing a distribution

1. In the profile directory, create `distribution.yaml` with at least `name` and `version`.
2. Commit distribution-owned files to a git repository.
3. Tell recipients to run `superforecasting-agent profile install <repo-url>`.

Use git tags and manifest version bumps for release tracking.

## `-p` / `--profile`

```bash
superforecasting-agent -p <name> <command> [options]
superforecasting-agent --profile <name> <command> [options]
```

Runs any command under a specific profile without changing the sticky default.

| Option | Description |
|--------|-------------|
| `-p <name>`, `--profile <name>` | Profile to use for this command. |

Examples:

```bash
superforecasting-agent -p macro forecast status
superforecasting-agent --profile policy gateway start
superforecasting-agent forecast review -p markets --last 30d
superforecasting-agent -p macro config edit
```

## `completion`

```bash
superforecasting-agent completion <shell>
```

Generates shell completion scripts. Completion includes profile names and profile subcommands.

| Argument | Description |
|----------|-------------|
| `<shell>` | Shell to generate completions for: `bash`, `zsh`, or `fish`. |

Examples:

```bash
superforecasting-agent completion bash >> ~/.bashrc
superforecasting-agent completion zsh >> ~/.zshrc
superforecasting-agent completion fish > ~/.config/fish/completions/superforecasting-agent.fish
```

After installation, tab completion works for:

- `superforecasting-agent profile <TAB>` - subcommands.
- `superforecasting-agent profile use <TAB>` - profile names.
- `superforecasting-agent -p <TAB>` - profile names.

## See Also

- [Profiles User Guide](../user-guide/profiles.md)
- [CLI Commands Reference](./cli-commands.md)
- [FAQ - Profiles section](./faq.md#profiles)
