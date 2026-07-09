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

[Unreleased]: https://github.com/teddyjfpender/superforecasting-agent/compare/v0.18.0...HEAD
[0.18.0]: https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v0.18.0
[0.17.0]: https://github.com/teddyjfpender/superforecasting-agent/releases/tag/v2026.6.30
