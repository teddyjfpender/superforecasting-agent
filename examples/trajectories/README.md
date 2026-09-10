# Trajectory examples

These checkout examples support development and evaluation. Use the forecast
ledger for durable questions, evidence, probability updates, and scores.
Run the commands from the repository root with the development environment active.

## Browser tasks

`example_browser_tasks.jsonl` contains example prompts. The shell runner uses
that dataset and writes trajectories to `data/browser_tasks_example/` and logs
to `logs/`. It calls the configured model and browser tools:

```bash
bash examples/trajectories/run_browser_tasks.sh
```

## Research batches

Prepare a JSONL dataset with one `{"prompt": "..."}` object per line, then use
the batch command's supported arguments:

```bash
python -m superforecasting_agent.trajectories.batch \
  --dataset_file=research-prompts.jsonl \
  --batch_size=20 \
  --run_name=web_research_v1 \
  --distribution=research \
  --num_workers=4 \
  --max_samples=500
```

The former `web_research.yaml` example was removed because the batch command
has no `--config` option or `WebResearchEnv` integration. Use
`--list_distributions` to inspect the available tool distributions.

## Compression

Pass the sample configuration explicitly when compressing existing trajectories:

```bash
python -m superforecasting_agent.trajectories.compression \
  --input=data/browser_tasks_example \
  --config=examples/trajectories/trajectory_compression.yaml
```

Review the tokenizer and summarization model settings before running compression.
The configuration uses a remote tokenizer and model calls for summaries.
