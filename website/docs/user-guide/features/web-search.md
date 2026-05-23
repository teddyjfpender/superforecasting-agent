---
title: Web Search & Extract
description: Search, extract, and crawl web sources for forecast evidence.
sidebar_label: Web Search
sidebar_position: 6
---

# Web Search & Extract

Superforecasting Agent includes two model-callable web tools for forecast research:

- **`web_search`** searches the web and returns ranked candidate sources.
- **`web_extract`** fetches readable page content and can use provider-backed crawl modes when available.

These tools support evidence discovery and source inspection. They do not update probability, resolve questions, score forecasts, or write calibration lessons by themselves. Add forecast-relevant material to the ledger with timestamps, source metadata, reliability, relevance, stance, and as-of context before using it in an update.

Provider selection is configured through `superforecasting-agent tools` or `config.yaml`. Recursive crawling capabilities from providers such as Firecrawl or Tavily are exposed through `web_extract` rather than as a separate first-class product workflow.

## Backends

| Provider | Secret or setting | Search | Extract | Crawl |
|----------|-------------------|:------:|:-------:|:-----:|
| Firecrawl | `FIRECRAWL_API_KEY` or `FIRECRAWL_API_URL` | yes | yes | yes |
| SearXNG | `SEARXNG_URL` | yes | no | no |
| Brave Search | `BRAVE_SEARCH_API_KEY` | yes | no | no |
| DDGS | no key | yes | no | no |
| Tavily | `TAVILY_API_KEY` | yes | yes | yes |
| Exa | `EXA_API_KEY` | yes | yes | no |
| Parallel | `PARALLEL_API_KEY` | yes | yes | no |
| xAI (Grok) | `XAI_API_KEY` or `superforecasting-agent auth add xai-oauth` | yes | no | no |

Search-only providers should be paired with an extract provider when the workflow needs full page content, archived source snapshots, or crawl output. For example, use SearXNG for private search and Firecrawl for extraction.

