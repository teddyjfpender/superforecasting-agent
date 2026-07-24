## 24-hour capacity, content-yield, and operator-loop follow-up — 2026-07-23

The next unattended audit found that correctness held while source arrivals again
outpaced the one-task-per-30-minute estimator lane. This pass separates source
estimation from warning work completely and closes the remaining visibility and
operator-action gaps.

### Implemented

- Source estimation now has its own installed 15-minute cron job. It routes new
  immutable events, reclaims leases, sizes each batch from backlog pressure, and
  may burst to eight question-level tasks per cycle. A hard 48-task daily ceiling
  remains explicit. Oldest/P90 pending targets are two/four hours; two consecutive
  bad cycles open one deduplicated SLO alert, and an empty healthy queue closes it.
- The task claimer now backfills beyond same-question siblings. Previously a
  four-task selection could contain four events for one question, claim one, skip
  three because of the question fence, and return only one unit of work. It now
  scans a bounded larger candidate set until the requested number of distinct
  question claims is filled.
- The live source queue was drained from 57 pending observations to zero:
  `763 processed / 15 terminal failed / 0 pending`, with no stranded or open
  failed source task. In the last six hours, 56 events arrived and 111 reached a
  terminal state. The 24-hour window is exactly balanced at 135/135 and has no
  remaining age debt.
- Source snapshots now stamp `parser_version=changed-items-v1`. The Operations
  cockpit reports per adapter/source: event count, changed-item count, title/text,
  publication time, canonical URL, content hash, parser/adapter versions, and
  insufficient-content percentage. Only observations produced by the current
  parser count toward automatic low-yield suspension.
- Exact watches are suspended after three observation failures in seven days, or
  after five current-parser terminal events with at least 95% insufficient
  content. Suspension opens one repair/replace alert rather than manufacturing a
  probability proposal. The repeatedly failing Labour/next-PM Polymarket event
  page was suspended; its BBC and Guardian RSS watches remain active.
- Source-observation failures and insufficient-content dispositions now close the
  exact source-task alert. A separate suspension alert owns source repair.
  Estimation-required and autopilot-estimation alerts deduplicate by question
  condition rather than model-run ID. The live family migration folded 27
  redundant rows across 11 groups and the alert lifecycle trigger retired their
  redundant tasks.
- The cockpit now includes rolling 6h/24h source flow, 24h/7d alert arrivals,
  closures, net flow, P90 open age, P90 closure latency, executable percentage,
  and a grouped human inbox. The inbox prioritizes resolution-related work and
  exposes valid acknowledge, defer, resolve, and return-to-reforecast actions.
  Live `awaiting_human` work fell from 25 to 14 after duplicate condition families
  were folded; ten distinct questions remain for real operator judgment.
- Recurring job failures retry independently of recurrence at 15 minutes, one
  hour, and four hours, then return to their normal schedule. Empty output remains
  a failure. Forecast cron health now includes forecast-named agent jobs without
  generated scripts, so the failed weekly primary-race job is visible rather than
  omitted from doctor.
- Leak-domain safety remains row-level and unchanged, but repeated Yahoo/backtest
  messages are INFO-level and one normalized end-of-process tally replaces
  thousands of warning lines.

### Live state and readiness

At the final reconciliation checkpoint:

- operational tasks: `1,115 completed / 12 pending / 14 awaiting_human`;
- source events: `763 processed / 15 terminal failed / 0 pending`;
- open alerts: `55 high / 273 warning / 1 info`;
- forecast proposals: no pending proposals;
- source-estimator job: installed as `ba6eff9b02a8`;
- dedicated source-estimator daily usage at reconciliation: 19 of 48 task claims.

The failed weekly primary-race review was explicitly re-armed and completed a
substantive successful retry at `2026-07-23T18:39:20+01:00`; its ordinary Monday
recurrence remains scheduled. The dedicated estimator also completed its first
installed cron tick successfully at `18:42:21+01:00`. Forecast cron health is now
green, while future enabled failures—including agent jobs without generated
scripts—remain visible to doctor.

Tester/pilot readiness remains separate from the scientific claim. No readiness
threshold was weakened and no score was fabricated; the canonical live claim
still requires 100 eligible live binary scores.

Validation:

```text
focused source/alert/cron regressions: 175 passed
TUI type-check:                         passed
TUI lint:                               0 errors (pre-existing warnings only)
ruff on touched Python:                 passed
full forecasting suite:                3,206 passed, 2 skipped
JUnit artifact:                         .test-results/feedback-24h-3-final-forecasting.xml
```

