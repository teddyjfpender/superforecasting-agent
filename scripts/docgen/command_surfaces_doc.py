"""Derive slash-command identities and adapter surfaces from existing catalogs."""

from scripts.docgen.common import header
from superforecasting_agent.application.command_catalog import COMMAND_REGISTRY
from superforecasting_agent.application.command_catalog.operations import (
    COMMANDS as OPERATIONS,
)
from tui_gateway.command_routes import NATIVE_COMMANDS


def render() -> str:
    lines = [
        header(
            "Command surfaces",
            "superforecasting_agent/application/command_catalog + tui_gateway/command_routes.py",
            blurb="Stable slash-command identities, aliases and adapter dispatch surfaces. These are routing owners, not claims of identical behavior across interfaces.",
        ),
        "## Reading the inventory",
        "",
        "The canonical name is the stable command ID. Aliases resolve to the same definition; menu order never identifies an operation. Built-ins take precedence over configured quick commands.",
        "",
        "Classic CLI dispatch belongs to `cli.py`; messaging dispatch belongs to `gateway/run.py`. Terminal-native commands route through `command.dispatch` / `slash.exec`; other terminal commands are owned by Ink. A configuration gate indicates conditional messaging availability, not a separate command.",
        "",
        "The [forecast CLI reference](cli-reference.md) inventories the argparse forecast tree separately. Root runtime commands, plugin commands and local TUI actions are distinct surfaces; this table does not claim to inventory those or establish machine-output/error parity.",
        "",
        "## Slash commands",
        "",
        "| ID | Aliases | Definition owner | Classic CLI | Messaging | TUI |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    operation_ids = {id(command) for command in OPERATIONS}
    for command in COMMAND_REGISTRY:
        owner = "operations.py" if id(command) in operation_ids else "workflow.py"
        messaging = (
            "conditional: `" + command.gateway_config_gate + "`"
            if command.gateway_config_gate
            else "unavailable"
            if command.cli_only
            else "gateway/run.py"
        )
        terminal = (
            "unavailable"
            if command.gateway_only
            else "command.dispatch / slash.exec"
            if command.name in NATIVE_COMMANDS
            else "Ink"
        )
        aliases = ", ".join(f"`/{alias}`" for alias in command.aliases) or "—"
        classic = "unavailable" if command.gateway_only else "cli.py"
        lines.append(
            f"| `/{command.name}` | {aliases} | `{owner}` | {classic} | {messaging} | {terminal} |"
        )
    return "\n".join(lines) + "\n"
