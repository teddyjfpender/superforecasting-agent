# Learning, settlement and runtime hardening

Release work is deferred at the operator's request. This work does not monitor CI
or assert a published release.

## Confirmed defects and changes

- SQLite reuses authorization on cached prepared statements. A raw INSERT first
  prepared inside `allow_ledger_writes` succeeded again outside that context on
  the same connection. Ledger connections now disable statement caching, with
  regressions covering context exit and a switch to proposal-only policy.
- An exception inside a SQLite authorizer becomes `DatabaseError: not authorized`,
  including on SELECT. The callback now logs its original exception and traceback
  without SQL values. This reproduces a possible mechanism for the historical
  deadline failure; it does not prove what interrupted that CI worker.
- Source bindings reject malformed contracts, missing/out-of-range timestamps,
  numeric strings, booleans, missing measurements and nonfinite values at the
  parser boundary. These remain observation contracts, not proof of a completed
  daily maximum or independent corroboration.
- New trial admission and readiness share evidence and score-support checks.
  Invalidated, superseded, blocked, explicitly stale and backtest-excluded evidence
  cannot enter new frozen packets. Calibration-ineligible or zero-weight scores
  cannot establish outcome-backed lesson support. Applicability rejection reasons
  are visible in candidate reports.
- A pending update refresh no longer displays the previous completed result.
- Historical censoring conversion previews every forecast's original payload and
  selected event probability, binds application to a SHA-256 review digest, and
  retains the original question/forecast manifest in its review history. Explicit
  `p_gt_*`/`p_gte_*` keys must match the declared inequality and threshold. Missing
  keys cannot silently fall back to a Gaussian. Existing scores use the correction
  workflow, not this conversion. Censored scores remain calibration-ineligible.

Completed historical trials retain their original config and packet identities.
The compatibility registry explicitly reviews the connection-only change and the
opt-in censoring representation: old contracts without `probability_key` retain
unchanged scoring. Unknown source/evaluation identities still fail closed.

## Investigation still open

The SSL crash stack was inside default certificate loading in an update-check
thread on Linux CPython 3.11.15. Single-flight update checks address the observed
thread accumulation, but no native crash reproduction establishes the full cause.
Do not label it fixed based on that mitigation alone.

Android/Termux access is pending. A temporary Linux ARM64 Docker VM was created
for local verification, then stopped and deleted; the original Docker context was
restored. Credential-dependent services still need actual service access. Linux
containers and hermetic tests cannot substitute for those external environments.

## Additional behavior fixes

Categorical Brier is summed across outcomes in this ledger. Its uniform baseline
is `1 - 1/K`, whereas scalar binary Brier's baseline is `0.25`. The sports
exact-score case scored 0.8486104214 against a 15-category baseline of 0.9333333333;
its old automatic high-Brier label was not justified. Postmortems and domain-error
profiles now share the outcome-aware comparison. Recomputing a profile ignores
obsolete automatic labels from historical postmortems without rewriting them.
A score is a review signal, never proof of a calibration defect from one outcome.

`forecast facts bind-settlement` binds an existing verified NWS/USGS fact to an
explicit entity, units, measurement and observation window. Resolution rechecks
the binding, source identity, archive integrity and exact value. Instantaneous
NWS observations cannot become daily maxima, and automatic USGS magnitudes cannot
be used as reviewed settlement evidence. Other sources still need their own
verified parser and measurement contract.

Automatic update checks run in a bounded disposable Python process. An abnormal
exit, malformed receipt or timeout leaves update status unknown; a native TLS
failure there cannot kill the foreground forecasting process. This contains the
observed crash location without claiming to know the native bug's cause.

Model-selection persistence now shares the main config lock. Profile metadata
uses the existing atomic YAML writer instead of truncating the live file.
`forecast lifecycle run <question>` fails explicitly: this command supports
ledger-wide recovery, and previously silently ignored the positional question.
Use `forecast lifecycle review <question>` for an individual review.

## Live operations

The online backup and detailed receipts are in the active profile's reports
folder, `2026-09-11-learning-settlement-runtime-111522`.

