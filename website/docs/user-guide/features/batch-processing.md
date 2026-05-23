---
sidebar_position: 12
title: "Batch Processing"
description: "Run forecast backtests, benchmark suites, and trajectory jobs at scale."
---

# Batch Processing

Batch processing is the forecast desk's offline evaluation surface. Use it to
replay resolved questions, compare the local forecast engine against baselines,
measure calibration by domain and horizon, and regression-test prompt or model
changes before trusting them on live questions.

There are two batch paths:

- `forecast backtest` writes scoreable replay runs into the forecast ledger.
- `batch_runner.py` runs raw prompts in parallel and writes trajectory data for
  protocol evaluation, tooling checks, or training data.

For forecasting quality, prefer `forecast backtest`. Raw trajectories are useful
diagnostics, but they are not calibration records until converted into resolved,
time-aware forecast cases.

## Quick Start

List packaged replay datasets:

```bash
forecast backtest --benchmarks
```

Run every packaged benchmark with the deterministic local forecast engine:

```bash
forecast backtest --all-benchmarks --probability-source forecast-engine
```

Replay a frozen public market corpus and inspect the result:

```bash
forecast backtest builtin:manifold-public-120-binary \
  --probability-source forecast-engine

forecast backtest --list
forecast backtest --show <backtest_run_id>
forecast performance --last 10
```

Run a raw parallel trajectory batch:

```bash
python batch_runner.py \
  --dataset_file=data/forecast_prompts.jsonl \
  --batch_size=10 \
  --run_name=forecast_protocol_eval_v1 \
  --distribution=research \
  --model=anthropic/claude-sonnet-4.6 \
  --num_workers=4
```

## Forecast Backtesting

`forecast backtest` is the closed feedback-loop path:

1. Load resolved historical cases.
2. Recreate each question with a simulated forecast time.
3. Admit only evidence available at or before the cutoff.
4. Create a backtest forecast snapshot.
5. Resolve and score the snapshot.
6. Compare against naive, base-rate, crowd, market, or imported baselines.
7. Store the run in the ledger for calibration, performance review, and lessons.

Backtests are durable ledger records. They appear in `forecast performance`, the
forecast dashboard summary, calibration views, and exported audit packets.

### Probability Sources

| Source | Use when |
| --- | --- |
| `dataset` | The dataset already includes the probability to replay. |
| `baseline-ensemble` | The dataset includes explicit market, crowd, base-rate, or other baseline probabilities and you want a deterministic ensemble. |
| `forecast-engine` | You want the local desk engine to generate a probability from pre-cutoff baselines, evidence stance metadata, base rates, and fixed extremization. |
| `agent-protocol` | You want the forecast protocol to generate probabilities through live `AIAgent` calls or replay captured agent JSON outputs for deterministic evaluation. |
| `naive` | You want a 0.5 binary control baseline. |

Example:

```bash
forecast backtest builtin:heldout-120-binary \
  --probability-source forecast-engine
```

For agent-protocol evaluations, use captured JSONL when you need repeatable
local scoring without calling a model during the benchmark run:

```bash
forecast backtest path/to/cases.json \
  --probability-source agent-protocol \
  --agent-response-jsonl path/to/agent-responses.jsonl
```

Each JSONL row should be keyed by `case_id`, `id`, or `index` and contain a
`response` object or JSON string:

```jsonl
{"case_id":"macro-001","response":{"probability":0.42,"confidence":0.6,"rationale":"Base rate plus pre-cutoff evidence.","components":{"base_rate":{"probability":0.35,"weight":2}},"agent_model":"claude-sonnet-4.6"}}
```

Without `--agent-response-jsonl`, `agent-protocol` calls the configured agent
for each case. The prompt excludes dataset probability, resolved outcome,
resolution-time fields, notes, and metadata, and it filters evidence and
baselines to the simulated evidence cutoff before the agent sees the case.
Add `--agent-output-jsonl path/to/captured.jsonl` to write the responses used
by a run so the same agent outputs can be replayed later without another model
call.

### Built-In Benchmarks

Packaged benchmark datasets are local and require no live API calls:

| Dataset | Purpose |
| --- | --- |
| `builtin:mini-binary` | Five small smoke-test cases across macro, policy, credit, and biotech. |
| `builtin:synthetic-100-binary` | One hundred synthetic binary cases for replay scale tests. |
| `builtin:heldout-120-binary` | Frozen packaged binary cases for held-out replay checks. |
| `builtin:manifold-public-120-binary` | Frozen public Manifold resolved binary markets with market baselines. |

Use `forecast backtest --benchmarks` to see the current list.

## Backtest Dataset Format

Backtest datasets are JSON or CSV, not JSONL. JSON may be either an array of
cases or an object with a `cases` array.

