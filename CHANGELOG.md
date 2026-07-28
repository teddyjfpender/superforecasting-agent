# Changelog

All notable changes to the Superforecasting Agent are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project aims to follow [Semantic Versioning](https://semver.org/):
`feat` → minor, `fix`/`perf` → patch, breaking changes → major. Entries are
derived from conventional-commit history since the previous tag. `pyproject.toml`
is the single source of truth for the version; every release ships the formal
artifact set described in `docs/plans/2026-07-09-hetzner-productionization.md`
(§P0): wheel, multi-arch image, `SHA256SUMS`, and a machine-readable
`release-manifest.json`.

## [Unreleased]

## [0.20.0] - 2026-07-28

This release makes the terminal desk's own delivery path trustworthy: the TUI
suite gates releases, the artifacts a user installs are verified, the desk can
say which build it is and recover when its gateway dies, and the behaviour a
real terminal exercises is finally covered by tests.

### Added
- **The TUI suite is now release-blocking.** A `tui` CI job (type-check, the
  full vitest suite, and a down-only `--max-warnings` lint ratchet) runs in
  `tests.yml`, and `production-release.yml` declares `needs: [gate, test,
  tui]` — a red TUI suite blocks a release, which it previously could not. A
  blocking, version-pinned and checksum-verified `actionlint` job now lints
  every workflow.
- **A build-version signal.** A typed `BuildInfo` rides `gateway.ready` and
  `session.info`: the running version shows on the Home hero context line and
  as the first line of the help overlay, and `forecast doctor` gained a
  `◆ Build Version` section that names the stale-install trap explicitly.
- **Gateway supervision.** Gateway death is now recoverable: a bounded respawn
  ladder (500 ms → 8 s backoff, five attempts, budget earned back by uptime
  since `gateway.ready`) with a visible reconnecting state, a terminal state
  carrying the captured stderr tail plus `/reconnect` · `/logs` · `/quit`, and
  session resume so a reconnect never lands in a blank session. Previously a
  dead gateway left the desk rendering normally with every RPC rejecting and
  no recovery but quitting.
- **A real-terminal test harness.** `tests/tui_pty/` boots the actual TUI
  bundle on a pty and covers what headless tests structurally cannot — first
  paint, the alt-screen/mouse/bracketed-paste enable and restore sequences,
  and an 80→120 column resize — on a VT screen emulator with its own tests.
  A Desk load budget (`test_desk_load_budget.py`) gates the
  `forecast.workspace` fetch on an invariant — same SQLite connection and
  statement count regardless of book size — rather than wall-clock.

### Changed
- **Installer integrity is fatal-by-default.** The one-line installer
  (`install.sh` release asset) verifies the wheel against `SHA256SUMS` and
  cross-checks the `release-manifest.json` pin, aborting with nothing
  installed on a mismatch; `upgrade.sh` and `hetzner-install.sh` share the
  same posture. This closes a silent degrade where a failed checksum download
  was swallowed and a missing `SHA256SUMS` merely warned before installing
  anyway. An explicitly operator-supplied local wheel remains a trust decision
  and still installs unverified.
- **The Docker Hub mirror skips cleanly when unconfigured** instead of failing
  on every published release; ghcr remains the canonical registry, and the
  Docker guide now pulls `ghcr.io/teddyjfpender/superforecasting-agent`
  (the bare Docker-Hub name it previously documented does not exist).
- **Demo Vis is dev-gated.** The chart-engine demo view no longer ships in the
  operator nav bar: `NAV_TABS` filters it out unless
  `FORECAST_TUI_DEV_DEMO_VIZ=1` is set, and `navPatchFor` refuses the route, so
  it is unreachable by click or chord — absent, not hidden. The view and its
  tests still ship behind the flag.
- **Docs re-audited against the code.** The Hetzner deploy one-liners now pin
  the live branch (both previously 404'd); `docs/operating.md` documents the
  Operations cockpit, every view, and the current Desk lens model;
  architecture/CLI/development counts (job types, ledger leaves, hook rules,
  import adapters) and the CI gating story were corrected; offline regression
  tests now pin the branch refs and the container registry so both rots fail
  tests instead of readers.

### Fixed
- **The first quickstart command was wrong.** README and CLI docs claimed bare
  `forecast` opens the TUI; it prints the plain-text desk dashboard. The docs
  now lead with `forecast tui` and document the bare behaviour.
- **The update check could never fire for this fork** — a pipx venv has no
  `.git`, the fork is not on PyPI, and the git lane compared against the
  upstream remote — so a release-manifest-based check replaces it. Also
  silenced the Node `MODULE_TYPELESS_PACKAGE_JSON` warning that printed before
  first paint in the checkout lane.
- **Every clean TUI exit leaked its gateway process.** `kill()` sent a bare
  SIGTERM without awaiting; node exited in ~0.1 s while the child took
  0.6–1.1 s to die and was reparented to init. The client now reaps (EOF
  stdin → SIGTERM → bounded SIGKILL escalation), and the OOM path stops the
  gateway instead of orphaning it.
- **A script-injection vector in `lint.yml`** — attacker-controlled
  `github.head_ref` interpolated inline into a `run:` block — caught by the
  new actionlint gate and routed through an environment variable.
- **`scripts/release.sh` was broken for its own default `--out=dist`** (it
  copied the wheel onto itself and `set -e` aborted the dry run), and the
  installer reported the version of whatever binary `PATH` resolved rather
  than the one it had just installed.
- **`generate-skill-docs.py` rewrote link-like tokens inside fenced and inline
  code** into repo URLs, producing 404s in three published skill pages.
- **The TUI help registry contradicted the implementation** (the Operations
  lens was missing, the view chord is `Ctrl+G` not `g`, and Models-mode keys
  were unregistered); the registry, the in-app help, and the operator's guide
  now match the code.

## [0.19.0] - 2026-07-24

This release turns the forecasting desk into a durable operating system for
continuous forecasts: source changes become recoverable work, scheduled review
jobs can be leased and resumed safely, and human/GitHub/Slack collaboration is
recorded through the ledger instead of living in side channels.

### Added
- **Durable source-change operations.** Watched-source changes now enter an
  explicit workflow with deduplication, leases, retries, dead-letter recovery,
  estimator and learned-error workers, resolution finalization, a canary, and
  auditable human-task handoffs.
- **Multiplayer ledger collaboration.** Transactional changesets, private
  provenance, portable workspace projection, Slack reviews, GitHub publishing
  and merge reconciliation, installation-grant enforcement, bounded
  discussions, safe transcript publishing, offline health metrics, and
  recovery operations complete the collaboration control plane.
- **Operations cockpit.** The Forecast Desk now surfaces review-sweep state,
  queued and running work, alerts, schedule health, source-change progress,
  decision readiness, market context, and operational recovery actions without
  replacing the primary Ink transcript.
- **Market and model support.** Kalshi and Polymarket quote/history paths gained
  richer normalized data, while the desk gained improved charts, discovery,
  filtering, and market-to-forecast context.

### Changed
- **Autopilot and scheduler durability.** Warning drains, refreshes, recurring
  schedules, and review sweeps use bounded budgets, explicit recurrence,
  leases, cooldowns, and persisted start/completion state so operators can
  distinguish slow work from dead work.
- **Session isolation.** Runtime model, provider, and voice changes remain scoped
  to the owning session; new sessions keep their configured defaults instead
  of inheriting whichever session switched most recently.
- **Architecture modularization.** The ledger, forecasting CLI, quorum,
  dashboard, TUI forecast leaves, and gateway RPC families were split into
  focused modules with compatibility delegates, reducing the hottest
  monoliths without changing their public contracts.

### Fixed
- **Provider failure containment.** Shared Gemini hard-quota circuit breaking
  prevents repeated doomed calls, GMI fallback no longer issues a second
  nondeterministic live probe, and TUI authentication recovery rebuilds agents
  with fresh credential pools.
- **Desk and terminal reliability.** Network-backed market RPCs no longer block
  the gateway dispatcher; forecast charts, tables, scrolling, repaint budgets,
  viewport resizing, terminal modes, and provider switching received
  regression coverage and stability fixes.
- **Operational correctness.** Alert lifecycle reconciliation, source
  signatures, schedule deduplication, review leases, resolved-forecast
  teardown, GitHub ownership checks, and generated protocol/docs consistency
  are now enforced at their write boundaries.

## [0.18.0] - 2026-07-09

The forecasting-quality arc lands as the default, and the release process
itself becomes a formal, testable artifact.

### Added
- **Gate lattice (superforecaster-by-default).** The behaviour gates completed
  into a 42-rule lattice: per-candidate intervals are built, rendered, and
  gated; the "Clacton class" of ungrounded forecasts is now structurally
  impossible; thesis remediation carries never-again rules. Superforecasting is
  the default posture, not an opt-in.
- **Bayesian Ledger Foundations (BLF) harvest, A1–A7.** Belief trajectories and
  K-trial shrinkage (A1+A2); disagreement now steers pool-vs-anchor blending
  (A3); a hierarchical Platt calibration path (A4, shipped honestly **OFF**);
  deterministic specialists earn quorum seats (A5); difficulty-adjusted cohorts
  and a commit clamp for scoring (A6+A7). BLF artifacts are wired into the gate
  lattice (38 rules).
- **Quorum upgrades.** Delphi-style revision rounds; blind-then-reconcile with a
  deviation ledger; connected-provider panels with market-anchor discipline;
  fresh search with Delphi default ON and anchor-hugging demoted to an ERROR.
- **Information-triage subsystem** replicating desk judgment on what to read,
  plus multiplayer M2/M3 (the sfp/1 card wire; the import pipeline where imports
  are provably guests).
- **Scoring measurement.** CRPS, curation, ablation, and diversity metrics;
  cohort scoreboards so the pooled Brier is no longer an unbacked claim.
- **Release engineering (§P0).** A formal, versioned artifact set per `vX.Y.Z`:
  `scripts/release.sh` (dry-run-default: build + `SHA256SUMS` + machine-readable
  `release-manifest.json` + changelog scaffold), a shared readiness gate
  (`scripts/check-release-ready.sh`), the manifest schema + validator
  (`scripts/release_manifest.py`, `scripts/release-manifest.schema.json`), and
  the `production-release.yml` workflow (wheel + multi-arch ghcr.io image +
  checksums + manifest attached to the GitHub Release).

### Changed
- **Warnings lifecycle closed.** The free-tier warning backlog drained from
  2,773 open to 301, honestly; the free drain no longer requires an autopilot
  policy, and the `R` view renders a fixed progress bar instead of scrolling the
  transcript.
- **Missing-observation discipline.** Lag is not absence and absence is not
  zero — the data plane now models the missing-observation rule explicitly.
- **Version source of truth.** `pyproject.toml` (with `hermes_cli/__init__.py`
  and the ACP registry manifest kept in lockstep) is the single version source;
  the ad-hoc CalVer/SemVer split is superseded by SemVer `vX.Y.Z` releases.

### Fixed
- **TUI quality arc.** One-frame viewport explosions (scrollbar blink + drag
  jitter, one root); the token counter shows real work rather than the cache
  meter (4.8M was 312.9k); the transcript/keystroke flash cured (4,886 → 110
  bytes per keystroke); every alt-screen frame is DEC-2026 bracketed so the
  flash dies; transcript scrolling unstuck; charts never clamp and previews tell
  the story in 15 dots; the ghost-completion overlay per keystroke removed;
  liveness (verb, elapsed, tokens) rendered on a real heartbeat.
- Polymarket watches ride the data plane so events resolve at last; paired
  bootstrap scoring summaries sped up; replay probabilities preserved in the
  backtest.

## [0.17.0] - 2026-06-30

Baseline for this changelog (released as tag `v2026.6.30`). Shipped the typed
layered config + `forecast config doctor`, the HTTP+SSE gateway serve mode, the
approval/spend policy matrix, auto-resolution detection, the self-protecting
ledger (online backup, integrity checks, daily cron), multiplayer M1 (agent
identity + Slack voice), and the living generated documentation set.

[Unreleased]: https://github.com/teddyjfpender/superforecasting-agent/compare/v0.19.0...HEAD
[0.19.0]: https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v0.19.0
[0.18.0]: https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v0.18.0
[0.17.0]: https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v2026.6.30
