"""Plugin activation policy shared by hosts and inspection surfaces."""

from collections.abc import Collection
from dataclasses import dataclass

from superforecasting_agent.configuration.plugin_manifest import PluginManifest


@dataclass(frozen=True)
class PluginActivation:
    """Whether the general loader imports a plugin, and its visible status."""

    load: bool
    enabled: bool
    reason: str | None = None


def plugin_activation(
    manifest: PluginManifest,
    *,
    enabled: Collection[str] | None,
    disabled: Collection[str],
) -> PluginActivation:
    """Apply explicit disables before bundled defaults and opt-in activation.

    Model providers belong to a separate lazy loader. Their enabled status here
    means available to that loader, not imported by the general plugin manager.
    """
    key = manifest.key or manifest.name
    if key in disabled or manifest.name in disabled:
        return PluginActivation(False, False, "disabled via config")
    if manifest.source == "bundled" and manifest.name == "obsidian":
        return PluginActivation(True, True)
    if manifest.kind == "exclusive":
        return PluginActivation(
            False, False, "exclusive plugin — activate via <category>.provider config"
        )
    if manifest.kind == "model-provider":
        return PluginActivation(False, True)
    if manifest.source == "bundled" and manifest.kind in {"backend", "platform"}:
        return PluginActivation(True, True)
    if enabled is not None and (key in enabled or manifest.name in enabled):
        return PluginActivation(True, True)
    return PluginActivation(
        False,
        False,
        "not enabled in config (run `superforecasting-agent plugins enable {}` to activate)".format(
            key
        ),
    )