```json
[
  {
    "id": "macro-001",
    "title": "Will unemployment exceed 5 percent by year end?",
    "resolution_criteria": "Resolved yes if the official unemployment rate is above 5 percent in the final annual release.",
    "domain": "macro",
    "topics": ["labor"],
    "as_of": "2024-09-01T00:00:00Z",
    "close_time": "2024-12-31T00:00:00Z",
    "probability": 0.27,
    "base_rate": 0.22,
    "outcome": "no",
    "evidence": [
      {
        "note": "Payroll growth remained positive.",
        "available_at": "2024-08-30T12:00:00Z",
        "stance": "decreases"
      }
    ],
    "baselines": [
      {
        "source": "crowd",
        "baseline_type": "crowd",
        "probability": 0.31,
        "as_of": "2024-09-01T00:00:00Z"
      }
    ]
  }
]
```

For scoreable binary replays, include:

- `title`
- `resolution_criteria`
- `as_of` or `simulated_forecast_time`
- `outcome`
- `probability`, `forecast_probability`, or `distribution`

Useful optional fields:

- `domain`, `topics`, `tags`
- `close_time`, `resolution_time`, `resolution_source`
- `base_rate` or `base_rate_probability`
- `evidence` with `available_at`, `published_at`, `stance`, `claim_type`, and
  source metadata
- `baselines` with `baseline_type`, `source`, probability or distribution, and
  `as_of`

CSV input supports the same concepts through columns such as `title`,
`resolution_criteria`, `simulated_forecast_time`, `as_of`, `probability`,
`forecast_probability`, `outcome`, `domain`, `topics`, `evidence_json`, and
`baselines_json`.

## Leakage Rules

Backtests must not learn from the future.

- Evidence after the simulated cutoff is excluded from the replay case.
- Agent-protocol prompts also exclude answer-side replay fields before model or
  captured-output evaluation.
- Evidence without an `available_at` or `published_at` timestamp is treated as
  ambiguous and blocks calibration-memory eligibility.
- Backtest snapshots are not calibration memory by default.
- `--allow-calibration-memory` only admits clean cases; if leakage checks fail,
  calibration eligibility is disabled for the run.

Use `--as-of` to supply a default simulated time when cases omit it:

```bash
forecast backtest path/to/cases.json \
  --as-of 2024-01-01T00:00:00Z \
  --probability-source forecast-engine
```

## Importing Benchmarks

When you want a reusable local corpus, import it into the ledger and replay it
by ID:

```bash
forecast import benchmark path/to/cases.json \
  --name "policy-resolution-set"

forecast backtest --benchmarks
forecast backtest imported:<benchmark_id> --probability-source forecast-engine
```

Imported benchmark datasets are ledger objects. That makes later runs easier to
compare and removes ambiguity about which dataset version was used.

## Performance Review

Use these commands after running backtests:

```bash
forecast backtest --list
forecast backtest --show <backtest_run_id>
forecast performance --last 10
forecast performance --json
forecast calibration --by-origin
forecast errors --domain macro
```

The most useful signals are:

- Mean Brier score and log score.
- Paired agent-vs-baseline Brier edge.
- Agent wins, baseline wins, and ties on paired cases.
- Domain and horizon breakdowns.
- Leakage status.
- `evidence_status` in JSON output, which reports live-score counts,
  agent-protocol scored cases, leakage-free runs, positive baseline edges,
  distinct datasets, and the remaining evidence gaps before any live
  superiority claim. Positive-edge runs count generated probability sources
  such as `forecast-engine`, `baseline-ensemble`, or `agent-protocol`, not raw
  dataset replay probabilities. The same object includes `next_actions` with
  concrete commands for collecting missing live-score, agent-protocol, leakage,
  positive-edge, or dataset-coverage evidence.
- Whether misses produce postmortems and calibration lessons.

Performance output marks replay evidence as `benchmark_replay_only`.
Agent-protocol runs are identified separately as agent-protocol replay evidence,
but they still do not prove live superiority over human or market baselines.
That requires repeated held-out or live forecasts, later resolution, scoring,
and postmortem learning over time.

## Raw Trajectory Batches

`batch_runner.py` remains available for inherited runtime evaluation. It runs a
JSONL set of prompts through full agent sessions, samples toolset distributions,
and writes ShareGPT-like trajectories plus tool and reasoning statistics.

Use it for:

- Prompt-protocol regression tests.
- Tool availability and failure-rate checks.
- Provider or model comparisons before using them in live forecasts.
- Generating training trajectories when you need raw conversations.

Do not treat raw batch output as forecast performance. It lacks resolution
records, proper scoring, evidence cutoff checks, and baseline comparisons unless
you convert the prompts into `forecast backtest` cases.

