# Superforecasting Agent CLI/TUI Verification Transcript

Date: 2026-05-23

This transcript records a real local verification run against an isolated
temporary ledger:

```text
/private/tmp/sfa-manual-verification-20260523.db
```

The run used no model calls and no external APIs. Its purpose is to satisfy the
PRD quality gate that CLI/TUI stories include command output and resulting
ledger changes.

## CLI Lifecycle

### Create a scoreable question

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast new "Will the test feature ship by 2026-06-30?" --description "Verification transcript question for the fork PRD." --resolution-criteria "Resolves yes if a tagged release includes the test feature by 2026-06-30 23:59 UTC; otherwise no." --resolution-source "local release notes" --outcome-type binary --close-time 2026-06-30T23:59:00Z --resolution-time 2026-07-01T12:00:00Z --domain software --topic releases --impact medium --review-cadence 7d --next-review-at 2026-05-30T09:00:00Z
```

```text
created forecast question fq_3fec78ab6ed8
title: Will the test feature ship by 2026-06-30?
status: active
```

Ledger change: created `ForecastQuestion` `fq_3fec78ab6ed8` with binary
outcome space, resolution criteria, domain `software`, topic `releases`, close
time, resolution time, and review cadence.

### Add timestamped evidence

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast evidence add fq_3fec78ab6ed8 "Internal milestone note says the implementation branch has passed focused tests but still needs pilot review." --claim "Focused tests are passing, but tester pilot review is still pending." --claim-type fact --summary "Local implementation status as of the verification run." --source-name "verification transcript" --source-type manual_note --published-at 2026-05-23T10:00:00Z --available-at 2026-05-23T10:00:00Z --reliability 0.70 --relevance 0.80 --stance mixed
```

```text
added evidence ev_1ec1a36a7a0d
available_at: 2026-05-23T10:00:00Z
stance: mixed
claim_type: fact
```

Ledger change: created evidence item `ev_1ec1a36a7a0d` with distinct
`published_at`/`available_at` timestamps, claim type, reliability, relevance,
and stance.

### Store a base rate and model run

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast base-rate fq_3fec78ab6ed8 --name "Small maintained feature branches" --inclusion-criteria "Small features in maintained repos after focused tests pass." --exclusion-criteria "Large rewrites or features blocked on external vendors." --base-rate 0.62 --uncertainty 0.15 --source-ref ev_1ec1a36a7a0d --check-cadence 7d --notes "Verification sample uses illustrative base rate only."
```

```text
reference_class: rc_d938abb0b4d7
base_rate: 0.62
model_run: mr_597889a1bf8d
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast model fq_3fec78ab6ed8 --type bayesian_update --input-json "{\"prior\":0.62,\"evidence\":\"tests passing but pilot pending\"}" --parameters-json "{\"likelihood_if_true\":0.75,\"likelihood_if_false\":0.45}" --prior 0.62 --likelihood-if-true 0.75 --likelihood-if-false 0.45 --model-version verification-v1 --data-version 2026-05-23 --evidence-cutoff 2026-05-23T10:00:00Z
```

```text
model_run: mr_ab3695c1d8ba
type: bayesian_update
status: success
evidence_cutoff: 2026-05-23T10:00:00Z
posterior: 0.731
```

Ledger change: created reference class `rc_d938abb0b4d7`, base-rate model run
`mr_597889a1bf8d`, and Bayesian model run `mr_ab3695c1d8ba` with explicit
inputs, parameters, data version, model version, and evidence cutoff.

### Preview and save an ensemble forecast

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast update fq_3fec78ab6ed8 --probability 0.70 --confidence 0.63 --method weighted_ensemble --component-json "{\"base_rate\":{\"probability\":0.62,\"weight\":0.45},\"bayesian_update\":{\"probability\":0.731,\"weight\":0.55}}" --rationale "Focused verification evidence supports shipping, while unresolved pilot review keeps probability below the model posterior." --evidence-ref ev_1ec1a36a7a0d --reference-class-ref rc_d938abb0b4d7 --model-run-ref mr_ab3695c1d8ba --agent-model none --prompt-version manual-transcript --protocol-version forecasting-protocol-v1 --toolset-version forecast-desk --as-of 2026-05-23T10:10:00Z --preview
```

