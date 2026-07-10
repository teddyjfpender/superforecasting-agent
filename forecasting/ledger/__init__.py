"""Forecast ledger package (façade over carved domain modules).

Historically a single ~16k-line module, ``forecasting/ledger.py``. Arc D of the
architecture delivery plan carves it into domain modules behind an UNCHANGED
façade: ``from forecasting.ledger import ForecastLedger`` — and every other name
the module ever exported — keeps working because this package re-exports the
full public surface of :mod:`forecasting.ledger.core` (which itself pulls the
carved domain modules' shared constants back in).

Carve order (see the delivery plan's Arc D):

* ``core``      — connection, migrations, and everything not yet carved out.
* ``gate``      — the shared write-gate leaf (allow_ledger_writes + the SQLite
  authorizer + _enforce_write_gate) every gated write domain depends on.
* ``watches``   — D1, the pattern-prover: watched-source lifecycle + constants.
* ``questions`` — D2: question CRUD + spec-quality + per-forecast config.
* ``evidence``  — D3: evidence lifecycle + freshness helpers + triage glue.
* ``snapshots`` — D4: create_snapshot (the gated commit body) + snapshot
  readers/serializers + annotate.
* ``panels``    — D5: panel-run lifecycle + serializers + track-record weighting.
* ``reviews``   — D6: scheduled reviews + cadence resolution + the review sweep.
* ``alerts``    — D7: the doctor ``self_check`` engine + ``alert_events`` CRUD/
  lifecycle + saturation/producer/reconcile glue.
* ``theses``    — D8: thesis/factor member+entity CRUD + the aggregation engine +
  narratives + the re-aggregate cascade.
* ``scoring``   — D9: resolution scoring + Brier/calibration display + the paired-
  bootstrap edge test + lesson-application auditing.

The façade guarantees ``no caller changed``: `ForecastLedger` stays THE public
class; each carved method keeps a one-line delegate on the class, so external
call sites are byte-for-byte unchanged.
"""

from __future__ import annotations

import sys as _sys

# Import the carved submodules first so ``forecasting.ledger.core`` /
# ``forecasting.ledger.watches`` are always importable, then re-export core's
# full public surface (which includes the watch constants core imports back).
from forecasting.ledger import core as _core
from forecasting.ledger import gate as _gate  # noqa: F401  (write-gate leaf handle)
from forecasting.ledger import watches as _watches  # noqa: F401  (submodule handle)
from forecasting.ledger import questions as _questions  # noqa: F401  (submodule handle)
from forecasting.ledger import evidence as _evidence  # noqa: F401  (submodule handle)
from forecasting.ledger import snapshots as _snapshots  # noqa: F401  (submodule handle)
from forecasting.ledger import panels as _panels  # noqa: F401  (submodule handle)
from forecasting.ledger import reviews as _reviews  # noqa: F401  (submodule handle)
from forecasting.ledger import alerts as _alerts  # noqa: F401  (submodule handle)
from forecasting.ledger import theses as _theses  # noqa: F401  (submodule handle)
from forecasting.ledger import scoring as _scoring  # noqa: F401  (submodule handle)
from forecasting.ledger import resolutions as _resolutions  # noqa: F401  (submodule handle)
from forecasting.ledger import lessons as _lessons  # noqa: F401  (submodule handle)
from forecasting.ledger import model_scoring as _model_scoring  # noqa: F401  (submodule handle)
from forecasting.ledger import backtest as _backtest  # noqa: F401  (submodule handle)
from forecasting.ledger import market_models as _market_models  # noqa: F401  (submodule handle)
from forecasting.ledger import question_meta as _question_meta  # noqa: F401  (submodule handle)
from forecasting.ledger import source_signatures as _source_signatures  # noqa: F401  (submodule handle)
from forecasting.ledger import refresh as _refresh  # noqa: F401  (submodule handle)
from forecasting.ledger import autopilot as _autopilot  # noqa: F401  (submodule handle)
from forecasting.ledger import exports as _exports  # noqa: F401  (submodule handle)
from forecasting.ledger.core import *  # noqa: F401,F403  (re-export public surface)

# ``core`` re-exports the watch constants it still uses (ROLES/TYPES); re-export
# the full watch-constant surface here so ``forecasting.ledger.WATCH_SCOPE_TYPES``
# — which the pre-carve module exposed — keeps resolving even though ``core`` no
# longer references it.
from forecasting.ledger.watches import (  # noqa: F401  (re-export, surface parity)
    WATCH_SCOPE_TYPES,
    WATCH_SOURCE_ROLES,
    WATCH_SOURCE_TYPES,
)

# ``SCHEDULE_SCOPE_TYPES`` moved to the ``reviews`` leaf (D6). Re-export it here so
# ``forecasting.ledger.SCHEDULE_SCOPE_TYPES`` — which the pre-carve module exposed —
# keeps resolving even though ``core`` no longer defines it (mirrors WATCH_SCOPE_TYPES).
from forecasting.ledger.reviews import SCHEDULE_SCOPE_TYPES  # noqa: F401  (surface parity)

# ``THESIS_MEMBER_ROLES`` moved to the ``theses`` leaf (D8). Re-export it here so
# ``forecasting.ledger.THESIS_MEMBER_ROLES`` — which the pre-carve module exposed —
# keeps resolving even though ``core`` no longer defines it (mirrors WATCH_SCOPE_TYPES).
from forecasting.ledger.theses import THESIS_MEMBER_ROLES  # noqa: F401  (surface parity)

# The paired-bootstrap constants moved to the ``scoring`` leaf (D9). Re-export them
# here so ``forecasting.ledger.PAIRED_BOOTSTRAP_SEED`` / ``…_DRAWS`` — which the
# pre-carve module exposed (tests import them) — keep resolving even though ``core``
# no longer defines them (mirrors WATCH_SCOPE_TYPES / THESIS_MEMBER_ROLES).
from forecasting.ledger.scoring import (  # noqa: F401  (surface parity)
    PAIRED_BOOTSTRAP_DRAWS,
    PAIRED_BOOTSTRAP_SEED,
)


# ---------------------------------------------------------------------------
# Module-global monkeypatch façade — the D1 coupling finding.
#
# The former single module let tests patch module globals at
# ``forecasting.ledger.<name>`` (e.g. ``urlopen``) and have the patch REACH the
# call sites, because those call sites lived in the SAME module namespace. After
# the module→package carve the bodies live in ``forecasting.ledger.core``, so a
# plain re-export would leave ``forecasting.ledger.urlopen = fake`` invisible to
# core's call sites (distinct global namespace). Forwarding attribute writes to
# ``core`` reproduces the exact pre-carve monkeypatch semantics with ZERO test
# or caller changes — the façade behaves identically to the old module.
class _LedgerPackage(type(_sys.modules[__name__])):
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


_sys.modules[__name__].__class__ = _LedgerPackage
