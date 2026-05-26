# Forecast CLI Smoke Transcript

Date: 2026-05-25

Purpose: capture a concrete CLI verification transcript for the
Superforecasting Agent fork tester path. The smoke script creates an isolated
temporary ledger, runs the core forecast lifecycle, exercises the starter pilot
cohort path, and runs replay/backtest readiness checks. Generated ids and the
temporary ledger path vary between runs.

## Command

```bash
python3 scripts/forecast_smoke_test.py
```

## Observed Output

```text
[forecast-smoke] snapshot: 3b9006319c2f (main)
[forecast-smoke] ledger: /var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-agent-smoke-ekie3_bp/forecasting-smoke.db
[forecast-smoke] source_adapters: 52
[forecast-smoke] benchmark_datasets: 4
[forecast-smoke] question_id: fq_88cf7555cd35
[forecast-smoke] evidence_id: ev_e0549b8752d0
[forecast-smoke] reference_class_id: rc_fe05a081792d
[forecast-smoke] model_run_id: mr_7fc9de8ef8fe
[forecast-smoke] scheduled_self_check_question_id: fq_b83562457cc6
[forecast-smoke] pilot_cohort_dry_run_questions: 1
[forecast-smoke] pilot_cohort_example_questions: 5
[forecast-smoke] pilot_report_checks: 9/9
[forecast-smoke] packet_import_questions: 2
[forecast-smoke] pilot_aggregate_live_scores: 1
[forecast-smoke] backtest_run_id: bt_e2eefdf00b62
[forecast-smoke] agent_protocol_backtest_run_id: bt_8635c95c60ae
[forecast-smoke] performance_runs: 2
[forecast-smoke] readiness_verdict: insufficient_live_evidence
[forecast-smoke] readiness_gaps: 4
[forecast-smoke] live_baseline_comparisons: 1
[forecast-smoke] doctor_status: tester_handoff_ready_live_claim_unproven
[forecast-smoke] pilot_bundle_export_included: true
[forecast-smoke] forecast smoke test passed
```

## Ledger Effects Verified

- Creates an isolated SQLite forecast ledger.
- Prints the source snapshot used for the tester evidence bundle.
- Discovers source adapters and packaged benchmark datasets.
- Creates a scoreable forecast question.
- Adds evidence, a reference class, and a model run.
- Creates a scheduled self-check question.
- Validates both a one-question pilot dry run and the checked-in five-question
  starter pilot cohort.
- Generates a pilot report with all required checks passing.
- Restores the exported forecast packet into a clean ledger.
- Aggregates a pilot export containing one scored live forecast.
- Generates a pilot handoff bundle containing pilot-report, readiness, and
  export data.
- Runs deterministic benchmark replay and agent-protocol replay paths.
- Produces a performance summary and readiness verdict.

The readiness verdict is intentionally `insufficient_live_evidence`; the smoke
test proves the workflow and evidence plumbing, not live superforecasting
performance.
