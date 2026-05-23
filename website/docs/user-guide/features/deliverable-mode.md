---
title: Deliverable Mode
sidebar_label: Deliverable Mode
description: Send forecast packets, charts, reports, and data files as native messaging attachments.
---

# Deliverable Mode

When Superforecasting Agent runs through a messaging gateway such as Slack, Discord, Telegram, WhatsApp, or Signal, it can send generated files back into the thread as native attachments.

For a forecast desk, deliverables are the outward-facing artifacts around the ledger: calibration plots, forecast review packets, evidence tables, resolver notes, benchmark reports, spreadsheets, slide decks, PDFs, audio briefs, and generated images. Uploading a file does not change the scoreable forecast state. Forecast updates, evidence imports, resolutions, scores, postmortems, and calibration lessons still need explicit ledger actions.

## How It Works

Three pieces fit together:

1. Forecast workflows or tools produce files. Examples include code-generated charts, backtest reports, exported evidence tables, PDF packets, spreadsheets, slide decks, generated images, and text-to-speech audio.
2. The gateway scans the final response for file paths. Absolute paths and home-relative paths with supported extensions are extracted. Paths inside code blocks and inline code are ignored.
3. The gateway uploads by file type. Images embed inline where supported, audio routes to voice or audio attachments, and documents or data files upload as files.

The agent only needs to mention the generated file path as plain text in the response. The gateway removes that path from the visible message and uploads the file.

## Supported File Extensions

| Category | Extensions | Delivery |
|---|---|---|
| Images | `.png .jpg .jpeg .gif .webp .bmp .tiff .svg` | Inline embed |
| Video | `.mp4 .mov .avi .mkv .webm` | Inline embed where supported |
| Audio | `.mp3 .wav .ogg .m4a .flac` | Voice or audio attachment |
| Documents | `.pdf .docx .doc .odt .rtf .txt .md` | File upload |
| Data | `.xlsx .xls .csv .tsv .json .xml .yaml .yml` | File upload |
| Presentations | `.pptx .ppt .odp` | File upload |
| Archives | `.zip .tar .gz .tgz .bz2 .7z` | File upload |
| Web | `.html .htm` | File upload |

Source-file extensions such as `.py` and `.log` are intentionally excluded to avoid auto-shipping arbitrary code or logs. Use a code block when source text should appear in the message.

## Forecast Uses

Deliverable mode is useful for:

- daily or weekly active-forecast packets
- calibration and Brier/log-score charts
- backtest result exports
- evidence tables and source snapshots
- resolver packets for pending resolutions
- model-run notebooks or report PDFs
- briefings for stakeholders who do not use the CLI

Treat delivered artifacts as communication outputs. If an artifact contains a new claim, source, model result, or correction that should affect a forecast, write that item to the ledger through `forecast evidence`, `forecast model`, `forecast update`, `forecast resolve`, or the equivalent forecast tool action.

## Encouraging Artifacts

Per-session, ask explicitly for the format:

```text
Send the last 30 days of calibration as a PNG and CSV.
```

```text
Create a resolver packet PDF for forecast 142.
```

Project-level instructions can bias messaging responses toward artifact-style replies. Add that preference to `AGENTS.md`, `CLAUDE.md`, `.cursorrules`, or `agent.custom_instructions` in `~/.superforecasting-agent/config.yaml`.

During migration, legacy profiles may still read custom instructions from `~/.hermes/config.yaml`.

## Task Completion Artifacts

In multi-agent or kanban-style research workflows, workers can attach files to completion notifications:

```python
kanban_complete(
    summary="rendered calibration chart and benchmark report",
    artifacts=[
        "/tmp/calibration-30d.png",
        "/tmp/benchmark-report.pdf",
    ],
)
```

When a subscribed chat receives the completion message, the notifier uploads each existing artifact as a native attachment. Missing files are skipped.

## MCP Sources

MCP servers can help fetch inputs or publish deliverables to external workspaces. Typical forecast-desk uses include:

| Service | Forecast-desk use |
|---|---|
| Notion | Publish forecast review notes or resolver packets |
| GitHub | Attach issue/PR evidence or benchmark fixtures |
| Linear | Link forecast tasks to product or incident workflows |
| Slack | Search channels for timestamped source notes |
| Gmail | Triage alert emails and export evidence candidates |
| Snowflake / BigQuery | Query historical base-rate datasets |
| Google Drive | Find or publish reports and spreadsheets |

Configure MCP servers under `mcp_servers` in `~/.superforecasting-agent/config.yaml`. See [MCP integration](./mcp.md) for setup.

## Security

Deliverable mode only uploads paths that the agent explicitly mentions in its response. It does not scan arbitrary directories. Credentials remain on the user's machine in local auth and environment files; native platform uploads use the configured gateway credentials.