## 22.5-hour unattended-operation follow-up — 2026-07-22

The latest audit confirms that the control plane is functioning and narrows the
remaining defects to explicit worker and data-contract boundaries. This pass
fixed those boundaries without weakening forecast commit gates or scientific
readiness criteria.

### Implemented corrections

- Numeric estimator output is normalized before ledger validation. Typed
  envelopes may use a nested `distribution`, while structural fields such as
  `type`, `units`, `bounds`, and `estimate_status` never enter the numeric
  distribution. Deterministic schema failures now dead-letter after one attempt
  instead of consuming five identical retries. The live Q2 median-weekly-earnings
  dead letter replayed its already-persisted estimate with no sixth model call
  and closed `reviewed_immaterial`.
- Every worker cycle reclaims expired leases. Human escalations have the distinct
  `awaiting_human` state, retain an owner and escalation timestamp, and are
  excluded from worker backlog/throughput latency. The stale leased task is now
  awaiting its human owner, not claimable by an ordinary worker. Six older
  `recovered_to_reforecast` trigger tasks were terminally coalesced into the
  estimator/source-event work that already owned their questions.
- Provider/model compatibility is checked before dispatch. In particular,
  Anthropic model names cannot be sent through ChatGPT Codex, and quantitative
  method identifiers such as `correlated_regime_switching_monte_carlo` are moved
  into `analysis_type` rather than treated as LLM model names. Triage defaults
  to the configured active provider/model instead of an incompatible hard-coded
  judge. Hard Gemini quota exhaustion opens a shared one-hour circuit breaker;
  later CLI, gateway, and cron sessions use an allowed fallback or stop before a
  second doomed request.
- URL adapters reject concatenated URLs, control characters, non-string list
  members, and non-HTTP public URLs before dispatch. Explicit absolute local RSS
  fixtures remain supported. `web_extract` is exposed only when an extraction
  provider exists; DDGS/Brave/SearXNG are reported as search-only instead of
  being repeatedly attempted as extractors. Forecast tool schemas now explain
  the required `source_or_note`, raw-URL ingestion path, and exact Bayesian
  sensitivity shape.
- Watched-source signatures now retain the bounded immutable content that
  produced them. Source snapshots carry changed entry ID, title, publication
  time, canonical URL, summary/claim, old/new values, content hash, and
  observation time. These changed items become durable evidence refs on a
  proposal. Legacy signature-only observations close `insufficient_content`
  without invoking an estimator or manufacturing a probability proposal.
- Every pending proposal gets a dedicated `awaiting_human` review task, owner,
  SLA/expiry time, one-hour expiry warning, and explicit approved, rejected,
  expired, or superseded terminal state. Signature-only proposals are never
  auto-committed. The four live unsupported proposals were rejected and their
  alerts/events reconciled.
- The cockpit now reports arrival-to-claim and claim-to-terminal percentiles,
  an aged-high canary, new SLA violations separately from seven-day cleanup
  debt, and human work separately from executable backlog. High-severity work
  remains oldest-first within its minimum allocation.
- The 13 duplicated Alaska refresh failures are now one batch failure plus 12
  terminal per-source child records. Future multi-event failures use the same
  representation. Attempt-zero historical task rows are archived as recorded
  history, while genuinely retryable or human-owned failures remain actionable.
  Terminal external-source failures stay visible but no longer make doctor
  report an active worker failure.
- Repeated inadmissible-domain evidence warnings are emitted once per normalized
  domain/reason per process while every evidence row retains its own audit
  metadata.
- The canonical test runner writes a per-run JUnit artifact and a simultaneously
  streamed log under `.test-results/`. An outer five-minute timeout can no longer
  erase the first failure or all partial progress from a nine-minute suite.
- Every newly claimed operational-task attempt records the Git commit SHA and a
  dirty-worktree bit. Deployed worker behavior can now be tied to an exact code
  base even before the remaining dirty worktree is split and tagged.

### Live reconciliation

- Source events at the final checkpoint: `623 processed`, `4 failed`, `0 pending`;
  the failures comprise
  one Alaska batch parent, one New Hampshire batch failure, and two independent
  Labour source-observation failures. Twelve Alaska child records are terminal
  and no longer counted as 12 additional failures.
