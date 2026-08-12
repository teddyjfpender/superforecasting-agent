"""SQLite forecast ledger for the forecasting fork."""

from __future__ import annotations

import contextlib
import contextvars
import hashlib
import csv
import json
import logging
import math
import os
import random
import re
import shutil
import sqlite3
import statistics
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from hermes_constants import get_hermes_home

from forecasting.branding import (
    CORE_PRIMITIVE,
    FORK_CONTEXT_DOC,
    FORK_PRD_DOC,
    NORTH_STAR,
    PRODUCT_NAME,
    PRODUCT_SLUG,
)
from forecasting.benchmark_evidence import build_benchmark_evidence_profile
from forecasting.leak_domains import leak_reason
from forecasting.models import (
    ASSUMPTION_STATUSES,
    CALIBRATION_LESSON_STATUSES,
    EVIDENCE_CLAIM_TYPES,
    FAILURE_CLASSES,
    FORECAST_ORIGINS,
    QUESTION_STATUSES,
    REFERENCE_CLASS_STATUSES,
    RESOLUTION_STATUSES,
    AlertEvent,
    EvidenceItem,
    ForecastingError,
    ForecastQuestion,
    ForecastSnapshot,
    LedgerNotFoundError,
    OutcomeSpace,
    Resolution,
    ScoreRecord,
    ValidationError,
    evaluate_update_triggers,
    json_dumps,
    json_loads,
    lookup_model_pretraining_cutoff,
    normalize_update_triggers,
    parse_timestamp,
    question_decision_readiness_issues,
    recency_halflife_weight,
    timestamp_to_datetime,
    utc_now_iso,
)

# Watched-source domain lives in the sibling ``watches`` module (D1 carve).
# Import the module for the one-line delegates and pull the WATCH_* constants
# back so this module's non-watch call sites keep referencing them by name.
from forecasting.ledger import watches as _watches
from forecasting.ledger.watches import (
    WATCH_SOURCE_ROLES,
    WATCH_SOURCE_TYPES,
)

# Question domain lives in the sibling ``questions`` module (D2 carve).
from forecasting.ledger import questions as _questions

# Evidence + information-triage domain lives in the sibling ``evidence`` module
# (D3 carve).
from forecasting.ledger import evidence as _evidence
# Snapshot domain (create_snapshot + readers/serializers) lives in the
# sibling ``snapshots`` module (D4 carve).
from forecasting.ledger import snapshots as _snapshots
# Forecast-panel domain (panel runs + track-record weighting) lives in the
# sibling ``panels`` module (D5 carve).
from forecasting.ledger import panels as _panels
# Deviation-bet domain (UPGRADE 2 — the deviation ledger: the desk's named-edge
# bets against the market, scored Brier-ours-vs-market at resolution) lives in the
# sibling ``deviation_bets`` module.
from forecasting.ledger import deviation_bets as _deviation_bets
# Scheduled-review domain (cadence, schedules, the review sweep) lives in the
# sibling ``reviews`` module (D6 carve).
from forecasting.ledger import reviews as _reviews
# Alerts domain (the doctor self_check engine + alert_events CRUD/lifecycle +
# the saturation/producer/reconcile glue) lives in the sibling ``alerts`` module
# (D7 carve).
from forecasting.ledger import alerts as _alerts
# Theses domain (thesis/factor member+entity CRUD, correlation/event glue, the
# aggregation engine + narratives, and the re-aggregate cascade) lives in the
# sibling ``theses`` module (D8 carve).
from forecasting.ledger import theses as _theses
# Scoring domain (resolution scoring, Brier/calibration display, the paired-
# bootstrap edge test, and lesson-application auditing) lives in the sibling
# ``scoring`` module (D9 carve).
from forecasting.ledger import scoring as _scoring
# Outside-view anchor re-linking (the mechanical orphaned-anchor remediation).
from forecasting.ledger import anchors as _anchors
from forecasting.ledger import exports as _exports
from forecasting.ledger import autopilot as _autopilot
from forecasting.ledger import refresh as _refresh
from forecasting.ledger import source_signatures as _source_signatures
from forecasting.ledger import question_meta as _question_meta
from forecasting.ledger import market_models as _market_models
from forecasting.ledger import backtest as _backtest
from forecasting.ledger import model_scoring as _model_scoring
from forecasting.ledger import lessons as _lessons
from forecasting.ledger import resolutions as _resolutions


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Direct-write gate (carved to the ``gate`` leaf).
#
# The write-gate machinery — the commit-active contextvar, the
# ``allow_ledger_writes`` context + decorator, the connection-level SQLite
# authorizer, the gated-table set, and ``_enforce_write_gate`` — is the ONE
# cross-domain dependency every gated write domain shares (create_question in
# ``questions``, create_snapshot in ``snapshots``, record_panel_run in
# ``panels``). It lives in :mod:`forecasting.ledger.gate` (a leaf importing only
# stdlib + ``forecasting.models``). Import the names BACK here so this module's
# call sites keep referencing them by bare name and ``from .core import *`` re-
# exports the pre-carve public surface (``forecasting.ledger.allow_ledger_writes``
# and friends) byte-for-byte.
from forecasting.ledger.gate import (  # noqa: F401  (re-export, surface parity)
    _FORECAST_COMMIT_ACTIVE,
    _enforce_write_gate,
    _ledger_write_authorizer,
    allow_ledger_writes,
    allow_ledger_writes_decorator,
    forecast_commit_active,
    ledger_write_gate_mode,
    GATED_LEDGER_TABLES,
    GATED_LEDGER_WRITES,
)


FORECASTING_PROTOCOL_VERSION = "forecasting-ledger-v1"

# Reference anchor: an uninformative p=0.5-everywhere forecaster scores Brier 0.25.
# Surfaced next to mean Brier so a reader can place the score on the legible scale.
BRIER_COIN_FLIP_FLOOR = 0.25

# AIA P1.2 — content-aware foreknowledge judge + robustness bounds.
#
# The cheap DATE pre-filter remains the FIRST leakage channel. The judge is a
# SECOND, content-aware channel that reads the cited evidence text + rationale.
# It is OPT-IN: with the channel OFF (the default), a backtest is byte-identical
# to before — no judge call, no verdict rows, no new status.
#
# WORST_CASE_FLAG_THRESHOLD: a QUESTION is forced to the uninformative p=0.5
# (Brier 0.25) in the worst-case rescore only once it accumulates at least this
# many content flags across its cases. A single high-recall flag is too noisy to
# nuke a question; >=2 corroborating flags is the conservative bar.
WORST_CASE_FLAG_THRESHOLD = 2
# The worst-case rescore is "non-material" (the headline survives leakage) iff its
# mean Brier stays within this RELATIVE fraction of the baseline mean Brier. This
# replaces the old binary leakage kill-switch with a graded, defensible verdict.
LEAK_ROBUSTNESS_REL_TOLERANCE = 0.006

# A leak-judge runner takes the (already-built) judge prompt + the case dict and
# returns the raw model response (str or dict) for tolerant parsing. Supplying one
# is what OPTS the second channel IN; leaving it None keeps backtests unchanged.
LeakJudgeRunner = Callable[[str, dict[str, Any]], Any]



# Analyst write-ups ("desk notes"): time-series-indexed prose the model writes
# about each forecast. `brief` is written on every probability-bearing commit
# (and on evidence-only thinking updates); `retrospective` is the terminal note
# written once the question resolves.
ANALYST_NOTE_KINDS = {"brief", "retrospective"}
ANALYST_NOTE_STANCES = {"lean_yes", "lean_no", "toss_up"}
ANALYST_NOTE_VERDICTS = {"right", "wrong", "close", "far"}

# Cross-pollination links between forecasts. `related` is a symmetric correlation
# edge (sibling <-> sibling); `component_of` is directed (from=child, to=parent)
# so a higher-level question and its granular children inform each other.
FORECAST_LINK_TYPES = {"related", "component_of"}



# Per-forecast CRUX variables: the decisive inputs the resolution actually hinges
# on. Tracking them (+ their evidence status) stops "lots of evidence but wrong
# evidence" — the desk focuses gathering on what moves the answer.
CRUX_MATERIALITY = {"low", "medium", "high"}
CRUX_STATUS = {"missing", "stale", "current", "contradictory"}

# Longest crux sentence promoted verbatim into a crux_variable — a panelist crux is
# "one sentence naming the single biggest uncertainty", so a generous but finite cap.
_MAX_CRUX_VARIABLE_LEN = 240


def _crux_text_hash(text: str) -> str:
    """Stable dedupe key for a free-text crux: casefold, strip surrounding
    punctuation/whitespace, collapse internal whitespace, then SHA-256.

    Two panelists phrasing the SAME uncertainty with different casing / trailing
    punctuation collapse to one promoted crux (finding #4: dedupe by text-hash)."""

    norm = re.sub(r"\s+", " ", str(text or "").strip().casefold())
    norm = norm.strip(" \t\r\n.,;:!?-—\"'`()[]")
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

AUTOPILOT_MODES = {"propose", "auto_commit", "alert_only"}
AUTOPILOT_PROPOSAL_STATUSES = {
    "pending",
    "committing",
    "approved",
    "rejected",
    "superseded",
    "expired",
    "auto_committed",
}


