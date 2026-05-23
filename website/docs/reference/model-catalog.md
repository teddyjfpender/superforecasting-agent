---
sidebar_position: 11
title: Model Catalog
description: Remotely-hosted manifest driving curated model picker lists for OpenRouter and Nous Portal.
---

# Model Catalog

Superforecasting Agent fetches curated model lists for **OpenRouter** and **Nous Portal** from a JSON manifest hosted alongside the docs site. This lets maintainers update picker lists without shipping a new `superforecasting-agent` release.

When the manifest is unreachable (offline, network blocked, hosting failure), the CLI silently falls back to the in-repo snapshot that ships with the fork. The manifest never breaks the picker; worst case you see whatever list was bundled with your installed version.

## Live manifest URL

```
https://superforecasting-agent.nousresearch.com/docs/api/model-catalog.json
```

Published on every merge to `main` via the existing `deploy-site.yml` GitHub Pages pipeline. The source of truth lives in the repo at `website/static/api/model-catalog.json`. During the fork transition, the hosted URL may keep the inherited Hermes domain; override `model_catalog.url` if your fork publishes the manifest elsewhere.

## Schema

```json
{
  "version": 1,
  "updated_at": "2026-04-25T22:00:00Z",
  "metadata": {},
  "providers": {
    "openrouter": {
      "metadata": {},
      "models": [
        {"id": "moonshotai/kimi-k2.6", "description": "recommended", "metadata": {}},
        {"id": "openai/gpt-5.4",       "description": ""}
      ]
    },
    "nous": {
      "metadata": {},
      "models": [
        {"id": "anthropic/claude-opus-4.7"},
        {"id": "moonshotai/kimi-k2.6"}
      ]
    }
  }
}
```

Field notes:

- **`version`** — integer schema version. Future schemas bump this; Superforecasting Agent refuses manifests with versions it doesn't understand and falls back to the hardcoded snapshot.
- **`metadata`** — free-form dict at the manifest, provider, and model level. Any keys. The CLI ignores unknown fields, so you can annotate entries (`"tier": "paid"`, `"tags": [...]`, etc.) without coordinating a schema change.
- **`description`** — OpenRouter-only. Drives picker badge text (`"recommended"`, `"free"`, or empty). Nous Portal doesn't use this — free-tier gating is determined live from the Portal's pricing endpoint.
- **Pricing and context length** are NOT in the manifest. Those come from live provider APIs (`/v1/models` endpoints, models.dev) at fetch time.

## Fetch behavior

| When | What happens |
|---|---|
| `/model` or `superforecasting-agent model` | Fetches if disk cache is stale, else uses cache |
| `hermes model` | Legacy compatibility alias for the same picker |
| Disk cache fresh (< TTL) | No network hit |
| Network failure with cache | Silent fallback to cache, one log line |
| Network failure, no cache | Silent fallback to in-repo snapshot |
| Manifest fails schema validation | Treated as unreachable |

Cache location: `~/.superforecasting-agent/cache/model_catalog.json`. Existing legacy homes may still read and write `~/.hermes/cache/model_catalog.json` during migration.

## Config

```yaml
model_catalog:
  enabled: true
  url: https://superforecasting-agent.nousresearch.com/docs/api/model-catalog.json
  ttl_hours: 24
  providers: {}
```

Set `enabled: false` to disable remote fetch entirely and always use the in-repo snapshot.

### Per-provider override URLs

Third parties can self-host their own curation list using the same schema. Point a provider at a custom URL:

```yaml
model_catalog:
  providers:
    openrouter:
      url: https://example.com/my-openrouter-curation.json
```

The overriding manifest only needs to populate the provider block(s) it cares about. Other providers continue to resolve against the master URL.

## Updating the manifest

Maintainers:

```bash
# Re-generate from the in-repo hardcoded lists (keeps manifest in sync after
# editing OPENROUTER_MODELS or _PROVIDER_MODELS["nous"] in hermes_cli/models.py).
python scripts/build_model_catalog.py
```

Then PR the resulting change to `website/static/api/model-catalog.json` to `main`. The docs site auto-deploys on merge and the new manifest is live within a few minutes.

You can also hand-edit the JSON directly for fine-grained metadata changes that don't belong in the in-repo snapshot — the generator script is a convenience, not the single source of truth.
