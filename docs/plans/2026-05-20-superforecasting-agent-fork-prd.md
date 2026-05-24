# PRD: Superforecasting Agent Fork

## Overview

Fork Hermes Agent into a command-line forecasting desk that compounds judgment over time. The fork should not be a general assistant that occasionally answers forecasting questions; it should be a persistent research system that maintains probabilistic beliefs, updates them as evidence changes, scores itself after resolution, and improves calibration across repeated forecasts.

The product target is a CLI-first agent for users who think like quantitative researchers, prediction-market participants, forecasting tournament competitors, or domain experts making explicit uncertainty estimates. It should be good at any scoreable question: ingest information, structure uncertainty, build base rates, run probabilistic models, preserve an auditable evidence trail, and learn from resolved forecasts.

The north star:

> A command-line forecasting desk that compounds judgment over time.

For the strategic rationale behind the fork, see [Superforecasting Agent Fork Context](./2026-05-20-superforecasting-agent-fork-context.md).

## Goals

- Turn forecasts into the core product primitive, replacing generic chat sessions as the center of gravity.
- Preserve the useful Hermes runtime pieces: CLI/TUI, tool execution, model-provider adapters, session storage, logging, terminal/browser/MCP/file tools, plugin extensibility, and credential handling.
- Build an append-only forecast ledger with evidence, probability history, model runs, rationales, resolutions, and scoring.
- Make every probability auditable: a forecast should have sources, timestamps, assumptions, reference classes, and update history.
- Support repeatable research workflows for question parsing, evidence gathering, base-rate estimation, inside-view modeling, ensemble forecasting, and post-resolution review.
- Add calibration and scoring systems that improve future forecasts based on past misses.
- Add time-aware backtesting so benchmark runs cannot use evidence that was unavailable at the simulated forecast time.
- Add scheduled self-checks and alerts that detect stale forecasts, resolved questions, repeated domain errors, and calibration-memory updates.
- Create a CLI product that feels like a quantitative research terminal rather than a chatbot.
- Benchmark performance against held-out resolved questions, market-implied probabilities, crowd forecasts, Metaculus-style baselines, and domain-specific historical datasets without claiming guaranteed superiority.

## Non-Goals

- Do not preserve Hermes as a broad consumer assistant in the fork.
- Do not make messaging gateways the primary product surface.
- Do not optimize for personality, entertainment, or general-purpose chat.
- Do not allow the LLM's raw subjective probability to be the only forecasting mechanism.
- Do not claim guaranteed performance above human superforecasters without backtested evidence.
- Do not build a separate dashboard-first product before the CLI workflow is strong.
- Do not depend on any one data provider, prediction market, or forecasting platform.
- Do not revolve the product around Metaculus, tournaments, or any single benchmark source.
- Do not treat memory as unstructured chat recall; all durable learning must be tied to forecasts, evidence, scores, or postmortems.

## Users

### Primary User

A solo forecaster, researcher, investor, operator, or analyst who wants a local CLI system for maintaining many live probabilistic forecasts with explicit reasoning and measurable calibration.

### Secondary Users

- Forecasting tournament participants tracking active questions without making tournaments the default workflow.
- Quantitative researchers monitoring event probabilities.
- Teams that want auditable uncertainty estimates for decisions.
- Developers building specialized forecasting plugins, data connectors, or model adapters.

## Product Principles

1. Forecasts are first-class objects.
2. Every forecast has an "as of" timestamp.
3. Every probability update must cite what changed.
4. Evidence is append-only and source-linked.
5. Models are tools, not authorities.
6. Resolved forecasts must produce scores and postmortems.
7. Calibration is a product feature, not an analytics afterthought.
8. The CLI should show standing beliefs, stale assumptions, and deltas quickly.
9. General-purpose assistance is acceptable only when it improves forecast quality.
10. Platform imports are adapters; the core product must work for any scoreable question.
11. Backtests must be time-aware and must not leak post-forecast evidence.
12. Scheduled self-checks should surface review work and update learning artifacts without silently overwriting forecasts.

## Fork Strategy

### Keep From Hermes

- CLI/TUI infrastructure as the main product surface.
- Tool registry and core execution path.
- Terminal, browser, file, web, MCP, delegation, checkpoint, and code-execution tools.
- Provider adapters, credential pools, model routing, and auxiliary model support.
- Session database patterns where they can be adapted to forecast persistence.
- Logging, profiles, config loading, setup wizard, and plugin discovery.
- Test harness and `scripts/run_tests.sh`.

### Cut Or Demote

- Most gateway-first platform integrations from the default product path.
- Broad generic skills marketplace as a front-and-center UX.
- Kawaii/general assistant CLI branding and prompts.
- Chat transcript as the primary durable artifact.
- Default exposure of unrelated tools that do not help forecasting.
- Dashboard chat duplication unless it supports forecast review or observability.
- Any memory mechanism that cannot explain how it improves future forecast accuracy.

### Rename Product Surfaces

Candidate names can be decided later, but code should move toward neutral domain names:

- `ForecastDesk`
- `ForecastAgent`
- `forecasting/`
- `forecast ledger`
- `evidence log`
- `calibration engine`

Avoid leaving Hermes-specific metaphors or assistant-centric command names in new core modules.

## Core Domain Model

### ForecastQuestion

```text
id
title
description
resolution_criteria
resolution_source
created_at
close_time
resolution_time
outcome_space
status
tags
domain
topics
owner
impact
review_cadence
next_review_at
current_forecast_id
forecast_history_refs
evidence_log_refs
model_run_refs
assumption_refs
reference_class_refs
```

