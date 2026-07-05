"""Forecast CLI package (façade over the carved subcommand core).

Historically a single ~16.6k-line module, ``forecasting/cli.py``. Arc D of the
architecture delivery plan carves it into subcommand modules behind an UNCHANGED
façade: ``from forecasting.cli import main`` — and every other name the module
ever exported (``register_cli``, ``run_forecast_chain``, ``cmd_forecast``, the
``_cmd_*`` handlers, ``AUTO_FORECAST_STAGES`` …) — keeps working because this
package re-exports the full public surface of :mod:`forecasting.cli.core` and
forwards every remaining attribute (including the private ``_cmd_*`` handlers that
tests import and monkeypatch) to ``core``.

The module→package move (this file + ``core.py``) is the D1 pattern: the move
alone leaves every caller and test green. Subsequent slices carve subcommand
domains out of ``core`` into sibling modules, each registering its subparsers via
a shared hook and each keeping the same façade guarantee — no caller ever
changes.
"""

from __future__ import annotations

import sys as _sys

# Import the carved body first so ``forecasting.cli.core`` is always importable,
# then re-export its full public surface.
from forecasting.cli import core as _core
from forecasting.cli.core import *  # noqa: F401,F403  (re-export public surface)


# ---------------------------------------------------------------------------
# Module-global monkeypatch/access façade — the D1 coupling finding, applied one
# layer out to the CLI.
#
# The former single module let callers READ every name at ``forecasting.cli.<name>``
# (incl. private ``_cmd_*`` handlers: ``from forecasting.cli import _cmd_lint``,
# ``import forecasting.cli as cli; cli._resolve_active_model_id``) and PATCH module
# globals (``setattr(cli, "_run_update_agent", fake)``) and have the patch REACH the
# call sites, because those lived in the SAME module namespace. After the
# module→package carve the bodies live in ``forecasting.cli.core``, so:
#
#   * ``__getattr__`` forwards reads of any name NOT in the package namespace
#     (every private helper/handler) to ``core`` — reproducing the pre-carve read
#     surface for both ``from forecasting.cli import _x`` and ``cli._x``.
#   * ``__setattr__``/``__delattr__`` forward writes to ``core`` when ``core`` owns
#     the name, so a monkeypatch on the package reaches core's call sites exactly
#     as the pre-carve single module did.
class _CliPackage(type(_sys.modules[__name__])):
    def __getattr__(self, name):  # only called when normal lookup fails
        return getattr(_core, name)

    def __setattr__(self, name, value):
        if hasattr(_core, name):
            setattr(_core, name, value)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        if hasattr(_core, name):
            try:
                delattr(_core, name)
            except AttributeError:
                pass
        super().__delattr__(name)


_sys.modules[__name__].__class__ = _CliPackage