```text
forecast update preview
previous_as_of: -
previous_probability: -
proposed_as_of: 2026-05-23T10:10:00Z
proposed_probability: 0.700
delta: -
ensemble_components: 2
strongest_driver: base_rate pull=-0.036
component_drivers:
  base_rate p=0.620 w=0.45 contribution=0.279 pull=-0.036
  bayesian_update p=0.731 w=0.55 contribution=0.402 pull=+0.017
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast update fq_3fec78ab6ed8 --probability 0.70 --confidence 0.63 --method weighted_ensemble --component-json "{\"base_rate\":{\"probability\":0.62,\"weight\":0.45},\"bayesian_update\":{\"probability\":0.731,\"weight\":0.55}}" --rationale "Focused verification evidence supports shipping, while unresolved pilot review keeps probability below the model posterior." --evidence-ref ev_1ec1a36a7a0d --reference-class-ref rc_d938abb0b4d7 --model-run-ref mr_ab3695c1d8ba --agent-model none --prompt-version manual-transcript --protocol-version forecasting-protocol-v1 --toolset-version forecast-desk --as-of 2026-05-23T10:10:00Z
```

```text
created forecast snapshot fs_5f77a91ec2ca
question: fq_3fec78ab6ed8
as_of: 2026-05-23T10:10:00Z
probability: 0.700
ensemble_components: 2
strongest_driver: base_rate pull=-0.036
component_drivers:
  base_rate p=0.620 w=0.45 contribution=0.279 pull=-0.036
  bayesian_update p=0.731 w=0.55 contribution=0.402 pull=+0.017
```

Ledger change: appended forecast snapshot `fs_5f77a91ec2ca` with as-of time,
probability, confidence, rationale, evidence/reference/model refs, model/prompt
protocol metadata, and ensemble components.

### Inspect the ledger state

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast show fq_3fec78ab6ed8
```

```text
Will the test feature ship by 2026-06-30?
id: fq_3fec78ab6ed8
status: active
domain: software
outcome: binary ['yes', 'no']
close_time: 2026-06-30T23:59:00Z
resolution_time: 2026-07-01T12:00:00Z
resolution_criteria: Resolves yes if a tagged release includes the test feature by 2026-06-30 23:59 UTC; otherwise no.

current_forecast:
  id: fs_5f77a91ec2ca
  as_of: 2026-05-23T10:10:00Z
  probability: 0.700
  confidence: 0.63
  origin: live
  rationale: Focused verification evidence supports shipping, while unresolved pilot review keeps probability below the model posterior.

recent_history:
  2026-05-23T10:10:00Z fs_5f77a91ec2ca 0.700

evidence_count: 1
```

### Run scheduled self-checks and learning loop

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast resolve fq_3fec78ab6ed8 --outcome yes --source "local release notes" --resolver-type manual --status confirmed --criteria-satisfied --confidence 0.95 --confirmed-by verifier --notes "Verification transcript resolves the sample question as yes to exercise scoring."
```

```text
recorded resolution rs_423f8a6390ca
status: confirmed
criteria_satisfied: True
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast schedule add --question fq_3fec78ab6ed8 --cadence 1d --next-run-at 2026-05-23T10:25:00Z --stale-days 0 --trigger-reason resolved-verification --auto-score --auto-postmortem
```

```text
scheduled review sr_38f153c8b0e1
scope: question fq_3fec78ab6ed8
next_run_at: 2026-05-23T10:25:00Z
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast schedule run --now 2026-05-23T10:30:00Z --auto-score --auto-postmortem
```

```text
ran 1 scheduled review(s)
created 2 alert(s)
sr_38f153c8b0e1 next_run_at=2026-05-24T10:30:00Z alerts=2
  al_4489cec2bf43 question:fq_3fec78ab6ed8 score_created:sc_5c5bc655fd0e
  al_5535c44de722 question:fq_3fec78ab6ed8 postmortem_created:pm_1ad8271c13a0
```

Ledger change: confirmed resolution `rs_423f8a6390ca`; scheduled review
`sr_38f153c8b0e1`; score `sc_5c5bc655fd0e`; auto postmortem
`pm_1ad8271c13a0`; alert events `al_4489cec2bf43` and `al_5535c44de722`.
The scheduled job advanced to `2026-05-24T10:30:00Z` without mutating the
standing probability.

