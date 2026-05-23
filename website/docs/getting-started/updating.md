---
sidebar_position: 3
title: "Updating & Uninstalling"
description: "How to update or uninstall Superforecasting Agent."
---

# Updating & Uninstalling

## Updating

### Git installs

Update to the latest version with a single command:

```bash
superforecasting-agent update
```

This pulls the latest code from `main`, updates dependencies, and prompts you to configure any new options that were added since your last update.

### pip installs

PyPI releases track **tagged versions** (major and minor releases), not every commit on `main`. Check for updates and upgrade with:

```bash
superforecasting-agent update --check    # see if a newer release is on PyPI
superforecasting-agent update            # runs pip install --upgrade superforecasting-agent
```

Or manually:

```bash
pip install --upgrade superforecasting-agent    # or: uv pip install --upgrade superforecasting-agent
```

:::tip
`superforecasting-agent update` automatically detects new configuration options and prompts you to add them. If you skipped that prompt, you can manually run `superforecasting-agent config check` to see missing options, then `superforecasting-agent config migrate` to interactively add them.
:::

### What happens during an update (git installs)

When you run `superforecasting-agent update`, the following steps occur:

1. **Pairing-data snapshot** — a lightweight pre-update state snapshot is saved (covers `~/.superforecasting-agent/pairing/`, Feishu comment rules, and other state files that get modified at runtime). Recoverable via the snapshot restore flow described under [Snapshots and rollback](../user-guide/checkpoints-and-rollback.md), or by extracting the most recent quick-snapshot zip written next to your home directory. Existing legacy homes may still use `~/.hermes/pairing/` during migration.
2. **Git pull** — pulls the latest code from the `main` branch and updates submodules
3. **Dependency install** — runs `uv pip install -e ".[all]"` to pick up new or changed dependencies
4. **Config migration** — detects new config options added since your version and prompts you to set them
5. **Gateway auto-restart** — running gateways are refreshed after the update completes so the new code takes effect immediately. Service-managed gateways (systemd on Linux, launchd on macOS) are restarted through the service manager. Manual gateways are relaunched automatically when the updater can map the running PID back to a profile.

### Preview-only: `superforecasting-agent update --check`

Want to know if an update is available before pulling? Run `superforecasting-agent update --check` — for git installs it fetches and compares commits against `origin/main`; for pip installs it queries PyPI for the latest release. No files are modified, no gateway is restarted. Useful in scripts and cron jobs that gate on "is there an update".

### Full pre-update backup: `--backup`

For high-value profiles (production gateways, shared team installs) you can opt into a full pre-pull backup of the forecast home directory: `SUPERFORECASTING_AGENT_HOME`, `FORECAST_HOME`, or the legacy `HERMES_HOME` compatibility alias.

```bash
superforecasting-agent update --backup
```

Or make it the default for every run:

```yaml
# ~/.superforecasting-agent/config.yaml
updates:
  pre_update_backup: true
```

`--backup` was the always-on behavior in earlier builds, but it was adding minutes to every update on large homes, so it's now opt-in. The lightweight pairing-data snapshot above still runs unconditionally.

### Windows: another CLI executable is running

On Windows, `superforecasting-agent update` will refuse to run if it detects another generated CLI executable holding the venv's entry-point executable open. This most commonly means an open `superforecasting-agent`, `forecast`, or legacy `hermes` REPL in another terminal, a running dashboard backend, or a running gateway:

```
$ superforecasting-agent update
X Another Superforecasting Agent executable is running:
    PID 12345  superforecasting-agent.exe

  Updating now may fail to overwrite entry-point shims in ...\venv\Scripts
  because Windows blocks REPLACE on a running executable.

  Close any open Superforecasting Agent REPLs and
  stop the gateway (`superforecasting-agent gateway stop`) before retrying.
  Override with `superforecasting-agent update --force` if you've already
  confirmed those processes will not write to the venv.
```

Close the listed processes and re-run. If you're sure the concurrent process won't interfere (rare — usually only useful when an antivirus shim is mis-attributed), pass `--force` to skip the check. In that case the updater will still retry the `.exe` rename with exponential backoff and, on stubborn locks, schedule the replacement for next reboot via `MoveFileEx(MOVEFILE_DELAY_UNTIL_REBOOT)` so the update can complete.

Expected output looks like:

```
$ superforecasting-agent update
Updating Superforecasting Agent...
Pulling latest code...
Already up to date.  (or: Updating abc1234..def5678)
Updating dependencies...
Dependencies updated
Checking for new config options...
Config is up to date  (or: Found 2 new options - running migration...)
Restarting gateways...
Gateway restarted
Superforecasting Agent updated successfully!
```

