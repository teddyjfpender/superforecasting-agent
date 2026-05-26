# Mem0 Memory Provider

Server-side LLM fact extraction with semantic search, reranking, and automatic deduplication.

Forecast ledger note: this provider is auxiliary recall. Scoreable questions, probabilities, evidence, resolutions, postmortems, calibration lessons, and domain error profiles belong in the forecast ledger.

## Requirements

- `pip install mem0ai`
- Mem0 API key from [app.mem0.ai](https://app.mem0.ai)

## Setup

```bash
superforecasting-agent memory setup    # select "mem0"
```

Or manually:
```bash
superforecasting-agent config set memory.provider mem0
echo "MEM0_API_KEY=your-key" >> ~/.superforecasting-agent/.env
```

## Config

Config file: `mem0.json` under the active Superforecasting Agent home
(`$SUPERFORECASTING_AGENT_HOME` or `$FORECAST_HOME`; legacy `$HERMES_HOME`
remains readable during migration).

| Key | Default | Description |
|-----|---------|-------------|
| `user_id` | `hermes-user` | Inherited compatibility default user identifier on Mem0 |
| `agent_id` | `hermes` | Inherited compatibility default agent identifier |
| `rerank` | `true` | Enable reranking for recall |

## Tools

| Tool | Description |
|------|-------------|
| `mem0_profile` | All stored memories about the user |
| `mem0_search` | Semantic search with optional reranking |
| `mem0_conclude` | Store a fact verbatim (no LLM extraction) |