- Operational tasks at the final checkpoint: `13 pending`, `0 leased`,
  `0 dead_letter`, `0 failed`, `18 awaiting_human`; all six recovered trigger
  duplicates are gone. The 13 pending tasks are owned normal/urgent forecast
  work, not source events. Bounded workers remain installed and healthy.
- Proposal backlog: the four unsupported proposals are rejected; no signature-
  only proposal remains pending.
- Active-book coverage has no service-mode gap. The passed-close Gaza question
  now uses its Manifold watch as a typed resolver with a weekly
  `resolution_only` settlement cadence. The new AI-infrastructure relative-
  return question has an ordinary 30-day active review schedule.
- SQLite integrity and cron health remain good. A pre-apply online backup is at
  `~/.superforecasting-agent/forecasting/backups/feedback-24h-2-preapply-20260722T111523Z.db`.

### Readiness and remaining work

Tester/pilot readiness remains green, while the scientific claim remains false.
There are still 24 calibration-eligible live binary scores. The report supplied
with this audit used a 30-score minimum, but the repository's canonical
`DEFAULT_MIN_LIVE_SCORES_FOR_CLAIM` is 100; this pass did not reduce that gate or
fabricate scores. The 18 `awaiting_human` tasks and the bounded normal reforecast
queue are now explicit operator/worker work rather than hidden liveness defects.

The repository remains a broad, user-owned dirty worktree. This pass did not
pretend to split or tag unrelated changes; deployment revision tagging remains
the next release-management action after the user chooses the intended commit
boundaries.

Validation for this pass:

```text
expanded worker/provider/tool regression set: 391 passed
exact full-suite regression rerun:               2 passed
ruff (all touched Python):                       passed
bash syntax + diff whitespace:                   passed
full forecasting suite:                        3,201 passed, 2 skipped
post-suite workflow/lifecycle regression:         58 passed
```

## Estimation-stage and review-accounting follow-up — 2026-07-21

The follow-up correctly identified reforecast execution as the new limiting
stage. The apparent source backlog was counting immutable observations rather
than independent judgments: 50 queued events represented only 11 questions, and
20 fresh Clacton events represented two questions. Processing each event with a
separate model call would have been slow, produced competing proposals against
one prior forecast, and repeated correlated evidence.

The estimator queue now coalesces every pending or expired-leased source event
that shares a question and prior forecast into one immutable batch. The hosted
estimator receives all persisted events, source snapshots, and watched-source
records; its artifact must cite every event ID. One valid estimate creates at
most one proposal and terminally reconciles every sibling task/event. Concurrent
claims are fenced per question, while expired sibling leases no longer block a
replacement worker. A narrow optional question filter supports exact operator
recovery without changing normal utility ordering.

Provider-boundary normalization now handles the response shapes observed in
production: nested `distribution` wrappers, interval arrays on distributional
questions, and binary wrappers using `probability`, `point_estimate`, `mean`,
`median`, or equivalent point keys. The prompt also explicitly requires one JSON
number for binary outcomes. Invalid shapes still fail retryably before creating
a model run, proposal, or forecast commit.

Refresh-generated `forecast_estimation_required` alerts now always have one
executable owner. If an immutable source task already exists, the specialized
estimator owns the question; otherwise refresh immediately enqueues a durable
normal-reforecast warning task. The warning worker suppresses duplicate generic
work while a source task is unfinished and coalesces repeated estimation alerts
for one question into one paid run. A completed source estimate—including an
immaterial judgment or reviewable proposal—retires the redundant generic
estimation alert and pending task. Historical repair connected all 26 existing
`estimation_required` review runs to concrete task IDs.

Scheduled-review accounting now separates:

- `alert_count` / `metadata.alert_ids`: unique alerts created by that run;
- `observed_alert_count` / `observed_alert_ids`: actionable alerts the run saw;
- `source_change_event_ids` / `estimator_task_ids`: executable follow-up owners.

The 4,450 historical run rows were repaired under
`alert_count_semantics=created_unique_v2`. The previous aggregate count of 20,157
mixed repeated and pre-existing alerts; the reconstructed unique-created total is
7,908. The most visible 447-alert run is now 12 created, 21 unique observed, and
11 linked estimator tasks. The old counts remain in `legacy_alert_count` for
audit. The recurrence tests no longer depend on the wall clock: their sweep and
evidence timestamps use one fixed, internally consistent timeline.

Live execution validated the complete path:

- the fresh 11-event vote-share batch and nine-event Farage batch each became one
  audited `reviewed_immaterial` judgment;
- all 29 remaining older pending source events were serviced as eight question
  batches;
- the source queue is now `578 processed / 15 failed / 0 pending`; the 15 failed
  observations are genuine external-source failures and already terminal;
- no fake forecast commit was created; two pre-existing pending proposals remain
  for ordinary human review;
- the urgent warning-task queue fell from 62 to 43 after 19 manual conditions
  were surfaced and terminally removed from the execution queue without closing
  their alerts; one bounded paid evidence pass then imported real evidence and
  resolved its selected alert;
- learned-error pilot blockers fell from 13 at the start of the reported period
  to four; the independent worker continues at its bounded cadence;
- every one of the 26 historical estimation-required runs has a task owner, and
  16 still-open generic estimation alerts remain durably queued for subsequent
  paid passes;
- SQLite integrity remains `ok`, and cron health remains healthy.

Online backups were created before each live repair:

- `feedback24h-followup-preapply-20260721T123632Z.db`;
- `review-alert-count-v2-preapply-20260721T134500Z.db`;
- `estimation-ownership-preapply-20260721T135500Z.db`.

Formal readiness remains intentionally conservative: 24 eligible live binary
scores against the canonical floor of 100, pilot checks 8/9, four learned-error
review blockers, `tester_handoff_ready=false`, and
`claim_live_superforecasting=false`. The earlier 30-score display was stale or a
non-default report threshold; production code and `forecast doctor` both use 100.
No threshold was reduced and no score was fabricated.

Final validation for this follow-up:

```text
forecasting full suite:  3,195 passed, 2 skipped
ruff:                    all touched Python files passed
diff check:              no whitespace errors
```

## 24-hour liveness remediation — 2026-07-21

The 24-hour follow-up confirmed that correctness was holding but throughput was
not: 20 confirmed resolutions had never reached their deterministic finalizer,
32 immutable source observations were waiting for estimation, 21 warning tasks
had exhausted rapid retries, 70 high-severity alerts were beyond SLO, and 13
learned-error reviews still blocked the pilot. The fixes preserve every existing
evidence/commit gate while making each backlog executable:

- Both recurring maintenance entry points now drain `finalize_resolution` tasks.
  The live residual 20 were scored and postmortemed exactly once; the queue is
  now zero.
- Warning triggers such as `trigger_fired:fred:*` route to paid reforecasting,
  not a deterministic re-poll that cannot resolve them. Required learned-error
  updates use the same paid route.
- Unavailable-source alerts no longer re-poll every watch on the question. The
  source monitor owns retry; the warning remains open with an explicit
  `source_monitor_retrying`/manual-repair disposition. Inactive sources close as
  obsolete. Generic failures back off exponentially instead of reaching five
  attempts in minutes. The live dead-letter count is now zero.
- Source estimation has its own transactional budget and cadence rather than
  waiting for unused warning capacity. Superseded events are closed before an
  estimator call, avoiding model spend that cannot affect current state.
- Learned-error review now has a bounded hosted worker. It persists the profile,
  current forecast, substantive assessment, and `reviewed_no_change` versus
  `update_required` decision through the existing model-run audit before closing
  an alert. A required update opens an ordinary paid reforecast alert; bare
  acknowledgement is not considered a review.
- Paid warning, source-estimator, and learned-error lanes default to one action
  every 30 minutes (up to 48/day each). This exceeds the observed arrival rate
  without putting a large serial agent batch inside one cron tick.
- The nightly self-check no longer duplicates estimator work. Its generated
  script was refreshed in place, and forecast cron scripts now have a 900-second
  ceiling instead of the 120-second limit that killed the prior healthy batch.
- Review cadence already differentiated work correctly and was retained:
  repeated `completed_no_change` runs back off to 2x/4x cadence, while deadlines
  inside seven days and 48 hours clamp to daily and twice-daily reviews.
- Live reconciliation also retired 29 legacy source-warning tasks whose exact
  event or source monitor already had ownership, plus 15 obsolete high-severity
  tasks attached to profile-level informational digests. This left the
  deterministic-critical backlog at zero, reduced open high-severity alerts
  from 70 to 55, and reduced the urgent queue to 61 without closing any
  actionable forecast alert. All 55 high-severity alerts have executable tasks;
  none is unowned.

