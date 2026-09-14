# Experimental Nix qualification — 2026-09-14

The Linux x86-64 Nix package built successfully and installed into a separate
Nix profile on a temporary Ubuntu 24.04 Hetzner VM using Nix 2.18.1. The installed
CLI reported Superforecasting Agent v0.22.4. Nix remains experimental and its
workflow jobs remain non-blocking; no published release was changed.

## Evidence

[qualification.json](qualification.json) records the base commit, exact hashes of
modified source and lockfiles, OS/runtime versions, installed profile path and
all 14 successful check outputs. This was a working-tree qualification, not a
claim that a published tag contains these changes. The recorded source hashes
were compared against the local implementation before publication of this report.

The checks cover bundled assets, entrypoints, Node wrappers, configuration merges,
managed-install guards, package overrides, revision aliases and a synthetic
forecast lifecycle. The lifecycle uses the installed CLI for create → research →
update → resolve → score → postmortem, including repeated scoring. It supplies
structured reasoning and marks the forecast calibration-ineligible.

An additional installed-product probe used `scripts/terminal_session.py` from
outside the source checkout. It launched the profile's `superforecasting-agent tui`,
observed `setup required`, resized to 35 rows × 120 columns, sent `/quit`, and
verified exit status zero. No provider credentials or model calls were used.

## Reproduction

From the qualified source, follow [the Nix guide](../../../nix/README.md):

```sh
nix run .#fix-lockfiles -- --check
nix build --print-build-logs
nix flake check --print-build-logs
nix profile install --profile /tmp/sf-installed .#superforecasting-agent
HOME=/tmp/sf-install-home /tmp/sf-installed/bin/superforecasting-agent version
```

Create the disposable home before invoking the installed command. Never point a
qualification run at a real forecast profile. The package-contents check now sets
a writable isolated home instead of inheriting Nix's `/homeless-shelter`.

## Limits

Cross-evaluation passed for the declared flake systems, but these receipts qualify
installation only on Linux x86-64. They do not establish macOS/ARM installation,
Android/Termux operation, external-service integrations, long-running TUI recovery
or improved forecasting skill. The temporary qualification server was deleted
after receipts were retrieved; no existing project servers were changed.
