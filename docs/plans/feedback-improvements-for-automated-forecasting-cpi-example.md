User story: Automatic CPI forecast refresh in the Superforecaster harness

Story

As a forecasting desk operator,
I want the Superforecasting Agent harness to automatically monitor CPI-relevant sources, detect material evidence changes, re-run the forecastingprotocol, and append auditable forecast updates,
so that CPI forecasts stay current without me manually running forecast watch check, forecast research, forecast model, and forecast update eachday.

────────────────────────────────────

Current state / gap

The system already has many of the needed primitives:

• forecast ledger
• evidence records
• model runs
• assumptions
• reference classes
• forecast snapshots
• watched sources
• scheduled reviews
• cron bridge
• scoring / postmortem machinery

But the doctor report shows this current installation has:

• scheduled_review_count: 0
• watched_source_count: 0
• scheduled_review_run_count: 0
• score_count: 0
• claim_live_superforecasting: false

So the immediate product gap is not “no forecasting ledger exists.” The gap is that the loop is not yet wired into a trusted autonomous pipeline.

────────────────────────────────────

Feature: Autonomous CPI forecast refresh

Primary user flow

Given an active CPI forecast question, e.g.

  ─ text
  What will the May 2026 US CPI-U all-items 12-month percent change be as first published by BLS?

the user should be able to run one setup command:

  ─ bash
  forecast autopilot enable fq_145c7af5b87b \
    --sources bls:CUUR0000SA0,cleveland-fed-cpi-nowcast,kalshi:<market-id> \
    --cadence "every weekday at 09:00" \
    --materiality-threshold "probability_delta>=0.03 or source_value_delta>=0.05pp" \
    --mode propose

After that, the system should:

1. poll watched sources on schedule,
2. snapshot source data,
3. compare against prior evidence,
4. decide whether changes are material,
5. run the forecast protocol,
6. generate a proposed probability update,
7. attach evidence/model/assumption references,
8. notify the user,
9. optionally auto-commit if configured.

────────────────────────────────────

Acceptance criteria

1. Autopilot setup

AC1.1 — Enable autopilot for a forecast question

Given an active forecast question exists
When the user runs:

  ─ bash
  forecast autopilot enable <question-id> ...

Then the system creates:

• watched source records,
• a scheduled review row,
• an autopilot policy record,
• a materiality policy,
• a notification destination,
• an audit log entry.

Success output should include:

  ─ text
  Autopilot enabled for fq_...
  Sources: 3
  Cadence: every weekday at 09:00
  Mode: propose
  Next run: <timestamp>

────────────────────────────────────

AC1.2 — Validate question readiness before enabling

Given a question has missing resolution criteria or no prior forecast snapshot
When autopilot is enabled
Then the system refuses or warns, depending on severity.

Hard blockers:

• missing resolution criteria,
• missing resolution source,
• unsupported outcome type,
• no baseline forecast snapshot,
• no source adapter available for required evidence.

Soft warnings:

• no reference class,
• no calibration history,
• no scoring history,
• stale assumptions.

────────────────────────────────────

2. Source monitoring

AC2.1 — Poll CPI-relevant sources automatically

Given autopilot is enabled
When the scheduled run fires
Then the system checks configured sources, such as:

• BLS CPI series,
• Cleveland Fed inflation nowcast,
• prediction market contract,
• optionally FRED / Treasury / analyst consensus source.

Each source check creates a source snapshot with:

• source type,
• source URL or adapter ID,
• retrieved timestamp,
• parsed values,
• raw payload hash,
• success/failure status,
• adapter version.

────────────────────────────────────

AC2.2 — Do not duplicate unchanged evidence

Given the latest source payload hash matches the previous snapshot
When the source is checked again
Then no duplicate evidence item is added.

The run should instead record:

  ─ text
  No material source changes detected.

────────────────────────────────────

AC2.3 — Source failures create alerts, not silent failures

Given one or more source adapters fail
When autopilot runs
Then the system creates an alert with:

• failed source,
• error message,
• retry count,
• last successful snapshot,
• recommended action.

Autopilot should continue with remaining sources unless the failed source is marked required.

────────────────────────────────────

3. Materiality detection

AC3.1 — Detect material source changes

Given a new source snapshot differs from the prior snapshot
When the delta exceeds configured thresholds
Then the system marks the change as material and triggers a forecast refresh.

Example thresholds:

  ─ yaml
  materiality:
    source_value_delta_pp: 0.05
    market_probability_delta: 0.03
    nowcast_delta_pp: 0.05
    time_decay_days_before_release: 3

────────────────────────────────────

AC3.2 — Skip full update on immaterial changes

Given source changes are below materiality threshold
When autopilot runs
Then the system records a scheduled review run but does not generate a new forecast snapshot.

Output:

  ─ text
  Checked 3 sources.
  Changed: 1
  Material: 0
  Forecast update skipped.

────────────────────────────────────