### Create and activate a calibration lesson

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast postmortem fq_3fec78ab6ed8 --summary "Manual learning note after the scheduled self-check." --what-happened "The sample forecast resolved yes." --what-was-expected "The ledger held a 0.70 live probability." --lesson "When tests pass but pilot review is pending, keep the probability below the model posterior until tester evidence arrives." --calibration-adjustment-json "{\"probability_delta\":-0.03,\"applies_when\":\"pilot review pending\"}"
```

```text
postmortem: pm_d118fe70851c
score_record: sc_5c5bc655fd0e
calibration_lesson: created
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast lesson status cl_024256e30675 --status active
```

```text
calibration_lesson: cl_024256e30675
status: active
confidence: 0.5
```

Ledger change: created manual postmortem `pm_d118fe70851c`, calibration lesson
`cl_024256e30675`, and promoted it to active for domain-scoped future updates.

### Inspect scoring, calibration, and export packet

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast scores --domain software
```

```text
ID             Brier     Log       Proper    Rule                         Bucket   Horizon  Origin             Domain    Invalidated
sc_5c5bc655fd0e 0.0900    0.3567    0.0900    brier                        0.7-0.8  38.6d    live               software  -
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast calibration --domain software --by-origin
```

```text
origin: combined
count: 1
mean_brier: 0.090000
mean_log_score: 0.356675
mean_sharpness: 0.400000

origin: live
count: 1
mean_brier: 0.090000
mean_log_score: 0.356675
mean_sharpness: 0.400000
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast export fq_3fec78ab6ed8 --format markdown
```

Selected packet output:

```text
## Current Forecast
- Forecast ID: `fs_5f77a91ec2ca`
- As of: 2026-05-23T10:10:00Z
- Probability/distribution: `0.7`

## Evidence
- 2026-05-23T10:00:00Z: verification transcript - Focused tests are passing, but tester pilot review is still pending.

## Scores
- 2026-05-23T22:55:27Z: Brier=0.09000000000000002, bucket=0.7-0.8, origin=live

## Calibration Lessons
- cl_024256e30675 active: When tests pass but pilot review is pending, keep the probability below the model posterior until tester evidence arrives.
```

### Backtest and readiness guard

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast backtest builtin:mini-binary --probability-source forecast-engine
```

```text
backtest_run: bt_09de19d36792
cases: 5
scored_cases: 5
leakage_checks_passed: True
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast performance --last 3
```

```text
ID             Dataset                  Cases  AgentBrier  BestBaseline           AgentEdge  Leakage
bt_09de19d36792 builtin:mini-binary      5      0.130174    base_rate:dataset=0.14 +0.020     True
  claim benchmark_replay_only: Benchmark replay evidence only; live superiority requires repeated agent-generated forecasts on held-out or live questions.
evidence insufficient_live_evidence: live_scored=1 agent_protocol_scored=0 leakage_free_runs=1 positive_edge_runs=1 datasets=1
```

```bash
python3 -m superforecasting_agent --db /private/tmp/sfa-manual-verification-20260523.db forecast readiness --last 3
```

```text
readiness insufficient_live_evidence: Stored evidence is not enough for a live superforecasting claim.
claim_live_superforecasting: False
evidence insufficient_live_evidence: live_scored=1 agent_protocol_scored=0 leakage_free_runs=1 positive_edge_runs=1 datasets=1
  gap live_scored_forecasts: 1/100
  gap agent_protocol_scored_cases: 0/100
  ok leakage_free_backtest_runs: 1/1
  ok positive_best_baseline_edge_runs: 1/1
  gap distinct_backtest_datasets: 1/2
```

Ledger change: stored backtest run `bt_09de19d36792`, five scored historical
cases, leakage status, performance-vs-baseline summary, and an explicit
readiness guard that blocks live-superforecasting claims.

## TUI Shortcut Verification

The TUI route test verifies that forecast desk panels and gateway events render
the forecast lifecycle shortcuts, evidence imports, alerts, readiness,
assumption/reference-class review signals, and focused actions used by the CLI
workflow above.

```bash
cd ui-tui
npm test -- src/__tests__/forecastPanel.test.ts src/__tests__/createGatewayEventHandler.test.ts
```

```text
> superforecasting-agent-tui@0.0.1 test
> vitest run src/__tests__/forecastPanel.test.ts src/__tests__/createGatewayEventHandler.test.ts

 Test Files  2 passed (2)
      Tests  50 passed (50)
```

## Result

This run demonstrates a complete local CLI loop:

- create a scoreable question
- capture timestamped evidence
- store reference classes and model runs
- preview and append an ensemble forecast snapshot
- inspect the active forecast book
- resolve, score, and postmortem after confirmation
- create and activate calibration memory
- run a scheduled self-check without mutating probability
- run time-aware benchmark replay with leakage status
- keep benchmark/live-superiority claims gated by evidence readiness
- verify the TUI forecast panel and gateway rendering path, including stale
  assumption and reference-class desk signals
