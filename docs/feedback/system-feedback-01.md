Your intuition is correct. From inside the machinery, this does **not** look like a system that merely needs a faster warning-drain loop. It looks like a forecasting desk whose **control plane has not caught up with the sophistication of its forecasting components**.

There are many capable parts—source adapters, ledgers, evidence snapshots, schedules, warning automation, autopilot policies, panels, scoring, postmortems—but they are not yet connected by a reliable, prioritized, transactional workflow.

The system is producing activity faster than it produces resolved state.

## Executive diagnosis

At the read-only operational snapshot:

- **1,102 alerts were open**
  - 95 high severity
  - 989 warnings
  - 18 informational
- In the previous seven days:
  - approximately **2,941 alerts arrived**
  - approximately **2,307 closed**
  - backlog increased by roughly **634**
- Open-alert median age was **4.6 days**
- High-severity median age was **16.9 days**
- The system has **1,140 enabled review schedules**
  - **957 are attached to resolved questions**
  - only 183 cover active questions
  - **204 active questions have no enabled review schedule**
- Of 2,498 scheduled-review runs in the preceding week:
  - **2,270 ran against resolved questions**
- There are 73 autopilot runs:
  - 66 skipped
  - 6 successful
  - 1 partial
- Six forecast-update proposals are pending; none has been approved or rejected.
- The largest open-alert category is `new_evidence:*`, with **765 alerts**.

That is the essential picture:

> The system is spending most of its review capacity looking backward while much of the active book is not covered properly.

This is not primarily a compute-capacity problem. It is a **work-allocation, lifecycle, and state-transition problem**.

---

# The most serious defect: the automatic forecast loop is not actually closed

The expected autonomous loop is:

```text
source changes
    → detect material evidence
    → estimate its effect
    → produce revised probability
    → validate update
    → propose or commit
    → close the associated work
```

The implemented path can instead behave like:

```text
source changes
    → source signature immediately updated
    → alert emitted
    → autopilot later checks source again
    → sees no change
    → skips
```

The relevant path crosses:

- `forecasting/ledger/watches.py:check_watched_sources`
- `forecasting/cron_runner.py:build_warning_runners`
- `forecasting/ledger/autopilot.py:run_autopilot`

The watch check advances `last_seen_signature` before the later autopilot worker consumes the change. The durable object passed forward is effectively “there was a change,” not the actual old and new observations. When autopilot re-polls, it often finds nothing new.

Even when a change reaches proposal generation, the default proposed probability may be the **current unchanged probability**, accompanied by an update rationale. That creates the appearance of forecast maintenance without necessarily performing a forecast.

This is the single most important architectural gap.

## What must replace it

A durable event should be created when a source changes:

```text
SourceChangeEvent
- event_id
- question_id
- watch_id
- prior_snapshot_id
- new_snapshot_id
- detected_at
- source_observation_time
- materiality
- claimed_at
- claim_owner
- processing_status
- resulting_proposal_id
- resulting_forecast_id
```

The estimator must consume that exact event—not re-discover the source change later.

The event should move through explicit states:

```text
detected
→ triaged
→ claimed
→ researched
→ estimated
→ proposed
→ committed/rejected
→ reconciled
```

A source observation is not “handled” merely because it was seen. It is handled only when the system records a defensible disposition:

- immaterial—no update;
- material—forecast updated;
- ambiguous—human/panel review;
- failed—retry scheduled;
- superseded—newer event processed.

That is the foundation of an above-the-clouds system.

---

# The system is confusing alerts, conditions, and work

Currently, alerts are doing too many jobs simultaneously:

1. reporting a condition;
2. serving as a task queue;
3. recording repeated detection;
4. indicating priority;
5. triggering automation;
6. acting as a historical audit log.

Those are different objects.

An alert such as “new evidence exists” is not itself the work. The work is:

> Evaluate evidence `ev_x` against forecast `fs_y`, determine materiality, and either update or record an immateriality disposition.

Likewise, “cadence overdue” is a condition, not a task. Repeatedly acknowledging and recreating the alert does not resolve the underlying scheduling problem.

## Needed separation

### Condition

A current fact about the system:

- forecast is stale;
- source is failing;
- question is past close;
- new evidence exists;
- assumption check is due.

### Task

A bounded executable unit:

