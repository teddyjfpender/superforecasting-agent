# Remaining work

This is the follow-up list from the September 2026 repository cleanup. Completed
work and verification are recorded in the [cleanup review](docs/plans/2026-09-10-cleanup-review.md)
and its linked work log. These items are not claims of known production failures.

## Runtime ownership and real desk follow-up (September 11)

See [investigation, changes and evidence limits](docs/plans/2026-09-11-runtime-ownership.md).

- [x] Fix SDK pipe double-close with deterministic descriptor-reuse regression.
- [x] Protect gateway lock leases from stale cleanup and shield shared shutdown
  from a cancelled waiter.
- [x] Exercise real Ink, gateway, dashboard transport and SQLite together with
  local failure providers; fix temporary-versus-durable session ID recovery.
- [x] Remove fabricated publication times from remaining economic ingestion;
  reject wrong identities, ambiguous fields and malformed rows, with pure parsers.
- [x] Share service-tier/fast-command semantics and TUI atomic setting updates.
- [x] Release gateway startup leases on early exits; prevent embedded runners from
  adopting another runner's lease.
- [x] Bind configuration caches to contents; serialize credential edits and route
  memory setup through the shared writer.
- [x] Extend price/OWID ingestion checks for identity, malformed arrays/columns and
  ambiguous measurements; retain unknown publication times and fail-closed settlement.
- [ ] Conclusively attribute the historical native TLS crash. Native GDB experiment
  and core-capture workflow ran successfully on the matching native runner image;
  preserved-libc and upgraded-libc trials did not reproduce it. Python embeds
  OpenSSL 3.5.5; native real-desk tests passed. Original incident hashes/environment
  were not preserved. A clean experiment or synthetic abort is not an SSL cause.

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

## September 11 implementation and operational follow-up

See [current evidence and limits](docs/plans/2026-09-11-forecast-quality.md).

- [x] Separate semantic domains from acquisition labels with audited corrections.
- [x] Validate provider readiness, preserve response budgets and reject truncation.
- [x] Add NWS/USGS identity, units, measurement-window and revision contracts.
- [x] Carry declared right-censoring through resolution, scoring, exports and TUI.
- [x] Share model configuration/persistence and isolate gateway command hooks.
- [x] Verify 18 Unicode turns across three TUI lifetimes with durable history.
- [x] Finish prospective cohorts and retain failed arms: five and three complete
  pairs respectively, across two conservative clusters; outcomes still pending.
- [x] Verify fresh installation and upgrade on Windows, Linux and macOS in CI.
- [ ] Publish and verify the formal release artifact set. The v0.22.0 tag's
  release gate failed twice; fixes are in the follow-up branch, and the corrected
  candidate needs an explicit release-identity decision before publication.
- [ ] Supply Android/Termux access and missing live-service credentials.

## Current hardening pass (September 11)

See [implementation, live operations and limits](docs/plans/2026-09-11-learning-settlement-runtime.md).

- [x] Close the cached-statement ledger authorization bypass; retain callback
  exceptions that SQLite otherwise reports only as "not authorized".
- [x] Share stricter trial input admission and exclude known settlement outcomes
  even when their nominal closing date is in the future.
- [x] Repair applicability-evidence prompt rendering and verify that the new
  lesson and provenance reach the real update prompt.
- [x] Correct categorical review thresholds and stop historical binary-cutoff
  labels from contaminating recomputed error profiles.
- [x] Add exact source-specific settlement binding and audited historical
  censoring conversion. SpaceX is resolved, scored and postmortemed with its
  original explicit tail probability; no calibration/skill claim is made.
- [x] Contain optional update-probe native failures in a bounded child process.
- [x] Verify Linux cancellation/resume, gateway recovery and dashboard reconnects
  locally, independently of CI; retain macOS verification.
- [x] Reuse atomic profile writes and the configuration lock for model persistence;
  reject ignored question scope on global lifecycle recovery.
- [ ] Broaden beyond the existing two independent prospective outcome clusters.
  Six non-AI questions received researched primary-source evidence; one already
  has public outcome information and is excluded from prospective enrollment.
  The new categorical scoring-process lesson is not evidence of improved skill.
  Current audit: 195 questions lack applicable lessons, 93 lack admissible
  pre-cutoff evidence, and 52 are ready only for manual cluster review.
- [ ] Obtain Android/Termux access and missing live-service credentials. Linux
  containers do not establish Android or native Windows PTY recovery behavior.
- [x] Reproduce the SQLite signal/authorizer mechanism on uv Linux x86-64
  CPython 3.11.15; preserve the actual exception and verify rollback/reuse.
- [ ] Obtain a native core dump or reproducer for the historical TLS fault. Bounded
  tests on matching-version uv Linux, Debian and ARM64 did not reproduce it;
  subprocess containment is verified, but the exact native cause remains unproven.
- [ ] Review the Japan-earthquake settlement's substitution of USGS for its linked
  Manifold oracle, and the court decision's exact linked-market identity.
- [x] Distinguish missing provider authentication, rate limits and payment errors
  in auxiliary-provider cooldown diagnostics.
