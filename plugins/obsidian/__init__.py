"""obsidian plugin — native vault integration for notes, learnings, opinions.

The forecast desk treats an Obsidian vault as its publishing surface: the
agent can read/write/search notes directly (wikilinks, frontmatter), and
``obsidian_sync_learnings`` publishes the ledger's calibration lessons and
question dossiers (description, current probability, analyst-note timeline)
as a linked knowledge graph under ``Forecasting/``.

Direction of trust: the ledger DB is the source of truth, the vault is a
view. Generated notes keep agent content inside managed markers so human
annotations around them survive re-syncs.

Vault resolution: ``OBSIDIAN_VAULT_PATH`` env var, falling back to
``~/Documents/Obsidian Vault`` — same convention as the bundled obsidian
skill.
"""

from __future__ import annotations

from plugins.obsidian.cli import obsidian_command as _obsidian_command
from plugins.obsidian.cli import register_cli as _register_obsidian_cli
from plugins.obsidian.tools import (
    OBSIDIAN_APPEND_NOTE_SCHEMA,
    OBSIDIAN_READ_NOTE_SCHEMA,
    OBSIDIAN_SEARCH_SCHEMA,
    OBSIDIAN_SYNC_LEARNINGS_SCHEMA,
    OBSIDIAN_WRITE_NOTE_SCHEMA,
    check_obsidian_available,
    handle_obsidian_append_note,
    handle_obsidian_read_note,
    handle_obsidian_search,
    handle_obsidian_sync_learnings,
    handle_obsidian_write_note,
)

_TOOLS = (
    ("obsidian_read_note",      OBSIDIAN_READ_NOTE_SCHEMA,      handle_obsidian_read_note,      "📖"),
    ("obsidian_write_note",     OBSIDIAN_WRITE_NOTE_SCHEMA,     handle_obsidian_write_note,     "📝"),
    ("obsidian_append_note",    OBSIDIAN_APPEND_NOTE_SCHEMA,    handle_obsidian_append_note,    "➕"),
    ("obsidian_search",         OBSIDIAN_SEARCH_SCHEMA,         handle_obsidian_search,         "🔍"),
    ("obsidian_sync_learnings", OBSIDIAN_SYNC_LEARNINGS_SCHEMA, handle_obsidian_sync_learnings, "🧠"),
)


def register(ctx) -> None:
    """Register tools and the ``obsidian`` CLI command.

    Called once by the plugin loader when the plugin is enabled via
    ``plugins.enabled`` in config.yaml.
    """
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="obsidian",
            schema=schema,
            handler=handler,
            check_fn=check_obsidian_available,
            emoji=emoji,
        )

    ctx.register_cli_command(
        name="obsidian",
        help="Obsidian vault (notes, learnings sync)",
        setup_fn=_register_obsidian_cli,
        handler_fn=_obsidian_command,
        description=(
            "Publish the forecast desk's lessons and question dossiers into "
            "an Obsidian vault, and inspect the vault from the CLI. See: "
            "superforecasting-agent obsidian status"
        ),
    )
