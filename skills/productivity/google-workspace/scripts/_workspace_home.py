"""Resolve the agent home for standalone Google Workspace scripts.

Skill scripts may run outside the Superforecasting Agent process (e.g. system Python,
nix env, CI) where ``superforecasting_agent.constants`` is not importable.  This module
provides the same ``get_agent_home()`` and ``display_agent_home()``
contracts as ``superforecasting_agent.constants`` without requiring it on ``sys.path``.

When ``superforecasting_agent.constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``superforecasting_agent/constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating agent-home environment resolution.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from superforecasting_agent.constants import display_agent_home as display_agent_home
    from superforecasting_agent.constants import get_agent_home as get_agent_home
except (ModuleNotFoundError, ImportError):
    _HOME_ENV_VARS = ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME")

    def get_agent_home() -> Path:
        """Return the agent home directory (default: ~/.superforecasting-agent).

        Mirrors ``superforecasting_agent.constants.get_agent_home()``."""
        for env_var in _HOME_ENV_VARS:
            val = os.environ.get(env_var, "").strip()
            if val:
                return Path(val)
        return Path.home() / ".superforecasting-agent"

    def display_agent_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``superforecasting_agent.constants.display_agent_home()``."""
        home = get_agent_home()
        try:
            return "~/" + str(home.relative_to(Path.home()))
        except ValueError:
            return str(home)
