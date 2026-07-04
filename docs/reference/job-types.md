# Background Job Types

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: forecasting/jobs/types/ (registered_types + resolve) -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `forecasting/jobs/types/ (registered_types + resolve)`

Long-running desk work runs as a **detached job** on one runtime (`forecasting/jobs/runtime.py`) with shared progress coalescing, cancellation, persistence, and desk re-attach. Each capability is a registered `JobType`. There are **5 types**. `spend_class` `agent` means the job spends model budget (it drives the agent); `free` means it does not.


| type | spend class | min interval (s) | legacy alias namespace | what it does |
| --- | --- | --- | --- | --- |
| `quorum` | `agent` | 0.0 | `—` | The QUORUM job type: the multi-model Delphi forecast on the one detached-job |
| `reforecast` | `agent` | 0.0 | `forecast.reforecast` | The REFORECAST job type: the operator's Desk "mass LLM re-run" on the one |
| `refresh` | `free` | 0.0 | `—` | The REFRESH job type: the operator's Desk "Update now" (``U`` / mass-``U``) on |
| `task` | `agent` | 0.0 | `forecast.reforecast` | The TASK job type: the operator's Desk free-text "fix loop" on the one |
| `warnings` | `free` | 0.125 | `forecast.warnings.automode` | The WARNINGS job type: a background sweep of the open ``alert_events`` backlog. |

Jobs are started over the wire via the `jobs.start` RPC and stream `jobs.progress` / `jobs.complete` / `jobs.error` events (see the [protocol reference](protocol.md)). A job also runs standalone as a detached process: `python -m forecasting.jobs run <id>`.
