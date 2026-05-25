# OpenViking Memory Provider

Context database by Volcengine (ByteDance) with filesystem-style knowledge hierarchy, tiered retrieval, and automatic memory extraction.

Forecast ledger note: this provider is auxiliary recall. Scoreable questions, probabilities, evidence, resolutions, postmortems, calibration lessons, and domain error profiles belong in the forecast ledger.

## Requirements

- `pip install openviking`
- OpenViking server running (`openviking-server`)
- Embedding + VLM model configured in `~/.openviking/ov.conf`

## Setup

```bash
superforecasting-agent memory setup    # select "openviking"
```

Or manually:
```bash
superforecasting-agent config set memory.provider openviking
echo "OPENVIKING_ENDPOINT=http://localhost:1933" >> ~/.superforecasting-agent/.env
```

## Config

All config via environment variables in `.env`:

| Env Var | Default | Description |
|---------|---------|-------------|
| `OPENVIKING_ENDPOINT` | `http://127.0.0.1:1933` | Server URL |
| `OPENVIKING_API_KEY` | (none) | API key (optional) |

## Tools

| Tool | Description |
|------|-------------|
| `viking_search` | Semantic search with fast/deep/auto modes |
| `viking_read` | Read content at a viking:// URI (abstract/overview/full) |
| `viking_browse` | Filesystem-style navigation (list/tree/stat) |
| `viking_remember` | Store a fact for extraction on session commit |
| `viking_add_resource` | Ingest URLs/docs into the knowledge base |
