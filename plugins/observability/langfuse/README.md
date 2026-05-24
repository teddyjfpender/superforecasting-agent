# Langfuse Observability Plugin

This plugin ships bundled with Superforecasting Agent but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

```bash
pip install langfuse
superforecasting-agent plugins enable observability/langfuse
```

Or check the box in the interactive `superforecasting-agent plugins` UI.

## Required credentials

Set these in `~/.superforecasting-agent/.env`:

```bash
SUPERFORECASTING_AGENT_LANGFUSE_PUBLIC_KEY=pk-lf-...
SUPERFORECASTING_AGENT_LANGFUSE_SECRET_KEY=sk-lf-...
SUPERFORECASTING_AGENT_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

`FORECAST_LANGFUSE_*`, inherited `HERMES_LANGFUSE_*`, and standard Langfuse SDK
credential names remain accepted as compatibility aliases.

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
superforecasting-agent plugins list      # observability/langfuse should show "enabled"
superforecasting-agent chat -q "hello"   # then check Langfuse for a forecast desk trace
```

## Optional tuning

```bash
SUPERFORECASTING_AGENT_LANGFUSE_ENV=production       # environment tag
SUPERFORECASTING_AGENT_LANGFUSE_RELEASE=v1.0.0       # release tag
SUPERFORECASTING_AGENT_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
SUPERFORECASTING_AGENT_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
SUPERFORECASTING_AGENT_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
superforecasting-agent plugins disable observability/langfuse
```