### Recommended Post-Update Validation

`superforecasting-agent update` handles the main update path, but a quick validation confirms everything landed cleanly:

1. `git status --short` — if the tree is unexpectedly dirty, inspect before continuing
2. `superforecasting-agent doctor` — checks config, dependencies, and service health
3. `superforecasting-agent --version` — confirm the version bumped as expected
4. If you use the gateway: `superforecasting-agent gateway status`
5. If `doctor` reports npm audit issues: run `npm audit fix` in the flagged directory

:::warning Dirty working tree after update
If `git status --short` shows unexpected changes after `superforecasting-agent update`, stop and inspect them before continuing. This usually means local modifications were reapplied on top of the updated code, or a dependency step refreshed lockfiles.
:::

### If your terminal disconnects mid-update

`superforecasting-agent update` protects itself against accidental terminal loss:

- The update ignores `SIGHUP`, so closing your SSH session or terminal window no longer kills it mid-install. `pip` and `git` child processes inherit this protection, so the Python environment cannot be left half-installed by a dropped connection.
- All output is mirrored to `~/.superforecasting-agent/logs/update.log` while the update runs. Existing legacy homes may still write `~/.hermes/logs/update.log`. If your terminal disappears, reconnect and inspect the log to see whether the update finished and whether the gateway restart succeeded:

```bash
tail -f ~/.superforecasting-agent/logs/update.log
```

- `Ctrl-C` (SIGINT) and system shutdown (SIGTERM) are still honored — those are deliberate cancellations, not accidents.

You no longer need to wrap `superforecasting-agent update` in `screen` or `tmux` to survive a terminal drop.

### Checking your current version

```bash
superforecasting-agent version
```

Compare against the latest release on this fork's GitHub releases page.

### Updating from Messaging Platforms

You can also update directly from Telegram, Discord, Slack, WhatsApp, or Teams by sending:

```
/update
```

This pulls the latest code, updates dependencies, and restarts running gateways. The bot will briefly go offline during the restart (typically 5–15 seconds) and then resume.

### Manual Update

If you installed manually (not via the quick installer):

```bash
cd /path/to/superforecasting-agent
export VIRTUAL_ENV="$(pwd)/venv"

# Pull latest code
git pull origin main

# Reinstall (picks up new dependencies)
uv pip install -e ".[all]"

# Check for new config options
superforecasting-agent config check
superforecasting-agent config migrate   # Interactively add any missing options
```

### Rollback instructions

If an update introduces a problem, you can roll back to a previous version:

```bash
cd /path/to/superforecasting-agent

# List recent versions
git log --oneline -10

# Roll back to a specific commit
git checkout <commit-hash>
git submodule update --init --recursive
uv pip install -e ".[all]"

# Restart the gateway if running
superforecasting-agent gateway restart
```

To roll back to a specific release tag:

```bash
git checkout v0.6.0
git submodule update --init --recursive
uv pip install -e ".[all]"
```

:::warning
Rolling back may cause config incompatibilities if new options were added. Run `superforecasting-agent config check` after rolling back and remove any unrecognized options from `config.yaml` if you encounter errors.
:::

### Note for Nix users

If you installed via Nix flake, updates are managed through the Nix package manager:

```bash
# Update the flake input
nix flake update superforecasting-agent

# Or rebuild with the latest
nix profile upgrade superforecasting-agent
```

If your flake input or profile package is still named `hermes-agent` for compatibility, use that name in the same commands.

Nix installations are immutable — rollback is handled by Nix's generation system:

```bash
nix profile rollback
```

See [Nix Setup](./nix-setup.md) for more details.

---

## Uninstalling

### Git installs

```bash
superforecasting-agent uninstall
```

The uninstaller gives you the option to keep your configuration files (`~/.superforecasting-agent/`) for a future reinstall. Legacy `~/.hermes/` homes are kept unless you explicitly remove them.

### pip installs

```bash
pip uninstall superforecasting-agent
rm -rf ~/.superforecasting-agent            # Optional - keep if you plan to reinstall
```

### Manual Uninstall

```bash
rm -f ~/.local/bin/forecast ~/.local/bin/superforecast ~/.local/bin/superforecasting-agent
rm -rf /path/to/superforecasting-agent
rm -rf ~/.superforecasting-agent            # Optional - keep if you plan to reinstall
```

:::info
If you installed the gateway as a system service, stop and disable it first:
```bash
superforecasting-agent gateway stop
# Linux: systemctl --user disable hermes-gateway
# macOS: launchctl remove ai.hermes.gateway
```
:::
