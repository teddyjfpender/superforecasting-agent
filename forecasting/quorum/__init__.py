"""Quorum package façade over carved concern modules.

Historically a single ~3.1k-line module, ``forecasting/quorum.py``. Wave 4 of
the modularization program (``docs/plans/2026-07-10-modularization-program.md``,
§W3.a) carves it into concern modules behind an UNCHANGED façade:
``from forecasting.quorum import run_quorum`` — and every other name the module
ever exported — keeps working because this package re-exports the full public
surface of :mod:`forecasting.quorum.core` (which re-imports the carved concern
modules' public names so ``core``'s ``__all__`` stays satisfied) and forwards
attribute reads/writes/deletes to every submodule.

The forward is the D1 monkeypatch-forwarding finding: the former single module
let tests patch a module global at ``forecasting.quorum.<name>`` (e.g.
``make_aiagent_runner`` / ``available_provider_slugs``) and have the patch REACH
the call sites, because caller and callee shared one namespace. After the
module→package carve those call sites live in sibling modules, so ``__setattr__``
forwards the write to every submodule that already binds ``name`` — reproducing
the exact pre-carve monkeypatch semantics with zero test or caller changes.
``__getattr__`` forwards reads so a private name that moved to a leaf (e.g.
``_split_provider_model``, ``_POOL_SHRINK_C``) still resolves at
``forecasting.quorum.<name>``.

Carve map (see the plan's Wave-4 section):

* ``core``       — result types, presets/constants, the ``run_quorum``
  orchestrator, ``make_aiagent_runner``, ``should_research`` — the substrate.
* ``prompts``    — panelist / reconcile / judge / Delphi prompt builders.
* ``parsing``    — panelist/judge response parsing + belief-trajectory coercion.
* ``panels``     — model/provider resolution, reachability, connected + configured
  panel resolution.
* ``estimation`` — preset/call-count/trial machinery + cap logic.
* ``shrinkage``  — the James–Stein pool/trial shrinkage family + final-probability
  + market-anchor discipline.
"""

from __future__ import annotations

import sys as _sys

# Import the carved submodules first so ``forecasting.quorum.core`` /
# ``forecasting.quorum.prompts`` (etc.) are always importable, then re-export
# core's full public surface (which re-imports the carved modules' public names).
from forecasting.quorum import core as _core
from forecasting.quorum import prompts as _prompts  # noqa: F401  (submodule handle)
from forecasting.quorum import parsing as _parsing  # noqa: F401  (submodule handle)
from forecasting.quorum import panels as _panels  # noqa: F401  (submodule handle)
from forecasting.quorum import estimation as _estimation  # noqa: F401  (submodule handle)
from forecasting.quorum import shrinkage as _shrinkage  # noqa: F401  (submodule handle)
from forecasting.quorum.core import *  # noqa: F401,F403  (re-export public surface)

# Submodule handles for the read/write/delete forward. Extended as leaves land.
_SUBMODULES = (_core, _prompts, _parsing, _panels, _estimation, _shrinkage)


# ---------------------------------------------------------------------------
# Module-object monkeypatch façade — the D1 coupling finding (see the docstring).
class _QuorumPackage(type(_sys.modules[__name__])):
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


_sys.modules[__name__].__class__ = _QuorumPackage