class _IngestHTMLParser(HTMLParser):
    """Small metadata/text extractor for generic forecast URL ingest."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta: dict[str, str] = {}
        self.text_lines: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if tag != "meta":
            return
        attr_map = {name.lower(): value or "" for name, value in attrs}
        key = (attr_map.get("name") or attr_map.get("property") or "").strip().lower()
        content = attr_map.get("content", "").strip()
        if key and content:
            self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        if len(self.text_lines) < 40:
            self.text_lines.append(text)


def _export_metadata() -> dict[str, Any]:
    return {
        "product_name": PRODUCT_NAME,
        "product_slug": PRODUCT_SLUG,
        "core_primitive": CORE_PRIMITIVE,
        "north_star": NORTH_STAR,
        "context_doc": FORK_CONTEXT_DOC,
        "prd_doc": FORK_PRD_DOC,
    }


_PACKET_PRIMARY_KEYS = {
    "forecast_snapshots": "forecast_id",
}
_PACKET_JSON_FIELDS = {
    "forecast_questions": {"outcome_space", "tags", "topics", "metadata", "update_triggers"},
    "forecast_snapshots": {
        "probability_or_distribution",
        "ensemble_components",
        "key_assumptions",
        "assumption_refs",
        "reference_class_refs",
        "evidence_refs",
        "model_run_refs",
        "source_snapshot_refs",
        "calibration_lesson_refs",
        "calibration_adjustment",
        "metadata",
        "reasons_up",
        "reasons_down",
        "change_my_mind",
    },
    "evidence_items": {"metadata"},
    "ingest_candidates": {"outcome_space", "metadata"},
    "assumptions": {"evidence_refs"},
    "reference_classes": {"source_refs"},
    "model_runs": {"inputs", "parameters", "output", "diagnostics", "artifact_paths"},
    "resolutions": {"outcome"},
    "postmortems": {"calibration_adjustment"},
    "calibration_lessons": {
        "recommended_adjustment",
        "source_postmortem_refs",
        "source_score_record_refs",
        "metadata",
    },
    "forecast_corrections": {
        "old_value",
        "new_value",
        "patch",
        "affected_score_record_refs",
        "affected_postmortem_refs",
        "affected_calibration_lesson_refs",
    },
    "domain_error_profiles": {
        "calibration_summary",
        "recurring_errors",
        "recommended_adjustments",
    },
    "panel_runs": {
        "perspectives",
        "spread_summary",
        "notes",
        "judge",
        "supervisor_evidence",
    },
    "panel_estimates": {
        "reasons_up",
        "reasons_down",
        "change_my_mind",
        "metadata",
    },
    "analyst_notes": {"metadata"},
    "forecast_links": {"metadata"},
    "thesis_members": {"metadata"},
    "thesis_entities": {"weights", "metadata"},
    "baseline_comparisons": {"probability_or_distribution", "metadata"},
    "source_snapshots": {"parsed_values", "metadata"},
    "watched_sources": {"metadata"},
    "scheduled_review_runs": {"metadata"},
    "autopilot_policies": {"materiality_policy", "guardrail_policy", "notification_policy"},
    "autopilot_runs": {"diagnostics"},
    "forecast_update_proposals": {
        "proposed_probability_or_distribution",
        "evidence_refs",
        "source_snapshot_refs",
        "model_run_refs",
        "assumption_refs",
        "reference_class_refs",
        "snapshot_args",
    },
}
_PACKET_BOOL_FIELDS = {
    "evidence_items": {"admissible_for_backtests"},
    "resolutions": {"criteria_satisfied", "scoreable"},
    "score_records": {"calibration_eligible"},
    "postmortems": {"calibration_eligible"},
    "scheduled_reviews": {"enabled", "auto_score", "auto_postmortem"},
    "autopilot_policies": {"enabled"},
    "thesis_members": {"hi_is_good"},
}
_PACKET_RECORD_LABELS = {
    "forecast_questions": "questions",
    "forecast_snapshots": "forecast_history",
    "evidence_items": "evidence",
    "ingest_candidates": "ingest_candidates",
    "assumptions": "assumptions",
    "reference_classes": "reference_classes",
    "model_runs": "model_runs",
    "resolutions": "resolutions",
    "score_records": "scores",
    "postmortems": "postmortems",
    "calibration_lessons": "calibration_lessons",
    "forecast_corrections": "corrections",
    "domain_error_profiles": "domain_error_profiles",
    "analyst_notes": "analyst_notes",
    "forecast_links": "forecast_links",
    "thesis_members": "thesis_members",
    "thesis_entities": "thesis_entities",
    "baseline_comparisons": "baseline_comparisons",
    "source_snapshots": "source_snapshots",
    "watched_sources": "watched_sources",
    "scheduled_reviews": "scheduled_reviews",
    "scheduled_review_runs": "scheduled_review_runs",
    "alert_events": "alerts",
    "autopilot_policies": "autopilot_policies",
    "autopilot_runs": "autopilot_runs",
    "forecast_update_proposals": "forecast_update_proposals",
}


def _coerce_distribution_number(raw: Any) -> float | None:
    """Coerce a distribution value to a float, tolerating the numbers models
    commonly quote ("50,000", "$71500", "4.2%"). Returns None for booleans and
    anything not coercible so the caller can reject it with a named error."""

    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        cleaned = raw.strip().replace(",", "").replace("$", "").replace("%", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


class ForecastLedger:
    """Local-first SQLite ledger for questions, evidence, forecasts, and scores."""

    # Resolve-time bias-synthesis debounce window (seconds). A burst of live
    # resolutions in the same process re-synthesises a scope at most once per
    # window; the cron path (run_due_reviews) is the periodic catch-up, so nothing
    # is lost — only the redundant O(live-scores) rescans in a tight loop are cut.
    _BIAS_SYNTH_DEBOUNCE_SECONDS = 30.0

    def __init__(self, db_path: str | Path | None = None) -> None:
        from forecasting import appconfig

        configured_db = (appconfig.get_str("FORECAST_LEDGER_DB", "") or "").strip()
        self.db_path = (
            Path(db_path).expanduser()
            if db_path
            else Path(configured_db).expanduser()
            if configured_db
            else get_hermes_home() / "forecasting" / "forecasting.db"
        )
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ForecastingError(
                "could not create forecast ledger directory "
                f"{self.db_path.parent}: {exc}. Set FORECAST_LEDGER_DB or "
                "pass --db with a writable path."
            ) from exc
        # Per-scope wall-clock debounce for the resolve-time bias synthesis (S7):
        # scope -> monotonic timestamp of the last auto-synthesis in THIS process.
        # A burst of resolutions (a bulk close, a backfill loop) fires at most one
        # synthesis per scope per window; human-paced resolutions each fire.
        self._bias_synth_last: dict[str, float] = {}
        # A changeset apply may call several existing ledger methods.  Those
        # methods all use ``with ledger._connect()`` independently, so keep a
        # task/thread-local borrowed connection while an outer transaction is
        # active.  The small wrapper below prevents inner context managers from
        # committing or closing the outer transaction.
        self._transaction_connection: contextvars.ContextVar[sqlite3.Connection | None] = (
            contextvars.ContextVar(
                f"forecast_ledger_transaction_{id(self)}",
                default=None,
            )
        )
        try:
            self.initialize_schema()
        except sqlite3.Error as exc:
            raise ForecastingError(
                "could not initialize forecast ledger "
                f"{self.db_path}: {exc}. Set FORECAST_LEDGER_DB or "
                "pass --db with a writable path."
            ) from exc

    class _BorrowedConnection:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def __enter__(self) -> sqlite3.Connection:
            return self._connection

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return False

        def __getattr__(self, name: str) -> Any:
            return getattr(self._connection, name)

    class _OwnedConnection(_BorrowedConnection):
        def __exit__(self, exc_type, exc, traceback) -> bool:
            try:
                return self._connection.__exit__(exc_type, exc, traceback)
            finally:
                self._connection.close()

    def _new_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Write-Ahead Logging lets a reader run concurrently with an in-flight
        # writer (DELETE-mode journaling would block it), which is what the TUI
        # gateway + cron reforecasts actually do. journal_mode=WAL persists at the
        # DB-file level (a one-time flip); synchronous=NORMAL is the safe/fast
        # pairing under WAL. On :memory: WAL is a silent no-op, and on a read-only
        # filesystem the PRAGMA can raise — degrade quietly rather than break
        # connectivity (the DB still works in its prior journal mode).
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        except Exception:  # pragma: no cover - read-only FS / stripped build
            logger.debug("could not set WAL journal mode", exc_info=True)
        # Connection-level write gate. This is the REAL chokepoint: the
        # method-level _enforce_write_gate only sees create_question /
        # create_snapshot / record_panel_run, but a script can grab THIS raw
        # connection and run an INSERT directly. The authorizer checks the live
        # commit-context contextvar at query time, so a raw forecast-producing
        # write outside a recognised commit context is denied — even when the
        # script is run by the agent via the terminal tool. Reads + DDL +
        # transactions are always allowed (so initialize_schema / migrations,
        # which run in __init__ outside any allow-context, keep working), and the
        # whole thing is inert under warn/off mode. The set_authorizer call is
        # cheap and defensive: if a stripped-down sqlite build lacked it, fall
        # back to the method-level gate rather than break ledger connectivity.
        try:
            conn.set_authorizer(_ledger_write_authorizer)
        except Exception:  # pragma: no cover - defensive only
            logger.debug("could not install ledger write authorizer", exc_info=True)
        return conn

    def _connect(self) -> sqlite3.Connection:
        active = self._transaction_connection.get()
        if active is not None:
            return self._BorrowedConnection(active)  # type: ignore[return-value]
        return self._OwnedConnection(self._new_connection())  # type: ignore[return-value]

    @contextlib.contextmanager
    def transaction(self, *, immediate: bool = False):
        """Run public ledger methods in one atomic SQLite transaction.

        Nested calls reuse the outer transaction. ``BEGIN IMMEDIATE`` is used
        by changeset promotion to obtain SQLite's cross-process writer lock
        before checking the base revision.
        """

        active = self._transaction_connection.get()
        if active is not None:
            yield active
            return
        conn = self._new_connection()
        token = self._transaction_connection.set(conn)
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._transaction_connection.reset(token)
            conn.close()

    # ── durability: online backup + integrity (the ledger IS the asset) ─────────
    #
    # The forecast ledger is months of irreplaceable judgment. These methods give
    # it a backup + integrity spine with ZERO risk to the live file: backups use
    # SQLite's ONLINE backup API (``sqlite3.Connection.backup``) — a page-level
    # copy that is safe under concurrent readers/writers — NEVER an OS file-copy of
    # a live WAL database (which can capture a torn, unrecoverable image).

    # Retention (deterministic, applied after each backup): always keep the newest
    # ``BACKUP_KEEP_RECENT`` snapshots, PLUS the newest snapshot in each of the most
    # recent ``BACKUP_WEEKLY_WEEKS`` ISO weeks (one-per-week long tail). Everything
    # else is pruned.
    BACKUP_KEEP_RECENT = 14
    BACKUP_WEEKLY_WEEKS = 8
    _BACKUP_PREFIX = "forecast-"
    _BACKUP_SUFFIX = ".db"
    _BACKUP_TS_FORMAT = "%Y%m%d-%H%M%S"  # forecast-YYYYMMDD-HHMMSS.db
    _BACKUP_TS_LEN = 15  # len("YYYYMMDD-HHMMSS")

    # A small, meaningful row-count snapshot (friendly name -> table). A count that
    # holds across a backup+restore is the cheapest end-to-end integrity signal.
    _BACKUP_COUNT_TABLES = (
        ("questions", "forecast_questions"),
        ("snapshots", "forecast_snapshots"),
        ("evidence", "evidence_items"),
        ("resolutions", "resolutions"),
        ("scores", "score_records"),
        ("panel_runs", "panel_runs"),
        ("alerts", "alert_events"),
        ("watched_sources", "watched_sources"),
    )

    def default_backup_dir(self) -> Path:
        """Where backups land when no ``dest_dir`` is given: ``<ledger dir>/backups``.

        Co-located with the ledger file (rather than a fixed ``{home}/backups``) so a
        custom ``--db`` / ``FORECAST_LEDGER_DB`` ledger keeps its backups beside it —
        and a scratch/test ledger never writes anywhere near the operator's live
        home."""

        return self.db_path.parent / "backups"

    def row_counts(self) -> dict[str, int]:
        """A best-effort ``{questions, snapshots, evidence, …}`` row-count snapshot.

        Fail-soft per table: a table absent on an older schema is skipped, never
        fatal — this is a sanity signal, not a schema assertion."""

        counts: dict[str, int] = {}
        with self._connect() as conn:
            for friendly, table in self._BACKUP_COUNT_TABLES:
                try:
                    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                except sqlite3.Error:
                    continue
                counts[friendly] = int(row[0]) if row else 0
        return counts

    def integrity_check(self) -> dict[str, Any]:
        """Run ``PRAGMA integrity_check`` + ``PRAGMA quick_check`` plus a row-count
        snapshot, returned as a dict.

        ``ok`` is True only when BOTH pragmas report the single ``ok`` row and the
        connection did not raise. A severely corrupt database can make the PRAGMA
        itself raise ``sqlite3.DatabaseError`` — that is caught and reported as a
        violation (``ok=False``) rather than propagated, so this method is always a
        safe read."""

        checked_at = utc_now_iso()
        integrity: list[str] = []
        quick: list[str] = []
        error: str | None = None
        try:
            with self._connect() as conn:
                integrity = [str(r[0]) for r in conn.execute("PRAGMA integrity_check").fetchall()]
                quick = [str(r[0]) for r in conn.execute("PRAGMA quick_check").fetchall()]
        except sqlite3.DatabaseError as exc:
            error = f"{type(exc).__name__}: {exc}"
        try:
            counts = self.row_counts()
        except sqlite3.DatabaseError:
            counts = {}

        violations: list[str] = []
        if error:
            violations.append(error)
        violations.extend(v for v in integrity if v != "ok")
        violations.extend(v for v in quick if v != "ok")
        ok = not violations and integrity == ["ok"] and quick == ["ok"]
        return {
            "ok": ok,
            "integrity_check": integrity,
            "quick_check": quick,
            "violations": violations,
            "counts": counts,
            "checked_at": checked_at,
            "db_path": str(self.db_path),
        }

    def backup(
        self,
        dest_dir: str | Path | None = None,
        *,
        retention: bool = True,
        keep_recent: int | None = None,
        weekly_weeks: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Take an ONLINE backup of the ledger and prune old snapshots.

        Uses ``sqlite3.Connection.backup`` (page-level, concurrency-safe) to copy the
        live database into ``<dest_dir>/forecast-YYYYMMDD-HHMMSS.db`` (``dest_dir``
        defaults to :meth:`default_backup_dir`). Returns ``{path, bytes, created_at,
        retention}``. Retention (unless ``retention=False``) keeps the newest
        ``keep_recent`` (default :data:`BACKUP_KEEP_RECENT`) plus one-per-week for
        ``weekly_weeks`` (default :data:`BACKUP_WEEKLY_WEEKS`) ISO weeks."""

        moment = now or datetime.now(timezone.utc)
        target_dir = Path(dest_dir).expanduser() if dest_dir else self.default_backup_dir()
        target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if dest_dir is None:
            target_dir.chmod(0o700)
            for existing in target_dir.glob(
                f"{self._BACKUP_PREFIX}*{self._BACKUP_SUFFIX}"
            ):
                if existing.is_file() and not existing.is_symlink():
                    existing.chmod(0o600)

        stamp = moment.strftime(self._BACKUP_TS_FORMAT)
        dest = target_dir / f"{self._BACKUP_PREFIX}{stamp}{self._BACKUP_SUFFIX}"
        # Collision guard: two backups in the same wall-clock second get a numeric
        # suffix so neither is clobbered. The timestamp parser reads only the leading
        # 15 chars, so a suffixed file still buckets into the right second/week.
        counter = 1
        while True:
            try:
                fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                dest = target_dir / (
                    f"{self._BACKUP_PREFIX}{stamp}-{counter}{self._BACKUP_SUFFIX}"
                )
                counter += 1
                continue
            os.close(fd)
            break

        # A plain connection reads the fully-committed logical state (WAL frames
        # included). The online backup restarts internally if a writer commits
        # mid-copy, so it is safe to run against the live ledger.
        try:
            src = sqlite3.connect(self.db_path)
            try:
                dst = sqlite3.connect(dest)
                try:
                    with dst:
                        src.backup(dst)
                finally:
                    dst.close()
            finally:
                src.close()
        except BaseException:
            dest.unlink(missing_ok=True)
            raise

        result: dict[str, Any] = {
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "created_at": moment.astimezone(timezone.utc).isoformat(),
        }
        if retention:
            result["retention"] = self._prune_backups(
                target_dir,
                keep_recent=self.BACKUP_KEEP_RECENT if keep_recent is None else int(keep_recent),
                weekly_weeks=self.BACKUP_WEEKLY_WEEKS if weekly_weeks is None else int(weekly_weeks),
            )
        return result

    def _parse_backup_ts(self, path: Path) -> datetime | None:
        """The UTC timestamp encoded in a backup filename, or None if it does not
        match the ``forecast-YYYYMMDD-HHMMSS[.…].db`` shape."""

        name = path.name
        if not name.startswith(self._BACKUP_PREFIX) or not name.endswith(self._BACKUP_SUFFIX):
            return None
        core = name[len(self._BACKUP_PREFIX) : -len(self._BACKUP_SUFFIX)]
        try:
            return datetime.strptime(core[: self._BACKUP_TS_LEN], self._BACKUP_TS_FORMAT).replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            return None

    def list_backups(self, dest_dir: str | Path | None = None) -> list[dict[str, Any]]:
        """Existing backups as ``[{path, created_at, bytes}]``, newest first."""

        target_dir = Path(dest_dir).expanduser() if dest_dir else self.default_backup_dir()
        rows: list[dict[str, Any]] = []
        if not target_dir.is_dir():
            return rows
        for path in target_dir.glob(f"{self._BACKUP_PREFIX}*{self._BACKUP_SUFFIX}"):
            ts = self._parse_backup_ts(path)
            if ts is None:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            rows.append(
                {"path": str(path), "created_at": ts.isoformat(), "bytes": size, "_ts": ts, "_name": path.name}
            )
        rows.sort(key=lambda r: (r["_ts"], r["_name"]), reverse=True)
        for r in rows:
            r.pop("_ts", None)
            r.pop("_name", None)
        return rows

    def latest_backup(
        self, dest_dir: str | Path | None = None, *, now: datetime | None = None
    ) -> dict[str, Any] | None:
        """The most recent backup with its ``age_hours`` (and total ``count``), or
        None when no backup exists yet — the seam the doctor's WARN reads."""

        rows = self.list_backups(dest_dir)
        if not rows:
            return None
        latest = dict(rows[0])
        moment = now or datetime.now(timezone.utc)
        age_hours: float | None
        try:
            created = datetime.fromisoformat(latest["created_at"])
            age_hours = (moment - created).total_seconds() / 3600.0
        except (ValueError, TypeError):
            age_hours = None
        latest["age_hours"] = age_hours
        latest["count"] = len(rows)
        return latest

    def _prune_backups(
        self, dest_dir: str | Path, *, keep_recent: int, weekly_weeks: int
    ) -> dict[str, Any]:
        """Delete backups outside the retention window, deterministically.

        Keep set = the newest ``keep_recent`` snapshots ∪ the newest snapshot in each
        of the most recent ``weekly_weeks`` ISO weeks. Given a fixed set of files this
        always produces the same keep/prune partition (ordering ties broken by
        filename)."""

        target_dir = Path(dest_dir)
        entries: list[tuple[datetime, Path]] = []
        for path in target_dir.glob(f"{self._BACKUP_PREFIX}*{self._BACKUP_SUFFIX}"):
            ts = self._parse_backup_ts(path)
            if ts is not None:
                entries.append((ts, path))
        # Newest first; filename breaks ties so the partition is fully deterministic.
        entries.sort(key=lambda e: (e[0], e[1].name), reverse=True)

        keep: set[Path] = set()
        for _ts, path in entries[: max(0, keep_recent)]:
            keep.add(path)
        by_week: dict[tuple[int, int], Path] = {}
        for ts, path in entries:  # descending → first seen per week is the newest
            iso = ts.isocalendar()
            key = (iso[0], iso[1])
            by_week.setdefault(key, path)
        for key in sorted(by_week, reverse=True)[: max(0, weekly_weeks)]:
            keep.add(by_week[key])

        pruned: list[str] = []
        for _ts, path in entries:
            if path in keep:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            pruned.append(str(path))
        return {
            "kept": len(entries) - len(pruned),
            "pruned": pruned,
            "pruned_count": len(pruned),
        }

    def initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS forecast_questions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    resolution_criteria TEXT NOT NULL,
                    resolution_source TEXT,
                    created_at TEXT NOT NULL,
                    close_time TEXT,
                    resolution_time TEXT,
                    outcome_space TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    tags TEXT NOT NULL DEFAULT '[]',
                    domain TEXT,
                    topics TEXT NOT NULL DEFAULT '[]',
                    owner TEXT,
                    impact TEXT,
                    review_cadence TEXT,
                    next_review_at TEXT,
                    current_forecast_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS forecast_snapshots (
                    forecast_id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    probability_or_distribution TEXT NOT NULL,
                    confidence REAL,
                    forecast_horizon_days REAL,
                    method TEXT,
                    ensemble_components TEXT NOT NULL DEFAULT '{}',
                    rationale TEXT NOT NULL DEFAULT '',
                    key_assumptions TEXT NOT NULL DEFAULT '[]',
                    assumption_refs TEXT NOT NULL DEFAULT '[]',
                    reference_class_refs TEXT NOT NULL DEFAULT '[]',
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    model_run_refs TEXT NOT NULL DEFAULT '[]',
                    parent_forecast_id TEXT,
                    forecast_origin TEXT NOT NULL DEFAULT 'live',
                    agent_model TEXT,
                    prompt_version TEXT,
                    forecasting_protocol_version TEXT,
                    toolset_version TEXT,
                    source_snapshot_refs TEXT NOT NULL DEFAULT '[]',
                    evidence_cutoff TEXT,
                    backtest_run_id TEXT,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    calibration_weight REAL NOT NULL DEFAULT 1.0,
                    calibration_lesson_refs TEXT NOT NULL DEFAULT '[]',
                    calibration_adjustment TEXT NOT NULL DEFAULT '{}',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_question
                    ON forecast_snapshots(question_id, created_at);

                CREATE TABLE IF NOT EXISTS evidence_items (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    captured_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    source_url TEXT,
                    source_name TEXT,
                    source_type TEXT NOT NULL,
                    published_at TEXT,
                    claim TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    reliability_rating REAL,
                    relevance_rating REAL,
                    stance TEXT NOT NULL DEFAULT 'context',
                    claim_type TEXT NOT NULL DEFAULT 'fact',
                    snapshot_path TEXT,
                    admissible_for_backtests INTEGER NOT NULL DEFAULT 1,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_evidence_question_available
                    ON evidence_items(question_id, available_at);

                CREATE TABLE IF NOT EXISTS ingest_candidates (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    candidate_title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    resolution_criteria TEXT NOT NULL DEFAULT '',
                    resolution_source TEXT,
                    close_time TEXT,
                    resolution_time TEXT,
                    outcome_space TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    confirmed_question_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS assumptions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    invalidated_at TEXT,
                    check_cadence TEXT,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS reference_classes (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    inclusion_criteria TEXT NOT NULL DEFAULT '',
                    exclusion_criteria TEXT NOT NULL DEFAULT '',
                    base_rate REAL,
                    base_rate_uncertainty REAL,
                    source_refs TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    invalidated_at TEXT,
                    check_cadence TEXT,
                    notes TEXT,
                    sample_size INTEGER
                );

                CREATE TABLE IF NOT EXISTS question_cruxes (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    crux_variable TEXT NOT NULL,
                    preferred_roles TEXT NOT NULL DEFAULT '[]',
                    materiality TEXT NOT NULL DEFAULT 'medium',
                    status TEXT NOT NULL DEFAULT 'missing',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_question_cruxes_question
                    ON question_cruxes(question_id, materiality, status);

                CREATE TABLE IF NOT EXISTS model_runs (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    model_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'success',
                    inputs TEXT NOT NULL DEFAULT '{}',
                    parameters TEXT NOT NULL DEFAULT '{}',
                    output TEXT NOT NULL DEFAULT '{}',
                    diagnostics TEXT NOT NULL DEFAULT '{}',
                    code_ref TEXT,
                    artifact_paths TEXT NOT NULL DEFAULT '[]',
                    model_version TEXT,
                    prompt_version TEXT,
                    data_version TEXT,
                    evidence_cutoff TEXT
                );

                CREATE TABLE IF NOT EXISTS resolutions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    resolved_at TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    resolution_source TEXT,
                    resolution_source_snapshot_ref TEXT,
                    resolver_type TEXT NOT NULL DEFAULT 'manual',
                    resolution_status TEXT NOT NULL DEFAULT 'confirmed',
                    criteria_satisfied INTEGER NOT NULL DEFAULT 1,
                    confidence REAL,
                    confirmed_at TEXT,
                    confirmed_by TEXT,
                    resolver_notes TEXT,
                    disputed_at TEXT,
                    correction_ref TEXT,
                    scoreable INTEGER NOT NULL DEFAULT 1,
                    trusted_policy_id TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_resolutions_question_status
                    ON resolutions(question_id, resolution_status, resolved_at);

                CREATE TABLE IF NOT EXISTS score_records (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT NOT NULL REFERENCES forecast_snapshots(forecast_id) ON DELETE CASCADE,
                    resolution_id TEXT NOT NULL REFERENCES resolutions(id) ON DELETE CASCADE,
                    scored_at TEXT NOT NULL,
                    brier_score REAL,
                    log_score REAL,
                    proper_score REAL,
                    score_rule TEXT,
                    calibration_bucket TEXT,
                    forecast_horizon_days REAL,
                    domain TEXT,
                    forecast_origin TEXT NOT NULL,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    calibration_weight REAL NOT NULL DEFAULT 1.0,
                    baseline_ref TEXT,
                    invalidated_by_correction_id TEXT,
                    notes TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_score_records_domain_bucket
                    ON score_records(domain, calibration_bucket, forecast_origin);

                CREATE TABLE IF NOT EXISTS postmortems (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT NOT NULL REFERENCES forecast_snapshots(forecast_id) ON DELETE CASCADE,
                    resolution_id TEXT NOT NULL REFERENCES resolutions(id) ON DELETE CASCADE,
                    score_record_id TEXT NOT NULL REFERENCES score_records(id) ON DELETE CASCADE,
                    forecast_origin TEXT NOT NULL,
                    calibration_eligible INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    what_happened TEXT NOT NULL DEFAULT '',
                    what_was_expected TEXT NOT NULL DEFAULT '',
                    missed_evidence TEXT NOT NULL DEFAULT '',
                    overweighted_evidence TEXT NOT NULL DEFAULT '',
                    base_rate_error TEXT NOT NULL DEFAULT '',
                    inside_view_error TEXT NOT NULL DEFAULT '',
                    resolution_error TEXT NOT NULL DEFAULT '',
                    lesson TEXT NOT NULL DEFAULT '',
                    calibration_adjustment TEXT NOT NULL DEFAULT '{}',
                    invalidated_by_correction_id TEXT
                );

                CREATE TABLE IF NOT EXISTS calibration_lessons (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'tentative',
                    confidence REAL,
                    lesson TEXT NOT NULL,
                    recommended_adjustment TEXT NOT NULL DEFAULT '{}',
                    source_postmortem_refs TEXT NOT NULL DEFAULT '[]',
                    source_score_record_refs TEXT NOT NULL DEFAULT '[]',
                    supersedes_lesson_id TEXT,
                    invalidated_by_correction_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                -- Coverage ledger: one row each time an active lesson was IN SCOPE at a
                -- successful commit. Lets `forecast lessons audit` answer "is this
                -- learning actually being used?" — a lesson with zero rows since its
                -- creation is DORMANT (never even encountered), not silently trusted.
                CREATE TABLE IF NOT EXISTS lesson_applications (
                    id TEXT PRIMARY KEY,
                    lesson_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    snapshot_id TEXT,
                    kind TEXT NOT NULL DEFAULT 'advisory',
                    applied INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_lesson_applications_lesson
                    ON lesson_applications(lesson_id, created_at);

                CREATE TABLE IF NOT EXISTS forecast_corrections (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    reason TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    patch TEXT,
                    affected_score_record_refs TEXT NOT NULL DEFAULT '[]',
                    affected_postmortem_refs TEXT NOT NULL DEFAULT '[]',
                    affected_calibration_lesson_refs TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'proposed'
                );

                CREATE TABLE IF NOT EXISTS trusted_resolver_policies (
                    id TEXT PRIMARY KEY,
                    resolver_plugin TEXT NOT NULL,
                    plugin_version TEXT,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    approved_by TEXT,
                    last_used_at TEXT,
                    audit_log_ref TEXT
                );

                CREATE TABLE IF NOT EXISTS baseline_comparisons (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    backtest_case_id TEXT,
                    source TEXT NOT NULL,
                    baseline_type TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    probability_or_distribution TEXT NOT NULL,
                    score_record_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS backtest_runs (
                    id TEXT PRIMARY KEY,
                    dataset TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    default_forecast_time_cutoff TEXT,
                    evidence_cutoff_policy TEXT NOT NULL,
                    question_filter TEXT NOT NULL DEFAULT '{}',
                    model_profile TEXT NOT NULL DEFAULT '{}',
                    calibration_policy TEXT NOT NULL DEFAULT '{}',
                    result_summary TEXT NOT NULL DEFAULT '{}',
                    artifact_paths TEXT NOT NULL DEFAULT '[]',
                    leakage_checks_passed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS benchmark_datasets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    case_count INTEGER NOT NULL,
                    description TEXT,
                    cases TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS backtest_cases (
                    id TEXT PRIMARY KEY,
                    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
                    question_id TEXT REFERENCES forecast_questions(id) ON DELETE SET NULL,
                    simulated_forecast_time TEXT NOT NULL,
                    evidence_cutoff TEXT NOT NULL,
                    generated_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    baseline_comparison_refs TEXT NOT NULL DEFAULT '[]',
                    score_record_id TEXT,
                    leakage_check_status TEXT NOT NULL DEFAULT 'pending',
                    excluded_evidence_count INTEGER NOT NULL DEFAULT 0,
                    ambiguous_evidence_count INTEGER NOT NULL DEFAULT 0,
                    leakage_verdicts TEXT NOT NULL DEFAULT '{}',
                    content_flag_count INTEGER NOT NULL DEFAULT 0,
                    notes TEXT
                );

                CREATE TABLE IF NOT EXISTS scheduled_reviews (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    cadence TEXT NOT NULL,
                    stale_days INTEGER NOT NULL DEFAULT 7,
                    confidence_below REAL,
                    confidence_above REAL,
                    large_delta_threshold REAL,
                    next_run_at TEXT NOT NULL,
                    last_run_at TEXT,
                    trigger_reason TEXT NOT NULL DEFAULT 'scheduled',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    auto_score INTEGER NOT NULL DEFAULT 0,
                    auto_postmortem INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    unchanged_streak INTEGER NOT NULL DEFAULT 0,
                    adaptive_multiplier INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS scheduled_review_runs (
                    id TEXT PRIMARY KEY,
                    scheduled_review_id TEXT NOT NULL REFERENCES scheduled_reviews(id) ON DELETE CASCADE,
                    run_at TEXT NOT NULL,
                    next_run_at TEXT NOT NULL,
                    alert_count INTEGER NOT NULL DEFAULT 0,
                    score_count INTEGER NOT NULL DEFAULT 0,
                    postmortem_count INTEGER NOT NULL DEFAULT 0,
                    learning_review_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'completed',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_scheduled_review_runs_review
                    ON scheduled_review_runs(scheduled_review_id, run_at DESC);

                CREATE TABLE IF NOT EXISTS watched_sources (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_checked_at TEXT,
                    last_seen_signature TEXT,
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_watched_sources_scope
                    ON watched_sources(scope_type, scope_ref, status);

                CREATE TABLE IF NOT EXISTS source_snapshots (
                    id TEXT PRIMARY KEY,
                    question_id TEXT REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    watched_source_id TEXT REFERENCES watched_sources(id) ON DELETE SET NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    retrieved_at TEXT NOT NULL,
                    raw_payload_path TEXT,
                    raw_payload_sha256 TEXT,
                    parsed_values TEXT NOT NULL DEFAULT '{}',
                    adapter_version TEXT,
                    status TEXT NOT NULL DEFAULT 'success',
                    error_message TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_source_snapshots_question
                    ON source_snapshots(question_id, retrieved_at DESC);

                CREATE TABLE IF NOT EXISTS alert_events (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    recommended_action TEXT NOT NULL,
                    acknowledged_at TEXT,
                    dismissed_at TEXT,
                    dismiss_note TEXT,
                    dismiss_actor TEXT,
                    dismiss_reason TEXT,
                    dismiss_ttl_days INTEGER,
                    last_attempted_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    seen_count INTEGER NOT NULL DEFAULT 1,
                    last_seen_at TEXT,
                    ack_note TEXT,
                    alert_key TEXT,
                    disposition TEXT
                );

                CREATE TABLE IF NOT EXISTS autopilot_policies (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    mode TEXT NOT NULL DEFAULT 'propose',
                    cadence TEXT NOT NULL,
                    scheduled_review_id TEXT REFERENCES scheduled_reviews(id) ON DELETE SET NULL,
                    materiality_policy TEXT NOT NULL DEFAULT '{}',
                    guardrail_policy TEXT NOT NULL DEFAULT '{}',
                    notification_policy TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    created_by TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_autopilot_policies_question
                    ON autopilot_policies(question_id, enabled);

                CREATE TABLE IF NOT EXISTS autopilot_runs (
                    id TEXT PRIMARY KEY,
                    policy_id TEXT NOT NULL REFERENCES autopilot_policies(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger_reason TEXT NOT NULL,
                    sources_checked INTEGER NOT NULL DEFAULT 0,
                    sources_changed INTEGER NOT NULL DEFAULT 0,
                    material_changes INTEGER NOT NULL DEFAULT 0,
                    proposal_id TEXT,
                    forecast_snapshot_id TEXT,
                    alerts_created INTEGER NOT NULL DEFAULT 0,
                    diagnostics TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_autopilot_runs_policy
                    ON autopilot_runs(policy_id, started_at DESC);

                CREATE TABLE IF NOT EXISTS forecast_update_proposals (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    run_id TEXT REFERENCES autopilot_runs(id) ON DELETE SET NULL,
                    prior_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    proposed_probability_or_distribution TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    source_snapshot_refs TEXT NOT NULL DEFAULT '[]',
                    model_run_refs TEXT NOT NULL DEFAULT '[]',
                    assumption_refs TEXT NOT NULL DEFAULT '[]',
                    reference_class_refs TEXT NOT NULL DEFAULT '[]',
                    snapshot_args TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT,
                    resulting_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    expires_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_update_proposals_question
                    ON forecast_update_proposals(question_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS panel_runs (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    snapshot_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    aggregation_method TEXT NOT NULL DEFAULT 'trimmed_geomean_odds',
                    trim INTEGER NOT NULL DEFAULT 0,
                    aggregate_probability REAL NOT NULL,
                    perspectives TEXT NOT NULL DEFAULT '[]',
                    spread_summary TEXT NOT NULL DEFAULT '{}',
                    notes TEXT NOT NULL DEFAULT '[]',
                    triggered_by TEXT,
                    judge TEXT,
                    final_source TEXT NOT NULL DEFAULT 'pool',
                    research_rounds INTEGER NOT NULL DEFAULT 0,
                    supervisor_evidence TEXT NOT NULL DEFAULT '[]',
                    delphi_rounds INTEGER NOT NULL DEFAULT 0,
                    delphi_audit TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_panel_runs_question
                    ON panel_runs(question_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS panel_estimates (
                    id TEXT PRIMARY KEY,
                    panel_run_id TEXT NOT NULL REFERENCES panel_runs(id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    perspective TEXT NOT NULL,
                    probability REAL NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    trimmed INTEGER NOT NULL DEFAULT 0,
                    confidence_low REAL,
                    confidence_high REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    reasons_up TEXT NOT NULL DEFAULT '[]',
                    reasons_down TEXT NOT NULL DEFAULT '[]',
                    change_my_mind TEXT NOT NULL DEFAULT '[]',
                    crux TEXT,
                    agent_model TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_panel_estimates_run
                    ON panel_estimates(panel_run_id);

                CREATE TABLE IF NOT EXISTS deviation_bets (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    panel_run_id TEXT REFERENCES panel_runs(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL,
                    market_price REAL NOT NULL,
                    blind_pool REAL,
                    reconciled_verdict REAL NOT NULL,
                    deviation_pp REAL NOT NULL,
                    named_edge TEXT,
                    threshold_pp REAL NOT NULL,
                    forecast_origin TEXT,
                    outcome TEXT,
                    brier_ours REAL,
                    brier_market REAL,
                    brier_delta REAL,
                    resolution_id TEXT REFERENCES resolutions(id) ON DELETE SET NULL,
                    scored_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_deviation_bets_question
                    ON deviation_bets(question_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_deviation_bets_open
                    ON deviation_bets(outcome, created_at DESC);

                CREATE TABLE IF NOT EXISTS analyst_notes (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
                    resolution_id TEXT REFERENCES resolutions(id) ON DELETE SET NULL,
                    kind TEXT NOT NULL DEFAULT 'brief',
                    created_at TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    headline TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    how_it_feels TEXT NOT NULL DEFAULT '',
                    how_it_thinks TEXT NOT NULL DEFAULT '',
                    looking_for TEXT NOT NULL DEFAULT '',
                    be_aware TEXT NOT NULL DEFAULT '',
                    stance TEXT,
                    verdict TEXT,
                    confidence_at_write REAL,
                    agent_model TEXT,
                    prompt_version TEXT,
                    forecasting_protocol_version TEXT,
                    generator TEXT NOT NULL DEFAULT 'llm',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_analyst_notes_question
                    ON analyst_notes(question_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS forecast_links (
                    id TEXT PRIMARY KEY,
                    from_question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    to_question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    link_type TEXT NOT NULL DEFAULT 'related',
                    weight REAL NOT NULL DEFAULT 1.0,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_forecast_links_from
                    ON forecast_links(from_question_id);
                CREATE INDEX IF NOT EXISTS idx_forecast_links_to
                    ON forecast_links(to_question_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_forecast_links_edge
                    ON forecast_links(from_question_id, to_question_id, link_type);

                CREATE TABLE IF NOT EXISTS thesis_members (
                    id TEXT PRIMARY KEY,
                    thesis_question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    member_question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    direction TEXT NOT NULL DEFAULT 'support',
                    weight REAL NOT NULL DEFAULT 1.0,
                    role TEXT,
                    target REAL,
                    hi_is_good INTEGER NOT NULL DEFAULT 1,
                    max_age_days REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_thesis_members_thesis
                    ON thesis_members(thesis_question_id);
                CREATE INDEX IF NOT EXISTS idx_thesis_members_member
                    ON thesis_members(member_question_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_thesis_members_edge
                    ON thesis_members(thesis_question_id, member_question_id);

                CREATE TABLE IF NOT EXISTS thesis_entities (
                    id TEXT PRIMARY KEY,
                    thesis_question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    label TEXT,
                    kind TEXT NOT NULL DEFAULT 'entity',
                    weights TEXT NOT NULL DEFAULT '[]',
                    action_threshold REAL,
                    created_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_thesis_entities_thesis
                    ON thesis_entities(thesis_question_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_thesis_entities_name
                    ON thesis_entities(thesis_question_id, name);

                CREATE TABLE IF NOT EXISTS domain_error_profiles (
                    id TEXT PRIMARY KEY,
                    domain TEXT,
                    topic TEXT,
                    forecast_horizon_bucket TEXT,
                    question_type TEXT,
                    sample_count INTEGER NOT NULL DEFAULT 0,
                    calibration_summary TEXT NOT NULL DEFAULT '{}',
                    recurring_errors TEXT NOT NULL DEFAULT '[]',
                    recommended_adjustments TEXT NOT NULL DEFAULT '[]',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS market_models (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    title TEXT NOT NULL,
                    question TEXT NOT NULL,
                    depth TEXT NOT NULL DEFAULT 'standard',
                    spec TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL DEFAULT 'active',
                    current_version INTEGER NOT NULL DEFAULT 0,
                    tags TEXT NOT NULL DEFAULT '[]',
                    agent_model TEXT,
                    prompt_version TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_market_models_updated
                    ON market_models(updated_at DESC);

                CREATE TABLE IF NOT EXISTS market_model_presentations (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL REFERENCES market_models(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    as_of_analysis TEXT,
                    as_of_data TEXT,
                    schema_version TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'complete',
                    summary TEXT NOT NULL DEFAULT '',
                    presentation TEXT NOT NULL DEFAULT '{}',
                    refine_instruction TEXT,
                    diagnostics TEXT NOT NULL DEFAULT '{}',
                    agent_model TEXT,
                    prompt_version TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_mmp_version
                    ON market_model_presentations(model_id, version);

                CREATE TABLE IF NOT EXISTS market_model_messages (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL REFERENCES market_models(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    content TEXT NOT NULL DEFAULT '',
                    version_ref INTEGER,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_mmm_model
                    ON market_model_messages(model_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS market_data_series (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL REFERENCES market_models(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    name TEXT NOT NULL,
                    source_type TEXT,
                    source TEXT,
                    unit TEXT,
                    points TEXT NOT NULL DEFAULT '[]',
                    as_of TEXT,
                    evidence_refs TEXT NOT NULL DEFAULT '[]',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_mds_model
                    ON market_data_series(model_id);

                -- Triage rubrics: the desk-authored "what counts as INTERESTING
                -- here" taste, scoped like calibration lessons (global / domain /
                -- topic / domain_topic / question_type). The labeler retrieves the
                -- most-specific active rubric for a question and folds its criteria
                -- into the labeling prompt, so the desk's taste is explicit and
                -- versioned, not re-improvised each run. (Thinking Machines L9: the
                -- relevant-vs-interesting reframe carried the result.)
                CREATE TABLE IF NOT EXISTS triage_rubrics (
                    id TEXT PRIMARY KEY,
                    scope_type TEXT NOT NULL,
                    scope_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    interesting_criteria TEXT NOT NULL DEFAULT '',
                    uninteresting_criteria TEXT NOT NULL DEFAULT '',
                    irrelevant_criteria TEXT NOT NULL DEFAULT '',
                    examples TEXT NOT NULL DEFAULT '[]',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_triage_rubrics_scope
                    ON triage_rubrics(scope_type, scope_ref);

                -- Triage labels: a STAGING surface that keeps the evidence table
                -- clean. Each row is one candidate reading the cheap auto-labeler
                -- classified BEFORE it becomes evidence. ``auto_label`` is the
                -- model's three-way call; ``expert_label`` is the operator's
                -- adjudication on a CONTESTED item (Thinking Machines L8 —
                -- contested-routing). The held-out trust gate scores auto_label
                -- against expert_label; the contested loop opens an alert when they
                -- disagree. ``triage_label`` is the current best label (auto, or
                -- expert once adjudicated).
                CREATE TABLE IF NOT EXISTS triage_labels (
                    id TEXT PRIMARY KEY,
                    question_id TEXT,
                    created_at TEXT NOT NULL,
                    candidate_ref TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    summary TEXT NOT NULL DEFAULT '',
                    source_type TEXT,
                    source TEXT,
                    url TEXT,
                    auto_label TEXT,
                    expert_label TEXT,
                    triage_label TEXT,
                    label_source TEXT NOT NULL DEFAULT 'auto',
                    materiality TEXT NOT NULL DEFAULT 'medium',
                    verdict TEXT NOT NULL DEFAULT 'skim',
                    relevance REAL,
                    rationale TEXT NOT NULL DEFAULT '',
                    rubric_id TEXT,
                    model TEXT,
                    contested INTEGER NOT NULL DEFAULT 0,
                    alert_id TEXT,
                    adjudicated_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_triage_labels_question
                    ON triage_labels(question_id, created_at);

                -- Desk key/value state: a tiny durable side-table for
                -- process-autonomy bookkeeping that does not belong on any
                -- domain row (e.g. the last-observed triage trust-gate mode, so
                -- graduation/demotion alerts fire once per TRANSITION, not every
                -- sweep). Value is opaque text (JSON or a bare string).
                CREATE TABLE IF NOT EXISTS desk_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT NOT NULL
                );

                -- Operator practice loop (R2): the OPERATOR's own forecasts,
                -- recorded so the human can be scored + calibrated exactly like
                -- the system is. `probability_or_distribution` is JSON (a scalar
                -- in [0,1] for a binary, or a distribution dict). `context` is
                -- 'practice' (recorded live, scored when the question resolves) or
                -- 'drill' (a replay of an already-resolved question, scored on the
                -- spot). `resolved_outcome`/`brier`/`scored_at` fill in at scoring.
                CREATE TABLE IF NOT EXISTS operator_estimates (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL REFERENCES forecast_questions(id) ON DELETE CASCADE,
                    probability_or_distribution TEXT NOT NULL,
                    note TEXT,
                    context TEXT NOT NULL DEFAULT 'practice',
                    created_at TEXT NOT NULL,
                    resolved_outcome TEXT,
                    brier REAL,
                    scored_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_operator_estimates_question
                    ON operator_estimates(question_id, created_at);
                """
            )
            self._ensure_column(conn, "model_runs", "status", "TEXT NOT NULL DEFAULT 'success'")
            self._ensure_column(conn, "forecast_snapshots", "metadata", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "evidence_items", "claim_type", "TEXT NOT NULL DEFAULT 'fact'")
            self._ensure_column(conn, "score_records", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "score_records", "proper_score", "REAL")
            self._ensure_column(conn, "score_records", "score_rule", "TEXT")
            # Measurement-honesty quarantine: a NON-NULL reason marks a score row
            # as a provable ingestion artifact (e.g. a synthetic target-price
            # binary whose imported baseline is a degenerate 0.0) — excluded from
            # every cohort aggregate + made calibration-ineligible via the gated
            # audit path, never a real forecast miss.
            self._ensure_column(conn, "score_records", "audit_quarantine_reason", "TEXT")
            self._ensure_column(conn, "postmortems", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "calibration_lessons", "invalidated_by_correction_id", "TEXT")
            self._ensure_column(conn, "resolutions", "trusted_policy_id", "TEXT")
            self._ensure_column(conn, "reference_classes", "check_cadence", "TEXT")
            self._ensure_column(conn, "reference_classes", "sample_size", "INTEGER")
            self._ensure_column(conn, "panel_runs", "judge", "TEXT")
            # AIA P0.3: which branch produced the committed aggregate
            # ('pool' | 'judge_high'). Defaults to 'pool' so pre-P0.3 runs read
            # back as non-overridden (no regression).
            self._ensure_column(
                conn, "panel_runs", "final_source", "TEXT NOT NULL DEFAULT 'pool'"
            )
            # AIA P1.1 — agentic-supervisor fresh-search loop. research_rounds
            # counts the fresh-search re-syntheses (0 = no loop / no search_runner);
            # supervisor_evidence holds the fresh evidence items. Both default to
            # the no-loop state so existing rows + the no-loop path read unchanged.
            self._ensure_column(
                conn, "panel_runs", "research_rounds", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn, "panel_runs", "supervisor_evidence", "TEXT NOT NULL DEFAULT '[]'"
            )
            # Delphi v1 — optional anonymous revision round. delphi_rounds counts
            # revision passes (0 = no Delphi / byte-identical legacy path; v1 caps
            # at 1); delphi_audit holds the prior-round audit artifact. Both default
            # to the no-Delphi state so existing rows + the delphi_rounds==0 path
            # read back unchanged.
            self._ensure_column(
                conn, "panel_runs", "delphi_rounds", "INTEGER NOT NULL DEFAULT 0"
            )
            self._ensure_column(
                conn, "panel_runs", "delphi_audit", "TEXT NOT NULL DEFAULT '{}'"
            )
            self._ensure_column(conn, "scheduled_reviews", "auto_score", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "auto_postmortem", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "stale_days", "INTEGER NOT NULL DEFAULT 7")
            self._ensure_column(conn, "scheduled_reviews", "confidence_below", "REAL")
            self._ensure_column(conn, "scheduled_reviews", "confidence_above", "REAL")
            self._ensure_column(conn, "scheduled_reviews", "large_delta_threshold", "REAL")
            self._ensure_column(conn, "scheduled_reviews", "lease_owner", "TEXT")
            self._ensure_column(conn, "scheduled_reviews", "lease_expires_at", "TEXT")
            self._ensure_column(conn, "scheduled_reviews", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "unchanged_streak", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "scheduled_reviews", "adaptive_multiplier", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "forecast_questions", "decision_owner", "TEXT")
            self._ensure_column(conn, "forecast_questions", "decision_deadline", "TEXT")
            self._ensure_column(conn, "forecast_questions", "action_threshold", "TEXT")
            self._ensure_column(conn, "forecast_questions", "update_triggers", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "reasons_up", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "reasons_down", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "forecast_snapshots", "change_my_mind", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(conn, "postmortems", "failure_class", "TEXT")
            self._ensure_column(conn, "model_runs", "market_model_id", "TEXT")
            # R4 Living Models — score a model_run against its question's confirmed
            # outcome (binary: Brier of the model's probability; numeric: coverage
            # hit inside [lo,hi] + absolute error vs projected_value). All nullable:
            # an unscored run (no confirmed resolution, or output carries no usable
            # projection) leaves them NULL and is invisible to model-skill.
            self._ensure_column(conn, "model_runs", "outcome_score", "REAL")
            self._ensure_column(conn, "model_runs", "interval_hit", "INTEGER")
            self._ensure_column(conn, "model_runs", "scored_at", "TEXT")
            # Typed watched-source roles: distinguish resolution-critical sources
            # (resolver/consensus/official_primary) from background context (RSS).
            self._ensure_column(conn, "watched_sources", "role", "TEXT")
            # AIA P1.2 — content-aware foreknowledge judge (SECOND leakage channel).
            # leakage_verdicts holds the persisted judge JSON (or '{}' when the
            # opt-in channel was OFF); content_flag_count is the cheap integer the
            # worst-case rescore aggregates per question. Both default to the
            # not-flagged state so an existing backtest is unchanged.
            self._ensure_column(conn, "backtest_cases", "leakage_verdicts", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_column(conn, "backtest_cases", "content_flag_count", "INTEGER NOT NULL DEFAULT 0")
            # Slice 5 — dismissal audit trail on alert_events (recorded human silence).
            self._ensure_column(conn, "alert_events", "dismissed_at", "TEXT")
            self._ensure_column(conn, "alert_events", "dismiss_note", "TEXT")
            self._ensure_column(conn, "alert_events", "dismiss_actor", "TEXT")
            self._ensure_column(conn, "alert_events", "dismiss_reason", "TEXT")
            self._ensure_column(conn, "alert_events", "dismiss_ttl_days", "INTEGER")
            # Slice 8 — per-alert re-spend cooldown (paid-tier exponential backoff)
            # so the continuous automode loop never re-spends on the same
            # gated/failing alert every cycle. NEVER touched by an ack — a failed
            # paid attempt stamps these while leaving the alert OPEN (no bare-ack).
            self._ensure_column(conn, "alert_events", "last_attempted_at", "TEXT")
            self._ensure_column(conn, "alert_events", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
            # Warnings-lifecycle fix — universal enqueue dedup + auditable auto-close.
            # ``seen_count`` / ``last_seen_at`` are the dedup touch trail (an open
            # alert with the same scope+reason is touched, not re-emitted); ``ack_note``
            # records WHY an alert was auto-closed (reconcile) or folded (collapse), so
            # an automatic close is auditable + distinct from an operator ack/dismissal.
            self._ensure_column(conn, "alert_events", "seen_count", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "alert_events", "last_seen_at", "TEXT")
            self._ensure_column(conn, "alert_events", "ack_note", "TEXT")
            self._ensure_column(conn, "alert_events", "alert_key", "TEXT")
            self._ensure_column(conn, "alert_events", "disposition", "TEXT")
            self._ensure_column(conn, "forecast_update_proposals", "resulting_forecast_id", "TEXT")
            self._ensure_column(conn, "forecast_update_proposals", "expires_at", "TEXT")
            self._ensure_column(conn, "forecast_update_proposals", "snapshot_args", "TEXT NOT NULL DEFAULT '{}'")
            self._ensure_operational_uniqueness(conn)
            # R2 operator practice loop — defensive migrations for the scoring
            # columns (idempotent; a fresh CREATE already carries them).
            self._ensure_column(conn, "operator_estimates", "resolved_outcome", "TEXT")
            self._ensure_column(conn, "operator_estimates", "brier", "REAL")
            self._ensure_column(conn, "operator_estimates", "scored_at", "TEXT")

            # Multiplayer ledger governance is an additive domain. Keep its DDL
            # outside this already-large schema body while initializing it on
            # every normal ForecastLedger construction and legacy database open.
            from forecasting.change_control.store import initialize_schema

            initialize_schema(conn)
            from forecasting.ledger.workflow import initialize_schema as initialize_workflow_schema

            initialize_workflow_schema(conn)

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _ensure_operational_uniqueness(self, conn: sqlite3.Connection) -> None:
        """Backfill stable keys, collapse legacy duplicates, then enforce them in SQLite."""
        # Repair legacy databases on open: a resolved question is a hard stop for
        # active forecast-maintenance producers. New resolutions perform the same
        # teardown transactionally in ``resolve_question``.
        stamp = utc_now_iso()
        conn.execute(
            """
            UPDATE forecast_update_proposals
            SET expires_at = strftime('%Y-%m-%dT%H:%M:%SZ', created_at, '+24 hours')
            WHERE status = 'pending' AND expires_at IS NULL
            """
        )
        conn.execute(
            """
            UPDATE scheduled_reviews SET enabled = 0, lease_owner = NULL, lease_expires_at = NULL
            WHERE enabled = 1 AND scope_type = 'question' AND scope_ref IN (
                SELECT id FROM forecast_questions WHERE status = 'resolved'
            )
            """
        )
        conn.execute(
            """
            UPDATE watched_sources SET status = 'inactive'
            WHERE status = 'active' AND scope_type = 'question' AND scope_ref IN (
                SELECT id FROM forecast_questions WHERE status = 'resolved'
            )
            """
        )
        conn.execute(
            """
            UPDATE autopilot_policies SET enabled = 0, updated_at = ?
            WHERE enabled = 1 AND question_id IN (
                SELECT id FROM forecast_questions WHERE status = 'resolved'
            )
            """,
            (stamp,),
        )
        conn.execute(
            """
            UPDATE forecast_update_proposals
            SET status = 'rejected', reviewed_at = ?,
                reviewed_by = COALESCE(reviewed_by, 'lifecycle:resolved')
            WHERE status IN ('pending', 'committing') AND question_id IN (
                SELECT id FROM forecast_questions WHERE status = 'resolved'
            )
            """,
            (stamp,),
        )
        conn.execute(
            """
            UPDATE alert_events SET acknowledged_at = ?,
                ack_note = COALESCE(ack_note, 'auto_close:question_resolved'),
                disposition = COALESCE(disposition, 'resolved_by_resolution')
            WHERE acknowledged_at IS NULL AND scope_type = 'question' AND scope_ref IN (
                SELECT id FROM forecast_questions WHERE status = 'resolved'
            )
              AND reason NOT IN ('score_due', 'high_impact_score_due',
                                 'postmortem_due', 'high_impact_postmortem_due')
            """,
            (stamp,),
        )
        rows = conn.execute(
            "SELECT id, scope_type, scope_ref, reason FROM alert_events "
            "WHERE alert_key IS NULL OR alert_key = ''"
        ).fetchall()
        for row in rows:
            prior_forecast_id = None
            if row["scope_type"] == "question" and str(row["reason"]).startswith("new_evidence:"):
                question = conn.execute(
                    "SELECT current_forecast_id FROM forecast_questions WHERE id = ?",
                    (row["scope_ref"],),
                ).fetchone()
                prior_forecast_id = question["current_forecast_id"] if question else None
            conn.execute(
                "UPDATE alert_events SET alert_key = ? WHERE id = ?",
                (
                    _alerts.normalized_alert_key(
                        row["reason"], prior_forecast_id=prior_forecast_id
                    ),
                    row["id"],
                ),
            )

        duplicate_alerts = conn.execute(
            """
            SELECT scope_type, scope_ref, alert_key
            FROM alert_events
            WHERE acknowledged_at IS NULL
            GROUP BY scope_type, scope_ref, alert_key
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for group in duplicate_alerts:
            members = conn.execute(
                """
                SELECT id, severity, seen_count FROM alert_events
                WHERE scope_type = ? AND scope_ref = ? AND alert_key = ?
                  AND acknowledged_at IS NULL
                ORDER BY created_at ASC, id ASC
                """,
                (group["scope_type"], group["scope_ref"], group["alert_key"]),
            ).fetchall()
            survivor = members[0]
            severity = "high" if any(row["severity"] == "high" for row in members) else (
                "warning" if any(row["severity"] == "warning" for row in members) else "info"
            )
            seen_count = sum(int(row["seen_count"] or 1) for row in members)
            conn.execute(
                "UPDATE alert_events SET severity = ?, seen_count = ? WHERE id = ?",
                (severity, seen_count, survivor["id"]),
            )
            for duplicate in members[1:]:
                conn.execute(
                    "UPDATE alert_events SET acknowledged_at = COALESCE(acknowledged_at, created_at), "
                    "ack_note = COALESCE(ack_note, ?), "
                    "disposition = COALESCE(disposition, 'duplicate') WHERE id = ?",
                    (f"collapsed:{survivor['id']}", duplicate["id"]),
                )

        def disable_duplicates(table: str, key_columns: str, active_where: str, disable_sql: str) -> None:
            groups = conn.execute(
                f"SELECT {key_columns} FROM {table} WHERE {active_where} "
                f"GROUP BY {key_columns} HAVING COUNT(*) > 1"
            ).fetchall()
            key_names = [part.strip() for part in key_columns.split(",")]
            for group in groups:
                predicates = " AND ".join(
                    f"{name} IS ?" if group[name] is None else f"{name} = ?"
                    for name in key_names
                )
                values = [group[name] for name in key_names]
                members = conn.execute(
                    f"SELECT id FROM {table} WHERE {active_where} AND {predicates} "
                    "ORDER BY rowid ASC",
                    values,
                ).fetchall()
                for duplicate in members[1:]:
                    conn.execute(disable_sql, (duplicate["id"],))

        disable_duplicates(
            "scheduled_reviews",
            "scope_type, scope_ref, cadence, trigger_reason",
            "enabled = 1",
            "UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?",
        )
        disable_duplicates(
            "watched_sources",
            "scope_type, scope_ref, source, source_type",
            "status = 'active'",
            "UPDATE watched_sources SET status = 'inactive' WHERE id = ?",
        )
        disable_duplicates(
            "autopilot_policies",
            "question_id",
            "enabled = 1",
            "UPDATE autopilot_policies SET enabled = 0 WHERE id = ?",
        )
        disable_duplicates(
            "forecast_update_proposals",
            "question_id, prior_forecast_id",
            "status IN ('pending', 'committing')",
            "UPDATE forecast_update_proposals SET status = 'rejected' WHERE id = ?",
        )

        duplicate_postmortems = conn.execute(
            """
            SELECT score_record_id FROM postmortems
            WHERE invalidated_by_correction_id IS NULL
            GROUP BY score_record_id HAVING COUNT(*) > 1
            """
        ).fetchall()
        for group in duplicate_postmortems:
            members = conn.execute(
                """
                SELECT id FROM postmortems
                WHERE score_record_id = ? AND invalidated_by_correction_id IS NULL
                ORDER BY created_at ASC, id ASC
                """,
                (group["score_record_id"],),
            ).fetchall()
            for duplicate in members[1:]:
                conn.execute(
                    "UPDATE postmortems SET invalidated_by_correction_id = ? WHERE id = ?",
                    (f"duplicate:{members[0]['id']}", duplicate["id"]),
                )

        conn.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_alert_events_open_key
                ON alert_events(scope_type, scope_ref, alert_key)
                WHERE acknowledged_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_scheduled_reviews_active
                ON scheduled_reviews(scope_type, IFNULL(scope_ref, ''), cadence, trigger_reason)
                WHERE enabled = 1;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_watched_sources_active
                ON watched_sources(scope_type, IFNULL(scope_ref, ''), source, source_type)
                WHERE status = 'active';
            CREATE UNIQUE INDEX IF NOT EXISTS uq_autopilot_policies_active
                ON autopilot_policies(question_id)
                WHERE enabled = 1;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_forecast_update_proposals_active
                ON forecast_update_proposals(question_id, IFNULL(prior_forecast_id, ''))
                WHERE status IN ('pending', 'committing');
            CREATE UNIQUE INDEX IF NOT EXISTS uq_postmortems_active_score
                ON postmortems(score_record_id)
                WHERE invalidated_by_correction_id IS NULL;
            """
        )

    def _is_auto_review_eligible(
        self,
        domain: str | None,
        tags: list[str] | None,
    ) -> bool:
        return _reviews._is_auto_review_eligible(self, domain=domain, tags=tags)

    def create_question(
        self,
        *,
        title: str,
        resolution_criteria: str,
        outcome_space: OutcomeSpace | None = None,
        description: str = "",
        resolution_source: str | None = None,
        close_time: str | None = None,
        resolution_time: str | None = None,
        tags: list[str] | None = None,
        domain: str | None = None,
        topics: list[str] | None = None,
        owner: str | None = None,
        impact: str | None = None,
        review_cadence: str | None = None,
        next_review_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        decision_owner: str | None = None,
        decision_deadline: str | None = None,
        action_threshold: str | None = None,
        update_triggers: Any = None,
    ) -> ForecastQuestion:
        return _questions.create_question(self, title=title, resolution_criteria=resolution_criteria, outcome_space=outcome_space, description=description, resolution_source=resolution_source, close_time=close_time, resolution_time=resolution_time, tags=tags, domain=domain, topics=topics, owner=owner, impact=impact, review_cadence=review_cadence, next_review_at=next_review_at, metadata=metadata, decision_owner=decision_owner, decision_deadline=decision_deadline, action_threshold=action_threshold, update_triggers=update_triggers)

    def list_questions(
        self,
        *,
        status: str | None = None,
        domain: str | None = None,
        limit: int | None = None,
    ) -> list[ForecastQuestion]:
        return _questions.list_questions(self, status=status, domain=domain, limit=limit)

    def get_question(self, question_id: str) -> ForecastQuestion:
        return _questions.get_question(self, question_id=question_id)

    def update_question_decision(
        self,
        question_id: str,
        *,
        decision_owner: str | None = None,
        decision_deadline: str | None = None,
        action_threshold: str | None = None,
        update_triggers: Any = None,
    ) -> ForecastQuestion:
        return _questions.update_question_decision(self, question_id=question_id, decision_owner=decision_owner, decision_deadline=decision_deadline, action_threshold=action_threshold, update_triggers=update_triggers)

    # ── per-forecast settings (cadence + decision card + hooks gates/thresholds) ──
    def update_question_config(
        self,
        question_id: str,
        *,
        review_cadence: str | None = None,
        decision: dict[str, Any] | None = None,
        hooks: dict[str, Any] | None = None,
    ) -> ForecastQuestion:
        return _questions.update_question_config(self, question_id=question_id, review_cadence=review_cadence, decision=decision, hooks=hooks)

    def set_question_market_ref(
        self,
        question_id: str,
        *,
        market_id: str,
        market_source: str | None = None,
        actor: str | None = None,
    ) -> ForecastQuestion:
        return _questions.set_question_market_ref(self, question_id=question_id, market_id=market_id, market_source=market_source, actor=actor)

    def _cadence_is_valid(self, cadence: str) -> bool:
        return _questions._cadence_is_valid(self, cadence=cadence)

    def _rearm_question_cadence(self, question_id: str, cadence: str | None) -> None:
        return _questions._rearm_question_cadence(self, question_id=question_id, cadence=cadence)

    def _validate_hook_profile_patch(self, profile: Any) -> dict[str, Any]:
        return _questions._validate_hook_profile_patch(self, profile=profile)

    def _validate_hook_overrides(self, overrides: Any) -> dict[str, str]:
        return _questions._validate_hook_overrides(self, overrides=overrides)

    def resolve_question_config(self, question_id: str) -> dict[str, Any]:
        return _questions.resolve_question_config(self, question_id=question_id)

    def rename_question(self, question_id: str, new_title: str, *, actor: str | None = None) -> ForecastQuestion:
        return _questions.rename_question(self, question_id=question_id, new_title=new_title, actor=actor)

    def decision_readiness_issues(self, question: ForecastQuestion | str) -> list[str]:
        return _questions.decision_readiness_issues(self, question=question)

    def _audit_unapplied_lessons(
        self,
        question: Any,
        committed_payload: Any,
        calibration_adjustment: dict[str, Any] | None,
    ) -> int:
        return _scoring._audit_unapplied_lessons(self, question=question, committed_payload=committed_payload, calibration_adjustment=calibration_adjustment)

    @staticmethod
    def _committed_winner_prob(payload: Any, outcome_type: str | None = None) -> float | None:
        return _snapshots._committed_winner_prob(payload=payload, outcome_type=outcome_type)

    @staticmethod
    def _machine_scoreable_payload(payload: Any, outcome_space: OutcomeSpace) -> bool:
        return _snapshots._machine_scoreable_payload(payload=payload, outcome_space=outcome_space)

    def _derived_child_present(self, question_id: str) -> bool:
        return _snapshots._derived_child_present(self, question_id=question_id)

    def _record_lesson_applications(
        self,
        question: Any,
        snapshot_id: str | None,
        committed_payload: Any,
        calibration_adjustment: dict[str, Any] | None,
    ) -> None:
        return _scoring._record_lesson_applications(self, question=question, snapshot_id=snapshot_id, committed_payload=committed_payload, calibration_adjustment=calibration_adjustment)

    def lesson_coverage(self) -> list[dict[str, Any]]:
        return _lessons.lesson_coverage(self)

    def calibration_correcting_lessons(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        return _lessons.calibration_correcting_lessons(self, domain=domain)

    def detect_templated_batches(
        self, *, window_days: int = 7, min_cluster: int = 3, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Flag clusters of recent LIVE forecasts that share an identical structural
        skeleton — same method + reasoning_methods + a name-stripped rationale tail.
        That is the tell of a 'one template x N' batch (a script substituting a name
        into a fixed shell) rather than N individually-reasoned forecasts. Read-only;
        a heuristic flag for REVIEW, never a block — a shared standardized footer can
        also cluster, so the member titles let a human dismiss a false hit. Defensive:
        never raises on malformed metadata/timestamps. See skills/ledger-interaction."""
        import hashlib
        import re

        def _skeleton(text: str) -> str:
            # drop digits + Capitalized tokens (substituted names/places/numbers) so two
            # rationales that differ ONLY by a name hash identically; fall back to the
            # fully-lowercased tokens when stripping empties it (e.g. Title-Case prose)
            # so distinct rationales don't all collapse to "" and falsely cluster.
            text = re.sub(r"\d+(?:\.\d+)?", "", text or "")
            words = re.findall(r"[A-Za-z']+", text)
            stripped = [w.lower() for w in words if not w[:1].isupper()]
            return " ".join(stripped if len(stripped) >= 6 else (w.lower() for w in words))

        window_days = max(1, int(window_days))
        min_cluster = max(1, int(min_cluster))
        limit = max(1, int(limit))
        cutoff_iso = (timestamp_to_datetime(utc_now_iso()) - timedelta(days=window_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # One bounded query: current snapshots of active questions, live + in-window,
        # newest first, capped — no per-question N+1 and no unbounded scan.
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT s.forecast_id, s.question_id, s.method, s.rationale, s.metadata, "
                "q.title FROM forecast_snapshots s "
                "JOIN forecast_questions q ON q.current_forecast_id = s.forecast_id "
                "WHERE q.status = 'active' AND s.forecast_origin = 'live' "
                "AND s.created_at >= ? ORDER BY s.created_at DESC LIMIT ?",
                (cutoff_iso, limit),
            ).fetchall()
        clusters: dict[str, dict[str, Any]] = {}
        for row in rows:
            meta = json_loads(row["metadata"], {})
            if not isinstance(meta, dict):
                meta = {}  # a script may have written a non-dict metadata blob
            raw = meta.get("reasoning_methods")
            methods = tuple(sorted(str(m) for m in raw)) if isinstance(raw, list) else ()
            method = (row["method"] or "").strip().lower()
            tail = _skeleton((row["rationale"] or "")[-200:])
            if len(tail.split()) < 6:
                continue  # too thin to fingerprint reliably (avoids empty-skeleton clustering)
            key = hashlib.sha1(f"{method}|{methods}|{tail}".encode()).hexdigest()[:16]
            entry = clusters.setdefault(key, {
                "fingerprint": key, "method": method,
                "reasoning_methods": list(methods), "members": [],
            })
            entry["members"].append({
                "question_id": row["question_id"], "forecast_id": row["forecast_id"],
                "title": (row["title"] or "")[:70],
            })
        flagged = [dict(c, count=len(c["members"])) for c in clusters.values() if len(c["members"]) >= min_cluster]
        flagged.sort(key=lambda c: c["count"], reverse=True)
        return flagged

    def create_snapshot(
        self,
        *,
        question_id: str,
        probability_or_distribution: Any,
        rationale: str,
        as_of: str | None = None,
        confidence: float | None = None,
        method: str | None = None,
        ensemble_components: dict[str, Any] | None = None,
        key_assumptions: list[str] | None = None,
        assumption_refs: list[str] | None = None,
        reference_class_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        model_run_refs: list[str] | None = None,
        forecast_origin: str = "live",
        agent_model: str | None = None,
        prompt_version: str | None = None,
        forecasting_protocol_version: str | None = None,
        toolset_version: str | None = None,
        source_snapshot_refs: list[str] | None = None,
        evidence_cutoff: str | None = None,
        backtest_run_id: str | None = None,
        calibration_eligible: bool = True,
        calibration_weight: float = 1.0,
        calibration_lesson_refs: list[str] | None = None,
        calibration_adjustment: dict[str, Any] | None = None,
        stale_evidence_days: int | None = None,
        acknowledge_stale_evidence: bool = False,
        stale_evidence_reason: str | None = None,
        require_citations: bool = False,
        metadata: dict[str, Any] | None = None,
        set_current: bool = True,
        reasons_up: list[str] | None = None,
        reasons_down: list[str] | None = None,
        change_my_mind: list[str] | None = None,
        require_decision_readiness: bool = False,
        require_structured_reasoning: bool = False,
        require_components: bool = False,
        require_fresh_evidence: bool = False,
        require_panel: bool = False,
        panel_run_ref: str | None = None,
        panel_skipped_reason: str | None = None,
        outcome_paths: dict[str, Any] | None = None,
        require_outcome_paths: bool = False,
        style_autofix: bool = False,
        require_style: bool = True,
        reasoning_methods: list[str] | None = None,
        require_output_structure: bool = True,
        distribution_autofix: bool = False,
        enforce_resolved_hooks: bool = False,
        allow_resolved_backfill: bool = False,
        preview: bool = False,
    ) -> "ForecastSnapshot | dict[str, Any]":
        return _snapshots.create_snapshot(self, question_id=question_id, probability_or_distribution=probability_or_distribution, rationale=rationale, as_of=as_of, confidence=confidence, method=method, ensemble_components=ensemble_components, key_assumptions=key_assumptions, assumption_refs=assumption_refs, reference_class_refs=reference_class_refs, evidence_refs=evidence_refs, model_run_refs=model_run_refs, forecast_origin=forecast_origin, agent_model=agent_model, prompt_version=prompt_version, forecasting_protocol_version=forecasting_protocol_version, toolset_version=toolset_version, source_snapshot_refs=source_snapshot_refs, evidence_cutoff=evidence_cutoff, backtest_run_id=backtest_run_id, calibration_eligible=calibration_eligible, calibration_weight=calibration_weight, calibration_lesson_refs=calibration_lesson_refs, calibration_adjustment=calibration_adjustment, stale_evidence_days=stale_evidence_days, acknowledge_stale_evidence=acknowledge_stale_evidence, stale_evidence_reason=stale_evidence_reason, require_citations=require_citations, metadata=metadata, set_current=set_current, reasons_up=reasons_up, reasons_down=reasons_down, change_my_mind=change_my_mind, require_decision_readiness=require_decision_readiness, require_structured_reasoning=require_structured_reasoning, require_components=require_components, require_fresh_evidence=require_fresh_evidence, require_panel=require_panel, panel_run_ref=panel_run_ref, panel_skipped_reason=panel_skipped_reason, outcome_paths=outcome_paths, require_outcome_paths=require_outcome_paths, style_autofix=style_autofix, require_style=require_style, reasoning_methods=reasoning_methods, require_output_structure=require_output_structure, distribution_autofix=distribution_autofix, enforce_resolved_hooks=enforce_resolved_hooks, allow_resolved_backfill=allow_resolved_backfill, preview=preview)

    def _thesis_auto_aggregate_enabled(self, thesis_id: str) -> bool:
        return _theses._thesis_auto_aggregate_enabled(self, thesis_id=thesis_id)

    def _cascade_reaggregate_parents(self, member_id: str, *, as_of: str | None = None) -> None:
        return _theses._cascade_reaggregate_parents(self, member_id=member_id, as_of=as_of)

    def get_snapshot(self, forecast_id: str) -> ForecastSnapshot:
        return _snapshots.get_snapshot(self, forecast_id=forecast_id)

    def get_current_snapshot(self, question_id: str) -> ForecastSnapshot | None:
        return _snapshots.get_current_snapshot(self, question_id=question_id)

    def list_snapshots(self, question_id: str) -> list[ForecastSnapshot]:
        return _snapshots.list_snapshots(self, question_id=question_id)

    def add_evidence(
        self,
        *,
        question_id: str,
        source_or_note: str,
        claim: str = "",
        summary: str = "",
        source_url: str | None = None,
        source_name: str | None = None,
        source_type: str | None = None,
        published_at: str | None = None,
        available_at: str | None = None,
        reliability_rating: float | None = None,
        relevance_rating: float | None = None,
        stance: str = "context",
        claim_type: str = "fact",
        snapshot_path: str | None = None,
        admissible_for_backtests: bool = True,
        metadata: dict[str, Any] | None = None,
        archive_url_snapshot: bool = True,
        extra_leak_denylist: object = None,
    ) -> EvidenceItem:
        return _evidence.add_evidence(self, question_id=question_id, source_or_note=source_or_note, claim=claim, summary=summary, source_url=source_url, source_name=source_name, source_type=source_type, published_at=published_at, available_at=available_at, reliability_rating=reliability_rating, relevance_rating=relevance_rating, stance=stance, claim_type=claim_type, snapshot_path=snapshot_path, admissible_for_backtests=admissible_for_backtests, metadata=metadata, archive_url_snapshot=archive_url_snapshot, extra_leak_denylist=extra_leak_denylist)

    def get_evidence(self, evidence_id: str) -> EvidenceItem:
        return _evidence.get_evidence(self, evidence_id=evidence_id)

    def list_evidence(self, question_id: str) -> list[EvidenceItem]:
        return _evidence.list_evidence(self, question_id=question_id)

    def question_source_diversity(self, question_id: str) -> dict[str, Any]:
        return _evidence.question_source_diversity(self, question_id=question_id)

    def source_diversity_summary(self) -> dict[str, Any]:
        return _evidence.source_diversity_summary(self)

    def existing_evidence_keys(self, question_id: str) -> set[tuple[str, str]]:
        return _evidence.existing_evidence_keys(self, question_id=question_id)

    def find_stale_evidence_refs(
        self,
        question_id: str,
        evidence_refs: list[str],
        *,
        as_of: str | None = None,
        stale_days: int = 30,
    ) -> list[EvidenceItem]:
        return _evidence.find_stale_evidence_refs(self, question_id=question_id, evidence_refs=evidence_refs, as_of=as_of, stale_days=stale_days)

    def create_ingest_candidate(
        self,
        *,
        source: str,
        title: str | None = None,
        description: str = "",
        resolution_criteria: str = "",
        resolution_source: str | None = None,
        outcome_space: OutcomeSpace | None = None,
        close_time: str | None = None,
        resolution_time: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _market_models.create_ingest_candidate(self, source=source, title=title, description=description, resolution_criteria=resolution_criteria, resolution_source=resolution_source, outcome_space=outcome_space, close_time=close_time, resolution_time=resolution_time, metadata=metadata)

    def get_ingest_candidate(self, candidate_id: str) -> dict[str, Any]:
        return _market_models.get_ingest_candidate(self, candidate_id=candidate_id)

    def list_ingest_candidates(self, *, status: str | None = None) -> list[dict[str, Any]]:
        return _market_models.list_ingest_candidates(self, status=status)

    def confirm_ingest_candidate(
        self,
        candidate_id: str,
        *,
        title: str | None = None,
        resolution_criteria: str | None = None,
        domain: str | None = None,
        tags: list[str] | None = None,
        topics: list[str] | None = None,
    ) -> ForecastQuestion:
        return _market_models.confirm_ingest_candidate(self, candidate_id=candidate_id, title=title, resolution_criteria=resolution_criteria, domain=domain, tags=tags, topics=topics)

    def add_assumption(
        self,
        *,
        question_id: str,
        text: str,
        status: str = "active",
        check_cadence: str | None = None,
        evidence_refs: list[str] | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return _question_meta.add_assumption(self, question_id=question_id, text=text, status=status, check_cadence=check_cadence, evidence_refs=evidence_refs, notes=notes)

    def update_assumption(
        self,
        assumption_id: str,
        *,
        status: str | None = None,
        last_checked_at: str | None = None,
        invalidated_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return _question_meta.update_assumption(self, assumption_id=assumption_id, status=status, last_checked_at=last_checked_at, invalidated_at=invalidated_at, notes=notes)

    def get_assumption(self, assumption_id: str) -> dict[str, Any]:
        return _question_meta.get_assumption(self, assumption_id=assumption_id)

    def list_assumptions(self, question_id: str) -> list[dict[str, Any]]:
        return _question_meta.list_assumptions(self, question_id=question_id)

    def add_reference_class(
        self,
        *,
        question_id: str,
        name: str,
        inclusion_criteria: str,
        exclusion_criteria: str = "",
        base_rate: float | None = None,
        base_rate_uncertainty: float | None = None,
        source_refs: list[str] | None = None,
        check_cadence: str | None = None,
        notes: str | None = None,
        sample_size: int | None = None,
    ) -> dict[str, Any]:
        return _question_meta.add_reference_class(self, question_id=question_id, name=name, inclusion_criteria=inclusion_criteria, exclusion_criteria=exclusion_criteria, base_rate=base_rate, base_rate_uncertainty=base_rate_uncertainty, source_refs=source_refs, check_cadence=check_cadence, notes=notes, sample_size=sample_size)

    def delete_reference_class(self, reference_class_id: str) -> None:
        return _question_meta.delete_reference_class(self, reference_class_id=reference_class_id)

    def update_reference_class(
        self,
        reference_class_id: str,
        *,
        status: str | None = None,
        last_checked_at: str | None = None,
        invalidated_at: str | None = None,
        check_cadence: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        return _question_meta.update_reference_class(self, reference_class_id=reference_class_id, status=status, last_checked_at=last_checked_at, invalidated_at=invalidated_at, check_cadence=check_cadence, notes=notes)

    def get_reference_class(self, reference_class_id: str) -> dict[str, Any]:
        return _question_meta.get_reference_class(self, reference_class_id=reference_class_id)

    def list_reference_classes(self, question_id: str) -> list[dict[str, Any]]:
        return _question_meta.list_reference_classes(self, question_id=question_id)

    def set_snapshot_reference_class_refs(self, snapshot_id: str, refs: list[str]) -> list[str]:
        return _anchors.set_snapshot_reference_class_refs(self, snapshot_id, refs)

    def refresh_current_snapshot_saturation(self, question_id: str, *, snapshot_id: str | None = None) -> bool:
        return _anchors.refresh_current_snapshot_saturation(self, question_id, snapshot_id=snapshot_id)

    def relink_orphaned_anchors(self, *, question_ids: list[str] | None = None, apply: bool = False) -> dict[str, Any]:
        return _anchors.relink_orphaned_anchors(self, question_ids=question_ids, apply=apply)

    # ── crux evidence map ─────────────────────────────────────────────────────
    def add_crux(
        self,
        *,
        question_id: str,
        crux_variable: str,
        preferred_roles: list[str] | None = None,
        materiality: str = "medium",
        status: str = "missing",
        notes: str | None = None,
    ) -> dict[str, Any]:
        return _question_meta.add_crux(self, question_id=question_id, crux_variable=crux_variable, preferred_roles=preferred_roles, materiality=materiality, status=status, notes=notes)

    def get_crux(self, crux_id: str) -> dict[str, Any]:
        return _question_meta.get_crux(self, crux_id=crux_id)

    def list_cruxes(self, question_id: str) -> list[dict[str, Any]]:
        return _question_meta.list_cruxes(self, question_id=question_id)

    def set_crux_status(self, crux_id: str, status: str) -> dict[str, Any]:
        return _question_meta.set_crux_status(self, crux_id=crux_id, status=status)

    def promote_panel_cruxes(
        self,
        *,
        question_id: str,
        panel_run_id: str,
        estimates: list[dict[str, Any]] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return _question_meta.promote_panel_cruxes(self, question_id=question_id, panel_run_id=panel_run_id, estimates=estimates, dry_run=dry_run)

    def backfill_panel_cruxes(self, *, dry_run: bool = True) -> dict[str, Any]:
        return _question_meta.backfill_panel_cruxes(self, dry_run=dry_run)

    def crux_promotion_stats(self) -> dict[str, Any]:
        return _question_meta.crux_promotion_stats(self)

    def evidence_map(self, question_id: str) -> dict[str, Any]:
        return _evidence.evidence_map(self, question_id=question_id)

    def record_model_run(
        self,
        *,
        question_id: str,
        model_type: str,
        status: str = "success",
        inputs: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
        code_ref: str | None = None,
        artifact_paths: list[str] | None = None,
        model_version: str | None = None,
        prompt_version: str | None = None,
        data_version: str | None = None,
        evidence_cutoff: str | None = None,
        market_model_id: str | None = None,
    ) -> dict[str, Any]:
        return _model_scoring.record_model_run(self, question_id=question_id, model_type=model_type, status=status, inputs=inputs, parameters=parameters, output=output, diagnostics=diagnostics, code_ref=code_ref, artifact_paths=artifact_paths, model_version=model_version, prompt_version=prompt_version, data_version=data_version, evidence_cutoff=evidence_cutoff, market_model_id=market_model_id)

    def link_question_market_model(self, question_id: str, market_model_id: str) -> ForecastQuestion:
        return _model_scoring.link_question_market_model(self, question_id=question_id, market_model_id=market_model_id)

    def get_model_run(self, model_run_id: str) -> dict[str, Any]:
        return _model_scoring.get_model_run(self, model_run_id=model_run_id)

    def list_model_runs(self, question_id: str) -> list[dict[str, Any]]:
        return _model_scoring.list_model_runs(self, question_id=question_id)

    # ── R4 Living Models: score model runs at resolution ────────────────
    @staticmethod
    def _model_run_probability(output: dict[str, Any]) -> float | None:
        return _model_scoring._model_run_probability(output=output)

    @staticmethod
    def _model_run_numeric(output: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        return _model_scoring._model_run_numeric(output=output)

    def score_model_runs(
        self,
        question_id: str,
        outcome: Any,
        *,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        return _model_scoring.score_model_runs(self, question_id=question_id, outcome=outcome, now=now)

    def resolve_question(
        self,
        *,
        question_id: str,
        outcome: Any,
        resolution_source: str | None = None,
        resolution_source_snapshot_ref: str | None = None,
        resolver_type: str = "manual",
        resolution_status: str = "confirmed",
        criteria_satisfied: bool = True,
        confidence: float | None = None,
        confirmed_by: str | None = None,
        resolver_notes: str | None = None,
        correction_ref: str | None = None,
        trusted_policy_id: str | None = None,
        scoreable: bool = True,
        auto_score: bool = True,
    ) -> Resolution:
        return _resolutions.resolve_question(self, question_id=question_id, outcome=outcome, resolution_source=resolution_source, resolution_source_snapshot_ref=resolution_source_snapshot_ref, resolver_type=resolver_type, resolution_status=resolution_status, criteria_satisfied=criteria_satisfied, confidence=confidence, confirmed_by=confirmed_by, resolver_notes=resolver_notes, correction_ref=correction_ref, trusted_policy_id=trusted_policy_id, scoreable=scoreable, auto_score=auto_score)

    def get_resolution(self, resolution_id: str) -> Resolution:
        return _resolutions.get_resolution(self, resolution_id=resolution_id)

    def get_latest_resolution(
        self,
        question_id: str,
        *,
        confirmed_only: bool = False,
    ) -> Resolution | None:
        return _resolutions.get_latest_resolution(self, question_id=question_id, confirmed_only=confirmed_only)

    def score_question(self, question_id: str, *, force: bool = False) -> ScoreRecord:
        return _scoring.score_question(self, question_id=question_id, force=force)

    def get_current_score(self, question_id: str) -> ScoreRecord | None:
        return _scoring.get_current_score(self, question_id=question_id)

    def score_snapshot(self, forecast_id: str, *, force: bool = False) -> ScoreRecord:
        return _scoring.score_snapshot(self, forecast_id=forecast_id, force=force)

    def backfill_crps_scores(self, *, dry_run: bool = True) -> dict[str, Any]:
        return _scoring.backfill_crps_scores(self, dry_run=dry_run)

    def cohort_scoreboard(self) -> dict[str, Any]:
        return _scoring.cohort_scoreboard(self)

    def scores_audit(self) -> dict[str, Any]:
        return _scoring.scores_audit(self)

    def quarantine_artifact_scores(
        self, *, dry_run: bool = True, reasons: tuple[str, ...] = ("artifact_degenerate_import",)
    ) -> dict[str, Any]:
        return _scoring.quarantine_artifact_scores(self, dry_run=dry_run, reasons=reasons)

    def get_score(self, score_id: str) -> ScoreRecord:
        return _scoring.get_score(self, score_id=score_id)

    def list_scores(
        self,
        *,
        domain: str | None = None,
        forecast_origin: str | None = None,
        calibration_eligible: bool | None = None,
        horizon: str | None = None,
        bucket: str | None = None,
        include_invalidated: bool = False,
    ) -> list[ScoreRecord]:
        return _scoring.list_scores(self, domain=domain, forecast_origin=forecast_origin, calibration_eligible=calibration_eligible, horizon=horizon, bucket=bucket, include_invalidated=include_invalidated)

    def calibration_summary(
        self,
        *,
        domain: str | None = None,
        forecast_origin: str | None = None,
        horizon: str | None = None,
        calibration_eligible: bool | None = True,
    ) -> dict[str, Any]:
        return _scoring.calibration_summary(self, domain=domain, forecast_origin=forecast_origin, horizon=horizon, calibration_eligible=calibration_eligible)

    def _calibration_trend(
        self,
        points: list[dict[str, Any]],
        *,
        windows: tuple[int, ...] = (30, 90),
        now: str | None = None,
    ) -> dict[str, Any]:
        return _scoring._calibration_trend(self, points=points, windows=windows, now=now)

    # ------------------------------------------------------------------
    # Operator practice loop (R2) — score the HUMAN, not just the system.
    #
    # The system already scores its own forecasts and learns from the Brier;
    # the goal of the desk is also to make the OPERATOR a superforecaster, so we
    # record the operator's own numbers (practice or drill), score them on
    # resolution, and surface an operator calibration curve + a vs-system pairing.
    # These tables are NOT forecast-producing (the operator's practice number is
    # never a committed forecast), so they are deliberately kept OUT of the
    # forecast-fabrication write gate — but the tool/CLI callers still open an
    # allow_ledger_writes context for hygiene.
    # ------------------------------------------------------------------

    def _row_to_operator_estimate(self, row: sqlite3.Row) -> dict[str, Any]:
        raw_outcome = row["resolved_outcome"]
        return {
            "id": row["id"],
            "question_id": row["question_id"],
            "probability_or_distribution": json_loads(row["probability_or_distribution"], None),
            "note": row["note"],
            "context": row["context"],
            "created_at": row["created_at"],
            "resolved_outcome": json_loads(raw_outcome, None) if raw_outcome is not None else None,
            "brier": row["brier"],
            "scored_at": row["scored_at"],
        }

    def get_operator_estimate(self, estimate_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM operator_estimates WHERE id = ?", (estimate_id,)
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"operator estimate not found: {estimate_id}")
        return self._row_to_operator_estimate(row)

    def record_operator_estimate(
        self,
        question_id: str,
        probability_or_distribution: Any,
        *,
        note: str | None = None,
        context: str = "practice",
    ) -> dict[str, Any]:
        """Record the OPERATOR's own forecast for ``question_id``.

        ``probability_or_distribution`` is a scalar in [0, 1] for a binary
        estimate, or a distribution dict (stored as JSON, scored later only if
        binary). ``context`` is 'practice' (scored when the question resolves)
        or 'drill' (a replay of an already-resolved question). Validates the
        probability range; the question must exist."""

        self.get_question(question_id)
        if context not in {"practice", "drill"}:
            raise ValidationError("operator estimate context must be 'practice' or 'drill'")
        payload = probability_or_distribution
        if isinstance(payload, bool):
            raise ValidationError("operator probability must be a number in [0, 1], not a boolean")
        if isinstance(payload, (int, float)):
            payload = float(payload)
            if not (0.0 <= payload <= 1.0):
                raise ValidationError("operator probability must be in [0, 1]")
        elif isinstance(payload, dict):
            if not payload:
                raise ValidationError("operator distribution must not be empty")
            for key, value in payload.items():
                try:
                    float(value)
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"operator distribution value for {key!r} is not numeric"
                    )
        else:
            raise ValidationError(
                "operator estimate must be a probability in [0, 1] or a distribution dict"
            )
        note = (note or "").strip() or None
        estimate_id = f"oe_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO operator_estimates (
                    id, question_id, probability_or_distribution, note, context,
                    created_at, resolved_outcome, brier, scored_at
                )
                VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                """,
                (
                    estimate_id,
                    question_id,
                    json_dumps(payload),
                    note,
                    context,
                    now,
                ),
            )
        return self.get_operator_estimate(estimate_id)

    def list_operator_estimates(
        self,
        question_id: str | None = None,
        *,
        unscored_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if unscored_only:
            clauses.append("scored_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM operator_estimates {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._row_to_operator_estimate(row) for row in rows]

    def score_operator_estimates(
        self,
        question_id: str,
        outcome: Any,
        *,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        """Score the operator's UNSCORED estimates for ``question_id`` against a
        confirmed ``outcome``. Binary estimates get a Brier score; non-binary
        estimates are marked scored with brier=None + a skip note (kept out of
        the calibration curve). Called best-effort from ``resolve_question``."""

        question = self.get_question(question_id)
        outcome_space = question.outcome_space
        now = now or utc_now_iso()
        outcome_json = json_dumps(outcome)
        scored: list[dict[str, Any]] = []
        for estimate in self.list_operator_estimates(question_id, unscored_only=True):
            payload = estimate["probability_or_distribution"]
            brier: float | None = None
            skip_reason: str | None = None
            if outcome_space.type == "binary" and isinstance(payload, (int, float)):
                try:
                    brier = self._brier_score(payload, outcome, outcome_space)
                except Exception:
                    brier = None
                    skip_reason = "unscoreable binary outcome"
            else:
                skip_reason = (
                    f"non-binary estimate ({outcome_space.type}) — operator scoring is binary-only"
                )
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE operator_estimates
                    SET resolved_outcome = ?, brier = ?, scored_at = ?
                    WHERE id = ?
                    """,
                    (outcome_json, brier, now, estimate["id"]),
                )
            row = self.get_operator_estimate(estimate["id"])
            if skip_reason:
                row["skip_reason"] = skip_reason
            scored.append(row)
        return scored

    # Labels a corpus DRILL outcome may carry (ForecastBench resolves to yes/no).
    _CORPUS_DRILL_YES_LABELS = frozenset({"yes", "y", "true", "1", "occurred", "success"})
    _CORPUS_DRILL_NO_LABELS = frozenset({"no", "n", "false", "0", "not_occurred", "failed"})

    def record_and_score_corpus_drill(
        self,
        corpus_ref: str,
        probability: Any,
        outcome: Any,
        *,
        note: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Record + INSTANTLY score an operator drill against a CORPUS question.

        Unlike :meth:`record_operator_estimate`, ``corpus_ref`` (e.g.
        ``'fb:<case-id>'``) is a reference to a question that lives OUTSIDE the
        desk's ``forecast_questions`` table (a ForecastBench replay case). It is
        stored verbatim as the estimate's ``question_id`` so corpus drills flow
        into :meth:`operator_calibration_summary` alongside desk drills, and the
        ``operator_estimates -> forecast_questions`` FK is bypassed FOR THIS INSERT
        ONLY (the ref has, by construction, no desk row to point at).

        The estimate is a binary probability in [0, 1] and ``outcome`` is the
        KNOWN binary label ('yes'/'no'); the Brier is computed on the spot and the
        row is written already-scored (``context='drill'``). Raises
        :class:`ValidationError` on a bad ref / probability / outcome so the
        interactive flow fails politely.
        """

        ref = str(corpus_ref or "").strip()
        if not ref or ":" not in ref:
            raise ValidationError(
                "corpus drill reference must look like 'fb:<case-id>'"
            )
        if isinstance(probability, bool):
            raise ValidationError("operator probability must be a number in [0, 1], not a boolean")
        if not isinstance(probability, (int, float)):
            raise ValidationError("corpus drill estimate must be a probability in [0, 1]")
        prob = float(probability)
        if not (0.0 <= prob <= 1.0):
            raise ValidationError("operator probability must be in [0, 1]")
        outcome_label = str(outcome).strip().lower()
        if outcome_label in self._CORPUS_DRILL_YES_LABELS:
            observed = 1.0
        elif outcome_label in self._CORPUS_DRILL_NO_LABELS:
            observed = 0.0
        else:
            raise ValidationError(
                f"corpus drill outcome must be a binary yes/no label, got {outcome!r}"
            )
        brier = (prob - observed) ** 2

        note = (note or "").strip() or None
        estimate_id = f"oe_{uuid.uuid4().hex[:12]}"
        now = now or utc_now_iso()
        with self._connect() as conn:
            # The corpus ref has no forecast_questions row, so the FK on
            # operator_estimates.question_id must not fire for THIS insert. The
            # PRAGMA is per-connection and each _connect() re-enables it, so this
            # never weakens FK enforcement anywhere else.
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute(
                """
                INSERT INTO operator_estimates (
                    id, question_id, probability_or_distribution, note, context,
                    created_at, resolved_outcome, brier, scored_at
                )
                VALUES (?, ?, ?, ?, 'drill', ?, ?, ?, ?)
                """,
                (
                    estimate_id,
                    ref,
                    json_dumps(prob),
                    note,
                    now,
                    json_dumps(outcome_label),
                    brier,
                    now,
                ),
            )
        return self.get_operator_estimate(estimate_id)

    def _operator_binary_observed(
        self, resolved_outcome: Any, outcome_space: OutcomeSpace
    ) -> float | None:
        return _scoring._operator_binary_observed(self, resolved_outcome=resolved_outcome, outcome_space=outcome_space)

    def _operator_vs_system(
        self, estimates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        return _scoring._operator_vs_system(self, estimates=estimates)

    def operator_calibration_summary(
        self, window_days: int | None = None
    ) -> dict[str, Any]:
        return _scoring.operator_calibration_summary(self, window_days=window_days)

    def create_postmortem(
        self,
        *,
        question_id: str,
        summary: str = "",
        what_happened: str = "",
        what_was_expected: str = "",
        missed_evidence: str = "",
        overweighted_evidence: str = "",
        base_rate_error: str = "",
        inside_view_error: str = "",
        resolution_error: str = "",
        lesson: str = "",
        calibration_adjustment: dict[str, Any] | None = None,
        failure_class: str | None = None,
    ) -> dict[str, Any]:
        return _resolutions.create_postmortem(self, question_id=question_id, summary=summary, what_happened=what_happened, what_was_expected=what_was_expected, missed_evidence=missed_evidence, overweighted_evidence=overweighted_evidence, base_rate_error=base_rate_error, inside_view_error=inside_view_error, resolution_error=resolution_error, lesson=lesson, calibration_adjustment=calibration_adjustment, failure_class=failure_class)

    def _predictive_central(self, payload: Any) -> float | None:
        return _resolutions._predictive_central(self, payload=payload)

    def create_continuous_miss_postmortem_stubs(
        self,
        *,
        question_ids: list[str] | None = None,
        dry_run: bool = True,
        min_crps: float = 0.0,
    ) -> dict[str, Any]:
        return _resolutions.create_continuous_miss_postmortem_stubs(self, question_ids=question_ids, dry_run=dry_run, min_crps=min_crps)

    def get_postmortem(self, postmortem_id: str) -> dict[str, Any]:
        return _resolutions.get_postmortem(self, postmortem_id=postmortem_id)

    def list_postmortems(
        self,
        question_id: str | None = None,
        *,
        include_invalidated: bool = False,
    ) -> list[dict[str, Any]]:
        return _resolutions.list_postmortems(self, question_id=question_id, include_invalidated=include_invalidated)

    # ── Forecast panel ─────────────────────────────────────────────────────

    def record_panel_run(
        self,
        *,
        question_id: str,
        estimates: list[dict[str, Any]],
        aggregation_method: str = "trimmed_geomean_odds",
        trim: int = 1,
        snapshot_id: str | None = None,
        triggered_by: str | None = None,
        perspectives: list[str] | None = None,
        judge: Any = None,
        final_probability: float | None = None,
        final_source: str | None = None,
        research_rounds: int = 0,
        supervisor_evidence: list[dict[str, Any]] | None = None,
        delphi_rounds: int = 0,
        delphi_audit: dict[str, Any] | None = None,
        supervisor_search_enabled: bool = False,
        market_anchor: dict[str, Any] | None = None,
        pseudo_diversity_caveat: str | None = None,
        panel_resolution_note: str | None = None,
        blind_pool: float | None = None,
        reconciled_pool: float | None = None,
        pool_shrinkage: dict[str, Any] | None = None,
        specialist_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _panels.record_panel_run(self, question_id=question_id, estimates=estimates, aggregation_method=aggregation_method, trim=trim, snapshot_id=snapshot_id, triggered_by=triggered_by, perspectives=perspectives, judge=judge, final_probability=final_probability, final_source=final_source, research_rounds=research_rounds, supervisor_evidence=supervisor_evidence, delphi_rounds=delphi_rounds, delphi_audit=delphi_audit, supervisor_search_enabled=supervisor_search_enabled, market_anchor=market_anchor, pseudo_diversity_caveat=pseudo_diversity_caveat, panel_resolution_note=panel_resolution_note, blind_pool=blind_pool, reconciled_pool=reconciled_pool, pool_shrinkage=pool_shrinkage, specialist_summary=specialist_summary)

    def get_panel_run(self, run_id: str) -> dict[str, Any]:
        return _panels.get_panel_run(self, run_id=run_id)

    # ── Deviation bets (UPGRADE 2 — the deviation ledger) ──────────────────────

    def record_deviation_bet(self, **kwargs: Any) -> dict[str, Any]:
        return _deviation_bets.record_deviation_bet(self, **kwargs)

    def get_deviation_bet(self, bet_id: str) -> dict[str, Any]:
        return _deviation_bets.get_deviation_bet(self, bet_id)

    def list_deviation_bets(
        self,
        question_id: str | None = None,
        *,
        only_open: bool = False,
        only_scored: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _deviation_bets.list_deviation_bets(self, question_id, only_open=only_open, only_scored=only_scored, limit=limit)

    def score_deviation_bets(
        self,
        question_id: str,
        outcome: Any,
        *,
        resolution_id: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        return _deviation_bets.score_deviation_bets(self, question_id, outcome, resolution_id=resolution_id, now=now)

    def deviation_bet_edge_report(self) -> dict[str, Any]:
        return _deviation_bets.deviation_bet_edge_report(self)

    def list_panel_runs(
        self,
        question_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _panels.list_panel_runs(self, question_id=question_id, limit=limit)

    def attach_panel_to_snapshot(self, panel_run_id: str, snapshot_id: str) -> dict[str, Any]:
        return _panels.attach_panel_to_snapshot(self, panel_run_id=panel_run_id, snapshot_id=snapshot_id)

    def _panel_run_dict(
        self,
        row: sqlite3.Row,
        estimates_rows: list[sqlite3.Row],
    ) -> dict[str, Any]:
        return _panels._panel_run_dict(self, row=row, estimates_rows=estimates_rows)

    def _panel_estimate_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _panels._panel_estimate_dict(self, row=row)

    # ── Component track record (measured "weight by track record") ──────
    def component_track_record(
        self,
        *,
        forecast_origin: str | None = "live",
        min_count: int | None = None,
        shrink_n0: float | None = None,
        edge_scale: float | None = None,
    ) -> list[dict[str, Any]]:
        return _panels.component_track_record(self, forecast_origin=forecast_origin, min_count=min_count, shrink_n0=shrink_n0, edge_scale=edge_scale)

    def recommended_component_weights(
        self,
        *,
        kind: str = "panel",
        forecast_origin: str | None = "live",
        min_count: int | None = None,
    ) -> dict[str, float]:
        return _panels.recommended_component_weights(self, kind=kind, forecast_origin=forecast_origin, min_count=min_count)

    # ── Per-panelist-model track record (quorum weighting) ──────────────
    # Default sample gate for a MODEL's recommended weight. Distinct from the
    # component gate (DEFAULT_MIN_COUNT=5): a per-model quorum weight is applied
    # SILENTLY at dispatch (when the config flag is on), so it needs a stiffer
    # bar — a model must clear this many resolved binaries before its measured
    # skill moves its weight off 1.0.
    MODEL_WEIGHT_MIN_SAMPLE = 10

    def model_track_record(
        self,
        *,
        min_count: int | None = None,
        shrink_n0: float | None = None,
        edge_scale: float | None = None,
    ) -> list[dict[str, Any]]:
        return _panels.model_track_record(self, min_count=min_count, shrink_n0=shrink_n0, edge_scale=edge_scale)

    def recommended_model_weights(
        self,
        *,
        min_sample: int | None = None,
    ) -> dict[str, float]:
        return _panels.recommended_model_weights(self, min_sample=min_sample)

    # ── R4 Living Models: per-model skill from scored model_runs ─────────
    # Uninformative binary reference: a p=0.5 forecast scores Brier 0.25, so a
    # model's edge over the coin flip is 0.25 - its Brier. Any informative model
    # beats it; the shrink+clip in forecasting.track_record keeps a thin record
    # near 1.0 (identity on cold start).
    _MODEL_SKILL_BASELINE_BRIER = 0.25

    def model_skill(
        self,
        *,
        model_type: str | None = None,
        market_model_id: str | None = None,
        min_count: int | None = None,
        shrink_n0: float | None = None,
        edge_scale: float | None = None,
    ) -> dict[str, Any]:
        return _model_scoring.model_skill(self, model_type=model_type, market_model_id=market_model_id, min_count=min_count, shrink_n0=shrink_n0, edge_scale=edge_scale)

    # ── Analyst notes (time-series desk write-ups) ──────────────────────
    def add_analyst_note(
        self,
        *,
        question_id: str,
        body: str,
        kind: str = "brief",
        headline: str = "",
        how_it_feels: str = "",
        how_it_thinks: str = "",
        looking_for: str = "",
        be_aware: str = "",
        as_of: str | None = None,
        forecast_id: str | None = None,
        resolution_id: str | None = None,
        stance: str | None = None,
        verdict: str | None = None,
        probability_at_write: Any | None = None,
        confidence_at_write: float | None = None,
        agent_model: str | None = None,
        prompt_version: str | None = None,
        forecasting_protocol_version: str | None = None,
        generator: str = "llm",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _question_meta.add_analyst_note(self, question_id=question_id, body=body, kind=kind, headline=headline, how_it_feels=how_it_feels, how_it_thinks=how_it_thinks, looking_for=looking_for, be_aware=be_aware, as_of=as_of, forecast_id=forecast_id, resolution_id=resolution_id, stance=stance, verdict=verdict, probability_at_write=probability_at_write, confidence_at_write=confidence_at_write, agent_model=agent_model, prompt_version=prompt_version, forecasting_protocol_version=forecasting_protocol_version, generator=generator, metadata=metadata)

    def get_analyst_note(self, note_id: str) -> dict[str, Any]:
        return _question_meta.get_analyst_note(self, note_id=note_id)

    def list_analyst_notes(
        self,
        question_id: str,
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return _question_meta.list_analyst_notes(self, question_id=question_id, kind=kind, limit=limit)

    def latest_analyst_note(
        self,
        question_id: str,
        *,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        return _question_meta.latest_analyst_note(self, question_id=question_id, kind=kind)

    def _analyst_note_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _question_meta._analyst_note_to_dict(self, row=row)

    # ── Batched per-question reads (desk-payload N+1 collapse) ───────────────
    # The forecasts-workspace payload (forecasting.dashboard.build_workspace_payload)
    # used to run ~5 SEPARATE ledger queries PER active question — list_snapshots,
    # list_evidence, list_panel_runs, get_latest_resolution, list_analyst_notes —
    # i.e. ~5×N connects+executes for N≈226 questions (~1.7s, the slow "starting
    # forecast desk…"). These helpers fetch the SAME data for a set of question ids
    # in ONE query each (WHERE question_id IN (…)), returning a dict keyed by
    # question_id with IDENTICAL per-question ordering/contents to the singular
    # methods. The IN-list is chunked under SQLite's ~999-variable limit (we have
    # ~226, so a single chunk, but the guard keeps it correct for any book size).
    # NOTE: unlike list_snapshots/list_evidence these skip the per-question
    # get_question() existence check — callers already hold the question rows.

    @staticmethod
    def _chunk_ids(question_ids: list[str], size: int = 900) -> list[list[str]]:
        seen: set[str] = set()
        ordered: list[str] = []
        for qid in question_ids:
            if qid not in seen:
                seen.add(qid)
                ordered.append(qid)
        return [ordered[i : i + size] for i in range(0, len(ordered), size)] or [[]]

    def snapshots_by_question(self, question_ids: list[str]) -> dict[str, list[ForecastSnapshot]]:
        return _snapshots.snapshots_by_question(self, question_ids=question_ids)

    def evidence_by_question(self, question_ids: list[str]) -> dict[str, list[EvidenceItem]]:
        return _evidence.evidence_by_question(self, question_ids=question_ids)

    def latest_panel_run_by_question(self, question_ids: list[str]) -> dict[str, dict[str, Any]]:
        return _panels.latest_panel_run_by_question(self, question_ids=question_ids)

    def latest_resolution_by_question(self, question_ids: list[str]) -> dict[str, Resolution]:
        return _resolutions.latest_resolution_by_question(self, question_ids=question_ids)

    def analyst_notes_by_question(self, question_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return _question_meta.analyst_notes_by_question(self, question_ids=question_ids)

    def active_watched_source_counts(self, question_ids: list[str]) -> dict[str, int]:
        return _watches.active_watched_source_counts(self, question_ids=question_ids)

    def active_reference_class_counts(self, question_ids: list[str]) -> dict[str, int]:
        return _question_meta.active_reference_class_counts(self, question_ids=question_ids)

    def closing_question_ids(self, *, now: str | None = None) -> set[str]:
        """Active question ids that are "closing soon" — i.e. would carry a
        close-review reason (close_time_passed / resolution_check_due) from
        review_questions(stale=False). With stale=False the only close-review
        reasons are close_time<=now OR resolution_time<=now (the
        close_time_within_*d reason requires stale=True), so this is a single
        cheap filter — no per-question snapshot/evidence walk. Mirrors
        is_close_review_reason's semantics for the desk's closing-soon count."""
        now_iso = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM forecast_questions "
                "WHERE status = 'active' "
                "AND ((close_time IS NOT NULL AND close_time <= ?) "
                "  OR (resolution_time IS NOT NULL AND resolution_time <= ?))",
                (now_iso, now_iso),
            ).fetchall()
        return {row["id"] for row in rows}

    # ── Market Models ────────────────────────────────────────────────────────
    # A Market Model is an agentic quant-research artifact: a re-runnable spec
    # (which series + which computation), an append-only series of versioned
    # presentations, a chat thread, and the data series it imported. CRUD mirrors
    # the analyst-note pattern (append-only, JSON columns, row→dict helpers).

    def create_market_model(
        self,
        *,
        title: str,
        question: str,
        depth: str = "standard",
        spec: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent_model: str | None = None,
        prompt_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _market_models.create_market_model(self, title=title, question=question, depth=depth, spec=spec, tags=tags, agent_model=agent_model, prompt_version=prompt_version, metadata=metadata)

    def update_market_model_spec(self, model_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        return _market_models.update_market_model_spec(self, model_id=model_id, spec=spec)

    def get_market_model(self, model_id: str) -> dict[str, Any]:
        return _market_models.get_market_model(self, model_id=model_id)

    def list_market_models(self, *, status: str | None = "active", limit: int | None = None) -> list[dict[str, Any]]:
        # Join the latest presentation's build status (complete/partial/failed) so
        # the list can show a failure/ready icon without an N+1 per-row fetch.
        return _market_models.list_market_models(self, status=status, limit=limit)

    def delete_market_model(self, model_id: str) -> bool:
        return _market_models.delete_market_model(self, model_id=model_id)

    def add_market_presentation(
        self,
        *,
        model_id: str,
        presentation: dict[str, Any],
        status: str = "complete",
        summary: str = "",
        as_of_analysis: str | None = None,
        as_of_data: str | None = None,
        refine_instruction: str | None = None,
        diagnostics: dict[str, Any] | None = None,
        agent_model: str | None = None,
        prompt_version: str | None = None,
    ) -> dict[str, Any]:
        return _market_models.add_market_presentation(self, model_id=model_id, presentation=presentation, status=status, summary=summary, as_of_analysis=as_of_analysis, as_of_data=as_of_data, refine_instruction=refine_instruction, diagnostics=diagnostics, agent_model=agent_model, prompt_version=prompt_version)

    def get_market_presentation(self, model_id: str, *, version: int | None = None) -> dict[str, Any]:
        return _market_models.get_market_presentation(self, model_id=model_id, version=version)

    def list_market_presentations(self, model_id: str) -> list[dict[str, Any]]:
        return _market_models.list_market_presentations(self, model_id=model_id)

    def add_market_message(
        self, *, model_id: str, role: str, content: str, version_ref: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _market_models.add_market_message(self, model_id=model_id, role=role, content=content, version_ref=version_ref, metadata=metadata)

    def list_market_messages(self, model_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        return _market_models.list_market_messages(self, model_id=model_id, limit=limit)

    def add_market_data_series(
        self, *, model_id: str, name: str, points: list[Any], source_type: str | None = None,
        source: str | None = None, unit: str | None = None, as_of: str | None = None,
        evidence_refs: list[str] | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _market_models.add_market_data_series(self, model_id=model_id, name=name, points=points, source_type=source_type, source=source, unit=unit, as_of=as_of, evidence_refs=evidence_refs, metadata=metadata)

    def list_market_data_series(self, model_id: str) -> list[dict[str, Any]]:
        return _market_models.list_market_data_series(self, model_id=model_id)

    def replace_market_data_series(self, model_id: str, series: list[dict[str, Any]]) -> None:
        return _market_models.replace_market_data_series(self, model_id=model_id, series=series)

    def export_market_model(self, model_id: str, *, fmt: str = "json") -> dict[str, Any]:
        return _market_models.export_market_model(self, model_id=model_id, fmt=fmt)

    def _market_model_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _market_models._market_model_to_dict(self, row=row)

    def _market_presentation_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _market_models._market_presentation_to_dict(self, row=row)

    def _market_message_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _market_models._market_message_to_dict(self, row=row)

    def _market_series_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _market_models._market_series_to_dict(self, row=row)

    def create_calibration_lesson(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        lesson: str,
        confidence: float | None = None,
        recommended_adjustment: dict[str, Any] | None = None,
        source_postmortem_refs: list[str] | None = None,
        source_score_record_refs: list[str] | None = None,
        status: str = "tentative",
        supersedes_lesson_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _lessons.create_calibration_lesson(self, scope_type=scope_type, scope_ref=scope_ref, lesson=lesson, confidence=confidence, recommended_adjustment=recommended_adjustment, source_postmortem_refs=source_postmortem_refs, source_score_record_refs=source_score_record_refs, status=status, supersedes_lesson_id=supersedes_lesson_id, metadata=metadata)

    def get_calibration_lesson(self, lesson_id: str) -> dict[str, Any]:
        return _lessons.get_calibration_lesson(self, lesson_id=lesson_id)

    def update_calibration_lesson(
        self,
        lesson_id: str,
        *,
        status: str | None = None,
        confidence: float | None = None,
        recommended_adjustment: dict[str, Any] | None = None,
        supersedes_lesson_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _lessons.update_calibration_lesson(self, lesson_id=lesson_id, status=status, confidence=confidence, recommended_adjustment=recommended_adjustment, supersedes_lesson_id=supersedes_lesson_id, metadata=metadata)

    def apply_lesson(self, lesson_id: str, *, severity: str = "warn") -> dict[str, Any]:
        return _lessons.apply_lesson(self, lesson_id=lesson_id, severity=severity)

    def list_calibration_lessons(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        return _lessons.list_calibration_lessons(self, scope_type=scope_type, scope_ref=scope_ref, active_only=active_only)

    # ── Triage rubrics + labels (information triage) ──────────────────────────
    # The desk-authored "interesting vs merely relevant" taste (rubrics) plus a
    # STAGING surface for the cheap auto-labeler's three-way calls (labels), kept
    # OFF the evidence table. The labeler itself lives in forecasting/triage.py;
    # the held-out trust gate scores auto_label vs expert_label.


    def _row_to_triage_rubric(self, row: sqlite3.Row) -> dict[str, Any]:
        return _evidence._row_to_triage_rubric(self, row=row)

    def _row_to_triage_label(self, row: sqlite3.Row) -> dict[str, Any]:
        return _evidence._row_to_triage_label(self, row=row)

    def set_triage_rubric(
        self,
        *,
        scope_type: str,
        scope_ref: str | None = None,
        interesting_criteria: str,
        uninteresting_criteria: str = "",
        irrelevant_criteria: str = "",
        examples: list[Any] | None = None,
        notes: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _evidence.set_triage_rubric(self, scope_type=scope_type, scope_ref=scope_ref, interesting_criteria=interesting_criteria, uninteresting_criteria=uninteresting_criteria, irrelevant_criteria=irrelevant_criteria, examples=examples, notes=notes, metadata=metadata)

    def get_triage_rubric(self, rubric_id: str) -> dict[str, Any] | None:
        return _evidence.get_triage_rubric(self, rubric_id=rubric_id)

    def list_triage_rubrics(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        active_only: bool = True,
    ) -> list[dict[str, Any]]:
        return _evidence.list_triage_rubrics(self, scope_type=scope_type, scope_ref=scope_ref, active_only=active_only)

    def record_triage_labels(
        self, *, question_id: str | None = None, verdicts: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        return _evidence.record_triage_labels(self, question_id=question_id, verdicts=verdicts)

    def get_triage_label(self, label_id: str) -> dict[str, Any] | None:
        return _evidence.get_triage_label(self, label_id=label_id)

    def list_triage_labels(
        self,
        *,
        question_id: str | None = None,
        label_source: str | None = None,
        contested: bool | None = None,
        adjudicated: bool | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        return _evidence.list_triage_labels(self, question_id=question_id, label_source=label_source, contested=contested, adjudicated=adjudicated, limit=limit)

    def update_triage_label(
        self,
        label_id: str,
        *,
        expert_label: str | None = None,
        triage_label: str | None = None,
        label_source: str | None = None,
        contested: bool | None = None,
        alert_id: str | None = None,
        adjudicated_at: str | None = None,
        verdict: str | None = None,
        materiality: str | None = None,
    ) -> dict[str, Any] | None:
        return _evidence.update_triage_label(self, label_id=label_id, expert_label=expert_label, triage_label=triage_label, label_source=label_source, contested=contested, alert_id=alert_id, adjudicated_at=adjudicated_at, verdict=verdict, materiality=materiality)

    # ── Desk key/value state ─────────────────────────────────────────────────
    def get_desk_state(self, key: str) -> str | None:
        return _question_meta.get_desk_state(self, key=key)

    def set_desk_state(self, key: str, value: str | None, *, now: str | None = None) -> None:
        return _question_meta.set_desk_state(self, key=key, value=value, now=now)

    def transition_desk_state(
        self, key: str, new_value: str | None, *, now: str | None = None
    ) -> tuple[bool, str | None]:
        return _question_meta.transition_desk_state(self, key=key, new_value=new_value, now=now)

    def _has_open_alert(self, *, reason: str, scope_type: str, scope_ref: str) -> bool:
        return _alerts._has_open_alert(self, reason=reason, scope_type=scope_type, scope_ref=scope_ref)

    def enqueue_saturation_alert(
        self,
        question_id: str,
        saturation: Any,
        *,
        threshold: float | None = None,
    ) -> "AlertEvent | None":
        return _alerts.enqueue_saturation_alert(self, question_id=question_id, saturation=saturation, threshold=threshold)

    def sweep_saturation_alerts(
        self,
        *,
        threshold: float | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return _alerts.sweep_saturation_alerts(self, threshold=threshold, limit=limit)

    def sweep_cadence_alerts(self, *, limit: int = 500) -> dict[str, Any]:
        return _alerts.sweep_cadence_alerts(self, limit=limit)


    def check_triage_gate_graduation(
        self,
        *,
        threshold: float = 0.8,
        min_sample: int = 20,
        demote_margin: float = 0.05,
        now: str | None = None,
    ) -> dict[str, Any] | None:
        return _evidence.check_triage_gate_graduation(self, threshold=threshold, min_sample=min_sample, demote_margin=demote_margin, now=now)

    # ── Signed calibration-bias loop ─────────────────────────────────────────
    # Measure whether committed binary forecasts run systematically over- or
    # under-confident (the SIGNED companion to the unsigned ECE in
    # ``calibration_summary``) and, optionally, distil that into a calibration
    # lesson. Every gate here exists to keep the loop from teaching the model to
    # over-bias; the math lives in :mod:`forecasting.calibration_bias`.

    _BIAS_LESSON_SOURCE = "calibration_bias"

    def _bias_observations(
        self,
        *,
        domain: str | None,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        forecast_origin: str | None = "live",
        now: str | None = None,
    ) -> list[Any]:
        return _scoring._bias_observations(self, domain=domain, since=since, recency_halflife_days=recency_halflife_days, forecast_origin=forecast_origin, now=now)

    def derive_extremize_alpha(
        self,
        question: Any,
        *,
        forecast_origin: str | None = "live",
    ) -> float:
        """Derive a per-scope terminal Platt slope from RESOLVED calibration data.

        Reuses the VALIDATED extremization safety gate (AIA P2.3,
        :func:`forecasting.calibration_bias.extremization_alpha_gate`): it proposes
        the theory-grounded variance-matching slope
        :data:`forecasting.bayes_toolkit.PLATT_ALPHA_VARIANCE_MATCH` (``sqrt(3)``)
        and PERMITS it only when the question's domain is measurably
        under-confident on its leaned side with enough effective sample; otherwise
        the gate forces the slope back to ``1.0``. Invents NO new statistic — it is
        the same help/hurt gate already unit-tested and used to make activating √3
        Platt safe.

        FAIL-SAFE COLD START: any thin/empty scope (a non-binary question, or a
        domain without enough resolved binaries) or any error returns ``1.0`` (the
        identity — no extremization). This is data-layer only (the ledger already
        depends on ``calibration_bias``); the caller decides whether to consult it.
        """

        try:
            from forecasting.bayes_toolkit import PLATT_ALPHA_VARIANCE_MATCH
            from forecasting.calibration_bias import extremization_alpha_gate

            observations = self._bias_observations(
                domain=getattr(question, "domain", None),
                forecast_origin=forecast_origin,
            )
            verdict = extremization_alpha_gate(PLATT_ALPHA_VARIANCE_MATCH, observations)
            allowed = verdict.get("allowed_alpha", 1.0)
            return float(allowed) if allowed else 1.0
        except Exception:  # noqa: BLE001 — derivation is best-effort; identity on any failure
            return 1.0

    # ── Hierarchical Platt calibration (BLF A4) ──────────────────────────────
    # The terminal calibration gains per-cohort intercept offsets delta_s over the
    # scoreboard strata: q = sigma(a*logit(p) + b + delta_s). The fit lives in
    # ``forecasting.hierarchical_calibration``; here is the READ-ONLY ledger glue
    # (row gather + fit + held-out validation) and the DEFAULT-OFF activation
    # derivation that mirrors ``derive_extremize_alpha``.

    _HIER_CALIBRATION_FLAG = "FORECAST_HIERARCHICAL_CALIBRATION"

    def hierarchical_calibration_rows(
        self,
        *,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        split_by_venue: bool = False,
        now: str | None = None,
    ) -> list[Any]:
        return _scoring.hierarchical_calibration_rows(
            self,
            since=since,
            recency_halflife_days=recency_halflife_days,
            split_by_venue=split_by_venue,
            now=now,
        )

    def fit_hierarchical_calibration(
        self,
        *,
        min_cohort_n: int | None = None,
        split_by_venue: bool = False,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        now: str | None = None,
    ) -> Any | None:
        """Fit the hierarchical Platt model on resolved rows, or ``None`` if empty.

        READ-ONLY. Gathers cohort-tagged resolved rows and fits ``(a, b,
        {delta_s})`` with LOO-CV ridge selection. Returns the
        :class:`~forecasting.hierarchical_calibration.HierarchicalPlattModel` (its
        ``to_payload`` is JSON-ready) or ``None`` when there are no resolved rows."""

        from forecasting.hierarchical_calibration import (
            DEFAULT_MIN_COHORT_N,
            fit_hierarchical_platt,
        )

        rows = self.hierarchical_calibration_rows(
            since=since,
            recency_halflife_days=recency_halflife_days,
            split_by_venue=split_by_venue,
            now=now,
        )
        if not rows:
            return None
        return fit_hierarchical_platt(
            rows,
            min_cohort_n=DEFAULT_MIN_COHORT_N if min_cohort_n is None else int(min_cohort_n),
        )

    def validate_hierarchical_calibration(
        self,
        *,
        min_cohort_n: int | None = None,
        folds: int = 5,
        split_by_venue: bool = False,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        """Held-out per-cohort Brier — global vs hierarchical — on resolved rows.

        READ-ONLY. This is the operator's flip evidence: the numbers that decide
        whether to activate hierarchical mode. Mirrors the sweep-then-activate
        discipline of the sqrt(3) slope."""

        from forecasting.hierarchical_calibration import (
            DEFAULT_MIN_COHORT_N,
            validate_hierarchical_calibration as _validate,
        )

        rows = self.hierarchical_calibration_rows(
            since=since,
            recency_halflife_days=recency_halflife_days,
            split_by_venue=split_by_venue,
            now=now,
        )
        return _validate(
            rows,
            min_cohort_n=DEFAULT_MIN_COHORT_N if min_cohort_n is None else int(min_cohort_n),
            folds=folds,
        )

    def derive_cohort_calibration(
        self,
        question: Any,
        *,
        forecast_origin: str | None = "live",
        activated: bool | None = None,
    ) -> dict[str, Any]:
        """Per-question terminal-calibration params — DEFAULT-OFF hierarchical Platt.

        Returns ``{alpha, platt_d, cohort, delta_s, intercept_b, ...}`` for the
        question's scoreboard cohort. ``alpha``/``platt_d`` feed the terminal
        calibration as ``platt_scale(p, alpha, d=platt_d)`` (the intercept ``b +
        delta_s`` rides the ``d`` bias term as ``exp(b + delta_s)``).

        ACTIVATION mirrors the sqrt(3) precedent: unless the operator flips
        ``FORECAST_HIERARCHICAL_CALIBRATION`` on (or ``activated=True`` is passed),
        this returns the IDENTITY (``alpha=1, platt_d=1`` — a strict no-op, so the
        commit is byte-identical to today). When active it fits the model, resolves
        the cohort, and — crucially — routes the fitted slope ``a`` through the
        UNCHANGED P2.3 extremization safety gate: an ``a>1`` on a wrong-sided scope
        is clamped back to 1.0, exactly as for the sqrt(3) slope. The intercept
        offset (a base-rate shift, not extremization) is unaffected by that gate.

        FAIL-SAFE: any thin/empty/non-binary scope, an unfit cohort, or any error
        returns the identity. Data-layer only; the caller decides to consult it."""

        identity = {
            "alpha": 1.0,
            "platt_d": 1.0,
            "cohort": None,
            "delta_s": 0.0,
            "intercept_b": 0.0,
            "slope_a": 1.0,
            "active": False,
            "small_cohort_fallback": True,
            "reason": "hierarchical calibration inactive — identity (no-op)",
        }
        try:
            if activated is None:
                from forecasting import appconfig

                activated = appconfig.get_bool(self._HIER_CALIBRATION_FLAG, False)
            if not activated:
                return identity
            if getattr(getattr(question, "outcome_space", None), "type", None) != "binary":
                return dict(identity, reason="non-binary question — identity")
            model = self.fit_hierarchical_calibration()
            if model is None:
                return dict(identity, active=True, reason="no resolved rows — identity")

            # Resolve the cohort this question would score into.
            venue = _scoring._cohort_venue(question)
            if forecast_origin == "live":
                base = "live_calibration_eligible"
            elif forecast_origin in _scoring._HIER_BASELINE_ORIGINS:
                base = forecast_origin
            else:
                base = "live_calibration_eligible"
            cohort = f"{base}:{venue}" if (venue and f"{base}:{venue}" in model.deltas) else base

            delta_s, fell_back = model.delta_for(cohort)

            # P2.3 guard, UNCHANGED: clamp an extremizing slope on a wrong-sided
            # scope. Reuse the exact gate used for the sqrt(3) slope.
            from forecasting.calibration_bias import extremization_alpha_gate

            observations = self._bias_observations(
                domain=getattr(question, "domain", None),
                forecast_origin=forecast_origin,
            )
            verdict = extremization_alpha_gate(model.a, observations)
            alpha = float(verdict.get("allowed_alpha", model.a) or 1.0)
            intercept = model.b + delta_s
            return {
                "alpha": alpha,
                "platt_d": math.exp(intercept),
                "cohort": cohort,
                "delta_s": delta_s,
                "intercept_b": model.b,
                "slope_a": model.a,
                "slope_gated": alpha != model.a,
                "active": True,
                "small_cohort_fallback": fell_back,
                "lambda": model.lambda_,
                "reason": (
                    f"hierarchical Platt cohort={cohort} delta_s={delta_s:.4f}"
                    + (" (small-cohort fallback → global)" if fell_back else "")
                    + (" [slope gated to 1.0]" if alpha != model.a else "")
                ),
            }
        except Exception:  # noqa: BLE001 — best-effort; identity on any failure
            return identity

    def calibration_bias(
        self,
        *,
        domain: str | None = None,
        scope_type: str | None = None,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        lesson_free_only: bool = True,
        forecast_origin: str | None = "live",
        enable_mechanical: bool = False,
        shrink_prior: float = 0.0,
        prior_scale: float | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        return _scoring.calibration_bias(self, domain=domain, scope_type=scope_type, since=since, recency_halflife_days=recency_halflife_days, lesson_free_only=lesson_free_only, forecast_origin=forecast_origin, enable_mechanical=enable_mechanical, shrink_prior=shrink_prior, prior_scale=prior_scale, now=now)

    def _live_score_count(self, domain: str | None) -> int:
        return _scoring._live_score_count(self, domain=domain)

    def _domains_with_scores(self, *, forecast_origin: str | None = "live") -> list[str]:
        return _scoring._domains_with_scores(self, forecast_origin=forecast_origin)

    def _prior_bias_lessons(self, scope_type: str, scope_ref: str | None) -> list[dict[str, Any]]:
        return _lessons._prior_bias_lessons(self, scope_type=scope_type, scope_ref=scope_ref)

    def synthesize_bias_lessons(
        self,
        *,
        scope: str = "all",
        domains: list[str] | None = None,
        since: str | None = None,
        recency_halflife_days: float | None = None,
        forecast_origin: str | None = "live",
        enable_mechanical: bool = False,
        activate: bool = True,
        dry_run: bool = False,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        return _lessons.synthesize_bias_lessons(self, scope=scope, domains=domains, since=since, recency_halflife_days=recency_halflife_days, forecast_origin=forecast_origin, enable_mechanical=enable_mechanical, activate=activate, dry_run=dry_run, now=now)

    def _apply_bias_disposition(
        self,
        report: Any,
        *,
        status: str,
        trajectory: list[float],
        prior_lessons: list[dict[str, Any]],
        dry_run: bool,
    ) -> dict[str, Any]:
        return _lessons._apply_bias_disposition(self, report=report, status=status, trajectory=trajectory, prior_lessons=prior_lessons, dry_run=dry_run)

    def create_correction(
        self,
        *,
        target_type: str,
        target_id: str,
        reason: str,
        created_by: str | None = None,
        old_value: Any = None,
        new_value: Any = None,
        patch: dict[str, Any] | None = None,
        status: str = "proposed",
    ) -> dict[str, Any]:
        return _resolutions.create_correction(self, target_type=target_type, target_id=target_id, reason=reason, created_by=created_by, old_value=old_value, new_value=new_value, patch=patch, status=status)

    def get_correction(self, correction_id: str) -> dict[str, Any]:
        return _resolutions.get_correction(self, correction_id=correction_id)

    def apply_correction(
        self, correction_id: str, *, applied_by: str | None = None
    ) -> dict[str, Any]:
        return _resolutions.apply_correction(
            self, correction_id, applied_by=applied_by
        )

    def list_corrections(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        return _resolutions.list_corrections(self, target_type=target_type, target_id=target_id, status=status)

    def create_trusted_resolver_policy(
        self,
        *,
        resolver_plugin: str,
        plugin_version: str | None,
        scope_type: str,
        scope_ref: str | None = None,
        enabled: bool = False,
        approved_by: str | None = None,
        audit_log_ref: str | None = None,
    ) -> dict[str, Any]:
        return _resolutions.create_trusted_resolver_policy(self, resolver_plugin=resolver_plugin, plugin_version=plugin_version, scope_type=scope_type, scope_ref=scope_ref, enabled=enabled, approved_by=approved_by, audit_log_ref=audit_log_ref)

    def get_trusted_resolver_policy(self, policy_id: str) -> dict[str, Any]:
        return _resolutions.get_trusted_resolver_policy(self, policy_id=policy_id)

    def list_trusted_resolver_policies(
        self,
        *,
        resolver_plugin: str | None = None,
        scope_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        return _resolutions.list_trusted_resolver_policies(self, resolver_plugin=resolver_plugin, scope_type=scope_type, enabled=enabled)

    def update_domain_error_profile(self, question: ForecastQuestion) -> dict[str, Any] | None:
        return _lessons.update_domain_error_profile(self, question=question)

    def _write_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
        question_type: str,
        scores: list[ScoreRecord],
    ) -> dict[str, Any]:
        return _lessons._write_error_profile(self, domain=domain, topic=topic, question_type=question_type, scores=scores)

    def _postmortems_for_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
    ) -> list[dict[str, Any]]:
        return _lessons._postmortems_for_error_profile(self, domain=domain, topic=topic)

    def _error_counts_for_profile(
        self,
        *,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
    ) -> Counter[str]:
        return _lessons._error_counts_for_profile(self, scores=scores, postmortems=postmortems)

    def _recurring_error_tags(self, error_counts: Counter[str]) -> list[str]:
        return _lessons._recurring_error_tags(self, error_counts=error_counts)

    def _recommended_adjustments_for_errors(self, recurring_errors: list[str]) -> list[str]:
        return _lessons._recommended_adjustments_for_errors(self, recurring_errors=recurring_errors)

    def get_domain_error_profile(self, profile_id: str) -> dict[str, Any]:
        return _lessons.get_domain_error_profile(self, profile_id=profile_id)

    def list_domain_error_profiles(
        self,
        *,
        domain: str | None = None,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        return _lessons.list_domain_error_profiles(self, domain=domain, topic=topic)

    def review_learned_error_alerts(
        self,
        question_id: str,
        *,
        reviewed_by: str,
        assessment: str,
        decision: str = "reviewed_no_change",
        now: str | None = None,
    ) -> dict[str, Any]:
        return _lessons.review_learned_error_alerts(
            self,
            question_id,
            reviewed_by=reviewed_by,
            assessment=assessment,
            decision=decision,
            now=now,
        )

    def add_baseline_comparison(
        self,
        *,
        question_id: str,
        source: str,
        baseline_type: str,
        probability_or_distribution: Any,
        as_of: str | None = None,
        forecast_id: str | None = None,
        backtest_case_id: str | None = None,
        score_record_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _backtest.add_baseline_comparison(self, question_id=question_id, source=source, baseline_type=baseline_type, probability_or_distribution=probability_or_distribution, as_of=as_of, forecast_id=forecast_id, backtest_case_id=backtest_case_id, score_record_id=score_record_id, metadata=metadata)

    def get_baseline_comparison(self, baseline_id: str) -> dict[str, Any]:
        return _backtest.get_baseline_comparison(self, baseline_id=baseline_id)

    def list_baseline_comparisons(self, question_id: str) -> list[dict[str, Any]]:
        return _backtest.list_baseline_comparisons(self, question_id=question_id)

    def score_baseline_comparisons(self, question_id: str, *, force: bool = False) -> list[dict[str, Any]]:
        return _backtest.score_baseline_comparisons(self, question_id=question_id, force=force)

    def import_benchmark_dataset(
        self,
        *,
        source: str,
        cases: list[dict[str, Any]],
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _backtest.import_benchmark_dataset(self, source=source, cases=cases, name=name, description=description, metadata=metadata)

    def get_benchmark_dataset(self, dataset_id: str) -> dict[str, Any]:
        return _backtest.get_benchmark_dataset(self, dataset_id=dataset_id)

    def list_benchmark_datasets(self) -> list[dict[str, Any]]:
        return _backtest.list_benchmark_datasets(self)

    def run_backtest_dataset(
        self,
        *,
        dataset: str,
        cases: list[dict[str, Any]],
        default_forecast_time_cutoff: str | None = None,
        evidence_cutoff_policy: str = "available_at_lte_cutoff",
        calibration_policy: dict[str, Any] | None = None,
        allow_calibration_memory: bool = False,
        leak_judge_runner: "LeakJudgeRunner | None" = None,
        arm: str | None = None,
    ) -> dict[str, Any]:
        return _backtest.run_backtest_dataset(self, dataset=dataset, cases=cases, default_forecast_time_cutoff=default_forecast_time_cutoff, evidence_cutoff_policy=evidence_cutoff_policy, calibration_policy=calibration_policy, allow_calibration_memory=allow_calibration_memory, leak_judge_runner=leak_judge_runner, arm=arm)

    def get_backtest_run(self, run_id: str) -> dict[str, Any]:
        return _backtest.get_backtest_run(self, run_id=run_id)

    def list_backtest_runs(self) -> list[dict[str, Any]]:
        return _backtest.list_backtest_runs(self)

    def list_backtest_cases(self, run_id: str) -> list[dict[str, Any]]:
        return _backtest.list_backtest_cases(self, run_id=run_id)

    def backtest_performance_report(self, run_id: str) -> dict[str, Any]:
        return _backtest.backtest_performance_report(self, run_id=run_id)

    def live_performance_report(self, *, domain: str | None = None) -> dict[str, Any]:
        return _backtest.live_performance_report(self, domain=domain)

    def review_questions(
        self,
        *,
        stale: bool = False,
        last_days: int | None = None,
        domain: str | None = None,
        topic: str | None = None,
        horizon: str | None = None,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        return _reviews.review_questions(self, stale=stale, last_days=last_days, domain=domain, topic=topic, horizon=horizon, confidence_below=confidence_below, confidence_above=confidence_above, large_delta_threshold=large_delta_threshold, now=now)

    def schedule_review(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        cadence: str,
        next_run_at: str | None = None,
        trigger_reason: str = "scheduled",
        enabled: bool = True,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        stale_days: int = 7,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
    ) -> dict[str, Any]:
        return _reviews.schedule_review(self, scope_type=scope_type, scope_ref=scope_ref, cadence=cadence, next_run_at=next_run_at, trigger_reason=trigger_reason, enabled=enabled, auto_score=auto_score, auto_postmortem=auto_postmortem, stale_days=stale_days, confidence_below=confidence_below, confidence_above=confidence_above, large_delta_threshold=large_delta_threshold)

    def get_scheduled_review(self, review_id: str) -> dict[str, Any]:
        return _reviews.get_scheduled_review(self, review_id=review_id)

    def list_scheduled_reviews(self) -> list[dict[str, Any]]:
        return _reviews.list_scheduled_reviews(self)

    def annotate_snapshot(self, snapshot_id: str, patch: dict[str, Any]) -> None:
        return _snapshots.annotate_snapshot(self, snapshot_id=snapshot_id, patch=patch)

    def next_review_by_question(self) -> dict[str, dict[str, Any]]:
        return _reviews.next_review_by_question(self)

    def count_due_scheduled_reviews(self, *, now: str | None = None) -> int:
        return _reviews.count_due_scheduled_reviews(self, now=now)

    def next_scheduled_review_at(self) -> str | None:
        return _reviews.next_scheduled_review_at(self)

    def mark_question_review_due(self, question_id: str, *, now: str | None = None) -> dict[str, Any]:
        return _reviews.mark_question_review_due(self, question_id=question_id, now=now)

    def dedupe_scheduled_reviews(self) -> dict[str, Any]:
        return _reviews.dedupe_scheduled_reviews(self)

    def list_scheduled_review_runs(
        self,
        *,
        scheduled_review_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return _reviews.list_scheduled_review_runs(self, scheduled_review_id=scheduled_review_id, limit=limit)

    def count_scheduled_review_runs(
        self, *, scheduled_review_id: str | None = None
    ) -> int:
        return _reviews.count_scheduled_review_runs(
            self, scheduled_review_id=scheduled_review_id
        )

    def add_watched_source(
        self,
        *,
        scope_type: str,
        scope_ref: str | None,
        source: str,
        source_type: str | None = None,
        role: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _watches.add_watched_source(self, scope_type=scope_type, scope_ref=scope_ref, source=source, source_type=source_type, role=role, metadata=metadata)

    def get_watched_source(self, watch_id: str) -> dict[str, Any]:
        return _watches.get_watched_source(self, watch_id=watch_id)

    def list_watched_sources(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        status: str | None = "active",
    ) -> list[dict[str, Any]]:
        return _watches.list_watched_sources(self, scope_type=scope_type, scope_ref=scope_ref, status=status)

    # ── Forecast links (cross-pollination) ──────────────────────────────
    def _forecast_link_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _question_meta._forecast_link_to_dict(self, row=row)

    def add_forecast_link(
        self,
        from_question_id: str,
        to_question_id: str,
        *,
        link_type: str = "related",
        weight: float = 1.0,
        rationale: str = "",
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _question_meta.add_forecast_link(self, from_question_id=from_question_id, to_question_id=to_question_id, link_type=link_type, weight=weight, rationale=rationale, created_by=created_by, metadata=metadata)

    def get_forecast_link(self, link_id: str) -> dict[str, Any]:
        return _question_meta.get_forecast_link(self, link_id=link_id)

    def remove_forecast_link(
        self,
        from_question_id: str,
        to_question_id: str,
        *,
        link_type: str | None = None,
    ) -> int:
        return _question_meta.remove_forecast_link(self, from_question_id=from_question_id, to_question_id=to_question_id, link_type=link_type)

    def list_forecast_links(
        self,
        question_id: str,
        *,
        link_type: str | None = None,
        direction: str = "both",
        status: str | None = None,  # accepted for signature parity; links have no status
    ) -> list[dict[str, Any]]:
        return _question_meta.list_forecast_links(self, question_id=question_id, link_type=link_type, direction=direction, status=status)

    def shared_sources(self, question_id: str, other_id: str) -> list[dict[str, Any]]:
        return _question_meta.shared_sources(self, question_id=question_id, other_id=other_id)

    def related_forecast_views(
        self,
        question: Any,
        *,
        # Display default: the links/show surfaces use this and must show ALL
        # explicit links (e.g. a 7-child component_of master), so the default is
        # generous. The agent cross-pollination CONTEXT passes an explicit
        # limit=5 (protocol.py) to stay within its context budget.
        limit: int = 25,
        overlap_threshold: float = 0.2,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return _question_meta.related_forecast_views(self, question=question, limit=limit, overlap_threshold=overlap_threshold)

    def build_cross_refs(self, question: Any, *, advisory_only: bool = False) -> dict[str, Any]:
        return _question_meta.build_cross_refs(self, question=question, advisory_only=advisory_only)

    # ── Thesis membership + aggregation ─────────────────────────────────
    #
    # A thesis is a first-class forecast question (outcome_space.type ==
    # "thesis") whose belief is a DETERMINISTIC aggregate of its tagged
    # members' latest snapshots (see forecasting/thesis.py). Membership lives
    # in its own ``thesis_members`` table (NOT forecast_links) so the
    # cross-pollination auto-walk never pulls a thesis into a member's
    # provenance, and so each edge can carry a signed direction
    # (support / inverted) + weight + a distributional target.

    def is_thesis(self, question: Any) -> bool:
        return _theses.is_thesis(self, question=question)

    def is_factor(self, question: Any) -> bool:
        return _theses.is_factor(self, question=question)

    def _thesis_member_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _theses._thesis_member_to_dict(self, row=row)

    def add_thesis_member(
        self,
        thesis_id: str,
        member_id: str,
        *,
        direction: str = "support",
        weight: float = 1.0,
        role: str | None = None,
        target: float | None = None,
        hi_is_good: bool = True,
        max_age_days: float | None = None,
        rationale: str = "",
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _theses.add_thesis_member(self, thesis_id=thesis_id, member_id=member_id, direction=direction, weight=weight, role=role, target=target, hi_is_good=hi_is_good, max_age_days=max_age_days, rationale=rationale, created_by=created_by, metadata=metadata)

    def remove_thesis_member(self, thesis_id: str, member_id: str) -> int:
        return _theses.remove_thesis_member(self, thesis_id=thesis_id, member_id=member_id)

    def list_thesis_members(self, thesis_id: str) -> list[dict[str, Any]]:
        return _theses.list_thesis_members(self, thesis_id=thesis_id)

    def list_theses_for_member(self, member_id: str) -> list[dict[str, Any]]:
        return _theses.list_theses_for_member(self, member_id=member_id)

    def theses_by_member(self, member_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        return _theses.theses_by_member(self, member_ids=member_ids)

    def _belief_record(
        self,
        member_id: str,
        *,
        direction: str = "support",
        weight: float = 1.0,
        target: float | None = None,
        hi_is_good: bool = True,
        max_age_days: float | None = None,
        title: str | None = None,
        outcome_type: str | None = None,
    ) -> dict[str, Any]:
        return _theses._belief_record(self, member_id=member_id, direction=direction, weight=weight, target=target, hi_is_good=hi_is_good, max_age_days=max_age_days, title=title, outcome_type=outcome_type)

    def _thesis_member_belief(self, member: dict[str, Any]) -> dict[str, Any]:
        return _theses._thesis_member_belief(self, member=member)

    # ── Thesis entities (per-name suitability + trade triggers) ─────────────
    #
    # An entity — a stock, a candidate, a currency, a sector, anything the
    # thesis's signals map onto — carries its OWN weighted vector over the
    # thesis members. Its "suitability" is the same 0..1 aggregate as the
    # thesis, just with the entity's weights + direction, so the §22/§10 rule
    # ("if power-bottleneck prob rises -> BE/IREN/CORZ better suited") falls out
    # generically for ANY thesis (elections, FX, manufacturing, ...).

    def _thesis_entity_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return _theses._thesis_entity_to_dict(self, row=row)

    def _normalize_entity_weights(self, weights: Any) -> list[dict[str, Any]]:
        return _theses._normalize_entity_weights(self, weights=weights)

    def add_thesis_entity(
        self,
        thesis_id: str,
        name: str,
        *,
        label: str | None = None,
        kind: str = "entity",
        weights: Any = None,
        action_threshold: float | None = None,
        created_by: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _theses.add_thesis_entity(self, thesis_id=thesis_id, name=name, label=label, kind=kind, weights=weights, action_threshold=action_threshold, created_by=created_by, metadata=metadata)

    def set_entity_weight(
        self,
        thesis_id: str,
        name: str,
        member_id: str,
        *,
        weight: float = 1.0,
        direction: str = "support",
        hi_is_good: bool = True,
        target: float | None = None,
        role: str | None = None,
    ) -> dict[str, Any]:
        return _theses.set_entity_weight(self, thesis_id=thesis_id, name=name, member_id=member_id, weight=weight, direction=direction, hi_is_good=hi_is_good, target=target, role=role)

    def remove_thesis_entity(self, thesis_id: str, name: str) -> int:
        return _theses.remove_thesis_entity(self, thesis_id=thesis_id, name=name)

    def list_thesis_entities(self, thesis_id: str) -> list[dict[str, Any]]:
        return _theses.list_thesis_entities(self, thesis_id=thesis_id)

    def _compute_thesis_entities(
        self,
        thesis_id: str,
        *,
        rho: float | str,
        now: str,
        member_map: dict[str, dict[str, Any]],
        current_components: list[dict[str, Any]],
        prev_components: list[dict[str, Any]],
        prev_entities: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return _theses._compute_thesis_entities(self, thesis_id=thesis_id, rho=rho, now=now, member_map=member_map, current_components=current_components, prev_components=prev_components, prev_entities=prev_entities)

    def _aggregate_factor(
        self,
        factor: Any,
        *,
        rho: float | str,
        now: str | None,
        commit: bool,
        analyst_note: bool = True,
    ) -> dict[str, Any]:
        return _theses._aggregate_factor(self, factor=factor, rho=rho, now=now, commit=commit, analyst_note=analyst_note)

    def set_thesis_correlation(self, thesis_id: str, member_a: str, member_b: str, rho: float) -> dict[str, float]:
        return _theses.set_thesis_correlation(self, thesis_id=thesis_id, member_a=member_a, member_b=member_b, rho=rho)

    def _thesis_correlation_matrix(self, thesis: Any) -> dict[frozenset[str], float] | None:
        return _theses._thesis_correlation_matrix(self, thesis=thesis)

    def set_thesis_event(
        self,
        thesis_id: str,
        *,
        kind: str = "count_threshold",
        threshold: int | None = None,
    ) -> dict[str, Any]:
        return _theses.set_thesis_event(self, thesis_id=thesis_id, kind=kind, threshold=threshold)

    def clear_thesis_event(self, thesis_id: str) -> bool:
        return _theses.clear_thesis_event(self, thesis_id=thesis_id)

    def _thesis_event_spec(self, thesis: Any) -> dict[str, Any] | None:
        return _theses._thesis_event_spec(self, thesis=thesis)

    @staticmethod
    def _thesis_event_seed(thesis_id: str, as_of: str | None) -> int:
        return _theses._thesis_event_seed(thesis_id=thesis_id, as_of=as_of)

    def aggregate_thesis(
        self,
        thesis_id: str,
        *,
        rho: float | str = 0.4,
        now: str | None = None,
        commit: bool = True,
        analyst_note: bool = True,
    ) -> dict[str, Any]:
        return _theses.aggregate_thesis(self, thesis_id=thesis_id, rho=rho, now=now, commit=commit, analyst_note=analyst_note)

    def aggregate_all_theses(
        self,
        *,
        now: str | None = None,
        rho: float | str = 0.4,
        limit: int = 500,
        commit: bool = True,
    ) -> dict[str, Any]:
        return _theses.aggregate_all_theses(self, now=now, rho=rho, limit=limit, commit=commit)

    def backfill_thesis_member_intervals(
        self,
        thesis_id: str,
        *,
        weight_floor: float = 1.5,
        apply: bool = False,
    ) -> dict[str, Any]:
        return _theses.backfill_thesis_member_intervals(self, thesis_id, weight_floor=weight_floor, apply=apply)

    def list_source_snapshots(
        self,
        *,
        question_id: str | None = None,
        watched_source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return _refresh.list_source_snapshots(self, question_id=question_id, watched_source_id=watched_source_id, limit=limit)

    # ── resolver framework (propose-only; never auto-commits) ─────────────────
    def set_resolution_rule(
        self,
        question_id: str,
        *,
        field: str,
        comparator: str,
        threshold: float,
        resolver: str = "metric_threshold",
        source_role: str = "resolver",
    ) -> dict[str, Any]:
        return _resolutions.set_resolution_rule(self, question_id=question_id, field=field, comparator=comparator, threshold=threshold, resolver=resolver, source_role=source_role)

    def propose_resolution(self, question_id: str) -> dict[str, Any] | None:
        return _resolutions.propose_resolution(self, question_id=question_id)

    def propose_due_resolutions(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        return _resolutions.propose_due_resolutions(self, dry_run=dry_run)

    def autopilot_readiness(
        self,
        question_id: str,
        *,
        sources: list[str] | None = None,
        allow_missing_resolution_source: bool = False,
    ) -> dict[str, Any]:
        return _autopilot.autopilot_readiness(self, question_id=question_id, sources=sources, allow_missing_resolution_source=allow_missing_resolution_source)

    def enable_autopilot(
        self,
        *,
        question_id: str,
        sources: list[str],
        cadence: str,
        mode: str = "propose",
        materiality_policy: dict[str, Any] | None = None,
        guardrail_policy: dict[str, Any] | None = None,
        notification_policy: dict[str, Any] | None = None,
        required_sources: list[str] | None = None,
        next_run_at: str | None = None,
        created_by: str | None = None,
        allow_missing_resolution_source: bool = False,
    ) -> dict[str, Any]:
        return _autopilot.enable_autopilot(self, question_id=question_id, sources=sources, cadence=cadence, mode=mode, materiality_policy=materiality_policy, guardrail_policy=guardrail_policy, notification_policy=notification_policy, required_sources=required_sources, next_run_at=next_run_at, created_by=created_by, allow_missing_resolution_source=allow_missing_resolution_source)

    def disable_autopilot(self, question_id: str) -> dict[str, Any]:
        return _autopilot.disable_autopilot(self, question_id=question_id)

    def get_autopilot_policy(self, policy_id: str) -> dict[str, Any]:
        return _autopilot.get_autopilot_policy(self, policy_id=policy_id)

    def get_active_autopilot_policy(self, question_id: str) -> dict[str, Any]:
        return _autopilot.get_active_autopilot_policy(self, question_id=question_id)

    def list_autopilot_policies(
        self,
        *,
        question_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        return _autopilot.list_autopilot_policies(self, question_id=question_id, enabled_only=enabled_only)

    def list_autopilot_runs(
        self,
        *,
        question_id: str | None = None,
        policy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return _autopilot.list_autopilot_runs(self, question_id=question_id, policy_id=policy_id, limit=limit)

    def list_forecast_update_proposals(
        self,
        *,
        question_id: str | None = None,
        status: str | None = "pending",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return _autopilot.list_forecast_update_proposals(self, question_id=question_id, status=status, limit=limit)

    def create_forecast_update_proposal(
        self,
        *,
        question_id: str,
        run_id: str | None,
        prior_forecast_id: str | None,
        proposed_probability_or_distribution: Any,
        rationale: str,
        evidence_refs: list[str] | None = None,
        source_snapshot_refs: list[str] | None = None,
        model_run_refs: list[str] | None = None,
        assumption_refs: list[str] | None = None,
        reference_class_refs: list[str] | None = None,
        snapshot_args: dict[str, Any] | None = None,
        status: str = "pending",
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        return _autopilot.create_forecast_update_proposal(self, question_id=question_id, run_id=run_id, prior_forecast_id=prior_forecast_id, proposed_probability_or_distribution=proposed_probability_or_distribution, rationale=rationale, evidence_refs=evidence_refs, source_snapshot_refs=source_snapshot_refs, model_run_refs=model_run_refs, assumption_refs=assumption_refs, reference_class_refs=reference_class_refs, snapshot_args=snapshot_args, status=status, expires_at=expires_at)

    def get_forecast_update_proposal(self, proposal_id: str) -> dict[str, Any]:
        return _autopilot.get_forecast_update_proposal(self, proposal_id=proposal_id)

    def approve_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
        status: str = "approved",
    ) -> ForecastSnapshot:
        return _autopilot.approve_forecast_update_proposal(self, proposal_id=proposal_id, reviewed_by=reviewed_by, status=status)

    def reject_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
    ) -> dict[str, Any]:
        return _autopilot.reject_forecast_update_proposal(self, proposal_id=proposal_id, reviewed_by=reviewed_by)

    def expire_forecast_update_proposals(
        self,
        *,
        now: str | None = None,
        question_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return _autopilot.expire_forecast_update_proposals(
            self, now=now, question_id=question_id
        )

    def reject_unsupported_source_proposals(
        self, *, reviewed_by: str = "lifecycle:insufficient_source_content"
    ) -> list[dict[str, Any]]:
        return _autopilot.reject_unsupported_source_proposals(
            self, reviewed_by=reviewed_by
        )

    # Canonical pooling-method aliases so a re-pool matches the snapshot's
    # original recipe. Mirrors the CLI's bayes-method handling.
    _REFRESH_POOL_METHODS = {
        "log_odds_pool": "log_odds_pool",
        "log_odds": "log_odds_pool",
        "logit": "log_odds_pool",
        "geometric": "log_odds_pool",
        "geo_mean_odds": "log_odds_pool",
        "log_pool": "log_pool",
        "log_linear": "log_pool",
        "linear_pool": "linear_pool",
        "linear": "linear_pool",
    }

    @classmethod
    def _refresh_pool_method(cls, method: str | None) -> str:
        """Map a stored snapshot.method to a combine_forecasts pooling method,
        defaulting to log-odds pooling (the desk default for disagreeing sources)."""
        key = (method or "").strip().lower()
        return cls._REFRESH_POOL_METHODS.get(key, "log_odds_pool")

    @staticmethod
    def _refresh_source_keys(source_type: str, source: str) -> set[str]:
        return _refresh._refresh_source_keys(source_type=source_type, source=source)

    def refresh_forecast(
        self,
        question_id: str,
        *,
        fetcher: Any,
        now: str | None = None,
        re_estimate: str = "deterministic",
        extremize: float = 1.0,
        correlation: Any | None = None,
        dry_run: bool = False,
        commit: bool = True,
        proposal_only: bool = False,
        trigger_reason: str = "manual_refresh",
        skill_weights: bool | None = None,
    ) -> dict[str, Any]:
        return _refresh.refresh_forecast(self, question_id=question_id, fetcher=fetcher, now=now, re_estimate=re_estimate, extremize=extremize, correlation=correlation, dry_run=dry_run, commit=commit, proposal_only=proposal_only, trigger_reason=trigger_reason, skill_weights=skill_weights)

    # A market-model id is ``mm_<hex12>`` (create_market_model). A component is
    # "model-sourced" when it carries that id explicitly or references it in its
    # source slug (e.g. ``market_model:mm_abc123``, ``model:mm_abc123``, or the
    # bare id) — the R4 re-pool scales such a component's weight by the model's skill.
    _MARKET_MODEL_ID_RE = re.compile(r"mm_[0-9a-f]{12}")

    @classmethod
    def _component_market_model_id(cls, row: dict[str, Any]) -> str | None:
        """Return the ``mm_...`` market-model id a component references, or None."""
        if not isinstance(row, dict):
            return None
        explicit = row.get("market_model_id")
        if isinstance(explicit, str) and cls._MARKET_MODEL_ID_RE.fullmatch(explicit.strip()):
            return explicit.strip()
        for key in ("source", "source_ref", "name"):
            raw = row.get(key)
            if isinstance(raw, str):
                match = cls._MARKET_MODEL_ID_RE.search(raw)
                if match:
                    return match.group(0)
        return None

    def _skill_weights_enabled(self) -> bool:
        return _model_scoring._skill_weights_enabled(self)

    def _market_model_scored_run_count(self, market_model_id: str) -> int:
        return _model_scoring._market_model_scored_run_count(self, market_model_id=market_model_id)

    def _apply_model_skill_weights(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return _model_scoring._apply_model_skill_weights(self, rows=rows)

    def _refresh_reading_value(self, item: dict[str, Any]) -> float | None:
        return _refresh._refresh_reading_value(self, item=item)

    def _apply_fresh_market_probabilities(
        self, components: dict[str, Any], fresh_readings: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[str]]:
        return _refresh._apply_fresh_market_probabilities(self, components=components, fresh_readings=fresh_readings)

    @staticmethod
    def _default_refresh_rationale(
        *,
        changed_readings: list[dict[str, Any]],
        unmatched_sources: list[str],
        new_prob: Any,
        prior_prob: Any,
        re_estimate: str,
        needs_agent: bool,
    ) -> str:
        return _refresh._default_refresh_rationale(changed_readings=changed_readings, unmatched_sources=unmatched_sources, new_prob=new_prob, prior_prob=prior_prob, re_estimate=re_estimate, needs_agent=needs_agent)

    def _autopilot_recheck_without_policy(
        self,
        question_id: str,
        *,
        now: str | None = None,
        trigger_reason: str = "manual",
    ) -> dict[str, Any]:
        return _autopilot._autopilot_recheck_without_policy(self, question_id=question_id, now=now, trigger_reason=trigger_reason)

    def run_autopilot(
        self,
        question_id: str,
        *,
        now: str | None = None,
        trigger_reason: str = "manual",
        proposed_probability_or_distribution: Any | None = None,
        rationale: str | None = None,
        require_policy: bool = True,
        allow_auto_commit: bool = True,
    ) -> dict[str, Any]:
        # The autopilot POLICY governs only the MATERIALITY threshold and the
        # auto-commit MODE (whether a watched-source change becomes a proposal /
        # auto-commit). Watched sources + update-triggers are attached to a question
        # at spec/import time WITHOUT the operator ever enabling autopilot (autopilot
        # is a deliberate per-question opt-in), yet they still emit
        # `watched_source_changed` alerts that land in the FREE resolution tier. So a
        # missing policy must NOT hard-fail the free-tier drain: with
        # ``require_policy=False`` we degrade to a conservative, zero-spend,
        # deterministic source RE-CHECK (record a source-snapshot audit row, propose
        # /commit nothing). The explicit `forecast autopilot run` path keeps the
        # default ``require_policy=True`` so an operator asking to autopilot a
        # policy-less question still gets a loud, actionable error.
        return _autopilot.run_autopilot(self, question_id=question_id, now=now, trigger_reason=trigger_reason, proposed_probability_or_distribution=proposed_probability_or_distribution, rationale=rationale, require_policy=require_policy, allow_auto_commit=allow_auto_commit)

    def check_watched_sources(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        return _watches.check_watched_sources(self, scope_type=scope_type, scope_ref=scope_ref, now=now)

    def list_source_change_events(
        self,
        *,
        question_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import list_source_change_events

        return list_source_change_events(
            self, question_id=question_id, status=status, limit=limit
        )

    def list_source_change_event_transitions(
        self, source_change_event_id: str
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import list_source_change_event_transitions

        return list_source_change_event_transitions(self, source_change_event_id)

    def list_operational_tasks(
        self,
        *,
        status: str | None = None,
        lane: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import list_operational_tasks

        return list_operational_tasks(self, status=status, lane=lane, limit=limit)

    def claim_alert_operational_task(
        self,
        alert: AlertEvent,
        *,
        owner: str,
        lane: str,
        now: str | None = None,
        lease_seconds: int = 300,
    ) -> dict[str, Any] | None:
        from forecasting.ledger.workflow import claim_alert_operational_task

        return claim_alert_operational_task(
            self,
            alert,
            owner=owner,
            lane=lane,
            now=now,
            lease_seconds=lease_seconds,
        )

    def enqueue_alert_operational_task(
        self,
        alert: AlertEvent,
        *,
        lane: str,
        now: str | None = None,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import enqueue_alert_operational_task

        return enqueue_alert_operational_task(self, alert, lane=lane, now=now)

    def claim_operational_tasks(
        self,
        *,
        owner: str,
        lane: str = "deterministic_critical",
        now: str | None = None,
        lease_seconds: int = 300,
        limit: int = 10,
        task_type: str | None = None,
        question_id: str | None = None,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import claim_operational_tasks

        return claim_operational_tasks(
            self,
            owner=owner,
            lane=lane,
            now=now,
            lease_seconds=lease_seconds,
            limit=limit,
            task_type=task_type,
            question_id=question_id,
        )

    def heartbeat_operational_task(
        self,
        task_id: str,
        *,
        owner: str,
        now: str | None = None,
        lease_seconds: int = 300,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import heartbeat_operational_task

        return heartbeat_operational_task(
            self,
            task_id,
            owner=owner,
            now=now,
            lease_seconds=lease_seconds,
        )

    def reclaim_expired_operational_tasks(
        self, *, owner: str = "lease-reclaimer", now: str | None = None
    ) -> dict[str, int]:
        from forecasting.ledger.workflow import reclaim_expired_operational_tasks

        return reclaim_expired_operational_tasks(self, owner=owner, now=now)

    def suspend_unhealthy_watched_sources(
        self,
        *,
        now: str | None = None,
        failure_threshold: int = 3,
        low_yield_min_events: int = 5,
        low_yield_ratio: float = 0.95,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import suspend_unhealthy_watched_sources

        return suspend_unhealthy_watched_sources(
            self,
            now=now,
            failure_threshold=failure_threshold,
            low_yield_min_events=low_yield_min_events,
            low_yield_ratio=low_yield_ratio,
        )

    def act_on_human_task(
        self,
        task_id: str,
        *,
        action: str,
        owner: str = "human:forecast-duty",
        defer_hours: float = 24.0,
        note: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import act_on_human_task

        return act_on_human_task(
            self,
            task_id,
            action=action,
            owner=owner,
            defer_hours=defer_hours,
            note=note,
            now=now,
        )

    def complete_operational_task(
        self,
        task_id: str,
        *,
        owner: str,
        disposition: str,
        result: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import complete_operational_task

        return complete_operational_task(
            self,
            task_id,
            owner=owner,
            disposition=disposition,
            result=result,
            usage=usage,
            now=now,
        )

    def run_estimator_tasks(
        self,
        *,
        owner: str,
        estimator,
        now: str | None = None,
        limit: int = 5,
        lease_seconds: int = 900,
        question_id: str | None = None,
        allow_auto_commit: bool = False,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import run_estimator_tasks

        return run_estimator_tasks(
            self,
            owner=owner,
            estimator=estimator,
            now=now,
            limit=limit,
            lease_seconds=lease_seconds,
            question_id=question_id,
            allow_auto_commit=allow_auto_commit,
        )

    def run_source_change_router(
        self,
        *,
        owner: str,
        now: str | None = None,
        limit: int = 100,
        lease_seconds: int = 300,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import run_source_change_router

        return run_source_change_router(
            self,
            owner=owner,
            now=now,
            limit=limit,
            lease_seconds=lease_seconds,
        )

    def run_resolution_finalization_tasks(
        self,
        *,
        owner: str,
        now: str | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import run_resolution_finalization_tasks

        return run_resolution_finalization_tasks(
            self, owner=owner, now=now, limit=limit
        )

    def reconcile_operational_dead_letters(
        self,
        *,
        owner: str,
        now: str | None = None,
        transient_retry_delay_seconds: int = 86400,
    ) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import reconcile_operational_dead_letters

        return reconcile_operational_dead_letters(
            self,
            owner=owner,
            now=now,
            transient_retry_delay_seconds=transient_retry_delay_seconds,
        )

    def fail_operational_task(
        self,
        task_id: str,
        *,
        owner: str,
        error: str,
        usage: dict[str, Any] | None = None,
        now: str | None = None,
        retry_delay_seconds: int = 60,
        retryable: bool = True,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import fail_operational_task

        return fail_operational_task(
            self,
            task_id,
            owner=owner,
            error=error,
            usage=usage,
            now=now,
            retry_delay_seconds=retry_delay_seconds,
            retryable=retryable,
        )

    def set_operational_lane_policy(
        self,
        lane: str,
        *,
        daily_claim_budget: int,
        slo_minutes: int,
        enabled: bool = True,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import set_operational_lane_policy

        return set_operational_lane_policy(
            self,
            lane,
            daily_claim_budget=daily_claim_budget,
            slo_minutes=slo_minutes,
            enabled=enabled,
        )

    def operational_cockpit(self, *, now: str | None = None) -> dict[str, Any]:
        from forecasting.ledger.workflow import operational_cockpit

        return operational_cockpit(self, now=now)

    def escalate_overdue_high_severity_tasks(
        self, *, now: str | None = None
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import escalate_overdue_high_severity_tasks

        return escalate_overdue_high_severity_tasks(self, now=now)

    def utility_backtest(self) -> dict[str, Any]:
        from forecasting.ledger.workflow import utility_backtest

        return utility_backtest(self)

    def calibrate_task_utility(
        self, *, min_samples: int = 20, iterations: int = 400
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import calibrate_task_utility

        return calibrate_task_utility(
            self, min_samples=min_samples, iterations=iterations
        )

    def claim_automation_budget(
        self,
        bucket: str,
        *,
        owner: str,
        now: str | None = None,
        min_interval_hours: float = 0.0,
        lease_seconds: int = 3600,
        reserved_spend: int = 0,
        force: bool = False,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import claim_automation_budget

        return claim_automation_budget(
            self,
            bucket,
            owner=owner,
            now=now,
            min_interval_hours=min_interval_hours,
            lease_seconds=lease_seconds,
            reserved_spend=reserved_spend,
            force=force,
        )

    def release_automation_budget(
        self,
        bucket: str,
        *,
        owner: str,
        spent: int,
        now: str | None = None,
        completed: bool = True,
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import release_automation_budget

        return release_automation_budget(
            self,
            bucket,
            owner=owner,
            spent=spent,
            now=now,
            completed=completed,
        )

    def automation_budget_status(self, bucket: str) -> dict[str, Any] | None:
        from forecasting.ledger.workflow import automation_budget_status

        return automation_budget_status(self, bucket)

    def acquire_watch_source_token(
        self, watch: dict[str, Any], *, now: str | None = None
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import acquire_watch_source_token

        return acquire_watch_source_token(self, watch, now=now)

    def list_source_token_buckets(self) -> list[dict[str, Any]]:
        from forecasting.ledger.workflow import list_source_token_buckets

        return list_source_token_buckets(self)

    def set_question_service_mode(
        self, question_id: str, mode: str
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import set_question_service_mode

        return set_question_service_mode(self, question_id, mode)

    def classify_active_question_service_modes(
        self, *, dry_run: bool = True
    ) -> dict[str, Any]:
        from forecasting.ledger.workflow import classify_active_question_service_modes

        return classify_active_question_service_modes(self, dry_run=dry_run)

    # Canonical numeric-value keys an adapter item may expose, newest-relevant
    # first. Used to derive the latest observation for an executable trigger and
    # for refresh change-detection. "probability" covers market/crowd adapters
    # (manifold/metaculus/polymarket/kalshi) whose reading IS a probability.
    _TRIGGER_VALUE_KEYS = (
        "value",
        "observed_value",
        "latest_value",
        "level",
        "close_price",
        "close",
        "price",
        "rate",
        "yield",
        "index_value",
        "views",
        "count",
        "probability",
    )

    def _derive_trigger_observations(self, question_id: str) -> dict[str, float]:
        return _refresh._derive_trigger_observations(self, question_id=question_id)

    def check_update_triggers(
        self,
        *,
        question_id: str,
        observations: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        return _refresh.check_update_triggers(self, question_id=question_id, observations=observations, now=now)

    def run_due_scheduled_reviews(
        self,
        *,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        refresh_fetcher: Any = None,
        worker_id: str | None = None,
        lease_seconds: int = 300,
        limit: int = 100,
        max_wall_seconds: float = 60.0,
    ) -> list[dict[str, Any]]:
        return _reviews.run_due_scheduled_reviews(
            self,
            now=now,
            auto_score=auto_score,
            auto_postmortem=auto_postmortem,
            refresh_fetcher=refresh_fetcher,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            limit=limit,
            max_wall_seconds=max_wall_seconds,
        )

    def _refresh_due_question(
        self, question_id: str, *, fetcher: Any, now: str | None
    ) -> dict[str, Any] | None:
        return _reviews._refresh_due_question(self, question_id=question_id, fetcher=fetcher, now=now)

    def _record_scheduled_review_run(
        self,
        *,
        review: dict[str, Any],
        run_at: str,
        next_run_at: str,
        alerts: list[AlertEvent],
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return _reviews._record_scheduled_review_run(
            self,
            review=review,
            run_at=run_at,
            next_run_at=next_run_at,
            alerts=alerts,
            status=status,
            metadata=metadata,
        )

    def _record_source_snapshot(
        self,
        *,
        question_id: str,
        watch: dict[str, Any],
        retrieved_at: str,
        signature: str | None,
        previous_signature: str | None,
        changed: bool,
        status: str,
        error_message: str | None,
        observed_content: Any | None = None,
    ) -> dict[str, Any]:
        return _refresh._record_source_snapshot(self, question_id=question_id, watch=watch, retrieved_at=retrieved_at, signature=signature, previous_signature=previous_signature, changed=changed, status=status, error_message=error_message, observed_content=observed_content)

    def _record_autopilot_run(
        self,
        *,
        policy_id: str,
        question_id: str,
        started_at: str,
        finished_at: str,
        status: str,
        trigger_reason: str,
        sources_checked: int,
        sources_changed: int,
        material_changes: int,
        proposal_id: str | None,
        forecast_snapshot_id: str | None,
        alerts_created: int,
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        return _autopilot._record_autopilot_run(self, policy_id=policy_id, question_id=question_id, started_at=started_at, finished_at=finished_at, status=status, trigger_reason=trigger_reason, sources_checked=sources_checked, sources_changed=sources_changed, material_changes=material_changes, proposal_id=proposal_id, forecast_snapshot_id=forecast_snapshot_id, alerts_created=alerts_created, diagnostics=diagnostics)

    @staticmethod
    def _autopilot_material_change(policy: dict[str, Any], changed: list[dict[str, Any]]) -> bool:
        return _autopilot._autopilot_material_change(policy=policy, changed=changed)

    @staticmethod
    def _default_autopilot_rationale(
        *,
        changed: list[dict[str, Any]],
        current: ForecastSnapshot,
    ) -> str:
        return _autopilot._default_autopilot_rationale(changed=changed, current=current)

    def _autopilot_guardrail_violations(
        self,
        *,
        policy: dict[str, Any],
        prior_payload: Any,
        proposed_payload: Any,
        source_snapshots: list[dict[str, Any]],
    ) -> list[str]:
        return _autopilot._autopilot_guardrail_violations(self, policy=policy, prior_payload=prior_payload, proposed_payload=proposed_payload, source_snapshots=source_snapshots)

    @staticmethod
    def _is_learning_alert_reason(reason: str | None) -> bool:
        return _alerts._is_learning_alert_reason(reason=reason)

    def create_alert(
        self,
        *,
        severity: str,
        scope_type: str,
        scope_ref: str,
        reason: str,
        recommended_action: str,
        refresh_action: bool = False,
        now: str | None = None,
    ) -> AlertEvent:
        return _alerts.create_alert(self, severity=severity, scope_type=scope_type, scope_ref=scope_ref, reason=reason, recommended_action=recommended_action, refresh_action=refresh_action, now=now)

    def enqueue_resolution_proposal(self, *, question_id: str, outcome: Any, rationale: str, confirm_command: str | None = None) -> AlertEvent:
        return _alerts.enqueue_resolution_proposal(self, question_id=question_id, outcome=outcome, rationale=rationale, confirm_command=confirm_command)

    def enqueue_approval_request(self, *, job_id: str, job_type: str, action_class: str, detail: str, run_mode: str, confirm_command: str | None = None) -> AlertEvent:
        return _alerts.enqueue_approval_request(self, job_id=job_id, job_type=job_type, action_class=action_class, detail=detail, run_mode=run_mode, confirm_command=confirm_command)

    def get_alert(self, alert_id: str) -> AlertEvent:
        return _alerts.get_alert(self, alert_id=alert_id)

    def list_alerts(self, *, unresolved_only: bool = True) -> list[AlertEvent]:
        return _alerts.list_alerts(self, unresolved_only=unresolved_only)

    def acknowledge_alert(self, alert_id: str, *, acknowledged_at: str | None = None, ack_note: str | None = None, disposition: str | None = None) -> AlertEvent:
        return _alerts.acknowledge_alert(self, alert_id=alert_id, acknowledged_at=acknowledged_at, ack_note=ack_note, disposition=disposition)

    def record_alert_attempt(self, alert_id: str, *, now: str | None = None) -> AlertEvent:
        return _alerts.record_alert_attempt(self, alert_id=alert_id, now=now)

    def dismiss_alerts(
        self,
        alert_ids: "Iterable[str]",
        *,
        note: str,
        actor: str,
        dismiss_reason: str | None = None,
        ttl_days: int | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        return _alerts.dismiss_alerts(self, alert_ids=alert_ids, note=note, actor=actor, dismiss_reason=dismiss_reason, ttl_days=ttl_days, now=now)

    def active_dismissal_keys(self, *, now: str | None = None) -> "set[tuple[str, str]]":
        return _alerts.active_dismissal_keys(self, now=now)

    def reconcile_alerts(self, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return _alerts.reconcile_alerts(self, now=now, dry_run=dry_run)

    def escalate_aged_alerts(self, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return _alerts.escalate_aged_alerts(self, now=now, dry_run=dry_run)

    def collapse_duplicate_alerts(self, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return _alerts.collapse_duplicate_alerts(self, now=now, dry_run=dry_run)

    def self_check(
        self,
        *,
        question_id: str | None = None,
        domain: str | None = None,
        topic: str | None = None,
        horizon: str | None = None,
        portfolio: str | None = None,
        stale_days: int = 7,
        stale: bool = True,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
    ) -> list[AlertEvent]:
        return _alerts.self_check(self, question_id=question_id, domain=domain, topic=topic, horizon=horizon, portfolio=portfolio, stale_days=stale_days, stale=stale, now=now, auto_score=auto_score, auto_postmortem=auto_postmortem, confidence_below=confidence_below, confidence_above=confidence_above, large_delta_threshold=large_delta_threshold)

    def pilot_report(
        self,
        *,
        min_questions: int = 3,
        min_structured_source_questions: int = 1,
        min_scores: int = 1,
        min_postmortems: int = 1,
        min_scheduled_reviews: int = 1,
        min_scheduled_review_runs: int = 1,
    ) -> dict[str, Any]:
        """Summarize whether a tester ledger has the artifacts needed for a pilot."""

        min_questions = max(int(min_questions), 0)
        min_structured_source_questions = max(int(min_structured_source_questions), 0)
        min_scores = max(int(min_scores), 0)
        min_postmortems = max(int(min_postmortems), 0)
        min_scheduled_reviews = max(int(min_scheduled_reviews), 0)
        min_scheduled_review_runs = max(int(min_scheduled_review_runs), 0)

        questions = self.list_questions()
        status_counts = Counter(question.status for question in questions)
        domain_counts = Counter(question.domain or "unscoped" for question in questions)
        topic_counts: Counter[str] = Counter()
        source_type_counts: Counter[str] = Counter()
        score_origin_counts: Counter[str] = Counter()
        question_rows: list[dict[str, Any]] = []
        questions_with_forecasts = 0
        questions_with_evidence = 0
        questions_with_structured_sources = 0
        questions_with_models = 0
        questions_with_reference_classes = 0

        scores = self.list_scores()
        score_counts_by_question = Counter(score.question_id for score in scores)
        score_origin_counts.update(score.forecast_origin for score in scores)
        evidence_sources_by_question: defaultdict[str, Counter[str]] = defaultdict(Counter)
        with self._connect() as conn:
            snapshot_counts = {
                row["question_id"]: int(row["n"])
                for row in conn.execute(
                    "SELECT question_id, COUNT(*) AS n FROM forecast_snapshots GROUP BY question_id"
                ).fetchall()
            }
            for row in conn.execute(
                "SELECT question_id, source_type, COUNT(*) AS n "
                "FROM evidence_items GROUP BY question_id, source_type"
            ).fetchall():
                evidence_sources_by_question[row["question_id"]][
                    row["source_type"] or "unknown"
                ] = int(row["n"])
            model_run_counts = {
                row["question_id"]: int(row["n"])
                for row in conn.execute(
                    "SELECT question_id, COUNT(*) AS n FROM model_runs GROUP BY question_id"
                ).fetchall()
            }
            reference_class_counts = {
                row["question_id"]: int(row["n"])
                for row in conn.execute(
                    "SELECT question_id, COUNT(*) AS n FROM reference_classes GROUP BY question_id"
                ).fetchall()
            }
            postmortem_counts = {
                row["question_id"]: int(row["n"])
                for row in conn.execute(
                    "SELECT question_id, COUNT(*) AS n FROM postmortems GROUP BY question_id"
                ).fetchall()
            }
            resolved_question_ids = {
                row["question_id"]
                for row in conn.execute("SELECT DISTINCT question_id FROM resolutions").fetchall()
            }
            scheduled_review_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM scheduled_reviews").fetchone()["n"]
            )
            enabled_scheduled_review_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM scheduled_reviews WHERE enabled = 1"
                ).fetchone()["n"]
            )
            scheduled_review_run_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM scheduled_review_runs").fetchone()["n"]
            )
            watched_source_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM watched_sources").fetchone()["n"]
            )
            autopilot_policy_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM autopilot_policies").fetchone()["n"]
            )
            active_autopilot_policy_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM autopilot_policies WHERE enabled = 1"
                ).fetchone()["n"]
            )
            autopilot_run_count = int(
                conn.execute("SELECT COUNT(*) AS n FROM autopilot_runs").fetchone()["n"]
            )
            pending_autopilot_proposal_count = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM forecast_update_proposals WHERE status = 'pending'"
                ).fetchone()["n"]
            )
            alert_counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN acknowledged_at IS NULL THEN 1 ELSE 0 END) AS open, "
                "SUM(CASE WHEN acknowledged_at IS NULL AND "
                "reason LIKE 'domain_error_profile_applies:%' THEN 1 ELSE 0 END) AS learned "
                "FROM alert_events"
            ).fetchone()
            lesson_counts = conn.execute(
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) AS active "
                "FROM calibration_lessons"
            ).fetchone()
            postmortem_count = sum(postmortem_counts.values())

        non_manual_source_types = {"manual_note", "note"}
        for question in questions:
            snapshot_count = snapshot_counts.get(question.id, 0)
            source_types = evidence_sources_by_question[question.id]
            model_run_count = model_run_counts.get(question.id, 0)
            reference_class_count = reference_class_counts.get(question.id, 0)
            question_postmortem_count = postmortem_counts.get(question.id, 0)
            question_score_count = score_counts_by_question.get(question.id, 0)
            structured_source_types = sorted(
                source_type for source_type in source_types if source_type not in non_manual_source_types
            )

            if snapshot_count:
                questions_with_forecasts += 1
            if source_types:
                questions_with_evidence += 1
            if structured_source_types:
                questions_with_structured_sources += 1
            if model_run_count:
                questions_with_models += 1
            if reference_class_count:
                questions_with_reference_classes += 1
            for topic in question.topics:
                topic_counts[topic] += 1
            source_type_counts.update(source_types)

            question_rows.append(
                {
                    "id": question.id,
                    "title": question.title,
                    "status": question.status,
                    "domain": question.domain,
                    "topics": question.topics,
                    "forecast_count": snapshot_count,
                    "evidence_count": sum(source_types.values()),
                    "source_types": dict(sorted(source_types.items())),
                    "structured_source_types": structured_source_types,
                    "reference_class_count": reference_class_count,
                    "model_run_count": model_run_count,
                    "score_count": question_score_count,
                    "postmortem_count": question_postmortem_count,
                    "resolved": question.id in resolved_question_ids,
                }
            )

        alert_count = int(alert_counts["total"] or 0)
        open_alert_count = int(alert_counts["open"] or 0)
        open_learned_error_review_alert_count = int(alert_counts["learned"] or 0)
        calibration_lesson_count = int(lesson_counts["total"] or 0)
        active_calibration_lesson_count = int(lesson_counts["active"] or 0)

        def check(
            check_id: str,
            label: str,
            observed: int,
            required: int,
            action: str,
        ) -> dict[str, Any]:
            passed = observed >= required
            return {
                "id": check_id,
                "label": label,
                "observed": observed,
                "required": required,
                "passed": passed,
                "recommended_action": "" if passed else action,
            }

        def max_check(
            check_id: str,
            label: str,
            observed: int,
            maximum: int,
            action: str,
        ) -> dict[str, Any]:
            passed = observed <= maximum
            return {
                "id": check_id,
                "label": label,
                "observed": observed,
                "required": maximum,
                "passed": passed,
                "recommended_action": "" if passed else action,
            }

        checks = [
            check(
                "questions_created",
                "scoreable questions created",
                len(questions),
                min_questions,
                "Create more scoreable questions with `forecast new ...`.",
            ),
            check(
                "forecast_updates_recorded",
                "questions with at least one forecast update",
                questions_with_forecasts,
                min_questions,
                "Record probability updates with `forecast update <id> ...`.",
            ),
            check(
                "evidence_recorded",
                "questions with timestamped evidence",
                questions_with_evidence,
                min_questions,
                "Add evidence with `forecast evidence add <id> ...` or `forecast import ... --question <id>`.",
            ),
            check(
                "structured_sources_used",
                "questions with non-manual source evidence",
                questions_with_structured_sources,
                min_structured_source_questions,
                "Import at least one structured source with `forecast sources` then `forecast import ... --question <id>`.",
            ),
            check(
                "scheduled_self_checks",
                "scheduled self-checks configured",
                scheduled_review_count,
                min_scheduled_reviews,
                "Schedule review work with `forecast schedule add --question <id> ...`.",
            ),
            check(
                "scheduled_self_check_runs",
                "scheduled self-checks run",
                scheduled_review_run_count,
                min_scheduled_review_runs,
                "Run due schedule rows with `forecast schedule run --due`, or install the cron bridge with `forecast schedule install-cron`.",
            ),
            check(
                "live_scores_recorded",
                "resolved live forecasts scored",
                score_origin_counts.get("live", 0),
                min_scores,
                "Resolve and score at least one forecast with `forecast resolve <id> ...` and `forecast score <id>`.",
            ),
            check(
                "postmortems_recorded",
                "postmortems recorded",
                postmortem_count,
                min_postmortems,
                "Write at least one postmortem with `forecast postmortem <id> ...`.",
            ),
            max_check(
                "learned_error_reviews_cleared",
                "open learned-error profile review alerts",
                open_learned_error_review_alert_count,
                0,
                "Run the bounded warning automode worker; its learned-error reviewer persists a substantive assessment and decision before closing each alert. Do not bare-ack these reviews.",
            ),
        ]
        passed_count = sum(1 for row in checks if row["passed"])
        next_actions = [row["recommended_action"] for row in checks if row["recommended_action"]]
        pilot_status = "pilot_exit_ready" if passed_count == len(checks) else "collecting_pilot_evidence"

        return {
            "product": _export_metadata(),
            "generated_at": utc_now_iso(),
            "pilot_status": pilot_status,
            "passed_checks": passed_count,
            "total_checks": len(checks),
            "checks": checks,
            "next_actions": next_actions,
            "summary": {
                "question_count": len(questions),
                "question_status_counts": dict(sorted(status_counts.items())),
                "questions_with_forecasts": questions_with_forecasts,
                "questions_with_evidence": questions_with_evidence,
                "questions_with_structured_sources": questions_with_structured_sources,
                "questions_with_models": questions_with_models,
                "questions_with_reference_classes": questions_with_reference_classes,
                "score_counts_by_origin": dict(sorted(score_origin_counts.items())),
                "postmortem_count": postmortem_count,
                "scheduled_review_count": scheduled_review_count,
                "enabled_scheduled_review_count": enabled_scheduled_review_count,
                "scheduled_review_run_count": scheduled_review_run_count,
                "watched_source_count": watched_source_count,
                "autopilot_policy_count": autopilot_policy_count,
                "active_autopilot_policy_count": active_autopilot_policy_count,
                "autopilot_run_count": autopilot_run_count,
                "pending_autopilot_proposal_count": pending_autopilot_proposal_count,
                "alert_count": alert_count,
                "open_alert_count": open_alert_count,
                "open_learned_error_review_alert_count": open_learned_error_review_alert_count,
                "calibration_lesson_count": calibration_lesson_count,
                "active_calibration_lesson_count": active_calibration_lesson_count,
            },
            "domains": dict(sorted(domain_counts.items())),
            "topics": dict(sorted(topic_counts.items())),
            "source_types": dict(sorted(source_type_counts.items())),
            "questions": question_rows,
        }

    def export_question(self, question_id: str, *, fmt: str = "markdown") -> str:
        return _exports.export_question(self, question_id=question_id, fmt=fmt)

    def export_all(self, *, fmt: str = "markdown") -> str:
        return _exports.export_all(self, fmt=fmt)

    def import_packet(self, packet: dict[str, Any], *, conflict: str = "error") -> dict[str, Any]:
        return _exports.import_packet(self, packet=packet, conflict=conflict)

    def _question_packets_from_import(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        return _exports._question_packets_from_import(self, packet=packet)

    def _import_question_packet(
        self,
        conn: sqlite3.Connection,
        packet: dict[str, Any],
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        return _exports._import_question_packet(self, conn=conn, packet=packet, conflict=conflict, summary=summary, seen=seen)

    def _import_packet_rows(
        self,
        conn: sqlite3.Connection,
        table: str,
        rows: Any,
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        return _exports._import_packet_rows(self, conn=conn, table=table, rows=rows, conflict=conflict, summary=summary, seen=seen)

    def _insert_packet_row(
        self,
        conn: sqlite3.Connection,
        table: str,
        row: dict[str, Any],
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        return _exports._insert_packet_row(self, conn=conn, table=table, row=row, conflict=conflict, summary=summary, seen=seen)

    def _existing_score(self, forecast_id: str, resolution_id: str) -> ScoreRecord | None:
        return _scoring._existing_score(self, forecast_id=forecast_id, resolution_id=resolution_id)

    def _validate_evidence_refs(
        self,
        question_id: str,
        evidence_refs: list[str],
        evidence_cutoff: str | None,
    ) -> None:
        return _snapshots._validate_evidence_refs(self, question_id=question_id, evidence_refs=evidence_refs, evidence_cutoff=evidence_cutoff)

    def _validate_question_scoped_refs(
        self,
        question_id: str,
        refs: list[str],
        getter,
        label: str,
    ) -> None:
        for ref in refs:
            obj = getter(ref)
            if obj["question_id"] != question_id:
                raise ValidationError(f"{label} {ref} does not belong to question {question_id}")

    def _affected_records_for_correction(
        self,
        target_type: str,
        target_id: str,
    ) -> tuple[list[str], list[str], list[str]]:
        return _resolutions._affected_records_for_correction(self, target_type=target_type, target_id=target_id)

    def _invalidate_learning_records_for_correction(
        self,
        conn: sqlite3.Connection,
        *,
        correction_id: str,
        score_refs: list[str],
        postmortem_refs: list[str],
        lesson_refs: list[str],
    ) -> None:
        return _resolutions._invalidate_learning_records_for_correction(self, conn=conn, correction_id=correction_id, score_refs=score_refs, postmortem_refs=postmortem_refs, lesson_refs=lesson_refs)

    def _disable_backtest_calibration(self, run_id: str) -> None:
        return _backtest._disable_backtest_calibration(self, run_id=run_id)

    def _run_backtest_case(
        self,
        *,
        run_id: str,
        case: dict[str, Any],
        default_cutoff: str | None,
        allow_calibration_memory: bool,
        leak_judge_runner: "LeakJudgeRunner | None" = None,
    ) -> dict[str, Any]:
        return _backtest._run_backtest_case(self, run_id=run_id, case=case, default_cutoff=default_cutoff, allow_calibration_memory=allow_calibration_memory, leak_judge_runner=leak_judge_runner)

    def _run_leak_judge(
        self,
        *,
        runner: "LeakJudgeRunner",
        case: dict[str, Any],
        question: ForecastQuestion,
        evidence_cutoff: str | None,
    ) -> dict[str, Any]:
        return _backtest._run_leak_judge(self, runner=runner, case=case, question=question, evidence_cutoff=evidence_cutoff)

    # AIA P1.2 — read-only leakage robustness re-scores.
    _RESCORE_MODES = ("baseline", "filtered", "worst_case")

    def rescore_backtest_run(self, run_id: str, mode: str) -> dict[str, Any]:
        return _backtest.rescore_backtest_run(self, run_id=run_id, mode=mode)

    @staticmethod
    def _rescore_brier_summary(briers: list[float]) -> dict[str, Any]:
        return _backtest._rescore_brier_summary(briers=briers)

    def _backtest_case_question_key(self, case: dict[str, Any]) -> str:
        return _backtest._backtest_case_question_key(self, case=case)

    def _build_leak_robustness_summary(
        self,
        run_id: str,
        *,
        content_flagged_cases: int,
    ) -> dict[str, Any]:
        return _backtest._build_leak_robustness_summary(self, run_id=run_id, content_flagged_cases=content_flagged_cases)

    def get_backtest_case(self, case_id: str) -> dict[str, Any]:
        return _backtest.get_backtest_case(self, case_id=case_id)

    @staticmethod
    def _backtest_snapshot_components(case: dict[str, Any]) -> dict[str, Any]:
        return _backtest._backtest_snapshot_components(case=case)

    @staticmethod
    def _backtest_snapshot_metadata(case: dict[str, Any]) -> dict[str, Any]:
        return _backtest._backtest_snapshot_metadata(case=case)

    @staticmethod
    def _optional_unit_float(value: Any) -> float | None:
        return _backtest._optional_unit_float(value=value)

    def _backtest_case_baselines(
        self,
        case: dict[str, Any],
        outcome_space: OutcomeSpace,
    ) -> list[dict[str, Any]]:
        return _backtest._backtest_case_baselines(self, case=case, outcome_space=outcome_space)

    def _has_baseline(self, baselines: list[dict[str, Any]], baseline_type: str, source: str) -> bool:
        return _backtest._has_baseline(self, baselines=baselines, baseline_type=baseline_type, source=source)

    def _validate_probability_payload(self, value: Any, outcome_space: OutcomeSpace | None = None) -> Any:
        outcome_type = (outcome_space.type if outcome_space else "binary")
        if isinstance(value, bool):
            raise ValidationError("probability must be numeric, not boolean")
        if isinstance(value, (int, float)):
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValidationError("forecast value must be finite")
            if outcome_type == "numeric":
                return numeric
            if not (0 <= numeric <= 1):
                raise ValidationError("probability must be between 0 and 1")
            return numeric
        if isinstance(value, dict):
            if not value:
                raise ValidationError("forecast distribution cannot be empty")
            normalized: dict[str, float] = {}
            for key, raw in value.items():
                # A null entry (e.g. an omitted quantile) is simply dropped rather
                # than failing the whole distribution.
                if raw is None:
                    continue
                numeric = _coerce_distribution_number(raw)
                if numeric is None:
                    raise ValidationError(
                        f"distribution value for '{key}' must be a number "
                        f"(got {type(raw).__name__}: {raw!r}); use numeric quantiles/moments, "
                        f"e.g. {{\"mean\": 0.36, \"q05\": 0.05, \"q50\": 0.35, \"q95\": 0.75}}"
                    )
                if not math.isfinite(numeric):
                    raise ValidationError(f"distribution value for '{key}' must be finite")
                # "thesis" carries a mixed payload (health in [0,1] plus a 0-100
                # score and score-scale quantiles), so it is exempt from the
                # [0,1] clamp like numeric/distribution.
                if outcome_type not in {"numeric", "distribution", "thesis"} and not (0 <= numeric <= 1):
                    raise ValidationError(f"distribution value for '{key}' must be between 0 and 1")
                normalized[str(key)] = numeric
            if not normalized:
                raise ValidationError("forecast distribution cannot be empty")
            return normalized
        raise ValidationError("forecast update requires a probability or distribution")

    def _scoreability_issues(
        self,
        title: str,
        resolution_criteria: str,
        outcome_space: OutcomeSpace,
    ) -> list[str]:
        return _questions._scoreability_issues(self, title=title, resolution_criteria=resolution_criteria, outcome_space=outcome_space)

    def _binary_outcome_value(
        self, score: ScoreRecord, outcome_space: OutcomeSpace
    ) -> float | None:
        """Return 1.0 if the score's question resolved yes, 0.0 if no, else None
        (unknown/ambiguous outcome). Used for the reliability curve."""

        try:
            resolution = self.get_resolution(score.resolution_id)
        except LedgerNotFoundError:
            return None
        label = str(resolution.outcome).strip().lower()
        yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
        no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
        choices = [str(choice).lower() for choice in outcome_space.choices]
        if label in yes_labels or (choices and label == choices[0]):
            return 1.0
        if label in no_labels or (len(choices) > 1 and label == choices[1]):
            return 0.0
        return None

    def _probability_for_outcome(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> float:
        outcome_label = str(outcome).strip().lower()
        if isinstance(probability_or_distribution, (int, float)):
            yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
            no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
            if outcome_label in yes_labels or outcome_label == str(outcome_space.choices[0]).lower():
                return float(probability_or_distribution)
            if outcome_label in no_labels or outcome_label == str(outcome_space.choices[1]).lower():
                return 1.0 - float(probability_or_distribution)
            raise ValidationError(f"binary outcome is not recognized: {outcome}")
        if isinstance(probability_or_distribution, dict):
            lowered = {str(key).lower(): float(value) for key, value in probability_or_distribution.items()}
            if outcome_label not in lowered:
                raise ValidationError(f"outcome {outcome!r} is not present in the forecast distribution")
            return lowered[outcome_label]
        raise ValidationError("unsupported probability payload")

    def _score_forecast_payload(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any]:
        if outcome_space.type in {"binary", "categorical"}:
            probability = self._probability_for_outcome(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            brier = self._brier_score(
                probability_or_distribution,
                outcome,
                outcome_space,
            )
            log_score = self._log_score(probability)
            return {
                "brier_score": brier,
                "log_score": log_score,
                "proper_score": brier,
                "score_rule": "brier",
                "calibration_bucket": self._probability_bucket(probability),
                "notes": "Brier score against confirmed resolution.",
            }

        if outcome_space.type == "numeric":
            # A dict payload with real distributional shape (quantiles / CDF
            # thresholds / mean+sd) is scored with CRPS — a proper score for the
            # whole predictive distribution, not just its mean point.
            if isinstance(probability_or_distribution, dict):
                crps = self._crps_score(probability_or_distribution, outcome, outcome_space)
                if crps is not None:
                    return crps
            forecast_value = self._numeric_forecast_point(probability_or_distribution)
            outcome_value = self._numeric_outcome(outcome)
            score, rule = self._numeric_squared_error(forecast_value, outcome_value, outcome_space)
            return {
                "brier_score": None,
                "log_score": None,
                "proper_score": score,
                "score_rule": rule,
                "calibration_bucket": self._numeric_bucket(forecast_value, outcome_space),
                "notes": f"{rule} against confirmed numeric resolution.",
            }

        if outcome_space.type in {"distribution", "thesis"}:
            if isinstance(probability_or_distribution, (int, float)):
                forecast_value = self._numeric_forecast_point(probability_or_distribution)
                outcome_value = self._numeric_outcome(outcome)
                score, rule = self._numeric_squared_error(forecast_value, outcome_value, outcome_space)
                return {
                    "brier_score": None,
                    "log_score": None,
                    "proper_score": score,
                    "score_rule": rule,
                    "calibration_bucket": self._numeric_bucket(forecast_value, outcome_space),
                    "notes": f"{rule} for distributional point summary against confirmed resolution.",
                }
            if isinstance(probability_or_distribution, dict):
                # CRPS is the proper score for a continuous predictive
                # distribution; it REFUSES (None) a candidate-share vote dict,
                # which falls through to the vote-share vector scorer below.
                crps = self._crps_score(probability_or_distribution, outcome, outcome_space)
                if crps is not None:
                    return crps
                normal = self._normal_distribution_score(probability_or_distribution, outcome, outcome_space)
                if normal is not None:
                    return normal
                # Vote-share pattern: a candidate-SHARE dict forecast scored against a
                # candidate-SHARE dict outcome (e.g. {"Lasher": .39, ...} vs certified
                # {"Lasher": 39.2, ...}). The fallthrough below treats the dict OUTCOME
                # as a categorical label, which mis-scores / fails — the bug behind the
                # hand-rolled manual scores. Score it as a vector MAE/RMSE in
                # percentage points so vote-share forecasts are machine-scoreable
                # (lesson cl_ec9059c809ba). None -> no shared candidates -> fall through.
                if isinstance(outcome, dict):
                    vector = self._vote_share_vector_score(probability_or_distribution, outcome)
                    if vector is not None:
                        return vector
                probability = self._probability_for_outcome(
                    probability_or_distribution,
                    outcome,
                    outcome_space,
                )
                brier = self._brier_score(
                    probability_or_distribution,
                    outcome,
                    outcome_space,
                )
                log_score = self._log_score(probability)
                return {
                    "brier_score": brier,
                    "log_score": log_score,
                    "proper_score": log_score,
                    "score_rule": "discrete_distribution_log_score",
                    "calibration_bucket": self._probability_bucket(probability),
                    "notes": "Discrete distribution log score against confirmed resolution.",
                }

        raise ValidationError(f"scoring is not implemented for outcome type: {outcome_space.type}")

    def _brier_score(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> float:
        return _scoring._brier_score(self, probability_or_distribution=probability_or_distribution, outcome=outcome, outcome_space=outcome_space)

    def _log_score(self, resolved_probability: float) -> float:
        return _scoring._log_score(self, resolved_probability=resolved_probability)

    def _numeric_forecast_point(self, probability_or_distribution: Any) -> float:
        if isinstance(probability_or_distribution, bool):
            raise ValidationError("numeric forecast value must be numeric, not boolean")
        if isinstance(probability_or_distribution, (int, float)):
            value = float(probability_or_distribution)
        elif isinstance(probability_or_distribution, dict):
            for key in ("mean", "expected", "value", "point"):
                if key in probability_or_distribution:
                    value = float(probability_or_distribution[key])
                    break
            else:
                raise ValidationError("numeric distribution requires a mean, expected, value, or point field")
        else:
            raise ValidationError("numeric forecast value must be numeric")
        if not math.isfinite(value):
            raise ValidationError("numeric forecast value must be finite")
        return value

    def _numeric_outcome(self, outcome: Any) -> float:
        if isinstance(outcome, bool):
            raise ValidationError("numeric outcome must be numeric, not boolean")
        try:
            value = float(outcome)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"numeric outcome is not recognized: {outcome!r}") from exc
        if not math.isfinite(value):
            raise ValidationError("numeric outcome must be finite")
        return value

    def _numeric_squared_error(
        self,
        forecast_value: float,
        outcome_value: float,
        outcome_space: OutcomeSpace,
    ) -> tuple[float, str]:
        error = forecast_value - outcome_value
        bounds = outcome_space.bounds or []
        if len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if math.isfinite(low) and math.isfinite(high) and high > low:
                return (error / (high - low)) ** 2, "normalized_squared_error"
        return error**2, "squared_error"

    def _numeric_bucket(self, value: float, outcome_space: OutcomeSpace) -> str:
        return _scoring._numeric_bucket(self, value=value, outcome_space=outcome_space)

    def _vote_share_vector_score(self, forecast: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
        return _scoring._vote_share_vector_score(self, forecast=forecast, outcome=outcome)

    def _normal_distribution_score(
        self,
        probability_or_distribution: dict[str, Any],
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any] | None:
        return _scoring._normal_distribution_score(self, probability_or_distribution=probability_or_distribution, outcome=outcome, outcome_space=outcome_space)

    def _crps_score(
        self,
        probability_or_distribution: Any,
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any] | None:
        return _scoring._crps_score(self, probability_or_distribution=probability_or_distribution, outcome=outcome, outcome_space=outcome_space)

    def _probability_bucket(self, probability: float) -> str:
        return _scoring._probability_bucket(self, probability=probability)

    def _horizon_matches(self, horizon_days: float | None, horizon: str | None) -> bool:
        if horizon is None:
            return True
        if horizon_days is None:
            return False
        raw = horizon.strip().lower()
        if not raw:
            return True
        if raw.endswith("d"):
            raw = raw[:-1]
        try:
            if "-" in raw:
                start, end = raw.split("-", 1)
                return float(start) <= horizon_days <= float(end)
            return horizon_days <= float(raw)
        except ValueError as exc:
            raise ValidationError("horizon must be a day count or range like 30 or 30-90") from exc

    def _sharpness(self, probability_or_distribution: Any) -> float | None:
        if isinstance(probability_or_distribution, (int, float)):
            return abs(float(probability_or_distribution) - 0.5) * 2
        if isinstance(probability_or_distribution, dict) and probability_or_distribution:
            # A vote-share PMF's sharpness is its LEADING share, normalized to a
            # 0-1 fraction. Without this, a percentage-point payload (Clacton's
            # {Farage: 67, ...}) returned 67.0, making confidence_committed (floor
            # 0.05) vacuously satisfied for every share board. candidate_shares is
            # the shared extractor (it divides pp payloads by 100), so the gate and
            # the metric agree on the scale.
            try:
                from forecasting.hooks.distribution import candidate_shares

                shares = candidate_shares(probability_or_distribution)
            except Exception:
                shares = None
            if shares:
                return max(shares.values())
            numeric = [
                float(value)
                for value in probability_or_distribution.values()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            ]
            if numeric:
                return max(numeric)
        return None

    def _archive_file_evidence_snapshot(
        self,
        *,
        question_id: str,
        evidence_id: str,
        source_file_path: Path,
    ) -> str:
        snapshot_dir = self.db_path.parent / "evidence_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{evidence_id}{source_file_path.suffix}"
        shutil.copy2(source_file_path, snapshot_path)
        return str(snapshot_path)

    def _archive_url_evidence_snapshot(
        self,
        *,
        question_id: str,
        evidence_id: str,
        source_url: str,
    ) -> dict[str, Any] | None:
        if not source_url.startswith(("http://", "https://")):
            return None
        snapshot_dir = self.db_path.parent / "evidence_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{evidence_id}.html"
        metadata_path = snapshot_dir / f"{evidence_id}.snapshot.json"
        request = Request(source_url, headers={"User-Agent": f"{PRODUCT_SLUG}/1"})
        try:
            with urlopen(request, timeout=5) as response:
                content = response.read(2_000_000)
                status = getattr(response, "status", None)
                content_type = response.headers.get("Content-Type")
        except (OSError, URLError, TimeoutError):
            return None
        snapshot_path.write_bytes(content)
        # Detect bot-block / interstitial pages disguised as HTTP 200
        # (Cloudflare challenge, DataDome, cookie wall, JS-required, …) so
        # downstream consumers don't treat the block markup as evidence.
        block_info = None
        try:
            from forecasting.source_adapters import detect_block_page

            decoded: str
            if isinstance(content_type, str) and ("text" in content_type.lower() or "html" in content_type.lower() or "json" in content_type.lower()):
                decoded = content.decode("utf-8", errors="replace")
            elif content_type is None:
                decoded = content[:8192].decode("utf-8", errors="replace")
            else:
                decoded = ""
            if decoded:
                block_info = detect_block_page(decoded, status=status)
        except Exception:
            block_info = None
        metadata = {
            "url": source_url,
            "captured_at": utc_now_iso(),
            "status": status,
            "content_type": content_type,
            "snapshot_path": str(snapshot_path),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        if block_info is not None:
            metadata["blocked"] = True
            metadata["block_reason"] = block_info["reason"]
            metadata["block_signal"] = block_info["signal"]
        metadata_path.write_text(json_dumps(metadata), encoding="utf-8")
        metadata["metadata_path"] = str(metadata_path)
        return metadata

    def _archive_resolution_source_snapshot(
        self,
        *,
        question_id: str,
        resolution_id: str,
        source_file_path: Path,
    ) -> str:
        snapshot_dir = self.db_path.parent / "resolution_snapshots" / question_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{resolution_id}{source_file_path.suffix}"
        shutil.copy2(source_file_path, snapshot_path)
        return str(snapshot_path)

    def _calibration_lessons_for_question(
        self,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return _lessons._calibration_lessons_for_question(self, scores=scores, postmortems=postmortems)

    def _domain_error_profiles_for_question(self, question: ForecastQuestion) -> list[dict[str, Any]]:
        return _lessons._domain_error_profiles_for_question(self, question=question)

    def _corrections_for_question(
        self,
        *,
        question_id: str,
        snapshots: list[ForecastSnapshot],
        evidence: list[EvidenceItem],
        assumptions: list[dict[str, Any]],
        reference_classes: list[dict[str, Any]],
        model_runs: list[dict[str, Any]],
        resolution: Resolution | None,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
        calibration_lessons: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return _resolutions._corrections_for_question(self, question_id=question_id, snapshots=snapshots, evidence=evidence, assumptions=assumptions, reference_classes=reference_classes, model_runs=model_runs, resolution=resolution, scores=scores, postmortems=postmortems, calibration_lessons=calibration_lessons)

    def _score_summary(self, scores: list[ScoreRecord]) -> dict[str, Any]:
        return _scoring._score_summary(self, scores=scores)

    def _score_breakdown(
        self,
        scores: list[ScoreRecord],
        key_fn,
    ) -> dict[str, dict[str, Any]]:
        return _scoring._score_breakdown(self, scores=scores, key_fn=key_fn)

    def _score_horizon_bucket(self, score: ScoreRecord) -> str:
        return _scoring._score_horizon_bucket(self, score=score)

    def _paired_brier_summary(
        self,
        pairs: list[tuple[ScoreRecord, ScoreRecord]],
    ) -> dict[str, Any]:
        return _scoring._paired_brier_summary(self, pairs=pairs)

    def _paired_bootstrap(
        self,
        deltas: list[float],
        mean_delta: float | None,
    ) -> dict[str, float | None]:
        return _scoring._paired_bootstrap(self, deltas=deltas, mean_delta=mean_delta)

    @staticmethod
    def _percentile(sorted_values: list[float], pct: float) -> float:
        return _scoring._percentile(sorted_values=sorted_values, pct=pct)

    def _win_rate_vs_best(
        self,
        score_pairs: dict[str, list[tuple[float | None, float | None]]],
    ) -> dict[str, Any]:
        """Fraction of resolved agent FORECASTS that beat EVERY baseline.

        score_pairs maps an agent SCORE id to the list of (agent_brier,
        baseline_brier) pairs for that forecast across the FULL baseline set (keyed
        by score id, not question id, so a question that recurs across cutoffs keeps
        each forecast paired with its own baselines). A forecast counts as a win
        when its Brier is <= EVERY baseline's Brier; forecasts with no comparable
        pair (any missing Brier) are excluded from the denominator.
        """

        wins = 0
        n = 0
        for pairs in score_pairs.values():
            comparable = [
                (agent_brier, baseline_brier)
                for agent_brier, baseline_brier in pairs
                if agent_brier is not None and baseline_brier is not None
            ]
            if not comparable:
                continue
            n += 1
            agent_brier = comparable[0][0]
            if all(agent_brier <= baseline_brier for _, baseline_brier in comparable):
                wins += 1
        return {
            "win_rate_vs_best": (wins / n) if n else None,
            "win_rate_vs_best_wins": wins,
            "win_rate_vs_best_n": n,
        }

    def _mean(self, values: list[float | None]) -> float | None:
        clean = [value for value in values if value is not None]
        return sum(clean) / len(clean) if clean else None

    def _forecast_horizon_days(self, close_time: str | None, as_of: str) -> float | None:
        return _snapshots._forecast_horizon_days(self, close_time=close_time, as_of=as_of)

    def _review_priority(self, reasons: list[str]) -> int:
        return _reviews._review_priority(self, reasons=reasons)

    def _recommended_action(self, reason: str) -> str:
        return _alerts._recommended_action(self, reason=reason)

    def _auto_postmortem_lesson(self, question: ForecastQuestion, score: ScoreRecord) -> str:
        return _resolutions._auto_postmortem_lesson(self, question=question, score=score)

    def _auto_postmortem_adjustment(self, question: ForecastQuestion, score: ScoreRecord) -> dict[str, Any]:
        return _resolutions._auto_postmortem_adjustment(self, question=question, score=score)

    def _auto_postmortem_error_tags(self, score: ScoreRecord) -> list[str]:
        return _resolutions._auto_postmortem_error_tags(self, score=score)

    def _question_in_portfolio(self, question: ForecastQuestion, portfolio: str) -> bool:
        return _alerts._question_in_portfolio(self, question=question, portfolio=portfolio)

    def _question_matches_confidence(
        self,
        question_id: str,
        *,
        confidence_below: float | None,
        confidence_above: float | None,
    ) -> bool:
        return _alerts._question_matches_confidence(self, question_id=question_id, confidence_below=confidence_below, confidence_above=confidence_above)

    @staticmethod
    def _validate_confidence_filters(
        *,
        confidence_below: float | None,
        confidence_above: float | None,
    ) -> None:
        for label, value in (
            ("confidence_below", confidence_below),
            ("confidence_above", confidence_above),
        ):
            if value is not None and not 0 <= value <= 1:
                raise ValidationError(f"{label} must be between 0 and 1")

    @staticmethod
    def _validate_probability_threshold(value: float | None, *, field_name: str) -> None:
        if value is not None and not 0 <= value <= 1:
            raise ValidationError(f"{field_name} must be between 0 and 1")

    def _latest_forecast_delta(self, question_id: str) -> float | None:
        snapshots = self.list_snapshots(question_id)
        if len(snapshots) < 2:
            return None
        previous, current = snapshots[-2], snapshots[-1]
        return self._probability_delta(
            previous.probability_or_distribution,
            current.probability_or_distribution,
        )

    @staticmethod
    def _probability_delta(previous: Any, current: Any) -> float | None:
        if isinstance(previous, bool) or isinstance(current, bool):
            return None
        if isinstance(previous, (int, float)) and isinstance(current, (int, float)):
            return float(current) - float(previous)
        return None

    def _score_probability_movement_before_close(
        self,
        score: ScoreRecord,
        scored_snapshot: ForecastSnapshot,
    ) -> float | None:
        return _scoring._score_probability_movement_before_close(self, score=score, scored_snapshot=scored_snapshot)

    @staticmethod
    def _numeric_probability(payload: Any) -> float | None:
        if isinstance(payload, bool):
            return None
        if isinstance(payload, (int, float)):
            return float(payload)
        return None

    def _snapshot_component_contributions(self, snapshot: ForecastSnapshot) -> list[dict[str, Any]]:
        return _scoring._snapshot_component_contributions(self, snapshot=snapshot)

    def _ensemble_component_rows(self, components: dict[str, Any]) -> list[dict[str, Any]]:
        raw_rows: list[Any]
        if isinstance(components.get("components"), list):
            raw_rows = components["components"]
        else:
            raw_rows = [
                {"name": name, **value}
                if isinstance(value, dict)
                else {"name": name, "probability": value}
                for name, value in components.items()
            ]
        rows: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_rows, start=1):
            if not isinstance(raw, dict):
                continue
            probability = self._numeric_probability(raw.get("probability"))
            weight = self._numeric_probability(raw.get("weight", 1.0))
            if probability is None or weight is None or weight < 0:
                continue
            rows.append(
                {
                    "name": str(raw.get("name") or raw.get("source") or f"component_{index}"),
                    "probability": probability,
                    "weight": weight,
                }
            )
        return rows

    @staticmethod
    def _is_high_impact_question(question: ForecastQuestion) -> bool:
        return _alerts._is_high_impact_question(question=question)

    def _domain_error_profile_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        return _alerts._domain_error_profile_alerts(self, domain=domain, topic=topic, questions=questions)

    def _active_questions_for_error_profile(
        self,
        profile: dict[str, Any],
        questions: list[ForecastQuestion],
    ) -> list[ForecastQuestion]:
        return _alerts._active_questions_for_error_profile(self, profile=profile, questions=questions)

    def _error_profile_question_action(
        self,
        profile: dict[str, Any],
        question: ForecastQuestion,
    ) -> str:
        return _alerts._error_profile_question_action(self, profile=profile, question=question)

    def _calibration_lesson_review_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        return _alerts._calibration_lesson_review_alerts(self, domain=domain, topic=topic, questions=questions)

    def _benchmark_evidence_alerts(self) -> list[AlertEvent]:
        return _alerts._benchmark_evidence_alerts(self)

    def _advance_cadence(
        self, now_ts: str, cadence: str, *, deadlines: list[str | None] | None = None
    ) -> str:
        return _reviews._advance_cadence(self, now_ts=now_ts, cadence=cadence, deadlines=deadlines)

    def _clamp_cadence_to_deadline(
        self, now_dt, delta: timedelta, deadlines: list[str | None] | None
    ) -> timedelta:
        return _reviews._clamp_cadence_to_deadline(self, now_dt=now_dt, delta=delta, deadlines=deadlines)

    def _cadence_due(self, last_checked_at: str | None, cadence: str | None, now_dt) -> bool:
        return _reviews._cadence_due(self, last_checked_at=last_checked_at, cadence=cadence, now_dt=now_dt)

    def _cadence_delta(self, cadence: str) -> timedelta:
        return _reviews._cadence_delta(self, cadence=cadence)

    def _row_to_question(self, row: sqlite3.Row) -> ForecastQuestion:
        return _questions._row_to_question(self, row=row)

    def _row_to_snapshot(self, row: sqlite3.Row) -> ForecastSnapshot:
        return _snapshots._row_to_snapshot(self, row=row)

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceItem:
        return _evidence._row_to_evidence(self, row=row)

    def _row_to_ingest_candidate(self, row: sqlite3.Row) -> dict[str, Any]:
        return _market_models._row_to_ingest_candidate(self, row=row)

    def _row_to_resolution(self, row: sqlite3.Row) -> Resolution:
        return _resolutions._row_to_resolution(self, row=row)

    def _row_to_score(self, row: sqlite3.Row) -> ScoreRecord:
        return _scoring._row_to_score(self, row=row)

    def _row_to_alert(self, row: sqlite3.Row) -> AlertEvent:
        return _alerts._row_to_alert(self, row=row)

    def _row_to_scheduled_review_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return _reviews._row_to_scheduled_review_run(self, row=row)

    def _row_to_model_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return _model_scoring._row_to_model_run(self, row=row)

    def _row_to_calibration_lesson(self, row: sqlite3.Row) -> dict[str, Any]:
        return _lessons._row_to_calibration_lesson(self, row=row)

    def _row_to_domain_error_profile(self, row: sqlite3.Row) -> dict[str, Any]:
        return _lessons._row_to_domain_error_profile(self, row=row)

    def _row_to_watched_source(self, row: sqlite3.Row) -> dict[str, Any]:
        return _watches._row_to_watched_source(self, row=row)

    def _row_to_source_snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        return _refresh._row_to_source_snapshot(self, row=row)

    def _row_to_autopilot_policy(self, row: sqlite3.Row) -> dict[str, Any]:
        return _autopilot._row_to_autopilot_policy(self, row=row)

    def _row_to_autopilot_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return _autopilot._row_to_autopilot_run(self, row=row)

    def _row_to_forecast_update_proposal(self, row: sqlite3.Row) -> dict[str, Any]:
        return _autopilot._row_to_forecast_update_proposal(self, row=row)

    def _row_to_backtest_case(self, row: sqlite3.Row) -> dict[str, Any]:
        return _backtest._row_to_backtest_case(self, row=row)

    def _row_to_benchmark_dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        return _backtest._row_to_benchmark_dataset(self, row=row)

    def _domain_error_profile_id(
        self,
        domain: str | None,
        topic: str | None,
        horizon: str | None,
        question_type: str | None,
    ) -> str:
        return _lessons._domain_error_profile_id(self, domain=domain, topic=topic, horizon=horizon, question_type=question_type)

    def _infer_ingest_source_type(self, source: str) -> str:
        return _market_models._infer_ingest_source_type(self, source=source)

    def _extract_ingest_metadata(self, source: str, source_type: str) -> dict[str, Any]:
        return _market_models._extract_ingest_metadata(self, source=source, source_type=source_type)

    def _extract_url_ingest_metadata(self, source: str) -> dict[str, Any]:
        return _market_models._extract_url_ingest_metadata(self, source=source)

    def _metadata_from_ingest_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return _market_models._metadata_from_ingest_payload(self, payload=payload)

    def _coerce_ingest_probability(self, value: Any) -> Any:
        return _market_models._coerce_ingest_probability(self, value=value)

    def _dedupe_ingest_baselines(self, baselines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return _market_models._dedupe_ingest_baselines(self, baselines=baselines)

    def _candidate_baseline_payloads(self, metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
        return _market_models._candidate_baseline_payloads(self, metadata=metadata)

    def _baseline_probability_value(self, baseline: dict[str, Any]) -> Any:
        return _market_models._baseline_probability_value(self, baseline=baseline)

    def _normalize_ingest_baseline(self, baseline: dict[str, Any]) -> dict[str, Any]:
        return _market_models._normalize_ingest_baseline(self, baseline=baseline)

    def _metadata_from_text_source(self, text: str) -> dict[str, Any]:
        return _market_models._metadata_from_text_source(self, text=text)

    def _metadata_from_html_source(self, text: str) -> dict[str, Any]:
        return _market_models._metadata_from_html_source(self, text=text)

    def _infer_watch_source_type(self, source: str) -> str:
        return _watches._infer_watch_source_type(self, source=source)

    def _rss_relevance_filters(self, metadata: dict[str, Any]) -> dict[str, list[str]]:
        return _source_signatures._rss_relevance_filters(self, metadata=metadata)

    def _rss_filter_terms(self, value: Any) -> list[str]:
        return _source_signatures._rss_filter_terms(self, value=value)

    def _rss_filter_cli_args(self, filters: dict[str, list[str]]) -> str:
        return _source_signatures._rss_filter_cli_args(self, filters=filters)

    def _shell_arg(self, value: str) -> str:
        return _source_signatures._shell_arg(self, value=value)

    def _source_signature(
        self,
        source: str,
        source_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        return _source_signatures._source_signature(self, source=source, source_type=source_type, metadata=metadata)

    def _url_source_signature(self, source: str) -> str:
        return _source_signatures._url_source_signature(self, source=source)

    def _rss_source_signature(self, source: str, *, metadata: dict[str, Any] | None = None) -> str:
        return _source_signatures._rss_source_signature(self, source=source, metadata=metadata)

    def _gdelt_source_signature(self, source: str) -> str:
        return _source_signatures._gdelt_source_signature(self, source=source)

    def _fivethirtyeight_source_signature(self, source: str) -> str:
        return _source_signatures._fivethirtyeight_source_signature(self, source=source)

    def _github_source_signature(self, source: str) -> str:
        return _source_signatures._github_source_signature(self, source=source)

    def _github_repo_metadata_source_signature(self, source: str) -> str:
        return _source_signatures._github_repo_metadata_source_signature(self, source=source)

    def _github_issues_source_signature(self, source: str) -> str:
        return _source_signatures._github_issues_source_signature(self, source=source)

    def _github_commits_source_signature(self, source: str) -> str:
        return _source_signatures._github_commits_source_signature(self, source=source)

    def _github_actions_source_signature(self, source: str) -> str:
        return _source_signatures._github_actions_source_signature(self, source=source)

    def _coingecko_source_signature(self, source: str) -> str:
        return _source_signatures._coingecko_source_signature(self, source=source)

    def _pypi_source_signature(self, source: str) -> str:
        return _source_signatures._pypi_source_signature(self, source=source)

    def _npm_source_signature(self, source: str) -> str:
        return _source_signatures._npm_source_signature(self, source=source)

    def _hackernews_source_signature(self, source: str) -> str:
        return _source_signatures._hackernews_source_signature(self, source=source)

    def _reddit_source_signature(self, source: str) -> str:
        return _source_signatures._reddit_source_signature(self, source=source)

    def _bluesky_source_signature(self, source: str) -> str:
        return _source_signatures._bluesky_source_signature(self, source=source)

    def _mastodon_source_signature(self, source: str) -> str:
        return _source_signatures._mastodon_source_signature(self, source=source)

    def _federalregister_source_signature(self, source: str) -> str:
        return _source_signatures._federalregister_source_signature(self, source=source)

    def _courtlistener_source_signature(self, source: str) -> str:
        return _source_signatures._courtlistener_source_signature(self, source=source)

    def _nvd_source_signature(self, source: str) -> str:
        return _source_signatures._nvd_source_signature(self, source=source)

    def _cisa_kev_source_signature(self, source: str) -> str:
        return _source_signatures._cisa_kev_source_signature(self, source=source)

    def _openmeteo_source_signature(self, source: str) -> str:
        return _source_signatures._openmeteo_source_signature(self, source=source)

    def _airquality_source_signature(self, source: str) -> str:
        return _source_signatures._airquality_source_signature(self, source=source)

    def _weatherhistory_source_signature(self, source: str) -> str:
        return _source_signatures._weatherhistory_source_signature(self, source=source)

    def _usgs_source_signature(self, source: str) -> str:
        return _source_signatures._usgs_source_signature(self, source=source)

    def _eonet_source_signature(self, source: str) -> str:
        return _source_signatures._eonet_source_signature(self, source=source)

    def _nws_source_signature(self, source: str) -> str:
        return _source_signatures._nws_source_signature(self, source=source)

    def _clinicaltrials_source_signature(self, source: str) -> str:
        return _source_signatures._clinicaltrials_source_signature(self, source=source)

    def _openfda_source_signature(self, source: str) -> str:
        return _source_signatures._openfda_source_signature(self, source=source)

    def _pubmed_source_signature(self, source: str) -> str:
        return _source_signatures._pubmed_source_signature(self, source=source)

    def _owid_source_signature(self, source: str) -> str:
        return _source_signatures._owid_source_signature(self, source=source)

    def _who_gho_source_signature(self, source: str) -> str:
        return _source_signatures._who_gho_source_signature(self, source=source)

    def _fema_source_signature(self, source: str) -> str:
        return _source_signatures._fema_source_signature(self, source=source)

    def _fred_source_signature(self, source: str) -> str:
        return _source_signatures._fred_source_signature(self, source=source)

    def _eia_source_signature(self, source: str) -> str:
        return _source_signatures._eia_source_signature(self, source=source)

    def _treasury_source_signature(self, source: str) -> str:
        return _source_signatures._treasury_source_signature(self, source=source)

    def _bls_source_signature(self, source: str) -> str:
        return _source_signatures._bls_source_signature(self, source=source)

    def _worldbank_source_signature(self, source: str) -> str:
        return _source_signatures._worldbank_source_signature(self, source=source)

    def _imf_source_signature(self, source: str) -> str:
        return _source_signatures._imf_source_signature(self, source=source)

    def _census_source_signature(self, source: str) -> str:
        return _source_signatures._census_source_signature(self, source=source)

    def _socrata_source_signature(self, source: str) -> str:
        return _source_signatures._socrata_source_signature(self, source=source)

    def _ckan_source_signature(self, source: str) -> str:
        return _source_signatures._ckan_source_signature(self, source=source)

    def _stooq_source_signature(self, source: str) -> str:
        return _source_signatures._stooq_source_signature(self, source=source)

    def _yahoo_source_signature(self, source: str) -> str:
        return _source_signatures._yahoo_source_signature(self, source=source)

    def _sec_source_signature(self, source: str) -> str:
        return _source_signatures._sec_source_signature(self, source=source)

    def _sec_company_facts_source_signature(self, source: str) -> str:
        return _source_signatures._sec_company_facts_source_signature(self, source=source)

    def _arxiv_source_signature(self, source: str) -> str:
        return _source_signatures._arxiv_source_signature(self, source=source)

    def _openalex_source_signature(self, source: str) -> str:
        return _source_signatures._openalex_source_signature(self, source=source)

    def _crossref_source_signature(self, source: str) -> str:
        return _source_signatures._crossref_source_signature(self, source=source)

    def _reliefweb_source_signature(self, source: str) -> str:
        return _source_signatures._reliefweb_source_signature(self, source=source)

    def _wikipedia_source_signature(self, source: str) -> str:
        return _source_signatures._wikipedia_source_signature(self, source=source)

    def _wikipediapageviews_source_signature(self, source: str) -> str:
        return _source_signatures._wikipediapageviews_source_signature(self, source=source)

    def _manifold_source_signature(self, source: str) -> str:
        return _source_signatures._manifold_source_signature(self, source=source)

    def _metaculus_source_signature(self, source: str) -> str:
        return _source_signatures._metaculus_source_signature(self, source=source)

    def _polymarket_source_signature(self, source: str) -> str:
        return _source_signatures._polymarket_source_signature(self, source=source)

    def _kalshi_source_signature(self, source: str) -> str:
        return _source_signatures._kalshi_source_signature(self, source=source)

    def _validate_watch_scope(self, scope_type: str, scope_ref: str | None) -> None:
        return _watches._validate_watch_scope(self, scope_type=scope_type, scope_ref=scope_ref)

    def _self_check_watch_scope(
        self,
        *,
        question_id: str | None,
        domain: str | None,
        topic: str | None,
        portfolio: str | None,
    ) -> tuple[str | None, str | None]:
        return _watches._self_check_watch_scope(self, question_id=question_id, domain=domain, topic=topic, portfolio=portfolio)

    def _watched_source_action(self, watch: dict[str, Any]) -> str:
        return _watches._watched_source_action(self, watch=watch)

    def _cli_arg(self, value: str) -> str:
        return _source_signatures._cli_arg(self, value=value)

    def _candidate_title_from_source(self, source: str, source_type: str) -> str:
        return _market_models._candidate_title_from_source(self, source=source, source_type=source_type)

    def _question_to_dict(self, question: ForecastQuestion) -> dict[str, Any]:
        return _questions._question_to_dict(self, question=question)

    def _snapshot_to_dict(self, snapshot: ForecastSnapshot) -> dict[str, Any]:
        return _snapshots._snapshot_to_dict(self, snapshot=snapshot)

    def _evidence_to_dict(self, item: EvidenceItem) -> dict[str, Any]:
        return _evidence._evidence_to_dict(self, item=item)

    def _resolution_to_dict(self, resolution: Resolution) -> dict[str, Any]:
        return _resolutions._resolution_to_dict(self, resolution=resolution)

    def _score_to_dict(self, score: ScoreRecord) -> dict[str, Any]:
        return _scoring._score_to_dict(self, score=score)
