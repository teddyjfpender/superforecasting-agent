# Reference (generated)

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

These pages are generated from the code — the protocol registry, the tool schema, the jobs registry, the provider registries, the CLI argparse tree, and the built-in hooks. They regenerate deterministically and a CI staleness gate fails if any is out of date, so the reference cannot drift from the system it documents. Do not edit them by hand.

Regenerate after changing any of those sources:

```bash
python -m scripts.docgen            # rewrite docs/reference/*.md
python -m scripts.docgen --check    # CI gate: fail if stale
```

| page | contents |
| --- | --- |
| [Gateway wire protocol](protocol.md) | Every RPC method and event crossing the gateway, with request/response/payload schemas. |
| [Forecast tool actions](tool-actions.md) | The `forecast_ledger` tool's actions and parameter bag — how the agent drives the desk. |
| [Background job types](job-types.md) | The detached-job runtime's registered job types (quorum, reforecast, refresh, task, warnings). |
| [Data-plane providers](providers.md) | Market-data quote providers and prediction-market venues. |
| [CLI reference](cli-reference.md) | The exhaustive `forecast` command tree, introspected from argparse. |
| [Forecast hooks (built-in rules)](hooks-rules.md) | The commit-gate rules that warn on or block an under-saturated forecast. |
| [Skills catalogue](skills.md) | Every bundled `SKILL.md`, grouped by category, with its when-to-use triggers. |
| [Configuration & environment variables](config-and-env.md) | Every environment variable the server, tools, and CLI read — defaults and secrets. |
