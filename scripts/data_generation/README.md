# Trajectory development utilities

These source-checkout tools support data generation and experiments. Forecast
questions, evidence, updates, and scoring belong to the `forecast` CLI and ledger.

Run the task runner from the repository root with the development environment
activated:

```bash
python -m scripts.data_generation.swe_runner --help
```

`--task` runs one development task; `--prompts_file` accepts JSONL prompts.
The runner can execute tools and call the configured model. Its conversation
output preserves the inherited Hermes trajectory format for existing consumers.

The runner moved from `mini_swe_runner.py`; use the module command above in local
scripts. It is a checkout utility, not an installed product entry point.

Batch-run datasets, a browser example, and compression settings are collected in
[examples/trajectories/](../../examples/trajectories/README.md).