- SpaceX: all 30 original forecasts explicitly contained `p_gt_45_days`. The
  conversion preserved every payload and original criteria, with SHA-256 review
  binding. Consecutive primary mission records place Flight 12 on May 22 and
  Flight 13 on July 24. Resolution `rs_20cc3163b9b7`, score `sc_aefdbad653b4`
  (threshold-event loss 0.0784; calibration-ineligible), and postmortem
  `pm_5d31b67754f2` close that lifecycle. The original July 15 / >45-day calendar
  mismatch is explicitly retained and explained, not silently corrected.
- Six non-AI questions received primary-source research: FOMC timing, wildlife
  screwworm infection, psilocybin approval, MLB attendance, campaign-finance law
  and marine-treaty enforcement. Sources distinguish animal species, clinical
  investigations from approval, regular-season totals from other attendance,
  and treaty commencement from evidence of effective enforcement.
- The campaign-finance decision was already public despite its future ledger
  close time. An append-only ready-for-settlement review prevents new prospective
  enrollment; final settlement still requires linked-market identity review.
- Lesson `cl_5cc62289aa8d` is active for categorical outcomes, with the sports
  score as provenance. It teaches correct score interpretation, explicitly makes
  no numerical adjustment, and declares its one-outcome empirical limitation.
- Readiness after research: 252 future-closing questions, 52 ready for manual
  cluster review, 195 without applicable lessons, 93 without admissible evidence,
  eight unsupported vector-loss cases and one already-known outcome (overlapping
  categories). The two additional ready categorical cases still belong to AI
  infrastructure and US elections. No independent cluster count was inflated.

Research references: [FOMC calendar](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm),
[APHIS cattle detection](https://direct.aphis.usda.gov/news/agency-announcements/usda-confirms-presence-new-world-screwworm-united-states),
[FDA clinical-investigation guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/psychedelic-drugs-considerations-clinical-investigations),
[MLB reference attendance](https://www.mlb.com/press-release/press-release-mlb-attendance-reaches-71-4-million-three-straight-years-of-growth-for-first-time-since-2007),
[FEC case record](https://www.fec.gov/legal-resources/court-cases/national-republican-senatorial-committee-et-al-v-federal-election-commission-et-al-22-639/),
and [UN BBNJ agreement](https://www.un.org/bbnjagreement/en).


## Verification receipts

- Broad forecasting suite: 3,507 passed, three skipped. Later profile-mean and
  protocol-rendering refinements also passed their focused regressions.
- Final targeted macOS checks: 146 passed across persistence, update probes,
  source settlement, score review and lifecycle scope. Protocol/fact checks: six
  passed. Real macOS TUI/reconnect exercise: ten passed.
- Linux ARM64 / Python 3.11: final targeted suite 180 passed, including the real
  composer, cancelled-stream resume, Unicode/restart soak, gateway respawn and
  dashboard reconnect; four dependency deprecation warnings. Detailed JUnit and
  logs are retained with the operational receipts. The final one-line protocol
  import fix was verified on macOS after the Linux VM was removed.
- Generated CLI reference check passed; the architecture guide now points to the
  actual CLI/ledger packages and documents the new ownership boundaries.
- Seven affected live sports profiles were recomputed through the CLI. None
  retains the erroneous elevated-mean/high-Brier labels. Original postmortems and
  frozen trial treatments remain unchanged.
- A real `forecast protocol ... --stage update` call initially exposed a missing
  `json` import in applicability rendering. After repair, the Texas categorical
  update prompt contains lesson `cl_5cc62289aa8d`, its source references and the
  native-score baseline guidance. This verifies consultation, not beneficial
  probability movement or causal accuracy improvement.
- Live conservation: all 7,403 snapshot rows and every historical trial/case/arm
  are unchanged. Additions: seven evidence records, one resolution, one score,
  one postmortem and one reviewed lesson. SpaceX's finalization task completed.

The live evidence commands also exposed unavailable auxiliary Nous authentication
being described as a payment/credit failure in diagnostic copy. This is now fixed:
missing authentication, rate limits and payment failures carry distinct reasons
without changing cooldown behavior. Evidence and settlement persisted successfully.
