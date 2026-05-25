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
[forecast-smoke] snapshot: 7e8956498d58 (main)
[forecast-smoke] ledger: /var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-agent-smoke-ihgegz_n/forecasting-smoke.db
[forecast-smoke] source_adapters: 52
[forecast-smoke] benchmark_datasets: 4
[forecast-smoke] question_id: fq_3d1ea8575de7
[forecast-smoke] evidence_id: ev_ecfe35990c9f
[forecast-smoke] reference_class_id: rc_295ccec6b0d4
[forecast-smoke] model_run_id: mr_0b25539cb24c
[forecast-smoke] scheduled_self_check_question_id: fq_5b7624e4adf0
[forecast-smoke] pilot_cohort_dry_run_questions: 1
[forecast-smoke] pilot_cohort_example_questions: 5
[forecast-smoke] pilot_report_checks: 7/7
[forecast-smoke] pilot_aggregate_live_scores: 1
[forecast-smoke] backtest_run_id: bt_4395b2fa2750
[forecast-smoke] agent_protocol_backtest_run_id: bt_16d64e280e03
[forecast-smoke] performance_runs: 2
[forecast-smoke] readiness_verdict: insufficient_live_evidence
[forecast-smoke] readiness_gaps: 3
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
- Aggregates a pilot export containing one scored live forecast.
- Generates a pilot handoff bundle containing pilot-report, readiness, and
  export data.
- Runs deterministic benchmark replay and agent-protocol replay paths.
- Produces a performance summary and readiness verdict.

The readiness verdict is intentionally `insufficient_live_evidence`; the smoke
test proves the workflow and evidence plumbing, not live superforecasting
performance.