### Trajectory Dataset Format

The raw runner input is JSONL, one object per line, with a `prompt` field:

```jsonl
{"prompt": "As of 2024-09-01, forecast whether unemployment will exceed 5 percent by year end. Use only evidence dated on or before 2024-09-01 and end with a probability and rationale."}
{"prompt": "As of 2024-03-01, forecast whether the regulator will approve the therapy by the PDUFA date. Include base-rate reasoning and uncertainty."}
```

Optional fields:

- `image` or `docker_image`: Per-prompt container image for Docker, Modal,
  Singularity, or Daytona terminal backends.
- `cwd`: Working directory override for that prompt's terminal session.

### Raw Runner Options

| Parameter | Default | Description |
| --- | --- | --- |
| `--dataset_file` | required | JSONL prompt dataset. |
| `--batch_size` | required | Prompts per batch. |
| `--run_name` | required | Output directory name under `data/`. |
| `--distribution` | `default` | Toolset distribution to sample for each prompt. |
| `--model` | `anthropic/claude-sonnet-4.6` | Model for the run. |
| `--base_url` | `https://openrouter.ai/api/v1` | API base URL. |
| `--api_key` | env/config | API key or compatible runtime credential. |
| `--max_turns` | `10` | Maximum tool-calling iterations per prompt. |
| `--num_workers` | `4` | Parallel worker processes. |
| `--resume` | `false` | Resume from existing batch files and checkpoint. |
| `--max_samples` | all | Process only the first N samples. |
| `--max_tokens` | model default | Maximum tokens per model response. |
| `--reasoning_effort` | provider default | `none`, `minimal`, `low`, `medium`, `high`, or `xhigh`. |
| `--reasoning_disabled` | `false` | Disable reasoning or thinking tokens. |
| `--prefill_messages_file` | none | JSON file containing prefill messages for few-shot priming. |
| `--ephemeral_system_prompt` | none | System prompt used during execution but omitted from saved trajectories. |

OpenRouter routing flags are also supported:

| Parameter | Description |
| --- | --- |
| `--providers_allowed` | Comma-separated providers to allow. |
| `--providers_ignored` | Comma-separated providers to ignore. |
| `--providers_order` | Comma-separated preferred provider order. |
| `--provider_sort` | Sort by `price`, `throughput`, or `latency`. |

### Toolset Distributions

Use `python batch_runner.py --list_distributions` to inspect available
distributions. Common choices for forecast-oriented testing:

| Distribution | Use when |
| --- | --- |
| `research` | Web and browser-heavy evidence gathering. |
| `minimal` | Web-only prompt checks. |
| `terminal_web` | Statistical notebooks or data pulls that also need docs. |
| `safe` | Avoid local terminal execution. |
| `balanced` | General protocol smoke tests. |

The sampler flips each toolset independently, then guarantees at least one
toolset is enabled.

## Raw Output Format

Raw batches write to `data/<run_name>/`:

```text
data/forecast_protocol_eval_v1/
├── trajectories.jsonl
├── batch_0.jsonl
├── batch_1.jsonl
├── checkpoint.json
└── statistics.json
```

Each trajectory row includes:

- `prompt_index`
- `conversations`
- `metadata`
- `completed` and `partial`
- `api_calls`
- `toolsets_used`
- `tool_stats`
- `tool_error_counts`

The runner normalizes tool stats across all known tools so downstream dataset
loaders see a stable schema.

## Checkpointing

The raw runner writes checkpoints after each completed batch.

- Resume scans existing `batch_*.jsonl` files by prompt text, not only by index.
- Successfully completed prompts are skipped.
- Failed prompts are retried on resume.
- Final output merges all batch files into `trajectories.jsonl`.

```bash
python batch_runner.py \
  --dataset_file=data/forecast_prompts.jsonl \
  --batch_size=10 \
  --run_name=forecast_protocol_eval_v1 \
  --resume
```

## Quality Filtering

The raw runner filters or records:

- Samples with no assistant reasoning turns.
- Corrupted entries with hallucinated tool names.
- Tool success and failure counts.
- Reasoning coverage across assistant turns.

These are runtime-quality signals. They complement, but do not replace, Brier
score, log score, calibration curves, and postmortems from the ledger.

## Scheduled Evaluation

For recurring forecast hygiene, combine batch runs with the scheduler:

- Run `forecast backtest --all-benchmarks --probability-source forecast-engine`
  weekly to catch regressions.
- Run `forecast performance --json` after the replay and store the report.
- Run `forecast self-check --domain <domain> --auto-score --auto-postmortem`
  for domains with active forecasts.
- Use watched sources and review schedules for live standing beliefs; use
  backtests for resolved historical corpora.

See [Cron Automation](./cron.md) for scheduler setup.
