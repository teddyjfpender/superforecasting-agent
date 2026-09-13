# Installed-product qualification — 2026-09-13

Backend candidate **0.22.1**, independent terminal **0.1.1**. Receipts identify
artifact hashes and actual interpreters; these are engineering fixtures, not live
forecasts or evidence that calibration improves.

| Environment actually exercised | Result |
| --- | --- |
| macOS ARM64, Python 3.13.12 | Fresh products, both upgrades, local/remote Ink, durable scoring and authenticated reconnects passed |
| Debian Linux ARM64 container on Colima's native ARM64 Linux VM, Python 3.13.14, Node 20.19.2 | Same checks passed; no x86 emulation |
| Native Linux x86-64 / Windows | Matrix configured; execution not verified in this closeout |
| Windows interactive terminal | Explicitly skipped: no ConPTY harness |
| Android/Termux | No device available; not qualified |

Receipts: [macOS](macos.json), [Linux](linux.json).
The backend baseline is the published v0.19.0 wheel. The terminal baseline is
0.1.0 built from `3a42c3054f2a7f9671b69259ec2388b037728d55`'s product source and
the unchanged compiled Ink bundle; it is a locally built preceding version,
not a claim that terminal 0.1.0 was publicly released. Both old and new terminals
actually opened the desk and scored the durable fixture during the upgrade check.

## Repeatable checks

```bash
python3 scripts/build_profiles.py
python3 scripts/verify_profiles.py dist/profiles --python 3.11.15 --report qualification/report.json
# Add genuine older wheels when testing upgrades:
# --upgrade-from /path/to/older-backend.whl
# --terminal-upgrade-from /path/to/older-terminal.whl
```

Run on the target OS with uv and Node available. Wheel metadata, versions and
SHA-256 are recorded. Reinstalls/downgrades cannot qualify as upgrades. Failures
leave a failed receipt with completed/pending checks; Windows PTY skips produce
`passed_with_skips`. The product-quality workflow runs native Linux/macOS/Windows
against Node 20.19.2 and 22 and retains these receipts. This does not substitute
for Termux installation through its platform installer.

Installed tests use fresh environments outside the checkout. The backend has no
Node on PATH. Upgrade checks preserve question, forecast history, evidence,
Unicode session messages and configuration. Independent Ink uses a separate
interpreter, then connects to an authenticated installed headless host. Five
connections must see the same durable session inventory. Unauthorized tokens and
origins are rejected, shutdown completes, and logs must redact tokens.

## Fixes exposed by qualification

- Node 20's WebSocket API was disabled by default, causing endless unsuccessful
  remote retries despite passing prerequisites. Production launchers enable its
  native flag; standalone remote checks probe the same options before launch.
  Packaged launch requires Node 20.10+; direct Node/tsx development on Node 20
  needs `--experimental-websocket` (or use Node 22+).
- The canonical runner erased selected live-service credentials and excluded the
  selected suites. It now preserves only explicitly selected Daytona/Modal keys
  and collects their integration files. Both services lack credentials here.
- Release lifecycle used a wildcard that could pass the terminal wheel as a second
  backend argument after product separation. It now selects only the backend wheel.
- Runtime helper imports left behind by ownership extraction were removed; this
  inherited owner and the native TLS experiment now have blocking correctness lint.

## Release and native TLS limits

The formal local release rehearsal produced both wheels, sdist, installers,
validated manifest, notes and verified SHA256SUMS under
`/tmp/forecast-qualified-release`. Wheel member contents exactly match the
qualified candidates; archive hashes may differ because of build timestamps.
A separate installed forecast-lifecycle rehearsal passed both fresh and upgraded
profiles against the formal backend wheel (`/tmp/forecast-qualified-lifecycle/report.json`).
Release/installer regression checks passed 78 tests with one platform skip; focused
launcher, upgrade-receipt and live-runner checks passed 49 tests. The shared quality
gates passed all 76 import contracts. The full-suite pre-push log is
`/tmp/forecast-qualification-push.log`. No container image or release is claimed published. The production workflow
requires the tagged commit on the default branch. The existing v0.22.0 tag points
to `b98f8a85d36967e0ec81b4e54352f2e1dd86e42d`, so it was preserved and a successor
candidate prepared instead. Publish only through `production-release.yml` after
integration; verify downloaded assets before marking publication complete.

[Recovered native TLS report](previous-native-tls.json) comes from GitHub artifact
`10273627021` (2026-09-11), not a new run. It records the original runner image
version, Python 3.11.15, OpenSSL 3.5.5 and glibc 2.39. The synthetic abort captured
a core. Seven TLS cases did not reproduce the crash. The shutdown case completed
zero contexts, so its clean exit is particularly weak evidence of overlap.
Original incident binary/CA hashes and a native incident core remain unavailable.
Existing in-process OAuth, email, Weixin and library-owned certificate paths remain
outside update-check subprocess containment. No blanket lock or stress-only
"fix" is inferred from the absence of reproduction.

Conversation deadlines remain cooperative. A hard deadline for arbitrary SDK or
plugin code requires a separately owned process and durable IPC; killing threads
or closing live resources beneath them would violate the established ownership
contract. No new process architecture was added without an identified workload
that needs that guarantee.
