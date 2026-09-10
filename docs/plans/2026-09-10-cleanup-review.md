# Repository cleanup review

Status: this cleanup round is wrapped up at the user's request. This note summarizes the
integrated worktree; the detailed evidence and intermediate failures are in the
[work log](2026-09-09-product-repository-cleanup.md). The user has authorized committing and pushing this verified worktree.
Release deployment is not part of this closeout.

## Structure and product identity

The public package, runtime services, storage, tooling, and trajectory utilities
now live under `superforecasting_agent/`. The former `hermes_cli/` package and
standalone inherited infrastructure modules have moved into that namespace.
The [migration guide](../architecture/runtime-layout.md) maps old internal imports
to their current locations and explains the retained launcher, home, environment,
and persisted-data compatibility paths.

The root README leads with the forecast desk, its TUI, installation, workflow,
and repository layout. Historical release material, platform packaging, and data
generation utilities have dedicated directories. New checkpoint stores use the
Superforecasting Agent identity; existing stores are preserved.

Measurements against starting commit `b0a15ea05289111ade2b3d8710ebb240ce6c17d5`:

| Surface | Before | Integrated worktree |
| --- | ---: | ---: |
| Root Python files | 16 | 3 |
| Classic CLI entry point | 15,005 lines | 11,843 lines |
| Agent entry point | 4,448 lines | 3,040 lines |
| Source adapter facade | 10,193 lines | 2,675 lines |
| Session storage facade | 3,285 lines | 374 lines |
| Runtime CLI entry point | 13,817 lines | 11,857 lines |

These are entry-point and facade measurements. Implementation moved into focused
modules; the table does not imply that all removed lines were deleted from the
product. The [ownership map](../architecture/ownership-map.md) records the new
boundaries and extension points.

## Behavior preserved and hardened

The Ink TUI remains the primary interface, including the dashboard's embedded
PTY. Its renderer package is now `@superforecasting/ink`. Python owns the same
session, tool, and command behavior; no replacement React transcript was added.

Storage, tool dispatch, provider setup, checkpoint commands, and source adapters
were extracted with syntax-tree, signature, serialization, or executable behavior
comparisons appropriate to each boundary. Source-reader injection and the existing
public loader names remain available.

Regression fixtures cover malformed source metadata, optional timestamps and
fiscal years, finite fetch timeouts, valid empty result pages, historical Wikipedia
extracts, and prediction arrays whose missing entries previously shifted outcome
labels. Runtime fixes include command-input handling and test import isolation.
The work log records each reproduced failure separately from moves-only changes.

## Verification checkpoint

| Check | Latest evidence |
| --- | --- |
| Full hermetic Python suite | Run 42: 30,123 passed, 147 skipped, 48 warnings in 594.65 seconds |
| Provider setup and CLI suite | 5,960 passed, 8 skipped after the cumulative setup changes |
| TUI TypeScript suite | 2,010 passed, 1 skipped across 185 files after the renderer migration |
| TUI build, types, lint | Passed after that migration; later batches did not edit Ink source |
| Python lint and architecture | Whole-repository Ruff passed; all six import contracts kept |
| Release installation | Wheel source bytes and required assets checked; installed outside the checkout |
| Actual TUI interaction | Installed CLI exchanged a response with a local model fixture and exited cleanly |

Full Python run 42 passed against the integrated setup and session-browser batch.
Final formatting preserved Python syntax trees and all string literals; the
formatted wheel was rebuilt, byte-verified, installed, and exercised in the TUI. The latest installed
wheel has SHA-256
`2875d1c4977b2c2f2647fff8985d578f0672dba2b4f26bf36bdc92bcc3265467`;
962 packaged Python files, four plugin assets, the TUI bundle, and the Termux
constraints were compared with their source artifacts.

## Remaining work and verification limits

Large modules remain, particularly the runtime CLI, classic CLI, and messaging
gateway. Their remaining responsibilities still need incremental decomposition;
the repository is not uniformly small-module code.

The default Python runner excludes integration and end-to-end suites. Provider
and source fixtures establish local behavior, not live service availability or
forecasting performance. Installed TUI checks used a local model fixture. This
pass has not validated native Windows, Android, or an actual container deployment.

The [TODO document](../../TODO.md) records the remaining work. This round is
complete as a cleanup checkpoint; it does not establish full production release
readiness or eliminate every compatibility name. Release publication remains a
separate task.