4. Forecast protocol execution

AC4.1 — Run the full forecast refresh protocol

Given a material evidence change is detected
When autopilot runs
Then the system executes the forecast protocol:

1. import evidence,
2. update assumptions if invalidated,
3. refresh reference-class/base-rate context if relevant,
4. run model or calculation component,
5. compare against prior forecast,
6. generate proposed probability or numeric distribution,
7. record model run diagnostics,
8. create an auditable forecast snapshot.

────────────────────────────────────

AC4.2 — Preserve evidence linkage

Given a forecast update is generated
When the snapshot is recorded
Then it must include references to:

• evidence item IDs,
• source snapshot IDs,
• model run IDs,
• assumptions used,
• reference classes used,
• prior forecast snapshot,
• calibration lessons applied, if any.

No forecast snapshot should be accepted without at least one evidence reference unless explicitly marked as a manual judgment update.

────────────────────────────────────

AC4.3 — Store model output separately from final forecast

Given the model produces an updated forecast
When the run completes
Then the ledger stores:

• raw model output,
• structured parsed probability/distribution,
• diagnostics,
• final accepted forecast snapshot.

This makes it possible to audit cases where the model recommended one update but the final forecast was clipped, rejected, or manually adjusted.

────────────────────────────────────

5. Human approval / autonomy modes

AC5.1 — Propose mode

Given autopilot is configured with:

  ─ bash
  --mode propose

When a forecast refresh produces a new probability
Then the system creates a pending proposal, not an active forecast snapshot.

The user sees:

  ─ text
  CPI forecast update proposed:
  Previous: 0.62
  Proposed: 0.68
  Delta: +0.06
  Main driver: Cleveland Fed nowcast +0.11pp since last snapshot
  Approve with:
  forecast autopilot approve <proposal-id>

────────────────────────────────────

AC5.2 — Auto-commit mode

Given autopilot is configured with:

  ─ bash
  --mode auto-commit

When a forecast refresh produces a valid update within guardrails
Then the system appends the forecast snapshot automatically.

Guardrails should include:

• maximum probability delta per run,
• maximum daily cumulative delta,
• required source count,
• no critical source failures,
• model output parse success,
• forecast passes schema validation.

────────────────────────────────────

AC5.3 — Escalate instead of committing unsafe updates

Given an update exceeds guardrails
When autopilot is in auto-commit mode
Then the system should not commit automatically.

Instead it creates an escalation alert:

  ─ text
  Autopilot update requires review.
  Reason: proposed probability delta +0.18 exceeds max_auto_delta 0.07.

────────────────────────────────────

6. Notifications

AC6.1 — Notify on material updates

Given autopilot detects a material change
When a proposal or committed update is generated
Then the user receives a concise notification containing:

• question title,
• previous forecast,
• proposed/current forecast,
• delta,
• top evidence changes,
• approval command or review command.

────────────────────────────────────

AC6.2 — Daily quiet success option

Given the user configures quiet mode
When no material changes occur
Then the system does not notify.

But the run remains visible in:

  ─ bash
  forecast autopilot history <question-id>

────────────────────────────────────

7. Resolution and scoring

AC7.1 — Auto-detect resolution when BLS releases final value

Given the CPI release becomes available from BLS
When the resolution source publishes the first official value
Then the system proposes resolution:

  ─ text
  Resolution detected:
  May 2026 CPI-U all-items 12-month percent change: X.X%
  Source: BLS
  Resolve with:
  forecast resolve fq_... --outcome X.X --source <url>

In strict autopilot mode, resolution may also be auto-committed if the trusted resolver policy allows it.

────────────────────────────────────

AC7.2 — Automatically score resolved forecasts

Given the forecast has a confirmed resolution
When scoring is enabled
Then the system runs:

  ─ bash
  forecast score <question-id> --baselines

and records:

• Brier score or numeric score,
• baseline comparison,
• calibration eligibility,
• forecast origin,
• scoring timestamp.

────────────────────────────────────

AC7.3 — Prompt postmortem after scoring

Given a forecast has been scored
When score is worse than configured threshold or materially worse than baseline
Then the system creates a postmortem task.

Example:

  ─ text
  Postmortem needed:
  Forecast underperformed Cleveland Fed baseline by 0.08 Brier.
  Run:
  forecast postmortem fq_...

────────────────────────────────────

Engineering notes

Data model additions

Add or formalize the following tables / entities:

autopilot_policies

Fields:

  ─ text
  id
  question_id
  enabled
  mode                  # propose | auto_commit | alert_only
  cadence
  materiality_policy_id
  guardrail_policy_id
  notification_policy_id
  created_at
  updated_at
  created_by

────────────────────────────────────

autopilot_runs

Fields:

  ─ text
  id
  policy_id
  question_id
  started_at
  finished_at
  status                # success | partial | failed | skipped
  trigger_reason        # schedule | manual | source_change | pre_resolution
  sources_checked
  sources_changed
  material_changes
  proposal_id
  forecast_snapshot_id
  alerts_created
  diagnostics_json

