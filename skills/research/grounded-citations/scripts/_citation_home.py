"""Resolve the active forecast home for standalone skill scripts.

Skill scripts may run outside the agent process (system Python, nix env,
CI) where ``superforecasting_agent.constants`` is not importable.  This module provides the
same ``get_agent_home()`` contract without requiring it on ``sys.path``.

When ``superforecasting_agent.constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from superforecasting_agent.constants import get_agent_home as get_agent_home
except (ModuleNotFoundError, ImportError):

    def get_agent_home() -> Path:
        """Return the forecast home (default: ``~/.superforecasting-agent``)."""
        for key in ("SUPERFORECASTING_AGENT_HOME", "FORECAST_HOME", "HERMES_HOME"):
            value = os.environ.get(key, "").strip()
            if value:
                return Path(value)
        return Path.home() / ".superforecasting-agent"
