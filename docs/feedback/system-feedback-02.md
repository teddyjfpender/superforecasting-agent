> **Status note (2026-07-17):** This document's original verdict is the
> pre-remediation audit. It is preserved below as the problem statement. See
> [Remediation verification — 2026-07-17](#remediation-verification--2026-07-17)
> for the current implementation, live-ledger state, tests, and remaining gate.

# Verdict

**Yes, it feels materially better. No, it does not yet meet the requirements fully.**

The changes address several of the most important architectural defects rather than merely hiding the alert count. The live ledger now shows genuine operational improvement. However, there are still correctness gaps, three failing forecasting tests, an unexercised new workflow in production, incomplete active-book coverage, stale high-severity work, and insufficient prospective evidence for a live-superforecasting claim.

My overall assessment:

- **Operational architecture:** substantially improved, but not production-complete.
- **Current live operations:** markedly healthier, but still not sustainably managed across the whole active book.
- **Forecasting/scientific readiness:** essentially unchanged; the formal claim remains blocked.
- **“Meets requirements fully”:** **No.**

## What I inspected

I checked:

- the current branch and uncommitted diff;
- the affected control-plane implementation;
- the live SQLite ledger;
- database constraints and new workflow tables;
- targeted and full forecasting tests;
- doctor, pilot, calibration, and readiness reports;
- the previously contaminated PPI score and correction records.

The current worktree is large: **170 modified or new files, with 4,243 insertions and 774 deletions**. The relevant new surfaces include:

- `forecasting/ledger/workflow.py`
- `forecasting/estimator_worker.py`
- source-change workflow changes;
- review leasing;
- lifecycle retirement;
- database uniqueness constraints;
- an operations cockpit;
- new targeted tests.

None of my verification work modified your files or ledger.

---

# What is clearly better

## 1. The alert situation improved dramatically

| Metric | Before | Current |
|---|---:|---:|
| Open alerts | 1,102 | **229** |
| Open distinct keys | 1,006 | **229** |
| High severity | 95 | **62** |
| Warning | 989 | **148** |
| Median closed latency | 14.5 hours | **7.1 hours** |
| Seven-day net flow | +634 alerts | **−67 alerts** |

The open backlog dropped by approximately **79%**. More importantly, all 229 open alerts now have unique `alert_key` values: the old condition where duplicate open rows inflated the queue is gone.

The queue is currently shrinking rather than growing:

- Last 24 hours: 526 arrivals, 579 closures, net **−53**
- Last seven days: 3,088 arrivals, 3,155 closures, net **−67**

That is a real improvement, not a cosmetic dashboard change.

## 2. Resolved-question workload was actually retired

This was the worst allocation failure in the old system.

Before:

- 957 enabled schedules on resolved questions;
- 88 open question alerts attached to resolved questions;
- most recent review execution was being spent on resolved questions.

Now the live residual counts for resolved questions are:

- enabled schedules: **0**
- active watches: **0**
- enabled autopilot policies: **0**
- open alerts: **0**

All **957 resolved-question schedules were disabled**. This is the clearest operational success in the update.

The new resolution path also retires:

- schedules;
- watched sources;
- autopilot policies;
- pending operational tasks;
- source-change events;
- relevant alerts.

That lifecycle is covered by a dedicated test.

## 3. The lost source-change handoff is fixed architecturally

The previous failure was:

```text
detect source change
→ advance source signature
→ autopilot checks later
→ no longer sees a change
→ skips
```

The new implementation creates a durable `source_change_event` and operational task in the same transactional path as the signature update. The work survives after source polling returns.

This is a substantive fix.

The new event/task architecture includes:

- source-change events;
- event transitions;
- operational tasks;
- task attempts;
- claims and leases;
- ownership;
- retries and dead-lettering;
- utility components;
- alert/event/task reconciliation.

The targeted source-workflow tests pass.

## 4. The dangerous implicit unchanged-probability fallback is fixed

Previously, autopilot could detect a change and create a proposal carrying the current probability because no estimator had actually supplied a new estimate.

Now, when evidence is material but no explicit estimate exists, the run becomes:

```text
needs_estimation
```

It does not silently manufacture a proposal from the prior forecast.

That is a major safety improvement.

## 5. Database-enforced uniqueness is now present

I verified the actual live SQLite indexes, not just the migration code.

The database now enforces uniqueness for:

- open alert identity;
- enabled schedule identity;
- active watched-source identity;
- enabled autopilot policy per question.

The alert concurrency test launches 16 concurrent enqueues and verifies that they converge to one row with `seen_count == 16`.

This fixes the earlier “Python check then insert” race for the principal object classes.

## 6. Review workers now claim work transactionally

Scheduled reviews now have:

- `lease_owner`;
- `lease_expires_at`;
- `attempt_count`;
- conditional claim updates;
- owner-checked completion;
- batch limits;
- wall-clock limits;
- per-review error isolation.

Two ledger instances are tested against each other, and only one can claim a given review.

This is materially better than the former unclaimed full-table sweep.

## 7. Future review statuses are more truthful

The code now distinguishes statuses such as:

- `completed_no_change`
- `evidence_imported`
- `proposal_created`
- `forecast_committed`
- `resolved_and_scored`
- `partial_source_failure`
- `failed_retryable`

It also records:

- refresh status;
- refresh errors;
- review errors;
- worker identity;
- lease duration;
- adaptive cadence state.

That fixes the old implementation at the code level for future runs.

## 8. Paid-budget coordination moved into SQLite

The paid warning-automation path now uses a transactional database lease instead of relying on the unsafe JSON timing file.

The old JSON helpers still exist, but the current paid execution path claims and releases `automation_budget_leases` transactionally.

---

# What is only partially fixed

## 1. Long-running reviews can still execute twice

The initial review claim is cross-process safe, but there is no heartbeat around the potentially long external callback.

The sequence can still be:

```text
worker A claims review
→ callback runs longer than lease
→ lease expires
→ worker B reclaims review
→ both perform external/model work
```

The final owner check prevents both workers from recording successful completion, but it does not prevent duplicate external work or duplicate side effects that occur before finalization.

This needs one of:

- periodic lease renewal;
- per-item heartbeat;
- sufficiently short claim batches with claim-on-demand;
- fencing tokens checked by downstream writes.

Also, the implementation claims several rows before processing them serially. Later rows can consume much of their lease while waiting behind earlier rows.

**Verdict: partial, not complete cross-process exclusivity.**

## 2. Explicit zero-delta proposals remain possible

The implicit fallback is gone, but if an estimator explicitly supplies a probability equal to the current probability, the code can still create a proposal.

A same-value estimate should normally become:

```text
reviewed_immaterial
```

rather than another forecast-update proposal.

There should be a configurable minimum material probability delta, with an exception for cases where the evidence or rationale changed enough to justify a new auditable snapshot.

**Verdict: dangerous default fixed; categorical unchanged-proposal prevention incomplete.**

## 3. Resolution teardown does not enforce a hard “no post-resolution write” invariant

Resolving a question now disables its normal machinery. However:

- an already-running review cannot be revoked;
- snapshot creation does not universally reject resolved questions;
- some programmatic snapshot paths do not enable the stronger resolved-question hooks.

Therefore an in-flight worker or direct programmatic path may still commit a post-resolution snapshot.

Lifecycle teardown should be backed by a hard commit-time check:

```text
if question.status == resolved:
    reject snapshot unless explicit correction/backfill mode
```

**Verdict: lifecycle cleanup is excellent; transaction-bound finality is incomplete.**

## 4. Operational tasks do not yet own all automated work

The new `operational_tasks` infrastructure is strong, but not every warning path uses it.

In particular, the free warning-resolution tier runs every tick without a global or per-alert work lease. Concurrent cron processes could therefore execute the same remediation action even though alert-row creation itself is deduplicated.

The paid tier has a bucket-wide budget lease, but that is not equivalent to per-alert task ownership.

**Verdict: durable task plane exists, but adoption is incomplete.**

## 5. Crash-safe budget accounting remains imperfect

The SQLite lease prevents simultaneous paid sweeps. But if a worker:

1. spends externally;
2. crashes before releasing the lease and recording spend;
3. waits until lease expiry;

another worker may spend again without the prior expense having been durably charged.

A stronger design would reserve budget before execution and reconcile actual spend afterward, or record per-item spending with an idempotency key.

**Verdict: concurrency fixed; crash accounting partial.**

## 6. Report caps are still misleading

The doctor report currently says:

```text
scheduled_review_run_count: 1000
```

The live database contains **4,206 scheduled-review runs**.

So the same historical reporting problem remains: the count is still derived from a capped list in at least this reporting path.

The dashboard changes distinguish some true totals from rendered details, but the doctor/pilot reporting path still understates schedule-run history. Some views also load full collections before slicing their display output, so rendering is capped while query/materialization cost is not.

**Verdict: partially fixed in the dashboard, not fixed system-wide.**

---

# Live operations still have important gaps

## 1. Half the active book remains uncovered

There are 385 active questions.

Only:

- 181 active questions have enabled schedules;
- **204 active questions have no enabled schedule**.

Turning off obsolete resolved schedules was correct, but the capacity has not yet been reallocated across the active portfolio.

The review queue is now **341 questions**, up from the previous snapshot of 323. That does not necessarily indicate regression—the new queue logic may surface conditions more honestly—but it means the active book is still not under reliable maintenance.

This needs an explicit portfolio decision:

- actively serviced;
- monitor-only;
- resolution-only;
- archived.

Do not blindly schedule all 204 uncovered questions. First decide which questions deserve active maintenance and archive or downgrade the remainder.

## 2. High-severity alerts are still older than routine work

The current open-alert median age is about 3.4 days, an improvement from 4.6 days.

But high-severity alerts have a median age of approximately **17.1 days**, essentially unchanged from the previous 16.9-day result.

That means prioritization is still failing the most consequential alerts. High severity is currently a label, not an enforced SLA.

I would require:

- critical/high claimed within a short fixed interval;
- oldest-high-first ordering;
- escalation when unclaimed;
- explicit owner;
- a dead-letter or human-escalation path;
- cockpit reporting for high-severity SLA breaches.

## 3. Six proposals remain abandoned

The six existing forecast-update proposals remain pending, now approximately 3.4 days old. None has been approved or rejected, and autopilot has not run since July 13.

Proposal expiration logic now exists, but the current queue has not been cleared.

A proposal system needs:

- review SLA;
- automatic expiration;
- refresh-before-approval when stale;
- explicit rejected/immaterial disposition;
- escalation for high-impact proposals.

## 4. The new event/task pipeline has not yet processed live work

The live database currently has:

- source-change events: **0**
- event transitions: **0**
- operational tasks: **0**
- task attempts: **0**

That is not itself a bug—the tables are new and may not have encountered a fresh source transition—but it means the strongest new architecture has been validated by tests, not yet by actual live throughput.

Before declaring it operationally complete, I would require a canary proving:

```text
source change
→ source-change event
→ task claim
→ estimation
→ proposal/immaterial disposition
→ event reconciliation
→ alert closure
```

including retry and worker-crash scenarios.

## 5. Historical review utility is still poor

The live database has 4,206 scheduled-review runs. They remain historically marked `completed` because the richer statuses apply only to new runs.

Aggregate outputs are:

- 13,995 alert detections;
- 6,053 learning reviews;
- **0 scores**;
- **2 postmortems**.

Since the previous snapshot, 63 runs were added:

- 14 active-question runs;
- 49 resolved-question runs before teardown took effect;
- 823 alert detections;
- 181 learning reviews;
- no scores;
- no postmortems.

The resolved-question waste appears to have stopped, which is good. But there is not yet enough post-change history to show that reviews now produce materially useful forecast maintenance.

---

# Test verdict

## Targeted control-plane tests

The focused set passed:

- source-change workflow;
- review leases;
- resolved lifecycle teardown;
- alert lifecycle;
- schedule deduplication;
- warning automode;
- warning dispatch;
- policyless material drain.

Result:

```text
111 passed
0 failed
```

That is strong evidence that the main intended mechanisms are implemented.

## Full forecasting suite

The full forecasting directory result was:

```text
3,164 passed
3 failed
2 skipped
3,169 collected
```

I independently reran all three failures with `scripts/run_tests.sh`; all three reproduced.

### Failure 1: free-tier warning closes without a persisted score

```text
test_drain_resolves_only_the_free_tier_through_real_work
```

The test observes:

- the `score_due` alert closes;
- no score record is persisted.

This directly violates the stated invariant:

> No bare acknowledgement without real work.

This is substantive and should block a “fully meets requirements” verdict.

### Failure 2: scheduled-review result ordering assumption

```text
test_forecast_ledger_tool_self_check_and_schedule_filter_by_confidence
```

The expected alert is not in `scheduled_review_results[0]`. Similar updated tests now locate a result by schedule ID rather than assuming it is first.

This may be a brittle test rather than a product defect, but it must be resolved and the intended result-selection contract made explicit.

### Failure 3: pilot-bundle fixture conflicts with lifecycle teardown

```text
test_forecast_cli_pilot_bundle_outputs_handoff_packet
```

The test resolves a question before running its scheduled review. The new lifecycle teardown correctly disables the schedule, so the expected review-run artifact is never created, and pilot status remains `collecting_pilot_evidence`.

The test fixture likely needs to run the review before resolution. Still, the suite is red until that contract is repaired.

## Missing concurrency coverage

The new tests are useful but do not fully cover:

- source polling by concurrent processes;
- lease expiration during a long review;
- lease heartbeat;
- worker crash after claim;
- concurrent resolution versus in-flight review;
- post-resolution snapshot rejection;
- concurrent budget claims and crash-after-spend;
- concurrent schedule creation;
- concurrent policy/watch insertion;
- close-versus-enqueue alert races;
- source recovery closing a failure alert;
- zero-delta estimator disposition.

---

# Scientific/readiness verdict

This portion did not materially improve because operational engineering does not create prospective scored evidence.

The current formal report remains:

```text
doctor_status: needs_tester_pilot_artifacts
tester_handoff_ready: false
claim_live_superforecasting: false
evidence verdict: insufficient_live_evidence
```

The pilot report remains:

```text
pilot_status: collecting_pilot_evidence
checks passed: 8 of 9
```

The failed pilot check is:

- 19 open learned-error-profile review alerts;
- required: 0.

## Live evidence remains below the formal minimum

For comparable live binary forecasts:

- observed: **23**
- formal minimum: **30**
- remaining: **7**
- mean live Brier: **0.04377**

The backtest evidence remains substantial:

- 485 agent-protocol scored cases;
- 20 leakage-free runs;
- 9 distinct datasets;
- four external source families;
- nine runs beating the best available baseline.

But the live sample remains:

- small;
- heavily weather-concentrated;
- vulnerable to a single severe overconfident miss;
- insufficient for a defensible live-superforecasting claim.

Even reaching 30 is only the tool’s minimum gate. My scientific standard remains closer to 100–200 clean prospective binary forecasts with domain/horizon breadth, predeclared cutoffs, paired baselines, confidence intervals, and high-confidence-miss audits.

---

# One unresolved data-integrity problem

The contaminated June PPI score is still calibration-eligible:

- score: `sc_c61620cfd987`
- `calibration_eligible = true`
- calibration weight: 1.0
- quarantine reason: null

Two correction records exist, but both remain merely:

```text
status: proposed
```

They have not been applied.

Because the scored forecast was committed after the official release became public, this score should not contribute to live calibration. Until the correction is actually applied, cutoff integrity is not fully enforced operationally.

---

# Requirement-by-requirement assessment

| Requirement | Verdict |
|---|---|
| Durable source-trigger records with old/new snapshots | **Fixed in code; not yet exercised live** |
| Estimator produces explicit output before proposal | **Mostly fixed** |
| Separate source observation from forecast completion | **Fixed architecturally** |
| Transactional review/task claims | **Partial—no long-work heartbeat/fencing** |
| Bounded batches and wall-clock limits | **Fixed for review selection** |
| Retries, attempts, dead-lettering | **Fixed for operational tasks; not universal** |
| Database-enforced idempotency | **Fixed for principal object classes** |
| Resolved-question lifecycle retirement | **Mostly fixed; post-resolution write invariant remains** |
| Event-driven reconciliation | **Implemented for new source workflow; not universal** |
| Durable ownership/state/SLA/disposition | **Partial** |
| Truthful operational statuses | **Fixed for future review runs; legacy/reporting remains misleading** |
| Transactional paid-budget coordination | **Mostly fixed; crash accounting remains** |
| Alert arrival below service rate | **Currently passes over 24h and 7d** |
| High severity handled faster than routine work | **Not fixed** |
| Active-question maintenance coverage | **Not fixed—204 active questions uncovered** |
| Proposal queue governed by SLA | **Not fixed—six stale proposals** |
| Useful-work yield proven in production | **Not yet demonstrated** |
| Accurate uncapped summary counts | **Not fixed system-wide** |
| Full forecasting test suite green | **Not met—three failures** |
| PPI leakage correction applied | **Not fixed** |
| Tester handoff ready | **No** |
| Live-superforecasting evidence sufficient | **No** |

# Bottom line

You fixed enough that I would no longer describe the system as simply flying blind. It now has the beginnings of a credible flight-management system:

- durable source events;
- operational tasks;
- leases;
- uniqueness constraints;
- lifecycle teardown;
- better alert identity;
- shrinking backlog;
- truthful future review statuses.

That is a substantial improvement.

But I would not call it fully ready yet. The release-blocking items are:

1. fix the free-tier “alert closed without persisted score” failure;
2. resolve the other two forecasting-suite failures;
3. add heartbeat/fencing for long-running leased work;
4. enforce a hard no-post-resolution-snapshot invariant;
5. convert explicit zero-delta estimates to an immaterial disposition;
6. put free-tier warning actions behind task-level claims;
7. fix doctor/pilot run counts so 4,206 is not reported as 1,000;
8. classify or cover the 204 unscheduled active questions;
9. clear or expire the six stale proposals;
10. enforce high-severity SLAs;
11. run a live canary through the new source-event/task/estimator pipeline;
12. apply the PPI calibration exclusion;
13. clear the 19 learned-error review alerts;
14. accumulate the missing prospective live evidence.

**My score:** operationally, this has moved from roughly **“unsafe and misallocated” to “promising but still pre-release.”** The architectural direction now meets most of my requirements; the complete working system does not yet.

---

# Remediation verification — 2026-07-17

## Current verdict

The engineering blockers identified above have been implemented and tested.
The tester pilot is now ready, but the system still correctly refuses a live
superforecasting claim because the prospective cohort is too small.

```text
doctor_status: tester_handoff_ready_live_claim_unproven
tester_handoff_ready: true
pilot_status: pilot_exit_ready
pilot_checks: 9/9
claim_live_superforecasting: false
```

This is the intended separation of concerns:

- operational readiness is now evidenced;
- forecasting superiority remains unproven until genuine prospective outcomes
  resolve;
- no historical, market-nightly, exploratory, post-release, or fabricated
  result may be used to fill that gap.

## Release-blocker disposition

| # | Original blocker | Current disposition | Authoritative evidence |
|---:|---|---|---|
| 1 | Free-tier alert could close without a score | **Fixed** | Resolution now persists the score before lifecycle teardown closes `score_due`; regression coverage passes in the full forecasting suite. |
| 2 | Two other forecasting failures | **Fixed** | Review-result selection no longer assumes list position, and the pilot fixture creates review history before resolution teardown. Full result: **3,180 passed, 2 skipped, 2 deselected**. |
| 3 | No heartbeat/fencing for long reviews | **Fixed** | `forecasting/ledger/reviews.py` claims one item on demand, renews the lease in a heartbeat thread, fences renewal/finalization with `attempt_count`, and abandons writes after lease loss. Concurrent, long-callback, and lease-loss tests pass. |
| 4 | Post-resolution snapshots still possible | **Fixed** | `create_snapshot()` rejects resolved questions at commit time. Only explicit correction/historical replay paths can opt into `allow_resolved_backfill=True`; normal callers cannot silently bypass finality. |
| 5 | Explicit zero-delta proposals | **Fixed** | Equal/current probability estimates become `reviewed_immaterial`; the source event and alert reconcile without creating a proposal. |
| 6 | Warning automation lacked task ownership | **Fixed** | Every mutating warning action claims a durable per-alert operational task first. Another worker receives `claimed_elsewhere`; success, surfaced work, retry, and failure are persisted as task attempts. |
| 7 | Capped/misleading report totals | **Fixed** | Pilot/doctor summary counts are exact SQL aggregates. Live doctor reports **4,279** scheduled-review runs, not a capped 1,000-row list. Pilot-report generation is approximately 0.2 seconds on the live ledger. |
| 8 | 204 active questions unclassified/uncovered | **Fixed as a portfolio decision** | All active questions have an explicit service mode. Current active book: **178 actively serviced, 1 monitor-only, 202 resolution-only, 0 unclassified**. Resolution-only is deliberate and is not misreported as missing maintenance. |
| 9 | Six stale proposals | **Fixed** | All six were expired. Expiry now also closes the proposal alert and rejects/reconciles its linked source event. Live pending proposal count: **0**. |
| 10 | High severity had no enforced SLA | **Control fixed; historical work remains open** | High/critical alerts create urgent durable tasks with due times, oldest-first selection, explicit escalation owner, and cockpit breach reporting. All **59** current high tasks are assigned and escalated; overdue-but-unescalated count is **0**. They remain open until real research/operator work occurs—escalation is not treated as resolution. |
| 11 | New source workflow unexercised live | **Fixed and canaried** | Live canary `fq_67240f394064` traversed change detection, event/task creation, malformed-estimator retry, worker lease expiry, recovery, zero-delta `reviewed_immaterial`, reconciliation, no proposal, and archive. Task `ot_808d5b62f493` has attempts `failed_retrying`, `lease_expired`, and `reviewed_immaterial`. The reproducible runner is `scripts/forecast_workflow_canary.py`. |
| 12 | June PPI leakage correction unapplied | **Fixed** | Correction `fc_bc805dcad823` is `applied`; sibling correction is `rejected`. Score `sc_c61620cfd987` has `calibration_eligible=0`, weight `0.0`, and an explicit post-release exclusion note. |
| 13 | Nineteen learned-error review alerts | **Fixed** | Reviews now persist a `learned_error_profile_review` model run with profiles, recurring errors, current forecast, diagnostics, assessment, reviewer, and decision. The original 19 alerts were resolved through substantive review/resolution. Pilot-gating open learned-error alert count: **0**. |
| 14 | Missing prospective live evidence | **Still externally pending** | The clean comparable live cohort increased from **23 to 24**. The original 30-case milestone still needs 6 outcomes; the current formal scientific gate has been strengthened to **100**, so doctor reports 24/100 and 76 remaining. No code or ledger mutation can truthfully manufacture prospective outcomes. |

## Live operational verification

The live ledger was backed up before remediation to:

```text
~/.superforecasting-agent/forecasting/backups/feedback02-preapply-20260717T130024Z.db
```

The verified post-remediation state was backed up to:

```text
~/.superforecasting-agent/forecasting/backups/feedback02-postapply-20260717.db
~/.superforecasting-agent/forecasting/backups/feedback02-final-20260717.db
```

The live ledger and both post-remediation backups pass
`PRAGMA integrity_check`.

Post-remediation checks against
`~/.superforecasting-agent/forecasting/forecasting.db` show:

| Invariant | Current value |
|---|---:|
| Database integrity | `ok` |
| Active questions | 381 |
| Active questions without a service mode | **0** |
| Pending proposals | **0** |
| Pilot-gating learned-error alerts | **0** |
| Scheduled-review runs | **4,279** |
| Source-change events | 325 |
| Operational tasks | 416 |
| Pending tasks linked to closed alerts | **0** |
| Leased tasks left by verification | **0** |
| High/critical tasks without escalation after SLA | **0** |

The normal zero-token warning sweep was also exercised against live state. It
claimed all 21 eligible watched-source alerts through durable tasks. Because
the unavailable sources supplied no real gated work, all 21 alerts remained
open and their tasks became `failed_retrying`. No alert was bare-acknowledged
and no lease was leaked. That is the required failure behavior.

The final audit also found one genuinely due distribution forecast. The
[official NHC 2026 advisory archive](https://www.nhc.noaa.gov/archive/2026/)
showed Tropical Storm Arthur as the sole named Atlantic storm through July 15.
Question `fq_4adaccf7b68e` was resolved to 1, scored with discrete CRPS, and
given postmortem `pm_18a1ba8d99d3` plus a calibration lesson. Doctor correctly
did **not** count this distribution score toward the comparable binary Brier
cohort.

## Verification commands and results

```text
ruff check .
  All checks passed

pytest -q -n 0 tests/forecasting
  3180 passed, 2 skipped, 2 deselected

focused workflow/control-plane regression set
  117 passed

ui-tui: npm run type-check
  passed

ui-tui: npm run lint
  0 errors, 54 warnings

ui-tui: npm test -- --run
  1932 passed, 4 skipped

ui-tui: npm run build
  passed
```

The 54 ESLint warnings are repository-wide React compiler/hook warnings, not
lint errors; none is emitted by the new operations cockpit. They remain
visible rather than being suppressed.

## Remaining work

There is no remaining engineering shortcut that can satisfy the evidence
requirement. The active prospective questions must resolve naturally, then run
through resolution, scoring, postmortem, and calibration review. Until the
formal gate passes, public/operator output must continue to say:

```text
tester_handoff_ready: true
claim_live_superforecasting: false
readiness_verdict: insufficient_live_evidence
```

Historical high-severity alerts also remain assigned to human owners. The SLA
control is now enforced, but the underlying research and portfolio judgments
must be completed rather than auto-acknowledged. The operations cockpit is the
authoritative queue for that work.
