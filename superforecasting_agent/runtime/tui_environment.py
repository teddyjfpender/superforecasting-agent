"""Shared Python runtime settings for native and dashboard TUI launches."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from superforecasting_agent.environment import env_var_alias_nonempty_value


def configure_tui_runtime(env: dict[str, str], project_root: Path, *, dev: bool = False) -> None:
    """Keep the gateway on the launcher's interpreter, source tree and cwd.

    The bundle can live under site-packages or an external directory. Node's
    bundle-relative Python discovery must not decide which installation runs.
    Explicit runtime overrides retain native-first alias precedence.
    """
    defaults = {
        "PYTHON_SRC_ROOT": str(project_root),
        "PYTHON": os.environ.get("PYTHON", "").strip() or sys.executable,
        "CWD": os.getcwd(),
    }
    for name, default in defaults.items():
        aliases = tuple(f"{prefix}_{name}" for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES"))
        value = env_var_alias_nonempty_value(aliases, default=default)
        for alias in aliases:
            env[alias] = value
    env.setdefault("NODE_ENV", "development" if dev else "production")