- refresh three named sources;
- classify evidence materiality;
- rerun forecast;
- confirm resolution;
- review a proposal;
- perform postmortem.

### Alert

A notification that a condition or task requires attention.

### Event

An immutable record of something that happened:

- source changed;
- task failed;
- proposal created;
- forecast committed;
- question resolved.

The durable operational queue should contain **tasks**, not alerts.

Every task needs:

- owner or worker class;
- status;
- priority;
- due time;
- retry count;
- lease;
- idempotency key;
- linked question/event/alert;
- completion disposition;
- dead-letter state.

Alerts should become projections of task and condition state. They should not be the primary workflow database.

---

# The system is working on the wrong portfolio

The most striking operational imbalance is:

- **957 enabled schedules belong to resolved questions**
- **204 active questions lack enabled schedules**

This is almost the inverse of the desired allocation.

The previous week recorded 2,498 review runs, of which 2,270 were against resolved questions. Those obsolete runs generated thousands of alerts and learning reviews while active questions remained stale or uncovered.

## Immediate lifecycle rule

When a question resolves:

1. disable its recurring forecast-review schedule;
2. disable its autopilot policy;
3. deactivate policy-owned watches, except explicit resolver/audit watches;
4. reconcile its open stale/new-evidence/update alerts;
5. run score/postmortem/lesson tasks exactly once;
6. move it to a low-frequency resolution-correction watch only when needed.

This should be transactional and automatic.

A resolved question should not remain in the same operational lifecycle as an active forecast.

---

# More workers would currently make the system worse

It is tempting to respond to a large queue by adding concurrency. That would be dangerous before fixing the state model.

Several key operations currently use patterns like:

```text
SELECT due work
process it
UPDATE afterward
```

There is no durable cross-process claim or lease for scheduled reviews. Gateway and cron processes can therefore see the same due work.

Other idempotency checks are enforced with Python “check then insert” logic rather than database constraints. This allows concurrent producers to create duplicates.

Examples include:

- one open alert per logical condition;
- one enabled schedule per schedule key;
- one active autopilot policy per question;
- one active watched source per source identity.

Proposal approval also has a repeat-commit race: a proposal can create a snapshot before its status is atomically transitioned out of pending.

Adding more workers now could produce:

- duplicate alerts;
- duplicate source fetches;
- duplicate schedules;
- duplicate watches;
- duplicate forecast snapshots;
- conflicting autopilot policies;
- repeated paid model calls.

## Required execution primitive

Every worker should claim bounded work transactionally:

```sql
UPDATE work_items
SET status = 'running',
    lease_owner = ?,
    lease_expires_at = ?
WHERE id IN (
    SELECT id
    FROM work_items
    WHERE status = 'pending'
      AND available_at <= CURRENT_TIMESTAMP
    ORDER BY priority DESC, available_at ASC
    LIMIT ?
)
RETURNING *;
```

The system needs:

- lease expiration;
- heartbeat/renewal;
- retry policy;
- maximum attempts;
- dead-letter queue;
- idempotency key;
- compare-and-swap state transitions;
- transactional linkage between a proposal and its resulting snapshot.

Only after that should concurrency be increased.

---

# Alert identity and storm control are inadequate

The ledger contained:

- 9,328 historical alert rows;
- only 4,084 distinct logical `(scope, reference, reason)` keys;
- 5,244 excess rows;
- 26,835 total detections through `seen_count`.

One domain-error profile had 97 simultaneously open alerts for effectively the same condition. One of them had been detected 2,337 times. Several cadence-overdue conditions had each been rediscovered 237 times.

That is not useful vigilance. It is an alert storm.

## Needed identity model

Alert identity should not include volatile text. It should use a normalized key:

```text
alert_key =
    condition_type
    + scope_type
    + scope_id
    + object_id/version where relevant
```

Examples:

```text
new_evidence:question_id:evidence_id
source_failed:watch_id
cadence_overdue:schedule_id
domain_error_profile:profile_id:question_id
resolution_due:question_id
```

A database-enforced partial unique index should guarantee one open alert per key.

Repeated detection should update:

- `last_seen_at`;
- `seen_count`;
- latest severity;
- latest supporting event.

It should not create another parallel row.

## Storm controls

Each producer needs:

- cooldown;
- exponential backoff;
- maximum repeat frequency;
- escalation by age and impact;
- suppression when a higher-order task already exists;
- automatic reconciliation when the underlying condition disappears.

For example, 15 evidence items arriving for one question should generally produce one task:

> Review evidence batch `B`, containing 15 observations since forecast `fs_x`.

It should not create 15 separate operator-facing alerts unless the evidence has distinct urgent implications.

---

# “Acknowledged” is not the same as “resolved”

Operationally, all historical closure was through acknowledgement; no alerts were dismissed. `attempt_count` was effectively unused.

That means the system cannot reliably distinguish:

- successfully remediated;
- examined and found immaterial;
- suppressed as noise;
- acknowledged without action;
- automation attempted and failed;
- condition disappeared;
- superseded by newer work.

This undermines both learning and automation.

## Required dispositions

Every task or alert closure should carry one of:

```text
resolved_by_forecast_update
resolved_by_resolution
resolved_by_source_recovery
reviewed_immaterial
duplicate
superseded
false_positive
not_actionable
deferred
failed_retrying
failed_dead_letter
dismissed_by_policy
```

A warning must not close because the warning processor ran. It should close because the associated condition is no longer true or a documented disposition was recorded.

One concrete bug is that `autopilot_source_failed` is classified as bookkeeping. It can therefore be acknowledged without proving that the source recovered. Source-failure alerts should close only after a successful recheck or explicit source deactivation.

---

# Scheduled reviews need to become real jobs

The scheduler currently loads all due schedules and processes them serially without a proper bounded job queue. A failure in the wrong stage can abort later work, and run status is overly optimistic.

All 4,143 recorded scheduled-review runs were marked `completed`, yet collectively they produced:

- 13,172 alerts;
- 5,872 learning reviews;
- zero scores;
- two postmortems.

“Completed” therefore means “the function returned,” not “the forecast was maintained successfully.”

## Better review statuses

A review run should report:

```text
completed_no_change
evidence_imported
forecast_reestimated
proposal_created
forecast_committed
resolved_and_scored
partial_source_failure
failed_retryable
failed_terminal
skipped_resolved
skipped_not_due
```

And metrics such as:

- sources attempted/succeeded/failed;
- evidence items imported;
- evidence items deduplicated;
- material changes detected;
- probability movement;
- proposals created;
- forecasts committed;
- alerts closed;
- alerts generated;
- cost and latency;
- model/panel calls;
- cutoff violations prevented.

A “successful review” should be defined by useful output, not successful invocation.

---

# The desk needs economic prioritization, not FIFO warning draining

Not all forecasts deserve equal attention.

The correct ordering should reflect expected decision value:

```text
priority ≈
impact
× urgency
× probability of material movement
× information value
× resolution proximity
÷ expected processing cost
```

High-priority examples:

- high-impact question near decision deadline;
- executable trigger crossed;
- strong new disconfirming evidence;
- resolution source has published;
- active forecast lacks a snapshot;
- high-confidence forecast receives contradictory evidence;
- source required for resolution is failing.

Low-priority examples:

- another stale reminder for an inactive low-impact question;
- unchanged weekly source;
- new evidence already covered by an open batch task;
- resolved question receiving non-resolution news;
- reference-class reminder with no decision horizon.

## Required queue lanes

### Lane 0: deterministic critical

- resolution checks;
- scoring;
- duplicate reconciliation;
- disable resolved schedules;
- source-health checks;
- cutoff enforcement.

### Lane 1: urgent forecast work

- executable trigger crossings;
- high-impact new evidence;
- closing/decision deadline;
- material forecast disagreement.

### Lane 2: normal reforecast

- scheduled active-question reviews;
- evidence batches;
- assumption checks;
- reference-class refreshes.

### Lane 3: maintenance

- stale low-impact forecasts;
- taxonomy cleanup;
- lesson synthesis;
- optional source enrichment.

Each lane needs a daily budget and SLO. The system should stop accepting low-value Lane 3 work when Lane 0 or Lane 1 is falling behind.

---

# Autopilot needs an estimator, not merely a monitor

The current autopilot is closer to a source-change monitor with proposal plumbing than an autonomous forecasting agent.

A real autopilot run must produce a structured estimation artifact:

```json
{
  "prior_probability": 0.41,
  "evidence_updates": [
    {
      "event_id": "sce_...",
      "likelihood_ratio": 1.35,
      "correlation_cluster": "official-release",
      "reliability_weight": 0.95
    }
  ],
  "raw_posterior": 0.49,
  "ensemble_components": {
    "base_rate": {},
    "mechanism": {},
    "market": {},
    "case_specific": {}
  },
  "panel_result": {},
  "proposed_probability": 0.47,
  "materiality": "medium",
  "evidence_cutoff": "...",
  "change_my_mind": [],
  "guardrail_results": {}
}
```

An unchanged probability may be valid, but it needs to be the **result of estimation**, not the default because no estimator ran.

## Proposal policy

- Tiny change, low impact: record reviewed/immaterial automatically.
- Moderate change: create proposal with expiration.
- High-confidence, bounded delta, multiple sources: allow guarded auto-commit.
- Large change or high-impact question: require panel or operator.
- Missing required source or conflicting evidence: escalate.
- Proposal pending beyond SLA: notify or automatically reject/refresh.

The six current proposals have sat for several days with no disposition. A proposal queue without an approval SLA is another form of backlog.

---

# The system needs a real operational cockpit

At present, count metrics can mislead. The status report showed 1,000 scheduled-review runs because of a reporting cap, while the database contained 4,143. “Completed” concealed weak output. Alert totals changed while we were inspecting them.

An above-the-clouds cockpit should answer:

## Queue health

- arrival rate versus service rate;
- backlog by lane;
- oldest item;
- P50/P90/P95 age;
- SLA breaches;
- retry and dead-letter counts.

## Forecast coverage

- active questions with valid schedule;
- active questions without watched sources;
- active questions without current forecast;
- active questions past decision deadline;
- resolved questions with enabled recurring work.

## Automation effectiveness

- source changes detected;
- percentage triaged;
- percentage producing a material update;
- proposal acceptance/rejection rate;
- auto-commit rate;
- duplicate-commit rate;
- mean time from evidence to forecast update.

## Quality and safety

- post-cutoff updates blocked;
- stale evidence used;
- source failure rate;
- high-confidence misses;
- calibration by domain and horizon;
- baseline edge;
- panel disagreement;
- forecast-update reversals.

## Cost

- model calls per useful update;
- source calls per new observation;
- dollars per material probability move;
- dollars per resolved/scored forecast;
- warning-processing cost per alert closed.

The controlling metric should not be “alerts processed.” It should be:

> **Material forecast states maintained correctly per unit of time and cost.**

---

# Recommended implementation order

## Phase 0: Stop the bleeding

These changes should happen before expanding automation:

1. Automatically disable the **957 resolved-question schedules**.
2. Reconcile the 88 open question alerts attached to resolved questions.
3. Prevent resolved questions from entering normal active-review sweeps.
4. Merge duplicate open alerts using normalized condition keys.
5. Batch `new_evidence` alerts by question and prior forecast.
6. Put hard batch and wall-clock limits on review sweeps.
7. Make every scheduled-review failure isolated to its own row.
8. Record truthful run outcomes.
9. Stop acknowledging source failures without successful recovery.
10. Freeze new low-priority maintenance alerts when higher lanes exceed SLA.

This alone would dramatically reduce wasted throughput.

## Phase 1: Repair correctness

1. Add transactional work claiming and leases.
2. Add database uniqueness constraints for:
   - open alert keys;
   - active schedules;
   - active policies;
   - active watches;
   - proposal-to-snapshot linkage.
3. Make proposal commit compare-and-swap and idempotent.
4. Make policy, schedule, watches, and notification route one transactional lifecycle.
5. Enforce automatic teardown when a question resolves.
6. Move paid-budget reservation from an unlocked JSON file into SQLite.
7. Reject paid/reforecast jobs when no actual paid runner is wired.

## Phase 2: Close the forecasting loop

1. Introduce immutable source-change events.
2. Pass old/new snapshots directly into estimation.
3. Require a real estimation artifact before proposal or commit.
4. Separate observation acknowledgement from forecast completion.
5. Reconcile alerts based on committed events rather than full-ledger rescans.
6. Add bounded concurrent workers with per-source rate limits.
7. Add retries, leases, dead-letter handling, and proposal expiration.

## Phase 3: Build the operational brain