Before live reconciliation, an online SQLite backup was created at
`~/.superforecasting-agent/forecasting/backups/feedback24h-preapply-20260721T105856Z.db`
and passed `PRAGMA integrity_check`.

Scientific readiness remains deliberately separate from operational recovery.
There are 41 eligible live scores, of which 24 are binary/Brier-scoreable, against
the formal floor of 100. `claim_live_superforecasting=false` remains correct. No
score was fabricated and no threshold was reduced; prospective settlements must
accrue the remaining independent outcomes.

The repaired generated scripts were exercised exactly as installed. Both now
complete successfully, `forecast_cron_health.healthy=true`, and their previous
120-second timeout errors are cleared. At the final live checkpoint there were
31 estimator-required source events, 11 learned-error review blockers, zero
dead letters, and zero deterministic-critical tasks. Fifteen genuine unavailable
source observations remain visible as external source failures; active source
monitors, rather than duplicate warning tasks, own their next checks.

The assessment now stands:

- **Code/test health:** strong and fully green.
- **Operational health:** executable and observable: cron is healthy, lifecycle
  finalization is current, and every queued event has one worker owner. The
  remaining queues are bounded work, not orphaned work.
- **Remaining concerns:** 15 external sources are still unavailable, 55
  high-severity reforecasts must drain, 31 source observations need estimation,
  and 11 learned-error reviews need substantive model-run records.
- **Live-superforecasting claim:** still not supported. The observed binary/Brier
  subset is 24; the current formal live-score readiness floor is 100 (the earlier
  30-score note was stale), with broader independent evidence still needed.

Final validation for this 24-hour remediation:

```text
forecasting full suite:                  3,192 passed, 2 skipped
focused worker/lifecycle control plane:    127 passed
ruff:                                      all targeted files passed
diff check:                                no whitespace errors
```

## Remediation implemented 2026-07-20

The production-state problems shared one systemic cause: local transition tests
existed, but the runtime did not enforce conservation and liveness across the
alert, source-event, task, schedule, and worker boundaries. A green suite could
therefore coexist with durable rows that no worker owned. The fixes below make
those boundaries explicit and expose their invariants in `forecast doctor` and
the TUI Operations cockpit.

| Feedback observation | Root cause | Implemented correction | Live state after repair |
|---|---|---|---|
| 314 stranded source events | Closing a linked alert completed only its task. The source event remained `pending`, so the three durable records diverged. | Alert closure now atomically transitions a linked pending/failed source event to `reconciled`, closes its task, and records the transition. Schema initialization idempotently repairs existing rows. | `stranded=0`; 315 events are explicitly reconciled as `alert_closed_elsewhere`. |
| 77 failed source tasks | The generic warning worker re-polled every source for a question after an immutable observation already existed, then applied one transient failure to every pending event for that question. No task had actually been claimed (`attempt_count=0`). | A deterministic router now consumes the exact persisted event/snapshot and moves it to the estimator lane without network access. Successfully observed, source-owned alerts awaiting estimation are excluded from the generic re-poll path; failed observations remain retryable by the warning worker. Event completion/defer APIs require exact event IDs. The migration recovered only successful immutable observations matching the legacy failure signature. | The legacy batch is gone. `17` valid observations are queued for bounded estimation; `14` remaining failed events are genuine open `watched_source_unavailable` observations, not poisoned successful events. |
| Unchanged carry-forward “commits” | Raw evidence that could not be deterministically re-pooled still created a new live snapshot at the old probability and reported `committed`. | Refresh now persists the evidence and model-run audit, opens `forecast_estimation_required`, returns `needs_estimation`, and creates no forecast snapshot. Only a deterministic re-pool or explicit estimator output can commit; estimator-confirmed zero delta is recorded as reviewed immaterial. | New carry-forwards cannot inflate forecast history or masquerade as fresh judgment. |
| Old high-severity work | Alerts had durable tasks and escalation labels, but no installed bounded warning worker; the cockpit also called assigned work “unclaimed.” | The default routine installs the 30-minute warning automode with transactional leases. The current design gives paid warning, exact-event estimation, and learned-error review independent one-per-30-minute budgets, so one backlog cannot consume another lane's capacity. The cockpit distinguishes awaiting execution from genuinely unowned work. | The worker is installed and firing. Current reconciliation reduced open high-severity work from 70 to 55; all 55 have executable tasks and none is unowned. |
| 203 active questions without schedules | `resolution_only` disabled all schedules. Classification labelled 202 questions as settlement-only but supplied no settlement mechanism; the one monitor-only question intentionally had a watch but no review cadence. | Service-mode invariants are now executable: actively serviced requires a review schedule, monitor-only requires a watch, resolution-only gets a lightweight deadline/weekly settlement schedule with auto-score/postmortem, and archived gets no work. Resolution-only runs suppress staleness/evidence refresh noise. | `service_mode_coverage_gaps=0`; all 202 resolution-only questions have settlement schedules. The sole active question without a schedule is the intentional monitor-only case. |
| Live-superforecasting claim unsupported | Operational throughput cannot substitute for independent, foreknowledge-proof resolved outcomes. The earlier “30” note also understated the current formal readiness floor. | No scores were fabricated and no gate was weakened. Settlement coverage now makes due outcomes visible and scoreable; doctor continues to block the claim and reports operational health separately from scientific readiness. | `41` eligible live scores total, of which `24` are binary/Brier-scoreable. The formal live-score requirement remains `100`, so `claim_live_superforecasting=false` is still correct. |

