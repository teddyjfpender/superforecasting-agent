# RetainDB Memory Provider

Cloud memory API with hybrid search (Vector + BM25 + Reranking) and 7 memory types.

Forecast ledger note: this provider is auxiliary recall. Scoreable questions, probabilities, evidence, resolutions, postmortems, calibration lessons, and domain error profiles belong in the forecast ledger.

## Requirements

- RetainDB account ($20/month) from [retaindb.com](https://www.retaindb.com)
- `pip install requests`

## Setup

```bash
superforecasting-agent memory setup    # select "retaindb"
```

Or manually:
```bash
superforecasting-agent config set memory.provider retaindb
echo "RETAINDB_API_KEY=your-key" >> ~/.superforecasting-agent/.env
```

## Config

All config via environment variables in `.env`:

| Env Var | Default | Description |
|---------|---------|-------------|
| `RETAINDB_API_KEY` | (required) | API key |
| `RETAINDB_BASE_URL` | `https://api.retaindb.com` | API endpoint |
| `RETAINDB_PROJECT` | auto (profile-scoped) | Project identifier |

## Tools

| Tool | Description |
|------|-------------|
| `retaindb_profile` | User's stable profile |
| `retaindb_search` | Semantic search |
| `retaindb_context` | Task-relevant context |
| `retaindb_remember` | Store a fact with type + importance |
| `retaindb_forget` | Delete a memory by ID |
