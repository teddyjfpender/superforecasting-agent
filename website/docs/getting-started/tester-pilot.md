---
sidebar_position: 4
title: "Beta Tester Guide"
description: "Install a pinned beta, try an isolated forecast, and report reproducible bugs."
---

# Beta tester guide

Start here for the supported beta path: install the assigned build, configure a
provider, open the terminal desk, and complete the synthetic walkthrough below.
Use `superforecasting-agent` throughout; you do not need to learn its compatibility
aliases or install development dependencies.

## 1. Get the assigned build

The beta coordinator supplies a release tag, its exact source commit, the backend
and terminal wheels, and their SHA-256 checksums. Use the same bundle throughout a
bug reproduction. Do not follow a moving snapshot branch or an unpinned `latest`
installer. Release publication is a separate operator step: **0.22.1 is currently
a candidate, not a promised downloadable release**. Wait for the assigned bundle.

This guide targets backend **0.22.1** and terminal **0.1.1**. If the coordinator
assigns different versions, use the filenames and checksums in that brief.

Install Python 3.11–3.13 and Node 20 or 22 first. From the directory containing the
verified wheels, create a dedicated environment:

```sh
python -m venv beta-env
```

Activate it on macOS/Linux:

```sh
source beta-env/bin/activate
```

Or in Windows PowerShell:

```powershell
.\beta-env\Scripts\Activate.ps1
```

With the environment active, install both products:

```sh
python -m pip install ./superforecasting_agent-0.22.1-py3-none-any.whl ./superforecasting_agent_tui-0.1.1-py3-none-any.whl
python -m pip check
superforecasting-agent-tui --check
```

Use `python3` instead of `python` where that is the installed interpreter name.
Compare each downloaded file with the coordinator's checksum using `shasum -a 256`
on macOS, `sha256sum` on Linux, or `Get-FileHash -Algorithm SHA256` in PowerShell.
Stop if a checksum differs. The wheels contain the compiled terminal; no npm build
or editable source installation is required.

## 2. Use an isolated beta profile and configure a provider

Set the profile before running any agent command. In macOS/Linux shells:

```sh
export SUPERFORECASTING_AGENT_HOME="$HOME/.superforecasting-agent-beta"
```

In PowerShell:

```powershell
$env:SUPERFORECASTING_AGENT_HOME = "$HOME/.superforecasting-agent-beta"
```

Repeat this selection in new terminals. Keep your ordinary profile separate.

```sh
superforecasting-agent setup
superforecasting-agent model
superforecasting-agent doctor
superforecasting-agent tui
```

Use setup to enter credentials for a provider you control, then select an available
model. Credentials belong in the profile's `.env`; model and runtime settings belong
in `config.yaml`. Model calls may incur charges. The synthetic ledger exercise below
needs no provider call; the TUI's research/chat operations do.

Inside the desk, `/help` is the command-discovery entrypoint. Use the forecast views
for everyday work. For terminal commands, `superforecasting-agent forecast --help`
and a subcommand's `--help` provide the relevant options without exposing every
support subsystem at once.

## 3. Complete one synthetic forecast

This exercises persistence and scoring, not forecasting skill. Keep it in the
isolated beta profile. Copy the `fq_...` question ID printed by the first command
and replace `QUESTION_ID` in the following commands.

```sh
superforecasting-agent forecast new "Will I finish this synthetic walkthrough?" --resolution-criteria "YES if I reach the resolve step in this walkthrough; otherwise leave this test question unresolved. Synthetic training record only." --domain beta-test
superforecasting-agent forecast update QUESTION_ID --probability 0.7 --rationale "I intend to finish the walkthrough." --reason-up "The installation is ready." --reason-down "A command may fail." --change-my-mind "An unrecoverable setup failure."
superforecasting-agent forecast list
superforecasting-agent forecast resolve QUESTION_ID --outcome true --source "Synthetic local walkthrough: reached the resolve step."
superforecasting-agent forecast score QUESTION_ID
superforecasting-agent forecast postmortem QUESTION_ID --what-happened "I completed the synthetic workflow." --what-was-expected "Completion was assigned probability 0.7." --lesson "This is a synthetic product check, not evidence of forecasting calibration."
```

Resolution can automatically score the outcome. Explicit scoring should remain
safe to repeat. Reopen the TUI and confirm the same question and outcome remain.
Do not mix this record or its lesson into a real learning evaluation. Real questions
need independent evidence and exact resolution semantics; successful source ingestion
does not mean that source is approved for settlement.

## 4. Recover without losing the reproduction

- **Interrupted call:** cancel through the desk, then inspect its displayed state.
  Cancellation can remain pending while provider code exits; do not assume it stopped
  merely because output paused.
- **Disconnected terminal:** reopen the desk with the same profile and use `/resume`.
  For a remote host, reconnect to the same host/profile; creating a new local profile
  will not recover the remote session.
- **Provider failure:** run `doctor`, check setup/model selection, and record the error.
  Do not repeatedly retry an authentication or quota error without addressing it.
- **Before an upgrade:** stop the desk and any host using that profile, then copy the
  entire profile directory to a private backup. Install only the next assigned bundle.
  Keep the original wheels and pre-upgrade backup. Restoring that backup discards
  subsequent changes; do not point an older binary at a migrated live profile.

If recovery fails, preserve the profile and report the exact interruption and
subsequent actions. Do not delete the database as a troubleshooting step.

## 5. Report a reproducible issue

```sh
superforecasting-agent debug share --local
```

This prints diagnostics locally, including installed backend and terminal versions.
Review the output before attaching it. Secret redaction is enabled by default, but
private question text, filenames and other personal information may remain.
Never use `--no-redact` for a beta support report.

`superforecasting-agent debug share` and the `/debug` shortcut upload diagnostics
immediately to a public paste service. Use them only when you intentionally want
that upload. Local output does not upload the report.

Use the repository's Bug Report template. Include the assigned release tag, installed
versions, OS, local/VPS mode, exact commands or interactions, expected/actual behavior,
and whether the synthetic walkthrough succeeds. Share a minimal synthetic export
rather than a private production ledger. Keep the failing version available until
the issue is reproduced; do not update blindly to a snapshot.

## Supported scope and limitations

See [beta support scope](./beta-scope.md) for qualified platforms and exclusions.
Installation and recovery qualification do not demonstrate better forecasting or
beneficial learning. Calibration claims require prospective evidence outside this
engineering walkthrough.
