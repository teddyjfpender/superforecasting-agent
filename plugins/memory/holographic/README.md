# Holographic Memory Provider

Local SQLite fact store with FTS5 search, trust scoring, entity resolution, and HRR-based compositional retrieval.

Forecast ledger note: this provider is auxiliary recall. Scoreable questions, probabilities, evidence, resolutions, postmortems, calibration lessons, and domain error profiles belong in the forecast ledger.

## Requirements

None — uses SQLite (always available). NumPy optional for HRR algebra.

## Setup

```bash
superforecasting-agent memory setup    # select "holographic"
```

Or manually:
```bash
superforecasting-agent config set memory.provider holographic
```

## Config

Config in `config.yaml` under the inherited `plugins.hermes-memory-store` namespace:

| Key | Default | Description |
|-----|---------|-------------|
| `db_path` | active agent-home `memory_store.db` | SQLite database path. `$SUPERFORECASTING_AGENT_HOME` and `$FORECAST_HOME` are preferred; legacy `$HERMES_HOME` remains readable during migration. |
| `auto_extract` | `false` | Auto-extract facts at session end |
| `default_trust` | `0.5` | Default trust score for new facts |
| `hrr_dim` | `1024` | HRR vector dimensions |

## Tools

| Tool | Description |
|------|-------------|
| `fact_store` | 9 actions: add, search, probe, related, reason, contradict, update, remove, list |
| `fact_feedback` | Rate facts as helpful/unhelpful (trains trust scores) |