DDGS uses the [`ddgs` Python package](https://pypi.org/project/ddgs/). If it is not installed, install it with `pip install ddgs` or let the runtime lazy-install it on first use.

xAI runs Grok's server-side `web_search` tool on the Responses API. Results are model-generated rather than index-backed, so titles, descriptions, and URL choices are model output. See the [trust-model caveat](#xai-grok).

**Per-capability split:** use different providers for search and extract independently. See [Per-capability configuration](#per-capability-configuration).

:::tip Nous Subscribers
Paid [Nous Portal](https://portal.nousresearch.com) subscriptions can route web search and extract through the [Tool Gateway](./tool-gateway) via managed Firecrawl, without a separate Firecrawl key. Enable it with `superforecasting-agent tools`.
:::

## Forecasting Use

Use web tools to build the evidence side of a forecast:

1. Search for candidate sources.
2. Extract the original page or a stable source page.
3. Record source metadata, publication time, availability time, and access time.
4. Classify the claim as fact, estimate, rumor, opinion, model assumption, or market-implied signal.
5. Add the material to the ledger before using it in `forecast update`.

Example:

```bash
forecast evidence add <id> \
  --source-url "https://example.com/source" \
  --source-type article \
  --published-at "2026-05-22T09:00:00Z" \
  --available-at "2026-05-22T10:15:00Z" \
  --reliability medium \
  --relevance high \
  --stance supports \
  --summary "Source claim and why it matters."

forecast update <id> --require-citations
```

For backtests, use only sources that would have been available before the forecast's evidence cutoff. Do not let future-dated extracts leak into historical replay.

---

## How `web_extract` Handles Long Pages

Backends can return very large markdown payloads, especially for forum threads, docs sites, long reports, or news pages with embedded comments. To keep the context window usable, `web_extract` runs large returned content through the **`web_extract` auxiliary model** before handing it to the agent.

| Page size in characters | What happens |
|-------------------------|--------------|
| Under 5,000 | Returned as-is, with no auxiliary model call |
| 5,000 to 500,000 | Single-pass summary capped around 5,000 characters |
| 500,000 to 2,000,000 | Chunked summarization, then synthesized into a final summary |
| Over 2,000,000 | Refused with a hint to narrow the source or use a more focused extraction path |

The summary keeps quoted claims, code blocks, links, and key facts where possible. It is a content compressor, not source truth. If summarization fails or times out, the runtime falls back to the first part of the raw content rather than hiding the failure.

### Which Model Does The Summarizing?

The `web_extract` auxiliary task controls long-page summarization. By default (`auxiliary.web_extract.provider: "auto"`), it uses your main configured model and provider.

To route extraction summaries to a cheaper or faster model:

```yaml
# ~/.superforecasting-agent/config.yaml
auxiliary:
  web_extract:
    provider: openrouter
    model: google/gemini-3-flash-preview
    timeout: 360
```

Or pick interactively:

```bash
superforecasting-agent model
```

Then open **Configure auxiliary models** and set `web_extract`.

See [Auxiliary Models](../configuration#auxiliary-models) for per-task override patterns.

### When Summarization Gets In The Way

If you need raw page structure, exact table rows, form state, or a live accessibility tree, use `browser_navigate` and `browser_snapshot` instead. The browser tools avoid auxiliary-model rewriting, though they have their own snapshot-size limits.

---

## Setup

### Quick Setup Via `superforecasting-agent tools`

Run:

```bash
superforecasting-agent tools
```

Choose **Web Search & Extract**, then select a provider. The wizard prompts for the required URL or API key and writes it to the active config.

### Firecrawl

Firecrawl supports search, extract, and crawl.

```bash
# ~/.superforecasting-agent/.env
FIRECRAWL_API_KEY=fc-your-key-here
```

Get a key at [firecrawl.dev](https://firecrawl.dev), or point the runtime at a self-hosted instance:

```bash
# ~/.superforecasting-agent/.env
FIRECRAWL_API_URL=http://localhost:3002
```

When `FIRECRAWL_API_URL` is set, the API key is optional if your self-hosted server disables API-key authentication.

### SearXNG

SearXNG is a privacy-respecting, open-source metasearch engine. It is search-only, so `web_extract` still needs a separate extract provider.

#### Option A - Self-Host With Docker

Create a working directory:

```bash
mkdir -p ~/searxng/searxng
cd ~/searxng
```

Write `docker-compose.yml`:

```yaml
# ~/searxng/docker-compose.yml
services:
  searxng:
    image: searxng/searxng:latest
    container_name: searxng
    ports:
      - "8888:8080"
    volumes:
      - ./searxng:/etc/searxng:rw
    environment:
      - SEARXNG_BASE_URL=http://localhost:8888/
    restart: unless-stopped
```

Start the container:

```bash
docker compose up -d
```

SearXNG ships with JSON output disabled by default. Copy the generated config and enable it:

```bash
docker cp searxng:/etc/searxng/settings.yml ~/searxng/searxng/settings.yml
```

In `~/searxng/searxng/settings.yml`, enable JSON:

```yaml
formats:
  - html
  - json
```

Apply the config:

```bash
docker cp ~/searxng/searxng/settings.yml searxng:/etc/searxng/settings.yml
docker restart searxng
```

Verify:

```bash
curl -s "http://localhost:8888/search?q=test&format=json" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(f'{len(d[\"results\"])} results')"
```

If you get `403 Forbidden`, JSON format is still disabled.

Configure Superforecasting Agent:

```bash
# ~/.superforecasting-agent/.env
SEARXNG_URL=http://localhost:8888
```

```yaml
# ~/.superforecasting-agent/config.yaml
web:
  search_backend: "searxng"
```

Or set it with:

```bash
superforecasting-agent tools
```

#### Option B - Use A Public Instance

Public SearXNG instances are listed at [searx.space](https://searx.space/). Use only instances with JSON format enabled.

```bash
# ~/.superforecasting-agent/.env
SEARXNG_URL=https://searx.example.com
```

:::caution Public instances
Public instances can have rate limits, variable uptime, logging policies, and configuration changes. For repeatable forecast workflows, self-hosting is preferable.
:::

#### Pair SearXNG With An Extract Provider

Use per-capability keys:

```yaml
# ~/.superforecasting-agent/config.yaml
web:
  search_backend: "searxng"
  extract_backend: "firecrawl"
```

This uses SearXNG for `web_search` and Firecrawl for `web_extract`.

### Brave Search

Brave Search is search-only.

```bash
# ~/.superforecasting-agent/.env
BRAVE_SEARCH_API_KEY=your-brave-key-here
```

Use an extract backend separately when you need page content.

### DDGS

DDGS is a no-key DuckDuckGo-backed search option through the `ddgs` Python package.

```bash
pip install ddgs
```

Configure:

```yaml
web:
  search_backend: "ddgs"
```

### Tavily

Tavily supports search, extract, and crawl.

```bash
# ~/.superforecasting-agent/.env
TAVILY_API_KEY=tvly-your-key-here
```

Get a key at [app.tavily.com](https://app.tavily.com/home).

### Exa

Exa supports semantic search and extraction.

```bash
# ~/.superforecasting-agent/.env
EXA_API_KEY=your-exa-key-here
```

Get a key at [exa.ai](https://exa.ai).

### Parallel

Parallel supports search and extraction.

```bash
# ~/.superforecasting-agent/.env
PARALLEL_API_KEY=your-parallel-key-here
```

Get access at [parallel.ai](https://parallel.ai).

### xAI (Grok) {#xai-grok}

xAI routes `web_search` through Grok's server-side [web_search tool](https://docs.x.ai/developers/tools/web-search) on the Responses API.

Use either credential path:

```bash
# ~/.superforecasting-agent/.env
XAI_API_KEY=sk-xai-your-key-here
```

Or for OAuth-backed xAI access:

```bash
superforecasting-agent auth add xai-oauth
```

Then select xAI as the search backend:

```yaml
# ~/.superforecasting-agent/config.yaml
web:
  backend: "xai"
```

Optional knobs:

```yaml
web:
  backend: "xai"
  xai:
    model: grok-4.3
    allowed_domains:
      - arxiv.org
    excluded_domains:
      - example-spam.com
    timeout: 90
```

`allowed_domains` and `excluded_domains` are mutually exclusive. xAI is search-only, so pair it with Firecrawl, Tavily, Exa, or Parallel when you also need `web_extract`.

On OAuth 401, the provider performs a single forced token refresh and retries. Env-var credentials skip that retry.

:::caution Trust model
Unlike index-backed providers, xAI is an LLM choosing which URLs to surface and writing the titles and descriptions itself. The query content can influence output, so validate returned URLs before fetching, especially if the query came from untrusted upstream input.
:::

---

## Configuration

### Single Backend

Set one provider for all web capabilities:

```yaml
# ~/.superforecasting-agent/config.yaml
web:
  backend: "searxng"
```

Supported backend names:

```text
firecrawl, searxng, brave-free, ddgs, tavily, exa, parallel, xai
```

### Per-capability Configuration

Use different providers for search and extract:

```yaml
# ~/.superforecasting-agent/config.yaml
web:
  search_backend: "searxng"
  extract_backend: "firecrawl"
```

When per-capability keys are empty, both fall through to `web.backend`. When `web.backend` is also empty, the runtime auto-detects from configured credentials.

Priority order:

1. `web.search_backend` or `web.extract_backend`
2. `web.backend`
3. auto-detection from environment variables

### Auto-detection

If no backend is explicitly configured, the runtime picks the first available backend based on configured credentials:

| Credential present | Auto-selected backend |
|--------------------|-----------------------|
| `FIRECRAWL_API_KEY` or `FIRECRAWL_API_URL` | firecrawl |
| `PARALLEL_API_KEY` | parallel |
| `TAVILY_API_KEY` | tavily |
| `EXA_API_KEY` | exa |
| `SEARXNG_URL` | searxng |

xAI Web Search is not in the auto-detection chain. `XAI_API_KEY` and xAI OAuth can also be used for inference, TTS, and image generation, so search traffic only routes through xAI when `web.backend: "xai"` or `web.search_backend: "xai"` is set.

Legacy `~/.hermes/config.yaml`, `~/.hermes/.env`, and `HERMES_*` runtime variables remain readable during migration, but new forecast profiles should use `~/.superforecasting-agent/`.

---

## Verify Your Setup

Run setup to see detected tool configuration:

```bash
superforecasting-agent setup
```

Or run the web tools module from the repository after activating the local virtual environment:

```bash
source .venv/bin/activate
python -m tools.web_tools
```

Expected output includes the active backend and status:

```text
Web backend: searxng
Using SearXNG (search only): http://localhost:8888
```

For forecast-specific verification, create or use a test question, add one manually reviewed extracted source as evidence, and confirm the ledger records source metadata:

```bash
forecast evidence list <id>
```

---

## Troubleshooting

### `web_search` Returns `{"success": false}`

- Check that the provider URL or key is present in the active profile.
- For SearXNG, check reachability: `curl -s "http://localhost:8888/search?q=test&format=json"`.
- If SearXNG returns HTTP 403, add `json` to the `formats` list in `settings.yml` and restart.
- If the container may not be running, inspect it with `docker ps`.

### `web_extract` Says "search-only backend"

SearXNG, Brave, DDGS, and xAI cannot extract URL content. Set `web.extract_backend` to a provider that supports extraction:

```yaml
web:
  search_backend: "searxng"
  extract_backend: "firecrawl"
```

### SearXNG Returns 0 Results

Try:

- a different query
- a different public instance from [searx.space](https://searx.space/)
- self-hosting for repeatable forecast workflows

### Rate Limited On A Public Instance

Switch to a self-hosted instance. Public instances are not reliable enough for scheduled self-checks, watched-source monitoring, or backtests.

### `web_extract` Returns Truncated Content With A Timeout Note

The auxiliary model did not finish summarizing within the configured timeout. Either:

- raise `auxiliary.web_extract.timeout`
- switch the `web_extract` auxiliary task to a faster model
- use `browser_navigate` for pages where summarization is the wrong tool
- use a domain-specific adapter when available, such as RSS/Atom, SEC EDGAR, FRED, BLS, World Bank, arXiv, OpenAlex, Wikipedia, Wikimedia pageviews, GitHub releases, Federal Register, NVD, Open-Meteo, USGS, NASA EONET, NWS alerts, OWID, GDELT, or a forecasting-platform importer

---

## Optional Skill: `searxng-search`

If a forecast workflow needs to call SearXNG directly as a fallback when the web toolset is unavailable, install the optional skill:

```bash
superforecasting-agent skills install official/research/searxng-search
```

This adds procedural guidance for:

- calling the SearXNG JSON API directly
- filtering by category such as `general`, `news`, or `science`
- handling pagination and error cases
- falling back gracefully when SearXNG is unreachable

Use direct calls as a fallback path. Ledger evidence rules still apply.
