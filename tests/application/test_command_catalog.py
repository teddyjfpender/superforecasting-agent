"""The shared command catalog works independently of all product presentation."""

import subprocess
import sys

from superforecasting_agent.application import command_catalog


def test_catalog_import_and_alias_resolution_do_not_load_presentation():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from superforecasting_agent.application.command_catalog import resolve_command, expand_quick_alias
assert resolve_command('/HELP').name == 'help'
assert expand_quick_alias('/fixture-alias Arg', {'fixture-alias': {'type': 'alias', 'target': 'help'}}) == '/help Arg'
for name in sys.modules:
    assert not any(name == prefix or name.startswith(prefix + '.') for prefix in (
        'cli', 'tui_gateway', 'gateway', 'prompt_toolkit', 'rich',
        'superforecasting_agent.runtime',
    )), name
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_classic_compatibility_exports_share_catalog_identity():
    from superforecasting_agent.runtime import commands

    for name in (
        "CommandDef",
        "COMMAND_REGISTRY",
        "COMMAND_CATEGORY_ORDER",
        "SUBCOMMANDS",
        "resolve_command",
        "expand_quick_alias",
    ):
        assert getattr(commands, name) is getattr(command_catalog, name)
    for command in command_catalog.COMMAND_REGISTRY:
        assert command_catalog.resolve_command(command.name) is command
        for alias in command.aliases:
            assert command_catalog.resolve_command(alias) is command


def test_catalog_rejects_alias_collisions_and_unreachable_capabilities():
    import pytest
    from superforecasting_agent.application.command_catalog import CommandDef

    base = CommandDef('first', 'Description', 'Session', aliases=('alias',))
    invalid = [
        [base, CommandDef('alias', 'Collision', 'Session')],
        [base, CommandDef('second', 'Collision', 'Session', aliases=('alias',))],
        [CommandDef('same', 'Redundant alias', 'Session', aliases=('same',))],
        [CommandDef('/help', 'Slash in identity', 'Session')],
        [CommandDef('UPPER', 'Unreachable spelling', 'Session')],
        [CommandDef('hidden', 'No consumer', 'Session', cli_only=True, gateway_only=True)],
        [CommandDef('gate', 'No restriction to override', 'Session', gateway_config_gate='display.enabled')],
    ]
    for commands in invalid:
        with pytest.raises(ValueError):
            command_catalog._build_command_lookup(commands)
    lookup = command_catalog._build_command_lookup([base])
    assert lookup['first'] is lookup['alias'] is base


def test_generated_surface_inventory_tracks_catalog_and_gated_messaging():
    from scripts.docgen.command_surfaces_doc import render

    output = render()
    for command in command_catalog.COMMAND_REGISTRY:
        assert output.count(f'| `/{command.name}` |') == 1
        for alias in command.aliases:
            assert f'`/{alias}`' in output
    assert 'conditional: `display.tool_progress_command`' in output
    assert 'machine-output/error parity' in output