- [x] Extend source-specific bindings to reviewed BLS and FRED observations with
  explicit revision policy and archived FRED series metadata. See the source-transfer
  follow-up below. Broader guide reconciliation remains in the documentation list.

## Engineering integrity follow-up

See [implementation and verification](docs/plans/2026-09-11-engineering-integrity.md).

- [x] Share resolution validation with imports; reject invalid unscoreable
  outcomes, boolean strings and inconsistent censored score/tail records.
- [x] Serialize resolution, score and postmortem retries; make postmortem/lesson
  handoffs atomic, add nested rollback savepoints, and preserve forced-rescore lineage.
- [x] Detect and repair historical missing lesson handoffs without replacing
  postmortems or existing lesson decisions.
- [x] Share indexed configuration updates across command surfaces, serialize
  updates across processes, and reject stale loaded full-config saves.
- [x] Close interrupted SQLite setup handles and test real update-probe timeout
  and signal-exit containment. Historical native TLS cause remains unproven.
- [x] Reject messages and replies from replaced/stopped TUI transports.
- [x] Separate BLS parsing from fetching; preserve zero, reject wrong entities and
  ambiguous revisions, and stop treating observation periods as publication dates.
- [x] Reject duplicate/nonfinite/overflow JSON across source adapters and make
  promotion tests independent of the operator's ledger.

## Source transfer and recovery follow-up

See [implementation, reproduction and limits](docs/plans/2026-09-11-source-portability-runtime.md).

- [x] Version source-bound exports, transfer archived bytes transactionally, retain
  historical provenance, and require explicit local byte verification.
- [x] Quarantine imported forecasts/scores from calibration even after verification.
- [x] Close raw configuration writer bypasses and reject stale dashboard/TUI saves.
- [x] Persist TUI partial turns before notifications; test provider failures,
  cancellation, owner-aware resume, stale frames and storage failure.
- [x] Preserve real SQLite callback interruptions through statements and commits;
  strengthen update-probe runtime identity and crash diagnostics.

## Before a production release

- [ ] Verify the pushed commit's CI results, including platform jobs and release
  gates. Keep the tested commit and release artifact provenance together.
- [ ] Run the integration and end-to-end suites excluded by the default Python
  runner with their required services and credentials. Record skips explicitly.
- [ ] Exercise the documented installation and upgrade paths on native Windows,
  Linux/container, and Android/Termux. Desktop installation and upgrade passed
  the CI matrix; Android/Termux and published-artifact verification remain.
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
  cases to other supported platforms and longer-running sessions. The macOS
  60-turn Unicode exercise across five process lifetimes passed locally and in
  macOS CI. Linux cancellation/resume, input/soak, gateway and reconnect tests now pass
  locally, including the live-worker orphan assertion. Android/Termux
  still requires device access.
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
- [x] Add explicit right-censored outcome representation and scoring before
  settling censored continuous questions. Do not substitute a boundary point.
- [ ] Evaluate prospective lesson benefit using independent outcomes and matched
  pre-adjustment forecasts; application coverage alone does not prove benefit.

See [live recovery, ledger hardening and measurement methodology](docs/plans/2026-09-10-live-lifecycle-learning.md).

## Controlled learning and durable settlement

See [commands, invariants and limits](docs/plans/2026-09-10-controlled-learning-lifecycle.md).

- [x] Add prospective paired learning trials with frozen evidence, policy, model,
  budgets, cluster assignments, durable call receipts and explicit missingness.
- [x] Add source-backed, typed lesson conditions with archive hashes, observation
  times, freshness limits and cutoff-bound provenance; expose unknowns in the desk.
- [x] Add append-only settlement states, ownership, next actions and durable
  reminders; distinguish missing historical forecasts from recoverable handoffs.
- [x] Prevent binary calibration adjustments from corrupting physical quantities.
- [ ] Accumulate independent prospective outcomes before claiming learning benefit.
- [x] Add source-specific bindings only after verifying their actual schema and
  measurement meaning; do not infer completed weather periods from local time.
- [x] Preserve quarantine reasons in typed score records and JSON exports, and
  reject quarantined lesson provenance during trial enrollment and comparison.
- [x] Accept one complete JSON code fence without retrying the model; retain the
  original response and reject ambiguous duplicate fields or surrounding prose.
- [x] Reconcile acquisition labels such as `market_nightly` with semantic domains:
  the live pilot exposed politics questions that cannot retrieve politics lessons.
  Keep acquisition provenance separate; do not silently broaden lesson scope.
- [x] Run a new prospective cohort once the provider is available, with a
  predeclared response budget sufficient for complete JSON. Earlier failed pilots
  had no usable pairs; September 11 cohorts retained five and three complete pairs
  across two conservative clusters. Outcomes remain pending.
- [x] Make numeric trial response schemas explicit and account for provider input
  quotas when pacing cohorts; preserve failed arms without rerolling.
- [x] Separate trial execution identity from evaluation compatibility so later
  prompt changes do not strand frozen comparisons; preserve historical integrity.

See [trial follow-up evidence](docs/plans/2026-09-11-trial-followup.md) for quota pauses,
legacy evaluation compatibility, cohort readiness gaps and settlement rechecks.
