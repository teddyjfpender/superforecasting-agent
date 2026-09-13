"""Shared plugin inspection used by terminal command consumers."""

from superforecasting_agent.constants import display_agent_home


def describe_plugins() -> str:
    """Inspect the active plugin manager without constructing a chat runtime."""
    from superforecasting_agent.runtime.plugins import get_plugin_manager

    plugins = get_plugin_manager().list_plugins()
    if not plugins:
        return (
            "No plugins installed.\n"
            f"Drop plugin directories into {display_agent_home()}/plugins/ to get started."
        )
    lines = [f"Plugins ({len(plugins)}):"]
    for plugin in plugins:
        status = "✓" if plugin["enabled"] else "✗"
        version = f" v{plugin['version']}" if plugin["version"] else ""
        counts = [
            f"{plugin[key]} {key}"
            for key in ("tools", "hooks", "commands")
            if plugin.get(key)
        ]
        detail = f" ({', '.join(counts)})" if counts else ""
        error = f" — {plugin['error']}" if plugin["error"] else ""
        lines.append(f"  {status} {plugin['name']}{version}{detail}{error}")
    return "\n".join(lines)