`ForecastQuestion` owns the durable identity of a scoreable question. The current forecast, history, evidence log, model runs, assumptions, and reference classes may live in separate tables, but they must be first-class relationships from the question because the CLI should operate on a user's standing book of beliefs.

### OutcomeSpace

```text
type: binary | categorical | numeric | distribution
choices
units
bounds
resolution_parser
```

### ForecastSnapshot

```text
question_id
forecast_id
created_at
as_of
probability_or_distribution
confidence
forecast_horizon_days
method
ensemble_components
rationale
key_assumptions
assumption_refs
reference_class_refs
evidence_refs
model_run_refs
parent_forecast_id
forecast_origin: live | backtest | imported_baseline
agent_model
prompt_version
forecasting_protocol_version
toolset_version
source_snapshot_refs
evidence_cutoff
backtest_run_id
calibration_eligible
calibration_weight
calibration_lesson_refs
calibration_adjustment
```

### EvidenceItem

```text
id
question_id
captured_at
available_at
source_url
source_name
source_type
published_at
claim
summary
reliability_rating
relevance_rating
stance: increases | decreases | mixed | context
snapshot_path
admissible_for_backtests
metadata
```

`available_at` is the earliest known time the evidence was publicly or operationally available. Backtests must use `available_at` to prevent post-forecast evidence leakage; `captured_at` only records when this system saved the item.

### ModelRun

```text
id
question_id
created_at
model_type
inputs
parameters
output
diagnostics
code_ref
artifact_paths
model_version
prompt_version
data_version
evidence_cutoff
```

### Assumption

```text
id
question_id
text
status: active | stale | invalidated | resolved
created_at
last_checked_at
invalidated_at
check_cadence
evidence_refs
notes
```

### ReferenceClass

```text
id
question_id
name
inclusion_criteria
exclusion_criteria
base_rate
base_rate_uncertainty
source_refs
status: active | stale | invalidated | superseded
created_at
last_checked_at
invalidated_at
notes
```

### Resolution

```text
id
question_id
resolved_at
outcome
resolution_source
resolution_source_snapshot_ref
resolver_type: manual | source_adapter | scheduled_check
resolution_status: proposed | confirmed | disputed | corrected
criteria_satisfied
confidence
confirmed_at
confirmed_by
resolver_notes
disputed_at
correction_ref
scoreable
```

### ScoreRecord

```text
id
question_id
forecast_id
resolution_id
scored_at
brier_score
log_score
calibration_bucket
forecast_horizon_days
domain
forecast_origin
calibration_eligible
calibration_weight
baseline_ref
notes
```

### Postmortem

```text
id
question_id
forecast_id
resolution_id
score_record_id
forecast_origin
calibration_eligible
created_at
summary
what_happened
what_was_expected
missed_evidence
overweighted_evidence
base_rate_error
inside_view_error
resolution_error
lesson
calibration_adjustment
```

### CalibrationLesson

```text
id
scope_type: domain | topic | horizon | question_type | model_component | global
scope_ref
created_at
updated_at
status: active | tentative | superseded | retired
confidence
lesson
recommended_adjustment
source_postmortem_refs
source_score_record_refs
supersedes_lesson_id
metadata
```

### ForecastCorrection

```text
id
target_type: forecast_snapshot | evidence_item | assumption | reference_class | resolution | score_record | postmortem | calibration_lesson
target_id
created_at
created_by
reason
old_value
new_value
patch
affected_score_record_refs
affected_postmortem_refs
affected_calibration_lesson_refs
status: proposed | applied | rejected
```

### TrustedResolverPolicy

```text
id
resolver_plugin
plugin_version
scope_type: domain | topic | source | question_type | global
scope_ref
enabled
created_at
approved_by
last_used_at
audit_log_ref
```

### BacktestRun

```text
id
dataset
created_at
default_forecast_time_cutoff
evidence_cutoff_policy
question_filter
model_profile
calibration_policy
result_summary
artifact_paths
leakage_checks_passed
```

### BacktestCase

```text
id
backtest_run_id
question_id
simulated_forecast_time
evidence_cutoff
generated_forecast_id
baseline_comparison_refs
score_record_id
leakage_check_status
excluded_evidence_count
ambiguous_evidence_count
notes
```

### BaselineComparison

```text
id
question_id
forecast_id
backtest_case_id
source
baseline_type: base_rate | market | crowd | prior_agent | imported
as_of
probability_or_distribution
score_record_id
metadata
```

### ScheduledReview

```text
id
scope_type: question | domain | topic | portfolio
scope_ref
cadence
next_run_at
last_run_at
trigger_reason
enabled
```

### AlertEvent

```text
id
created_at
severity
scope_type
scope_ref
reason
recommended_action
acknowledged_at
```

### DomainErrorProfile

```text
id
domain
topic
forecast_horizon_bucket
question_type
sample_count
calibration_summary
recurring_errors
recommended_adjustments
updated_at
```

## Core Workflow

Every serious forecast should follow this loop:

1. Parse the question and resolution criteria.
2. Detect ambiguity and request clarification if the outcome is not scoreable.
3. Define the outcome space.
4. Identify relevant reference classes.
5. Gather and timestamp evidence.
6. Estimate base rates.
7. Generate inside-view arguments.
8. Run quantitative models when useful.
9. Combine model outputs into an explicit ensemble.
10. Produce a probability or distribution with rationale.
11. Store the forecast snapshot in the ledger.
12. Monitor for new evidence and stale assumptions.
13. Update the probability when warranted.
14. Resolve the question when the outcome is known.
15. Score the forecast.
16. Write a postmortem.
17. Feed lessons into future calibration.
18. Schedule or update self-checks for stale forecasts, watched domains, and recurring error patterns.

