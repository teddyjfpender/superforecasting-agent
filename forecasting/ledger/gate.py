"""Ledger write-gate leaf (the ONE cross-domain dependency every carve needs).

Arc D of the architecture delivery plan carves ``forecasting/ledger.py`` into
domain modules behind an unchanged façade. Every gated write domain
(``create_question`` in D2's ``questions``, ``create_snapshot`` in D4's
``snapshots``, ``record_panel_run`` in D5's ``panels``) needs the SAME direct-
write gate machinery — the contextvar, the ``allow_ledger_writes`` context, the
connection-level SQLite authorizer, and ``_enforce_write_gate``. D1/D2/D3 all
flagged that this shared machinery should become its own leaf BEFORE D4
(snapshots) so multiple domains share it without a ``_core.`` hop.

This module is a LEAF: it imports only stdlib + :mod:`forecasting.models`
(for ``ForecastingError``). It has NO load-time dependency on
:mod:`forecasting.ledger.core`, so there is no import cycle — ``core`` imports
the names it needs BACK from here and re-exports them, so the pre-carve public
surface (``forecasting.ledger.allow_ledger_writes`` and friends) is byte-for-
byte unchanged.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import sqlite3

from forecasting.models import ForecastingError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Direct-write gate.
#
# The desk agent has, in the past, fabricated forecasts by scripting the
# ForecastLedger directly — importing it from an ad-hoc script and calling
# create_snapshot / create_question / record_panel_run (or raw INSERT/UPDATE
# via _connect()) — thereby bypassing the calibration / panel / evidence gates
# that the gated forecast TOOL enforces on the commit path.
#
# This guard refuses a *forecast-producing* WRITE attempted OUTSIDE a recognised
# commit context. A legitimate writer (the forecast tool's commit flow, the
# market-nightly + cron jobs, the autonomous cycle, schema migrations, and the
# CLI's own forecast commands) opens that context with `allow_ledger_writes()`
# (or, for whole-database setup, `allow_ledger_writes(reason="...")`). Reads are
# NEVER gated — scripts may freely audit / migrate-read the ledger; only the
# three forecast-producing write methods are guarded.
#
# Mode is a config flag (FORECAST_GATE_DIRECT_WRITES), default the strongest
# verified-safe mode ("on"):
#   on    -> refuse the write with a clear ForecastingError (DEFAULT)
#   warn  -> allow the write but log a warning (doctor/audit signal)
#   off   -> no-op (the legacy behaviour)
# The contextvar carries the active-commit flag (process- AND task-local, so a
# gateway thread-pool / asyncio worker each see their own state).
_FORECAST_COMMIT_ACTIVE: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "forecasting_tool_commit_active", default=False
)
_FORECAST_SNAPSHOT_WRITES_ALLOWED: "contextvars.ContextVar[bool]" = contextvars.ContextVar(
    "forecasting_snapshot_writes_allowed", default=True
)

# The three forecast-producing write methods the gate protects by name.
GATED_LEDGER_WRITES = ("create_question", "create_snapshot", "record_panel_run")

# The forecast-PRODUCING tables the connection-level authorizer protects. A
# script that grabs a raw connection via `_connect()` and INSERTs a new row into
# any of these is denied at QUERY time unless a recognised commit context is
# active — this is the real bypass vector (method-name gating alone is trivially
# side-stepped by `led._connect()`).
#
# We gate INSERT (row CREATION) specifically, because the three forecast-
# producing methods this mirrors — create_question / create_snapshot /
# record_panel_run — are precisely the row-creators (each is a single
# `INSERT INTO <table>`), and fabricating a forecast means creating a question /
# snapshot / panel-run row. We deliberately do NOT gate UPDATE/DELETE on these
# tables: many legitimate, non-fabrication operations UPDATE them outside any
# commit context (resolving a question -> status, editing config/metadata/title,
# setting current_forecast_id, attaching a panel-run snapshot, thesis
# re-aggregation), and those must keep working with the gate ON. Reads are never
# touched (audits/migrations script the ledger freely).
GATED_LEDGER_TABLES = frozenset(
    {
        "forecast_questions",
        "forecast_snapshots",
        "panel_runs",
        # Deviation bets (UPGRADE 2): a forecast-producing artifact (the desk's
        # named-edge bet AGAINST the market). Creating one is a gated write — an
        # ad-hoc script cannot fabricate a bet outside the quorum commit context.
        "deviation_bets",
        # Watch config drives every automated data flow (refresh, autopilot,
        # alerts): a script mass-inserting watches is the same bypass class as
        # a scripted forecast. The tool exposes add_watched_source and the bulk
        # add_watched_sources for the legitimate path.
        "watched_sources",
    }
)


def _authorize_ledger_write(action, arg1, arg2, db_name, trigger_or_view):
    """SQLite authorizer: deny forecast-producing row CREATION outside a commit context.

    Installed by ``ForecastLedger._connect`` so the gate fires at the CONNECTION
    level — a raw ``led._connect().execute("INSERT INTO forecast_snapshots …")``
    from an ad-hoc script is refused the same as a gated method call, because the
    authorizer checks the live contextvar at query time (so it fires even for
    scripts the agent runs via the terminal tool, in-process).

    Returns ``SQLITE_DENY`` only for an ``INSERT`` into a forecast-producing
    table (``GATED_LEDGER_TABLES``) when (a) no commit context is active AND
    (b) the gate mode is ``on``. Everything else — reads, DDL (CREATE/ALTER
    TABLE, so schema init + migrations run in ``__init__`` outside any
    allow-context keep working), transactions, PRAGMA, every UPDATE/DELETE on
    these tables (resolve/config/aggregation), writes to non-forecast tables,
    inserts inside a commit context, and every action under ``warn``/``off``
    mode — is allowed. SQLite passes the target table name in ``arg1`` for
    INSERT actions.
    """
    if action != sqlite3.SQLITE_INSERT:
        return sqlite3.SQLITE_OK
    if arg1 not in GATED_LEDGER_TABLES:
        return sqlite3.SQLITE_OK
    if (
        arg1 == "forecast_snapshots"
        and os.environ.get("FORECAST_COMMIT_POLICY", "").strip().lower()
        == "proposal_only"
    ):
        return sqlite3.SQLITE_DENY
    if _FORECAST_COMMIT_ACTIVE.get():
        return sqlite3.SQLITE_OK
    # warn/off never block at the connection level (the method-level
    # _enforce_write_gate already logs the warn signal); only "on" denies.
    if ledger_write_gate_mode() != "on":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _ledger_write_authorizer(action, arg1, arg2, db_name, trigger_or_view):
    try:
        return _authorize_ledger_write(action, arg1, arg2, db_name, trigger_or_view)
    except BaseException:
        # sqlite3 replaces callback exceptions with "not authorized", including
        # deadline exceptions during SELECT. Retain the actual traceback without
        # logging SQL parameters or relaxing the authorization decision.
        logger.exception("SQLite authorizer callback failed (action=%s, table=%s)", action, arg1)
        raise


def ledger_write_gate_mode() -> str:
    """Return the active direct-write gate mode: 'on' | 'warn' | 'off'.

    Read live from the environment each call so the flag is tunable at runtime
    (tests / doctor / an operator override) without re-importing the module.
    """
    from forecasting import appconfig

    raw = (appconfig.get_str("FORECAST_GATE_DIRECT_WRITES", "on") or "").strip().lower()
    if raw in ("", "1", "true", "on", "enforce", "refuse"):
        return "on"
    if raw in ("warn", "warning", "audit", "log"):
        return "warn"
    if raw in ("0", "false", "off", "disable", "disabled"):
        return "off"
    # Unknown value -> fail safe to the strongest mode.
    return "on"


def forecast_commit_active() -> bool:
    """True iff a recognised forecast-commit context is currently open."""
    return bool(_FORECAST_COMMIT_ACTIVE.get())


def snapshot_writes_allowed() -> bool:
    """False inside an unattended proposal-only forecast pass."""
    return bool(_FORECAST_SNAPSHOT_WRITES_ALLOWED.get()) and (
        os.environ.get("FORECAST_COMMIT_POLICY", "").strip().lower()
        != "proposal_only"
    )


@contextlib.contextmanager
def forbid_snapshot_writes():
    """Make snapshot commits fail closed while still allowing proposals/evidence."""
    token = _FORECAST_SNAPSHOT_WRITES_ALLOWED.set(False)
    try:
        yield
    finally:
        _FORECAST_SNAPSHOT_WRITES_ALLOWED.reset(token)


@contextlib.contextmanager
def allow_ledger_writes(reason: str | None = None):
    """Open a recognised forecast-commit context.

    Forecast-producing writes (create_question / create_snapshot /
    record_panel_run) executed *inside* this block are permitted; outside it
    they are refused (or warned, per the gate mode). Re-entrant and
    task/thread-local. ``reason`` is advisory (surfaced in logs).
    """
    token = _FORECAST_COMMIT_ACTIVE.set(True)
    try:
        if reason:
            logger.debug("ledger writes allowed: %s", reason)
        yield
    finally:
        _FORECAST_COMMIT_ACTIVE.reset(token)


def allow_ledger_writes_decorator(reason: str | None = None):
    """Decorate a recognised legitimate writer so its body runs inside the gate.

    Sugar over :func:`allow_ledger_writes` for whole-function entry points (the
    forecast tool, cron jobs, CLI commands). Preserves the wrapped signature.
    """

    def _wrap(func):
        import functools

        @functools.wraps(func)
        def _inner(*args, **kwargs):
            with allow_ledger_writes(reason=reason or getattr(func, "__name__", None)):
                return func(*args, **kwargs)

        return _inner

    return _wrap


def _enforce_write_gate(method_name: str) -> None:
    """Refuse / warn on a forecast-producing write outside a commit context."""
    if _FORECAST_COMMIT_ACTIVE.get():
        return
    mode = ledger_write_gate_mode()
    if mode == "off":
        return
    message = (
        f"Direct ledger writes are gated ({method_name}). "
        "Use the forecast tool's commit flow. Scripts may READ the ledger "
        "(audits/migrations) but not write forecasts."
    )
    if mode == "warn":
        logger.warning("%s (warn-only mode)", message)
        return
    raise ForecastingError(message)