1. Create a utility-ranked task queue.
2. Establish queue lanes and budgets.
3. Define SLOs for high-impact, resolution, evidence, and maintenance work.
4. Add a cockpit showing arrival/service rates and useful outputs.
5. Introduce portfolio capacity management:
   - actively serviced;
   - monitor-only;
   - resolution-only;
   - archived.
6. Automatically reduce review frequency for low-value unchanged forecasts.
7. Increase frequency when triggers, disagreement, or decision proximity justify it.

---

# What “above the clouds” should look like

The target architecture is a five-plane system:

## 1. Data plane

Fetches and snapshots evidence with provenance, timestamps, deduplication, and source health.

## 2. Event plane

Records immutable changes and condition transitions.

## 3. Decision plane

Runs materiality classification, Bayesian updates, models, panels, and tail audits.

## 4. Execution plane

Claims tasks, creates proposals, commits snapshots, resolves questions, scores outcomes, and retries failures transactionally.

## 5. Operations/governance plane

Allocates capacity, enforces cutoffs, monitors SLOs, controls spending, prevents duplicate work, and measures calibration and baseline edge.

The current system has pieces of all five, but they are coupled through alerts and periodic rescans rather than through durable state transitions. That is why it feels like flying blind: the aircraft has many instruments, but no reliable flight-management computer coordinating them.

# My strongest judgment

The system does **not** primarily need:

- more alerts;
- more scheduled jobs;
- more LLM calls;
- more active questions;
- more warning sweeps;
- more indiscriminate parallelism.

It needs:

1. **less work creation;**
2. **correct lifecycle teardown;**
3. **durable event handoff;**
4. **transactional task claiming;**
5. **idempotent state transitions;**
6. **utility-based prioritization;**
7. **truthful operational metrics;**
8. **an estimator inside autopilot;**
9. **backpressure;**
10. **clear definitions of “handled,” “updated,” and “healthy.”**

The biggest conceptual shift is this:

> Stop treating the alert backlog as the problem to drain. Treat it as evidence that the system lacks a coherent operational state machine.

Once that state machine exists, the warnings become a manageable by-product rather than the primary workload.

---

# Implementation status — 2026-07-16

This section is the delivery ledger for the remediation above. It distinguishes
code that is operational now from follow-on work; the diagnosis above is retained
unchanged as the design rationale.

## Delivered

### Phase 0 — stop the bleeding

- Confirmed resolution now transactionally disables question schedules, policies,
  watches, active proposals, and open question alerts. Opening a legacy database
  also repairs resolved-question work left active by older versions.
- Review sweeps have a row limit, wall-clock limit, per-row failure isolation,
  leases, and explicit useful-outcome statuses such as
  `completed_no_change`, `forecast_committed`, `partial_source_failure`, and
  `failed_retryable`.
- Open alerts use a normalized, database-unique condition key. Repeated detection
  touches `seen_count`/`last_seen_at`; legacy duplicates are collapsed on migration.
- `new_evidence:*` is batched by question and the prior forecast snapshot instead
  of creating one operator-facing alert per evidence row.
- Source-failure alerts are material work, not bookkeeping. A failed recheck leaves
  the alert open. Alert closure now records a machine-readable disposition.
- Maintenance-lane claims are backpressured while deterministic-critical or urgent
  work is beyond its SLO.

### Phase 1 — correctness under concurrency

- Scheduled reviews and operational tasks use compare-and-swap leases, bounded
  claims, heartbeats, attempts, retry delay, and dead-letter status.
- Partial unique indexes enforce one open alert key, one active schedule key, one
  active watch identity, one active policy per question, and one active proposal
  per question/prior forecast.
- Proposal approval claims `pending -> committing` before snapshot creation and
  stores `resulting_forecast_id`; repeated approval returns the existing snapshot.
- Confirmed resolution enqueues one idempotent `finalize_resolution` task. Its
  worker scores and creates one active postmortem per score record.
- Paid warning automation uses a transactional SQLite lease and interval record.
  Concurrent processes cannot reserve the same paid pass through an unlocked JSON
  timestamp. The paid tier still refuses to run when no real runner is wired.

### Phase 2 — durable forecast handoff

- Source detection writes an immutable source snapshot plus `source_change_events`
  and an idempotent operational task before it emits the alert. The watch cursor is
  not advanced until a consumer records a disposition.
