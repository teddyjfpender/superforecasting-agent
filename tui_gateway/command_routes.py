"""Terminal command ownership shared by dispatch and consumer parity checks."""

from superforecasting_agent.application.command_catalog import COMMAND_REGISTRY

# Implemented by command.dispatch or slash.exec without a classic CLI instance.
NATIVE_COMMANDS = frozenset({
    'tools', 'agents', 'stop', 'handoff', 'footer', 'debug', 'skills', 'kanban',
    'config', 'plugins', 'toolsets', 'profile', 'bundles', 'insights', 'codex-runtime',
    'gquota', 'platforms', 'cron', 'curator', 'retry', 'queue', 'steer',
    'goal', 'subgoal', 'learn', 'snapshot',
})


def terminal_command_names() -> frozenset[str]:
    """Commands whose Ink handler selects the dedicated operation or local UI.

    Cross-language parity checks require a terminal handler for every entry.
    New catalog commands must acquire a native or terminal owner before shipping.
    """
    return frozenset(
        command.name for command in COMMAND_REGISTRY
        if not command.gateway_only and command.name not in NATIVE_COMMANDS
    )