## CLI Product

The CLI should open into a forecasting dashboard, not a blank assistant prompt.
The primary console entrypoint should be `forecast`, with forecast-first aliases such as `superforecast` or `superforecasting-agent`. Legacy `hermes` entrypoints can remain during the fork transition, but bare CLI invocation should route to the forecasting desk rather than generic chat.

Example:

```text
ACTIVE FORECASTS

ID     Question                              P(now)  Delta  Close        Status
142    Will X win the election?             0.63    +0.08  2026-11-03   needs update
188    Will company Y default?              0.21    -0.04  2026-09-30   fresh
203    Will bill Z pass committee?          0.47    +0.12  2026-06-15   new evidence
```

### Required Commands

```bash
forecast new
forecast ingest <url-or-file>
forecast list [--status active|closed|resolved] [--domain ...]
forecast show <id>
forecast research <id>
forecast base-rate <id>
forecast model <id>
forecast update <id>
forecast evidence add <id> <url-or-note>
forecast evidence list <id>
forecast resolve <id> --outcome <value>
forecast score <id>
forecast postmortem <id>
forecast lesson list [--scope-type ...] [--scope-ref ...] [--active]
forecast lesson status <lesson-id> --status tentative|active|superseded|rejected
forecast calibration [--domain ...] [--horizon ...] [--origin live|backtest|imported_baseline] [--by-origin]
forecast errors [--domain ...] [--topic ...]
forecast review [--stale] [--last 30d] [--horizon <days|range>]
forecast backtest <dataset> [--as-of <timestamp>]
forecast backtest <dataset> --probability-source baseline-ensemble
forecast backtest <dataset> --probability-source forecast-engine
forecast backtest <dataset> --probability-source agent-protocol [--agent-response-jsonl <path>] [--agent-output-jsonl <path>]
forecast backtest builtin:manifold-public-120-binary
forecast backtest --all-benchmarks [--probability-source forecast-engine]
forecast performance [--last N] [--dataset <filter>] [--json]
# JSON includes evidence_status with live/backtest claim-readiness gaps.
forecast pilot-cohort <csv-or-json> [--schedule-cadence <duration>] [--schedule-next-run-at <time>]
forecast schedule add --question <id> --cadence <duration>
forecast schedule add --domain <domain> [--topic <topic>] --cadence <duration>
forecast schedule add --horizon <days|range> --cadence <duration> [--stale-days <days>]
forecast schedule add --portfolio <name> --cadence <duration>
forecast schedule list
forecast schedule run [--auto-score] [--auto-postmortem]
forecast watch add --question <id> <source>
forecast watch add --question <id> gdelt:<query>
forecast watch add --question <id> fred:<series-id>
forecast watch add --question <id> bls:<series-id>
forecast watch add --question <id> worldbank:<country>/<indicator>
forecast watch add --question <id> census:<dataset-path?get=...&for=...>
forecast watch add --question <id> sec:<cik>
forecast watch add --domain <domain> [--topic <topic>] <source>
forecast watch add --portfolio <name> <source>
forecast watch list
forecast watch check [--question <id>] [--domain ...] [--topic ...] [--portfolio <name>]
forecast alerts
forecast self-check [--question <id>] [--domain ...] [--topic ...] [--horizon <days|range>] [--portfolio <name>] [--auto-score] [--auto-postmortem]
forecast export <id|all>
```

### Optional Adapter Commands

Platform-specific importers are useful for extracting question metadata, crowd forecasts, priors, posteriors, and benchmark probabilities. They should enrich the generic forecast ledger without becoming the default product path.

```bash
forecast import metaculus <url>
forecast import market <url-or-symbol>
forecast import data <csv-or-json-url-or-file> --question <id>
forecast import gdelt <query> --question <id>
forecast import fred <series-id> --question <id>
forecast import bls <series-id> --question <id>
forecast import worldbank <country>/<indicator> --question <id>
forecast import census <dataset-path?get=...&for=...> --question <id>
forecast import socrata <domain>/<dataset-id> --question <id>
forecast import stooq <symbol-or-csv-url> --question <id>
forecast import yahoo <symbol> --question <id>
forecast import coingecko <coin-id-or-list> --question <id>
forecast import sec <cik> --question <id>
forecast import secfacts <cik>/<concept> --question <id>
forecast import arxiv <query> --question <id>
forecast import pubmed <query-or-PMID> --question <id>
forecast import githubcommits <owner/repo> --question <id>
forecast import githubactions <owner/repo> --question <id>
forecast import pypi <package> --question <id>
forecast import npm <package> --question <id>
forecast import manifold <url-or-id-or-slug>
forecast import polymarket <url-or-id-or-slug>
forecast import kalshi <url-or-ticker>
forecast import benchmark <source>
forecast import benchmark metaculus:resolved [--limit 100]
forecast import benchmark manifold:resolved [--limit 100]
forecast import benchmark kalshi:resolved [--limit 100]
forecast import tournament <source>
```

### Assistant Prompt Mode

Free-form chat should still exist, but it should be scoped to forecasting. If the user asks a general question, the agent should either connect it to a forecast or keep the answer ephemeral.

## Forecasting Engine

The forecasting engine should combine multiple probability sources rather than using a single LLM judgment.

### Components

- Reference-class/base-rate estimator.
- Bayesian update helper.
- Market-implied probability adapter where market data is available.
- Time-series/statistical model runner for questions with numeric historical data.
- Structured LLM judgment with explicit uncertainty and argument decomposition.
- Calibration adjustment based on the agent's historical performance.
- Ensemble combiner with component weights stored per forecast.