- Repeated polls of the same exact change reuse the pending event/task/alert.
- Autopilot consumes the persisted old/new handoff. Material change without an
  explicit estimate is moved to `normal_reforecast`; it creates neither a fake
  model run nor an unchanged proposal.
- Explicit estimates record a structured `autopilot_estimation` artifact containing
  prior/proposed probability, event and source-snapshot references, delta,
  materiality, cutoff, estimator provenance, and guardrail results.
- Source events and their linked tasks record processed/failed dispositions;
  successful event disposition can reconcile the linked alert directly rather than
  waiting for a whole-ledger scan.
- Proposal creation has a 24-hour default SLA, supports an explicit expiration, and
  expired proposals cannot commit. Expiration emits a refresh alert.
- Operational retries are bounded, expired leases are reclaimable, exhausted work
  dead-letters, and only one task for a watched source may be leased concurrently.

### Phase 3 — operational allocation

- The durable task queue has four policy-backed lanes:
  `deterministic_critical`, `urgent_forecast`, `normal_reforecast`, and
  `maintenance`. Each has an enabled flag, daily claim budget, and SLO.
- The operational cockpit reports backlog, oldest/P50/P95 age, SLO breaches,
  claims and completions today, dead letters, forecast coverage gaps, source-event
  states, and portfolio capacity modes. Dashboard payloads expose this block.
- Questions can be assigned `actively_serviced`, `monitor_only`,
  `resolution_only`, or `archived`. Resolution-only mode keeps resolver/official
  watches and shuts off ordinary maintenance; archive closes all recurring work.
- Three consecutive no-change question reviews begin adaptive cadence backoff, up
  to 4x. Deadline clamping still accelerates work to daily or twice daily near the
  decision/resolution boundary, and material outcomes reset the backoff.

### Phase 4 — estimator, economics, and operations UI

- A hosted estimator worker now claims `normal_reforecast` leases and consumes the
  exact immutable source-change event; it never re-polls the source. Its output is
  rejected unless it contains likelihood ratios, correlation clusters, reliability
  weights, a raw posterior, ensemble components, a panel result, materiality,
  evidence cutoff, `change_my_mind`, and guardrail results. The cron host exposes
  this as `--estimate-source-changes` and preserves the configured model/provider.
- Source polling uses SQLite token buckets keyed by adapter and credential/account.
  Distinct watches share quota; a denied token performs no network request and does
  not advance the watch cursor or fabricate a source failure.
- Source events retain compatibility status while recording the full audited state
  vocabulary: detected, triaged, claimed, researched, estimated, proposed,
  committed, rejected, reconciled, failed, and superseded. Proposal approval and
  rejection append their terminal transitions.
- The Desk has a dedicated Operations tab. It renders lane backlog/age/SLO/budget,
  30-day arrival and service history, coverage and capacity, rate-limit pressure,
  measured usage, and cost per material update or resolution.
- Every attempt records model/source calls, tokens, latency, dollar cost, and cost
  provenance. Hosted estimator usage comes from the agent runtime rather than the
  model's JSON. Dollar totals remain explicitly labelled by provider cost status;
  an `estimated` provider amount is not presented as a billed amount.
- Queue claims are utility-ranked using versioned impact × urgency × probability of
  movement × information value × resolution proximity ÷ expected cost components.
  Completed outcomes can be backtested for top-half yield and pairwise concordance.
  Once a minimum mixed sample exists, `calibrate_task_utility()` fits and activates
  a regularized logistic model and re-scores pending work; before that threshold the
  stored `utility-v1` priors remain visibly heuristic. Cron exposes the guarded fit
  as `--calibrate-utility`, and the cockpit shows the active version, sample size,
  concordance, and readiness.

## Acceptance evidence

Focused regression coverage now includes concurrent alert deduplication, review
lease exclusivity, per-row review failure isolation, resolved lifecycle teardown,
immutable/deduplicated source handoff, estimator-required deferral, structured
estimation artifacts, exact-event estimator execution without source re-polling,
event transition audit history, proposal outcome reconciliation, adapter/account
token sharing, utility ordering/calibration/backtesting, measured cost aggregation,
cockpit history rendering, proposal expiry, task heartbeat/retry/dead-letter behavior,
paid-budget interval locking, new-evidence batching, capacity modes, operational
cockpit output, and adaptive cadence backoff.