────────────────────────────────────

forecast_update_proposals

Fields:

  ─ text
  id
  question_id
  run_id
  prior_forecast_id
  proposed_probability_or_distribution
  rationale
  evidence_refs
  source_snapshot_refs
  model_run_refs
  assumption_refs
  reference_class_refs
  status                # pending | approved | rejected | expired | auto_committed
  created_at
  reviewed_at
  reviewed_by

────────────────────────────────────

source_snapshots

If not already durable enough, strengthen source snapshots with:

  ─ text
  id
  question_id
  watched_source_id
  source_type
  source_url
  retrieved_at
  raw_payload_path
  raw_payload_sha256
  parsed_values_json
  adapter_version
  status
  error_message

────────────────────────────────────

CLI surface

Suggested commands:

  ─ bash
  forecast autopilot enable <question-id> [options]
  forecast autopilot disable <question-id>
  forecast autopilot status <question-id>
  forecast autopilot run <question-id>
  forecast autopilot history <question-id>
  forecast autopilot proposals <question-id>
  forecast autopilot approve <proposal-id>
  forecast autopilot reject <proposal-id>

Useful options:

  ─ bash
  --mode propose|auto-commit|alert-only
  --cadence "every weekday at 09:00"
  --source bls:CUUR0000SA0
  --source url:https://...
  --source kalshi:<market-id>
  --materiality-threshold probability_delta=0.03
  --max-auto-delta 0.07
  --notify origin
  --quiet-if-unchanged

────────────────────────────────────

Forecast protocol runner

The key missing abstraction is probably a reusable internal runner like:

  ─ python
  run_forecast_refresh(
      question_id: str,
      trigger: str,
      evidence_cutoff: datetime,
      sources: list[WatchedSource],
      mode: Literal["proposal", "commit"],
      materiality_policy: MaterialityPolicy,
      guardrails: GuardrailPolicy,
  ) -> ForecastRefreshResult

It should coordinate existing primitives:

  ─ text
  check_watched_sources
  → import_source_evidence
  → evidence_readiness
  → record_model_run
  → update_forecast or create proposal
  → schedule/review alert

Important: this runner should be deterministic enough to test with fixture source payloads.

────────────────────────────────────

Source adapter requirements

For CPI specifically, we need robust adapters for:

BLS

• CPI-U all-items series: CUUR0000SA0
• retrieve latest observations,
• parse 12-month percent change,
• distinguish advance/latest/first-published if possible,
• detect release month.

Cleveland Fed nowcast

• scrape or API adapter for inflation nowcast,
• parse CPI month-over-month / year-over-year estimate if available,
• store publication date and target month.

Prediction markets

Kalshi / Polymarket adapter should provide:

• market title,
• contract bounds,
• bid/ask/mid,
• implied distribution,
• timestamp,
• liquidity / volume,
• market close and resolution metadata.

────────────────────────────────────

Guardrails

Autonomous probability updates need strict guardrails:

  ─ yaml
  guardrails:
    max_single_run_probability_delta: 0.07
    max_daily_probability_delta: 0.12
    min_independent_sources_for_auto_commit: 2
    require_no_critical_source_failures: true
    require_model_parse_success: true
    require_evidence_refs: true
    require_prior_forecast: true
    allow_resolution_auto_commit: false

For numeric CPI forecasts, use equivalent distribution guardrails:

  ─ yaml
  max_mean_delta_pp: 0.10
  max_tail_probability_delta: 0.10
  max_interval_width_collapse: 0.25

────────────────────────────────────

Testing plan

Unit tests

• materiality threshold logic,
• source snapshot hashing,
• duplicate evidence suppression,
• guardrail rejection,
• proposal creation,
• auto-commit path,
• failed-source alerting,
• CLI argument parsing.

Integration tests

Use fixture payloads for:

• unchanged BLS data,
• prediction-market move,
• failed source adapter,
• BLS release / resolution detection.

End-to-end test

A single test should verify:

─ text
forecast autopilot enable
→ scheduled run fires
→ source payload changes
→ materiality triggered
→ model run recorded
→ proposal created
→ proposal approved
→ forecast snapshot appended
→ later BLS resolution detected
→ score recorded
→ postmortem task created if needed

Run via project wrapper:

─ bash
scripts/run_tests.sh tests/forecasting/test_autopilot.py

────────────────────────────────────

Safety / product-positioning note

Until the ledger has substantial scored live forecasts and leakage-free backtests, the system should not market this as proven “livesuperforecasting.” The current doctor report explicitly says:

─ text
claim_live_superforecasting: false

So the product language should be:

─ text
Autonomous forecast maintenance and audit trail

not:

─ text
Autonomous superforecaster

The claim becomes stronger only after many resolved live forecasts, scored baselines, postmortems, and calibration improvements.