### Additional hardening from the second pass

- The nightly script is regenerated when its job already exists, so installing a
  feature no longer leaves a permanently stale generated script. It includes
  guarded utility calibration, scoring, postmortems, thesis aggregation, lesson
  synthesis, and market-model refresh. Source estimation now belongs solely to
  the continuous independent estimator lane, avoiding duplicate claims and long
  nightly batches.
- Source-event recovery is deliberately shape-restricted: only a successful
  immutable observation, a legacy `source_failure`, zero claims, an active
  question, and an open alert can be returned to the queue. Genuine unavailable
  sources remain failed and visible until a later successful check.
- `forecast doctor` now includes an operational-health gate for stranded source
  events, open source failures, service-mode coverage gaps, unowned high-severity
  work, and the presence of the warning worker. Scientific readiness remains a
  separate gate.
- The Operations cockpit now renders source lifecycle counts and the oldest
  pending event, plus service-mode invariant gaps. It no longer treats an assigned
  escalation as unowned work.
- Before applying the live migration, an online SQLite backup was created at
  `~/.superforecasting-agent/forecasting/backups/feedback03-preapply-20260720T123301Z.db`
  and passed `PRAGMA integrity_check`.
- The long-running TUI remained open while its Python sidecar was restarted in
  place. The replacement sidecar loaded the new settlement semantics and processed
  the remaining due resolution-only schedules without creating stale/no-evidence
  alerts; 16 rollout-noise alerts emitted by the old in-memory code were explicitly
  closed as `migration_cleanup:resolution_only_staleness_noise`.
- A newly unavailable source remains owned by the retryable warning path even
  while its durable event is pending; only successful observations already queued
  for estimation are suppressed from redundant re-fetch. This edge was found by
  the final full-suite run and is now regression-tested.
- Long review sweeps now persist `running` and start state before doing work, then
  a distinct completion timestamp and duration afterward. The 22-question live
  settlement sweep took 271 seconds; it was healthy, but the old terminal-only
  checkpoint made it appear stale until completion. `forecast doctor` can now
  distinguish a slow in-flight sweep from a dead ticker.
- Warning automode had dormant state-file helpers but never wrote them, leaving a
  live agent-backed run invisible until cron completion. The worker now checkpoints
  start/running/completion and terminal free/paid counts; cron status and doctor
  expose that runtime state. A live overlap test confirmed the transactional lease:
  the scheduled worker processed 14 free retries, skipped paid work already owned
  by the manual worker, completed `ok`, and advanced its next run without a second
  paid spend.

### Final validation

Validation was repeated after the source-failure edge fix and liveness hardening:

```text
forecasting:  3,186 passed, 2 skipped, 0 failed
TUI:          1,932 passed, 4 skipped, 0 failed
ruff:         all targeted files passed
TypeScript:   type-check passed
ESLint:       0 errors (54 pre-existing warnings outside this change)
diff check:   no whitespace errors
```

The final systemic conclusion is that queue health must be tested as a conserved
end-to-end state machine, not inferred from green component tests. Every durable
alert/event/task must have one current owner, one terminal disposition, and an
observable worker; every active question must have an executable service-mode
invariant; and audit history must distinguish observation, estimation, and commit.
The router, atomic reconciliation, scheduler invariants, bounded workers, doctor
gates, and in-flight checkpoints now enforce and expose those properties.
