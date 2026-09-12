"""Read plugin declarations without importing plugin implementations."""

import logging
from pathlib import Path

from superforecasting_agent.configuration.plugin_manifest import (
    VALID_PLUGIN_KINDS,
    PluginManifest,
    parse_manifest,
)

logger = logging.getLogger(__name__)


def read_plugin_manifest(
    manifest_file: Path, plugin_dir: Path, source: str, prefix: str = ""
) -> PluginManifest:
    """Read and validate metadata; leave discovery failure policy to the caller.

    Legacy provider routing examines at most 8192 characters of source text.
    Explicit kind declarations always take precedence over that heuristic.
    """
    import yaml

    data = yaml.safe_load(manifest_file.read_text(encoding="utf-8"))
    data = {} if data is None else data
    manifest = parse_manifest(
        data,
        directory_name=plugin_dir.name,
        path=str(plugin_dir),
        source=source,
        prefix=prefix,
    )
    raw_kind = data.get("kind", "standalone")
    if isinstance(raw_kind, str) and raw_kind.strip().lower() not in VALID_PLUGIN_KINDS:
        logger.warning(
            "Plugin %s: unknown kind '%s' (valid: %s); treating as 'standalone'",
            manifest.key,
            raw_kind,
            ", ".join(sorted(VALID_PLUGIN_KINDS)),
        )
    if "kind" not in data:
        try:
            with (plugin_dir / "__init__.py").open(
                encoding="utf-8", errors="replace"
            ) as handle:
                source_text = handle.read(8192)
        except OSError:
            source_text = ""
        if "register_memory_provider" in source_text or "MemoryProvider" in source_text:
            manifest.kind = "exclusive"
        elif "register_provider" in source_text and "ProviderProfile" in source_text:
            manifest.kind = "model-provider"
    return manifest
