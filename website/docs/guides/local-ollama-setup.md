---
sidebar_position: 9
title: "Run Superforecasting Agent Locally with Ollama"
description: "Run the forecasting desk on your own hardware with Ollama and open-weight models."
---

# Run Superforecasting Agent Locally with Ollama

## The Problem

Cloud LLM APIs charge per token. A long research session that reviews evidence, calls tools, and revisits forecasts can add up quickly, and every prompt leaves your machine.

## What This Guide Solves

You'll set up Superforecasting Agent running entirely on your own hardware, using [Ollama](https://ollama.com) as the model backend. No API keys, no subscriptions, no cloud model calls. Once configured, the CLI forecast desk can research questions, inspect local files, browse sources, update the forecast ledger, and run scheduled self-checks while the model runs locally.

By the end, you'll have:

- Ollama serving one or more open-weight models
- Superforecasting Agent connected to Ollama as a custom endpoint
- A local forecast desk that can research, update, and review forecasts
- Optional: Telegram/Discord delivery for alerts and scheduled review prompts

## What You Need

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **RAM** | 8 GB (for 3B models) | 32+ GB (for 27B+ models) |
| **Storage** | 5 GB free | 30+ GB (for multiple models) |
| **CPU** | 4 cores | 8+ cores (AMD EPYC, Ryzen, Intel Xeon) |
| **GPU** | Not required | NVIDIA GPU with 8+ GB VRAM speeds things up significantly |

