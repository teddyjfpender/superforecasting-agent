"""Resolve the agent home for standalone Google Workspace scripts.

Skill scripts may run outside the Superforecasting Agent process (e.g. system Python,
nix env, CI) where ``hermes_constants`` is not importable.  This module
provides the same ``get_hermes_home()`` and ``display_hermes_home()``
contracts as ``hermes_constants`` without requiring it on ``sys.path``.

When ``hermes_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``hermes_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating agent-home environment resolution.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from hermes_constants import display_hermes_home as display_hermes_home
    from hermes_constants import get_hermes_home as get_hermes_home
except (ModuleNotFoundError, ImportError):
    _HOME_ENV_VARS = ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME")

    def get_hermes_home() -> Path:
        """Return the agent home directory (default: ~/.superforecasting-agent).

        Mirrors ``hermes_constants.get_hermes_home()``."""
        for env_var in _HOME_ENV_VARS:
            val = os.environ.get(env_var, "").strip()
            if val:
                return Path(val)
        return Path.home() / ".superforecasting-agent"

    def display_hermes_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``hermes_constants.display_hermes_home()``."""
        home = get_hermes_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
