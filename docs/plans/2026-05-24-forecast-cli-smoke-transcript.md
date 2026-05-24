# Forecast CLI Smoke Transcript

Date: 2026-05-24

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
[forecast-smoke] ledger: /var/folders/5x/7hym3yzn05z0k_z3g1m17brc0000gn/T/superforecasting-agent-smoke-oqrewvgq/forecasting-smoke.db
[forecast-smoke] source_adapters: 47
[forecast-smoke] benchmark_datasets: 4
[forecast-smoke] question_id: fq_8a002f955f52
[forecast-smoke] evidence_id: ev_3e41e8c9a00f
[forecast-smoke] reference_class_id: rc_95b151558ec7
[forecast-smoke] model_run_id: mr_175bbc081163
[forecast-smoke] scheduled_self_check_question_id: fq_054edffde0d2
[forecast-smoke] pilot_cohort_dry_run_questions: 1
[forecast-smoke] pilot_cohort_example_questions: 5
[forecast-smoke] pilot_report_checks: 7/7
[forecast-smoke] pilot_aggregate_live_scores: 1
[forecast-smoke] backtest_run_id: bt_4ec03cdd604a
[forecast-smoke] agent_protocol_backtest_run_id: bt_fb6e42788da8
[forecast-smoke] performance_runs: 2
[forecast-smoke] readiness_verdict: insufficient_live_evidence
[forecast-smoke] readiness_gaps: 2
[forecast-smoke] forecast smoke test passed
```

## Ledger Effects Verified

- Creates an isolated SQLite forecast ledger.
- Discovers source adapters and packaged benchmark datasets.
- Creates a scoreable forecast question.
- Adds evidence, a reference class, and a model run.
- Creates a scheduled self-check question.
- Validates both a one-question pilot dry run and the checked-in five-question
  starter pilot cohort.
- Generates a pilot report with all required checks passing.
- Aggregates a pilot export containing one scored live forecast.
- Runs deterministic benchmark replay and agent-protocol replay paths.
- Produces a performance summary and readiness verdict.

The readiness verdict is intentionally `insufficient_live_evidence`; the smoke
test proves the workflow and evidence plumbing, not live superforecasting
performance.
