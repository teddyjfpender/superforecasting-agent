"""Read platform environment metadata without importing plugin implementation code."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from superforecasting_agent.configuration.plugin_environment import environment_metadata


def read_platform_environment(directory: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return result
    for child in sorted(directory.iterdir()):
        if not child.is_dir():
            continue
        path = child / "plugin.yaml"
        if not path.exists():
            path = child / "plugin.yml"
        try:
            manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):
            continue
        for name, metadata in environment_metadata(
            manifest, fallback_label=child.name
        ).items():
            result.setdefault(name, metadata)
    return result