### Output Requirements

Every forecast update must include:

- Current probability or distribution.
- Previous probability or distribution.
- Delta.
- Forecast horizon.
- Main evidence that caused the update.
- Base-rate estimate.
- Inside-view adjustment.
- Model components and weights.
- Confidence rating.
- Assumptions that would change the forecast.
- Model, prompt, protocol, and toolset versions used to produce the update.
- Evidence cutoff used by the update, especially for historical replays and backtests.
- Forecast origin and calibration eligibility policy.
- Calibration lesson refs that influenced any calibration adjustment.

## Evidence And Source Handling

Evidence quality is central to the product.

Requirements:

- Store every evidence item with capture time and source publication time when available.
- Store every evidence item's earliest known availability time for time-aware research and backtesting.
- Preserve source URLs and local snapshots when possible.
- Distinguish reported facts, estimates, rumors, opinions, and model assumptions.
- Track source reliability and relevance separately.
- Make stale evidence visible in `forecast review`.
- Warn or block when a forecast update relies on stale evidence without acknowledging it.
- Require citations for non-trivial factual claims in forecast rationales.
- Show the forecast's "as of" timestamp in all user-facing probability displays.
- Exclude evidence whose `available_at` is after the forecast's `as_of` or backtest cutoff unless the user explicitly runs a non-historical retrospective analysis.

## Learning And Calibration

The system must learn from resolved forecasts through explicit scoring and diagnosis.

### Metrics

- Brier score.
- Log score when distributional scoring is implemented and applicable.
- Calibration by probability bucket.
- Sharpness.
- Accuracy by forecast horizon.
- Accuracy by domain.
- Accuracy by question type.
- Probability movement before close.
- Ensemble component contribution.
- Model-vs-human-vs-ensemble comparisons where baseline data is available.

### Postmortem Questions

Each resolved forecast should answer:

- What happened?
- What did the system expect?
- Which evidence was overweighted?
- Which evidence was missed?
- Was the base rate wrong?
- Was the inside view wrong?
- Was the resolution criterion misunderstood?
- What update rule or calibration prior should change?

### Calibration Memory

Durable memory should be structured around lessons such as:

- "The system has historically been overconfident on long-horizon political forecasts."
- "The system underweights regulatory delay in biotech approval questions."
- "Market-implied probabilities improved forecasts in high-liquidity election questions."

These lessons should be queryable by domain, horizon, question type, and model component.

Calibration lessons should be durable, provenance-linked objects. Each lesson should record scope, confidence, status, source postmortems, source score records, and supersession history so old or weak lessons can be retired instead of silently influencing future forecasts forever.

### Domain Error Tracking

The system should maintain domain and topic error profiles derived from scored forecasts and postmortems. These profiles should track recurring mistakes such as overconfidence, stale base rates, missed source classes, late evidence updates, and model-family failures.

Scheduled self-checks should use these profiles to decide what to review next. For example, if the system repeatedly underweights regulatory delay in biotech questions, a biotech self-check should inspect active biotech forecasts for assumptions that rely on optimistic approval timelines.

### Learning Provenance

Scores must carry provenance so the system does not confuse live performance with historical replay performance or imported baselines. `forecast_origin` distinguishes live forecasts, backtest replays, and imported baseline records. `calibration_eligible` and `calibration_weight` control whether a score can update calibration memory or domain error profiles.

Default policy:

- Live forecast scores are calibration-eligible.
- Backtest scores are calibration-eligible only when the run passes leakage checks and the user or configuration allows historical replay data to update calibration memory.
- Imported baselines are comparison records by default, not self-calibration data.
- Calibration reports must be able to show live-only, backtest-only, baseline-only, and combined views.

### Assumptions And Reference Classes

Assumptions and reference classes must be durable objects, not only prose inside a rationale. Scheduled self-checks should inspect them directly for stale evidence, invalidated claims, and outdated base rates.

Requirements:

- Assumptions store status, evidence refs, last check time, invalidation time, and check cadence.
- Reference classes store inclusion/exclusion criteria, base-rate estimate, uncertainty, source refs, status, and last check time.
- Forecast updates must cite which assumptions and reference classes drove the probability.
- Scheduled reviews can target stale assumptions and reference classes without rerunning the whole forecast.

## Backtesting

Backtesting must be treated as a first-class learning and benchmark workflow.

Requirements:

- Backtest runs must use an explicit forecast timestamp or timestamp range.
- Each backtest case must store its own simulated forecast timestamp, evidence cutoff, generated forecast snapshot, baseline outputs, score record, and leakage status.
- Evidence admissibility must be enforced with `available_at` or an equivalent source-specific availability timestamp.
- The system must record the evidence cutoff policy used for every backtest run.
- Backtests must flag or fail when an evidence item lacks enough timestamp metadata to prove it was available before the simulated forecast.
- Backtests must compare against available baselines such as base-rate-only models, market probabilities, crowd forecasts, and prior agent versions.
- Agent-protocol backtests must exclude answer-side dataset fields from the prompt and support captured JSON outputs so benchmark runs are repeatable without live model calls.
- Backtest run and case results must be stored so later calibration reports can distinguish live forecasts from historical replays.
- Backtest scores must not update live calibration memory unless the backtest run passes leakage checks and its calibration policy explicitly allows it.

## Resolution Governance

Resolution quality controls are required because bad resolutions can poison scoring, postmortems, and calibration memory.

Requirements:

- Resolutions must store resolver type, resolution status, source snapshot, criteria satisfaction, and confidence.
- Forecasts must not be scored until the resolution criteria are satisfied and the resolution status is confirmed.
- Scheduled checks may propose resolutions, but proposed resolutions require confirmation before scoring unless a trusted resolver plugin is configured.
- Trusted resolver plugins must be explicitly configured, scoped, versioned, and audited when they confirm resolutions automatically.
- Disputed or corrected resolutions must create correction records and invalidate or recompute affected scores, postmortems, and calibration lessons.
- Resolution source snapshots must be preserved so future audits can verify why a forecast was scored.

## Scheduled Self-Checks And Alerts

The fork should use Hermes-style cron/scheduler infrastructure where possible, but the jobs should be forecast-native.

Scheduled jobs should support:

- Active forecast review by close date, domain, topic, confidence, and evidence age.
- Watched-domain evidence scans.
- Resolution checks for questions past resolution time.
- Automatic scoring of newly resolved questions after user or resolver confirmation.
- Postmortem generation for misses, large forecast deltas, and high-impact resolutions.
- Calibration-memory updates after score/postmortem completion.
- Alerts when forecasts become stale, new evidence appears, assumptions are invalidated, or domain error profiles change.

Scheduled jobs must not silently mutate the current forecast probability. They may create evidence, alerts, suggested updates, scores, postmortems, and calibration lessons; probability changes still require an explicit forecast update record.

## Persistence Contract

The forecast ledger is the fork's learning substrate. It replaces generic chat memory as the durable source of truth for what the system believed, why it believed it, what happened, and what should change next time.

Requirements:

- Forecast snapshots are append-only.
- Past forecasts are corrected through explicit correction records, not silent mutation.
- Each forecast update stores probability, rationale, evidence refs, source snapshot refs, model refs, model/prompt/protocol versions, assumptions, and calibration adjustments.
- Each calibration adjustment links to the calibration lessons that influenced it.
- Each postmortem links to the forecast snapshot, resolution, score record, forecast origin, and calibration eligibility state it diagnoses.
- Each historical replay stores the backtest run, simulated forecast timestamp, evidence cutoff policy, and leakage-check result.
- Each resolved question can be traced from question definition through forecast history, evidence, model runs, resolution, scores, and postmortem.
- Calibration memory must be derived from eligible scored forecasts and postmortems, not from unscored chat claims or imported baselines.
- Scheduled self-checks may create alerts, evidence, scores, postmortems, and calibration lessons, but must not mutate past snapshots or silently replace the current forecast.

## User Stories

### US-001: Create A Scoreable Forecast Question

**Description:** As a forecaster, I want to create a forecast question with clear resolution criteria so that future predictions can be scored correctly.

**Acceptance Criteria:**

- [ ] `forecast new` creates a durable question record.
- [ ] The command captures title, resolution criteria, close time, resolution time, and outcome space.
- [ ] The system flags ambiguous or unscoreable questions before saving.
- [ ] The saved question can be shown with `forecast show <id>`.

### US-002: Import External Forecast Context

**Description:** As a forecaster, I want to ingest a URL or file so that the system can initialize a scoreable question and capture useful external context without depending on one platform.

**Acceptance Criteria:**

- [ ] `forecast ingest <url>` extracts candidate title, description, close time, resolution criteria, and source.
- [ ] If the source exposes forecasts, priors, posteriors, or crowd probabilities, those values are stored as baseline evidence or comparison records.
- [ ] The imported question requires confirmation before becoming active.
- [ ] The original URL is stored as an evidence item.
- [ ] Platform-specific importers such as Metaculus are optional adapters over the generic import flow.
- [ ] Ingestion failures produce actionable errors without creating partial active forecasts.

### US-003: Maintain An Append-Only Forecast Ledger

**Description:** As a forecaster, I want every probability update stored immutably so that I can audit how beliefs changed over time.

**Acceptance Criteria:**

- [ ] Every `forecast update` creates a new forecast snapshot.
- [ ] Prior snapshots are not overwritten.
- [ ] `forecast show <id>` displays current probability and recent forecast history.
- [ ] The ledger stores probability, rationale, assumptions, evidence refs, model refs, and timestamp.

### US-004: Run A Structured Research Pass

**Description:** As a forecaster, I want the agent to gather and organize evidence so that updates are based on current information.

**Acceptance Criteria:**

- [ ] `forecast research <id>` creates evidence items with timestamps and sources.
- [ ] Evidence items are classified by relevance, reliability, and directional stance.
- [ ] The research pass summarizes what changed since the previous forecast.
- [ ] The command does not update the probability unless explicitly requested or confirmed.

### US-005: Estimate Base Rates

**Description:** As a forecaster, I want the system to identify and estimate reference classes so that forecasts start from defensible priors.

**Acceptance Criteria:**

- [ ] `forecast base-rate <id>` proposes at least one reference class.
- [ ] Each reference class includes inclusion/exclusion logic.
- [ ] The command stores base-rate estimates as model runs.
- [ ] The forecast rationale can cite the selected base rate.

### US-006: Run Quantitative Models

**Description:** As a forecaster, I want to run probabilistic models so that numeric evidence can be incorporated consistently.

**Acceptance Criteria:**

- [ ] `forecast model <id>` records model type, parameters, inputs, outputs, and diagnostics.
- [ ] Model artifacts are linked from the forecast question.
- [ ] Model failures are stored separately from successful model runs.
- [ ] Forecast updates can include model outputs as ensemble components.

### US-007: Produce An Ensemble Forecast

**Description:** As a forecaster, I want forecasts to combine base rates, models, markets, and structured judgment so that no single component dominates silently.

