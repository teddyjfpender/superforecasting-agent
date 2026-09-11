# Remaining work

This is the follow-up list from the September 2026 repository cleanup. Completed
work and verification are recorded in the [cleanup review](docs/plans/2026-09-10-cleanup-review.md)
and its linked work log. These items are not claims of known production failures.

## Completed reliability follow-up (September 10)

See [verification and reproduction](docs/plans/2026-09-10-forecast-reliability.md).

- [x] Fresh wheel installation and upgrade in isolated macOS profiles, including
  persisted configuration/evidence and create → research → update → resolve →
  score → postmortem through the installed public CLI.
- [x] Calibration lesson provenance, independent-outcome counts, small-sample
  safeguards, correction invalidation and bounded numerical adjustments.
- [x] Stalled-stream cancellation, durable follow-up prompts, session restart/resume,
  bounded terminal resize and dashboard reconnect with draft/output preservation.
- [x] Shared CLI/dashboard launch environment, isolated provider catalog ownership,
  and shared CLI/gateway alias expansion with cycle rejection.
- [x] Evidence source grouping, duplicate observations/revisions, timestamps,
  historical cutoffs, stale evidence and resolution outcome validation, including
  captured public USGS/NWS records.

## Before a production release

- [ ] Verify the pushed commit's CI results, including platform jobs and release
  gates. Keep the tested commit and release artifact provenance together.
- [ ] Run the integration and end-to-end suites excluded by the default Python
  runner with their required services and credentials. Record skips explicitly.
- [ ] Exercise the documented installation and upgrade paths on native Windows,
  Linux/container, and Android/Termux. This pass verified macOS and a wheel
  installed outside the checkout; it did not establish cross-platform readiness.
- [ ] Exercise paid-provider authentication and service-failure behavior under an
  approved budget. Public-source capture, local-model streaming and the installed
  lifecycle are verified; paid-service availability is a separate release gate.
- [ ] Build and publish the release through the release workflow after the above
  checks. A pushed source commit is not a published or deployed release.

## Continue modularization

- [ ] Decompose the remaining large classic CLI, runtime CLI, and messaging
  gateway responsibilities in bounded slices. Preserve public signatures,
  injected test seams, callback behavior, and wire responses.
- [ ] Continue splitting orchestration from parsing in remaining source adapters.
  Keep missing values distinct from zero and preserve provider outcome indices.
- [ ] Continue auditing remaining configuration/provider persistence differences.
  The picker catalog and CLI/dashboard launch settings now have clear ownership.
- [ ] Keep the ownership map and generated reference current as modules move.

## Identity and compatibility

- [ ] Review remaining inherited names by purpose: upstream attribution,
  external protocol/model identifiers, persisted data, or compatibility aliases.
  Migrate removable internal names; document any eventual alias removal before
  breaking existing installations. Do not rewrite third-party attribution.
- [ ] Reconcile older website guides and optional migration skills with the native
  runtime layout, without changing supported legacy-home migration behavior.
- [ ] Review the separate experimental terminal's product role and documentation;
  the Ink Forecast Desk remains the primary transcript and composer.

## Preserve the TUI and forecasting guarantees

- [x] Verify the installed public TUI outside the checkout: streamed local-model
  response, durable prompt/reply and clean exit. Keep this in future release checks.
- [ ] Extend the verified macOS cancellation/resume/resize/dashboard recovery
  cases to supported platforms and longer-running sessions, including Unicode.
- [ ] Keep scheduled monitoring limited to evidence, alerts, scores, and learning
  records; probability changes must remain explicit forecast updates.
- [ ] Evaluate forecasting accuracy and calibration with scored resolved questions;
  passing software tests does not establish forecasting skill.

## Lifecycle and learning follow-up

See [runtime changes and verification](docs/plans/2026-09-10-lifecycle-learning.md).

- [x] Recover missing score/postmortem handoffs through the existing durable queue;
  make them visible through CLI, TUI commands, and operational diagnostics.
- [x] Wake TUI maintenance for finalization work even when no reviews are due.
- [x] Record actual lesson decisions and rule verdicts, apply explicit in-scope
  supersession, and distinguish historical unverified application counts.
- [x] Share exact market-study evaluation records between CLI reports and scripts.
- [x] Back up and recover the live instance: 96 handoffs completed. Review the
  two missing-forecast outcomes separately without fabricating scoreable history.
- [x] Review 12 important settlement questions: six settled, six explicitly
  deferred with evidence needs or future outcome horizons recorded in the ledger.
- [x] Reconcile conditional weather guidance: ten lessons explicitly superseded,
  applicability enforced and lesson provenance frozen on subsequent snapshots.
- [x] Add an outcome-backed learning audit; report that causal benefit remains
  unestablished, rather than presenting reference counts as improved accuracy.
- [ ] Revisit the six reviewed/deferred questions when their recorded conditions
  are met. The remaining settlement book was deliberately outside this pass.
- [x] Correct the five newly settled BLS scores and 15 existing legacy CRPS
  scores with preserved correction lineage and replacement postmortems; a fresh
  preview reports zero remaining migrations for current resolved snapshots.
- [ ] Add explicit right-censored outcome representation and scoring before
  settling censored continuous questions. Do not substitute a boundary point.
- [ ] Evaluate prospective lesson benefit using independent outcomes and matched
  pre-adjustment forecasts; application coverage alone does not prove benefit.

See [live recovery, ledger hardening and measurement methodology](docs/plans/2026-09-10-live-lifecycle-learning.md).