:::tip CPU-only works, but expect slower responses
Ollama runs on CPU-only servers. A 9B model on a modern 8-core CPU gives ~10 tokens/sec. A 31B model on CPU is slower (~2–5 tokens/sec) — each response takes 30–120 seconds, but it works. A GPU dramatically improves this. For CPU-only setups, widen the API timeout via the env var (it's not a `config.yaml` key):

```bash
# ~/.superforecasting-agent/.env
HERMES_API_TIMEOUT=1800   # 30 minutes — generous for slow local models
```

`~/.hermes/.env` is still read as a legacy compatibility path during migration, but new setups should prefer the fork-native home.
:::

## Step 1: Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Verify it's running:

```bash
ollama --version
curl http://localhost:11434/api/tags   # Should return {"models":[]}
```

## Step 2: Pull a Model

Choose based on your hardware:

| Model | Size on Disk | RAM Needed | Tool Calling | Best For |
|-------|-------------|------------|:------------:|----------|
| `gemma4:31b` | ~20 GB | 24+ GB | Yes | Best quality — strong tool use and reasoning |
| `gemma2:27b` | ~16 GB | 20+ GB | No | Conversational tasks, no tool use |
| `gemma2:9b` | ~5 GB | 8+ GB | No | Fast chat, Q&A — cannot call tools |
| `llama3.2:3b` | ~2 GB | 4+ GB | No | Lightweight quick answers only |

:::warning Tool calling matters
Superforecasting Agent uses tool calls to gather evidence, write append-only ledger entries, run backtests, and schedule self-checks. Models without reliable tool-call support can help with short summaries, but they cannot safely drive the full forecasting workflow. For the full local desk experience, use a model that supports tools (like `gemma4:31b`).
:::

Pull your chosen model:

```bash
ollama pull gemma4:31b
```

:::info Multiple models
You can pull several models and switch between them inside Superforecasting Agent with `/model`. Ollama loads the active model into memory on demand and unloads idle ones automatically.
:::

Verify the model works:

```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gemma4:31b",
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 50
  }'
```

You should see a JSON response with the model's reply.

## Step 3: Configure Superforecasting Agent

Run the setup wizard:

```bash
superforecasting-agent setup
```

When prompted for a provider, select **Custom Endpoint** and enter:

- **Base URL:** `http://localhost:11434/v1`
- **API Key:** Leave empty or type `no-key` (Ollama doesn't need one)
- **Model:** `gemma4:31b` (or whichever model you pulled)

Alternatively, edit `~/.superforecasting-agent/config.yaml` directly:

```yaml
model:
  default: "gemma4:31b"
  provider: "custom"
  base_url: "http://localhost:11434/v1"
```

## Step 4: Start Forecasting

```bash
forecast
```

That's it. You're now running the local forecasting desk. Try it out:

```bash
forecast status
forecast new "Will the next CPI print be above consensus?" \
  --resolution-criteria "Resolved by the official BLS CPI release"
superforecasting-agent desk
```

The forecast desk and chat agent will use the terminal, file, browser, and ledger tools through your local model, with no cloud model calls.

## Step 5: Pick the Right Model for Your Task

Not every task needs the biggest model. Here's a practical guide:

| Task | Recommended Model | Why |
|------|-------------------|-----|
| Forecast research, ledger updates, tool use | `gemma4:31b` | Most reliable local tool-calling option |
| Source summaries and low-risk drafting | `gemma2:9b` | Fast responses when no tool writes are needed |
| Lightweight notes | `llama3.2:3b` | Fastest, but very limited capabilities |

:::note
For full forecast-desk work (evidence gathering, command execution, source inspection, and ledger writes), `gemma4:31b` is currently the best local option with tool-call support. Check [Ollama's model library](https://ollama.com/library) for newer models — tool-calling support is expanding rapidly.
:::

Switch models on the fly inside a session:

```
/model gemma2:9b
```

## Step 6: Optimize for Speed

### Increase Ollama's Context Window

By default, Ollama uses a 2048-token context. For long research sessions with tool calls and forecast updates, you need more:

```bash
# Create a Modelfile that extends context
cat > /tmp/Modelfile << 'EOF'
FROM gemma4:31b
PARAMETER num_ctx 16384
EOF

ollama create gemma4-16k -f /tmp/Modelfile
```

Then update your Superforecasting Agent config to use `gemma4-16k` as the model name.

### Keep the Model Loaded

By default, Ollama unloads models after 5 minutes of inactivity. For a persistent gateway bot, keep it loaded:

```bash
# Set keep-alive to 24 hours
curl http://localhost:11434/api/generate \
  -d '{"model": "gemma4:31b", "keep_alive": "24h"}'
```

Or set it globally in Ollama's environment:

```bash
# /etc/systemd/system/ollama.service.d/override.conf
[Service]
Environment="OLLAMA_KEEP_ALIVE=24h"
```

### Use GPU Offloading (If Available)

If you have an NVIDIA GPU, Ollama automatically offloads layers to it. Check with:

```bash
ollama ps   # Shows which model is loaded and how many GPU layers
```

For a 31B model on a 12 GB GPU, you'll get partial offload (~40 layers on GPU, rest on CPU), which still gives a significant speedup.

## Step 7: Deliver Alerts Through a Gateway (Optional)

Once the local CLI forecast desk works, you can expose review prompts, watched-source alerts, and scheduled self-check summaries through Telegram or Discord while still running the model on your hardware.

### Telegram

1. Create a bot via [@BotFather](https://t.me/BotFather) and get the token
2. Add to your `~/.superforecasting-agent/config.yaml`:

```yaml
model:
  default: "gemma4:31b"
  provider: "custom"
  base_url: "http://localhost:11434/v1"

platforms:
  telegram:
    enabled: true
    token: "YOUR_TELEGRAM_BOT_TOKEN"
```

3. Start the gateway:

```bash
superforecasting-agent gateway
```

Now message your bot on Telegram. Forecast alerts and review prompts use your local model configuration.

### Discord

1. Create a Discord application at [discord.com/developers](https://discord.com/developers/applications)
2. Add to config:

```yaml
platforms:
  discord:
    enabled: true
    token: "YOUR_DISCORD_BOT_TOKEN"
```

3. Start: `superforecasting-agent gateway`

## Step 8: Set Up Fallbacks (Optional)

Local models can struggle with complex tasks. Set up a cloud fallback that only activates when the local model fails:

```yaml
model:
  default: "gemma4:31b"
  provider: "custom"
  base_url: "http://localhost:11434/v1"

fallback_providers:
  - provider: openrouter
    model: anthropic/claude-sonnet-4
```

This way, 90% of your usage is free (local), and only the hard tasks hit the paid API.

## Troubleshooting

### "Connection refused" on startup

Ollama isn't running. Start it:

```bash
sudo systemctl start ollama
# or
ollama serve
```

### Slow responses

- **Check model size vs RAM:** If your model needs more RAM than available, it swaps to disk. Use a smaller model or add RAM.
- **Check `ollama ps`:** If no GPU layers are offloaded, responses are CPU-bound. This is normal for CPU-only servers.
- **Reduce context:** Large conversations slow down inference. Use `/compress` regularly, or set a lower compression threshold in config.

### Model doesn't follow tool calls

Smaller models (3B, 7B) sometimes ignore tool-call instructions and produce plain text instead of structured function calls. Solutions:

- **Use a bigger model** — `gemma4:31b` or `gemma2:27b` handle tool calls much better than 3B/7B models.
- **The inherited runtime has auto-repair** — it detects malformed tool calls and attempts to fix them automatically.
- **Set up a fallback** — if the local model fails 3 times, Superforecasting Agent falls back to a cloud provider.

### Context window errors

The default Ollama context (2048 tokens) is too small for long forecast research sessions. See [Step 6](#step-6-optimize-for-speed) to increase it.

## Cost Comparison

Here's what running locally saves compared to cloud APIs, based on a typical research/update session (~100K tokens input, ~20K tokens output):

| Provider | Cost per Session | Monthly (daily use) |
|----------|-----------------|---------------------|
| Anthropic Claude Sonnet | ~$0.80 | ~$24 |
| OpenRouter (GPT-4o) | ~$0.60 | ~$18 |
| **Ollama (local)** | **$0.00** | **$0.00** |

Your only cost is electricity — roughly $0.01–0.05 per session depending on hardware.

## What Works Well Locally

- **Forecast ledger updates** — local models can draft probability updates and rationales when tool calls are reliable
- **Source and data review** — the tools fetch files, URLs, RSS feeds, or public data; the model interprets the results
- **Terminal commands** — the runtime wraps the command, runs it, and reads output regardless of model
- **Scheduled self-checks** — cron jobs and watched-source alerts work identically to cloud setups
- **Multi-platform gateway delivery** — Telegram, Discord, and Slack can deliver alerts with local models

## What's Better with Cloud Models

- **Very complex multi-step reasoning** — 70B+ or cloud models like Claude Opus are noticeably better
- **Long context windows** — cloud models offer 100K–1M tokens; local models are typically 8K–32K
- **Speed on large responses** — cloud inference is faster than CPU-only local for long generations

The sweet spot: use local for everyday tasks, set up a cloud fallback for the hard stuff.