**Acceptance Criteria:**

- [ ] `forecast update <id>` shows component probabilities and weights before saving.
- [ ] The saved snapshot includes all component weights.
- [ ] The update output shows prior probability, new probability, and delta.
- [ ] The system explains the strongest drivers of the probability change.

### US-008: Review Stale Forecasts

**Description:** As a forecaster, I want to see stale or evidence-sensitive forecasts so that active beliefs do not decay silently.

**Acceptance Criteria:**

- [ ] `forecast review --stale` lists active forecasts with stale evidence or approaching close dates.
- [ ] Review output can be scoped by domain, topic, and confidence for focused active books.
- [ ] Each stale forecast shows last update time, close time, and reason for review.
- [ ] The user can launch research or update flows from the review list.
- [ ] Forecasts with new evidence are prioritized above merely old forecasts.

### US-009: Resolve And Score Forecasts

**Description:** As a forecaster, I want resolved outcomes scored automatically so that performance can be measured.

**Acceptance Criteria:**

- [ ] `forecast resolve <id> --outcome <value>` records a resolution.
- [ ] `forecast score <id>` computes Brier score for binary/categorical forecasts.
- [ ] Log score is computed only when distributional scoring has been implemented and the forecast representation supports it.
- [ ] Scores are queryable by domain, horizon, and probability bucket.

### US-010: Generate Postmortems

**Description:** As a forecaster, I want the agent to diagnose resolved forecasts so that mistakes become reusable lessons.

**Acceptance Criteria:**

- [ ] `forecast postmortem <id>` creates a structured postmortem.
- [ ] The postmortem links to the diagnosed forecast snapshot, resolution, and score record.
- [ ] The postmortem compares expected and actual outcomes.
- [ ] The postmortem identifies likely sources of error.
- [ ] Lessons are stored as provenance-linked calibration lessons and can influence future forecasts only while active.

### US-011: Show Calibration Analytics

**Description:** As a forecaster, I want to see calibration and sharpness over time so that I know whether the system is improving.

**Acceptance Criteria:**

- [ ] `forecast calibration` displays Brier score, calibration buckets, sample counts, and log score when distributional scoring is implemented and applicable.
- [ ] The command supports filtering by domain and forecast horizon.
- [ ] Empty or low-sample buckets are clearly marked.
- [ ] The output distinguishes accuracy from sharpness.
- [ ] `forecast errors` displays recurring error patterns and recommended calibration adjustments by domain/topic.

### US-012: Export An Auditable Forecast Packet

**Description:** As a forecaster, I want to export a forecast with its evidence and model history so that it can be reviewed outside the CLI.

**Acceptance Criteria:**

- [ ] `forecast export <id>` writes a markdown or JSON packet.
- [ ] The export includes question metadata, forecast history, evidence, model runs, and scores if resolved.
- [ ] Exported files include generation time and "as of" timestamps.
- [ ] Sensitive local credentials or unrelated session data are not included.

### US-013: Run Time-Aware Backtests

**Description:** As a forecaster, I want to replay resolved questions under historical evidence constraints so that benchmark results reflect information that was actually available at forecast time.

**Acceptance Criteria:**

- [ ] `forecast backtest <dataset>` records a durable backtest run.
- [ ] Each simulated forecast has an explicit forecast timestamp and evidence cutoff.
- [ ] Each simulated forecast stores a backtest case with generated forecast, score, baseline refs, and leakage status.
- [ ] Evidence with `available_at` after the cutoff is excluded from the run.
- [ ] The run flags evidence with missing or ambiguous availability metadata.
- [ ] Results compare the agent against at least one baseline when baseline data is available.
- [ ] Recent backtest runs can be summarized from the CLI with agent-vs-baseline Brier edge.

### US-014: Schedule Scoped Self-Checks

**Description:** As a forecaster, I want scheduled self-checks by question, domain, topic, forecast horizon, or portfolio so that stale forecasts, resolved outcomes, and recurring errors are surfaced automatically.

**Acceptance Criteria:**

- [ ] `forecast schedule add --domain <domain> --cadence <duration>` creates a durable scheduled review.
- [ ] `forecast schedule add --horizon <days|range> --cadence <duration>` creates a durable scheduled review for active forecasts in that horizon band.
- [ ] Scheduled reviews can persist a per-review stale-evidence threshold.
- [ ] Scheduled reviews can scan active forecasts for stale evidence, upcoming close dates, and invalidated assumptions.
- [ ] Scheduled reviews can detect resolved questions and queue scoring/postmortem work.
- [ ] Scheduled reviews can explicitly opt into automatic scoring and auto-created postmortem learning records.
- [ ] Scheduled reviews create alerts or suggested updates rather than silently changing current probabilities.
- [ ] Completed scoring/postmortems update domain or topic error profiles.
- [ ] Scheduled reviews can be scoped to a question, domain/topic, or portfolio.

### US-015: Govern Resolutions Before Learning

**Description:** As a forecaster, I want resolutions confirmed against their criteria before scores update calibration memory so that bad or disputed outcomes do not poison future forecasts.

**Acceptance Criteria:**

- [ ] Proposed resolutions store resolver type, source snapshot, criteria satisfaction, and confidence.
- [ ] `forecast score <id>` refuses to score unconfirmed or disputed resolutions.
- [ ] Resolution corrections create correction records instead of mutating historical scores silently.
- [ ] Corrected resolutions trigger recomputation or invalidation of affected scores, postmortems, and calibration lessons.

## Functional Requirements

