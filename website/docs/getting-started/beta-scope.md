---
sidebar_position: 5
title: "Beta Support Scope"
description: "Qualified beta platforms, experimental surfaces, and support limits."
---

# Beta support scope

The supported beta experience is the terminal forecasting desk with its shared
Python backend. Use the [beta tester guide](./tester-pilot.md) and its pinned
[v0.22.4 artifact bundle](https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v0.22.4).

| Surface | Beta status | Evidence and boundary |
| --- | --- | --- |
| macOS ARM64 | Supported | Fresh installation, upgrades, profile/plugin migration and terminal recovery on Node 20/22. |
| Linux x86-64 | Supported | Native fresh installation, upgrades, profile/plugin migration and terminal recovery on Node 20/22. |
| Windows AMD64 | Supported | Native ConPTY input, resize, cancellation, shutdown and installed upgrades on Node 20/22. |
| Linux VPS | Supported for the qualified headless host | Authenticated remote terminal reconnect and durable session recovery. VPS deployment requires operator-managed network access and credentials. |
| Linux ARM64 | Limited support | Earlier container/VM and upgrade evidence; not a member of the latest six-job native matrix. |
| Nix packaging | Experimental, outside supported beta | Linux x86-64 packaging, profile installation and the synthetic lifecycle are qualified; macOS/ARM installation remains unqualified. Its Linux/macOS workflow jobs remain informational, not required merge checks. Use the qualified wheels for supported beta installation. |
| macOS Intel | Experimental | No current native qualification receipt. |
| Android/Termux | Experimental, outside supported beta | No real-device qualification. Existing installation notes are exploratory. |
| Daytona and Modal execution backends | Unavailable as supported beta integrations | Credential-dependent verification has not run. Their presence in the code or setup UI is not a support claim. |
| Other optional messaging, browser, voice and plugin services | Experimental unless explicitly named in the tester brief | Credential-free tests do not qualify a live third-party service. |

The latest native run is
[34787794628](https://github.com/teddyjfpender/superforecasting-agent/actions/runs/34787794628).
All six platform/Node combinations verified the downloaded release artifacts and
passed fresh and upgrade checks, including
legacy profiles, customized/deleted skills and plugin execution. Python support is
3.11–3.13; the matrix used Python 3.11.15. This does not establish every OS/Python
combination independently.

## Desktop and VPS boundaries

The TUI owns the transcript and composer. A VPS runs the backend host; a desktop
terminal can connect to that host. The dashboard embeds the same TUI instead of
providing a second conversation implementation. Keep the beta's primary path in
the terminal; dashboard supporting panels remain optional.

Operators should expose a VPS host through controlled access such as an SSH tunnel
or authenticated TLS proxy. Do not publish an unauthenticated backend port. Keep
host tokens out of issue reports and command-history screenshots.

For host installation, token-file configuration and terminal connection commands,
see the [headless host reference](https://github.com/teddyjfpender/superforecasting-agent/blob/superforecasting-agent-snapshot/products/README.md#headless-protocol-host).
Use the assigned beta wheels with the backend `[web]` extra for this operator path.

## Known limits

- Cancellation is cooperative. A provider/plugin that does not stop immediately
  retains pending ownership until it exits.
- The historical native SSL crash has containment and diagnostics, but no conclusive
  attribution to its original build; original binary/certificate hashes are absent.
- Source coverage is intentionally narrower than all possible measurements. Unsupported
  units, identities, periods and revision policies fail closed at settlement.
- Learning effectiveness is not established by synthetic lifecycle or installation tests.
- Beta upgrades should preserve records, but retain a private pre-upgrade backup and
  the exact assigned artifacts for recovery and reproduction.
