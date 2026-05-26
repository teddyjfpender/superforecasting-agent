---
sidebar_position: 2
title: "Installation"
description: "Install Superforecasting Agent from this fork."
---

# Installation

This fork is in transition from Hermes Agent to Superforecasting Agent. The recommended install path is from the fork checkout so the forecast-native CLI, ledger, TUI shortcuts, docs, and package metadata are all present together.

## Recommended: Install From The Fork

```bash
git clone --branch superforecasting-agent-snapshot \
  https://github.com/teddyjfpender/superforecasting-agent.git \
  superforecasting-agent
cd superforecasting-agent
uv venv .venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

Open the forecast desk:

```bash
forecast status
forecast
superforecasting-agent
```

The legacy `hermes` command remains available for inherited runtime compatibility, but new workflow examples should prefer `forecast` for the desk and `superforecasting-agent` for the fork-native runtime command.

## Minimal Python Install

If you do not need optional browser, dashboard, voice, or messaging dependencies:

```bash
git clone --branch superforecasting-agent-snapshot \
  https://github.com/teddyjfpender/superforecasting-agent.git \
  superforecasting-agent
cd superforecasting-agent
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
```

Run a smoke check:

```bash
python -m superforecasting_agent status --json
python3 scripts/forecast_smoke_test.py
```

## Configure A Model Provider

Use the fork-native setup commands:

```bash
superforecasting-agent setup
superforecasting-agent model
superforecasting-agent tools
```

Provider secrets belong in the agent `.env`; non-secret settings belong in `config.yaml`. New installs default to `~/.superforecasting-agent`, while existing `~/.hermes` homes are reused during the compatibility transition.

## Verify The Forecast Desk

```bash
forecast new "Will this smoke test resolve yes?" \
  --resolution-criteria "Manual local test question."

forecast list
forecast status
forecast calibration --all
```

For a full lifecycle example, continue to the [Quickstart](./quickstart.md). For a repeatable tester handoff check, use the [Tester Smoke Test](./forecast-smoke-test.md).

## TUI

```bash
superforecasting-agent tui
```

Useful shortcuts:

```text
/forecast
/new-forecast
/base-rate
/update-forecast
/resolve
/score
/postmortem
/review
/alerts
/calibration
/lessons
/backtest
/schedule
/performance
```

## Developer Verification

Use the repo's test runner:

```bash
scripts/run_tests.sh tests/forecasting tests/test_project_metadata.py -q
```

For frontend surfaces:

```bash
cd ui-tui
npm install
npm run build

cd ../web
npm install
npm run build

cd ../website
npm install
npm run build
```

The website build should complete without broken-link or broken-anchor warnings.
Treat any new docs-link warning as a regression to fix before handoff.

## Platform Notes

### Linux, macOS, and WSL2

Use the fork checkout install above. WSL2 remains the safest Windows path for the embedded PTY-backed Forecast Desk pane.

### Native Windows

Native Windows support is inherited and still early beta. Most CLI, gateway, cron, browser, and MCP paths work, but the dashboard `/desk` terminal pane depends on POSIX PTYs and is WSL2-only (`/chat` remains a compatibility alias). Prefer WSL2 for forecast-desk development.

## Windows (native, PowerShell) — Early Beta

This heading is retained as a compatibility anchor for inherited Windows docs. Native Windows uses the same transition posture as above: forecast-desk CLI workflows can run natively, while the PTY-backed dashboard Forecast Desk pane remains WSL2-only.

### Termux

Termux support is inherited from the upstream installer path. It can work for basic CLI usage, but this fork's recommended development path is still a local checkout with Python 3.11.

### Nix

The Nix and NixOS module docs are available in [Nix & NixOS Setup](./nix-setup.md). New installs should use the fork-native `superforecasting-agent` package, `forecast`/`superforecasting-agent` commands, and `services.superforecasting-agent` module; Hermes-named attributes and services remain compatibility aliases for existing installs.

## Updating

For a source checkout:

```bash
git pull
source .venv/bin/activate
uv pip install -e ".[all,dev]"
```

Then rerun:

```bash
forecast status
scripts/run_tests.sh tests/forecasting tests/test_project_metadata.py -q
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `forecast: command not found` | Activate `.venv`, reinstall with `uv pip install -e ".[all,dev]"`, or use `python -m superforecasting_agent`. |
| Model/provider not configured | Run `superforecasting-agent model` or `superforecasting-agent setup`. |
| State is under `~/.hermes` | Expected during compatibility. New installs prefer `~/.superforecasting-agent`; existing legacy homes are reused. |
| Browser/dashboard deps missing | Install with `.[all,dev]` and run the relevant `npm install` in `web`, `ui-tui`, or `website`. |
| Website build reports broken links or anchors | Treat this as a docs regression; run `npm run build` in `website` and fix the reported link before handoff. |

For deeper diagnostics:

```bash
superforecasting-agent doctor
```