- FR-1: The system must store forecast questions as durable, queryable records.
- FR-2: The system must support binary, categorical, numeric, and distributional outcome spaces.
- FR-3: The system must store forecast snapshots append-only.
- FR-4: The system must link evidence items to forecast questions and forecast snapshots.
- FR-5: The system must preserve an "as of" timestamp for every displayed probability.
- FR-6: The system must support source capture from URLs, files, and manual notes.
- FR-7: The system must distinguish evidence capture from probability updates.
- FR-8: The system must store model runs with inputs, parameters, outputs, and diagnostics.
- FR-9: The system must compute Brier scores for scoreable binary and categorical forecasts.
- FR-10: After binary/categorical scoring is stable, the system should compute log scores when full probability distributions are available.
- FR-11: The system must generate calibration reports grouped by probability bucket, domain, and horizon.
- FR-12: The system must generate postmortems for resolved forecasts.
- FR-13: The system must expose forecasting workflows as first-class CLI commands.
- FR-14: The system must keep generic chat subordinate to forecast workflows.
- FR-15: The system must support import/export of forecast packets.
- FR-16: The system must allow future plugins for data sources, prediction markets, model families, and tournament platforms.
- FR-17: The system must store model, prompt, protocol, and toolset version metadata for every forecast update.
- FR-18: The system must support model-vs-human-vs-ensemble comparison records when external baselines are available.
- FR-19: The system must support explicit correction records for mistaken historical entries without mutating prior snapshots.
- FR-20: The system must store evidence availability timestamps and enforce evidence cutoffs in historical replays.
- FR-21: The system must store durable backtest runs with leakage-check results and baseline comparisons.
- FR-22: The system must support scheduled self-checks by question, domain, topic, forecast horizon, and portfolio.
- FR-23: The system must create alert events for stale forecasts, new evidence, invalidated assumptions, and newly resolved questions.
- FR-24: The system must maintain domain/topic error profiles derived from scored forecasts and postmortems.
- FR-25: The system must distinguish live forecasts, backtest replays, and imported baselines in forecast snapshots, score records, and calibration reports.
- FR-26: The system must store calibration eligibility and weighting policy for every score record.
- FR-27: The system must store assumptions and reference classes as durable, checkable objects.
- FR-28: The system must prevent unconfirmed, disputed, or criteria-incomplete resolutions from updating scores or calibration memory.
- FR-29: The system must store calibration lessons as durable, provenance-linked objects with scope, status, confidence, and supersession history.
- FR-30: The system must link postmortems to the forecast snapshot, resolution, and score record they diagnose.
- FR-31: The system must link calibration adjustments to the calibration lessons that influenced them.
- FR-32: The system must store correction records for non-mutating fixes to forecasts, evidence, assumptions, reference classes, resolutions, scores, postmortems, and calibration lessons.
- FR-33: The system must audit trusted resolver plugins by scope, version, approval, and automatic confirmation event.

## V1 Outcome And Scoring Scope

The ledger should represent binary, categorical, numeric, and distributional outcome spaces from the start so the product can handle any scoreable question. Initial scoring support should prioritize binary and categorical forecasts because they are enough to validate the ledger, calibration loop, and backtesting pipeline.

Numeric and distributional forecasts should be stored and exported in v1, but their scoring rules can be phased in after the binary/categorical loop is working. Candidate scoring rules include log score for full distributions and CRPS or interval scores for numeric forecasts.

## Technical Architecture

### Proposed Package Layout

```text
forecasting/
  questions.py
  outcome_space.py
  ledger.py
  evidence.py
  research.py
  base_rates.py
  assumptions.py
  reference_classes.py
  models.py
  ensembles.py
  scoring.py
  calibration.py
  postmortems.py
  backtesting.py
  baselines.py
  scheduler.py
  alerts.py
  error_profiles.py
  corrections.py
  resolvers.py
  importers/
  exporters/
  cli/
```

### Storage

Use SQLite initially, following the existing Hermes local-first posture. Forecast data should be normalized enough to query by status, domain, horizon, evidence age, score, and calibration bucket.

Required tables:

- `forecast_questions`
- `forecast_snapshots`
- `evidence_items`
- `assumptions`
- `reference_classes`
- `model_runs`
- `resolutions`
- `score_records`
- `postmortems`
- `calibration_lessons`
- `forecast_corrections`
- `trusted_resolver_policies`
- `baseline_comparisons`
- `backtest_runs`
- `backtest_cases`
- `scheduled_reviews`
- `watched_sources`
- `alert_events`
- `domain_error_profiles`

### Agent Loop Changes

The core loop should be re-prompted and wrapped around forecasting protocols. Tool access should be narrowed by workflow stage:

- Question parsing: file/web input, no update writes until confirmed.
- Research: browser/web/MCP/file tools, evidence writes allowed.
- Modeling: terminal/code execution, model-run writes allowed.
- Update: ledger write allowed after forecast preview.
- Resolution: score write allowed only after criteria satisfaction and resolution confirmation.
- Backtesting: evidence/model access restricted by the simulated forecast timestamp.
- Scheduled self-checks: evidence, alert, score, postmortem, and calibration writes allowed; probability updates require explicit forecast snapshots.

### Prompting

System prompts should require:

- Explicit uncertainty.
- Base-rate-first reasoning.
- Separation of evidence from interpretation.
- Forecast deltas.
- Assumption tracking.
- Source timestamp awareness.
- Time-aware evidence admissibility.
- Assumption and reference-class status awareness.
- Calibration humility.
- Resolution criteria discipline.
- Postmortem discipline.
- Error-profile awareness by domain, topic, horizon, and question type.

### Plugins

Plugin categories should be forecast-specific:

- Data source plugins.
- Prediction market plugins.
- Forecasting platform importers.
- Statistical model plugins.
- Resolution-source plugins.
- Alert delivery plugins.
- Calibration visualizer plugins.

Generic plugins can remain installable, but the default product should expose only plugins that improve forecasting workflows.

## Quality Gates

These commands should pass for every implementation story unless the story is docs-only:

```bash
scripts/run_tests.sh -q
python3 -m compileall -q forecasting
```

For focused stories, run the narrowest relevant test set first, then the full gate before merge:

```bash
scripts/run_tests.sh tests/forecasting -q
scripts/run_tests.sh tests/hermes_cli -q
```

For CLI/TUI stories, include a manual verification transcript that shows the command, output, and resulting ledger changes.

For docs-only changes, verify the markdown renders cleanly and links point to existing files.

## Milestones

### M0: Fork Definition

- Rename product metadata and CLI branding.
- Document keep/cut/demote decisions.
- Disable gateway-first surfaces by default.
- Add the `forecast` command namespace with placeholder help.
- Link implementation work back to the fork context doc so product surgery stays anchored to the forecast-first thesis.

### M1: Forecast Ledger

- Add forecast question, outcome space, snapshot, evidence, and resolution storage.
- Implement `forecast new`, `forecast list`, `forecast show`, and `forecast update`.
- Enforce append-only snapshots.

### M2: Evidence And Research

- Implement URL/file/manual evidence capture.
- Add `forecast research` and `forecast evidence` commands.
- Store source metadata and evidence stance.
- Display stale evidence and pending review flags.

### M3: Models And Ensembles

- Implement base-rate model runs.
- Add simple Bayesian update helpers.
- Add ensemble forecast previews.
- Store model runs and ensemble weights.

### M4: Resolution And Calibration

- Implement resolution records.
- Add Brier scoring for binary/categorical forecasts.
- Add calibration reports.
- Add structured postmortems and calibration lessons.
- Add domain/topic error profiles derived from scored forecasts and postmortems.
- Add resolution governance so only confirmed, criteria-satisfied resolutions can update scoring and calibration.
- Add correction records and trusted resolver audit policy.

### M5: Backtesting And Benchmarking

- Import resolved question datasets.
- Replay historical forecasts under time-aware constraints.
- Enforce evidence cutoff and leakage checks for every replay.
- Store per-question backtest cases with simulated timestamp, generated snapshot, baselines, score, and leakage status.
- Compare against baselines and simple ensembles.
- Produce performance reports by domain and horizon.
- Keep live, backtest, and imported baseline calibration views separate by default.

### M6: Scheduled Self-Checks And Alerts

- Add scheduled review jobs for active forecasts, domains, topics, and portfolios.
- Add alert events for stale forecasts, new evidence, invalidated assumptions, and resolved questions.
- Add global self-check alerts for benchmark evidence gaps that still block
  live-superiority claims.
- Add self-check flows that queue scoring, postmortems, and calibration-memory updates.
- Add watched-source checks that create alerts when monitored files or adapter sources change.
- Ensure scheduled jobs cannot silently overwrite forecast probabilities.

### M7: Benchmark And Platform Adapters

- Add importers/exporters for forecasting platforms where terms permit, without making any platform required.
- Add prediction-market connectors.
- Add generic benchmark importers for resolved-question datasets.
- Add external-source monitoring adapters and local watched-source feeds that can trigger scheduled self-check alerts.

## Success Metrics

- A user can create, research, update, resolve, score, and postmortem a forecast entirely from the CLI.
- Every stored forecast has a current probability, history, evidence, and "as of" timestamp.
- The system can produce calibration reports over at least 100 resolved binary forecasts.
- Backtests show improvement over naive base-rate and uncalibrated LLM-only baselines.
- Backtests report evidence-cutoff and leakage-check status.
- Scheduled self-checks detect stale forecasts and newly resolved questions without silently changing probabilities.
- Domain/topic error profiles show recurring mistakes and recommended calibration adjustments.
- Users can inspect recurring error patterns from the CLI.
- Calibration reports can separate live forecasts, backtest replays, imported baselines, and combined views.
- Unconfirmed or disputed resolutions cannot update calibration memory.
- Users can identify stale forecasts in under one command.
- Forecast packets are auditable without reading raw database rows.
- The product's default screen communicates active beliefs and required updates, not generic chat history.

## Risks

- Forecast quality may appear better in demos than in true time-aware backtests.
- Source ingestion can leak stale or post-resolution evidence into historical simulations.
- Scheduled jobs can create alert fatigue or over-update pressure if priorities are not tuned.
- Weak timestamp metadata can make some backtests unusable or misleading.
- LLM rationales may sound precise while probability estimates remain poorly calibrated.
- Overfitting calibration lessons to small resolved samples can degrade performance.
- Prediction market data may be unavailable, expensive, or legally constrained.
- Broad Hermes functionality may distract from the forecasting product unless aggressively hidden.

## Open Questions

- What should the fork be named?
- Should the first storage layer reuse `hermes_state.py` patterns or start with a separate `forecasting/ledger.py` database?
- Which resolved dataset should be the first benchmark source?
- Which optional platform adapter should come first: Metaculus, prediction markets, or a generic resolved-question dataset importer?
- Which numeric/distributional scoring rules should be implemented first after binary/categorical scoring?
- What default self-check cadences should apply by domain, topic, impact, and forecast horizon?
- Should the CLI support multi-user/team forecasts in v1?
- What data providers are acceptable for finance, politics, macro, and science domains?
- How much of Hermes gateway support should be deleted from the fork versus kept behind optional extras?
