"""Dashboard package façade over carved section modules.

Historically a single ~2.9k-line module, ``forecasting/dashboard.py``. Wave 4 of
the modularization program (``docs/plans/2026-07-10-modularization-program.md``,
§W3.b) carves it into section modules behind an UNCHANGED façade:
``from forecasting.dashboard import build_workspace_payload`` — and every other
name the module ever exported — keeps working because this package re-exports
the full public surface of :mod:`forecasting.dashboard.core` (which re-imports
the carved sections' public names) and forwards attribute reads/writes/deletes
to every submodule.

``build_workspace_payload`` output stays BYTE-IDENTICAL for a fixed ledger
fixture across the carve — the moves-only conformance proof (the payload
assembly is only relocated, never rewritten). ``__getattr__`` forwards reads so a
private helper that moved to a section (e.g. ``_distribution_view``,
``_candidate_intervals``, ``_belief_trajectory_line``) still resolves at
``forecasting.dashboard.<name>`` for the tests that import it.

Carve map (see the plan's Wave-4 section):

* ``core``       — the workspace-payload assembler, VOI/attention engine,
  dashboard-summary + text renderers, and the standalone formatters — the substrate.
* ``scoreboard`` — the benchmark scoreboard + its Brier/baseline helpers.
* ``thesis``     — thesis/factor summaries, workspace thesis/factor sections,
  candidate intervals, event-sensitivity.
* ``headline``   — compact display strings and compatibility summary aliases.
  Distribution interpretation is owned by ``forecasting.distribution_summary``.
* ``panel``      — the workspace panel-detail + belief-trajectory section.
"""

from __future__ import annotations

import sys as _sys

# Import the carved submodules first so ``forecasting.dashboard.core`` /
# ``forecasting.dashboard.scoreboard`` (etc.) are always importable, then
# re-export core's full public surface (core re-imports the sections' publics).
from forecasting.dashboard import core as _core
from forecasting.dashboard import scoreboard as _scoreboard  # noqa: F401  (submodule handle)
from forecasting.dashboard import headline as _headline  # noqa: F401  (submodule handle)
from forecasting.dashboard import thesis as _thesis  # noqa: F401  (submodule handle)
from forecasting.dashboard import panel as _panel  # noqa: F401  (submodule handle)
from forecasting.dashboard.core import *  # noqa: F401,F403  (re-export public surface)

# Submodule handles for the read/write/delete forward. Extended as leaves land.
_SUBMODULES = (_core, _scoreboard, _headline, _thesis, _panel)


class _DashboardPackage(type(_sys.modules[__name__])):
    def __getattr__(self, name):
        for _m in _SUBMODULES:
            try:
                return getattr(_m, name)
            except AttributeError:
                continue
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}")

    def __setattr__(self, name, value):
        for _m in _SUBMODULES:
            if hasattr(_m, name):
                setattr(_m, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        for _m in _SUBMODULES:
            if hasattr(_m, name):
                try:
                    delattr(_m, name)
                except AttributeError:
                    pass
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _DashboardPackage
