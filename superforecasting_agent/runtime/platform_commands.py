"""Configuration-only messaging inspection shared by terminal consumers."""

from superforecasting_agent.constants import display_agent_home


def platform_configuration_lines(argument: str = "") -> list[str]:
    if argument.strip():
        raise ValueError("Usage: /platforms")
    from gateway.config import Platform, load_gateway_config
    from superforecasting_agent.platform_registry import platform_registry

    config = load_gateway_config()
    platforms = set(Platform) | set(config.platforms)
    platforms.discard(Platform.LOCAL)
    lines = [
        "Messaging platform configuration",
        "Live connections are not checked.",
        "",
    ]
    for platform in sorted(platforms, key=lambda item: item.value):
        entry = platform_registry.get(platform.value)
        label = entry.label if entry else platform.value
        settings = config.platforms.get(platform)
        if settings is None:
            state = "Not configured"
        elif settings.enabled:
            state = "Enabled in configuration"
        else:
            state = "Disabled in configuration"
        home = config.get_home_channel(platform)
        destination = f" → {home.name}" if home else ""
        lines.append(f"{label}: {state}{destination}")
    policy = config.default_reset_policy
    lines.extend([
        "",
        "Session reset policy:",
        f"Mode: {policy.mode}",
        f"Daily reset at: {policy.at_hour}:00",
        f"Idle timeout: {policy.idle_minutes} minutes",
        "",
        "Start: superforecasting-agent gateway",
        f"Configuration file: {display_agent_home()}/config.yaml",
    ])
    return lines
