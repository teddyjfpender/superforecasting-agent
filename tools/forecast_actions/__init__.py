"""Tool-action registry for the forecast ledger tool.

Each domain submodule exposes a ``HANDLERS`` mapping of ``action -> handler(args,
ledger)``.  ``ACTIONS`` aggregates them; ``forecast_ledger_tool`` reads it.  The
submodules import helpers from :mod:`tools.forecasting_tool` at load, so this
package is imported LAZILY (inside ``forecast_ledger_tool``) to avoid an
import-time cycle -- by first-call time the facade module is fully initialised.
"""

from __future__ import annotations

from typing import Any, Callable

from . import (
    questions,
    resolution,
    forecast_update,
    models,
    evidence,
    sources,
    panels,
    reviews,
    calibration,
    autopilot,
    markets,
    triage,
    diagnostics,
)

ACTIONS: dict[str, Callable[[dict[str, Any], Any], str]] = {}
for _module in (
    questions,
    resolution,
    forecast_update,
    models,
    evidence,
    sources,
    panels,
    reviews,
    calibration,
    autopilot,
    markets,
    triage,
    diagnostics,
):
    ACTIONS.update(_module.HANDLERS)

__all__ = ["ACTIONS"]
