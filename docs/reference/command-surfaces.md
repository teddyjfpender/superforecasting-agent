# Command surfaces

<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->
<!-- Source of truth: superforecasting_agent/application/command_catalog + tui_gateway/command_routes.py -->
<!-- Regenerate:      python -m scripts.docgen -->
<!-- Staleness gate:  python -m scripts.docgen --check -->

> This page is generated from code. Do not edit it by hand — your change would be overwritten on the next regeneration and the staleness gate would fail. Edit the source instead, then run `python -m scripts.docgen`.

> **Source of truth:** `superforecasting_agent/application/command_catalog + tui_gateway/command_routes.py`

Stable slash-command identities, aliases and adapter dispatch surfaces. These are routing owners, not claims of identical behavior across interfaces.

## Reading the inventory

The canonical name is the stable command ID. Aliases resolve to the same definition; menu order never identifies an operation. Built-ins take precedence over configured quick commands.

Classic CLI dispatch belongs to `cli.py`; messaging dispatch belongs to `gateway/run.py`. Terminal-native commands route through `command.dispatch` / `slash.exec`; other terminal commands are owned by Ink. A configuration gate indicates conditional messaging availability, not a separate command.

The [forecast CLI reference](cli-reference.md) inventories the argparse forecast tree separately. Root runtime commands, plugin commands and local TUI actions are distinct surfaces; this table does not claim to inventory those or establish machine-output/error parity.

## Slash commands

| ID | Aliases | Definition owner | Classic CLI | Messaging | TUI |
| --- | --- | --- | --- | --- | --- |
| `/new` | `/reset` | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/topic` | — | `workflow.py` | unavailable | gateway/run.py | unavailable |
| `/clear` | — | `workflow.py` | cli.py | unavailable | Ink |
| `/redraw` | — | `workflow.py` | cli.py | unavailable | Ink |
| `/history` | — | `workflow.py` | cli.py | unavailable | Ink |
| `/save` | — | `workflow.py` | cli.py | unavailable | Ink |
| `/retry` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/undo` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/title` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/handoff` | — | `workflow.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/branch` | `/fork` | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/compress` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/rollback` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/snapshot` | `/snap` | `workflow.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/stop` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/approve` | — | `workflow.py` | unavailable | gateway/run.py | unavailable |
| `/deny` | — | `workflow.py` | unavailable | gateway/run.py | unavailable |
| `/background` | `/bg`, `/btw` | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/agents` | `/tasks` | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/queue` | `/q` | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/steer` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/goal` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/subgoal` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/status` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/whoami` | — | `workflow.py` | unavailable | gateway/run.py | unavailable |
| `/profile` | — | `workflow.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/sethome` | `/set-home` | `workflow.py` | unavailable | gateway/run.py | unavailable |
| `/resume` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/sessions` | — | `workflow.py` | cli.py | gateway/run.py | Ink |
| `/questions` | `/book`, `/qbook` | `workflow.py` | cli.py | unavailable | Ink |
| `/ledger` | `/store`, `/state` | `workflow.py` | cli.py | unavailable | Ink |
| `/find` | `/search-forecasts`, `/lookup` | `workflow.py` | cli.py | unavailable | Ink |
| `/open` | `/question`, `/show-forecast` | `workflow.py` | cli.py | unavailable | Ink |
| `/note` | `/evidence-for`, `/note-for` | `workflow.py` | cli.py | unavailable | Ink |
| `/revise` | `/update-for`, `/updateq` | `workflow.py` | cli.py | unavailable | Ink |
| `/forecast` | `/forecasts`, `/desk` | `workflow.py` | cli.py | unavailable | Ink |
| `/api-key` | `/apikey`, `/api-keys`, `/keys` | `workflow.py` | cli.py | unavailable | Ink |
| `/config` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/model` | `/provider` | `operations.py` | cli.py | gateway/run.py | Ink |
| `/codex-runtime` | `/codex_runtime` | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/gquota` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/style` | `/personality` | `operations.py` | cli.py | gateway/run.py | Ink |
| `/statusbar` | `/sb` | `operations.py` | cli.py | unavailable | Ink |
| `/verbose` | — | `operations.py` | cli.py | conditional: `display.tool_progress_command` | Ink |
| `/footer` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/yolo` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/reasoning` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/fast` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/skin` | — | `operations.py` | cli.py | unavailable | Ink |
| `/indicator` | — | `operations.py` | cli.py | unavailable | Ink |
| `/voice` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/busy` | — | `operations.py` | cli.py | unavailable | Ink |
| `/tools` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/toolsets` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/skills` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/bundles` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/learn` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/cron` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/curator` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/kanban` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/reload` | — | `operations.py` | cli.py | unavailable | Ink |
| `/reload-mcp` | `/reload_mcp` | `operations.py` | cli.py | gateway/run.py | Ink |
| `/reload-skills` | `/reload_skills` | `operations.py` | cli.py | gateway/run.py | Ink |
| `/browser` | — | `operations.py` | cli.py | unavailable | Ink |
| `/plugins` | — | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/commands` | — | `operations.py` | unavailable | gateway/run.py | unavailable |
| `/help` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/restart` | — | `operations.py` | unavailable | gateway/run.py | unavailable |
| `/usage` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/insights` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/platforms` | `/gateway` | `operations.py` | cli.py | unavailable | command.dispatch / slash.exec |
| `/platform` | — | `operations.py` | unavailable | gateway/run.py | unavailable |
| `/copy` | — | `operations.py` | cli.py | unavailable | Ink |
| `/paste` | — | `operations.py` | cli.py | unavailable | Ink |
| `/image` | — | `operations.py` | cli.py | unavailable | Ink |
| `/update` | — | `operations.py` | cli.py | gateway/run.py | Ink |
| `/debug` | — | `operations.py` | cli.py | gateway/run.py | command.dispatch / slash.exec |
| `/quit` | `/exit` | `operations.py` | cli.py | unavailable | Ink |
