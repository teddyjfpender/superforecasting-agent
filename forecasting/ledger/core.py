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
from datetime import timedelta
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


logger = logging.getLogger(__name__)

# Thread-local visited-set for the thesis/factor re-aggregate cascade. Module-
# level + thread-local so concurrent member commits (e.g. a shared ForecastLedger
# across the gateway's RPC thread pool) each get their OWN cycle guard, while the
# synchronous recursion within one commit still shares it. Avoids the race a plain
# instance attribute would have if a ledger were ever shared across threads.
_CASCADE_TLS = threading.local()

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
        # Watch config drives every automated data flow (refresh, autopilot,
        # alerts): a script mass-inserting watches is the same bypass class as
        # a scripted forecast. The tool exposes add_watched_source and the bulk
        # add_watched_sources for the legitimate path.
        "watched_sources",
    }
)


def _ledger_write_authorizer(action, arg1, arg2, db_name, trigger_or_view):
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
    if _FORECAST_COMMIT_ACTIVE.get():
        return sqlite3.SQLITE_OK
    # warn/off never block at the connection level (the method-level
    # _enforce_write_gate already logs the warn signal); only "on" denies.
    if ledger_write_gate_mode() != "on":
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def ledger_write_gate_mode() -> str:
    """Return the active direct-write gate mode: 'on' | 'warn' | 'off'.

    Read live from the environment each call so the flag is tunable at runtime
    (tests / doctor / an operator override) without re-importing the module.
    """
    raw = os.getenv("FORECAST_GATE_DIRECT_WRITES", "on").strip().lower()
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


FORECASTING_PROTOCOL_VERSION = "forecasting-ledger-v1"

# Auto-review eligibility — default-weekly-review gate for create_question.
#
# A LIVE organic forecast question created without an explicit review cadence
# should DEFAULT to a weekly scheduled review so it is auto-re-forecast and shows
# a "NEXT" column on the desk. But two classes of question are forecast-once-then-
# scored and must STAY cadence-less:
#   - market_nightly: foreknowledge-proof live benchmark snapshots — re-forecasting
#     them later would break the foreknowledge lock (the agent must not revisit a
#     question after the market it was pinned against has moved).
#   - forecastbench: historical replay / closed-book backtest cases — re-forecasting
#     them with today's information would contaminate the replay.
# Membership is checked against the lowercased domain OR any lowercased tag.
_AUTO_REVIEW_INELIGIBLE_DOMAINS = frozenset({"forecastbench", "market_nightly"})
_AUTO_REVIEW_INELIGIBLE_TAGS = frozenset({"bench", "forecastbench", "market_nightly"})

# AIA P0.2 — paired bootstrap significance.
#
# The paired Brier edge (per resolved question: baseline_brier - agent_brier,
# POSITIVE = agent better) is tested for significance with a SEEDED, deterministic
# paired bootstrap so the p-value and CI reproduce byte-for-byte across runs.
# PAIRED_BOOTSTRAP_SEED fixes the random.Random stream; PAIRED_BOOTSTRAP_DRAWS
# is the number of resample-means drawn for both the recenter-at-zero p-value and
# the uncentered percentile CI.
PAIRED_BOOTSTRAP_SEED = 0xA1A02
PAIRED_BOOTSTRAP_DRAWS = 10000
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


def _normalize_reason_list(raw: Any, *, field: str) -> list[str]:
    """Coerce a reasons_up / reasons_down / change_my_mind payload to ``list[str]``.

    ``None`` is treated as empty. Strings are split on newlines when they
    contain them, allowing the CLI to pass either repeated ``--reason-up`` flags
    or a single multi-line block. Whitespace-only entries are dropped.
    """

    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[str] = raw.splitlines() if "\n" in raw else [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        raise ValidationError(f"{field} must be a string or list of strings")
    cleaned: list[str] = []
    for entry in items:
        if entry is None:
            continue
        if not isinstance(entry, str):
            raise ValidationError(f"{field} entries must be strings")
        stripped = entry.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned

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
SCHEDULE_SCOPE_TYPES = {"question", "domain", "topic", "domain_topic", "portfolio", "horizon"}



# Per-forecast CRUX variables: the decisive inputs the resolution actually hinges
# on. Tracking them (+ their evidence status) stops "lots of evidence but wrong
# evidence" — the desk focuses gathering on what moves the answer.
CRUX_MATERIALITY = {"low", "medium", "high"}
CRUX_STATUS = {"missing", "stale", "current", "contradictory"}

# Semantic roles a thesis member plays in the aggregate — so a thesis reads as
# decision intelligence (which signal LEADS, which is the BOTTLENECK, which is
# market VALIDATION) rather than an undifferentiated weighted pool.
THESIS_MEMBER_ROLES = {
    "leading_indicator",   # moves early, before the thesis resolves
    "confirming_signal",   # corroborates the thesis once underway
    "bottleneck_signal",   # a gating constraint the thesis depends on
    "market_validation",   # a market/price signal validating the thesis
    "disconfirming_signal",  # would cut against the thesis if it moves
}
AUTOPILOT_MODES = {"propose", "auto_commit", "alert_only"}
AUTOPILOT_PROPOSAL_STATUSES = {"pending", "approved", "rejected", "expired", "auto_committed"}


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


_THESIS_DEAD_STATUS = {"stale", "missing", "unusable"}


def _thesis_member_label(component: dict[str, Any]) -> str:
    return str(component.get("title") or component.get("member_id") or "member")


def _thesis_reason_lines(agg: Any, kind: str) -> list[str]:
    """Top member contributions, as 'support' (lifting) or 'drag' (pulling down) lines."""

    usable = [
        c for c in agg.components
        if c.get("status") not in _THESIS_DEAD_STATUS and (c.get("w_norm") or 0) > 0
    ]
    if kind == "support":
        rows = sorted(
            (c for c in usable if float(c.get("s_i") or 0) >= 0.5),
            key=lambda c: -(float(c.get("contribution_pts") or 0)),
        )
    else:
        rows = sorted(
            (c for c in usable if float(c.get("s_i") or 0) < 0.5),
            key=lambda c: float(c.get("s_i") or 0),
        )
    lines: list[str] = []
    for c in rows[:4]:
        lines.append(
            f"{_thesis_member_label(c)}: signal {float(c.get('s_i') or 0):.0%}, "
            f"weight {float(c.get('w_norm') or 0):.0%}"
        )
    return lines


def _thesis_narrative(thesis: Any, agg: Any, event: Any = None) -> tuple[str, str, str, str, str]:
    """Build the rolling analyst note (headline, how_it_thinks, looking_for, be_aware, body)."""

    health = agg.health
    score = agg.thesis_score or 0.0
    # When a joint-event probability exists it is THE headline (the question the
    # thesis actually asks); the mean-index health becomes a diagnostic.
    has_event = event is not None and getattr(event, "event_probability", None) is not None
    if has_event:
        ev = event.event_probability
        kind = event.event.get("kind")
        k = event.event.get("threshold")
        label = f"≥{k} of {event.participants}" if kind == "count_threshold" else str(kind)
        headline = f"{thesis.title} — P(event) {ev:.0%} ({label})"
    elif health is not None:
        headline = f"{thesis.title} — health {health:.0%}"
    else:
        headline = f"{thesis.title} — withheld"

    usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
    top = sorted(usable, key=lambda c: -(float(c.get("contribution_pts") or 0)))[:3]
    drivers = ", ".join(f"{_thesis_member_label(c)} ({float(c.get('s_i') or 0):.0%})" for c in top)
    how_it_thinks = (
        f"Weighted across {len(usable)} fresh member(s); score {score:.0f}/100."
        + (f" Top drivers: {drivers}." if drivers else "")
    )
    if has_event:
        cd = event.count_distribution or {}
        mean_ct = cd.get("mean")
        movers = event.top_sensitivities(1)
        biggest = movers[0] if movers else None
        parts_ev = [
            f"Event P={event.event_probability:.0%} via Gaussian-copula MC "
            f"({event.n_draws} draws, rho {event.rho:.2f})"
        ]
        if mean_ct is not None:
            parts_ev.append(
                f"expected count ~{mean_ct:.1f} (p10-p90 {cd.get('p10', 0):.0f}-{cd.get('p90', 0):.0f})"
            )
        if biggest is not None:
            parts_ev.append(
                f"biggest swing: {biggest.get('title') or biggest.get('member_id')} "
                f"(±2pp ⇒ {biggest.get('delta_p_event', 0.0):+.1%} on P)"
            )
        how_it_thinks += " " + "; ".join(parts_ev) + "."

    contested = [c for c in usable if abs(float(c.get("s_i") or 0.5) - 0.5) < 0.2]
    contested.sort(key=lambda c: abs(float(c.get("s_i") or 0.5) - 0.5))
    looking_for = (
        "; ".join(f"{_thesis_member_label(c)} is contested ({float(c.get('s_i') or 0):.0%})" for c in contested[:2])
        or "No single member is decisively contested."
    )

    stale = [c for c in agg.components if c.get("status") in {"stale", "missing"}]
    parts = [
        f"coverage {agg.coverage:.0%}",
        f"n_eff ~{agg.n_eff:.1f} of {len(agg.components)} (members co-move; rho {agg.rho:.2f})",
    ]
    if stale:
        parts.append(f"{len(stale)} member(s) stale/missing and down-weighted")
    be_aware = "; ".join(parts) + (("; " + "; ".join(agg.notes)) if agg.notes else "")

    body = f"{headline}. {how_it_thinks} Watching: {looking_for} Caveats: {be_aware}."
    return headline, how_it_thinks, looking_for, be_aware, body


def _entity_stance(
    suitability: float | None, delta: float | None, threshold: float | None = None
) -> tuple[str, str]:
    """Map an entity's 0..1 suitability + its move into a stance + trend.

    Generic across thesis kinds: a stock 'overweight', a candidate 'frontrunner',
    a currency 'long' all share the same suitability ladder. The optional
    per-entity ``threshold`` raises the overweight bar.
    """

    if suitability is None:
        return ("WITHHELD", "flat")
    over = threshold if (isinstance(threshold, (int, float)) and threshold > 0) else 0.65
    if suitability >= over:
        stance = "OVERWEIGHT"
    elif suitability >= 0.55:
        stance = "ADD"
    elif suitability >= 0.45:
        stance = "NEUTRAL"
    elif suitability >= 0.35:
        stance = "TRIM"
    else:
        stance = "UNDERWEIGHT"
    move = delta or 0.0
    trend = "rising" if move > 0.01 else "falling" if move < -0.01 else "flat"
    return (stance, trend)


def _thesis_entity_triggers(
    member_deltas: dict[str, float],
    entities: list[dict[str, Any]],
    member_map: dict[str, dict[str, Any]],
    *,
    min_move: float = 0.05,
) -> list[dict[str, Any]]:
    """The §10 "if signal X moves -> entities Y better/less suited" lines, generic.

    For each member signal that moved at least ``min_move`` since the prior
    aggregation, ranks the entities weighting it and splits them into helped vs
    hurt by the move's direction × the entity's weight direction.
    """

    triggers: list[dict[str, Any]] = []
    for member_id, delta in member_deltas.items():
        if abs(delta) < min_move:
            continue
        better: list[tuple[float, str]] = []
        less: list[tuple[float, str]] = []
        for entity in entities:
            for weight in entity.get("weights", []):
                if weight.get("member_id") != member_id or float(weight.get("weight", 0)) <= 0:
                    continue
                effect = (1 if delta > 0 else -1) * (1 if weight.get("direction", "support") == "support" else -1)
                (better if effect > 0 else less).append((float(weight.get("weight", 0)), entity.get("name", "?")))
                break
        if not better and not less:
            continue
        better.sort(reverse=True)
        less.sort(reverse=True)
        better_names = [name for _, name in better][:8]
        less_names = [name for _, name in less][:8]
        member = member_map.get(member_id, {})
        signal = member.get("member_title") or member.get("role") or member_id
        parts: list[str] = []
        if better_names:
            parts.append(f"{', '.join(better_names)} better suited")
        if less_names:
            parts.append(f"{', '.join(less_names)} less suited")
        triggers.append(
            {
                "member_id": member_id,
                "signal": signal,
                "delta": delta,
                "direction": "up" if delta > 0 else "down",
                "note": f"{signal} {'▲' if delta > 0 else '▼'} {delta * 100:+.0f}pp → " + "; ".join(parts),
                "better": better_names,
                "less": less_names,
            }
        )
    triggers.sort(key=lambda trigger: -abs(trigger["delta"]))
    return triggers


def _factor_narrative(factor: Any, agg: Any) -> tuple[str, str, str, str, str]:
    """Rolling note for a factor: basket return + volatility + downside (plain
    units; the factor question's `units` supply the scale for display)."""

    mean = agg.mean if agg.mean is not None else 0.0
    sd = agg.sd
    headline = (
        f"{factor.title} — μ {mean:.2f} · vol {sd:.2f}" if sd is not None else f"{factor.title} — μ {mean:.2f}"
    )
    usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
    top = sorted(usable, key=lambda c: -abs(c.get("contribution") or 0))[:3]
    drivers = ", ".join(
        f"{(c.get('title') or c.get('member_id'))} ({(c.get('contribution') or 0):+.2f})" for c in top
    )
    how_it_thinks = (
        f"Weighted basket of {len(usable)} constituent return distribution(s)."
        + (f" Top contributors: {drivers}." if drivers else "")
    )
    looking_for = (
        f"90% return band {agg.q05:.2f} to {agg.q95:.2f}."
        if (agg.q05 is not None and agg.q95 is not None)
        else "Awaiting dispersion."
    )
    parts = [
        f"coverage {agg.coverage:.0%}",
        f"n_eff ~{agg.n_eff:.1f} of {len(agg.components)} (constituents co-move; rho {agg.rho:.2f})",
    ]
    if agg.downside is not None:
        parts.append(f"downside(5%) {agg.downside:.2f}")
    if agg.cvar is not None:
        parts.append(f"CVaR {agg.cvar:.2f}")
    be_aware = "; ".join(parts) + (("; " + "; ".join(agg.notes)) if agg.notes else "")
    body = f"{headline}. {how_it_thinks} {looking_for} Caveats: {be_aware}."
    return headline, how_it_thinks, looking_for, be_aware, body


class ForecastLedger:
    """Local-first SQLite ledger for questions, evidence, forecasts, and scores."""

    # Resolve-time bias-synthesis debounce window (seconds). A burst of live
    # resolutions in the same process re-synthesises a scope at most once per
    # window; the cron path (run_due_reviews) is the periodic catch-up, so nothing
    # is lost — only the redundant O(live-scores) rescans in a tight loop are cut.
    _BIAS_SYNTH_DEBOUNCE_SECONDS = 30.0

    def __init__(self, db_path: str | Path | None = None) -> None:
        configured_db = os.getenv("FORECAST_LEDGER_DB", "").strip()
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
        try:
            self.initialize_schema()
        except sqlite3.Error as exc:
            raise ForecastingError(
                "could not initialize forecast ledger "
                f"{self.db_path}: {exc}. Set FORECAST_LEDGER_DB or "
                "pass --db with a writable path."
            ) from exc

    def _connect(self) -> sqlite3.Connection:
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
                    auto_postmortem INTEGER NOT NULL DEFAULT 0
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
                    attempt_count INTEGER NOT NULL DEFAULT 0
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
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    reviewed_by TEXT
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
            # R2 operator practice loop — defensive migrations for the scoring
            # columns (idempotent; a fresh CREATE already carries them).
            self._ensure_column(conn, "operator_estimates", "resolved_outcome", "TEXT")
            self._ensure_column(conn, "operator_estimates", "brier", "REAL")
            self._ensure_column(conn, "operator_estimates", "scored_at", "TEXT")

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

    def _is_auto_review_eligible(
        self,
        domain: str | None,
        tags: list[str] | None,
    ) -> bool:
        """Whether a newly-created question should DEFAULT to a weekly review.

        INELIGIBLE (returns False — must stay cadence-less) when the question is a
        forecast-once-then-scored benchmark/foreknowledge-proof case, identified by
        a benchmark domain OR a benchmark tag (case-insensitive). See
        ``_AUTO_REVIEW_INELIGIBLE_DOMAINS`` / ``_AUTO_REVIEW_INELIGIBLE_TAGS``.
        Everything else is eligible.
        """
        if (domain or "").strip().lower() in _AUTO_REVIEW_INELIGIBLE_DOMAINS:
            return False
        for tag in tags or []:
            if str(tag).strip().lower() in _AUTO_REVIEW_INELIGIBLE_TAGS:
                return False
        return True

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
        """Count active in-scope NUMERIC calibration lessons the committed forecast
        did NOT actually apply.

        "Applied" means the committed number net-MOVED from the recorded pre-lesson
        raw payload (the trusted marker ``apply_active_lesson_adjustments`` writes) —
        NOT that a lesson ref was stapled on. So citation-stapling no longer satisfies
        the gate, and an in-scope lesson the agent simply ignored is counted as
        unapplied. Prose lessons (no numeric key) are not counted here; they are
        enforced as compiled rules in a later slice. Best-effort: any failure returns
        0 so the audit can never break a commit."""
        try:
            from forecasting.learning import active_lessons_for_question

            active = active_lessons_for_question(self, question)
        except Exception:
            return 0
        if not active:
            return 0
        adjustment = calibration_adjustment or {}
        applied_ids = {
            item.get("id")
            for item in (adjustment.get("applied_active_lessons") or [])
            if isinstance(item, dict)
        }
        raw = adjustment.get("raw_probability")
        committed = (
            committed_payload
            if isinstance(committed_payload, (int, float)) and not isinstance(committed_payload, bool)
            else None
        )
        unapplied = 0
        for lesson in active:
            recommended = lesson.get("recommended_adjustment") or {}
            is_numeric = any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale"))
            if not is_numeric:
                continue
            net_moved = (
                lesson["id"] in applied_ids
                and isinstance(raw, (int, float))
                and committed is not None
                and abs(committed - float(raw)) > 1e-9
            )
            if not net_moved:
                unapplied += 1
        return unapplied

    @staticmethod
    def _committed_winner_prob(payload: Any, outcome_type: str | None = None) -> float | None:
        """The committed winner probability — defined ONLY for binary (the p) and
        categorical (the leading outcome's mass). For a distribution payload the
        quantiles/mean are NOT probabilities, so this returns None (a vote-share
        model must never be mistaken for a 0.62 'winner probability')."""
        if outcome_type == "binary":
            if isinstance(payload, (int, float)) and not isinstance(payload, bool):
                return float(payload)
            return None
        if outcome_type == "categorical" and isinstance(payload, dict):
            values = [v for v in payload.values() if isinstance(v, (int, float)) and not isinstance(v, bool)]
            return max(values) if values else None
        if outcome_type is None and isinstance(payload, (int, float)) and not isinstance(payload, bool):
            return float(payload)  # back-compat: a bare scalar is binary-like
        return None

    @staticmethod
    def _machine_scoreable_payload(payload: Any, outcome_space: OutcomeSpace) -> bool:
        """A candidate-share (vote-share) forecast is born machine-scoreable when it
        carries numeric shares keyed to the question's candidates (the vector scorer
        can then grade it, not the operator by hand). Non-share questions always True."""
        if getattr(outcome_space, "type", None) != "distribution" or not getattr(outcome_space, "choices", None):
            return True
        if not isinstance(payload, dict):
            return False
        choices = {str(c).strip().lower() for c in outcome_space.choices}
        numeric_keys = {
            str(key).strip().lower()
            for key, value in payload.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        return bool(choices & numeric_keys)

    def _derived_child_present(self, question_id: str) -> bool:
        """Whether a derived component child (e.g. a vote-share model linked
        ``component_of`` this question) is present, is a distribution, and has a
        current snapshot — i.e. real downstream modeling actually backs this call.
        (Qualified existence; semantic consistency of the child stays advisory.)"""
        try:
            links = self.list_forecast_links(question_id, link_type="component_of", direction="incoming")
        except Exception:
            return False
        for link in links:
            child_id = link.get("from_question_id")
            if not child_id:
                continue
            try:
                child = self.get_question(child_id)
                if getattr(child.outcome_space, "type", None) != "distribution":
                    continue
                if self.get_current_snapshot(child_id) is not None:
                    return True
            except Exception:
                continue
        return False

    def _record_lesson_applications(
        self,
        question: Any,
        snapshot_id: str | None,
        committed_payload: Any,
        calibration_adjustment: dict[str, Any] | None,
    ) -> None:
        """Coverage ledger: one row per active in-scope lesson at a successful commit
        (kind + whether it was applied). Best-effort — never raises into the commit."""
        try:
            from forecasting.learning import active_lessons_for_question

            active = active_lessons_for_question(self, question)
            if not active:
                return
            adjustment = calibration_adjustment or {}
            applied_ids = {
                item.get("id")
                for item in (adjustment.get("applied_active_lessons") or [])
                if isinstance(item, dict)
            }
            raw = adjustment.get("raw_probability")
            committed = (
                committed_payload
                if isinstance(committed_payload, (int, float)) and not isinstance(committed_payload, bool)
                else None
            )
            now = utc_now_iso()
            rows = []
            for lesson in active:
                recommended = lesson.get("recommended_adjustment") or {}
                if isinstance(recommended.get("rule"), dict):
                    # The commit SUCCEEDED, so an error-severity lesson rule passed
                    # (it would otherwise have blocked); recorded as applied.
                    kind, applied = "rule", 1
                elif any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")):
                    kind = "numeric"
                    applied = 1 if (
                        lesson["id"] in applied_ids
                        and isinstance(raw, (int, float))
                        and committed is not None
                        and abs(committed - float(raw)) > 1e-9
                    ) else 0
                else:
                    kind, applied = "advisory", 0
                rows.append((f"la_{uuid.uuid4().hex[:12]}", lesson["id"], question.id, snapshot_id, kind, applied, now))
            if rows:
                with self._connect() as conn:
                    conn.executemany(
                        "INSERT INTO lesson_applications (id, lesson_id, question_id, snapshot_id, kind, applied, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        rows,
                    )
        except Exception:
            logger.debug("lesson-application coverage recording failed (non-fatal)", exc_info=True)

    def lesson_coverage(self) -> list[dict[str, Any]]:
        """Per active lesson: how often it has been IN SCOPE at a commit since it was
        created, how often applied, and whether it is DORMANT (never encountered) —
        the honest answer to 'is this learning actually being used?'. A dormant or
        rarely-applied lesson is a review trigger, not silently-trusted machinery."""
        now = utc_now_iso()
        out: list[dict[str, Any]] = []
        with self._connect() as conn:
            lessons = conn.execute(
                "SELECT id, scope_type, scope_ref, lesson, created_at, recommended_adjustment "
                "FROM calibration_lessons WHERE status = 'active' ORDER BY created_at"
            ).fetchall()
            for row in lessons:
                apps = conn.execute(
                    "SELECT applied, created_at FROM lesson_applications WHERE lesson_id = ? ORDER BY created_at",
                    (row["id"],),
                ).fetchall()
                in_scope = len(apps)
                applied = sum(int(a["applied"]) for a in apps)
                last_seen = apps[-1]["created_at"] if apps else None
                recommended = json_loads(row["recommended_adjustment"], {}) or {}
                if isinstance(recommended.get("rule"), dict):
                    kind = "rule"
                elif any(k in recommended for k in ("probability_delta", "logit_shift", "logit_scale")):
                    kind = "numeric"
                else:
                    kind = "advisory"
                out.append({
                    "lesson_id": row["id"],
                    "scope": f"{row['scope_type']}:{row['scope_ref'] or '*'}",
                    "kind": kind,
                    "lesson": (row["lesson"] or "")[:90],
                    "in_scope_count": in_scope,
                    "applied_count": applied,
                    "application_rate": (applied / in_scope) if in_scope else 0.0,
                    "last_seen": last_seen,
                    "dormant": in_scope == 0,
                    "enforceable": kind in ("numeric", "rule"),
                })
        return out

    def calibration_correcting_lessons(self, *, domain: str | None = None) -> list[dict[str, Any]]:
        """Active calibration lessons CORRECTING forecasts in scope, each carrying
        its ``recommended_adjustment``, its measured ``coverage`` (from
        :meth:`lesson_coverage` — in-scope/applied counts + application rate), and
        whether it is ``dormant`` (never yet encountered at a commit). When
        ``domain`` is given, domain/domain_topic lessons are restricted to that
        domain (global/topic/question_type lessons still apply broadly). The
        plain-language answer to 'which learning is adjusting my numbers here, and
        is it actually biting?'."""
        coverage_by_id = {row["lesson_id"]: row for row in self.lesson_coverage()}
        out: list[dict[str, Any]] = []
        for lesson in self.list_calibration_lessons(active_only=True):
            scope_type = lesson.get("scope_type")
            scope_ref = lesson.get("scope_ref")
            if domain is not None and scope_type in ("domain", "domain_topic"):
                # domain_topic scope_ref is colon-joined ("politics:nyc-primaries").
                lesson_domain = str(scope_ref or "").split(":", 1)[0]
                if lesson_domain != domain:
                    continue
            cov = coverage_by_id.get(lesson["id"], {})
            out.append({
                "lesson_id": lesson["id"],
                "scope": f"{scope_type}:{scope_ref or '*'}",
                "scope_type": scope_type,
                "scope_ref": scope_ref,
                "lesson": lesson.get("lesson"),
                "recommended_adjustment": lesson.get("recommended_adjustment") or {},
                "coverage": {
                    "in_scope_count": cov.get("in_scope_count", 0),
                    "applied_count": cov.get("applied_count", 0),
                    "application_rate": cov.get("application_rate", 0.0),
                    "last_seen": cov.get("last_seen"),
                },
                "dormant": cov.get("dormant", True),
            })
        return out

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
        preview: bool = False,
    ) -> "ForecastSnapshot | dict[str, Any]":
        # PREVIEW (preview=True): run every gate + saturation/observe scoring
        # IDENTICALLY up to the first ledger WRITE, then return a preview record
        # instead of inserting — the caller SEES the saturation score, advisories,
        # and blockers WITHOUT committing, so it fixes them and commits ONCE (this
        # kills the commit-then-remediate churn the Senate-batch audit surfaced). A
        # gate that would REFUSE the commit surfaces as {would_commit: False,
        # blockers:[...]} rather than raising. The write gate is skipped (preview
        # writes nothing; the connection-level authorizer is the backstop for any
        # accidental INSERT). All pre-insert work here is read-only/in-memory and
        # all post-insert machinery is naturally skipped by returning before it.
        if not preview:
            _enforce_write_gate("create_snapshot")
        try:
            question = self.get_question(question_id)
            # Forecast hooks: saturation/style gates raise SaturationBlocked (a
            # ValidationError subclass with a byte-identical message) so the report —
            # the failing rule + its remediation — propagates to the interactive tool
            # and the programmatic escalator. Non-saturation ValidationErrors stay plain.
            from forecasting.hooks import SaturationBlocked, single_block
            from forecasting.hooks.spec import Category as _HookCategory

            if forecast_origin not in FORECAST_ORIGINS:
                raise ValidationError(f"forecast_origin must be one of {', '.join(sorted(FORECAST_ORIGINS))}")
            # Exploratory forecasts are scratchpad thinking — never scored, and
            # exempt from the commit-time formalities below (the gates all key on
            # forecast_origin == "live"). Commit a live forecast to put it on the
            # record.
            if forecast_origin == "exploratory":
                calibration_eligible = False
            payload = self._validate_probability_payload(probability_or_distribution, question.outcome_space)
            if not rationale.strip():
                raise ValidationError("forecast rationale is required")
            if confidence is not None and not (0 <= confidence <= 1):
                raise ValidationError("confidence must be between 0 and 1")
            if calibration_weight < 0:
                raise ValidationError("calibration_weight must be non-negative")
            reasons_up_list = _normalize_reason_list(reasons_up, field="reasons_up")
            reasons_down_list = _normalize_reason_list(reasons_down, field="reasons_down")
            change_my_mind_list = _normalize_reason_list(change_my_mind, field="change_my_mind")
            if require_structured_reasoning and forecast_origin == "live":
                missing_reasoning = []
                if not reasons_up_list:
                    missing_reasoning.append("reasons_up")
                if not reasons_down_list:
                    missing_reasoning.append("reasons_down")
                if not change_my_mind_list:
                    missing_reasoning.append("change_my_mind")
                if missing_reasoning:
                    raise single_block(
                        "require_structured_reasoning",
                        "live forecast requires structured reasoning fields: "
                        + ", ".join(missing_reasoning)
                        + ". Provide reasons_up/reasons_down/change_my_mind, rerun with "
                        "require_structured_reasoning=false, or record it as "
                        "forecast_origin='exploratory'.",
                        action="decompose",
                    )
            if require_components and forecast_origin == "live":
                # A serious live forecast must show its work: the pooled drivers
                # (base rate, mechanism, market/crowd, case-specific factors) in the
                # structured ensemble_components field, not a bare number. This is
                # the gate that stops snapshots collapsing into an under-specified
                # point estimate.
                component_rows = ensemble_components
                if isinstance(component_rows, dict):
                    component_rows = component_rows.get("components", component_rows)
                has_components = bool(component_rows) and (
                    len(component_rows) > 0 if isinstance(component_rows, (list, dict)) else False
                )
                if not has_components:
                    raise single_block(
                        "require_components",
                        "live forecast requires ensemble_components: decompose the estimate "
                        "into pooled drivers (base rate, mechanism, market/crowd, case-specific "
                        "factors), each with a stable source slug. Provide ensemble_components, "
                        "rerun with require_components=false, or record it as "
                        "forecast_origin='exploratory'.",
                        action="decompose",
                    )

            # Re-run discipline: a re-run is not a retrieval. When asked (the agent's
            # update path sets this by default), refuse to commit a new live snapshot
            # if a prior forecast exists and NO fresh evidence was collected since it
            # — stopping the agent from re-estimating off stale ledger evidence and
            # perpetuating a hedge. "Fresh" is measured tie-proof by the evidence
            # count recorded on the prior snapshot (timestamp fallback for snapshots
            # predating this field). The deterministic `forecast refresh` path imports
            # fresh readings first and does not set this; a genuine no-change re-run
            # can acknowledge_stale_evidence or record forecast_origin='exploratory'.
            evidence_count_at_commit: int | None = None
            if forecast_origin == "live":
                # Always count live evidence so the evidence-floor gate (require_evidence)
                # sees the true count; the fresh-evidence RE-RUN check layers on top of it
                # and only applies when require_fresh_evidence is set.
                evidence_now = self.list_evidence(question_id)
                evidence_count_at_commit = len(evidence_now)
                if require_fresh_evidence and not acknowledge_stale_evidence:
                    prior = self.get_current_snapshot(question_id)
                    if prior is not None:
                        prior_count = (prior.metadata or {}).get("evidence_count_at_commit")
                        if isinstance(prior_count, int):
                            has_fresh = evidence_count_at_commit > prior_count
                        else:
                            prior_ts = prior.created_at or prior.as_of or ""
                            has_fresh = any((item.captured_at or "") > prior_ts for item in evidence_now)
                        if not has_fresh:
                            raise single_block(
                                "require_fresh_evidence",
                                "re-run blocked: no fresh evidence collected since the prior forecast "
                                f"({prior.forecast_id}, as_of {prior.as_of}). Re-running a forecast must "
                                "start from fresh readings — run `forecast refresh <id>` (re-fetches "
                                "watched sources and re-pools) or import_source_evidence for each driver "
                                "to pull the latest data, THEN update. If you have genuinely checked and "
                                "nothing has changed, set acknowledge_stale_evidence=true (CLI "
                                "--ack-stale-evidence), or record it as forecast_origin='exploratory'.",
                                action="collect_evidence",
                            )

            if require_decision_readiness and forecast_origin == "live":
                readiness_issues = question_decision_readiness_issues(question)
                if readiness_issues:
                    raise single_block(
                        "require_decision_readiness",
                        "forecast update blocked by missing decision context: "
                        + "; ".join(readiness_issues)
                        + ". Set decision_owner, action_threshold, and update_triggers "
                        "on the question, or rerun without require_decision_readiness.",
                        category=_HookCategory.DECISION,
                    )

            now = utc_now_iso()
            as_of_ts = parse_timestamp(as_of, field_name="as_of") or now
            cutoff_ts = parse_timestamp(evidence_cutoff, field_name="evidence_cutoff")
            effective_cutoff = cutoff_ts or as_of_ts
            self._validate_evidence_refs(question_id, evidence_refs or [], effective_cutoff)
            snapshot_metadata = dict(metadata or {})
            # Baseline for the next re-run's fresh-evidence gate (tie-proof count).
            if evidence_count_at_commit is not None:
                snapshot_metadata.setdefault("evidence_count_at_commit", evidence_count_at_commit)

            # Panel formality. A deliberative panel — independent multi-perspective
            # estimates aggregated into a spread — is *indicated* for high-impact
            # questions and for the first forecast on any question (see
            # should_run_panel). For a high-impact live forecast we hard-require
            # evidence one ran (a panel run linked via panel_run_ref) OR an explicit
            # recorded reason for skipping it; the cost of a single-model miss is
            # highest there. For a non-high-impact first forecast the panel is only
            # recommended (recorded as a note), so routine and exploratory research
            # stays unencumbered. Exploratory snapshots are exempt entirely.
            # Read the linked panel run at most ONCE per commit; reused below for the
            # terminal-calibration + quorum-participation signals (no N+1).
            _linked_panel: dict[str, Any] | None = None
            if forecast_origin == "live":
                from forecasting.panel import should_run_panel  # local import avoids cycle

                if panel_run_ref:
                    _linked_panel = self.get_panel_run(panel_run_ref)
                    if _linked_panel["question_id"] != question_id:
                        raise ValidationError("panel_run_ref belongs to a different question")
                panel_skip = (panel_skipped_reason or "").strip()
                high_impact = (question.impact or "").strip().lower() == "high"
                has_prior = bool(question.current_forecast_id)
                panel_indicated = should_run_panel(
                    impact=question.impact,
                    has_prior_snapshot=has_prior,
                )
                # A re-commitment of an existing live forecast is the highest-risk
                # path for silently inheriting the prior's biases, so it binds the
                # panel just like a high-impact forecast — even though should_run_panel
                # treats a non-high-impact re-run as not-indicated (its rationale is the
                # first-forecast baseline). Scoped to callers that opt into require_panel
                # (the agent's update_forecast tool defaults it True); programmatic
                # re-pools pass a panel_skipped_reason and are exempt below.
                panel_required_here = require_panel and (high_impact or has_prior)
                if (panel_indicated or panel_required_here) and not panel_run_ref and not panel_skip:
                    if panel_required_here:
                        why = "high-impact" if high_impact else "re-committed (a prior live snapshot exists)"
                        raise single_block(
                            "require_panel",
                            f"{why} live forecast requires a deliberative panel: run a "
                            "panel or quorum and pass panel_run_ref, record why you skipped it "
                            "with panel_skipped_reason, rerun with require_panel=false, or record "
                            "it as forecast_origin='exploratory'.",
                            action="run_panel",
                        )
                    # First-forecast panels on lower-impact questions are recommended,
                    # not required — leave a note the agent/guidance can surface.
                    snapshot_metadata["panel_recommended"] = True
                if panel_skip:
                    snapshot_metadata["panel_skipped_reason"] = panel_skip
                # Mirror the panel-skip escape hatch for the freshness one: if a live
                # forecast acknowledges stale evidence, record WHY so the bypass is
                # explained + auditable (the stale_evidence_justified rule WARNs when
                # acknowledged without a reason).
                stale_reason = (stale_evidence_reason or "").strip()
                if stale_reason:
                    snapshot_metadata["stale_evidence_reason"] = stale_reason
                if acknowledge_stale_evidence and has_prior:
                    # mark the bypass so a later lint/doctor re-read can surface it even
                    # when no reason was given (the WARN state)
                    snapshot_metadata["acknowledge_stale_evidence"] = True
            if panel_run_ref:
                # PROVENANCE: the panel that underwrote this commit was previously
                # consumed by the gates and DISCARDED — a post-hoc audit could not
                # verify "committed with panel pr_..." from the record itself (the
                # operator's Senate-batch review hit exactly this). Stamp it.
                snapshot_metadata["panel_run_ref"] = panel_run_ref

            if require_citations and forecast_origin == "live":
                citation_refs = [
                    *(evidence_refs or []),
                    *(model_run_refs or []),
                    *(reference_class_refs or []),
                    *(source_snapshot_refs or []),
                    *(assumption_refs or []),
                    *(calibration_lesson_refs or []),
                ]
                if not citation_refs:
                    raise single_block(
                        "require_citations",
                        "live forecast requires citations: add evidence/model/reference/source refs, "
                        "rerun with require_citations=false, or record it as forecast_origin='exploratory'",
                        action="collect_evidence",
                    )
                snapshot_metadata["citation_policy"] = "required"
            # Probability-mass audit for CATEGORICAL forecasts: route every
            # material outcome through a named mechanism so mass can't be spread
            # across answer-choice labels by default (outcome-space anchoring).
            # Always recorded for auditability; only ENFORCED when the caller opts
            # in via require_outcome_paths on a live forecast.
            if question.outcome_space.type == "categorical" and isinstance(payload, dict):
                from forecasting.tail_audit import audit_outcomes, outcome_paths_from_inputs

                audit = audit_outcomes(outcome_paths_from_inputs(payload, outcome_paths))
                snapshot_metadata["tail_audit"] = audit.to_dict()
                if require_outcome_paths and forecast_origin == "live" and not audit.passes:
                    offenders = [v.name for v in audit.verdicts if v.unearned]
                    raise single_block(
                        "require_outcome_paths",
                        "live categorical forecast has unearned tail mass "
                        f"({audit.unearned_mass:.1%}) on outcomes with no named path: "
                        f"{', '.join(offenders)}. Name the mechanism for each (pass "
                        "outcome_paths / --outcome-path), compress the mass onto outcomes "
                        "with a live path, rerun with require_outcome_paths=false, or record "
                        "it as forecast_origin='exploratory'.",
                        action="compress_tails",
                    )
            if stale_evidence_days is not None and evidence_refs:
                stale_refs = self.find_stale_evidence_refs(
                    question_id,
                    evidence_refs,
                    as_of=as_of_ts,
                    stale_days=stale_evidence_days,
                )
                if stale_refs and not acknowledge_stale_evidence:
                    refs = ", ".join(item.id for item in stale_refs)
                    raise ValidationError(
                        f"stale evidence requires acknowledgement before update: {refs}"
                    )
                if stale_refs:
                    snapshot_metadata["stale_evidence_acknowledgement"] = {
                        "acknowledged_at": now,
                        "stale_evidence_days": stale_evidence_days,
                        "evidence_refs": [item.id for item in stale_refs],
                    }
            self._validate_question_scoped_refs(question_id, assumption_refs or [], self.get_assumption, "assumption")
            self._validate_question_scoped_refs(
                question_id,
                reference_class_refs or [],
                self.get_reference_class,
                "reference class",
            )
            self._validate_question_scoped_refs(question_id, model_run_refs or [], self.get_model_run, "model run")
            for lesson_id in calibration_lesson_refs or []:
                lesson = self.get_calibration_lesson(lesson_id)
                if lesson["status"] != "active" or lesson.get("invalidated_by_correction_id"):
                    raise ValidationError("calibration lesson refs must be active and non-invalidated")

            # Style gate (Phase 2): a live forecast's prose must be house-clean (no
            # em-dashes / formatting). The interactive AGENT path BLOCKS so the agent
            # rewrites to conform (the user's choice). PROGRAMMATIC system paths
            # (refresh / autopilot / aggregates) pass style_autofix=True: they have no
            # agent to rewrite their generated prose, so the hook mechanically cleans
            # it (the "auto-orchestrate remediation" choice) rather than break
            # automation. Exploratory/backtest/imported work is exempt (not "live").
            if forecast_origin == "live":
                from forecasting.hooks import style_clean_for_rationale, style_message

                _style_ok, _style_offenders = style_clean_for_rationale(rationale)
                if not _style_ok:
                    if style_autofix:
                        from forecasting.writeup import sanitize_writeup_text

                        rationale = sanitize_writeup_text(rationale)
                    elif require_style:
                        raise single_block(
                            "style_clean",
                            style_message(_style_offenders),
                            action="sanitize_style",
                            category=_HookCategory.STYLE,
                            weight=5.0,
                        )
                    # else: style downgraded to warn/off via config — leave the prose;
                    # the observe-mode report still records the style verdict.

            # Record the agent's declared reasoning methods (normalized to the taxonomy)
            # in metadata, so the reasoning-composition hook + lint can read them.
            if reasoning_methods:
                from forecasting.hooks.reasoning import normalize_methods as _norm_methods

                _rm, _ = _norm_methods(reasoning_methods)
                if _rm:
                    snapshot_metadata["reasoning_methods"] = _rm

            # Distribution structure gate (v2): a live distribution/numeric forecast must
            # be RENDERABLE + WELL-FORMED (ordered / nested / in-bounds), so the Desk chart
            # never draws absurd bounds. The agent path BLOCKS (fix the distribution); a
            # programmatic system path AUTO-FIXES (reorder / clamp / nest / derive). Binary
            # and plain categorical payloads are unaffected (assess returns None).
            if forecast_origin == "live":
                from forecasting.hooks.distribution import assess_distribution, autofix_distribution

                _osp = question.outcome_space
                _bounds = getattr(_osp, "bounds", None)
                _da = assess_distribution(probability_or_distribution, outcome_type=_osp.type, bounds=_bounds, units=getattr(_osp, "units", None))
                if _da and (not _da.renderable or not _da.well_formed or not _da.in_range):
                    if distribution_autofix:
                        _fixed, _fxs = autofix_distribution(probability_or_distribution, bounds=_bounds)
                        if _fxs:
                            probability_or_distribution = _fixed
                            payload = self._validate_probability_payload(_fixed, _osp)
                            snapshot_metadata["distribution_autofixed"] = _fxs
                            # Re-assess: a clamp can still leave a degenerate/edge interval.
                            # Record what the mechanical fix could not resolve (observability)
                            # rather than silently committing a still-malformed band.
                            _da2 = assess_distribution(_fixed, outcome_type=_osp.type, bounds=_bounds, units=getattr(_osp, "units", None))
                            if _da2 and (not _da2.well_formed or not _da2.renderable):
                                snapshot_metadata["distribution_autofix_incomplete"] = list(_da2.issues)
                    elif require_output_structure:
                        if not _da.renderable:
                            raise single_block(
                                "output_renderable",
                                "distribution forecast is not renderable: it needs a central tendency "
                                "(median or mean) AND at least one ordered interval (ci90 or quantiles) "
                                "so the Desk chart can draw a band. Provide them, or record "
                                "forecast_origin='exploratory'.",
                                action="fix_distribution", category=_HookCategory.OUTPUT, weight=12.0,
                            )
                        raise single_block(
                            "uncertainty_well_formed",
                            "forecast uncertainty bounds are malformed: " + ("; ".join(_da.issues) or "ordering/nesting/range")
                            + ". Intervals must be ordered (lo<=hi), nested (ci50 inside ci90), finite, "
                            "non-degenerate, and within the question bounds. Fix the distribution, or "
                            "record forecast_origin='exploratory'.",
                            action="fix_distribution", category=_HookCategory.OUTPUT, weight=12.0,
                        )

            # Lesson-application audit (revives the previously-dead lessons_applied
            # signal): count active in-scope NUMERIC lessons the committed forecast did
            # not actually apply (net-movement, not citation-stapling). Fed into BOTH the
            # user-rule context and the observe-mode score below so the gate can finally
            # see a non-zero value. Best-effort.
            try:
                _active_unapplied = self._audit_unapplied_lessons(
                    question, probability_or_distribution, calibration_adjustment
                )
            except Exception:
                _active_unapplied = 0
            # Structural-lesson signals (NY-12): the committed winner probability + whether
            # a derived vote-share child model backs it. Fed into both contexts so a lesson
            # rule can require ">X% winner -> a vote-share child exists". Best-effort.
            _winner_prob = self._committed_winner_prob(probability_or_distribution, question.outcome_space.type)
            try:
                _has_child = self._derived_child_present(question_id)
            except Exception:
                _has_child = False
            _scoreable = self._machine_scoreable_payload(probability_or_distribution, question.outcome_space)

            # Terminal Platt-calibration signal (AIA P0.1): when this commit LINKS a
            # panel run, did that run pass through aggregate_panel_estimates' terminal
            # calibration stage (which records `applied_alpha` on the persisted spread)?
            # True when no panel is linked (nothing to skip). Best-effort / fail-open.
            _terminal_calibration_present = True
            # Quorum / panel participation signals (v2) derived from the SAME linked
            # panel run, so the quorum rules (participation / judged) evaluate truthfully
            # at commit instead of defaulting (which false-fired quorum_participation and
            # left quorum_judged indeterminate). Fail-open: defaults on any error.
            _quorum_is = False
            _quorum_persp = 0
            _quorum_models = 0
            _quorum_judged = False
            if panel_run_ref:
                try:
                    from forecasting.hooks.signals import quorum_signals_from_panel_run as _quorum_signals

                    _pr = _linked_panel if _linked_panel is not None else self.get_panel_run(panel_run_ref)
                    _terminal_calibration_present = "applied_alpha" in (_pr.get("spread_summary") or {})
                    _quorum_is, _quorum_persp, _quorum_models, _quorum_judged = _quorum_signals(_pr)
                except Exception:
                    _terminal_calibration_present = True

            # Per-question minimum-requirement THRESHOLD overrides (from the settings
            # modal / forecast.config.set). Fed into both the user-rule context and the
            # observe-mode score so a gate's floor is per-forecast, not a global constant.
            try:
                from forecasting.hooks.thresholds import normalize_thresholds as _norm_thr

                _qthresholds = _norm_thr(((question.metadata or {}).get("forecast_hooks") or {}).get("thresholds"))
            except Exception:
                _qthresholds = {}

            # VOI-directed research adequacy (research_audit.py): the DETERMINISTIC checks
            # only (NO LLM at commit), computed against the current evidence/reference/
            # watched state + THIS candidate commit's reasons_down + evidence_refs. Feeds
            # the `research_adequate` hook rule (WARN standard / ERROR strict). Fail-open:
            # any read error yields adequate=True so a commit is never falsely blocked.
            _research_adequate = True
            _research_adequacy_score = None
            if forecast_origin == "live":
                try:
                    from forecasting.research_audit import audit_research_for_commit

                    _ra = audit_research_for_commit(
                        self, question,
                        reasons_down=reasons_down_list, evidence_refs=evidence_refs or [],
                        stale_evidence_days=stale_evidence_days,
                    )
                    _research_adequate = bool(_ra.get("adequate"))
                    _research_adequacy_score = _ra.get("score")
                except Exception:
                    _research_adequate, _research_adequacy_score = True, None

            # User-defined rule enforcement (Phase 5). Only runs when the desk has
            # authored custom rules (zero overhead otherwise). A buggy rule engine must
            # never brick a commit (fail-OPEN on evaluation errors), but a legitimately
            # failing error-severity user rule DOES block (that is the point).
            if forecast_origin == "live":
                try:
                    import dataclasses as _dc

                    from forecasting.hooks import build_commit_context, resolve_severities, run_hooks
                    from forecasting.hooks.engine import load_hook_config
                    from forecasting.hooks.loader import load_user_rules

                    _hcfg = load_hook_config()
                    _user_rules = load_user_rules(_hcfg)
                except Exception:
                    _user_rules = []
                    _hcfg = {}
                # Compile active in-scope calibration lessons that carry a `rule` into
                # enforceable lesson:* rules — this is how a STRUCTURAL lesson (not just a
                # numeric bias) bites at commit. Force-stamped scope; broken rules skipped.
                try:
                    from forecasting.learning import compile_lesson_rules as _compile_lessons

                    _lesson_rules = _compile_lessons(self, question)
                except Exception:
                    _lesson_rules = []
                if _user_rules or _lesson_rules:
                    _ublocked = None
                    try:
                        _ucomp = ensemble_components
                        if isinstance(_ucomp, dict):
                            _ucomp = _ucomp.get("components", _ucomp)
                        _ctx = build_commit_context(
                            question_id=question_id, forecast_origin=forecast_origin, event="update",
                            impact=question.impact, has_prior=bool(question.current_forecast_id),
                            is_categorical=(question.outcome_space.type == "categorical"),
                            reasons_up=reasons_up_list, reasons_down=reasons_down_list, change_my_mind=change_my_mind_list,
                            has_components=bool(_ucomp), component_count=(len(_ucomp) if isinstance(_ucomp, (list, dict)) else 0),
                            citation_refs=[*(evidence_refs or []), *(model_run_refs or [])],
                            panel_run_ref=panel_run_ref, panel_skipped_reason=panel_skipped_reason,
                            stale_evidence_reason=stale_evidence_reason,
                            has_fresh_evidence=True, acknowledge_stale_evidence=acknowledge_stale_evidence,
                            evidence_count=len(evidence_refs or []), prior_forecast_id=None, prior_as_of=None,
                            decision_gaps=question_decision_readiness_issues(question),
                            tail_audit_passes=((snapshot_metadata.get("tail_audit") or {}).get("passes")),
                            tail_unearned_mass=float((snapshot_metadata.get("tail_audit") or {}).get("unearned_mass") or 0.0),
                            tail_offenders=[], rationale=rationale,
                            domain=getattr(question, "domain", None), outcome_type=question.outcome_space.type,
                            thresholds=_qthresholds,
                        )
                        # Augment with the signals user rules may test that the candidate
                        # context does not carry (only fetched when user rules exist) —
                        # including the v2 output/uncertainty/confidence/reasoning signals,
                        # so a user rule that references e.g. bounds.well_formed or
                        # reasoning.method_count enforces against real values, not defaults.
                        from forecasting.hooks.distribution import assess_distribution as _u_assess
                        from forecasting.hooks.profiles import resolve_reasoning_requirement as _u_rrr

                        _uosp = question.outcome_space
                        _uda = _u_assess(probability_or_distribution, outcome_type=_uosp.type, bounds=getattr(_uosp, "bounds", None), units=getattr(_uosp, "units", None))
                        try:
                            _ush = self._sharpness(probability_or_distribution)
                        except Exception:
                            _ush = None
                        _uprof = ((question.metadata or {}).get("forecast_hooks") or {}).get("profile") or _hcfg.get("profile") or "standard"
                        _urq, _umin = _u_rrr(_uprof)
                        _uuc = False
                        try:
                            _ub = self.calibration_bias(domain=getattr(question, "domain", None))
                            _uuc = (_ub.get("status") not in (None, "insufficient_evidence")) and _ub.get("direction") == "under"
                        except Exception:
                            _uuc = False
                        _utd = snapshot_metadata.get("tail_audit") or {}
                        _ctx = _dc.replace(
                            _ctx,
                            reference_class_count=len(self.list_reference_classes(question_id)),
                            linked_reference_class_count=len(reference_class_refs or []),
                            is_thesis_or_factor=self.is_thesis(question),
                            watched_source_count=len(self.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")),
                            panel_run_count=len(self.list_panel_runs(question_id)),
                            reasoning_methods=tuple(snapshot_metadata.get("reasoning_methods") or ()),
                            required_reasoning_methods=tuple(_urq), min_reasoning_methods=_umin,
                            is_distribution=bool(_uda and _uda.is_distribution),
                            distribution_renderable=(_uda.renderable if _uda else True),
                            bounds_well_formed=(_uda.well_formed if _uda else True),
                            bounds_in_range=(_uda.in_range if _uda else True),
                            interval_width_ratio=(_uda.width_ratio if _uda else None),
                            sharpness=_ush,
                            is_quorum=_quorum_is,
                            panel_perspective_count=_quorum_persp,
                            quorum_model_count=_quorum_models,
                            quorum_judged=_quorum_judged,
                            calibration_under_confident=_uuc,
                            tail_null_excess=float(((_utd.get("null_model") or {}).get("excess_tail")) or 0.0),
                            active_lessons_unapplied=_active_unapplied,
                            committed_winner_prob=_winner_prob,
                            derived_child_present=_has_child,
                            machine_scoreable=_scoreable,
                            terminal_calibration_present=_terminal_calibration_present,
                            research_adequate=_research_adequate,
                            research_adequacy_score=_research_adequacy_score,
                        )
                        _upolicy = resolve_severities(question, forecast_origin=forecast_origin, hooks_config=_hcfg)
                        _ureport = run_hooks(_ctx, _upolicy, rules=tuple(_user_rules) + tuple(_lesson_rules))
                        if not _ureport.passed:
                            _ublocked = _ureport
                    except Exception:
                        logger.debug("forecast-hooks user-rule eval failed (non-fatal, fail-open)", exc_info=True)
                    if _ublocked is not None:
                        raise SaturationBlocked(_ublocked)

            # Forecast hooks (Wave 3): the shared commit context is assembled ONCE below
            # and drives two consumers:
            #   (1) a RESOLVED-POLICY blocking pass (Slice H3) for the built-in rules that
            #       have NO inline gate above — evaluated under resolve_severities (profile
            #       + impact/origin scaling + config/per-question overrides, the SAME
            #       resolution the observe call uses). A failing ERROR-severity rule here
            #       raises SaturationBlocked with the rule's canonical builtin message +
            #       remediation. This is what makes require_evidence (ERROR by default) a
            #       real floor for an agent commit, and lets the strict profile /
            #       impact-scaling actually block the non-inline rules instead of only
            #       colouring the observe report.
            #   (2) the OBSERVE-mode recording (Phase 1): compute the FULL saturation score
            #       + per-rule report and record it on the snapshot.
            # The inline gates above stay the byte-identical, first-failing-wins enforcement
            # for the rules they own; the blocking pass NEVER re-evaluates a rule an inline
            # gate already owns (de-duplicated by rule_id), so precedence + messages are
            # preserved.
            #
            # SCOPE (all must hold for the blocking pass to fire):
            #   * forecast_origin == 'live' (exploratory / backtest / imported stay observe-only);
            #   * enforce_resolved_hooks is True — the OPT-IN the AGENT path (the interactive
            #     forecast tool's update_forecast) sets. This mirrors the codebase's existing
            #     require_* opt-in discipline: the ledger stays lenient for direct callers
            #     (operator seeds, migrations, fixtures, internal recompute) so a raw
            #     create_snapshot never retroactively hard-blocks, while the agent commit —
            #     the path this floor is FOR — enforces the resolved policy. Programmatic
            #     system paths (refresh / aggregate / autopilot / pilot-cohort) commit
            #     directly with their style_autofix / distribution_autofix leniency and do
            #     NOT opt in, so they keep observe + autofix (belt-and-braces: the autofix
            #     flags below are also treated as an exemption);
            #   * neither style_autofix nor distribution_autofix is set (programmatic exemption);
            #   * the env kill-switch FORECAST_DISABLE_HOOK_BLOCKING is not set (it disables
            #     the pass entirely; observe still runs).
            # Everything is fully guarded and must NEVER break a commit; the block report is
            # computed inside the fail-open try (run_hooks returns a report, it does not
            # raise) and RAISED afterwards so SaturationBlocked escapes the fail-open.
            #
            # Built-in rule_ids already owned by an inline gate above (excluded from the
            # blocking pass so nothing is evaluated as blocking twice; their precedence +
            # exact messages are unchanged).
            _INLINE_GATE_RULE_IDS = frozenset({
                "require_structured_reasoning", "require_components", "require_fresh_evidence",
                "require_decision_readiness", "require_panel", "require_citations",
                "require_outcome_paths", "style_clean", "output_renderable",
                "uncertainty_well_formed",
            })
            _resolved_block: SaturationReport | None = None
            try:
                from forecasting.hooks import build_commit_context, policy_from_require_flags, run_hooks

                _comp = ensemble_components
                if isinstance(_comp, dict):
                    _comp = _comp.get("components", _comp)
                _has_comp = bool(_comp) and (len(_comp) > 0 if isinstance(_comp, (list, dict)) else False)
                _comp_n = len(_comp) if isinstance(_comp, (list, dict)) else 0
                _cite_refs = [
                    *(evidence_refs or []), *(model_run_refs or []), *(reference_class_refs or []),
                    *(source_snapshot_refs or []), *(assumption_refs or []), *(calibration_lesson_refs or []),
                ]
                _td = snapshot_metadata.get("tail_audit") or {}
                # v2 signals for the observe score
                from forecasting.hooks.distribution import assess_distribution as _assess_dist
                from forecasting.hooks.profiles import resolve_reasoning_requirement as _resolve_rr

                _osp2 = question.outcome_space
                _oda = _assess_dist(probability_or_distribution, outcome_type=_osp2.type, bounds=getattr(_osp2, "bounds", None), units=getattr(_osp2, "units", None))
                try:
                    _osharp = self._sharpness(probability_or_distribution)
                except Exception:
                    _osharp = None
                try:
                    _oprof = ((question.metadata or {}).get("forecast_hooks") or {}).get("profile") or "standard"
                    _orq, _omin = _resolve_rr(_oprof)
                except Exception:
                    _orq, _omin = (), 0
                _hook_ctx = build_commit_context(
                    question_id=question_id, forecast_origin=forecast_origin, event="update",
                    impact=question.impact, has_prior=bool(question.current_forecast_id),
                    is_categorical=(question.outcome_space.type == "categorical"),
                    reasons_up=reasons_up_list, reasons_down=reasons_down_list, change_my_mind=change_my_mind_list,
                    has_components=_has_comp, component_count=_comp_n, citation_refs=_cite_refs,
                    panel_run_ref=panel_run_ref, panel_skipped_reason=panel_skipped_reason,
                    stale_evidence_reason=stale_evidence_reason,
                    # Freshness is treated as satisfied for the advisory SCORE: when the
                    # fresh-evidence rule is enforced, a stale re-run is blocked by the
                    # gate above and never reaches here; when it is not enforced, the
                    # score should not penalize freshness. So a recorded saturation
                    # score never reflects a freshness failure (the gate owns that).
                    has_fresh_evidence=True, acknowledge_stale_evidence=acknowledge_stale_evidence,
                    evidence_count=(evidence_count_at_commit or 0),
                    prior_forecast_id=None, prior_as_of=None,
                    decision_gaps=question_decision_readiness_issues(question),
                    tail_audit_passes=(_td.get("passes") if _td else None),
                    tail_unearned_mass=float(_td.get("unearned_mass") or 0.0),
                    tail_offenders=[v.get("name") for v in (_td.get("verdicts") or []) if v.get("unearned")],
                    rationale=rationale,
                    domain=getattr(question, "domain", None),
                    outcome_type=question.outcome_space.type,
                    reasoning_methods=snapshot_metadata.get("reasoning_methods") or [],
                    required_reasoning_methods=tuple(_orq), min_reasoning_methods=_omin,
                    reference_class_count=len(self.list_reference_classes(question_id)),
                    linked_reference_class_count=len(reference_class_refs or []),
                    is_thesis_or_factor=self.is_thesis(question),
                    is_distribution=bool(_oda and _oda.is_distribution),
                    distribution_renderable=(_oda.renderable if _oda else True),
                    bounds_well_formed=(_oda.well_formed if _oda else True),
                    bounds_in_range=(_oda.in_range if _oda else True),
                    interval_width_ratio=(_oda.width_ratio if _oda else None),
                    sharpness=_osharp,
                    panel_run_count=len(self.list_panel_runs(question_id)),
                    is_quorum=_quorum_is,
                    panel_perspective_count=_quorum_persp,
                    quorum_model_count=_quorum_models,
                    quorum_judged=_quorum_judged,
                    active_lessons_unapplied=_active_unapplied,
                    committed_winner_prob=_winner_prob,
                    derived_child_present=_has_child,
                    machine_scoreable=_scoreable,
                    terminal_calibration_present=_terminal_calibration_present,
                    research_adequate=_research_adequate,
                    research_adequacy_score=_research_adequacy_score,
                    thresholds=_qthresholds,
                )
                # (1) RESOLVED-POLICY blocking pass (Slice H3). Only for a live commit that
                # is NOT a programmatic (autofix) path and has not disabled the pass via the
                # kill-switch. Evaluate ONLY the built-in rules with no inline gate, under the
                # resolved (profile + scaling + override) severities, and stage the block to be
                # raised after this fail-open try. run_hooks preserves builtin order, so the
                # first failing ERROR is the same rule the report's blocking_failures()[0] names.
                _block_disabled = os.environ.get("FORECAST_DISABLE_HOOK_BLOCKING", "").strip().lower() in {
                    "1", "true", "yes", "on",
                }
                if (
                    forecast_origin == "live"
                    and enforce_resolved_hooks
                    and not style_autofix
                    and not distribution_autofix
                    and not _block_disabled
                ):
                    from forecasting.hooks import resolve_severities as _resolve_sev_block
                    from forecasting.hooks.builtins import BUILTIN_RULES as _ALL_BUILTIN_RULES

                    _resolved_policy = _resolve_sev_block(
                        question, forecast_origin=forecast_origin, hooks_config=_hcfg,
                    )
                    _noninline_rules = tuple(
                        r for r in _ALL_BUILTIN_RULES if r.id not in _INLINE_GATE_RULE_IDS
                    )
                    _block_report = run_hooks(_hook_ctx, _resolved_policy, rules=_noninline_rules)
                    if _block_report.blocking_failures():
                        _resolved_block = _block_report

                _hook_policy = policy_from_require_flags(
                    forecast_origin=forecast_origin,
                    require_structured_reasoning=require_structured_reasoning,
                    require_components=require_components, require_fresh_evidence=require_fresh_evidence,
                    require_decision_readiness=require_decision_readiness, require_panel=require_panel,
                    require_citations=require_citations, require_outcome_paths=require_outcome_paths,
                )
                snapshot_metadata["saturation"] = run_hooks(_hook_ctx, _hook_policy).to_dict()
            except Exception:  # observe-mode is best-effort and must NEVER break a commit
                logger.debug("forecast-hooks observe-mode failed (non-fatal)", exc_info=True)
            # RAISE the resolved-policy block OUTSIDE the fail-open try so SaturationBlocked
            # (a ValidationError) is never swallowed by the observe guard above.
            if _resolved_block is not None:
                raise SaturationBlocked(_resolved_block)
        except ValidationError as _preview_err:
            # A gate refused the commit. In preview, surface the blocker cheaply so
            # the caller can fix it before writing, instead of paying a real commit.
            if preview:
                return {"preview": True, "would_commit": False, "blockers": [str(_preview_err)]}
            raise
        if preview:
            # Every gate passed. Return the SAME saturation score + post-adjustment
            # value + assembled metadata a real commit would stamp — but no INSERT.
            return {
                "preview": True,
                "would_commit": True,
                "saturation": snapshot_metadata.get("saturation"),
                "probability_or_distribution": payload,
                "metadata": snapshot_metadata,
            }

        forecast_id = f"fs_{uuid.uuid4().hex[:12]}"
        horizon_days = self._forecast_horizon_days(question.close_time, as_of_ts)
        parent_forecast_id = question.current_forecast_id
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_snapshots (
                    forecast_id, question_id, created_at, as_of,
                    probability_or_distribution, confidence, forecast_horizon_days,
                    method, ensemble_components, rationale, key_assumptions,
                    assumption_refs, reference_class_refs, evidence_refs, model_run_refs,
                    parent_forecast_id, forecast_origin, agent_model, prompt_version,
                    forecasting_protocol_version, toolset_version, source_snapshot_refs,
                    evidence_cutoff, backtest_run_id, calibration_eligible,
                    calibration_weight, calibration_lesson_refs, calibration_adjustment,
                    metadata, reasons_up, reasons_down, change_my_mind
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    forecast_id,
                    question_id,
                    now,
                    as_of_ts,
                    json_dumps(payload),
                    confidence,
                    horizon_days,
                    method,
                    json_dumps(ensemble_components or {}),
                    rationale.strip(),
                    json_dumps(key_assumptions or []),
                    json_dumps(assumption_refs or []),
                    json_dumps(reference_class_refs or []),
                    json_dumps(evidence_refs or []),
                    json_dumps(model_run_refs or []),
                    parent_forecast_id,
                    forecast_origin,
                    agent_model,
                    prompt_version,
                    forecasting_protocol_version or FORECASTING_PROTOCOL_VERSION,
                    toolset_version,
                    json_dumps(source_snapshot_refs or []),
                    cutoff_ts,
                    backtest_run_id,
                    1 if calibration_eligible else 0,
                    calibration_weight,
                    json_dumps(calibration_lesson_refs or []),
                    json_dumps(calibration_adjustment or {}),
                    json_dumps(snapshot_metadata),
                    json_dumps(reasons_up_list),
                    json_dumps(reasons_down_list),
                    json_dumps(change_my_mind_list),
                ),
            )
            if set_current:
                conn.execute(
                    "UPDATE forecast_questions SET current_forecast_id = ? WHERE id = ?",
                    (forecast_id, question_id),
                )
        if panel_run_ref:
            self.attach_panel_to_snapshot(panel_run_ref, forecast_id)
        # A member commit re-freshens its parent thesis/factor aggregates so the
        # desk never shows a thesis that "hasn't moved" while its members have.
        # Runs POST-transaction (the `with conn` block above has closed) so the
        # parent re-aggregate's writes never deadlock the just-committed member
        # write; cycle-guarded + fail-open; a no-op (one indexed lookup) when the
        # question has no parents — i.e. on the common forecast commit.
        if set_current and forecast_origin == "live":
            self._cascade_reaggregate_parents(question_id, as_of=as_of_ts)
        # Coverage ledger: record which active lessons were in scope at this live
        # commit, so `forecast lessons audit` can show whether each is actually used.
        if forecast_origin == "live":
            self._record_lesson_applications(question, forecast_id, probability_or_distribution, calibration_adjustment)
        # Programmatic escalation (Wave 3 H4): a programmatic commit (refresh /
        # aggregate / autopilot — the lenient autofix paths that never hard-block)
        # whose recorded saturation is under the sweep bar escalates the SAME deduped
        # WARN under-saturation alert the scheduled sweep raises, so the leniency
        # stays but the under-saturation becomes VISIBLE + actionable. Live-only,
        # deduped, fail-open; the AGENT path (no autofix — it sees the tool-result
        # advisory instead) and non-live origins are untouched. Disable with
        # FORECAST_DISABLE_SATURATION_ESCALATION.
        if (
            set_current
            and forecast_origin == "live"
            and (style_autofix or distribution_autofix)
            and os.environ.get("FORECAST_DISABLE_SATURATION_ESCALATION", "").strip().lower()
            not in {"1", "true", "yes", "on"}
        ):
            try:
                self.enqueue_saturation_alert(question_id, snapshot_metadata.get("saturation"))
            except Exception:  # visibility is best-effort and must NEVER break a commit
                logger.debug("saturation escalation failed (non-fatal)", exc_info=True)
        return self.get_snapshot(forecast_id)

    def _thesis_auto_aggregate_enabled(self, thesis_id: str) -> bool:
        """Per-thesis opt-out of the member-commit re-aggregate cascade
        (metadata.forecast_hooks.auto_aggregate = false)."""
        try:
            q = self.get_question(thesis_id)
            meta = (getattr(q, "metadata", None) or {}).get("forecast_hooks") or {}
            return meta.get("auto_aggregate", True) is not False
        except Exception:
            return True

    def _cascade_reaggregate_parents(self, member_id: str, *, as_of: str | None = None) -> None:
        """Re-aggregate every parent thesis/factor of a just-committed member so
        their stored member contributions + health track the live members
        (``aggregate_thesis`` auto-dispatches to the factor portfolio math, so one
        call covers both). Each parent's own aggregate commit re-enters this method
        via ``create_snapshot``, freshening grandparents up the DAG; a
        per-top-commit visited-set bounds the work and breaks cycles. Fail-open: a
        cascade error never breaks the member commit. Disable globally with
        ``FORECAST_DISABLE_THESIS_CASCADE``."""
        if os.environ.get("FORECAST_DISABLE_THESIS_CASCADE", "").strip().lower() in {"1", "true", "yes", "on"}:
            return
        try:
            parents = self.list_theses_for_member(member_id)
        except Exception:
            return
        if not parents:
            return
        visited = getattr(_CASCADE_TLS, "visited", None)
        top = visited is None
        if top:
            visited = set()
            _CASCADE_TLS.visited = visited
        try:
            for parent in parents:
                pid = parent.get("thesis_id")
                if not pid or pid == member_id or pid in visited:
                    continue
                visited.add(pid)
                if not self._thesis_auto_aggregate_enabled(pid):
                    continue
                try:
                    # analyst_note=False: a member move must not spam the parent's
                    # analyst log with a re-aggregation brief on every commit.
                    self.aggregate_thesis(pid, now=as_of, analyst_note=False)
                except Exception:
                    logger.debug("thesis/factor cascade re-aggregate failed for parent %s", pid, exc_info=True)
        finally:
            if top:
                _CASCADE_TLS.visited = None

    def get_snapshot(self, forecast_id: str) -> ForecastSnapshot:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_snapshots WHERE forecast_id = ?",
                (forecast_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast snapshot not found: {forecast_id}")
        return self._row_to_snapshot(row)

    def get_current_snapshot(self, question_id: str) -> ForecastSnapshot | None:
        question = self.get_question(question_id)
        if not question.current_forecast_id:
            return None
        return self.get_snapshot(question.current_forecast_id)

    def list_snapshots(self, question_id: str) -> list[ForecastSnapshot]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM forecast_snapshots WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        return [self._row_to_snapshot(row) for row in rows]

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
        source = source.strip()
        if not source:
            raise ValidationError("ingest source is required")
        candidate_id = f"ic_{uuid.uuid4().hex[:12]}"
        source_type = self._infer_ingest_source_type(source)
        extracted = self._extract_ingest_metadata(source, source_type)
        candidate_title = (
            title
            or extracted.get("title")
            or self._candidate_title_from_source(source, source_type)
        ).strip()
        candidate_description = description or str(extracted.get("description") or "")
        candidate_resolution_criteria = resolution_criteria or str(extracted.get("resolution_criteria") or "")
        candidate_resolution_source = resolution_source or extracted.get("resolution_source")
        candidate_close_time = close_time or extracted.get("close_time")
        candidate_resolution_time = resolution_time or extracted.get("resolution_time")
        extracted_outcome = extracted.get("outcome_space")
        outcome = outcome_space or (
            OutcomeSpace.from_dict(extracted_outcome) if isinstance(extracted_outcome, dict) else OutcomeSpace()
        )
        candidate_metadata = dict(extracted.get("metadata") or {})
        candidate_metadata.update(metadata or {})
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingest_candidates (
                    id, source, source_type, created_at, candidate_title,
                    description, resolution_criteria, resolution_source,
                    close_time, resolution_time, outcome_space, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    source,
                    source_type,
                    utc_now_iso(),
                    candidate_title,
                    candidate_description,
                    candidate_resolution_criteria,
                    candidate_resolution_source,
                    parse_timestamp(candidate_close_time, field_name="close_time"),
                    parse_timestamp(candidate_resolution_time, field_name="resolution_time"),
                    outcome.to_json(),
                    json_dumps(candidate_metadata),
                ),
            )
        return self.get_ingest_candidate(candidate_id)

    def get_ingest_candidate(self, candidate_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ingest_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"ingest candidate not found: {candidate_id}")
        return self._row_to_ingest_candidate(row)

    def list_ingest_candidates(self, *, status: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM ingest_candidates {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self._row_to_ingest_candidate(row) for row in rows]

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
        candidate = self.get_ingest_candidate(candidate_id)
        if candidate["status"] != "proposed":
            raise ValidationError("only proposed ingest candidates can be confirmed")
        final_title = title or candidate["candidate_title"]
        final_criteria = resolution_criteria if resolution_criteria is not None else candidate["resolution_criteria"]
        if not final_criteria.strip():
            raise ValidationError("confirmation requires resolution criteria")
        outcome_space = OutcomeSpace.from_dict(candidate["outcome_space"])
        baseline_payloads = self._candidate_baseline_payloads(candidate["metadata"])
        for baseline in baseline_payloads:
            self._validate_probability_payload(self._baseline_probability_value(baseline), outcome_space)
        question = self.create_question(
            title=final_title,
            description=candidate["description"],
            resolution_criteria=final_criteria,
            resolution_source=candidate["resolution_source"],
            outcome_space=outcome_space,
            close_time=candidate["close_time"],
            resolution_time=candidate["resolution_time"],
            tags=tags or ["ingested"],
            domain=domain,
            topics=topics or [],
            metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
        )
        self.add_evidence(
            question_id=question.id,
            source_or_note=candidate["source"],
            claim="Original ingest source for forecast question.",
            source_type=candidate["source_type"],
            metadata={"ingest_candidate_id": candidate_id},
        )
        for baseline in baseline_payloads:
            self.add_baseline_comparison(
                question_id=question.id,
                source=str(baseline.get("source") or candidate["source_type"]),
                baseline_type=str(baseline.get("baseline_type") or "imported"),
                probability_or_distribution=self._baseline_probability_value(baseline),
                as_of=baseline.get("as_of"),
                metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
            )
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingest_candidates
                SET status = 'confirmed', confirmed_question_id = ?
                WHERE id = ?
                """,
                (question.id, candidate_id),
            )
        return question

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
        self.get_question(question_id)
        if not text.strip():
            raise ValidationError("assumption text is required")
        if status not in ASSUMPTION_STATUSES:
            raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
        assumption_id = f"as_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO assumptions (
                    id, question_id, text, status, created_at,
                    check_cadence, evidence_refs, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assumption_id,
                    question_id,
                    text.strip(),
                    status,
                    utc_now_iso(),
                    check_cadence,
                    json_dumps(evidence_refs or []),
                    notes,
                ),
            )
        return self.get_assumption(assumption_id)

    def update_assumption(
        self,
        assumption_id: str,
        *,
        status: str | None = None,
        last_checked_at: str | None = None,
        invalidated_at: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        current = self.get_assumption(assumption_id)
        new_status = status or current["status"]
        if new_status not in ASSUMPTION_STATUSES:
            raise ValidationError(f"assumption status must be one of {', '.join(sorted(ASSUMPTION_STATUSES))}")
        checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
        invalidated = (
            parse_timestamp(invalidated_at, field_name="invalidated_at")
            if invalidated_at
            else current["invalidated_at"]
        )
        if new_status == "invalidated" and invalidated is None:
            invalidated = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE assumptions
                SET status = ?, last_checked_at = ?, invalidated_at = ?, notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (new_status, checked, invalidated, notes, assumption_id),
            )
        return self.get_assumption(assumption_id)

    def get_assumption(self, assumption_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM assumptions WHERE id = ?", (assumption_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"assumption not found: {assumption_id}")
        data = dict(row)
        data["evidence_refs"] = json_loads(data["evidence_refs"], [])
        return data

    def list_assumptions(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM assumptions WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["evidence_refs"] = json_loads(data["evidence_refs"], [])
            result.append(data)
        return result

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
        self.get_question(question_id)
        if not name.strip():
            raise ValidationError("reference class name is required")
        if not inclusion_criteria.strip():
            raise ValidationError("reference class inclusion criteria are required")
        if base_rate is not None and not (0 <= base_rate <= 1):
            raise ValidationError("base_rate must be between 0 and 1")
        if base_rate_uncertainty is not None and base_rate_uncertainty < 0:
            raise ValidationError("base_rate_uncertainty must be non-negative")
        if sample_size is not None and int(sample_size) < 0:
            raise ValidationError("sample_size (n observations behind the base rate) must be non-negative")
        reference_class_id = f"rc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reference_classes (
                    id, question_id, name, inclusion_criteria, exclusion_criteria,
                    base_rate, base_rate_uncertainty, source_refs, created_at,
                    check_cadence, notes, sample_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reference_class_id,
                    question_id,
                    name.strip(),
                    inclusion_criteria.strip(),
                    exclusion_criteria,
                    base_rate,
                    base_rate_uncertainty,
                    json_dumps(source_refs or []),
                    utc_now_iso(),
                    check_cadence,
                    notes,
                    int(sample_size) if sample_size is not None else None,
                ),
            )
        return self.get_reference_class(reference_class_id)

    def delete_reference_class(self, reference_class_id: str) -> None:
        """Hard-delete a reference class. Intended for compensating rollback of an inline
        reference class created during a forecast commit that was then rejected — so a
        refused snapshot never orphans an unlinked anchor."""
        with self._connect() as conn:
            conn.execute("DELETE FROM reference_classes WHERE id = ?", (reference_class_id,))

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
        current = self.get_reference_class(reference_class_id)
        new_status = status or current["status"]
        if new_status not in REFERENCE_CLASS_STATUSES:
            raise ValidationError(
                f"reference class status must be one of {', '.join(sorted(REFERENCE_CLASS_STATUSES))}"
            )
        checked = parse_timestamp(last_checked_at, field_name="last_checked_at") if last_checked_at else current["last_checked_at"]
        invalidated = (
            parse_timestamp(invalidated_at, field_name="invalidated_at")
            if invalidated_at
            else current["invalidated_at"]
        )
        if new_status == "invalidated" and invalidated is None:
            invalidated = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE reference_classes
                SET status = ?, last_checked_at = ?, invalidated_at = ?,
                    check_cadence = COALESCE(?, check_cadence),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (new_status, checked, invalidated, check_cadence, notes, reference_class_id),
            )
        return self.get_reference_class(reference_class_id)

    def get_reference_class(self, reference_class_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM reference_classes WHERE id = ?",
                (reference_class_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"reference class not found: {reference_class_id}")
        data = dict(row)
        data["source_refs"] = json_loads(data["source_refs"], [])
        return data

    def list_reference_classes(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM reference_classes WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["source_refs"] = json_loads(data["source_refs"], [])
            result.append(data)
        return result

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
        """Register a decisive variable the resolution hinges on, with the source
        roles that would satisfy it + its current evidence status. Idempotent on
        (question_id, crux_variable): re-adding updates the existing crux."""
        self.get_question(question_id)
        crux_variable = crux_variable.strip()
        if not crux_variable:
            raise ValidationError("crux_variable is required")
        if materiality not in CRUX_MATERIALITY:
            raise ValidationError("materiality must be one of: " + ", ".join(sorted(CRUX_MATERIALITY)))
        if status not in CRUX_STATUS:
            raise ValidationError("status must be one of: " + ", ".join(sorted(CRUX_STATUS)))
        roles = list(preferred_roles or [])
        for role in roles:
            if role not in WATCH_SOURCE_ROLES:
                raise ValidationError("preferred_roles must be drawn from: " + ", ".join(sorted(WATCH_SOURCE_ROLES)))
        now = utc_now_iso()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM question_cruxes WHERE question_id = ? AND crux_variable = ?",
                (question_id, crux_variable),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE question_cruxes SET preferred_roles = ?, materiality = ?, status = ?, notes = ?, updated_at = ? WHERE id = ?",
                    (json_dumps(roles), materiality, status, notes, now, existing["id"]),
                )
                crux_id = existing["id"]
            else:
                crux_id = f"cx_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    "INSERT INTO question_cruxes (id, question_id, crux_variable, preferred_roles, materiality, status, notes, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (crux_id, question_id, crux_variable, json_dumps(roles), materiality, status, notes, now, now),
                )
        return self.get_crux(crux_id)

    def get_crux(self, crux_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM question_cruxes WHERE id = ?", (crux_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"crux not found: {crux_id}")
        data = dict(row)
        data["preferred_roles"] = json_loads(data["preferred_roles"], [])
        return data

    def list_cruxes(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM question_cruxes WHERE question_id = ? ORDER BY created_at ASC", (question_id,)
            ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["preferred_roles"] = json_loads(data["preferred_roles"], [])
            out.append(data)
        return out

    def set_crux_status(self, crux_id: str, status: str) -> dict[str, Any]:
        if status not in CRUX_STATUS:
            raise ValidationError("status must be one of: " + ", ".join(sorted(CRUX_STATUS)))
        self.get_crux(crux_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE question_cruxes SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now_iso(), crux_id),
            )
        return self.get_crux(crux_id)

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
        self.get_question(question_id)
        if not model_type.strip():
            raise ValidationError("model_type is required")
        if status not in {"success", "failure"}:
            raise ValidationError("model run status must be success or failure")
        model_run_id = f"mr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO model_runs (
                    id, question_id, created_at, model_type, status, inputs, parameters,
                    output, diagnostics, code_ref, artifact_paths, model_version,
                    prompt_version, data_version, evidence_cutoff, market_model_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_run_id,
                    question_id,
                    utc_now_iso(),
                    model_type.strip(),
                    status,
                    json_dumps(inputs or {}),
                    json_dumps(parameters or {}),
                    json_dumps(output or {}),
                    json_dumps(diagnostics or {}),
                    code_ref,
                    json_dumps(artifact_paths or []),
                    model_version,
                    prompt_version,
                    data_version,
                    parse_timestamp(evidence_cutoff, field_name="evidence_cutoff"),
                    market_model_id,
                ),
            )
        return self.get_model_run(model_run_id)

    def link_question_market_model(self, question_id: str, market_model_id: str) -> ForecastQuestion:
        """Record the question<->market-model edge on the QUESTION side.

        Writes ``metadata['source_market_model']`` (the reciprocal of the model
        spec's ``forecast_question_id``), so a question built/seeded from a Market
        Model carries the link both ways. Idempotent — re-linking the same model is
        a no-op. The spec side is written by the caller via
        :meth:`update_market_model_spec`."""
        question = self.get_question(question_id)
        meta = dict(question.metadata) if isinstance(question.metadata, dict) else {}
        if meta.get("source_market_model") == market_model_id:
            return question
        meta["source_market_model"] = market_model_id
        with self._connect() as conn:
            conn.execute(
                "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
                (json_dumps(meta), question_id),
            )
        return self.get_question(question_id)

    def get_model_run(self, model_run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (model_run_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"model run not found: {model_run_id}")
        return self._row_to_model_run(row)

    def list_model_runs(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_runs WHERE question_id = ? ORDER BY created_at ASC",
                (question_id,),
            ).fetchall()
        return [self._row_to_model_run(row) for row in rows]

    # ── R4 Living Models: score model runs at resolution ────────────────
    @staticmethod
    def _model_run_probability(output: dict[str, Any]) -> float | None:
        """Read a projected PROBABILITY in [0,1] from a model_run output, if one
        is present. Only genuine model projections carry these keys — a
        ``forecast_refresh`` run stores ``proposed_probability`` (deliberately not
        matched here) so the desk's own committed number never masquerades as an
        independent model observation."""
        if not isinstance(output, dict):
            return None
        for key in ("probability", "value", "projected_value", "p", "base_rate"):
            raw = output.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue
            val = float(raw)
            if math.isfinite(val) and 0.0 <= val <= 1.0:
                return val
        return None

    @staticmethod
    def _model_run_numeric(output: dict[str, Any]) -> tuple[float | None, float | None, float | None]:
        """Read ``(projected_value, lo, hi)`` from a model_run output for numeric
        interval scoring. Any of the three may be None."""
        if not isinstance(output, dict):
            return None, None, None

        def _num(*keys: str) -> float | None:
            for key in keys:
                raw = output.get(key)
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    continue
                val = float(raw)
                if math.isfinite(val):
                    return val
            return None

        return _num("projected_value", "value", "mean", "point"), _num("lo", "lower"), _num("hi", "upper")

    def score_model_runs(
        self,
        question_id: str,
        outcome: Any,
        *,
        now: str | None = None,
    ) -> list[dict[str, Any]]:
        """Score this question's model_runs against a confirmed ``outcome`` and
        persist ``outcome_score`` / ``interval_hit`` / ``scored_at`` on each row.

        * BINARY question — Brier of the model's projected probability (via the
          same :meth:`_score_forecast_payload` path as a snapshot). ``interval_hit``
          stays NULL (the read-side discriminator for a binary-Brier observation).
        * NUMERIC question — coverage: ``interval_hit`` is 1 when the outcome falls
          inside the model's ``[lo, hi]`` (else 0; NULL when the model emitted no
          interval); ``outcome_score`` is the absolute error vs ``projected_value``.

        Only runs whose output carries a usable projection are scored; the rest are
        left untouched. Best-effort per run — never raises (the caller in
        :meth:`resolve_question` is already fail-open, but a malformed single run
        must not skip its siblings). Returns the list of scored-run summaries."""
        question = self.get_question(question_id)
        stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
        scored: list[dict[str, Any]] = []
        for run in self.list_model_runs(question_id):
            output = run.get("output") if isinstance(run.get("output"), dict) else {}
            outcome_score: float | None = None
            interval_hit: int | None = None
            try:
                if question.outcome_space.type == "binary":
                    prob = self._model_run_probability(output)
                    if prob is None:
                        continue
                    payload = self._score_forecast_payload(
                        prob, outcome, question.outcome_space
                    )
                    brier = payload.get("brier_score")
                    if not isinstance(brier, (int, float)):
                        continue
                    outcome_score = float(brier)
                elif question.outcome_space.type == "numeric":
                    projected, lo, hi = self._model_run_numeric(output)
                    if projected is None and lo is None and hi is None:
                        continue
                    outcome_value = self._numeric_outcome(outcome)
                    if lo is not None and hi is not None:
                        low, high = (lo, hi) if lo <= hi else (hi, lo)
                        interval_hit = 1 if low <= outcome_value <= high else 0
                    if projected is not None:
                        outcome_score = abs(projected - outcome_value)
                    if outcome_score is None and interval_hit is None:
                        continue
                else:
                    continue
            except (TypeError, ValueError, ValidationError):
                continue
            with self._connect() as conn:
                conn.execute(
                    "UPDATE model_runs SET outcome_score = ?, interval_hit = ?, scored_at = ? WHERE id = ?",
                    (outcome_score, interval_hit, stamped, run["id"]),
                )
            scored.append(
                {
                    "model_run_id": run["id"],
                    "model_type": run.get("model_type"),
                    "market_model_id": run.get("market_model_id"),
                    "outcome_score": outcome_score,
                    "interval_hit": interval_hit,
                }
            )
        return scored

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
        resolved_question = self.get_question(question_id)
        if resolution_status not in RESOLUTION_STATUSES:
            raise ValidationError(
                f"resolution_status must be one of {', '.join(sorted(RESOLUTION_STATUSES))}"
            )
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("resolution confidence must be between 0 and 1")
        if resolution_status == "corrected" and not correction_ref:
            raise ValidationError("corrected resolutions require correction_ref")
        if trusted_policy_id:
            policy = self.get_trusted_resolver_policy(trusted_policy_id)
            if not policy["enabled"]:
                raise ValidationError("trusted resolver policy is disabled")
        now = utc_now_iso()
        resolution_id = f"rs_{uuid.uuid4().hex[:12]}"
        if resolution_source and resolution_source_snapshot_ref is None:
            source_path = Path(resolution_source).expanduser()
            if source_path.is_file():
                resolution_source_snapshot_ref = self._archive_resolution_source_snapshot(
                    question_id=question_id,
                    resolution_id=resolution_id,
                    source_file_path=source_path,
                )
        confirmed_at = now if resolution_status == "confirmed" and criteria_satisfied else None
        disputed_at = now if resolution_status == "disputed" else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO resolutions (
                    id, question_id, resolved_at, outcome, resolution_source,
                    resolution_source_snapshot_ref, resolver_type, resolution_status,
                    criteria_satisfied, confidence, confirmed_at, confirmed_by,
                    resolver_notes, disputed_at, correction_ref, scoreable,
                    trusted_policy_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution_id,
                    question_id,
                    now,
                    json_dumps(outcome),
                    resolution_source,
                    resolution_source_snapshot_ref,
                    resolver_type,
                    resolution_status,
                    1 if criteria_satisfied else 0,
                    confidence,
                    confirmed_at,
                    confirmed_by,
                    resolver_notes,
                    disputed_at,
                    correction_ref,
                    1 if scoreable else 0,
                    trusted_policy_id,
                ),
            )
            if resolution_status == "confirmed" and criteria_satisfied:
                conn.execute(
                    "UPDATE forecast_questions SET status = 'resolved' WHERE id = ?",
                    (question_id,),
                )
            elif resolution_status == "proposed":
                conn.execute(
                    "UPDATE forecast_questions SET status = 'closed' WHERE id = ? AND status = 'active'",
                    (question_id,),
                )
            if trusted_policy_id and resolution_status == "confirmed":
                conn.execute(
                    "UPDATE trusted_resolver_policies SET last_used_at = ? WHERE id = ?",
                    (now, trusted_policy_id),
                )

        # Auto-score on a confirmed, criteria-satisfied, scoreable resolution so
        # a forecast cannot resolve without a Brier/log score — closing the
        # feedback loop (calibration, postmortems, lessons) automatically. Only
        # scores a committed forecast (origin != "exploratory"); exploratory
        # scratchpad snapshots are never scored. Best-effort: a scoring hiccup
        # must never break the resolution itself, and score_snapshot is
        # idempotent so a later explicit `score` is a no-op.
        if auto_score and resolution_status == "confirmed" and criteria_satisfied and scoreable:
            try:
                snapshot = self.get_current_snapshot(question_id)
                if snapshot is not None and snapshot.forecast_origin != "exploratory":
                    self.score_snapshot(snapshot.forecast_id)
                    # Close the learning loop: a fresh LIVE score can shift the signed-
                    # bias picture, so re-synthesise the corrective calibration lesson
                    # for this question's scope family. synthesize_bias_lessons is
                    # internally FDR/ESS-gated — it emits nothing on thin/noisy data —
                    # so this is safe to fire on a live resolution. Gated on
                    # forecast_origin == "live" for BOTH correctness and cost: the
                    # synthesis measures the LIVE stratum only (forecast_origin="live"),
                    # so firing it on a backtest/imported resolution would rescan the
                    # same live data for no new signal — pure waste (and the per-resolve
                    # scan is O(live-scores), so a bulk backtest must not trigger it).
                    # Scoped to the resolved question's domain (or global when it has
                    # none) to bound cost to a single domain target, not the full "all"
                    # sweep. Best-effort: a synthesis hiccup must never break the
                    # resolution — a broken step degrades to today's behaviour.
                    # Cheap pre-gate (spend bound): the signed-bias estimator emits
                    # NOTHING until a scope clears its ESS floor (12 domain / 20
                    # global), and each synthesis is O(live-scores) — so a single
                    # COUNT skips the whole scan whenever the scope is still obviously
                    # too thin. This makes an ordinary small desk (and a bulk cohort
                    # below the floor) pay nothing, and only mature scopes run the
                    # full synthesis. Count is a necessary condition (ESS <= count),
                    # so skipping below it can never suppress a lesson that would fire.
                    synth_scope = resolved_question.domain or "global"
                    _floor = 12 if resolved_question.domain else 20
                    _now_mono = time.monotonic()
                    _last = self._bias_synth_last.get(synth_scope)
                    _debounced = _last is not None and (_now_mono - _last) < self._BIAS_SYNTH_DEBOUNCE_SECONDS
                    if (
                        snapshot.forecast_origin == "live"
                        and not _debounced
                        and self._live_score_count(resolved_question.domain) >= _floor
                    ):
                        self._bias_synth_last[synth_scope] = _now_mono
                        try:
                            synthesized = self.synthesize_bias_lessons(scope=synth_scope, now=now)
                            fired = [
                                r for r in synthesized
                                if isinstance(r, dict) and (r.get("action") or {}).get("written")
                            ]
                            if fired:
                                logger.debug(
                                    "auto bias-lesson synthesis on resolution of %s wrote %d lesson(s)",
                                    question_id,
                                    len(fired),
                                )
                        except Exception:
                            logger.debug(
                                "auto bias-lesson synthesis on resolution failed for %s",
                                question_id,
                                exc_info=True,
                            )
            except Exception:
                logger.debug("auto-score on resolution failed for %s", question_id, exc_info=True)

        # Operator practice loop (R2): score the OPERATOR's own estimates for
        # this question against the confirmed outcome — fail-open, exactly like
        # auto-score, and independent of the system-scoreable flag (the operator's
        # practice number is scored against the same realized outcome). A hiccup
        # here must never break the resolution itself.
        if resolution_status == "confirmed" and criteria_satisfied:
            try:
                self.score_operator_estimates(question_id, outcome, now=now)
            except Exception:
                logger.debug(
                    "operator-estimate scoring on resolution failed for %s",
                    question_id,
                    exc_info=True,
                )

        # R4 Living Models: score this question's model_runs against the confirmed
        # outcome so a model's skill accrues (model_skill reads these on-read).
        # Fail-open + gated on scoreable exactly like auto-score — a scoring hiccup
        # must never break the resolution itself.
        if resolution_status == "confirmed" and criteria_satisfied and scoreable:
            try:
                self.score_model_runs(question_id, outcome, now=now)
            except Exception:
                logger.debug(
                    "model-run scoring on resolution failed for %s",
                    question_id,
                    exc_info=True,
                )

        return self.get_resolution(resolution_id)

    def get_resolution(self, resolution_id: str) -> Resolution:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resolutions WHERE id = ?", (resolution_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"resolution not found: {resolution_id}")
        return self._row_to_resolution(row)

    def get_latest_resolution(
        self,
        question_id: str,
        *,
        confirmed_only: bool = False,
    ) -> Resolution | None:
        clauses = ["question_id = ?"]
        params: list[Any] = [question_id]
        if confirmed_only:
            clauses.extend(["resolution_status = 'confirmed'", "criteria_satisfied = 1", "scoreable = 1"])
        with self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM resolutions
                WHERE {' AND '.join(clauses)}
                ORDER BY resolved_at DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return self._row_to_resolution(row) if row else None

    def score_question(self, question_id: str, *, force: bool = False) -> ScoreRecord:
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None:
            raise ValidationError("cannot score a question with no forecast snapshot")
        return self.score_snapshot(snapshot.forecast_id, force=force)

    def get_current_score(self, question_id: str) -> ScoreRecord | None:
        """Return the score for the current snapshot against the confirmed
        resolution, if one has already been recorded; else None. Read-only —
        does not trigger scoring."""
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None:
            return None
        resolution = self.get_latest_resolution(question_id, confirmed_only=True)
        if resolution is None:
            return None
        return self._existing_score(snapshot.forecast_id, resolution.id)

    def score_snapshot(self, forecast_id: str, *, force: bool = False) -> ScoreRecord:
        snapshot = self.get_snapshot(forecast_id)
        question = self.get_question(snapshot.question_id)
        resolution = self.get_latest_resolution(snapshot.question_id, confirmed_only=True)
        if resolution is None:
            raise ValidationError(
                "cannot score until resolution is confirmed, criteria-satisfied, and scoreable"
            )

        if not force:
            existing = self._existing_score(snapshot.forecast_id, resolution.id)
            if existing is not None:
                return existing

        scoring = self._score_forecast_payload(
            snapshot.probability_or_distribution,
            resolution.outcome,
            question.outcome_space,
        )
        score_id = f"sc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO score_records (
                    id, question_id, forecast_id, resolution_id, scored_at,
                    brier_score, log_score, proper_score, score_rule, calibration_bucket,
                    forecast_horizon_days, domain, forecast_origin,
                    calibration_eligible, calibration_weight, baseline_ref, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    score_id,
                    snapshot.question_id,
                    snapshot.forecast_id,
                    resolution.id,
                    utc_now_iso(),
                    scoring["brier_score"],
                    scoring["log_score"],
                    scoring["proper_score"],
                    scoring["score_rule"],
                    scoring["calibration_bucket"],
                    snapshot.forecast_horizon_days,
                    question.domain,
                    snapshot.forecast_origin,
                    1 if snapshot.calibration_eligible else 0,
                    snapshot.calibration_weight,
                    scoring["notes"],
                ),
            )
        score = self.get_score(score_id)
        if score.calibration_eligible and score.forecast_origin == "live":
            self.update_domain_error_profile(question)
        return score

    def get_score(self, score_id: str) -> ScoreRecord:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM score_records WHERE id = ?", (score_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"score record not found: {score_id}")
        return self._row_to_score(row)

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
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if forecast_origin:
            clauses.append("forecast_origin = ?")
            params.append(forecast_origin)
        if calibration_eligible is not None:
            clauses.append("calibration_eligible = ?")
            params.append(1 if calibration_eligible else 0)
        if bucket:
            clauses.append("calibration_bucket = ?")
            params.append(bucket)
        if not include_invalidated:
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM score_records {where} ORDER BY scored_at DESC",
                params,
            ).fetchall()
        return [
            score
            for score in (self._row_to_score(row) for row in rows)
            if self._horizon_matches(score.forecast_horizon_days, horizon)
        ]

    def calibration_summary(
        self,
        *,
        domain: str | None = None,
        forecast_origin: str | None = None,
        horizon: str | None = None,
        calibration_eligible: bool | None = True,
    ) -> dict[str, Any]:
        all_scores = self.list_scores(
            domain=domain,
            forecast_origin=forecast_origin,
            calibration_eligible=calibration_eligible,
        )
        scores = [
            score
            for score in all_scores
            if self._horizon_matches(score.forecast_horizon_days, horizon)
        ]
        buckets: dict[str, list[float]] = defaultdict(list)
        # Reliability-diagram accumulators, keyed by P(yes) decile (0..9). For
        # binary questions we record the forecast's P(yes) and the realized
        # outcome (1.0 yes / 0.0 no) so we can compare predicted vs observed
        # frequency and compute the Expected Calibration Error.
        curve_bins: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {"predicted": [], "observed": []}
        )
        sharpness_values: list[float] = []
        probability_movements: list[float] = []
        # Time-bucketed calibration trend points (keyed on scored_at). Each row is
        # {scored_at, brier, p_yes, outcome} — p_yes/outcome present only for binary
        # forecasts so the rolling SCE can be computed per window.
        trend_points: list[dict[str, Any]] = []
        question_type_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "brier": [],
                "log": [],
                "proper": [],
                "sharpness": [],
                "score_rules": set(),
                "score_count": 0,
            }
        )
        component_stats: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {
                "probability": [],
                "weight": [],
                "weight_share": [],
                "contribution": [],
                "distance_from_forecast": [],
            }
        )
        for score in scores:
            outcome_space = None
            try:
                outcome_space = self.get_question(score.question_id).outcome_space
                question_type = outcome_space.type
            except LedgerNotFoundError:
                question_type = "unknown"
            type_stats = question_type_stats[question_type]
            type_stats["score_count"] += 1
            if score.brier_score is not None:
                type_stats["brier"].append(score.brier_score)
            if score.log_score is not None:
                type_stats["log"].append(score.log_score)
            if score.proper_score is not None:
                type_stats["proper"].append(score.proper_score)
            if score.score_rule:
                type_stats["score_rules"].add(score.score_rule)
            if score.brier_score is not None:
                buckets[score.calibration_bucket or "unknown"].append(score.brier_score)
            try:
                snapshot = self.get_snapshot(score.forecast_id)
            except LedgerNotFoundError:
                continue
            if score.brier_score is None:
                continue
            sharpness = self._sharpness(snapshot.probability_or_distribution)
            if sharpness is not None:
                sharpness_values.append(sharpness)
                type_stats["sharpness"].append(sharpness)
            # Trend point (all scoreable): rolling mean-Brier keyed on scored_at.
            trend_point: dict[str, Any] = {
                "scored_at": score.scored_at,
                "brier": float(score.brier_score),
                "p_yes": None,
                "outcome": None,
            }
            # Reliability point: bin the binary forecast by P(yes) and record the
            # realized outcome so observed frequency can be compared to it.
            if (
                outcome_space is not None
                and outcome_space.type == "binary"
                and isinstance(snapshot.probability_or_distribution, (int, float))
            ):
                observed = self._binary_outcome_value(score, outcome_space)
                if observed is not None:
                    p_yes = float(snapshot.probability_or_distribution)
                    decile = min(int(p_yes * 10), 9)
                    curve_bins[decile]["predicted"].append(p_yes)
                    curve_bins[decile]["observed"].append(observed)
                    # p_yes/outcome feed the per-window signed calibration error.
                    trend_point["p_yes"] = p_yes
                    trend_point["outcome"] = observed
            trend_points.append(trend_point)
            movement = self._score_probability_movement_before_close(score, snapshot)
            if movement is not None:
                probability_movements.append(movement)
            for component in self._snapshot_component_contributions(snapshot):
                stats = component_stats[component["name"]]
                stats["probability"].append(component["probability"])
                stats["weight"].append(component["weight"])
                stats["weight_share"].append(component["weight_share"])
                stats["contribution"].append(component["contribution"])
                if component["distance_from_forecast"] is not None:
                    stats["distance_from_forecast"].append(component["distance_from_forecast"])
        bucket_rows = []
        canonical_buckets = [f"{i / 10:.1f}-{(i + 1) / 10:.1f}" for i in range(10)]
        ordered_buckets = canonical_buckets + sorted(
            bucket for bucket in buckets if bucket not in canonical_buckets
        )
        for bucket in ordered_buckets:
            values = buckets.get(bucket, [])
            bucket_rows.append(
                {
                    "bucket": bucket,
                    "count": len(values),
                    "mean_brier": sum(values) / len(values) if values else None,
                    "sample_status": "empty" if not values else ("low_sample" if len(values) < 5 else "ok"),
                }
            )
        all_values = [score.brier_score for score in scores if score.brier_score is not None]
        log_values = [score.log_score for score in scores if score.log_score is not None]
        component_rows = [
            {
                "name": name,
                "count": len(stats["contribution"]),
                "mean_probability": self._mean(stats["probability"]),
                "mean_weight": self._mean(stats["weight"]),
                "mean_weight_share": self._mean(stats["weight_share"]),
                "mean_contribution": self._mean(stats["contribution"]),
                "mean_abs_distance_from_forecast": self._mean(
                    [abs(value) for value in stats["distance_from_forecast"]]
                ),
            }
            for name, stats in component_stats.items()
            if stats["contribution"]
        ]
        question_type_rows = [
            {
                "question_type": question_type,
                "count": int(stats["score_count"]),
                "brier_count": len(stats["brier"]),
                "mean_brier": self._mean(stats["brier"]),
                "mean_log_score": self._mean(stats["log"]),
                "mean_proper_score": self._mean(stats["proper"]),
                "mean_sharpness": self._mean(stats["sharpness"]),
                "score_rules": sorted(stats["score_rules"]),
            }
            for question_type, stats in question_type_stats.items()
        ]
        # Reliability curve on P(yes) + Expected/Max Calibration Error. ECE is the
        # sample-weighted mean gap between observed frequency and mean predicted
        # probability across the populated deciles; MCE is the worst single gap.
        curve_rows = []
        ece_numerator = 0.0
        ece_denominator = 0
        max_calibration_error = 0.0
        for index in range(10):
            data = curve_bins.get(index)
            predicted = data["predicted"] if data else []
            observed = data["observed"] if data else []
            count = len(observed)
            mean_predicted = sum(predicted) / count if count else None
            observed_frequency = sum(observed) / count if count else None
            gap = (
                abs(observed_frequency - mean_predicted)
                if count and mean_predicted is not None
                else None
            )
            curve_rows.append(
                {
                    "bucket": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                    "count": count,
                    "mean_predicted": mean_predicted,
                    "observed_frequency": observed_frequency,
                    "calibration_gap": gap,
                    "sample_status": "empty"
                    if not count
                    else ("low_sample" if count < 5 else "ok"),
                }
            )
            if count and gap is not None:
                ece_numerator += count * gap
                ece_denominator += count
                max_calibration_error = max(max_calibration_error, gap)
        expected_calibration_error = (
            ece_numerator / ece_denominator if ece_denominator else None
        )
        curve_predicted = [
            value for data in curve_bins.values() for value in data["predicted"]
        ]
        curve_observed = [
            value for data in curve_bins.values() for value in data["observed"]
        ]
        return {
            "count": len(all_values),
            "mean_brier": sum(all_values) / len(all_values) if all_values else None,
            "mean_log_score": sum(log_values) / len(log_values) if log_values else None,
            "mean_sharpness": sum(sharpness_values) / len(sharpness_values) if sharpness_values else None,
            "probability_movement_count": len(probability_movements),
            "mean_probability_movement_before_close": (
                sum(probability_movements) / len(probability_movements)
                if probability_movements
                else None
            ),
            "mean_abs_probability_movement_before_close": (
                sum(abs(value) for value in probability_movements) / len(probability_movements)
                if probability_movements
                else None
            ),
            "ensemble_component_contributions": sorted(
                component_rows,
                key=lambda row: (-row["count"], -(row["mean_contribution"] or 0.0), row["name"]),
            ),
            "question_type_breakdown": sorted(
                question_type_rows,
                key=lambda row: (-row["count"], row["question_type"]),
            ),
            "buckets": bucket_rows,
            "calibration_curve": curve_rows,
            "expected_calibration_error": expected_calibration_error,
            "max_calibration_error": max_calibration_error if ece_denominator else None,
            "calibration_curve_sample_count": ece_denominator,
            "mean_predicted": (
                sum(curve_predicted) / len(curve_predicted) if curve_predicted else None
            ),
            "observed_frequency": (
                sum(curve_observed) / len(curve_observed) if curve_observed else None
            ),
            "calibration_trend": self._calibration_trend(trend_points),
            "domain": domain,
            "forecast_origin": forecast_origin,
            "horizon": horizon,
            "calibration_eligible": calibration_eligible,
        }

    def _calibration_trend(
        self,
        points: list[dict[str, Any]],
        *,
        windows: tuple[int, ...] = (30, 90),
        now: str | None = None,
    ) -> dict[str, Any]:
        """Rolling mean-Brier + signed calibration error over recency windows.

        Each window reports ``{period, n, brier, sce}`` computed over the scored
        forecasts whose ``scored_at`` falls within the trailing window; ``sce`` is
        the signed calibration error over the window's binary forecasts (negative
        ⇒ under-confident, positive ⇒ over-confident), reusing the same estimator
        as the bias loop. ``direction`` compares the shortest to the longest
        window's mean Brier (lower Brier = better): ``improving`` when the recent
        window scores materially better, ``worsening`` when materially worse,
        ``stable`` within noise, ``insufficient`` when either window is too thin.
        Emits nothing misleading on thin data by construction."""
        from forecasting.calibration_bias import Observation, signed_calibration_error

        now_dt = timestamp_to_datetime(now or utc_now_iso())
        # Pre-parse each point's scored_at once; drop unparseable timestamps.
        parsed: list[tuple[Any, dict[str, Any]]] = []
        for point in points:
            try:
                dt = timestamp_to_datetime(point["scored_at"])
            except Exception:  # noqa: BLE001 — a garbage timestamp must not break the summary
                continue
            if dt is not None:
                parsed.append((dt, point))

        window_rows: list[dict[str, Any]] = []
        means: dict[int, float | None] = {}
        counts: dict[int, int] = {}
        for days in windows:
            cutoff = now_dt - timedelta(days=days)
            in_window = [p for dt, p in parsed if dt >= cutoff]
            briers = [p["brier"] for p in in_window if p.get("brier") is not None]
            observations = [
                Observation(p_yes=float(p["p_yes"]), outcome=float(p["outcome"]))
                for p in in_window
                if p.get("p_yes") is not None and p.get("outcome") is not None
            ]
            sce = signed_calibration_error(observations) if observations else None
            mean_brier = sum(briers) / len(briers) if briers else None
            means[days] = mean_brier
            counts[days] = len(briers)
            window_rows.append(
                {
                    "period": f"{days}d",
                    "n": len(briers),
                    "brier": mean_brier,
                    "sce": sce,
                }
            )

        # Direction: shortest vs longest window, both needing a floor sample.
        short, long = min(windows), max(windows)
        direction = "insufficient"
        if (
            short != long
            and counts.get(short, 0) >= 3
            and counts.get(long, 0) >= 3
            and means.get(short) is not None
            and means.get(long) is not None
        ):
            delta = means[short] - means[long]  # negative ⇒ recent Brier lower ⇒ better
            if delta < -0.01:
                direction = "improving"
            elif delta > 0.01:
                direction = "worsening"
            else:
                direction = "stable"
        return {"windows": window_rows, "direction": direction}

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
        """1.0 yes / 0.0 no / None ambiguous — the realized value of a scored
        operator estimate, from the stored resolved_outcome."""

        label = str(resolved_outcome).strip().lower()
        yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
        no_labels = {"no", "n", "false", "0", "not_occurred", "failed"}
        choices = [str(choice).lower() for choice in outcome_space.choices]
        if label in yes_labels or (choices and label == choices[0]):
            return 1.0
        if label in no_labels or (len(choices) > 1 and label == choices[1]):
            return 0.0
        return None

    def _operator_vs_system(
        self, estimates: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Pair each question that has a scored operator estimate with the
        system's own snapshot Brier on the SAME question, and report the shared
        sample + mean Brier on each side. The operator brier for a question is
        the mean over its estimates; the system brier is its best-available
        (calibration-eligible, else latest) non-invalidated snapshot score."""

        operator_by_question: dict[str, list[float]] = defaultdict(list)
        for estimate in estimates:
            if estimate["brier"] is not None:
                operator_by_question[estimate["question_id"]].append(float(estimate["brier"]))
        operator_shared: list[float] = []
        system_shared: list[float] = []
        with self._connect() as conn:
            for question_id, briers in operator_by_question.items():
                row = conn.execute(
                    """
                    SELECT brier_score FROM score_records
                    WHERE question_id = ?
                      AND brier_score IS NOT NULL
                      AND invalidated_by_correction_id IS NULL
                    ORDER BY calibration_eligible DESC, scored_at DESC
                    LIMIT 1
                    """,
                    (question_id,),
                ).fetchone()
                if row is None or row["brier_score"] is None:
                    continue
                operator_shared.append(sum(briers) / len(briers))
                system_shared.append(float(row["brier_score"]))
        return {
            "shared_n": len(operator_shared),
            "operator_brier": self._mean(operator_shared),
            "system_brier": self._mean(system_shared),
        }

    def operator_calibration_summary(
        self, window_days: int | None = None
    ) -> dict[str, Any]:
        """Operator calibration: n, mean Brier, a reliability curve over the
        operator's binary estimates, a recency trend, and a vs-system pairing.

        Only SCORED estimates with a numeric Brier feed the curve/trend/mean;
        ``window_days`` (when set) restricts to estimates scored within the
        trailing window."""

        estimates = [
            estimate
            for estimate in self.list_operator_estimates()
            if estimate["scored_at"] is not None and estimate["brier"] is not None
        ]
        if window_days:
            cutoff = timestamp_to_datetime(utc_now_iso()) - timedelta(days=window_days)
            windowed: list[dict[str, Any]] = []
            for estimate in estimates:
                try:
                    scored_dt = timestamp_to_datetime(estimate["scored_at"])
                except Exception:
                    continue
                if scored_dt is not None and scored_dt >= cutoff:
                    windowed.append(estimate)
            estimates = windowed

        briers = [float(estimate["brier"]) for estimate in estimates]
        curve_bins: dict[int, dict[str, list[float]]] = defaultdict(
            lambda: {"predicted": [], "observed": []}
        )
        trend_points: list[dict[str, Any]] = []
        for estimate in estimates:
            payload = estimate["probability_or_distribution"]
            trend_point: dict[str, Any] = {
                "scored_at": estimate["scored_at"],
                "brier": float(estimate["brier"]),
                "p_yes": None,
                "outcome": None,
            }
            if isinstance(payload, (int, float)) and estimate["resolved_outcome"] is not None:
                try:
                    outcome_space = self.get_question(estimate["question_id"]).outcome_space
                except LedgerNotFoundError:
                    # A corpus drill (question_id is a 'fb:<case-id>' ref with no
                    # forecast_questions row) — do NOT crash the whole summary
                    # joining it against the desk. Fall back to a binary outcome
                    # space so its yes/no resolution still maps into the
                    # reliability curve, exactly like a desk drill.
                    outcome_space = OutcomeSpace(type="binary", choices=["yes", "no"])
                observed = (
                    self._operator_binary_observed(estimate["resolved_outcome"], outcome_space)
                    if outcome_space is not None
                    else None
                )
                if observed is not None:
                    p_yes = float(payload)
                    decile = min(int(p_yes * 10), 9)
                    curve_bins[decile]["predicted"].append(p_yes)
                    curve_bins[decile]["observed"].append(observed)
                    trend_point["p_yes"] = p_yes
                    trend_point["outcome"] = observed
            trend_points.append(trend_point)

        curve_rows = []
        for index in range(10):
            data = curve_bins.get(index)
            predicted = data["predicted"] if data else []
            observed = data["observed"] if data else []
            count = len(observed)
            mean_predicted = sum(predicted) / count if count else None
            observed_frequency = sum(observed) / count if count else None
            gap = (
                abs(observed_frequency - mean_predicted)
                if count and mean_predicted is not None
                else None
            )
            curve_rows.append(
                {
                    "bucket": f"{index / 10:.1f}-{(index + 1) / 10:.1f}",
                    "count": count,
                    "mean_predicted": mean_predicted,
                    "observed_frequency": observed_frequency,
                    "calibration_gap": gap,
                    "sample_status": "empty"
                    if not count
                    else ("low_sample" if count < 5 else "ok"),
                }
            )

        return {
            "n": len(briers),
            "brier": self._mean(briers),
            "calibration_curve": curve_rows,
            "trend": self._calibration_trend(trend_points),
            "vs_system": self._operator_vs_system(estimates),
            "window_days": window_days,
        }

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
        question = self.get_question(question_id)
        if failure_class is not None:
            failure_class = failure_class.strip().lower() or None
            if failure_class and failure_class not in FAILURE_CLASSES:
                raise ValidationError(
                    f"failure_class must be one of {', '.join(sorted(FAILURE_CLASSES))}"
                )
        score = self.score_question(question_id)
        snapshot = self.get_snapshot(score.forecast_id)
        resolution = self.get_resolution(score.resolution_id)
        postmortem_id = f"pm_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO postmortems (
                    id, question_id, forecast_id, resolution_id, score_record_id,
                    forecast_origin, calibration_eligible, created_at, summary,
                    what_happened, what_was_expected, missed_evidence,
                    overweighted_evidence, base_rate_error, inside_view_error,
                    resolution_error, lesson, calibration_adjustment, failure_class
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    postmortem_id,
                    question_id,
                    snapshot.forecast_id,
                    resolution.id,
                    score.id,
                    score.forecast_origin,
                    1 if score.calibration_eligible else 0,
                    utc_now_iso(),
                    summary or f"Resolved outcome was {resolution.outcome!r}.",
                    what_happened or f"Resolution recorded outcome {resolution.outcome!r}.",
                    what_was_expected or f"Forecast probability was {snapshot.probability_or_distribution!r}.",
                    missed_evidence,
                    overweighted_evidence,
                    base_rate_error,
                    inside_view_error,
                    resolution_error,
                    lesson,
                    json_dumps(calibration_adjustment or {}),
                    failure_class,
                ),
            )
        postmortem = self.get_postmortem(postmortem_id)
        if lesson and score.calibration_eligible:
            self.create_calibration_lesson(
                scope_type="domain" if question.domain else "global",
                scope_ref=question.domain,
                lesson=lesson,
                confidence=0.5,
                recommended_adjustment=calibration_adjustment or {},
                source_postmortem_refs=[postmortem_id],
                source_score_record_refs=[score.id],
                status="tentative",
            )
        self.update_domain_error_profile(question)
        return postmortem

    def get_postmortem(self, postmortem_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM postmortems WHERE id = ?", (postmortem_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"postmortem not found: {postmortem_id}")
        data = dict(row)
        data["calibration_eligible"] = bool(data["calibration_eligible"])
        data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
        data.setdefault("failure_class", None)
        return data

    def list_postmortems(
        self,
        question_id: str | None = None,
        *,
        include_invalidated: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if not include_invalidated:
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM postmortems {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["calibration_eligible"] = bool(data["calibration_eligible"])
            data["calibration_adjustment"] = json_loads(data["calibration_adjustment"], {})
            data.setdefault("failure_class", None)
            result.append(data)
        return result

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
    ) -> dict[str, Any]:
        """Aggregate a panel of perspective estimates and persist the artifact.

        ``judge`` (a JudgeSynthesis dict: consensus / contradictions / blind_spots /
        judge_model / directional_confidence) is stored so a quorum's judge synthesis
        has a durable home and the quorum-judged gate can see it — instead of being
        dropped on the floor.

        ``final_probability`` / ``final_source`` (AIA P0.3): the ALREADY-resolved
        committed number and the branch that produced it (``'pool'`` or
        ``'judge_high'``). When supplied, the persisted ``aggregate_probability`` is
        this exact number — NOT a freshly re-pooled one — so the in-memory
        :class:`~forecasting.quorum.QuorumResult` and the durable panel_run can never
        diverge (the P0.1 divergence: this method used to silently re-pool the
        estimates WITH the per-question alpha while the QuorumResult showed the bare
        pool). The terminal Platt calibration has therefore already been applied
        upstream exactly once; we must NOT re-apply it here. When ``final_probability``
        is ``None`` (the perspective-panel path), we fall back to pooling-with-alpha as
        before so non-quorum callers are unchanged.

        Returns the panel-run record dict (including aggregate_probability,
        spread_summary, trimmed flags, and per-estimate ids). The caller
        typically passes the resulting ``aggregate_probability`` into
        :meth:`create_snapshot` and the panel run id into the snapshot's
        ``ensemble_components`` or ``metadata``.
        """

        _enforce_write_gate("record_panel_run")

        from forecasting.hooks.thresholds import resolve_alpha_extremize
        from forecasting.panel import aggregate_panel_estimates  # local import to avoid cycle

        question = self.get_question(question_id)
        if snapshot_id is not None:
            self.get_snapshot(snapshot_id)
        # Terminal Platt calibration (AIA P0.1): resolve the per-question slope
        # from the question's forecast-hooks config (default 1.0 = byte-identical
        # no-op for an un-configured question).
        alpha_extremize = resolve_alpha_extremize(
            question.metadata if isinstance(question.metadata, dict) else None
        )
        # Always aggregate WITH the real per-question slope so the persisted
        # calibration markers (applied_alpha, pre_extremize, terminal_calibration_
        # applied) and pool_probability are accurate on the quorum path too. Platt
        # is still applied EXACTLY ONCE to the committed number: when the caller
        # supplies an already-resolved value (the quorum path — run_quorum has
        # already applied alpha + the P0.3 override), we overwrite the committed
        # scalar with it below and never re-derive it from the aggregation, so the
        # aggregation's calibrated scalar is used only for the audit markers / the
        # pool the override beat — never double-Platt'd.
        resolved = final_probability is not None
        aggregation = aggregate_panel_estimates(
            estimates,
            method=aggregation_method,
            trim=trim,
            alpha_extremize=alpha_extremize,
        )
        committed_probability = (
            float(final_probability)
            if resolved
            else float(aggregation.aggregate_probability)
        )
        # Constrain to the known source domain (defensive against a future caller).
        committed_source = final_source if final_source in {"pool", "judge_high"} else "pool"
        # AIA P1.1 — agentic-supervisor fresh-search loop. Default to the no-loop
        # state so the perspective-panel path and any pre-P1.1 quorum caller
        # persist unchanged (0 rounds, no fresh evidence).
        research_rounds = max(0, int(research_rounds or 0))
        supervisor_evidence = list(supervisor_evidence or [])
        # Delphi v1 — additive audit fields. Default to the no-Delphi state so the
        # delphi_rounds==0 path (and every pre-Delphi caller) persists unchanged.
        delphi_rounds = max(0, int(delphi_rounds or 0))
        delphi_audit = dict(delphi_audit or {})
        now = utc_now_iso()
        run_id = f"pr_{uuid.uuid4().hex[:12]}"
        requested = perspectives if perspectives is not None else [
            row["perspective"] for row in aggregation.estimates
        ]
        # Fold the P0.3 override outcome into the persisted spread so it is
        # observable alongside the P0.1 calibration markers without a second
        # schema migration. ``final_source`` is also a first-class column.
        spread = dict(aggregation.spread)
        spread["final_source"] = committed_source
        if resolved:
            # The committed number is the resolved one; surface the CALIBRATED pool
            # (the value a high-confidence judge actually overrode) for audit.
            spread["pool_probability"] = round(
                float(aggregation.aggregate_probability), 6
            )
        estimate_records: list[dict[str, Any]] = []
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO panel_runs (
                    id, question_id, created_at, snapshot_id,
                    aggregation_method, trim, aggregate_probability,
                    perspectives, spread_summary, notes, triggered_by, judge,
                    final_source, research_rounds, supervisor_evidence,
                    delphi_rounds, delphi_audit
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    question_id,
                    now,
                    snapshot_id,
                    aggregation.method,
                    aggregation.trim,
                    committed_probability,
                    json_dumps(list(requested)),
                    json_dumps(spread),
                    json_dumps(aggregation.notes),
                    triggered_by,
                    json_dumps(judge) if judge is not None else None,
                    committed_source,
                    research_rounds,
                    json_dumps(supervisor_evidence),
                    delphi_rounds,
                    json_dumps(delphi_audit),
                ),
            )
            for row in aggregation.estimates:
                estimate_id = f"pe_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO panel_estimates (
                        id, panel_run_id, question_id, created_at, perspective,
                        probability, weight, trimmed, confidence_low, confidence_high,
                        rationale, reasons_up, reasons_down, change_my_mind, crux,
                        agent_model, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        estimate_id,
                        run_id,
                        question_id,
                        now,
                        row["perspective"],
                        float(row["probability"]),
                        float(row["weight"]),
                        1 if row.get("trimmed") else 0,
                        row.get("confidence_low"),
                        row.get("confidence_high"),
                        row.get("rationale") or "",
                        json_dumps(row.get("reasons_up") or []),
                        json_dumps(row.get("reasons_down") or []),
                        json_dumps(row.get("change_my_mind") or []),
                        row.get("crux"),
                        row.get("agent_model"),
                        json_dumps(row.get("metadata") or {}),
                    ),
                )
                estimate_records.append({"id": estimate_id, **row})
        return self.get_panel_run(run_id)

    def get_panel_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM panel_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise LedgerNotFoundError(f"panel run not found: {run_id}")
            estimates = conn.execute(
                """
                SELECT * FROM panel_estimates
                WHERE panel_run_id = ?
                ORDER BY perspective ASC
                """,
                (run_id,),
            ).fetchall()
        return self._panel_run_dict(row, estimates)

    def list_panel_runs(
        self,
        question_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM panel_runs {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                estimates = conn.execute(
                    """
                    SELECT * FROM panel_estimates
                    WHERE panel_run_id = ?
                    ORDER BY perspective ASC
                    """,
                    (row["id"],),
                ).fetchall()
                results.append(self._panel_run_dict(row, estimates))
        return results

    def attach_panel_to_snapshot(self, panel_run_id: str, snapshot_id: str) -> dict[str, Any]:
        self.get_panel_run(panel_run_id)
        self.get_snapshot(snapshot_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE panel_runs SET snapshot_id = ? WHERE id = ?",
                (snapshot_id, panel_run_id),
            )
        return self.get_panel_run(panel_run_id)

    def _panel_run_dict(
        self,
        row: sqlite3.Row,
        estimates_rows: list[sqlite3.Row],
    ) -> dict[str, Any]:
        data = dict(row)
        data["perspectives"] = json_loads(data["perspectives"], [])
        data["spread_summary"] = json_loads(data["spread_summary"], {})
        data["notes"] = json_loads(data["notes"], [])
        if "supervisor_evidence" in data:
            data["supervisor_evidence"] = json_loads(data["supervisor_evidence"], [])
        if "delphi_audit" in data:
            data["delphi_audit"] = json_loads(data.get("delphi_audit"), {})
        data["estimates"] = [self._panel_estimate_dict(e) for e in estimates_rows]
        return data

    def _panel_estimate_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["trimmed"] = bool(data["trimmed"])
        data["reasons_up"] = json_loads(data["reasons_up"], [])
        data["reasons_down"] = json_loads(data["reasons_down"], [])
        data["change_my_mind"] = json_loads(data["change_my_mind"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    # ── Component track record (measured "weight by track record") ──────
    def component_track_record(
        self,
        *,
        forecast_origin: str | None = "live",
        min_count: int | None = None,
        shrink_n0: float | None = None,
        edge_scale: float | None = None,
    ) -> list[dict[str, Any]]:
        """Measure each ensemble component's and panel perspective's Brier edge
        over the committed aggregate across resolved binary questions, and map
        it to an ADVISORY recommended weight (see :mod:`forecasting.track_record`
        for the shrinkage/clipping gates).

        Pairing rule — one observation per (question, component): the latest
        matching-origin snapshot that carries ``ensemble_components`` supplies
        the ensemble pairs (component probability vs that snapshot's committed
        probability); the latest panel run supplies the perspective pairs
        (estimate probability vs that run's aggregate). Non-binary questions
        and non-numeric payloads are skipped — the math is only proper for
        binary Brier.
        """
        from forecasting.ensembles import _component_rows
        from forecasting.track_record import (
            DEFAULT_EDGE_SCALE,
            DEFAULT_MIN_COUNT,
            DEFAULT_SHRINK_N0,
            ComponentObservation,
            summarize_components,
        )

        observations: list[ComponentObservation] = []
        for question in self.list_questions(status="resolved"):
            if question.outcome_space.type != "binary":
                continue
            resolution = self.get_latest_resolution(question.id, confirmed_only=True)
            if resolution is None:
                continue

            def _brier(probability: Any) -> float | None:
                try:
                    payload = self._score_forecast_payload(
                        float(probability), resolution.outcome, question.outcome_space
                    )
                except (TypeError, ValueError, ValidationError):
                    return None
                value = payload.get("brier_score")
                return float(value) if isinstance(value, (int, float)) else None

            # Ensemble components: latest matching-origin snapshot that has them.
            snapshots = [
                snap
                for snap in self.list_snapshots(question.id)
                if forecast_origin is None or snap.forecast_origin == forecast_origin
            ]
            for snapshot in reversed(snapshots):
                rows = _component_rows(
                    snapshot.ensemble_components
                    if isinstance(snapshot.ensemble_components, dict)
                    else {}
                )
                if not rows:
                    continue
                aggregate_brier = _brier(snapshot.probability_or_distribution)
                if aggregate_brier is None:
                    continue
                for row in rows:
                    name = str(row.get("name") or "").strip()
                    component_brier = _brier(row.get("probability"))
                    if not name or component_brier is None:
                        continue
                    observations.append(
                        ComponentObservation(
                            name=name,
                            kind="ensemble",
                            question_id=question.id,
                            component_brier=component_brier,
                            aggregate_brier=aggregate_brier,
                        )
                    )
                break  # one snapshot per question — newest with components

            # Panel perspectives: latest run, paired against its own aggregate.
            runs = self.list_panel_runs(question.id, limit=1)
            if runs:
                run = runs[0]
                aggregate_brier = _brier(run.get("aggregate_probability"))
                if aggregate_brier is not None:
                    for estimate in run.get("estimates", []):
                        perspective = str(estimate.get("perspective") or "").strip()
                        component_brier = _brier(estimate.get("probability"))
                        if not perspective or component_brier is None:
                            continue
                        observations.append(
                            ComponentObservation(
                                name=perspective,
                                kind="panel",
                                question_id=question.id,
                                component_brier=component_brier,
                                aggregate_brier=aggregate_brier,
                            )
                        )

        records = summarize_components(
            observations,
            min_count=min_count if min_count is not None else DEFAULT_MIN_COUNT,
            shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
            edge_scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
        )
        return [record.to_dict() for record in records]

    def recommended_component_weights(
        self,
        *,
        kind: str = "panel",
        forecast_origin: str | None = "live",
        min_count: int | None = None,
    ) -> dict[str, float]:
        """``{name: weight}`` for measured components only — advisory, never
        silently applied; callers opt in (e.g. ``forecast panel record
        --track-record-weights``)."""
        records = self.component_track_record(
            forecast_origin=forecast_origin, min_count=min_count
        )
        return {
            row["name"]: float(row["recommended_weight"])
            for row in records
            if row["kind"] == kind and row["status"] == "measured"
        }

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
        """Measure each PANELIST MODEL's Brier edge over the cross-model panel
        average across resolved binary questions, and map it to a shrunk,
        clipped weight (reuses :mod:`forecasting.track_record` — the same math
        as :meth:`component_track_record`, but keyed on the panelist ``model``
        and scored against the OUTCOME with the per-question cross-model mean as
        the reference).

        One observation per (question, model): the latest panel run supplies
        each panelist's probability; its Brier vs the confirmed outcome is paired
        against the mean panelist Brier on that same question (positive edge ⇒
        the model beat the pack). Non-binary questions and non-numeric payloads
        are skipped — binary Brier only. A model that repeats within one run (the
        ``self`` preset) is averaged to a single per-question observation so it
        cannot double-count.

        There is deliberately no ``forecast_origin`` filter: quorum ``panel_runs``
        are not origin-tagged per estimate (a run's ``snapshot_id`` is often unset
        at record time), so an origin argument could not honestly restrict pairing
        and would silently mix backtest+live panelist performance. Strata-aware
        weighting is a schema change (tag panel runs with an origin) — not a
        parameter — and is left for when that need is real.
        """
        from forecasting.track_record import (
            DEFAULT_EDGE_SCALE,
            DEFAULT_SHRINK_N0,
            ComponentObservation,
            summarize_components,
        )

        observations: list[ComponentObservation] = []
        for question in self.list_questions(status="resolved"):
            if question.outcome_space.type != "binary":
                continue
            resolution = self.get_latest_resolution(question.id, confirmed_only=True)
            if resolution is None:
                continue

            def _brier(probability: Any) -> float | None:
                try:
                    payload = self._score_forecast_payload(
                        float(probability), resolution.outcome, question.outcome_space
                    )
                except (TypeError, ValueError, ValidationError):
                    return None
                value = payload.get("brier_score")
                return float(value) if isinstance(value, (int, float)) else None

            runs = self.list_panel_runs(question.id, limit=1)
            if not runs:
                continue
            run = runs[0]
            # Group each panelist model's Brier(s) on THIS question, then average
            # within model so a repeated model (self preset) is one observation.
            per_model: dict[str, list[float]] = {}
            for estimate in run.get("estimates", []):
                model = str(estimate.get("agent_model") or estimate.get("perspective") or "").strip()
                brier = _brier(estimate.get("probability"))
                if not model or brier is None:
                    continue
                per_model.setdefault(model, []).append(brier)
            model_briers = {
                model: sum(values) / len(values)
                for model, values in per_model.items()
                if values
            }
            if not model_briers:
                continue
            # Reference: the cross-model mean Brier on this question (difficulty-
            # normalised — a model is rewarded/penalised only relative to the pack).
            reference_brier = sum(model_briers.values()) / len(model_briers)
            for model, brier in model_briers.items():
                observations.append(
                    ComponentObservation(
                        name=model,
                        kind="model",
                        question_id=question.id,
                        component_brier=brier,
                        aggregate_brier=reference_brier,
                    )
                )

        records = summarize_components(
            observations,
            min_count=min_count if min_count is not None else self.MODEL_WEIGHT_MIN_SAMPLE,
            shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
            edge_scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
        )
        return [record.to_dict() for record in records]

    def recommended_model_weights(
        self,
        *,
        min_sample: int | None = None,
    ) -> dict[str, float]:
        """``{model: weight}`` for MEASURED panelist models only (those clearing
        the resolved-sample gate). A model below the gate is absent — the quorum
        dispatcher defaults it to weight 1.0, so a cold-start panel is equal-
        weighted by construction and no model can dominate early. Shrinkage
        toward 1.0 lives in :func:`forecasting.track_record.edge_to_weight`."""
        records = self.model_track_record(
            min_count=min_sample if min_sample is not None else self.MODEL_WEIGHT_MIN_SAMPLE,
        )
        return {
            row["name"]: float(row["recommended_weight"])
            for row in records
            if row["status"] == "measured"
        }

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
        """Compute a model's SKILL on-read from scored ``model_runs`` (R4).

        Mirrors :meth:`model_track_record`: iterate resolved questions, read each
        matching model_run's persisted score, and reuse
        :mod:`forecasting.track_record` (shrink toward 1.0, clip, minimum resolved
        sample before the weight moves — the S7.5 semantics) to map the BINARY
        Brier edge over the uninformative baseline into a ``weight_multiplier``.

        ``model_type`` / ``market_model_id`` narrow the population (both None =
        every scored run, one global skill record). Cold start (fewer than
        ``min_count`` binary-scored runs) returns ``weight_multiplier`` exactly
        1.0 and ``status='insufficient_track_record'`` — harmless by construction.
        Numeric runs contribute ``coverage`` (interval-hit rate) and ``mae`` but do
        not move the binary weight multiplier (the re-pool they weight is
        binary-only)."""
        from forecasting.track_record import (
            DEFAULT_EDGE_SCALE,
            DEFAULT_SHRINK_N0,
            edge_to_weight,
            shrink_edge,
        )

        gate = min_count if min_count is not None else self.MODEL_WEIGHT_MIN_SAMPLE
        binary_briers: list[float] = []
        interval_hits: list[int] = []
        abs_errors: list[float] = []
        numeric_run_count = 0
        question_ids: set[str] = set()
        for question in self.list_questions(status="resolved"):
            resolution = self.get_latest_resolution(question.id, confirmed_only=True)
            if resolution is None:
                continue
            q_type = question.outcome_space.type
            for run in self.list_model_runs(question.id):
                if run.get("scored_at") is None:
                    continue
                if model_type is not None and run.get("model_type") != model_type:
                    continue
                if market_model_id is not None and run.get("market_model_id") != market_model_id:
                    continue
                score = run.get("outcome_score")
                hit = run.get("interval_hit")
                # Classify by the QUESTION's type (authoritative), not the NULL-ness
                # of interval_hit — a numeric run may legitimately carry no interval.
                if q_type == "binary":
                    if isinstance(score, (int, float)):
                        binary_briers.append(float(score))
                        question_ids.add(question.id)
                elif q_type == "numeric":
                    if hit is not None:
                        interval_hits.append(1 if hit else 0)
                    if isinstance(score, (int, float)):
                        abs_errors.append(float(score))
                    if hit is not None or isinstance(score, (int, float)):
                        numeric_run_count += 1
                        question_ids.add(question.id)

        n_binary = len(binary_briers)
        n_numeric = numeric_run_count
        brier_mean = (sum(binary_briers) / n_binary) if n_binary else None
        coverage = (sum(interval_hits) / len(interval_hits)) if interval_hits else None
        mae = (sum(abs_errors) / len(abs_errors)) if abs_errors else None

        # Weight multiplier: shrink+clip the binary edge over the baseline, gated
        # on the resolved-binary sample (identity below the gate).
        edge_shrunk = 0.0
        weight_multiplier = 1.0
        status = "insufficient_track_record"
        if brier_mean is not None and n_binary >= gate:
            edge_mean = self._MODEL_SKILL_BASELINE_BRIER - brier_mean
            edge_shrunk = shrink_edge(
                edge_mean, n_binary,
                shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
            )
            weight_multiplier = edge_to_weight(
                edge_shrunk,
                scale=edge_scale if edge_scale is not None else DEFAULT_EDGE_SCALE,
            )
            status = "measured"
        elif brier_mean is not None:
            # Report direction-of-travel even below the gate (weight stays 1.0).
            edge_mean = self._MODEL_SKILL_BASELINE_BRIER - brier_mean
            edge_shrunk = shrink_edge(
                edge_mean, n_binary,
                shrink_n0=shrink_n0 if shrink_n0 is not None else DEFAULT_SHRINK_N0,
            )

        return {
            "model_type": model_type,
            "market_model_id": market_model_id,
            "n_scored": n_binary + n_numeric,
            "n_binary": n_binary,
            "n_numeric": n_numeric,
            "brier": brier_mean,
            "coverage": coverage,
            "mae": mae,
            "edge_shrunk": edge_shrunk,
            "weight_multiplier": weight_multiplier,
            "status": status,
            "min_sample": gate,
            "question_ids": sorted(question_ids),
        }

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
        """Append a time-indexed analyst write-up for a question.

        Append-only: each call is one entry in the question's prose time series.
        ``forecast_id`` chains a brief to the snapshot it annotates;
        ``resolution_id`` chains a retrospective to the resolution. Both use
        ``ON DELETE SET NULL`` so the historical record survives a later purge.
        """

        self.get_question(question_id)
        if kind not in ANALYST_NOTE_KINDS:
            raise ValidationError(
                f"analyst note kind must be one of {', '.join(sorted(ANALYST_NOTE_KINDS))}"
            )
        if not body.strip():
            raise ValidationError("analyst note body is required")
        if stance is not None and stance not in ANALYST_NOTE_STANCES:
            raise ValidationError(
                f"analyst note stance must be one of {', '.join(sorted(ANALYST_NOTE_STANCES))}"
            )
        if verdict is not None and verdict not in ANALYST_NOTE_VERDICTS:
            raise ValidationError(
                f"analyst note verdict must be one of {', '.join(sorted(ANALYST_NOTE_VERDICTS))}"
            )
        if forecast_id is not None:
            self.get_snapshot(forecast_id)
        now = utc_now_iso()
        as_of_ts = parse_timestamp(as_of, field_name="as_of") or now
        note_id = f"an_{uuid.uuid4().hex[:12]}"
        note_metadata = dict(metadata or {})
        if probability_at_write is not None:
            note_metadata["probability_at_write"] = probability_at_write
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO analyst_notes (
                    id, question_id, forecast_id, resolution_id, kind, created_at,
                    as_of, headline, body, how_it_feels, how_it_thinks, looking_for,
                    be_aware, stance, verdict, confidence_at_write, agent_model,
                    prompt_version, forecasting_protocol_version, generator, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note_id,
                    question_id,
                    forecast_id,
                    resolution_id,
                    kind,
                    now,
                    as_of_ts,
                    headline,
                    body,
                    how_it_feels,
                    how_it_thinks,
                    looking_for,
                    be_aware,
                    stance,
                    verdict,
                    confidence_at_write,
                    agent_model,
                    prompt_version,
                    forecasting_protocol_version,
                    generator,
                    json_dumps(note_metadata),
                ),
            )
        return self.get_analyst_note(note_id)

    def get_analyst_note(self, note_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM analyst_notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"analyst note not found: {note_id}")
        return self._analyst_note_to_dict(row)

    def list_analyst_notes(
        self,
        question_id: str,
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a question's analyst notes oldest-first (a parallel time series
        to ``forecast_history``)."""

        sql = "SELECT * FROM analyst_notes WHERE question_id = ?"
        params: list[Any] = [question_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        # rowid is the insertion-order tiebreaker: utc_now_iso() can tie when
        # several notes are written in the same instant (e.g. resolve writes a
        # brief and a retrospective back to back).
        sql += " ORDER BY created_at ASC, rowid ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._analyst_note_to_dict(row) for row in rows]

    def latest_analyst_note(
        self,
        question_id: str,
        *,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the most recent analyst note (powers the desk quick-read)."""

        sql = "SELECT * FROM analyst_notes WHERE question_id = ?"
        params: list[Any] = [question_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY created_at DESC, rowid DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._analyst_note_to_dict(row) if row else None

    def _analyst_note_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json_loads(data.get("metadata"), {})
        return data

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
        """question_id -> snapshots oldest-first (mirrors list_snapshots ordering,
        so current=snapshots[-1] / previous=snapshots[-2] still hold)."""
        out: dict[str, list[ForecastSnapshot]] = {}
        for chunk in self._chunk_ids(question_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM forecast_snapshots WHERE question_id IN ({placeholders}) "
                    "ORDER BY question_id ASC, created_at ASC",
                    chunk,
                ).fetchall()
            for row in rows:
                out.setdefault(row["question_id"], []).append(self._row_to_snapshot(row))
        return out

    def evidence_by_question(self, question_ids: list[str]) -> dict[str, list[EvidenceItem]]:
        return _evidence.evidence_by_question(self, question_ids=question_ids)

    def latest_panel_run_by_question(self, question_ids: list[str]) -> dict[str, dict[str, Any]]:
        """question_id -> its most-recent panel run dict (mirrors
        list_panel_runs(qid, limit=1)[0]); absent when a question has no panel."""
        out: dict[str, dict[str, Any]] = {}
        for chunk in self._chunk_ids(question_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM panel_runs WHERE question_id IN ({placeholders}) "
                    "ORDER BY question_id ASC, created_at DESC",
                    chunk,
                ).fetchall()
                # Keep only the latest run per question (first row per id, since
                # created_at DESC), then fetch each run's estimates.
                latest_rows: list[sqlite3.Row] = []
                seen: set[str] = set()
                for row in rows:
                    qid = row["question_id"]
                    if qid not in seen:
                        seen.add(qid)
                        latest_rows.append(row)
                for row in latest_rows:
                    estimates = conn.execute(
                        "SELECT * FROM panel_estimates WHERE panel_run_id = ? "
                        "ORDER BY perspective ASC",
                        (row["id"],),
                    ).fetchall()
                    out[row["question_id"]] = self._panel_run_dict(row, estimates)
        return out

    def latest_resolution_by_question(self, question_ids: list[str]) -> dict[str, Resolution]:
        """question_id -> latest resolution by resolved_at (mirrors
        get_latest_resolution with confirmed_only=False); absent when none."""
        out: dict[str, Resolution] = {}
        for chunk in self._chunk_ids(question_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM resolutions WHERE question_id IN ({placeholders}) "
                    "ORDER BY question_id ASC, resolved_at DESC",
                    chunk,
                ).fetchall()
            for row in rows:
                qid = row["question_id"]
                if qid not in out:  # first row per question = latest resolved_at
                    out[qid] = self._row_to_resolution(row)
        return out

    def analyst_notes_by_question(self, question_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """question_id -> analyst notes oldest-first (mirrors list_analyst_notes,
        same created_at ASC, rowid ASC tiebreaker)."""
        out: dict[str, list[dict[str, Any]]] = {}
        for chunk in self._chunk_ids(question_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT * FROM analyst_notes WHERE question_id IN ({placeholders}) "
                    "ORDER BY question_id ASC, created_at ASC, rowid ASC",
                    chunk,
                ).fetchall()
            for row in rows:
                out.setdefault(row["question_id"], []).append(self._analyst_note_to_dict(row))
        return out

    def active_watched_source_counts(self, question_ids: list[str]) -> dict[str, int]:
        return _watches.active_watched_source_counts(self, question_ids=question_ids)

    def active_reference_class_counts(self, question_ids: list[str]) -> dict[str, int]:
        """question_id -> count of its ACTIVE reference classes.

        ONE batched ``GROUP BY`` per id-chunk — the batched equivalent of
        ``len([rc for rc in list_reference_classes(qid) if rc['status']=='active'])``.
        Ids with no active class are absent (caller defaults to 0)."""
        out: dict[str, int] = {}
        for chunk in self._chunk_ids(question_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"SELECT question_id, COUNT(*) AS n FROM reference_classes "
                    f"WHERE status = 'active' AND question_id IN ({placeholders}) "
                    f"GROUP BY question_id",
                    chunk,
                ).fetchall()
            for row in rows:
                out[row["question_id"]] = int(row["n"])
        return out

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
        if not (title or "").strip():
            raise ValidationError("market model title is required")
        if not (question or "").strip():
            raise ValidationError("market model question is required")
        now = utc_now_iso()
        model_id = f"mm_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_models (
                    id, created_at, updated_at, title, question, depth, spec,
                    status, current_version, tags, agent_model, prompt_version, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?)
                """,
                (
                    model_id, now, now, title.strip(), question.strip(), depth,
                    json_dumps(dict(spec or {})), json_dumps(list(tags or [])),
                    agent_model, prompt_version, json_dumps(dict(metadata or {})),
                ),
            )
        return self.get_market_model(model_id)

    def update_market_model_spec(self, model_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE market_models SET spec = ?, updated_at = ? WHERE id = ?",
                (json_dumps(dict(spec or {})), utc_now_iso(), model_id),
            )
            if cur.rowcount == 0:
                raise LedgerNotFoundError(f"market model not found: {model_id}")
        return self.get_market_model(model_id)

    def get_market_model(self, model_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM market_models WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"market model not found: {model_id}")
        return self._market_model_to_dict(row)

    def list_market_models(self, *, status: str | None = "active", limit: int | None = None) -> list[dict[str, Any]]:
        # Join the latest presentation's build status (complete/partial/failed) so
        # the list can show a failure/ready icon without an N+1 per-row fetch.
        sql = (
            "SELECT mm.*, ("
            " SELECT p.status FROM market_model_presentations p"
            " WHERE p.model_id = mm.id ORDER BY p.version DESC LIMIT 1"
            ") AS last_status FROM market_models mm"
        )
        params: list[Any] = []
        if status is not None:
            sql += " WHERE mm.status = ?"
            params.append(status)
        sql += " ORDER BY updated_at DESC, rowid DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._market_model_to_dict(r) for r in rows]

    def delete_market_model(self, model_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM market_models WHERE id = ?", (model_id,))
        return cur.rowcount > 0

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
        """Append a new presentation version and advance the model's current_version."""
        self.get_market_model(model_id)
        now = utc_now_iso()
        pres_id = f"mmp_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(version), 0) AS v FROM market_model_presentations WHERE model_id = ?",
                (model_id,),
            ).fetchone()
            version = int(row["v"]) + 1
            pres = dict(presentation or {})
            pres["version"] = version
            pres["model_id"] = model_id
            conn.execute(
                """
                INSERT INTO market_model_presentations (
                    id, model_id, version, created_at, as_of_analysis, as_of_data,
                    schema_version, status, summary, presentation, refine_instruction,
                    diagnostics, agent_model, prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pres_id, model_id, version, now, as_of_analysis or now, as_of_data or now,
                    str(pres.get("schema_version") or ""), status, summary,
                    json_dumps(pres), refine_instruction, json_dumps(dict(diagnostics or {})),
                    agent_model, prompt_version,
                ),
            )
            conn.execute(
                "UPDATE market_models SET current_version = ?, updated_at = ? WHERE id = ?",
                (version, now, model_id),
            )
        return self.get_market_presentation(model_id, version=version)

    def get_market_presentation(self, model_id: str, *, version: int | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            if version is None:
                row = conn.execute(
                    "SELECT * FROM market_model_presentations WHERE model_id = ? ORDER BY version DESC LIMIT 1",
                    (model_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM market_model_presentations WHERE model_id = ? AND version = ?",
                    (model_id, int(version)),
                ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"no presentation for market model {model_id} (version={version})")
        return self._market_presentation_to_dict(row)

    def list_market_presentations(self, model_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_model_presentations WHERE model_id = ? ORDER BY version ASC",
                (model_id,),
            ).fetchall()
        return [self._market_presentation_to_dict(r) for r in rows]

    def add_market_message(
        self, *, model_id: str, role: str, content: str, version_ref: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_market_model(model_id)
        now = utc_now_iso()
        msg_id = f"mmsg_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO market_model_messages (id, model_id, role, created_at, content, version_ref, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (msg_id, model_id, role, now, content, version_ref, json_dumps(dict(metadata or {}))),
            )
        with self._connect() as conn:
            r = conn.execute("SELECT * FROM market_model_messages WHERE id = ?", (msg_id,)).fetchone()
        return self._market_message_to_dict(r)

    def list_market_messages(self, model_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM market_model_messages WHERE model_id = ? ORDER BY created_at ASC, rowid ASC"
        params: list[Any] = [model_id]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._market_message_to_dict(r) for r in rows]

    def add_market_data_series(
        self, *, model_id: str, name: str, points: list[Any], source_type: str | None = None,
        source: str | None = None, unit: str | None = None, as_of: str | None = None,
        evidence_refs: list[str] | None = None, metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.get_market_model(model_id)
        now = utc_now_iso()
        series_id = f"mds_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO market_data_series (
                    id, model_id, created_at, name, source_type, source, unit, points,
                    as_of, evidence_refs, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    series_id, model_id, now, name, source_type, source, unit,
                    json_dumps(list(points or [])), as_of or now,
                    json_dumps(list(evidence_refs or [])), json_dumps(dict(metadata or {})),
                ),
            )
        with self._connect() as conn:
            r = conn.execute("SELECT * FROM market_data_series WHERE id = ?", (series_id,)).fetchone()
        return self._market_series_to_dict(r)

    def list_market_data_series(self, model_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM market_data_series WHERE model_id = ? ORDER BY created_at ASC, rowid ASC",
                (model_id,),
            ).fetchall()
        return [self._market_series_to_dict(r) for r in rows]

    def replace_market_data_series(self, model_id: str, series: list[dict[str, Any]]) -> None:
        """Replace all stored series for a model (used by re-pull on open)."""
        self.get_market_model(model_id)
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute("DELETE FROM market_data_series WHERE model_id = ?", (model_id,))
            for s in series or []:
                conn.execute(
                    """INSERT INTO market_data_series (
                        id, model_id, created_at, name, source_type, source, unit, points,
                        as_of, evidence_refs, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"mds_{uuid.uuid4().hex[:12]}", model_id, now, str(s.get("name") or ""),
                        s.get("source_type"), s.get("source"), s.get("unit"),
                        json_dumps(list(s.get("points") or [])), s.get("as_of") or now,
                        json_dumps(list(s.get("evidence_refs") or [])), json_dumps(dict(s.get("metadata") or {})),
                    ),
                )

    def export_market_model(self, model_id: str, *, fmt: str = "json") -> dict[str, Any]:
        """Full packet: model + current presentation + all versions + series + thread."""
        model = self.get_market_model(model_id)
        try:
            current = self.get_market_presentation(model_id)
        except LedgerNotFoundError:
            current = None
        return {
            "product": "market-models",
            "generated_at": utc_now_iso(),
            "model": model,
            "presentation": current,
            "versions": self.list_market_presentations(model_id),
            "series": self.list_market_data_series(model_id),
            "messages": self.list_market_messages(model_id),
        }

    def _market_model_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["spec"] = json_loads(d.get("spec"), {})
        d["tags"] = json_loads(d.get("tags"), [])
        d["metadata"] = json_loads(d.get("metadata"), {})
        return d

    def _market_presentation_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["presentation"] = json_loads(d.get("presentation"), {})
        d["diagnostics"] = json_loads(d.get("diagnostics"), {})
        return d

    def _market_message_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["metadata"] = json_loads(d.get("metadata"), {})
        return d

    def _market_series_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["points"] = json_loads(d.get("points"), [])
        d["evidence_refs"] = json_loads(d.get("evidence_refs"), [])
        d["metadata"] = json_loads(d.get("metadata"), {})
        return d

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
        if scope_type not in {"domain", "topic", "domain_topic", "horizon", "question_type", "model_component", "global"}:
            raise ValidationError("invalid calibration lesson scope_type")
        if scope_type == "domain_topic" and ":" not in (scope_ref or ""):
            # Stored + matched colon-joined ("politics:nyc-primaries"), the form both
            # active_lessons_for_question and lesson_scope_to_applies_to expect.
            raise ValidationError("domain_topic calibration lessons require a 'domain:topic' scope_ref")
        if status not in CALIBRATION_LESSON_STATUSES:
            raise ValidationError(
                f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
            )
        if not lesson.strip():
            raise ValidationError("calibration lesson text is required")
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("calibration lesson confidence must be between 0 and 1")
        # Lazy-operator hook: a lesson with a recognized enforcement pattern AUTO-
        # compiles to a hook rule at creation (WARN — observe-then-flip), so a learning
        # becomes strict, formal enforcement without anyone hand-authoring a RuleSpec.
        # An explicit `rule` always wins; no recognized pattern leaves it advisory.
        if isinstance(recommended_adjustment, dict) and "rule" not in recommended_adjustment:
            from forecasting.lesson_templates import build_lesson_rule

            _auto_rule = build_lesson_rule({"recommended_adjustment": recommended_adjustment}, severity="warn")
            if _auto_rule is not None:
                recommended_adjustment = {**recommended_adjustment, "rule": _auto_rule}
        # Authoring gate: a lesson that carries an enforceable `rule` must compile.
        # Refuse a broken rule at write time (so it can't silently fail to bite at
        # commit) — the rule's check predicate is validated against the signal DSL.
        _rule = (recommended_adjustment or {}).get("rule") if isinstance(recommended_adjustment, dict) else None
        if isinstance(_rule, dict):
            from forecasting.hooks.dsl import RuleSpec, validate_rule

            _spec = RuleSpec.from_dict({**_rule, "id": "lesson:_validate", "applies_to": {}})
            _rule_errs = [issue for issue in validate_rule(_spec) if issue.severity == "error"]
            if _rule_errs:
                raise ValidationError(f"calibration lesson rule is invalid: {_rule_errs[0].message}")
        now = utc_now_iso()
        lesson_id = f"cl_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO calibration_lessons (
                    id, scope_type, scope_ref, created_at, updated_at, status,
                    confidence, lesson, recommended_adjustment,
                    source_postmortem_refs, source_score_record_refs,
                    supersedes_lesson_id, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    scope_type,
                    scope_ref,
                    now,
                    now,
                    status,
                    confidence,
                    lesson.strip(),
                    json_dumps(recommended_adjustment or {}),
                    json_dumps(source_postmortem_refs or []),
                    json_dumps(source_score_record_refs or []),
                    supersedes_lesson_id,
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_calibration_lesson(lesson_id)

    def get_calibration_lesson(self, lesson_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM calibration_lessons WHERE id = ?",
                (lesson_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"calibration lesson not found: {lesson_id}")
        return self._row_to_calibration_lesson(row)

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
        current = self.get_calibration_lesson(lesson_id)
        new_status = status or current["status"]
        if new_status not in CALIBRATION_LESSON_STATUSES:
            raise ValidationError(
                f"calibration lesson status must be one of {', '.join(sorted(CALIBRATION_LESSON_STATUSES))}"
            )
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValidationError("calibration lesson confidence must be between 0 and 1")
        # Same authoring gate as create: a `rule` must compile, so an enforceable
        # lesson can never be saved in a broken state that silently fails to bite.
        _rule = (recommended_adjustment or {}).get("rule") if isinstance(recommended_adjustment, dict) else None
        if isinstance(_rule, dict):
            from forecasting.hooks.dsl import RuleSpec, validate_rule

            _spec = RuleSpec.from_dict({**_rule, "id": "lesson:_validate", "applies_to": {}})
            _rule_errs = [issue for issue in validate_rule(_spec) if issue.severity == "error"]
            if _rule_errs:
                raise ValidationError(f"calibration lesson rule is invalid: {_rule_errs[0].message}")
        if current.get("invalidated_by_correction_id") and new_status == "active":
            raise ValidationError("invalidated calibration lessons cannot be activated")
        if supersedes_lesson_id:
            self.get_calibration_lesson(supersedes_lesson_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE calibration_lessons
                SET status = ?, confidence = COALESCE(?, confidence),
                    recommended_adjustment = ?,
                    supersedes_lesson_id = COALESCE(?, supersedes_lesson_id),
                    metadata = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    confidence,
                    json_dumps(recommended_adjustment if recommended_adjustment is not None else current["recommended_adjustment"]),
                    supersedes_lesson_id,
                    json_dumps(metadata if metadata is not None else current["metadata"]),
                    utc_now_iso(),
                    lesson_id,
                ),
            )
        return self.get_calibration_lesson(lesson_id)

    def apply_lesson(self, lesson_id: str, *, severity: str = "warn") -> dict[str, Any]:
        """Compile a calibration lesson into an enforceable hook rule — the lazy-
        operator path: turn a learning into strict, formal enforcement WITHOUT
        hand-authoring a RuleSpec. Resolves the lesson's enforcement pattern (declared
        or inferred), attaches the built rule to recommended_adjustment['rule']
        (re-validated on update), and returns a summary. No recognized pattern ->
        the lesson stays advisory (reported, never silently no-op). Severity defaults
        to WARN (observe-then-flip)."""
        from forecasting.lesson_templates import build_lesson_rule, resolve_enforcement_pattern

        lesson = self.get_calibration_lesson(lesson_id)
        pattern = resolve_enforcement_pattern(lesson.get("recommended_adjustment"))
        rule = build_lesson_rule(lesson, severity=severity)
        if rule is None:
            return {"lesson_id": lesson_id, "applied": False, "pattern": None, "reason": "no enforcement pattern — advisory"}
        adjustment = dict(lesson.get("recommended_adjustment") or {})
        adjustment["rule"] = rule
        self.update_calibration_lesson(lesson_id, recommended_adjustment=adjustment)
        return {"lesson_id": lesson_id, "applied": True, "pattern": pattern, "severity": severity, "check": rule["check"]}

    def list_calibration_lessons(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if scope_ref:
            clauses.append("scope_ref = ?")
            params.append(scope_ref)
        if active_only:
            clauses.append("status = 'active'")
            clauses.append("invalidated_by_correction_id IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM calibration_lessons {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_calibration_lesson(row) for row in rows]

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
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM desk_state WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row is not None else None

    def set_desk_state(self, key: str, value: str | None, *, now: str | None = None) -> None:
        stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO desk_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, stamped),
            )

    def transition_desk_state(
        self, key: str, new_value: str | None, *, now: str | None = None
    ) -> tuple[bool, str | None]:
        """Atomically set ``desk_state[key] = new_value`` under a write lock and
        report whether THIS call performed the change.

        Returns ``(changed, previous)``. ``changed`` is True only for the caller
        that actually moved the value; a concurrent caller that lost the race
        (``BEGIN IMMEDIATE`` serialises writers) — or a steady state where the
        stored value already equals ``new_value`` — gets ``changed=False`` and must
        not re-act. This makes a read-compare-write transition (e.g. the triage
        trust-gate mode) safe under overlapping sweeps: two sweeps can no longer
        both observe the old value and both fire the same transition alert.
        """
        stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
        conn = self._connect()
        try:
            conn.isolation_level = None  # take manual control of the transaction
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value FROM desk_state WHERE key = ?", (key,)
            ).fetchone()
            prev = row["value"] if row is not None else None
            if prev == new_value:
                conn.execute("COMMIT")
                return False, prev
            conn.execute(
                "INSERT INTO desk_state (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, new_value, stamped),
            )
            conn.execute("COMMIT")
            return True, prev
        finally:
            conn.close()

    def _has_open_alert(self, *, reason: str, scope_type: str, scope_ref: str) -> bool:
        """True when an unacknowledged alert with the SAME reason+scope already
        exists — so a re-transition does not stack a duplicate row (mirrors the
        dedup in :meth:`propose_due_resolutions`)."""
        for alert in self.list_alerts(unresolved_only=True):
            if (
                alert.reason == reason
                and alert.scope_type == scope_type
                and alert.scope_ref == scope_ref
            ):
                return True
        return False

    # ── Saturation visibility: under-saturation WARN alerts ──────────────────
    # The observe-mode saturation score is recorded on every snapshot but changes
    # no behaviour. These make an under-saturated LIVE forecast VISIBLE + actionable
    # without ever hard-blocking a commit: the scheduled cron sweep raises a deduped
    # WARN alert for each active live forecast below the bar, and a programmatic
    # commit (refresh / aggregate / autopilot — the lenient autofix paths) escalates
    # the SAME alert the moment it commits under the bar. The alert routes to the
    # REFORECAST resolution kind (the agent re-saturates it), so `reconcile_alerts`
    # auto-clears it once a fresh snapshot lands and the next sweep re-raises only if
    # it is still under-saturated. Never a bare-ack; deduped by reason+scope.
    _SATURATION_ALERT_REASON = "under_saturated"

    def enqueue_saturation_alert(
        self,
        question_id: str,
        saturation: Any,
        *,
        threshold: float | None = None,
    ) -> "AlertEvent | None":
        """Open a deduped WARN under-saturation alert for a forecast whose STORED
        saturation report (``snapshot_metadata['saturation']``, passed in — no
        recompute) scores below ``threshold`` (config
        ``forecasting.hooks.sweep_alert_threshold``, default 60). The
        ``recommended_action`` carries the failing rule ids + remediation hints.
        Deduped against an already-open alert of the same reason+scope (mirrors the
        triage-graduation + resolver-proposal kinds — never stacks a duplicate).
        Returns the new AlertEvent, or None (no report / at-or-above the bar /
        already open). Fail-open callers should still wrap this."""
        from forecasting.hooks import saturation_summary, sweep_alert_threshold

        summary = saturation_summary(saturation)
        if summary is None:
            return None
        score = summary.get("score")
        if not isinstance(score, (int, float)):
            return None
        bar = threshold if threshold is not None else sweep_alert_threshold()
        if score >= bar:
            return None
        if self._has_open_alert(
            reason=self._SATURATION_ALERT_REASON,
            scope_type="question",
            scope_ref=question_id,
        ):
            return None
        advisories = summary.get("advisories") or []
        rule_ids = [str(a.get("rule_id")) for a in advisories if a.get("rule_id")]
        hints = sorted({str(a.get("remediation")) for a in advisories if a.get("remediation")})
        action = f"forecast saturation {float(score):.0f}/100 is below the {float(bar):.0f} bar — under-saturated. "
        if rule_ids:
            action += f"Failing checks: {', '.join(rule_ids)}. "
        if hints:
            action += f"Remediate: {', '.join(hints)}. "
        action += (
            "Re-run the forecast (collect fresh evidence / run the panel / decompose / "
            "tag reasoning) to raise saturation, then re-commit."
        )
        return self.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=question_id,
            reason=self._SATURATION_ALERT_REASON,
            recommended_action=action,
        )

    def sweep_saturation_alerts(
        self,
        *,
        threshold: float | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Scan active LIVE forecasts and open a deduped WARN alert for each whose
        STORED saturation score is below the bar. Read-only over the observe report
        already on each current snapshot — no hook recompute. Batched
        (``snapshots_by_question``) to avoid a per-question query. Returns
        ``{checked, under_saturated, alerted:[question_id]}``."""
        from forecasting.hooks import saturation_summary, sweep_alert_threshold

        bar = threshold if threshold is not None else sweep_alert_threshold()
        questions = [
            q for q in self.list_questions(status="active", limit=limit)
            if q.outcome_space.type != "thesis"
        ]
        snapshots_by_q = self.snapshots_by_question([q.id for q in questions])
        checked = 0
        under = 0
        alerted: list[str] = []
        for question in questions:
            snaps = snapshots_by_q.get(question.id) or []
            current = snaps[-1] if snaps else None
            if current is None or getattr(current, "forecast_origin", None) != "live":
                continue
            metadata = getattr(current, "metadata", None)
            saturation = metadata.get("saturation") if isinstance(metadata, dict) else None
            summary = saturation_summary(saturation)
            if summary is None or not isinstance(summary.get("score"), (int, float)):
                continue
            checked += 1
            if summary["score"] >= bar:
                continue
            under += 1
            alert = self.enqueue_saturation_alert(question.id, saturation, threshold=bar)
            if alert is not None:
                alerted.append(question.id)
        return {"checked": checked, "under_saturated": under, "alerted": alerted}


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
        """Reduce scored binary forecasts to ``calibration_bias.Observation`` rows.

        Uses the *raw* pre-adjustment probability when a lesson previously moved
        the number (contamination control), records whether a lesson was in
        context (``lesson_active`` → kept off the derivation stratum upstream),
        and attaches a recency weight when a half-life is supplied.
        """

        from datetime import datetime, timezone

        from forecasting.calibration_bias import Observation

        def _parse(ts: Any) -> "datetime | None":
            if not ts:
                return None
            raw = str(ts).strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(raw)
            except ValueError:
                return None
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

        now_dt = _parse(now) or datetime.now(timezone.utc)
        scores = self.list_scores(
            domain=domain,
            forecast_origin=forecast_origin,
            calibration_eligible=True,
        )
        observations: list[Any] = []
        for score in scores:
            try:
                question = self.get_question(score.question_id)
            except LedgerNotFoundError:
                continue
            if question.outcome_space.type != "binary":
                continue
            try:
                snapshot = self.get_snapshot(score.forecast_id)
            except LedgerNotFoundError:
                continue
            adjustment = snapshot.calibration_adjustment or {}
            raw = adjustment.get("raw_probability")
            committed = snapshot.probability_or_distribution
            probability = raw if isinstance(raw, (int, float)) and not isinstance(raw, bool) else committed
            if not isinstance(probability, (int, float)) or isinstance(probability, bool):
                continue
            observed = self._binary_outcome_value(score, question.outcome_space)
            if observed is None:
                continue
            resolved_at = None
            try:
                resolved_at = self.get_resolution(score.resolution_id).resolved_at
            except LedgerNotFoundError:
                pass
            if since and resolved_at and str(resolved_at) < str(since):
                continue
            weight = 1.0
            if recency_halflife_days and recency_halflife_days > 0:
                resolved_dt = _parse(resolved_at)
                if resolved_dt is not None:
                    age_days = (now_dt - resolved_dt).total_seconds() / 86400.0
                    weight = recency_halflife_weight(age_days, recency_halflife_days)
            observations.append(
                Observation(
                    p_yes=float(probability),
                    outcome=float(observed),
                    weight=weight,
                    lesson_active=bool(snapshot.calibration_lesson_refs),
                    horizon_days=score.forecast_horizon_days,
                )
            )
        return observations

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
        """Signed calibration-bias report for one scope (global or a domain).

        Returns the ``CalibrationBiasReport`` payload — including ``status``
        (``insufficient_evidence`` until enough effective sample accrues), the
        signed/shrunk SCE, its CI and p-value, the curve shape, and advisory
        text. Emits nothing actionable on thin or noisy data by construction.
        """

        from forecasting.calibration_bias import assess_bias

        scope = scope_type or ("domain" if domain else "global")
        observations = self._bias_observations(
            domain=domain,
            since=since,
            recency_halflife_days=recency_halflife_days,
            forecast_origin=forecast_origin,
            now=now,
        )
        report = assess_bias(
            observations,
            scope_type=scope,
            scope_ref=domain,
            lesson_free_only=lesson_free_only,
            enable_mechanical=enable_mechanical,
            prior_scale=prior_scale,
            shrink_prior=shrink_prior,
        )
        return report.to_payload()

    def _live_score_count(self, domain: str | None) -> int:
        """Fast COUNT of live, calibration-eligible, non-invalidated score records
        (optionally in one domain). A cheap necessary-condition gate for the
        resolve-time bias synthesis: ESS <= count, so a count below the ESS floor
        guarantees the estimator would emit nothing — skip the O(n) scan."""
        clauses = [
            "forecast_origin = 'live'",
            "calibration_eligible = 1",
            "invalidated_by_correction_id IS NULL",
        ]
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) FROM score_records WHERE {' AND '.join(clauses)}",
                params,
            ).fetchone()
        return int(row[0]) if row else 0

    def _domains_with_scores(self, *, forecast_origin: str | None = "live") -> list[str]:
        clauses = ["domain IS NOT NULL", "invalidated_by_correction_id IS NULL"]
        params: list[Any] = []
        if forecast_origin:
            clauses.append("forecast_origin = ?")
            params.append(forecast_origin)
        where = " AND ".join(clauses)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT domain FROM score_records WHERE {where} ORDER BY domain",
                params,
            ).fetchall()
        return [str(row[0]) for row in rows if row[0]]

    def _prior_bias_lessons(self, scope_type: str, scope_ref: str | None) -> list[dict[str, Any]]:
        """Bias-sourced lessons for a scope, newest first (any status)."""

        lessons = self.list_calibration_lessons(scope_type=scope_type, scope_ref=scope_ref)
        return [
            lesson
            for lesson in lessons
            if (lesson.get("metadata") or {}).get("source") == self._BIAS_LESSON_SOURCE
        ]

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
        """Derive calibration-bias lessons across scopes with FDR control.

        Computes a signed-bias report per scope (global + each domain that has
        scored forecasts), shrinks each domain toward the global estimate,
        applies Benjamini-Hochberg across the family, then writes/activates,
        leaves tentative, or retires lessons per :func:`decide_disposition`.
        ``dry_run`` measures and decides without writing. Returns one result
        dict per scope (report payload + disposition + action taken).
        """

        from forecasting.calibration_bias import (
            assess_bias,
            benjamini_hochberg,
            decide_disposition,
        )

        # Resolve the scope family.
        targets: list[tuple[str, str | None]] = []
        if scope in ("all", "global"):
            targets.append(("global", None))
        if scope in ("all", "domain"):
            for name in (domains if domains is not None else self._domains_with_scores(forecast_origin=forecast_origin)):
                targets.append(("domain", name))
        if scope not in ("all", "global", "domain"):
            targets = [("domain", scope)]

        # Global estimate first — domains shrink toward it (empirical Bayes).
        global_obs = self._bias_observations(
            domain=None,
            since=since,
            recency_halflife_days=recency_halflife_days,
            forecast_origin=forecast_origin,
            now=now,
        )
        global_report = assess_bias(global_obs, scope_type="global", scope_ref=None)
        global_prior = global_report.sce_raw or 0.0

        reports = []
        for scope_type, scope_ref in targets:
            observations = self._bias_observations(
                domain=scope_ref,
                since=since,
                recency_halflife_days=recency_halflife_days,
                forecast_origin=forecast_origin,
                now=now,
            )
            prior_lessons = self._prior_bias_lessons(scope_type, scope_ref)
            prior_scale = None
            if prior_lessons:
                prior_scale = (prior_lessons[0].get("recommended_adjustment") or {}).get("logit_scale")
            report = assess_bias(
                observations,
                scope_type=scope_type,
                scope_ref=scope_ref,
                lesson_free_only=True,
                enable_mechanical=enable_mechanical,
                prior_scale=prior_scale,
                shrink_prior=0.0 if scope_type == "global" else global_prior,
            )
            reports.append((report, prior_lessons))

        # Benjamini-Hochberg FDR across the family of detectable scopes.
        pvalues = [rep.pvalue if rep.has_detectable_bias else None for rep, _ in reports]
        survived = benjamini_hochberg(pvalues, q=0.10)

        results: list[dict[str, Any]] = []
        for (report, prior_lessons), bh_ok in zip(reports, survived):
            trajectory = []
            if prior_lessons:
                trajectory = list((prior_lessons[0].get("metadata") or {}).get("sce_trajectory") or [])
            disposition = decide_disposition(report, bh_survived=bh_ok, trajectory=trajectory)
            status = disposition["lesson_status"]
            if not activate and status == "active":
                status = "tentative"
            action = self._apply_bias_disposition(
                report,
                status=status,
                trajectory=trajectory,
                prior_lessons=prior_lessons,
                dry_run=dry_run,
            )
            payload = report.to_payload()
            payload["disposition"] = disposition
            payload["bh_survived"] = bh_ok
            payload["action"] = action
            results.append(payload)
        return results

    def _apply_bias_disposition(
        self,
        report: Any,
        *,
        status: str,
        trajectory: list[float],
        prior_lessons: list[dict[str, Any]],
        dry_run: bool,
    ) -> dict[str, Any]:
        """Write/activate, leave tentative, or retire a scope's bias lesson.

        ``none`` retires any prior active lesson (a bias no longer detected must
        not keep influencing forecasts). ``suppressed`` (trajectory diverging)
        also retires and records an audit-only tentative marker. Otherwise a new
        lesson supersedes the prior one — lessons never accumulate.
        """

        active_priors = [lesson for lesson in prior_lessons if lesson.get("status") == "active"]

        if status == "none":
            if dry_run:
                return {"written": False, "retired": [l["id"] for l in active_priors], "status": "none"}
            for lesson in active_priors:
                self.update_calibration_lesson(lesson["id"], status="superseded")
            return {"written": False, "retired": [l["id"] for l in active_priors], "status": "none"}

        # Persist the per-scope |SCE| trajectory (capped history) for the guard.
        magnitude = abs(report.sce_shrunk or 0.0)
        new_trajectory = (trajectory + [round(magnitude, 5)])[-8:]
        metadata = {
            "source": self._BIAS_LESSON_SOURCE,
            "sce_shrunk": report.sce_shrunk,
            "sce_raw": report.sce_raw,
            "ci": [report.ci_low, report.ci_high],
            "pvalue": report.pvalue,
            "ess": round(report.ess, 3),
            "n": report.n,
            "direction": report.direction,
            "horizon_label": report.horizon_label,
            "sce_trajectory": new_trajectory,
            "suppressed": status == "suppressed",
        }
        confidence = None
        if report.pvalue is not None:
            confidence = round(min(max(1.0 - report.pvalue, 0.0), 1.0), 3)

        # Suppressed: retire the active lesson and stop pushing; keep a tentative
        # audit marker so the trajectory stays continuous.
        write_status = "tentative" if status == "suppressed" else status
        lesson_text = report.advisory_text or "Calibration bias detected; see metadata."
        if status == "suppressed":
            lesson_text = (
                "[suppressed: bias trajectory diverging across cycles — not pushing further] "
                + lesson_text
            )

        if dry_run:
            return {
                "written": False,
                "would_write_status": write_status,
                "retired": [l["id"] for l in active_priors],
                "status": status,
            }

        supersedes = active_priors[0]["id"] if active_priors else None
        for lesson in active_priors:
            self.update_calibration_lesson(lesson["id"], status="superseded")
        created = self.create_calibration_lesson(
            scope_type=report.scope_type,
            scope_ref=report.scope_ref,
            lesson=lesson_text,
            confidence=confidence,
            recommended_adjustment=report.recommended_adjustment or {},
            status=write_status,
            supersedes_lesson_id=supersedes,
            metadata=metadata,
        )
        return {
            "written": True,
            "lesson_id": created["id"],
            "lesson_status": write_status,
            "retired": [l["id"] for l in active_priors],
            "status": status,
        }

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
        allowed = {
            "forecast_snapshot",
            "evidence_item",
            "assumption",
            "reference_class",
            "resolution",
            "score_record",
            "postmortem",
            "calibration_lesson",
        }
        if target_type not in allowed:
            raise ValidationError(f"target_type must be one of {', '.join(sorted(allowed))}")
        if status not in {"proposed", "applied", "rejected"}:
            raise ValidationError("correction status must be proposed, applied, or rejected")
        if not reason.strip():
            raise ValidationError("correction reason is required")
        correction_id = f"fc_{uuid.uuid4().hex[:12]}"
        affected_scores, affected_postmortems, affected_lessons = self._affected_records_for_correction(
            target_type,
            target_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_corrections (
                    id, target_type, target_id, created_at, created_by, reason,
                    old_value, new_value, patch, affected_score_record_refs,
                    affected_postmortem_refs, affected_calibration_lesson_refs,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    correction_id,
                    target_type,
                    target_id,
                    utc_now_iso(),
                    created_by,
                    reason.strip(),
                    json_dumps(old_value),
                    json_dumps(new_value),
                    json_dumps(patch or {}),
                    json_dumps(affected_scores),
                    json_dumps(affected_postmortems),
                    json_dumps(affected_lessons),
                    status,
                ),
            )
            if status == "applied":
                self._invalidate_learning_records_for_correction(
                    conn,
                    correction_id=correction_id,
                    score_refs=affected_scores,
                    postmortem_refs=affected_postmortems,
                    lesson_refs=affected_lessons,
                )
        if affected_scores or affected_postmortems or affected_lessons:
            self.create_alert(
                severity="high",
                scope_type=target_type,
                scope_ref=target_id,
                reason="correction_affects_learning_records",
                recommended_action="Review affected scores, postmortems, and calibration lessons before relying on them.",
            )
        return self.get_correction(correction_id)

    def get_correction(self, correction_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_corrections WHERE id = ?",
                (correction_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"correction not found: {correction_id}")
        data = dict(row)
        for field in (
            "old_value",
            "new_value",
            "patch",
            "affected_score_record_refs",
            "affected_postmortem_refs",
            "affected_calibration_lesson_refs",
        ):
            data[field] = json_loads(data[field], {} if field in {"old_value", "new_value", "patch"} else [])
        return data

    def list_corrections(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if target_type:
            clauses.append("target_type = ?")
            params.append(target_type)
        if target_id:
            clauses.append("target_id = ?")
            params.append(target_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM forecast_corrections {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        return [self.get_correction(row["id"]) for row in rows]

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
        if not resolver_plugin.strip():
            raise ValidationError("resolver_plugin is required")
        if scope_type not in {"domain", "topic", "source", "question_type", "global"}:
            raise ValidationError("resolver policy scope_type must be domain, topic, source, question_type, or global")
        policy_id = f"trp_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trusted_resolver_policies (
                    id, resolver_plugin, plugin_version, scope_type, scope_ref,
                    enabled, created_at, approved_by, audit_log_ref
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    resolver_plugin.strip(),
                    plugin_version,
                    scope_type,
                    scope_ref,
                    1 if enabled else 0,
                    utc_now_iso(),
                    approved_by,
                    audit_log_ref,
                ),
            )
        return self.get_trusted_resolver_policy(policy_id)

    def get_trusted_resolver_policy(self, policy_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM trusted_resolver_policies WHERE id = ?",
                (policy_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"trusted resolver policy not found: {policy_id}")
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        return data

    def list_trusted_resolver_policies(
        self,
        *,
        resolver_plugin: str | None = None,
        scope_type: str | None = None,
        enabled: bool | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if resolver_plugin:
            clauses.append("resolver_plugin = ?")
            params.append(resolver_plugin)
        if scope_type:
            clauses.append("scope_type = ?")
            params.append(scope_type)
        if enabled is not None:
            clauses.append("enabled = ?")
            params.append(1 if enabled else 0)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM trusted_resolver_policies {where} ORDER BY created_at DESC",
                params,
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["enabled"] = bool(data["enabled"])
            result.append(data)
        return result

    def update_domain_error_profile(self, question: ForecastQuestion) -> dict[str, Any] | None:
        domain = question.domain
        if not domain:
            return None
        domain_scores = self.list_scores(domain=domain, calibration_eligible=True)
        domain_profile = self._write_error_profile(
            domain=domain,
            topic=None,
            question_type=question.outcome_space.type,
            scores=domain_scores,
        )
        for topic in question.topics:
            topic_scores = [
                score
                for score in domain_scores
                if topic in self.get_question(score.question_id).topics
            ]
            self._write_error_profile(
                domain=domain,
                topic=topic,
                question_type=question.outcome_space.type,
                scores=topic_scores,
            )
        return domain_profile

    def _write_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
        question_type: str,
        scores: list[ScoreRecord],
    ) -> dict[str, Any]:
        brier_values = [score.brier_score for score in scores if score.brier_score is not None]
        postmortems = self._postmortems_for_error_profile(domain=domain, topic=topic)
        error_counts = self._error_counts_for_profile(scores=scores, postmortems=postmortems)
        summary = {
            "count": len(brier_values),
            "mean_brier": sum(brier_values) / len(brier_values) if brier_values else None,
            "postmortem_count": len(postmortems),
            "error_counts": dict(sorted(error_counts.items())),
        }
        recurring_errors: list[str] = []
        if summary["mean_brier"] is not None and summary["mean_brier"] > 0.25:
            recurring_errors.append("elevated_mean_brier")
        recurring_errors.extend(self._recurring_error_tags(error_counts))
        recurring_errors = list(dict.fromkeys(recurring_errors))
        recommended_adjustments = self._recommended_adjustments_for_errors(recurring_errors)
        sample_count = len(brier_values)
        profile_id = self._domain_error_profile_id(domain, topic, None, question_type)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO domain_error_profiles (
                    id, domain, topic, forecast_horizon_bucket, question_type,
                    sample_count, calibration_summary, recurring_errors,
                    recommended_adjustments, updated_at
                )
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    domain,
                    topic,
                    question_type,
                    sample_count,
                    json_dumps(summary),
                    json_dumps(recurring_errors),
                    json_dumps(recommended_adjustments),
                    utc_now_iso(),
                ),
            )
        return self.get_domain_error_profile(profile_id)

    def _postmortems_for_error_profile(
        self,
        *,
        domain: str,
        topic: str | None,
    ) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for postmortem in self.list_postmortems():
            if not postmortem.get("calibration_eligible"):
                continue
            try:
                question = self.get_question(postmortem["question_id"])
            except LedgerNotFoundError:
                continue
            if question.domain != domain:
                continue
            if topic and topic not in question.topics:
                continue
            scoped.append(postmortem)
        return scoped

    def _error_counts_for_profile(
        self,
        *,
        scores: list[ScoreRecord],
        postmortems: list[dict[str, Any]],
    ) -> Counter[str]:
        counts: Counter[str] = Counter()
        score_tags_by_id: dict[str, set[str]] = defaultdict(set)
        for score in scores:
            if score.brier_score is not None and score.brier_score > 0.25:
                counts["high_brier_miss"] += 1
                score_tags_by_id[score.id].add("high_brier_miss")
            if score.brier_score is not None and score.brier_score >= 0.36:
                try:
                    snapshot = self.get_snapshot(score.forecast_id)
                except LedgerNotFoundError:
                    snapshot = None
                if snapshot is not None:
                    sharpness = self._sharpness(snapshot.probability_or_distribution)
                    if sharpness is not None and sharpness >= 0.6:
                        counts["overconfidence"] += 1
                        score_tags_by_id[score.id].add("overconfidence")
                    for model_run_ref in snapshot.model_run_refs:
                        try:
                            model_run = self.get_model_run(model_run_ref)
                        except LedgerNotFoundError:
                            continue
                        if model_run["status"] == "failure":
                            counts["model_family_failure"] += 1

        field_tags = {
            "missed_evidence": "missed_evidence",
            "overweighted_evidence": "overweighted_evidence",
            "base_rate_error": "base_rate_error",
            "inside_view_error": "inside_view_error",
            "resolution_error": "resolution_error",
        }
        for postmortem in postmortems:
            for field, tag in field_tags.items():
                if str(postmortem.get(field) or "").strip():
                    counts[tag] += 1
            adjustment = postmortem.get("calibration_adjustment") or {}
            if isinstance(adjustment, dict):
                score_id = str(postmortem.get("score_record_id") or "")
                for tag in adjustment.get("error_tags") or []:
                    if not isinstance(tag, str) or not tag.strip():
                        continue
                    normalized = tag.strip()
                    if normalized in score_tags_by_id.get(score_id, set()):
                        continue
                    counts[normalized] += 1
        return counts

    def _recurring_error_tags(self, error_counts: Counter[str]) -> list[str]:
        ordered = [
            "overconfidence",
            "base_rate_error",
            "missed_evidence",
            "overweighted_evidence",
            "inside_view_error",
            "resolution_error",
            "model_family_failure",
            "late_evidence_update",
            "stale_base_rate",
            "high_brier_miss",
        ]
        ordered_set = set(ordered)
        tags = [tag for tag in ordered if error_counts.get(tag, 0) > 0]
        tags.extend(
            tag
            for tag, count in sorted(error_counts.items())
            if count > 0 and tag not in ordered_set
        )
        return tags

    def _recommended_adjustments_for_errors(self, recurring_errors: list[str]) -> list[str]:
        recommendations_by_error = {
            "elevated_mean_brier": "Review postmortems before increasing confidence in this scope.",
            "overconfidence": (
                "Temper high-confidence updates in this scope; require explicit outside-view, "
                "base-rate, and counterevidence checks before extreme probabilities."
            ),
            "base_rate_error": "Refresh reference classes and base rates before updating similar questions.",
            "stale_base_rate": "Shorten base-rate refresh cadence and verify stale reference classes before updates.",
            "missed_evidence": "Expand the source checklist and add watched sources for missing evidence classes.",
            "late_evidence_update": "Shorten review cadence for active questions with fast-moving evidence.",
            "overweighted_evidence": "Downweight single-source narratives until checked against base rates and counterevidence.",
            "inside_view_error": "Separate inside-view arguments from outside-view priors and record the reconciliation.",
            "resolution_error": "Re-read resolution criteria and resolver sources before forecasting similar questions.",
            "model_family_failure": "Review failed model runs before relying on that model family in this scope.",
            "high_brier_miss": "Inspect high-Brier misses before making adjacent forecasts.",
        }
        return [
            recommendations_by_error[tag]
            for tag in recurring_errors
            if tag in recommendations_by_error
        ]

    def get_domain_error_profile(self, profile_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM domain_error_profiles WHERE id = ?",
                (profile_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"domain error profile not found: {profile_id}")
        return self._row_to_domain_error_profile(row)

    def list_domain_error_profiles(
        self,
        *,
        domain: str | None = None,
        topic: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = ?")
            params.append(domain)
        if topic:
            clauses.append("topic = ?")
            params.append(topic)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM domain_error_profiles {where} ORDER BY updated_at DESC",
                params,
            ).fetchall()
        return [self._row_to_domain_error_profile(row) for row in rows]

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
        question = self.get_question(question_id)
        payload = self._validate_probability_payload(probability_or_distribution, question.outcome_space)
        if score_record_id is not None:
            self.get_score(score_record_id)
        baseline_id = f"bc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO baseline_comparisons (
                    id, question_id, forecast_id, backtest_case_id, source,
                    baseline_type, as_of, probability_or_distribution,
                    score_record_id, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    baseline_id,
                    question_id,
                    forecast_id,
                    backtest_case_id,
                    source,
                    baseline_type,
                    parse_timestamp(as_of, field_name="as_of") or utc_now_iso(),
                    json_dumps(payload),
                    score_record_id,
                    json_dumps(metadata or {}),
                ),
            )
            if score_record_id is not None:
                conn.execute(
                    "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                    (baseline_id, score_record_id),
                )
        return self.get_baseline_comparison(baseline_id)

    def get_baseline_comparison(self, baseline_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM baseline_comparisons WHERE id = ?",
                (baseline_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"baseline comparison not found: {baseline_id}")
        data = dict(row)
        data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def list_baseline_comparisons(self, question_id: str) -> list[dict[str, Any]]:
        self.get_question(question_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM baseline_comparisons WHERE question_id = ? ORDER BY as_of ASC",
                (question_id,),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["probability_or_distribution"] = json_loads(data["probability_or_distribution"], None)
            data["metadata"] = json_loads(data["metadata"], {})
            result.append(data)
        return result

    def score_baseline_comparisons(self, question_id: str, *, force: bool = False) -> list[dict[str, Any]]:
        """Score imported baselines for a resolved live question without moving the current forecast."""

        self.get_question(question_id)
        if self.get_latest_resolution(question_id, confirmed_only=True) is None:
            raise ValidationError(
                "cannot score baseline comparisons until resolution is confirmed, criteria-satisfied, and scoreable"
            )
        scored: list[dict[str, Any]] = []
        for baseline in self.list_baseline_comparisons(question_id):
            if baseline.get("score_record_id") and not force:
                scored.append({**baseline, "score": self.get_score(baseline["score_record_id"])})
                continue
            forecast_id = baseline.get("forecast_id")
            if not forecast_id:
                snapshot = self.create_snapshot(
                    question_id=question_id,
                    probability_or_distribution=baseline["probability_or_distribution"],
                    rationale=f"Imported baseline from {baseline.get('source') or 'unknown source'}.",
                    as_of=baseline.get("as_of"),
                    method=str(baseline.get("baseline_type") or "imported"),
                    forecast_origin="imported_baseline",
                    calibration_eligible=False,
                    calibration_weight=0.0,
                    metadata={
                        "baseline_comparison_id": baseline["id"],
                        "baseline_source": baseline.get("source"),
                    },
                    set_current=False,
                )
                forecast_id = snapshot.forecast_id
            score = self.score_snapshot(forecast_id, force=force)
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE baseline_comparisons
                    SET forecast_id = ?, score_record_id = ?
                    WHERE id = ?
                    """,
                    (forecast_id, score.id, baseline["id"]),
                )
                conn.execute(
                    "UPDATE score_records SET baseline_ref = ? WHERE id = ?",
                    (baseline["id"], score.id),
                )
            updated = self.get_baseline_comparison(baseline["id"])
            scored.append({**updated, "score": score})
        return scored

    def import_benchmark_dataset(
        self,
        *,
        source: str,
        cases: list[dict[str, Any]],
        name: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(cases, list):
            raise ValidationError("benchmark dataset cases must be a list")
        valid_cases = [case for case in cases if isinstance(case, dict)]
        if len(valid_cases) != len(cases):
            raise ValidationError("benchmark dataset cases must be objects")
        dataset_id = f"bd_{uuid.uuid4().hex[:12]}"
        dataset_name = name or Path(str(source)).stem or str(source)
        imported_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO benchmark_datasets (
                    id, name, source, imported_at, case_count,
                    description, cases, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    dataset_id,
                    dataset_name,
                    source,
                    imported_at,
                    len(valid_cases),
                    description,
                    json_dumps(valid_cases),
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_benchmark_dataset(dataset_id)

    def get_benchmark_dataset(self, dataset_id: str) -> dict[str, Any]:
        lookup = dataset_id.removeprefix("imported:")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM benchmark_datasets WHERE id = ?",
                (lookup,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"benchmark dataset not found: {dataset_id}")
        return self._row_to_benchmark_dataset(row)

    def list_benchmark_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM benchmark_datasets ORDER BY imported_at DESC",
            ).fetchall()
        return [self._row_to_benchmark_dataset(row) for row in rows]

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
        run_id = f"bt_{uuid.uuid4().hex[:12]}"
        default_cutoff = parse_timestamp(
            default_forecast_time_cutoff,
            field_name="default_forecast_time_cutoff",
        )
        created_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_runs (
                    id, dataset, created_at, default_forecast_time_cutoff,
                    evidence_cutoff_policy, calibration_policy,
                    leakage_checks_passed
                )
                VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    run_id,
                    dataset,
                    created_at,
                    default_cutoff,
                    evidence_cutoff_policy,
                    json_dumps(
                        calibration_policy
                        or {"allow_calibration_memory": allow_calibration_memory}
                    ),
                ),
            )

        case_rows: list[dict[str, Any]] = []
        leakage_passed = True
        for case in cases:
            case_row = self._run_backtest_case(
                run_id=run_id,
                case=case,
                default_cutoff=default_cutoff,
                allow_calibration_memory=allow_calibration_memory,
                leak_judge_runner=leak_judge_runner,
            )
            case_rows.append(case_row)
            if case_row["leakage_check_status"] != "passed":
                leakage_passed = False

        result_summary = {
            "case_count": len(case_rows),
            "benchmark_evidence": build_benchmark_evidence_profile(dataset, cases),
            "leakage_checks_passed": leakage_passed,
            "scored_cases": sum(1 for row in case_rows if row.get("score_record_id")),
        }
        # MARKET-HIDDEN ARM label: stamp the experimental arm on the run so later
        # analysis can separate arms (e.g. arm='market_hidden' — the market price was
        # scored as a baseline but withheld from the agent's prompt). Additive: absent
        # by default, so a run with no arm is byte-identical to before.
        if arm:
            result_summary["arm"] = str(arm)
        # AIA P1.2 — surface the content-channel bookkeeping + read-only robustness
        # bounds ONLY when the judge channel ran (a runner was supplied). With the
        # channel OFF these keys are absent, keeping the summary byte-identical.
        if leak_judge_runner is not None:
            content_flagged = sum(
                1 for row in case_rows if int(row.get("content_flag_count") or 0) > 0
            )
            result_summary["leak_judge"] = self._build_leak_robustness_summary(
                run_id,
                content_flagged_cases=content_flagged,
            )
        agent_brier_scores = [
            row["score_brier"]
            for row in case_rows
            if row.get("score_brier") is not None
        ]
        if agent_brier_scores:
            result_summary["agent_mean_brier"] = sum(agent_brier_scores) / len(agent_brier_scores)
        probability_sources = sorted(
            {
                str(case.get("probability_source"))
                for case in cases
                if case.get("probability_source")
            }
        )
        if probability_sources:
            result_summary["probability_sources"] = probability_sources
        if not leakage_passed:
            self._disable_backtest_calibration(run_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE backtest_runs
                SET result_summary = ?, leakage_checks_passed = ?
                WHERE id = ?
                """,
                (json_dumps(result_summary), 1 if leakage_passed else 0, run_id),
            )
        run = self.get_backtest_run(run_id)
        run["cases"] = case_rows
        return run

    def get_backtest_run(self, run_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"backtest run not found: {run_id}")
        data = dict(row)
        for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
            data[field] = json_loads(data[field], {})
        data["artifact_paths"] = json_loads(data["artifact_paths"], [])
        data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
        return data

    def list_backtest_runs(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY created_at DESC",
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            for field in ("question_filter", "model_profile", "calibration_policy", "result_summary"):
                data[field] = json_loads(data[field], {})
            data["artifact_paths"] = json_loads(data["artifact_paths"], [])
            data["leakage_checks_passed"] = bool(data["leakage_checks_passed"])
            result.append(data)
        return result

    def list_backtest_cases(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM backtest_cases WHERE backtest_run_id = ? ORDER BY simulated_forecast_time ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_backtest_case(row) for row in rows]

    def backtest_performance_report(self, run_id: str) -> dict[str, Any]:
        run = self.get_backtest_run(run_id)
        cases = self.list_backtest_cases(run_id)
        agent_scores: list[ScoreRecord] = []
        baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
        paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
        # Agent-vs-baseline Brier pairs across the FULL baseline set, keyed by the
        # agent SCORE id (NOT question_id) so a question that recurs across rolling
        # cutoffs keeps each agent forecast paired only with ITS OWN baselines —
        # win-rate-vs-best is then "agent <= every baseline" per resolved forecast.
        score_pairs: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
        for case in cases:
            agent_score = self.get_score(case["score_record_id"]) if case.get("score_record_id") else None
            if agent_score is not None:
                agent_scores.append(agent_score)
            for baseline_id in case.get("baseline_comparison_refs") or []:
                baseline = self.get_baseline_comparison(baseline_id)
                if not baseline.get("score_record_id"):
                    continue
                baseline_score = self.get_score(baseline["score_record_id"])
                key = (baseline["baseline_type"], baseline["source"])
                baseline_scores[key].append(baseline_score)
                if agent_score is not None:
                    paired_scores[key].append((agent_score, baseline_score))
                    score_pairs[agent_score.id].append(
                        (agent_score.brier_score, baseline_score.brier_score)
                    )

        baselines = []
        for key in sorted(baseline_scores):
            baseline_type, source = key
            pairs = paired_scores.get(key, [])
            paired_brier = self._paired_brier_summary(pairs)
            baselines.append(
                {
                    "baseline_type": baseline_type,
                    "source": source,
                    **self._score_summary(baseline_scores[key]),
                    "paired_count": len(pairs),
                    **paired_brier,
                    "mean_brier_improvement_vs_baseline": self._mean(
                        [
                            baseline.brier_score - agent.brier_score
                            for agent, baseline in pairs
                            if agent.brier_score is not None and baseline.brier_score is not None
                        ]
                    ),
                    "mean_log_improvement_vs_baseline": self._mean(
                        [
                            baseline.log_score - agent.log_score
                            for agent, baseline in pairs
                            if agent.log_score is not None and baseline.log_score is not None
                        ]
                    ),
                }
            )
        return {
            "run_id": run["id"],
            "dataset": run["dataset"],
            "case_count": len(cases),
            "leakage_checks_passed": run["leakage_checks_passed"],
            "agent": self._score_summary(agent_scores),
            "baselines": baselines,
            "win_rate_vs_best": self._win_rate_vs_best(score_pairs),
            "agent_by_domain": self._score_breakdown(agent_scores, lambda score: score.domain or "unknown"),
            "agent_by_horizon": self._score_breakdown(agent_scores, self._score_horizon_bucket),
        }

    def live_performance_report(self, *, domain: str | None = None) -> dict[str, Any]:
        """Compare scored live forecasts against scored imported baselines."""

        live_scores = self.list_scores(
            domain=domain,
            forecast_origin="live",
            calibration_eligible=None,
        )
        baseline_scores: dict[tuple[str, str], list[ScoreRecord]] = defaultdict(list)
        paired_scores: dict[tuple[str, str], list[tuple[ScoreRecord, ScoreRecord]]] = defaultdict(list)
        # Keyed by the agent SCORE id (not question_id) so multiple resolved live
        # scores of the same question stay paired with their own baselines.
        score_pairs: dict[str, list[tuple[float | None, float | None]]] = defaultdict(list)
        for live_score in live_scores:
            for baseline in self.list_baseline_comparisons(live_score.question_id):
                if not baseline.get("score_record_id"):
                    continue
                baseline_score = self.get_score(baseline["score_record_id"])
                key = (baseline["baseline_type"], baseline["source"])
                baseline_scores[key].append(baseline_score)
                paired_scores[key].append((live_score, baseline_score))
                score_pairs[live_score.id].append(
                    (live_score.brier_score, baseline_score.brier_score)
                )

        baselines = []
        for key in sorted(baseline_scores):
            baseline_type, source = key
            pairs = paired_scores.get(key, [])
            baselines.append(
                {
                    "baseline_type": baseline_type,
                    "source": source,
                    **self._score_summary(baseline_scores[key]),
                    "paired_count": len(pairs),
                    **self._paired_brier_summary(pairs),
                    "mean_brier_improvement_vs_baseline": self._mean(
                        [
                            baseline.brier_score - agent.brier_score
                            for agent, baseline in pairs
                            if agent.brier_score is not None and baseline.brier_score is not None
                        ]
                    ),
                    "mean_log_improvement_vs_baseline": self._mean(
                        [
                            baseline.log_score - agent.log_score
                            for agent, baseline in pairs
                            if agent.log_score is not None and baseline.log_score is not None
                        ]
                    ),
                }
            )
        return {
            "score_count": len(live_scores),
            "agent": self._score_summary(live_scores),
            "baselines": baselines,
            "win_rate_vs_best": self._win_rate_vs_best(score_pairs),
            "agent_by_domain": self._score_breakdown(live_scores, lambda score: score.domain or "unknown"),
            "agent_by_horizon": self._score_breakdown(live_scores, self._score_horizon_bucket),
            "claim_status": {
                "verdict": "live_comparison_evidence" if baselines else "no_scored_live_baselines",
                "can_claim_live_superforecasting": False,
                "message": (
                    "Resolved live forecasts have scored imported baselines for comparison; "
                    "superforecasting claims still require enough prospective volume and coverage."
                    if baselines
                    else "No scored imported baselines are available for live comparison yet."
                ),
            },
        }

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
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        questions = self.list_questions(status="active", domain=domain)
        if topic:
            questions = [question for question in questions if topic in question.topics]
        now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
        assert now_dt is not None
        rows: list[dict[str, Any]] = []
        for question in questions:
            snapshot = self.get_current_snapshot(question.id)
            if horizon and (
                snapshot is None
                or not self._horizon_matches(snapshot.forecast_horizon_days, horizon)
            ):
                continue
            if confidence_below is not None or confidence_above is not None:
                if snapshot is None or snapshot.confidence is None:
                    continue
                if confidence_below is not None and snapshot.confidence >= confidence_below:
                    continue
                if confidence_above is not None and snapshot.confidence <= confidence_above:
                    continue
            reasons: list[str] = []
            evidence_items = self.list_evidence(question.id)
            if snapshot is None:
                reasons.append("no_forecast_snapshot")
            else:
                snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
                for item in evidence_items:
                    available_dt = timestamp_to_datetime(item.available_at)
                    if snapshot_as_of and available_dt and available_dt > snapshot_as_of:
                        reasons.append(f"new_evidence:{item.id}")
            if question.next_review_at:
                next_review = timestamp_to_datetime(question.next_review_at)
                if next_review and next_review <= now_dt:
                    reasons.append("review_due")
            if question.close_time:
                close_time = timestamp_to_datetime(question.close_time)
                if close_time and close_time <= now_dt:
                    reasons.append("close_time_passed")
                elif stale and last_days is not None and close_time and close_time <= now_dt + timedelta(days=last_days):
                    reasons.append(f"close_time_within_{last_days}d")
            if question.resolution_time:
                resolution_time = timestamp_to_datetime(question.resolution_time)
                if resolution_time and resolution_time <= now_dt:
                    reasons.append("resolution_check_due")
            if stale and snapshot is not None and last_days is not None:
                as_of = timestamp_to_datetime(snapshot.as_of)
                if as_of and (now_dt - as_of).days >= last_days:
                    reasons.append(f"last_update_{last_days}d_plus")
                if not evidence_items:
                    reasons.append("no_evidence")
                else:
                    latest_available = max(
                        (
                            timestamp_to_datetime(item.available_at)
                            for item in evidence_items
                            if timestamp_to_datetime(item.available_at) is not None
                        ),
                        default=None,
                    )
                    if latest_available and (now_dt - latest_available).days >= last_days:
                        reasons.append(f"evidence_stale_{last_days}d_plus")
            for assumption in self.list_assumptions(question.id):
                if assumption["status"] == "invalidated":
                    reasons.append(f"assumption_invalidated:{assumption['id']}")
                elif assumption["status"] == "stale":
                    reasons.append(f"assumption_stale:{assumption['id']}")
                elif self._cadence_due(
                    assumption.get("last_checked_at") or assumption.get("created_at"),
                    assumption.get("check_cadence"),
                    now_dt,
                ):
                    reasons.append(f"assumption_check_due:{assumption['id']}")
            for reference_class in self.list_reference_classes(question.id):
                if reference_class["status"] == "invalidated":
                    reasons.append(f"reference_class_invalidated:{reference_class['id']}")
                elif reference_class["status"] in {"stale", "superseded"}:
                    reasons.append(f"reference_class_stale:{reference_class['id']}")
                elif self._cadence_due(
                    reference_class.get("last_checked_at") or reference_class.get("created_at"),
                    reference_class.get("check_cadence"),
                    now_dt,
                ):
                    reasons.append(f"reference_class_check_due:{reference_class['id']}")
            if large_delta_threshold is not None:
                delta = self._latest_forecast_delta(question.id)
                if delta is not None and abs(delta) >= large_delta_threshold:
                    reasons.append(f"large_forecast_delta:{delta:+.3f}")
            if reasons or not stale:
                rows.append(
                    {
                        "question": question,
                        "current_snapshot": snapshot,
                        "reasons": reasons,
                        "priority": self._review_priority(reasons),
                    }
                )
        return sorted(
            rows,
            key=lambda row: (
                row["priority"],
                row["question"].close_time or row["question"].resolution_time or "9999-12-31T00:00:00Z",
                row["question"].title.lower(),
            ),
        )

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
        if scope_type not in SCHEDULE_SCOPE_TYPES:
            raise ValidationError(
                "scope_type must be question, domain, topic, domain_topic, portfolio, or horizon"
            )
        if scope_type == "horizon":
            if not scope_ref:
                raise ValidationError("horizon scheduled reviews require scope_ref")
            self._horizon_matches(0.0, scope_ref)
        if not cadence.strip():
            raise ValidationError("cadence is required")
        if stale_days < 0:
            raise ValidationError("stale_days must be non-negative")
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        review_id = f"sr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            # Idempotent by (scope_type, scope_ref, cadence, trigger_reason): a
            # schedule for the same scope + cadence + reason already covers this, so
            # re-scheduling re-activates the existing row instead of spawning a
            # duplicate. Without this, a lazy prompter (or the agent re-running an
            # onboarding step) silently accumulates duplicate weekly reviews that
            # each fire independently. scope_ref may be NULL, so match it explicitly.
            existing = conn.execute(
                """
                SELECT id FROM scheduled_reviews
                WHERE scope_type = ? AND cadence = ? AND trigger_reason = ?
                  AND ((scope_ref IS NULL AND ? IS NULL) OR scope_ref = ?)
                ORDER BY enabled DESC, next_run_at ASC
                LIMIT 1
                """,
                (scope_type, cadence, trigger_reason, scope_ref, scope_ref),
            ).fetchone()
            if existing is not None:
                # Idempotent UPSERT: a re-schedule for the same scope+cadence+reason
                # must APPLY its new settings (stale_days, auto_*, filters), not be
                # silently dropped — only the duplicate ROW is avoided. next_run_at is
                # reset only when the caller passed one explicitly, so a plain
                # re-schedule preserves the existing cadence position (no re-trigger).
                set_clauses = [
                    "enabled = ?",
                    "stale_days = ?",
                    "auto_score = ?",
                    "auto_postmortem = ?",
                    "confidence_below = ?",
                    "confidence_above = ?",
                    "large_delta_threshold = ?",
                ]
                params: list[Any] = [
                    1 if enabled else 0,
                    int(stale_days),
                    1 if auto_score else 0,
                    1 if auto_postmortem else 0,
                    confidence_below,
                    confidence_above,
                    large_delta_threshold,
                ]
                if next_run_at is not None:
                    set_clauses.append("next_run_at = ?")
                    params.append(parse_timestamp(next_run_at, field_name="next_run_at") or utc_now_iso())
                params.append(existing["id"])
                conn.execute(f"UPDATE scheduled_reviews SET {', '.join(set_clauses)} WHERE id = ?", params)
                # Return the upserted row's id and read it AFTER this `with` commits:
                # get_scheduled_review opens its own connection, so reading it inside
                # this still-open transaction would return the pre-UPDATE row (the
                # upserted auto_*/stale_days/filters would be invisible).
                result_id = existing["id"]
            else:
                conn.execute(
                    """
                    INSERT INTO scheduled_reviews (
                        id, scope_type, scope_ref, cadence, stale_days, next_run_at,
                        trigger_reason, enabled, auto_score, auto_postmortem,
                        confidence_below, confidence_above, large_delta_threshold
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        review_id,
                        scope_type,
                        scope_ref,
                        cadence,
                        int(stale_days),
                        parse_timestamp(next_run_at, field_name="next_run_at") or utc_now_iso(),
                        trigger_reason,
                        1 if enabled else 0,
                        1 if auto_score else 0,
                        1 if auto_postmortem else 0,
                        confidence_below,
                        confidence_above,
                        large_delta_threshold,
                    ),
                )
                result_id = review_id
        return self.get_scheduled_review(result_id)

    def get_scheduled_review(self, review_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM scheduled_reviews WHERE id = ?", (review_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"scheduled review not found: {review_id}")
        return dict(row)

    def list_scheduled_reviews(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_reviews ORDER BY next_run_at ASC",
            ).fetchall()
        return [dict(row) for row in rows]

    def annotate_snapshot(self, snapshot_id: str, patch: dict[str, Any]) -> None:
        """Merge a small PROVENANCE patch into a snapshot's metadata.

        For decisions made immediately AFTER the commit (e.g. the auto-quorum
        started/skipped record) so audits read the full story from the record
        itself. UPDATE-only — never changes the probability, rationale, or any
        gated field; the method is the blessed writer (validation + scope)."""
        if not patch:
            return
        with allow_ledger_writes("annotate_snapshot"), self._connect() as conn:
            row = conn.execute(
                "SELECT metadata FROM forecast_snapshots WHERE forecast_id = ?", (snapshot_id,)
            ).fetchone()
            if row is None:
                raise LedgerNotFoundError(f"snapshot not found: {snapshot_id}")
            try:
                current = json.loads(row["metadata"]) if row["metadata"] else {}
            except (TypeError, json.JSONDecodeError):
                current = {}
            current.update(patch)
            conn.execute(
                "UPDATE forecast_snapshots SET metadata = ? WHERE forecast_id = ?",
                (json.dumps(current), snapshot_id),
            )

    def next_review_by_question(self) -> dict[str, dict[str, Any]]:
        """question_id -> {next_run_at, cadence} from the SOONEST enabled per-question
        scheduled review (the live, self-advancing schedule, not the stale question
        column). One batched query for the desk's "next update" column."""
        out: dict[str, dict[str, Any]] = {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope_ref, next_run_at, cadence FROM scheduled_reviews "
                "WHERE scope_type = 'question' AND enabled = 1 AND next_run_at IS NOT NULL "
                "ORDER BY next_run_at ASC",
            ).fetchall()
        for row in rows:
            ref = row["scope_ref"]
            # ORDER BY next_run_at ASC → the first row per question is the soonest.
            if ref and ref not in out:
                out[ref] = {"cadence": row["cadence"], "next_run_at": row["next_run_at"]}
        return out

    def count_due_scheduled_reviews(self, *, now: str | None = None) -> int:
        """Cheap COUNT of enabled scheduled-review rows already DUE (next_run_at <= now).

        The gateway due-sweeper reads this every tick to decide whether to run the
        deterministic sweep at all — one indexed COUNT, no row materialization, so
        the common "nothing due" case is nearly free."""
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM scheduled_reviews "
                "WHERE enabled = 1 AND next_run_at <= ?",
                (now_ts,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def next_scheduled_review_at(self) -> str | None:
        """The SOONEST enabled scheduled-review ``next_run_at`` (a past value means
        already due; a future value is the next time something becomes due), or
        None when nothing is scheduled. Backs the TUI review-sweep countdown."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(next_run_at) AS soonest FROM scheduled_reviews "
                "WHERE enabled = 1 AND next_run_at IS NOT NULL",
            ).fetchone()
        return (row["soonest"] if row else None) or None

    def mark_question_review_due(self, question_id: str, *, now: str | None = None) -> dict[str, Any]:
        """Re-arm a question's review to fire on the next cron tick — the desk's
        "run update" shortcut. Sets the enabled per-question schedule's next_run_at
        to now; if no schedule row exists, creates one at the question's cadence
        (default weekly). The autonomous cycle then reforecasts it on its next tick."""
        when = now or utc_now_iso()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE scheduled_reviews SET next_run_at = ? "
                "WHERE scope_type = 'question' AND scope_ref = ? AND enabled = 1",
                (when, question_id),
            )
            rearmed = cur.rowcount
        if rearmed:
            return {"next_run_at": when, "queued": True, "scheduled": "rearmed"}
        cadence = "weekly"
        try:
            question = self.get_question(question_id)
            cadence = question.review_cadence or "weekly"
        except Exception:
            pass
        self.schedule_review(
            scope_type="question", scope_ref=question_id, cadence=cadence,
            next_run_at=when, trigger_reason="manual",
        )
        return {"next_run_at": when, "queued": True, "scheduled": "created"}

    def dedupe_scheduled_reviews(self) -> dict[str, Any]:
        """Collapse pre-existing duplicate ENABLED schedules that share
        (scope_type, scope_ref, cadence, trigger_reason). Keeps the most-established
        one — the one that has run most recently, else the soonest next_run_at —
        and disables the rest (so its run history is preserved, not deleted).
        Idempotent: a deduped ledger is a no-op. Pairs with the idempotency guard
        in schedule_review() which prevents NEW duplicates."""
        groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
        for review in self.list_scheduled_reviews():
            if not review.get("enabled"):
                continue
            key = (review["scope_type"], review["scope_ref"], review["cadence"], review["trigger_reason"])
            groups.setdefault(key, []).append(review)

        disabled: list[str] = []
        kept: list[str] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            ran = [m for m in members if m.get("last_run_at")]
            keep = (
                max(ran, key=lambda m: (m["last_run_at"], m["id"]))
                if ran
                else min(members, key=lambda m: (m.get("next_run_at") or "", m["id"]))
            )
            kept.append(keep["id"])
            with self._connect() as conn:
                for member in members:
                    if member["id"] != keep["id"]:
                        conn.execute("UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?", (member["id"],))
                        disabled.append(member["id"])

        return {
            "groups_collapsed": len(kept),
            "kept": kept,
            "disabled": disabled,
            "disabled_count": len(disabled),
        }

    def list_scheduled_review_runs(
        self,
        *,
        scheduled_review_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        limit = max(int(limit), 1)
        clauses: list[str] = []
        params: list[Any] = []
        if scheduled_review_id:
            clauses.append("scheduled_review_id = ?")
            params.append(scheduled_review_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM scheduled_review_runs
                {where}
                ORDER BY run_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_scheduled_review_run(row) for row in rows]

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
        data = dict(row)
        data["metadata"] = json_loads(data.get("metadata"), {})
        return data

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
        """Record a typed edge between two forecasts. Idempotent on (from, to, type).

        `related` is symmetric (the endpoints are normalized so A-B == B-A);
        `component_of` is directed (from=child, to=parent).
        """

        self.get_question(from_question_id)
        self.get_question(to_question_id)
        if from_question_id == to_question_id:
            raise ValidationError("a forecast cannot link to itself")
        if link_type not in FORECAST_LINK_TYPES:
            raise ValidationError(
                f"link_type must be one of {', '.join(sorted(FORECAST_LINK_TYPES))}"
            )
        if link_type == "related" and from_question_id > to_question_id:
            from_question_id, to_question_id = to_question_id, from_question_id
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM forecast_links WHERE from_question_id = ? AND to_question_id = ? AND link_type = ?",
                (from_question_id, to_question_id, link_type),
            ).fetchone()
            if existing is not None:
                return self.get_forecast_link(existing["id"])
            link_id = f"fl_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO forecast_links (
                    id, from_question_id, to_question_id, link_type, weight,
                    rationale, created_by, created_at, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    link_id,
                    from_question_id,
                    to_question_id,
                    link_type,
                    float(weight),
                    rationale,
                    created_by,
                    utc_now_iso(),
                    json_dumps(metadata or {}),
                ),
            )
        return self.get_forecast_link(link_id)

    def get_forecast_link(self, link_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM forecast_links WHERE id = ?", (link_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast link not found: {link_id}")
        return self._forecast_link_to_dict(row)

    def remove_forecast_link(
        self,
        from_question_id: str,
        to_question_id: str,
        *,
        link_type: str | None = None,
    ) -> int:
        """Delete the edge(s) between two questions (either ordering). Returns the count."""

        sql = (
            "DELETE FROM forecast_links WHERE "
            "((from_question_id = ? AND to_question_id = ?) OR (from_question_id = ? AND to_question_id = ?))"
        )
        params: list[Any] = [from_question_id, to_question_id, to_question_id, from_question_id]
        if link_type is not None:
            sql += " AND link_type = ?"
            params.append(link_type)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.rowcount or 0)

    def list_forecast_links(
        self,
        question_id: str,
        *,
        link_type: str | None = None,
        direction: str = "both",
        status: str | None = None,  # accepted for signature parity; links have no status
    ) -> list[dict[str, Any]]:
        if direction == "outgoing":
            clause, params = "from_question_id = ?", [question_id]
        elif direction == "incoming":
            clause, params = "to_question_id = ?", [question_id]
        else:
            clause, params = "(from_question_id = ? OR to_question_id = ?)", [question_id, question_id]
        sql = f"SELECT * FROM forecast_links WHERE {clause}"
        if link_type is not None:
            sql += " AND link_type = ?"
            params.append(link_type)
        sql += " ORDER BY created_at DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._forecast_link_to_dict(row) for row in rows]

    def shared_sources(self, question_id: str, other_id: str) -> list[dict[str, Any]]:
        """Overlapping watched sources / evidence between two questions (read-only).

        Used purely to FLAG possible non-independence; never merges or imports.
        """

        def _signatures(qid: str) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for ws in self.list_watched_sources(scope_type="question", scope_ref=qid, status="active"):
                source = str(ws.get("source") or "").strip().lower()
                stype = str(ws.get("source_type") or "").strip().lower()
                if source:
                    out[f"{stype}:{source}"] = {"source_type": stype, "source": source, "kind": "watched_source"}
            for item in self.list_evidence(qid):
                stype = str(getattr(item, "source_type", "") or "").strip().lower()
                ident = str(getattr(item, "source_url", None) or getattr(item, "source_name", None) or "").strip().lower()
                if ident:
                    out.setdefault(f"{stype}:{ident}", {"source_type": stype, "source": ident, "kind": "evidence"})
            return out

        mine = _signatures(question_id)
        theirs = _signatures(other_id)
        shared: list[dict[str, Any]] = []
        for signature in mine.keys() & theirs.keys():
            shared.append({"signature": signature, "shared_with": other_id, **mine[signature]})
        shared.sort(key=lambda s: s["signature"])
        return shared

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
        """Resolve the forecasts related to `question` and pull their world-views.

        Unions explicit links with auto matches (same domain + topic Jaccard
        overlap). Each entry carries only the relative's current forecast, latest
        analyst-note view, and top drivers. Also returns the de-duplicated list of
        overlapping source signatures for the independence flag. Never merges
        evidence — world-views only.
        """

        if isinstance(question, str):
            question = self.get_question(question)
        question_id = question.id
        base_topics = {str(t).lower() for t in (question.topics or [])}

        # relationship from the perspective of `question`.
        relatives: dict[str, dict[str, Any]] = {}

        def _record(other_id: str, *, relationship: str, link_type: str, overlap: float,
                    link_id: str | None = None, rationale: str = "") -> None:
            if other_id == question_id or other_id in relatives:
                return
            relatives[other_id] = {
                "id": other_id,
                "relationship": relationship,
                "link_type": link_type,
                "link_label": link_type if link_type != "auto" else None,
                "direction": "auto" if link_type == "auto" else "explicit",
                "overlap_score": round(overlap, 3),
                "link_id": link_id,
                "rationale": rationale,
            }

        for link in self.list_forecast_links(question_id, direction="both"):
            outgoing = link["from_question_id"] == question_id
            other_id = link["to_question_id"] if outgoing else link["from_question_id"]
            if link["link_type"] == "component_of":
                # from=child, to=parent. If we are `from`, the other is our parent.
                relationship = "parent" if outgoing else "child"
            else:
                relationship = "correlated_sibling"
            _record(
                other_id,
                relationship=relationship,
                link_type=link["link_type"],
                overlap=1.0,
                link_id=link["id"],
                rationale=link.get("rationale", ""),
            )

        explicit_ids = set(relatives.keys())
        if question.domain and base_topics:
            for candidate in self.list_questions(domain=question.domain):
                if candidate.id == question_id or candidate.id in explicit_ids:
                    continue
                other_topics = {str(t).lower() for t in (candidate.topics or [])}
                union = base_topics | other_topics
                jaccard = len(base_topics & other_topics) / len(union) if union else 0.0
                if jaccard >= overlap_threshold:
                    _record(candidate.id, relationship="correlated_sibling", link_type="auto", overlap=jaccard)

        # Explicit first, then auto by overlap; truncate.
        ordered = sorted(
            relatives.values(),
            key=lambda r: (r["link_type"] == "auto", -r["overlap_score"]),
        )[: max(0, limit)]

        shared_labels: list[str] = []
        seen_labels: set[str] = set()
        for rel in ordered:
            other_id = rel["id"]
            try:
                other_q = self.get_question(other_id)
                rel["title"] = other_q.title
            except LedgerNotFoundError:
                rel["title"] = other_id
            snap = self.get_current_snapshot(other_id)
            rel["probability_or_distribution"] = snap.probability_or_distribution if snap else None
            rel["as_of"] = snap.as_of if snap else None
            rel["reasons_up"] = list(snap.reasons_up or [])[:3] if snap else []
            rel["reasons_down"] = list(snap.reasons_down or [])[:3] if snap else []
            note = self.latest_analyst_note(other_id)
            rel["headline"] = note.get("headline") if note else None
            rel["be_aware"] = note.get("be_aware") if note else None
            rel["stance"] = note.get("stance") if note else None
            rel["verdict"] = note.get("verdict") if note else None
            for shared in self.shared_sources(question_id, other_id):
                if shared["signature"] not in seen_labels:
                    seen_labels.add(shared["signature"])
                    shared_labels.append(shared["signature"])

        return ordered, shared_labels

    def build_cross_refs(self, question: Any, *, advisory_only: bool = False) -> dict[str, Any]:
        """The provenance record stamped onto a snapshot: which related forecasts
        informed it (server-side, never trusting model echo). Empty when there are
        no relatives. ``advisory_only`` marks the deterministic-refresh case where
        the number is NOT derived from siblings."""

        related, shared = self.related_forecast_views(question, limit=5)
        if not related and not shared:
            return {}
        return {
            "informed_by": [rel["id"] for rel in related],
            "explicit_links": [rel["id"] for rel in related if rel.get("link_type") != "auto"],
            "auto_related": [rel["id"] for rel in related if rel.get("link_type") == "auto"],
            "shared_sources": [{"source": s, "note": "may not be independent"} for s in shared],
            "as_of": utc_now_iso(),
            "advisory_only": bool(advisory_only),
        }

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
        """True when ``question`` (object or id) is a thesis question."""

        if isinstance(question, str):
            try:
                question = self.get_question(question)
            except LedgerNotFoundError:
                return False
        return getattr(question.outcome_space, "type", None) == "thesis"

    def is_factor(self, question: Any) -> bool:
        """True when ``question`` is a FACTOR — a thesis whose members are a
        weighted basket of return distributions aggregated by portfolio math
        (mean/vol/downside) rather than the health-signal pool. Marked by
        ``metadata['aggregation'] == 'factor'`` so it reuses the thesis
        membership table, run-all, and cron wholesale."""

        if isinstance(question, str):
            try:
                question = self.get_question(question)
            except LedgerNotFoundError:
                return False
        if not self.is_thesis(question):
            return False
        meta = question.metadata if isinstance(question.metadata, dict) else {}
        return str(meta.get("aggregation") or "").lower() == "factor"

    def _thesis_member_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json_loads(data.get("metadata"), {})
        data["hi_is_good"] = bool(data.get("hi_is_good", 1))
        return data

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
        """Tag ``member_id`` to the thesis ``thesis_id``. Upsert on (thesis, member)."""

        thesis = self.get_question(thesis_id)
        self.get_question(member_id)
        if not self.is_thesis(thesis):
            raise ValidationError("thesis_id must reference a question with outcome type 'thesis'")
        if thesis_id == member_id:
            raise ValidationError("a thesis cannot be a member of itself")
        if direction not in {"support", "inverted"}:
            raise ValidationError("direction must be 'support' or 'inverted'")
        if role is not None and role.strip() and role not in THESIS_MEMBER_ROLES:
            raise ValidationError("role must be one of: " + ", ".join(sorted(THESIS_MEMBER_ROLES)))
        if weight < 0:
            raise ValidationError("weight must be non-negative")
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM thesis_members WHERE thesis_question_id = ? AND member_question_id = ?",
                (thesis_id, member_id),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """
                    UPDATE thesis_members SET direction = ?, weight = ?, role = ?, target = ?,
                        hi_is_good = ?, max_age_days = ?, rationale = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (
                        direction,
                        float(weight),
                        role,
                        target,
                        1 if hi_is_good else 0,
                        max_age_days,
                        rationale,
                        json_dumps(metadata or {}),
                        existing["id"],
                    ),
                )
                member_pk = existing["id"]
            else:
                member_pk = f"tm_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO thesis_members (
                        id, thesis_question_id, member_question_id, direction, weight,
                        role, target, hi_is_good, max_age_days, rationale, created_by,
                        created_at, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        member_pk,
                        thesis_id,
                        member_id,
                        direction,
                        float(weight),
                        role,
                        target,
                        1 if hi_is_good else 0,
                        max_age_days,
                        rationale,
                        created_by,
                        utc_now_iso(),
                        json_dumps(metadata or {}),
                    ),
                )
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM thesis_members WHERE id = ?", (member_pk,)).fetchone()
        return self._thesis_member_to_dict(row)

    def remove_thesis_member(self, thesis_id: str, member_id: str) -> int:
        """Untag a member from a thesis. Returns the number of rows removed."""

        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM thesis_members WHERE thesis_question_id = ? AND member_question_id = ?",
                (thesis_id, member_id),
            )
            return int(cur.rowcount or 0)

    def list_thesis_members(self, thesis_id: str) -> list[dict[str, Any]]:
        """Members of a thesis, joined with each member's title + outcome type."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tm.*, q.title AS member_title, q.outcome_space AS member_outcome_space,
                       q.status AS member_status
                FROM thesis_members tm
                JOIN forecast_questions q ON q.id = tm.member_question_id
                WHERE tm.thesis_question_id = ?
                ORDER BY tm.weight DESC, tm.created_at ASC
                """,
                (thesis_id,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            data = self._thesis_member_to_dict(row)
            data["member_outcome_type"] = OutcomeSpace.from_json(data.pop("member_outcome_space", None)).type
            out.append(data)
        return out

    def list_theses_for_member(self, member_id: str) -> list[dict[str, Any]]:
        """The theses a member belongs to (for the 'member of …' badge)."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tm.thesis_question_id AS thesis_id, tm.direction, tm.weight, tm.role,
                       q.title AS thesis_title
                FROM thesis_members tm
                JOIN forecast_questions q ON q.id = tm.thesis_question_id
                WHERE tm.member_question_id = ?
                ORDER BY q.title ASC
                """,
                (member_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def theses_by_member(self, member_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """member_id -> theses it belongs to (batched ``list_theses_for_member``).

        Collapses the per-member N+1 the desk's workspace payload used to fire
        (one ``list_theses_for_member`` connection per member question) into a
        single chunked query, mirroring ``snapshots_by_question`` /
        ``evidence_by_question``. Each absent member defaults to ``[]`` — the
        exact value the singular method produces for a non-member."""
        out: dict[str, list[dict[str, Any]]] = {}
        for chunk in self._chunk_ids(member_ids):
            if not chunk:
                continue
            placeholders = ",".join("?" for _ in chunk)
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT tm.member_question_id AS member_id,
                           tm.thesis_question_id AS thesis_id, tm.direction, tm.weight, tm.role,
                           q.title AS thesis_title
                    FROM thesis_members tm
                    JOIN forecast_questions q ON q.id = tm.thesis_question_id
                    WHERE tm.member_question_id IN ({placeholders})
                    ORDER BY tm.member_question_id ASC, q.title ASC
                    """,
                    chunk,
                ).fetchall()
            for row in rows:
                data = dict(row)
                mid = data.pop("member_id")
                out.setdefault(mid, []).append(data)
        return out

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
        """Resolve one question's current belief into the input dict that
        :func:`forecasting.thesis.aggregate_thesis` consumes. Shared by thesis
        membership AND per-entity weight vectors (the suitability layer reuses
        the exact same 0..1-signal reduction, just with a different weight set)."""

        # Lazy import: dashboard imports the ledger, so importing it at module
        # scope would be circular.
        from forecasting.dashboard import _distribution_view

        if outcome_type is None or title is None:
            try:
                question = self.get_question(member_id)
                outcome_type = outcome_type or question.outcome_space.type
                title = title or question.title
            except LedgerNotFoundError:
                outcome_type = outcome_type or "binary"
        snapshot = self.get_current_snapshot(member_id)
        belief = snapshot.probability_or_distribution if snapshot else None
        record: dict[str, Any] = {
            "member_id": member_id,
            "title": title,
            "direction": direction,
            "weight": float(weight),
            "as_of": snapshot.as_of if snapshot else None,
            "max_age_days": max_age_days,
            "target": target,
            "hi_is_good": bool(hi_is_good),
            "probability": None,
            "dist": None,
        }
        if belief is None:
            record["kind"] = "binary"  # unusable -> flagged missing downstream
        elif outcome_type == "binary" and isinstance(belief, (int, float)):
            record["kind"] = "binary"
            record["probability"] = float(belief)
        elif isinstance(belief, dict):
            record["kind"] = "distribution"
            record["dist"] = _distribution_view(belief) or {"mean": None}
        elif isinstance(belief, (int, float)):
            record["kind"] = "distribution"
            record["dist"] = {"mean": float(belief)}
        else:
            record["kind"] = "binary"  # unrecognized -> unusable
        return record

    def _thesis_member_belief(self, member: dict[str, Any]) -> dict[str, Any]:
        """Resolve a membership row into the input dict that thesis.aggregate_thesis wants."""

        return self._belief_record(
            member["member_question_id"],
            direction=member.get("direction", "support"),
            weight=float(member.get("weight", 1.0)),
            target=member.get("target"),
            hi_is_good=bool(member.get("hi_is_good", True)),
            max_age_days=member.get("max_age_days"),
            title=member.get("member_title"),
            outcome_type=member.get("member_outcome_type") or "binary",
        )

    # ── Thesis entities (per-name suitability + trade triggers) ─────────────
    #
    # An entity — a stock, a candidate, a currency, a sector, anything the
    # thesis's signals map onto — carries its OWN weighted vector over the
    # thesis members. Its "suitability" is the same 0..1 aggregate as the
    # thesis, just with the entity's weights + direction, so the §22/§10 rule
    # ("if power-bottleneck prob rises -> BE/IREN/CORZ better suited") falls out
    # generically for ANY thesis (elections, FX, manufacturing, ...).

    def _thesis_entity_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["weights"] = json_loads(data.get("weights"), [])
        data["metadata"] = json_loads(data.get("metadata"), {})
        return data

    def _normalize_entity_weights(self, weights: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for weight in weights or []:
            if not isinstance(weight, dict):
                raise ValidationError("entity weight must be an object")
            member_id = str(weight.get("member_id") or "").strip()
            if not member_id:
                raise ValidationError("entity weight requires a member_id")
            self.get_question(member_id)  # must reference a real question
            direction = str(weight.get("direction") or "support")
            if direction not in {"support", "inverted"}:
                raise ValidationError("entity weight direction must be 'support' or 'inverted'")
            value = float(weight.get("weight", 1.0))
            if value < 0:
                raise ValidationError("entity weight must be non-negative")
            entry: dict[str, Any] = {"member_id": member_id, "weight": value, "direction": direction}
            if weight.get("role"):
                entry["role"] = str(weight["role"])
            if weight.get("hi_is_good") is not None:
                entry["hi_is_good"] = bool(weight["hi_is_good"])
            if weight.get("target") is not None:
                entry["target"] = float(weight["target"])
            out.append(entry)
        return out

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
        """Register an entity under a thesis with a weighted signal vector. Upsert on (thesis, name)."""

        thesis = self.get_question(thesis_id)
        if not self.is_thesis(thesis):
            raise ValidationError("thesis_id must reference a question with outcome type 'thesis'")
        name = (name or "").strip()
        if not name:
            raise ValidationError("entity name is required")
        normalized = self._normalize_entity_weights(weights)
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM thesis_entities WHERE thesis_question_id = ? AND name = ?",
                (thesis_id, name),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    "UPDATE thesis_entities SET label = ?, kind = ?, weights = ?, action_threshold = ?, metadata = ? WHERE id = ?",
                    (label, kind, json_dumps(normalized), action_threshold, json_dumps(metadata or {}), existing["id"]),
                )
                entity_id = existing["id"]
            else:
                entity_id = f"te_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO thesis_entities (
                        id, thesis_question_id, name, label, kind, weights,
                        action_threshold, created_by, created_at, metadata
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entity_id,
                        thesis_id,
                        name,
                        label,
                        kind,
                        json_dumps(normalized),
                        action_threshold,
                        created_by,
                        utc_now_iso(),
                        json_dumps(metadata or {}),
                    ),
                )
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM thesis_entities WHERE id = ?", (entity_id,)).fetchone()
        return self._thesis_entity_to_dict(row)

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
        """Add/replace a single signal weight on an entity (creates the entity if new)."""

        entities = {e["name"]: e for e in self.list_thesis_entities(thesis_id)}
        existing = entities.get(name)
        kept = [w for w in (existing["weights"] if existing else []) if w.get("member_id") != member_id]
        entry: dict[str, Any] = {"member_id": member_id, "weight": float(weight), "direction": direction}
        if role:
            entry["role"] = role
        entry["hi_is_good"] = bool(hi_is_good)
        if target is not None:
            entry["target"] = float(target)
        kept.append(entry)
        return self.add_thesis_entity(
            thesis_id,
            name,
            label=(existing.get("label") if existing else None),
            kind=(existing.get("kind") if existing else "entity"),
            weights=kept,
            action_threshold=(existing.get("action_threshold") if existing else None),
            metadata=(existing.get("metadata") if existing else None),
        )

    def remove_thesis_entity(self, thesis_id: str, name: str) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM thesis_entities WHERE thesis_question_id = ? AND name = ?",
                (thesis_id, name),
            )
            return int(cur.rowcount or 0)

    def list_thesis_entities(self, thesis_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM thesis_entities WHERE thesis_question_id = ? ORDER BY name ASC",
                (thesis_id,),
            ).fetchall()
        return [self._thesis_entity_to_dict(row) for row in rows]

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
        """Per-entity suitability (reusing the thesis aggregator) + trade triggers."""

        from forecasting import thesis as thesis_math

        entities = self.list_thesis_entities(thesis_id)
        if not entities:
            return [], []

        prev_suit = {e.get("name"): e.get("suitability") for e in (prev_entities or [])}
        out: list[dict[str, Any]] = []
        for entity in entities:
            records = []
            for weight in entity.get("weights", []):
                member_id = weight["member_id"]
                member = member_map.get(member_id, {})
                records.append(
                    self._belief_record(
                        member_id,
                        direction=weight.get("direction", "support"),
                        weight=float(weight.get("weight", 1.0)),
                        target=weight["target"] if "target" in weight else member.get("target"),
                        hi_is_good=weight["hi_is_good"]
                        if "hi_is_good" in weight
                        else bool(member.get("hi_is_good", True)),
                        max_age_days=member.get("max_age_days"),
                        title=member.get("member_title"),
                        outcome_type=member.get("member_outcome_type"),
                    )
                )
            agg = thesis_math.aggregate_thesis(records, rho=rho, now=now)
            suitability = agg.health
            previous = prev_suit.get(entity["name"])
            delta = (
                suitability - previous
                if (suitability is not None and isinstance(previous, (int, float)))
                else None
            )
            stance, trend = _entity_stance(suitability, delta, entity.get("action_threshold"))
            usable = [c for c in agg.components if c.get("status") not in _THESIS_DEAD_STATUS]
            top = max(usable, key=lambda c: abs(c.get("contribution_pts") or 0), default=None)
            out.append(
                {
                    "name": entity["name"],
                    "label": entity.get("label") or entity["name"],
                    "kind": entity.get("kind", "entity"),
                    "suitability": suitability,
                    "suitability_display": f"{suitability:.0%}" if suitability is not None else "—",
                    "score": agg.thesis_score,
                    "band": list(agg.band) if agg.band else None,
                    "coverage": agg.coverage,
                    "n_eff": agg.n_eff,
                    "delta": delta,
                    "stance": stance,
                    "trend": trend,
                    "action": f"{stance} ({trend})" if suitability is not None else "withheld",
                    "top_driver": top.get("title") if top else None,
                    "top_driver_id": top.get("member_id") if top else None,
                    "weight_count": len(entity.get("weights", [])),
                    "contributions": agg.components,
                }
            )

        # Trade triggers: member-signal moves since the prior aggregation, mapped
        # through each entity's weight vector to "better/less suited" lines.
        cur_sig = {c.get("member_id"): c.get("s_raw") for c in current_components}
        prev_sig = {c.get("member_id"): c.get("s_raw") for c in (prev_components or [])}
        member_deltas: dict[str, float] = {}
        for member_id, signal in cur_sig.items():
            previous_signal = prev_sig.get(member_id)
            if isinstance(signal, (int, float)) and isinstance(previous_signal, (int, float)):
                member_deltas[member_id] = signal - previous_signal
        triggers = _thesis_entity_triggers(member_deltas, entities, member_map)
        return out, triggers

    def _aggregate_factor(
        self,
        factor: Any,
        *,
        rho: float | str,
        now: str | None,
        commit: bool,
        analyst_note: bool = True,
    ) -> dict[str, Any]:
        """Portfolio-aggregate a factor's constituent return distributions."""

        from forecasting import factor as factor_math
        from forecasting.dashboard import _distribution_view

        members = self.list_thesis_members(factor.id)
        as_of = now or utc_now_iso()
        constituents: list[dict[str, Any]] = []
        for member in members:
            member_id = member["member_question_id"]
            snapshot = self.get_current_snapshot(member_id)
            belief = snapshot.probability_or_distribution if snapshot else None
            mean: float | None = None
            sd: float | None = None
            if isinstance(belief, dict):
                view = _distribution_view(belief) or {}
                mean = view.get("mean")
                sd = view.get("sd")
            elif isinstance(belief, (int, float)):
                mean = float(belief)
            constituents.append(
                {
                    "member_id": member_id,
                    "title": member.get("member_title"),
                    "weight": float(member.get("weight", 1.0)),
                    "direction": "short" if member.get("direction") == "inverted" else "long",
                    "as_of": snapshot.as_of if snapshot else None,
                    "max_age_days": member.get("max_age_days"),
                    "mean": mean,
                    "sd": sd,
                }
            )
        agg = factor_math.aggregate_factor(constituents, rho=rho, now=as_of)
        payload = agg.to_payload()
        result: dict[str, Any] = {
            "thesis_id": factor.id,
            "title": factor.title,
            "aggregate": agg,
            "payload": payload,
            "member_count": len(members),
            "is_factor": True,
            "entities": [],
            "triggers": [],
            "snapshot_id": None,
        }
        if not commit:
            return result
        if payload.get("factor_mean") is None:
            if analyst_note:
                note = self.add_analyst_note(
                    question_id=factor.id,
                    body="; ".join(agg.notes) or "withheld: no usable constituent",
                    kind="brief",
                    headline=f"{factor.title} — withheld (insufficient fresh constituents)",
                    be_aware="; ".join(agg.notes),
                    generator="factor_aggregate",
                    metadata={"coverage": agg.coverage, "member_count": len(members)},
                )
                result["analyst_note_id"] = note.get("id")
            return result
        rationale = (
            f"Portfolio aggregate of {len(members)} constituent return distribution(s) "
            f"(coverage {agg.coverage:.0%}, vol {agg.sd:.3f}, n_eff {agg.n_eff:.1f}, rho {agg.rho:.2f}). "
            "Computed after the constituents' latest runs; not LLM-led."
        )
        snapshot = self.create_snapshot(
            question_id=factor.id,
            probability_or_distribution=payload,
            rationale=rationale,
            as_of=as_of,
            confidence=round(max(0.0, min(1.0, agg.coverage)), 3),
            method="factor_aggregate",
            style_autofix=True,  # deterministic fold: mechanically clean generated prose
            distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
            ensemble_components={
                "components": agg.components,
                "rho": agg.rho,
                "n_eff": agg.n_eff,
                "coverage": agg.coverage,
            },
            forecast_origin="live",
            calibration_eligible=False,
            metadata={"factor_notes": agg.notes, "aggregation": "factor"},
        )
        result["snapshot_id"] = snapshot.forecast_id
        if analyst_note:
            headline, how_it_thinks, looking_for, be_aware, body = _factor_narrative(factor, agg)
            note = self.add_analyst_note(
                question_id=factor.id,
                body=body,
                kind="brief",
                headline=headline,
                how_it_thinks=how_it_thinks,
                looking_for=looking_for,
                be_aware=be_aware,
                forecast_id=snapshot.forecast_id,
                probability_at_write=payload,
                confidence_at_write=round(max(0.0, min(1.0, agg.coverage)), 3),
                generator="factor_aggregate",
                metadata={"coverage": agg.coverage, "n_eff": agg.n_eff, "rho": agg.rho},
            )
            result["analyst_note_id"] = note.get("id")
        return result

    def set_thesis_correlation(self, thesis_id: str, member_a: str, member_b: str, rho: float) -> dict[str, float]:
        """Pin a pairwise correlation between two thesis members so the aggregate's
        honest band + effective-N use real co-movement PER PAIR rather than one
        scalar rho (members co-move unequally). Stored on the thesis metadata;
        both ids must be members. Idempotent on the unordered pair. Returns the
        full correlation map."""
        thesis = self.get_question(thesis_id)
        if not self.is_thesis(thesis):
            raise ValidationError("set_thesis_correlation requires a question with outcome type 'thesis'")
        if member_a == member_b:
            raise ValidationError("a member cannot be correlated with itself")
        if "|" in member_a or "|" in member_b:
            # The pair is stored as "a|b"; a literal '|' in an id would corrupt the
            # key. System ids never contain it, but reject loudly rather than silently
            # dropping the correlation at load time.
            raise ValidationError("member ids must not contain '|'")
        member_ids = {m["member_question_id"] for m in self.list_thesis_members(thesis_id)}
        for mid in (member_a, member_b):
            if mid not in member_ids:
                raise ValidationError(f"{mid} is not a member of this thesis")
        rho_val = float(rho)
        if not (0.0 <= rho_val <= 0.95):
            raise ValidationError("correlation must be within [0, 0.95]")
        meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
        corr = dict(meta.get("thesis_correlations") or {})
        corr["|".join(sorted([member_a, member_b]))] = rho_val
        meta["thesis_correlations"] = corr
        with self._connect() as conn:
            conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
        return corr

    def _thesis_correlation_matrix(self, thesis: Any) -> dict[frozenset[str], float] | None:
        """Load the stored pairwise correlations into the {member_a, member_b} ->
        rho map the aggregation math consumes. None when none are pinned."""
        meta = thesis.metadata if isinstance(thesis.metadata, dict) else {}
        raw = meta.get("thesis_correlations")
        if not isinstance(raw, dict) or not raw:
            return None
        out: dict[frozenset[str], float] = {}
        for key, value in raw.items():
            parts = str(key).split("|")
            if len(parts) == 2:
                try:
                    out[frozenset(parts)] = float(value)
                except (TypeError, ValueError):
                    continue
        return out or None

    def set_thesis_event(
        self,
        thesis_id: str,
        *,
        kind: str = "count_threshold",
        threshold: int | None = None,
    ) -> dict[str, Any]:
        """Configure a thesis as a JOINT THRESHOLD EVENT — P(#member successes ≥ K).

        A thesis headline is otherwise a mean index (damped, threshold-insensitive).
        With an event spec, ``aggregate_thesis`` ALSO runs a Gaussian-copula Monte
        Carlo (seeded deterministically) and stamps ``event_probability`` — the way
        a "Democrats take back the Senate" question is really scored. Stored on the
        thesis metadata beside ``thesis_correlations``; pass ``threshold=None`` (any
        kind) to CLEAR it. Returns the stored spec.
        """
        thesis = self.get_question(thesis_id)
        if not self.is_thesis(thesis):
            raise ValidationError("set_thesis_event requires a question with outcome type 'thesis'")
        kind = str(kind).lower()
        if kind not in {"count_threshold", "all", "any"}:
            raise ValidationError("event kind must be 'count_threshold', 'all' or 'any'")
        spec: dict[str, Any] | None
        if kind == "count_threshold":
            if threshold is None:
                raise ValidationError("count_threshold event requires an integer 'threshold'")
            k = int(threshold)
            if k < 0:
                raise ValidationError("threshold must be non-negative")
            spec = {"kind": kind, "threshold": k}
        else:
            spec = {"kind": kind}
        meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
        meta["thesis_event"] = spec
        with self._connect() as conn:
            conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
        return spec

    def clear_thesis_event(self, thesis_id: str) -> bool:
        """Remove a thesis's event spec (reverts to the mean-index headline). True if one was set."""
        thesis = self.get_question(thesis_id)
        if not self.is_thesis(thesis):
            raise ValidationError("clear_thesis_event requires a question with outcome type 'thesis'")
        meta = dict(thesis.metadata) if isinstance(thesis.metadata, dict) else {}
        had = meta.pop("thesis_event", None) is not None
        if had:
            with self._connect() as conn:
                conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), thesis_id))
        return had

    def _thesis_event_spec(self, thesis: Any) -> dict[str, Any] | None:
        """Load the stored event spec ({kind, threshold?}) the MC consumes, or None."""
        meta = thesis.metadata if isinstance(thesis.metadata, dict) else {}
        raw = meta.get("thesis_event")
        if not isinstance(raw, dict):
            return None
        kind = str(raw.get("kind", "")).lower()
        if kind not in {"count_threshold", "all", "any"}:
            return None
        spec: dict[str, Any] = {"kind": kind}
        if kind == "count_threshold":
            try:
                spec["threshold"] = int(raw.get("threshold"))
            except (TypeError, ValueError):
                return None
        return spec

    @staticmethod
    def _thesis_event_seed(thesis_id: str, as_of: str | None) -> int:
        """Deterministic MC seed from (thesis_id, as_of) — no Date.now / global RNG."""
        digest = hashlib.sha256(f"{thesis_id}|{as_of or ''}".encode("utf-8")).hexdigest()
        return int(digest[:16], 16)

    def aggregate_thesis(
        self,
        thesis_id: str,
        *,
        rho: float | str = 0.4,
        now: str | None = None,
        commit: bool = True,
        analyst_note: bool = True,
    ) -> dict[str, Any]:
        """Deterministically aggregate a thesis's members into a fresh snapshot.

        Reads each member's CURRENT snapshot (so callers must run the members
        first — the thesis lags them), folds the beliefs via
        :func:`forecasting.thesis.aggregate_thesis`, and (when ``commit``)
        writes a thesis snapshot + a rolling analyst note.
        """

        from forecasting import thesis as thesis_math

        thesis = self.get_question(thesis_id)
        if not self.is_thesis(thesis):
            raise ValidationError("aggregate_thesis requires a question with outcome type 'thesis'")
        if self.is_factor(thesis):
            # A factor aggregates a weighted basket of return distributions via
            # portfolio math, not the health-signal pool.
            return self._aggregate_factor(thesis, rho=rho, now=now, commit=commit, analyst_note=analyst_note)
        members = self.list_thesis_members(thesis_id)
        beliefs = [self._thesis_member_belief(m) for m in members]
        as_of = now or utc_now_iso()
        correlation = self._thesis_correlation_matrix(thesis)
        agg = thesis_math.aggregate_thesis(
            beliefs, rho=rho, now=as_of,
            correlation_matrix=correlation,
        )

        # ── Event-probability layer ─────────────────────────────────────────
        # When the thesis is configured as a JOINT THRESHOLD EVENT (e.g. "Dems
        # take back the Senate" = P(#seats ≥ K)), run a Gaussian-copula MC over
        # the SAME binary member beliefs. The mean index is damped and
        # threshold-insensitive; the event probability is the number the
        # question actually asks. Seeded deterministically from (thesis_id,
        # as_of) so re-aggregation is reproducible. Stamped ALONGSIDE the mean
        # index (health/score/band stay as diagnostics; nothing removed).
        event_spec = self._thesis_event_spec(thesis)
        event_result = None
        # The snapshot's probability_or_distribution is validated to a FLAT numeric
        # dict, so only the numeric event_probability rides in the payload (it is
        # the headline). The structured detail (spec / count distribution / per-
        # member sensitivities) is stamped into the snapshot metadata below.
        event_payload: dict[str, Any] = {}
        if event_spec is not None:
            event_result = thesis_math.simulate_thesis_event(
                beliefs, event_spec,
                rho=rho,
                correlation_matrix=correlation,
                seed=self._thesis_event_seed(thesis_id, as_of),
            )
            if event_result.event_probability is not None:
                event_payload = {"event_probability": event_result.event_probability}

        def _thesis_payload() -> dict[str, Any]:
            return {**agg.to_payload(), **event_payload}

        # Entity suitability + trade triggers. Read the PRIOR snapshot first
        # (get_current_snapshot returns the latest before the new commit) so the
        # per-entity deltas + signal-move triggers compare against it.
        previous = self.get_current_snapshot(thesis_id)
        prev_components: list[dict[str, Any]] = []
        prev_entities: list[dict[str, Any]] = []
        if previous is not None:
            prev_ensemble = previous.ensemble_components if isinstance(previous.ensemble_components, dict) else {}
            prev_components = prev_ensemble.get("components") or []
            prev_meta = previous.metadata if isinstance(previous.metadata, dict) else {}
            prev_entities = prev_meta.get("entities") or []
        member_map = {m["member_question_id"]: m for m in members}
        entities, triggers = self._compute_thesis_entities(
            thesis_id,
            rho=rho,
            now=as_of,
            member_map=member_map,
            current_components=agg.components,
            prev_components=prev_components,
            prev_entities=prev_entities,
        )

        result: dict[str, Any] = {
            "thesis_id": thesis_id,
            "title": thesis.title,
            "aggregate": agg,
            "payload": _thesis_payload(),
            "event": event_result,
            "member_count": len(members),
            "entities": entities,
            "triggers": triggers,
            "snapshot_id": None,
        }
        if not commit:
            return result

        payload = _thesis_payload()
        if payload.get("health") is None:
            # No usable member signal: do not fabricate a number. Record the
            # withholding as an analyst note and skip the snapshot.
            if analyst_note:
                note = self.add_analyst_note(
                    question_id=thesis_id,
                    body="; ".join(agg.notes) or "withheld: no usable member signal",
                    kind="brief",
                    headline=f"{thesis.title} — withheld (insufficient fresh members)",
                    be_aware="; ".join(agg.notes),
                    generator="thesis_aggregate",
                    metadata={"coverage": agg.coverage, "member_count": len(members)},
                )
                result["analyst_note_id"] = note.get("id")
            return result

        rationale = (
            f"Deterministic aggregate of {len(members)} member forecast(s) "
            f"(coverage {agg.coverage:.0%}, n_eff {agg.n_eff:.1f}, rho {agg.rho:.2f}). "
            "Computed after the members' latest runs; not LLM-led."
        )
        snapshot = self.create_snapshot(
            question_id=thesis_id,
            probability_or_distribution=payload,
            rationale=rationale,
            as_of=as_of,
            confidence=round(max(0.0, min(1.0, agg.coverage)), 3),
            method="thesis_aggregate",
            style_autofix=True,  # deterministic fold: mechanically clean generated prose
            distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
            ensemble_components={
                "components": agg.components,
                "rho": agg.rho,
                "n_eff": agg.n_eff,
                "coverage": agg.coverage,
                "spread": agg.spread,
            },
            forecast_origin="live",
            calibration_eligible=False,
            metadata={
                "thesis_notes": agg.notes + ((event_result.notes if event_result else [])),
                "thesis_spread": agg.spread,
                "entities": entities,
                "triggers": triggers,
                # Full event read (count distribution + per-member sensitivities +
                # excluded members) for the desk; the compact headline fields live
                # in the snapshot payload alongside the mean index.
                "event": {
                    "event_probability": event_result.event_probability,
                    "event": event_result.event,
                    "count_distribution": event_result.count_distribution,
                    "sensitivities": event_result.sensitivities,
                    "excluded": event_result.excluded,
                    "participants": event_result.participants,
                    "backend": event_result.backend,
                    "n_draws": event_result.n_draws,
                    "rho": event_result.rho,
                    "seed": event_result.seed,
                } if (event_result and event_result.event_probability is not None) else None,
            },
            reasons_up=_thesis_reason_lines(agg, "support"),
            reasons_down=_thesis_reason_lines(agg, "drag"),
        )
        result["snapshot_id"] = snapshot.forecast_id
        if analyst_note:
            headline, how_it_thinks, looking_for, be_aware, body = _thesis_narrative(thesis, agg, event_result)
            note = self.add_analyst_note(
                question_id=thesis_id,
                body=body,
                kind="brief",
                headline=headline,
                how_it_thinks=how_it_thinks,
                looking_for=looking_for,
                be_aware=be_aware,
                forecast_id=snapshot.forecast_id,
                probability_at_write=payload,
                confidence_at_write=round(max(0.0, min(1.0, agg.coverage)), 3),
                generator="thesis_aggregate",
                metadata={"coverage": agg.coverage, "n_eff": agg.n_eff, "rho": agg.rho},
            )
            result["analyst_note_id"] = note.get("id")
        return result

    def aggregate_all_theses(
        self,
        *,
        now: str | None = None,
        rho: float | str = 0.4,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Aggregate every active thesis (the trailing lag phase of a sweep).

        Runs nested theses last (a thesis whose members include another thesis
        re-aggregates after that member). Used by ``run-all`` Phase 2 and the
        daily cron so theses + their entity suitabilities refresh after the
        members. Each thesis is isolated: one failing thesis does not abort the rest.
        """

        now = now or utc_now_iso()
        theses = [q for q in self.list_questions(status="active", limit=limit) if self.is_thesis(q)]

        def _depends_on_thesis(thesis: Any) -> bool:
            return any(
                self.is_thesis(member["member_question_id"])
                for member in self.list_thesis_members(thesis.id)
            )

        ordered = [q for q in theses if not _depends_on_thesis(q)] + [q for q in theses if _depends_on_thesis(q)]
        results: list[dict[str, Any]] = []
        for thesis in ordered:
            try:
                result = self.aggregate_thesis(thesis.id, rho=rho, now=now)
                results.append(
                    {
                        "id": thesis.id,
                        "title": thesis.title,
                        "ok": True,
                        "snapshot_id": result.get("snapshot_id"),
                        "withheld": result.get("snapshot_id") is None,
                        "health": (result.get("payload") or {}).get("health"),
                        "entity_count": len(result.get("entities") or []),
                        "trigger_count": len(result.get("triggers") or []),
                    }
                )
            except Exception as exc:  # one bad thesis must not abort the sweep
                results.append({"id": thesis.id, "title": thesis.title, "ok": False, "error": str(exc)})
        return {"count": len(ordered), "results": results}

    def list_source_snapshots(
        self,
        *,
        question_id: str | None = None,
        watched_source_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if watched_source_id:
            clauses.append("watched_source_id = ?")
            params.append(watched_source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM source_snapshots
                {where}
                ORDER BY retrieved_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_source_snapshot(row) for row in rows]

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
        """Attach a structured resolution rule so the desk can PROPOSE a resolution
        from ingested source data instead of resolving by hand (feedback #9). The
        rule is the generic shape behind the earnings/benchmark/infrastructure
        resolvers: read ``field`` from a watched source in role ``source_role`` and
        compare it to ``threshold``. Validated up front so a bad rule is refused."""
        from forecasting.resolvers import RESOLVER_TYPES, validate_metric_threshold_rule

        question = self.get_question(question_id)
        if resolver not in RESOLVER_TYPES:
            raise ValidationError("resolver must be one of: " + ", ".join(sorted(RESOLVER_TYPES)))
        if source_role not in WATCH_SOURCE_ROLES:
            raise ValidationError("source_role must be one of: " + ", ".join(sorted(WATCH_SOURCE_ROLES)))
        rule = {
            "resolver": resolver,
            "field": str(field).strip(),
            "comparator": comparator,
            "threshold": float(threshold),
            "source_role": source_role,
        }
        issues = validate_metric_threshold_rule(rule)
        if issues:
            raise ValidationError("; ".join(issues))
        meta = dict(question.metadata) if isinstance(question.metadata, dict) else {}
        meta["resolution_rule"] = rule
        with self._connect() as conn:
            conn.execute("UPDATE forecast_questions SET metadata = ? WHERE id = ?", (json_dumps(meta), question_id))
        return rule

    def propose_resolution(self, question_id: str) -> dict[str, Any] | None:
        """Run the question's resolution rule against the latest ingested source
        value and return a PROPOSED resolution (never committed — the user confirms
        with ``forecast resolve``). None when the question has no rule. An
        undetermined proposal (no observed value yet) is returned, never fabricated."""
        from forecasting.resolvers import propose_metric_threshold

        question = self.get_question(question_id)
        meta = question.metadata if isinstance(question.metadata, dict) else {}
        rule = meta.get("resolution_rule")
        if not isinstance(rule, dict):
            return None
        if rule.get("resolver") != "metric_threshold":
            return None
        field = str(rule.get("field") or "")
        source_role = rule.get("source_role") or "resolver"
        observed: float | None = None
        source_ref: str | None = None
        watched = self.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
        for source in watched:
            if source.get("role") != source_role:
                continue
            snaps = self.list_source_snapshots(watched_source_id=source["id"], limit=1)
            if not snaps:
                continue
            parsed = snaps[0].get("parsed_values") or {}
            value = parsed.get(field)
            if isinstance(value, (int, float)):
                observed = float(value)
                source_ref = source["id"]
                break
        return propose_metric_threshold(
            question_id=question_id, rule=rule, observed_value=observed, source_ref=source_ref,
        ).to_dict()

    def propose_due_resolutions(self, *, dry_run: bool = False) -> list[dict[str, Any]]:
        """Autonomy layer for the resolver framework: run every ACTIVE question's
        resolution rule and raise a confirm-me alert for each that now yields a
        DETERMINABLE proposal — so the desk surfaces "this is ready to resolve, YES"
        on its own instead of waiting for the operator to check. Propose-only (the
        user confirms with ``forecast resolve``). Deduped against an existing open
        proposal alert per question so it never re-alerts every cycle. ``dry_run``
        previews without raising alerts."""
        open_alerts = self.list_alerts(unresolved_only=True)
        # Dedup is OUTCOME-AWARE: an open alert suppresses re-alerting only for the
        # SAME proposed outcome. If the data flips the proposal (e.g. NO -> YES) the
        # operator must see the new one, so (scope_ref, outcome) is the key, not the
        # question alone.
        already: set[tuple[str, str]] = set()
        for alert in open_alerts:
            reason = (alert.reason or "").lower()
            if alert.scope_type == "question" and "resolution proposed:" in reason:
                tail = reason.split("resolution proposed:", 1)[1].strip()
                outcome = "yes" if tail.startswith("yes") else ("no" if tail.startswith("no") else "")
                already.add((alert.scope_ref, outcome))
        results: list[dict[str, Any]] = []
        for question in self.list_questions(status="active"):
            meta = question.metadata if isinstance(question.metadata, dict) else {}
            if not isinstance(meta.get("resolution_rule"), dict):
                continue
            proposal = self.propose_resolution(question.id)
            if not proposal or not proposal.get("determinable"):
                continue
            if (question.id, proposal["outcome"]) in already:
                results.append({"question_id": question.id, "outcome": proposal["outcome"], "alerted": False, "skipped": "open_alert"})
                continue
            alert_id = None
            if not dry_run:
                alert = self.create_alert(
                    severity="warning",
                    scope_type="question",
                    scope_ref=question.id,
                    reason=f"resolution proposed: {str(proposal['outcome']).upper()} — {proposal['rationale']}",
                    recommended_action=f"confirm with: forecast resolve {question.id} --outcome {proposal['outcome']}",
                )
                alert_id = alert.id
            results.append({"question_id": question.id, "outcome": proposal["outcome"], "alerted": not dry_run, "alert_id": alert_id})
        return results

    def autopilot_readiness(
        self,
        question_id: str,
        *,
        sources: list[str] | None = None,
        allow_missing_resolution_source: bool = False,
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        hard_blockers: list[str] = []
        warnings: list[str] = []
        if question.status != "active":
            hard_blockers.append("question is not active")
        if not question.resolution_criteria.strip():
            hard_blockers.append("missing resolution criteria")
        if not question.resolution_source and not allow_missing_resolution_source:
            hard_blockers.append("missing resolution source")
        if question.outcome_space.type not in {"binary", "categorical", "numeric", "distribution"}:
            hard_blockers.append(f"unsupported outcome type: {question.outcome_space.type}")
        if self.get_current_snapshot(question_id) is None:
            hard_blockers.append("no baseline forecast snapshot")
        if sources is not None and not sources:
            hard_blockers.append("at least one watched source is required")
        for source in sources or []:
            source_type = self._infer_watch_source_type(source.strip())
            if source_type == "manual_note":
                source_type = "manual"
            if source_type not in WATCH_SOURCE_TYPES:
                hard_blockers.append(f"no source adapter available for {source!r}")
            elif source_type == "manual":
                hard_blockers.append(f"no pollable source adapter available for {source!r}")
        if not self.list_reference_classes(question_id):
            warnings.append("no reference class recorded")
        if not self.list_scores():
            warnings.append("no calibration or scoring history")
        stale_assumptions = [
            row["id"]
            for row in self.list_assumptions(question_id)
            if row.get("status") in {"stale", "invalidated"}
        ]
        if stale_assumptions:
            warnings.append("stale assumptions: " + ", ".join(stale_assumptions))
        return {
            "question_id": question_id,
            "ready": not hard_blockers,
            "hard_blockers": hard_blockers,
            "warnings": warnings,
        }

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
        mode = mode.replace("-", "_")
        if mode not in AUTOPILOT_MODES:
            raise ValidationError("autopilot mode must be propose, auto-commit, or alert-only")
        sources = list(dict.fromkeys(source.strip() for source in sources if source.strip()))
        required_sources = list(
            dict.fromkeys(source.strip() for source in (required_sources or []) if source.strip())
        )
        for source in required_sources:
            if source not in sources:
                sources.append(source)
        required_source_set = set(required_sources)
        readiness = self.autopilot_readiness(
            question_id,
            sources=sources,
            allow_missing_resolution_source=allow_missing_resolution_source,
        )
        if readiness["hard_blockers"]:
            raise ValidationError("autopilot readiness failed: " + "; ".join(readiness["hard_blockers"]))
        if not cadence.strip():
            raise ValidationError("autopilot cadence is required")

        policy_id = f"ap_{uuid.uuid4().hex[:12]}"
        now = utc_now_iso()
        schedule = self.schedule_review(
            scope_type="question",
            scope_ref=question_id,
            cadence=cadence,
            next_run_at=next_run_at,
            trigger_reason="autopilot",
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO autopilot_policies (
                    id, question_id, enabled, mode, cadence, scheduled_review_id,
                    materiality_policy, guardrail_policy, notification_policy,
                    created_at, updated_at, created_by
                )
                VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    policy_id,
                    question_id,
                    mode,
                    cadence,
                    schedule["id"],
                    json_dumps(materiality_policy or {}),
                    json_dumps(guardrail_policy or {}),
                    json_dumps(notification_policy or {}),
                    now,
                    now,
                    created_by,
                ),
            )
        watches = [
            self.add_watched_source(
                scope_type="question",
                scope_ref=question_id,
                source=source,
                metadata={
                    "autopilot_policy_id": policy_id,
                    "required": source in required_source_set,
                },
            )
            for source in sources
        ]
        alert = self.create_alert(
            severity="info",
            scope_type="question",
            scope_ref=question_id,
            reason=f"autopilot_enabled:{policy_id}",
            recommended_action=f"Run `forecast autopilot status {question_id}` to inspect the maintenance policy.",
        )
        return {
            "policy": self.get_autopilot_policy(policy_id),
            "scheduled_review": schedule,
            "watched_sources": watches,
            "readiness": readiness,
            "audit_alert": alert,
        }

    def disable_autopilot(self, question_id: str) -> dict[str, Any]:
        policy = self.get_active_autopilot_policy(question_id)
        now = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE autopilot_policies SET enabled = 0, updated_at = ? WHERE id = ?",
                (now, policy["id"]),
            )
            if policy.get("scheduled_review_id"):
                conn.execute(
                    "UPDATE scheduled_reviews SET enabled = 0 WHERE id = ?",
                    (policy["scheduled_review_id"],),
                )
        return self.get_autopilot_policy(policy["id"])

    def get_autopilot_policy(self, policy_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM autopilot_policies WHERE id = ?", (policy_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"autopilot policy not found: {policy_id}")
        return self._row_to_autopilot_policy(row)

    def get_active_autopilot_policy(self, question_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM autopilot_policies
                WHERE question_id = ? AND enabled = 1
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (question_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"active autopilot policy not found for {question_id}")
        return self._row_to_autopilot_policy(row)

    def list_autopilot_policies(
        self,
        *,
        question_id: str | None = None,
        enabled_only: bool = True,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if enabled_only:
            clauses.append("enabled = 1")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM autopilot_policies {where} ORDER BY created_at DESC, id DESC",
                params,
            ).fetchall()
        return [self._row_to_autopilot_policy(row) for row in rows]

    def list_autopilot_runs(
        self,
        *,
        question_id: str | None = None,
        policy_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if policy_id:
            clauses.append("policy_id = ?")
            params.append(policy_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM autopilot_runs
                {where}
                ORDER BY started_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_autopilot_run(row) for row in rows]

    def list_forecast_update_proposals(
        self,
        *,
        question_id: str | None = None,
        status: str | None = "pending",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if question_id:
            clauses.append("question_id = ?")
            params.append(question_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(max(int(limit), 1))
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM forecast_update_proposals
                {where}
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_forecast_update_proposal(row) for row in rows]

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
        status: str = "pending",
    ) -> dict[str, Any]:
        question = self.get_question(question_id)
        if status not in AUTOPILOT_PROPOSAL_STATUSES:
            raise ValidationError("proposal status is invalid")
        payload = self._validate_probability_payload(
            proposed_probability_or_distribution,
            question.outcome_space,
        )
        if not rationale.strip():
            raise ValidationError("proposal rationale is required")
        proposal_id = f"fup_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forecast_update_proposals (
                    id, question_id, run_id, prior_forecast_id,
                    proposed_probability_or_distribution, rationale, evidence_refs,
                    source_snapshot_refs, model_run_refs, assumption_refs,
                    reference_class_refs, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal_id,
                    question_id,
                    run_id,
                    prior_forecast_id,
                    json_dumps(payload),
                    rationale.strip(),
                    json_dumps(evidence_refs or []),
                    json_dumps(source_snapshot_refs or []),
                    json_dumps(model_run_refs or []),
                    json_dumps(assumption_refs or []),
                    json_dumps(reference_class_refs or []),
                    status,
                    utc_now_iso(),
                ),
            )
        return self.get_forecast_update_proposal(proposal_id)

    def get_forecast_update_proposal(self, proposal_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM forecast_update_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"forecast update proposal not found: {proposal_id}")
        return self._row_to_forecast_update_proposal(row)

    def approve_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
        status: str = "approved",
    ) -> ForecastSnapshot:
        if status not in {"approved", "auto_committed"}:
            raise ValidationError("approved proposal status must be approved or auto_committed")
        proposal = self.get_forecast_update_proposal(proposal_id)
        if proposal["status"] != "pending" and status != "auto_committed":
            raise ValidationError("only pending proposals can be approved")
        snapshot = self.create_snapshot(
            question_id=proposal["question_id"],
            probability_or_distribution=proposal["proposed_probability_or_distribution"],
            rationale=proposal["rationale"],
            method="autopilot",
            style_autofix=True,  # autopilot auto-commit: no agent to rewrite, clean prose mechanically
            distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
            evidence_refs=proposal["evidence_refs"],
            source_snapshot_refs=proposal["source_snapshot_refs"],
            model_run_refs=proposal["model_run_refs"],
            assumption_refs=proposal["assumption_refs"],
            reference_class_refs=proposal["reference_class_refs"],
            require_citations=True,
            metadata={"autopilot_proposal_id": proposal_id},
        )
        reviewed_at = utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (status, reviewed_at, reviewed_by, proposal_id),
            )
            if proposal.get("run_id"):
                conn.execute(
                    "UPDATE autopilot_runs SET forecast_snapshot_id = ? WHERE id = ?",
                    (snapshot.forecast_id, proposal["run_id"]),
                )
        return snapshot

    def reject_forecast_update_proposal(
        self,
        proposal_id: str,
        *,
        reviewed_by: str | None = None,
    ) -> dict[str, Any]:
        proposal = self.get_forecast_update_proposal(proposal_id)
        if proposal["status"] != "pending":
            raise ValidationError("only pending proposals can be rejected")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_update_proposals
                SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (utc_now_iso(), reviewed_by, proposal_id),
            )
        return self.get_forecast_update_proposal(proposal_id)

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
        """The identifiers a fresh reading can match a component / prior
        observation by (same scheme as _derive_trigger_observations)."""
        keys = {source.strip().lower(), f"{source_type}:{source}".strip().lower()}
        keys.discard("")
        return keys

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
        trigger_reason: str = "manual_refresh",
        skill_weights: bool | None = None,
    ) -> dict[str, Any]:
        """Pull the latest watched-source readings, import the new values as
        evidence, deterministically re-pool the forecast, and (by default)
        auto-commit a new live snapshot.

        ``fetcher(specs) -> [{source_type, source, success, payloads, error}]``
        is injected by the caller (CLI / tool layer) so the ledger never imports
        the adapter/tool layer; ``payloads`` are kwargs for :meth:`add_evidence`.
        ``re_estimate="deterministic"`` re-pools the prior snapshot's
        probability-bearing components after refreshing market/crowd readings;
        ``"carry_forward"`` keeps the prior probability and flags that agent /
        manual re-reasoning is needed (also the automatic fallback for
        non-binary questions or raw-data-only sources). With ``commit`` and not
        ``dry_run`` the re-estimate is written through :meth:`create_snapshot`
        as a scored ``forecast_origin="live"`` snapshot; otherwise nothing is
        persisted and a preview is returned.
        """

        if re_estimate not in {"deterministic", "carry_forward"}:
            raise ValidationError("re_estimate must be 'deterministic' or 'carry_forward'")
        question = self.get_question(question_id)
        current = self.get_current_snapshot(question_id)
        if current is None:
            raise ValidationError("refresh requires a baseline forecast snapshot")
        run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
        persist = bool(commit) and not dry_run

        watches = self.list_watched_sources(
            scope_type="question", scope_ref=question_id, status="active"
        )
        if not watches:
            return {
                "status": "no_watched_sources",
                "committed": None,
                # NOT a completed update: a deterministic re-pool cannot collect
                # evidence, so a sourceless question gets none. The caller owns
                # closing this gap (import_source_evidence per driver, or re-run
                # with --agent so the LLM update stage gathers it) — never treat
                # this as "refreshed" or borrow a linked forecast's evidence.
                "evidence_required": True,
                "message": (
                    "NO active watched sources — this is NOT a completed update. Collect "
                    "evidence for THIS question (import_source_evidence per driver, then "
                    "`forecast watch add` so it can refresh next time), or re-run with --agent "
                    "to collect evidence via the LLM update stage. Do not borrow another "
                    "forecast's evidence as a substitute."
                ),
            }

        prior_observations = self._derive_trigger_observations(question_id)

        # 1) Re-fetch every active watched source (parallel, injected fetcher).
        specs = []
        for watch in watches:
            control_keys = {"autopilot_policy_id", "required", "auto_watch", "from_action", "source_ref"}
            adapter_args = {
                key: value
                for key, value in (watch.get("metadata") or {}).items()
                if key not in control_keys
            }
            specs.append(
                {"source_type": watch["source_type"], "source": watch["source"], "args": adapter_args}
            )
        fetched = fetcher(specs)

        # 2) Reduce each fetched reading to its latest numeric value + keys, and
        #    decide which readings actually changed vs the last imported value.
        fresh_market_readings: list[dict[str, Any]] = []
        fresh_values: dict[str, float] = {}
        changed_readings: list[dict[str, Any]] = []
        fetch_failures: list[dict[str, str]] = []
        new_evidence_ids: list[str] = []
        for result in fetched or []:
            if not result.get("success"):
                fetch_failures.append(
                    {"source": f"{result.get('source_type')}:{result.get('source')}", "error": result.get("error") or "fetch failed"}
                )
                continue
            stype = str(result.get("source_type") or "")
            source = str(result.get("source") or "")
            keys = self._refresh_source_keys(stype, source)
            for payload in result.get("payloads") or []:
                item = (payload.get("metadata") or {}).get("adapter_item") or {}
                market_p = self._numeric_probability(item.get("probability"))
                raw_value = self._refresh_reading_value(item)
                reading = market_p if market_p is not None else raw_value
                if market_p is not None:
                    # One reading, one entry (with all its identity keys) so the
                    # same reading is never double-counted as matched + unmatched.
                    fresh_market_readings.append(
                        {"keys": set(keys), "probability": market_p, "label": f"{stype}:{source}"}
                    )
                for key in keys:
                    if reading is not None:
                        fresh_values[key] = reading
                # A reading is "changed" if new or different from the last import.
                is_changed = reading is None or any(
                    key not in prior_observations or abs(prior_observations[key] - reading) > 1e-9
                    for key in keys
                )
                if is_changed:
                    changed_readings.append({"source_type": stype, "source": source, "value": reading, "payload": payload})
                    if persist:
                        evidence = self.add_evidence(
                            question_id=question_id, archive_url_snapshot=False, **payload
                        )
                        new_evidence_ids.append(evidence.id)

        # 3) Re-estimate.
        prior_rows = self._ensemble_component_rows(current.ensemble_components)
        binary = question.outcome_space.type == "binary" and isinstance(
            current.probability_or_distribution, (int, float)
        )
        updated_components, unmatched_sources = self._apply_fresh_market_probabilities(
            current.ensemble_components, fresh_market_readings
        )
        can_repool = (
            re_estimate == "deterministic"
            and binary
            and bool(prior_rows)
            and bool(updated_components["matched"])
        )

        prior_prob = float(current.probability_or_distribution) if binary else None
        new_prob: Any = current.probability_or_distribution
        new_components = current.ensemble_components
        diff_dict: dict[str, Any] | None = None
        reasons_up: list[str] = []
        reasons_down: list[str] = []
        needs_agent = not can_repool
        skill_multipliers_applied: list[dict[str, Any]] = []

        if can_repool:
            from forecasting.bayes_toolkit import (  # local import avoids cycle / heavy import at module load
                combine_forecasts,
                ensure_industry_backends,
                forecast_diff,
            )

            ensure_industry_backends()
            method = self._refresh_pool_method(current.method)
            # R4 Living Models: scale each model-sourced component's weight by its
            # Market Model's measured skill multiplier BEFORE pooling. The persisted
            # component weights stay the ORIGINAL (unscaled) values, so the
            # multiplier is re-derived fresh from current skill on every refresh and
            # never compounds. Config-gated (forecasting.models.skill_weights, default
            # ON) and identity on cold start — the pooled number is unchanged until a
            # model earns a measured skill.
            use_skill_weights = (
                self._skill_weights_enabled() if skill_weights is None else bool(skill_weights)
            )
            pool_rows = updated_components["rows"]
            if use_skill_weights:
                pool_rows, skill_multipliers_applied = self._apply_model_skill_weights(pool_rows)
            pool = combine_forecasts(
                pool_rows,
                method=method,
                extremize=extremize,
                correlation_matrix=correlation,
            )
            new_prob = pool.probability
            new_components = {"components": updated_components["rows"]}
            diff = forecast_diff(
                previous=prior_prob,
                current=float(new_prob),
                components=updated_components["diff_components"],
            )
            diff_dict = diff.to_dict()
            for driver in diff.drivers:
                pts = driver.get("contribution_pts")
                if pts is None:
                    continue
                label = f"{driver.get('name', 'component')} ({pts:+.1f} pts)"
                (reasons_up if pts >= 0 else reasons_down).append(label)

        prob_changed = (
            binary
            and isinstance(new_prob, (int, float))
            and abs(float(new_prob) - prior_prob) > 1e-9
        )

        # 4) No-op guard: nothing fetched-changed and probability unchanged.
        if not changed_readings and not prob_changed:
            return {
                "status": "no_change",
                "committed": None,
                "message": "no new readings and probability unchanged — nothing committed.",
                "prior_probability": current.probability_or_distribution,
                "fetch_failures": fetch_failures,
                "unmatched_sources": unmatched_sources,
            }

        # 5) Fire executable update_triggers against the fresh values (idempotent).
        trigger_alerts: list[AlertEvent] = []
        if persist:
            trigger_alerts = self.check_update_triggers(
                question_id=question_id, observations=fresh_values or None, now=run_at
            )

        # 6) Auto rationale (no human in the loop).
        rationale = self._default_refresh_rationale(
            changed_readings=changed_readings,
            unmatched_sources=unmatched_sources,
            new_prob=new_prob,
            prior_prob=current.probability_or_distribution,
            re_estimate="deterministic" if can_repool else "carry_forward",
            needs_agent=needs_agent,
        )

        preview = {
            "status": "carry_forward" if needs_agent else "re_pooled",
            "committed": None,
            "prior_probability": current.probability_or_distribution,
            "proposed_probability": new_prob,
            "diff": diff_dict,
            "reasons_up": reasons_up,
            "reasons_down": reasons_down,
            "rationale": rationale,
            "changed_readings": [
                {"source_type": r["source_type"], "source": r["source"], "value": r["value"]}
                for r in changed_readings
            ],
            "unmatched_sources": unmatched_sources,
            "fetch_failures": fetch_failures,
            "needs_agent": needs_agent,
            "triggers_fired": [alert.reason for alert in trigger_alerts],
            "skill_multipliers": skill_multipliers_applied,
        }

        if not persist:
            preview["message"] = "preview only — re-run without --dry-run/--no-commit to commit."
            return preview

        # 7) Record a model run as the audit + citation anchor, then commit.
        change_my_mind = [
            "A reversal in the strongest refreshed driver would move this back",
            "A watched source going stale or failing on the next refresh",
        ]
        model_run = self.record_model_run(
            question_id=question_id,
            model_type="forecast_refresh",
            inputs={
                "trigger_reason": trigger_reason,
                "prior_forecast_id": current.forecast_id,
                "new_evidence_ids": new_evidence_ids,
            },
            parameters={
                "re_estimate": "deterministic" if can_repool else "carry_forward",
                "method": self._refresh_pool_method(current.method),
                "extremize": extremize,
            },
            output={"proposed_probability": new_prob, "diff": diff_dict},
            diagnostics={"changed_readings": len(changed_readings), "fetch_failures": fetch_failures},
        )

        snapshot = self.create_snapshot(
            question_id=question_id,
            probability_or_distribution=new_prob,
            rationale=rationale,
            method=current.method,
            ensemble_components=new_components,
            forecast_origin="live",
            evidence_refs=new_evidence_ids,
            model_run_refs=[model_run["id"]],
            reasons_up=reasons_up or ["Refreshed watched-source readings"],
            reasons_down=reasons_down or ["Counter-signals in the refreshed sources"],
            change_my_mind=change_my_mind,
            require_citations=True,
            style_autofix=True,  # programmatic re-pool: mechanically clean generated prose, never block
            distribution_autofix=True,  # programmatic: auto-fix malformed bounds rather than block
            panel_skipped_reason=(
                "automated forecast refresh — deterministic re-pool of existing components; "
                "panel not required for a programmatic re-estimate"
            ),
            evidence_cutoff=run_at,
            metadata={
                "refresh": {
                    "trigger_reason": trigger_reason,
                    "re_estimate": "deterministic" if can_repool else "carry_forward",
                    "prior_forecast_id": current.forecast_id,
                    "needs_agent": needs_agent,
                    "diff": diff_dict,
                },
                # R4 audit trail: the skill multipliers applied to model-sourced
                # components in this re-pool (empty when none applied / cold start),
                # mirroring how calibration_adjustment records its applied factors.
                **({"skill_multipliers": skill_multipliers_applied} if skill_multipliers_applied else {}),
                # Provenance only — the deterministic re-pool does NOT derive its
                # number from siblings, so cross_refs are advisory.
                **({"cross_refs": cross_refs} if (cross_refs := self.build_cross_refs(question_id, advisory_only=True)) else {}),
            },
        )

        return {
            **preview,
            "status": "committed",
            "committed": snapshot.__dict__,
            "forecast_id": snapshot.forecast_id,
            "model_run": model_run,
            "new_evidence_ids": new_evidence_ids,
            "message": None,
        }

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
        """Read ``forecasting.models.skill_weights`` (default TRUE). Best-effort:
        a config-read failure degrades to enabled — the R4 re-pool weighting is
        harmless-by-construction on cold start (every multiplier is 1.0 until a
        model clears the resolved-binary sample gate)."""
        try:
            from hermes_cli.config import load_config

            cfg = load_config() or {}
            fc = cfg.get("forecasting", {}) if isinstance(cfg, dict) else {}
            models_cfg = fc.get("models", {}) if isinstance(fc, dict) else {}
            if isinstance(models_cfg, dict) and "skill_weights" in models_cfg:
                return bool(models_cfg["skill_weights"])
        except Exception:
            pass
        return True

    def _market_model_scored_run_count(self, market_model_id: str) -> int:
        """Cheap COUNT of scored model_runs tagged to a Market Model — an UPPER bound
        on the binary sample :meth:`model_skill` would find (some may be numeric). The
        skill weight can only move once ``n_binary >= MODEL_WEIGHT_MIN_SAMPLE``, so a
        count below the gate proves the multiplier is identity by construction. This
        lets the skill-weighted re-pool skip the O(resolved) skill scan on cold-start /
        lightly-tagged books (a batch sweep would otherwise pay it per question).
        Returns -1 on any read error so the caller falls back to the full scan."""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM model_runs WHERE market_model_id = ? AND scored_at IS NOT NULL",
                    (market_model_id,),
                ).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return -1

    def _apply_model_skill_weights(
        self, rows: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Scale each model-sourced component's weight by its Market Model's skill
        multiplier (R4). Returns ``(scaled_rows, applied)`` where ``applied`` is the
        audit trail of ``{name, market_model_id, multiplier, prior_weight,
        new_weight}`` for every component actually scaled (skill measured +
        multiplier != 1.0). Non-model components and cold-start models pass through
        unchanged (identity multiplier), so the pooled number is byte-identical to
        the unweighted re-pool until a model earns a measured skill."""
        applied: list[dict[str, Any]] = []
        skill_cache: dict[str, dict[str, Any]] = {}
        scaled: list[dict[str, Any]] = []
        for raw in rows:
            row = dict(raw)
            mmid = self._component_market_model_id(row)
            if mmid is not None:
                skill = skill_cache.get(mmid)
                if skill is None:
                    # Precheck: if the model has fewer scored runs than the sample gate,
                    # its skill is identity by construction — skip the O(resolved) scan
                    # (the batch-sweep cost the finding flagged). -1 = read error → do
                    # the real scan rather than silently skip.
                    n_scored = self._market_model_scored_run_count(mmid)
                    if 0 <= n_scored < self.MODEL_WEIGHT_MIN_SAMPLE:
                        skill = {"weight_multiplier": 1.0, "status": "insufficient_track_record"}
                    else:
                        try:
                            skill = self.model_skill(market_model_id=mmid)
                        except Exception:
                            skill = {"weight_multiplier": 1.0, "status": "insufficient_track_record"}
                    skill_cache[mmid] = skill
                multiplier = float(skill.get("weight_multiplier") or 1.0)
                if skill.get("status") == "measured" and abs(multiplier - 1.0) > 1e-9:
                    prior_weight = self._numeric_probability(row.get("weight", 1.0)) or 0.0
                    new_weight = prior_weight * multiplier
                    row["weight"] = new_weight
                    applied.append(
                        {
                            "name": str(row.get("name") or row.get("source") or mmid),
                            "market_model_id": mmid,
                            "multiplier": multiplier,
                            "prior_weight": prior_weight,
                            "new_weight": new_weight,
                            "n_scored": skill.get("n_binary"),
                        }
                    )
            scaled.append(row)
        return scaled, applied

    def _refresh_reading_value(self, item: dict[str, Any]) -> float | None:
        """Extract the latest numeric reading from an adapter item (the same
        canonical keys the trigger evaluator reads)."""
        for key in self._TRIGGER_VALUE_KEYS:
            raw = item.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                return float(raw)
            except (TypeError, ValueError):
                continue
        return None

    def _apply_fresh_market_probabilities(
        self, components: dict[str, Any], fresh_readings: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], list[str]]:
        """Update each prior component's probability with a freshly-fetched
        market/crowd reading that matches it. ``fresh_readings`` is a list of
        ``{"keys": set[str], "probability": float, "label": str}``. Returns
        ``{"rows", "diff_components", "matched"}`` and the list of reading
        labels that did not match any component."""

        raw_rows = (
            list(components.get("components"))
            if isinstance(components.get("components"), list)
            else [
                {"name": name, **(value if isinstance(value, dict) else {"probability": value})}
                for name, value in (components or {}).items()
            ]
        )
        rows: list[dict[str, Any]] = []
        diff_components: list[dict[str, Any]] = []
        matched_labels: set[str] = set()
        for index, raw in enumerate(raw_rows, start=1):
            if not isinstance(raw, dict):
                continue
            prior_p = self._numeric_probability(raw.get("probability"))
            weight = self._numeric_probability(raw.get("weight", 1.0))
            if prior_p is None or weight is None or weight < 0:
                continue
            name = str(raw.get("name") or raw.get("source") or f"component_{index}")
            identity = {str(raw.get("source") or "").lower(), name.lower()}
            identity.discard("")
            new_p = prior_p
            for reading in fresh_readings:
                keys = reading["keys"]
                if keys & identity or any(
                    key in token or token in key for key in keys for token in identity
                ):
                    new_p = reading["probability"]
                    matched_labels.add(reading["label"])
                    break
            # Preserve every original component key (esp. `source`) so the
            # component stays matchable on the NEXT refresh; only the probability
            # is overwritten. combine_forecasts ignores the extra keys.
            row = dict(raw)
            row["name"] = name
            row["probability"] = new_p
            row["weight"] = weight
            rows.append(row)
            diff_components.append(
                {"name": name, "previous_p": prior_p, "current_p": new_p, "weight": weight}
            )
        unmatched = sorted({r["label"] for r in fresh_readings} - matched_labels)
        return {"rows": rows, "diff_components": diff_components, "matched": sorted(matched_labels)}, unmatched

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
        sources = ", ".join(
            sorted({f"{r['source_type']}:{r['source']}" for r in changed_readings})
        ) or "no changed readings"
        if re_estimate == "deterministic":
            head = (
                f"Automated refresh: re-pooled components after refreshing {sources}. "
                f"Probability {prior_prob} -> {new_prob}."
            )
        else:
            head = (
                f"Automated refresh: imported fresh readings from {sources} and carried the prior "
                f"probability {prior_prob} forward"
                + (" — run with --agent for a re-reasoned estimate." if needs_agent else ".")
            )
        if unmatched_sources:
            head += f" Unmatched fresh readings (not wired to a component): {', '.join(unmatched_sources)}."
        return head

    def run_autopilot(
        self,
        question_id: str,
        *,
        now: str | None = None,
        trigger_reason: str = "manual",
        proposed_probability_or_distribution: Any | None = None,
        rationale: str | None = None,
    ) -> dict[str, Any]:
        policy = self.get_active_autopilot_policy(question_id)
        current = self.get_current_snapshot(question_id)
        if current is None:
            raise ValidationError("autopilot requires a baseline forecast snapshot")
        run_at = parse_timestamp(now, field_name="now") or utc_now_iso()
        watches = self.list_watched_sources(scope_type="question", scope_ref=question_id, status="active")
        source_snapshots: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        required_source_failures: list[str] = []
        alerts: list[AlertEvent] = []

        for watch in watches:
            previous_signature = watch.get("last_seen_signature")
            current_signature = self._source_signature(
                watch["source"],
                watch["source_type"],
                metadata=watch.get("metadata"),
            )
            status = "success"
            error_message = None
            if current_signature is None or str(current_signature).startswith("missing:"):
                status = "failed"
                error_message = str(current_signature or "source unavailable")
            did_change = (
                status == "success"
                and previous_signature is not None
                and current_signature is not None
                and current_signature != previous_signature
            )
            source_snapshot = self._record_source_snapshot(
                question_id=question_id,
                watch=watch,
                retrieved_at=run_at,
                signature=current_signature,
                previous_signature=previous_signature,
                changed=did_change,
                status=status,
                error_message=error_message,
            )
            source_snapshots.append(source_snapshot)
            if did_change:
                changed.append(source_snapshot)
            if status == "failed":
                is_required = bool((watch.get("metadata") or {}).get("required"))
                if is_required:
                    required_source_failures.append(source_snapshot["id"])
                alerts.append(
                    self.create_alert(
                        severity="high" if is_required else "warning",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=(
                            f"autopilot_required_source_failed:{watch['id']}"
                            if is_required
                            else f"autopilot_source_failed:{watch['id']}"
                        ),
                        recommended_action=(
                            "Required autopilot source failed; forecast refresh is blocked until it recovers. "
                            f"Inspect the source and rerun `forecast autopilot run {question_id}`."
                            if is_required
                            else (
                                "Inspect the watched source and rerun "
                                f"`forecast autopilot run {question_id}` after the adapter recovers."
                            )
                        ),
                    )
                )
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE watched_sources
                    SET last_checked_at = ?, last_seen_signature = ?
                    WHERE id = ?
                    """,
                    (run_at, current_signature, watch["id"]),
                )

        blocked_by_required_source_failure = bool(required_source_failures)
        material_changes = 0
        if not blocked_by_required_source_failure and self._autopilot_material_change(policy, changed):
            material_changes = len(changed)
        proposal: dict[str, Any] | None = None
        snapshot: ForecastSnapshot | None = None
        model_run: dict[str, Any] | None = None
        source_failures = [row["id"] for row in source_snapshots if row["status"] == "failed"]
        if blocked_by_required_source_failure:
            status = "failed"
        elif source_failures:
            status = "partial"
        else:
            status = "skipped" if material_changes == 0 else "success"
        diagnostics: dict[str, Any] = {
            "mode": policy["mode"],
            "source_snapshot_ids": [row["id"] for row in source_snapshots],
            "changed_source_snapshot_ids": [row["id"] for row in changed],
            "source_failures": source_failures,
            "required_source_failures": required_source_failures,
            "forecast_refresh_blocked": blocked_by_required_source_failure,
            "materiality_policy": policy["materiality_policy"],
            "guardrail_policy": policy["guardrail_policy"],
        }

        if material_changes:
            proposed_payload = (
                proposed_probability_or_distribution
                if proposed_probability_or_distribution is not None
                else current.probability_or_distribution
            )
            proposal_rationale = rationale or self._default_autopilot_rationale(
                changed=changed,
                current=current,
            )
            model_run = self.record_model_run(
                question_id=question_id,
                model_type="autopilot_refresh",
                inputs={
                    "trigger_reason": trigger_reason,
                    "prior_forecast_id": current.forecast_id,
                    "source_snapshot_refs": [row["id"] for row in source_snapshots],
                },
                parameters={
                    "materiality_policy": policy["materiality_policy"],
                    "guardrail_policy": policy["guardrail_policy"],
                },
                output={
                    "proposed_probability_or_distribution": proposed_payload,
                    "rationale": proposal_rationale,
                },
                diagnostics=diagnostics,
                model_version=FORECASTING_PROTOCOL_VERSION,
                evidence_cutoff=run_at,
            )
            proposal = self.create_forecast_update_proposal(
                question_id=question_id,
                run_id=None,
                prior_forecast_id=current.forecast_id,
                proposed_probability_or_distribution=proposed_payload,
                rationale=proposal_rationale,
                source_snapshot_refs=[row["id"] for row in source_snapshots],
                model_run_refs=[model_run["id"]],
            )
            if policy["mode"] == "alert_only":
                alerts.append(
                    self.create_alert(
                        severity="warning",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_material_change:{policy['id']}",
                        recommended_action=f"Review proposal {proposal['id']} before updating the forecast.",
                    )
                )
            elif policy["mode"] == "auto_commit":
                violations = self._autopilot_guardrail_violations(
                    policy=policy,
                    prior_payload=current.probability_or_distribution,
                    proposed_payload=proposed_payload,
                    source_snapshots=source_snapshots,
                )
                diagnostics["guardrail_violations"] = violations
                if violations:
                    alerts.append(
                        self.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question_id,
                            reason=f"autopilot_guardrail_review:{policy['id']}",
                            recommended_action=(
                                "Autopilot update requires review: "
                                + "; ".join(violations)
                                + f". Approve manually with `forecast autopilot approve {proposal['id']}`."
                            ),
                        )
                    )
                else:
                    snapshot = self.approve_forecast_update_proposal(
                        proposal["id"],
                        status="auto_committed",
                    )
            else:
                alerts.append(
                    self.create_alert(
                        severity="info",
                        scope_type="question",
                        scope_ref=question_id,
                        reason=f"autopilot_update_proposed:{proposal['id']}",
                        recommended_action=f"Review with `forecast autopilot approve {proposal['id']}` or reject it.",
                    )
                )

        run = self._record_autopilot_run(
            policy_id=policy["id"],
            question_id=question_id,
            started_at=run_at,
            finished_at=utc_now_iso(),
            status=status,
            trigger_reason=trigger_reason,
            sources_checked=len(watches),
            sources_changed=len(changed),
            material_changes=material_changes,
            proposal_id=proposal["id"] if proposal else None,
            forecast_snapshot_id=snapshot.forecast_id if snapshot else None,
            alerts_created=len(alerts),
            diagnostics=diagnostics,
        )
        if proposal and proposal.get("run_id") is None:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE forecast_update_proposals SET run_id = ? WHERE id = ?",
                    (run["id"], proposal["id"]),
                )
            proposal = self.get_forecast_update_proposal(proposal["id"])
        return {
            "policy": policy,
            "run": run,
            "source_snapshots": source_snapshots,
            "proposal": proposal,
            "forecast_snapshot": snapshot,
            "model_run": model_run,
            "alerts": alerts,
        }

    def check_watched_sources(
        self,
        *,
        scope_type: str | None = None,
        scope_ref: str | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        return _watches.check_watched_sources(self, scope_type=scope_type, scope_ref=scope_ref, now=now)

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
        """Best-effort map of source_ref -> latest numeric value, derived from the
        question's imported evidence. The newest evidence per source wins. Used
        when the caller does not supply observations explicitly."""

        latest: dict[str, tuple[str, float]] = {}
        for evidence in self.list_evidence(question_id):
            meta = evidence.metadata or {}
            item = meta.get("adapter_item")
            if not isinstance(item, dict):
                continue
            value: float | None = None
            for key in self._TRIGGER_VALUE_KEYS:
                raw = item.get(key)
                if raw is None or isinstance(raw, bool):
                    continue
                try:
                    value = float(raw)
                    break
                except (TypeError, ValueError):
                    continue
            if value is None:
                continue
            adapter = meta.get("adapter")
            source = meta.get("source")
            keys = set()
            if source:
                keys.add(str(source))
                if adapter:
                    keys.add(f"{adapter}:{source}")
            if meta.get("source_ref"):
                keys.add(str(meta["source_ref"]))
            # Rank by the OBSERVATION date, not the import time: a single batch
            # import stamps every observation in a series with the same
            # available_at, so using available_at would pick an arbitrary
            # mid-series reading (e.g. a stale peak) instead of the latest
            # observation. entry_id ("DCOILWTICO:2026-05-18") and
            # observation_date carry the real series date; fall back to
            # available_at for sources that have neither.
            entry_id = str(meta.get("entry_id") or "")
            obs_date = str(item.get("observation_date") or item.get("date") or "")
            entry_suffix = entry_id.split(":", 1)[1] if ":" in entry_id else ""
            stamp = obs_date or entry_suffix or evidence.available_at or evidence.captured_at or ""
            for key in keys:
                if key not in latest or stamp >= latest[key][0]:
                    latest[key] = (stamp, value)
        return {key: value for key, (_, value) in latest.items()}

    def check_update_triggers(
        self,
        *,
        question_id: str,
        observations: dict[str, Any] | None = None,
        now: str | None = None,
    ) -> list[AlertEvent]:
        """Evaluate a question's executable update_triggers against imported
        values and emit (idempotent) ``trigger_fired`` alerts. ``observations``
        (source_ref -> value) overrides values derived from imported evidence."""

        question = self.get_question(question_id)
        merged = dict(self._derive_trigger_observations(question_id))
        for key, value in (observations or {}).items():
            merged[str(key)] = value
        fired = evaluate_update_triggers(question.update_triggers, merged)
        if not fired:
            return []
        open_reasons = {
            alert.reason
            for alert in self.list_alerts(unresolved_only=True)
            if alert.scope_type == "question" and alert.scope_ref == question_id
        }
        alerts: list[AlertEvent] = []
        for entry in fired:
            reason = f"trigger_fired:{entry['source_ref']}"
            if reason in open_reasons:
                continue  # one open alert per source until acknowledged
            alerts.append(
                self.create_alert(
                    severity="warning",
                    scope_type="question",
                    scope_ref=question_id,
                    reason=reason,
                    recommended_action=(
                        f"Update trigger fired: {entry['mechanism']} "
                        f"({entry['source_ref']} {entry['operator']} {entry['threshold']}; "
                        f"observed {entry['observed']}). Re-run the forecast: "
                        f"`forecast pipeline {question_id} --stage update`."
                    ),
                )
            )
        return alerts

    def run_due_scheduled_reviews(
        self,
        *,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        refresh_fetcher: Any = None,
    ) -> list[dict[str, Any]]:
        """Run every due scheduled-review row, advancing each row's cadence.

        ``refresh_fetcher`` (injected by the cron layer — the ledger never imports
        the tool/adapter layer) turns the sweep into a DETERMINISTIC self-refresh:
        for each due QUESTION-scoped review that is refreshable (has a baseline
        snapshot with structured ensemble_components AND active watched sources) we
        re-pull the sources, re-pool, and auto-commit a fresh snapshot — no LLM.
        Fail-open per question: one broken source records an error in the row's
        result and never aborts the sweep. The cadence is also DEADLINE-AWARE — a
        question's next run is escalated (never slowed) as its close/resolution/
        decision deadline nears."""
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_reviews
                WHERE enabled = 1 AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (now_ts,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            review = dict(row)
            scope_type = review["scope_type"]
            scope_ref = review["scope_ref"]
            stale_days = int(review.get("stale_days") or 7)
            confidence_below = review.get("confidence_below")
            confidence_above = review.get("confidence_above")
            large_delta_threshold = review.get("large_delta_threshold")
            refresh_result: dict[str, Any] | None = None
            refresh_error: str | None = None
            deadlines: list[str | None] | None = None
            if scope_type == "question":
                alerts = self.self_check(
                    question_id=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
                # Deadline-aware cadence input: read the question's live deadlines so
                # the next run can be escalated as close/resolution/decision nears.
                try:
                    question = self.get_question(scope_ref)
                    deadlines = [
                        getattr(question, "close_time", None),
                        getattr(question, "resolution_time", None),
                        getattr(question, "decision_deadline", None),
                    ]
                except Exception:
                    deadlines = None
                # Deterministic self-refresh (no LLM) for a refreshable question.
                if refresh_fetcher is not None:
                    try:
                        refresh_result = self._refresh_due_question(
                            scope_ref, fetcher=refresh_fetcher, now=now_ts
                        )
                    except Exception as exc:  # never abort the sweep on one question
                        refresh_error = str(exc)
            elif scope_type == "domain":
                alerts = self.self_check(
                    domain=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "topic":
                alerts = self.self_check(
                    topic=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "domain_topic":
                scope_filter = json_loads(scope_ref, {})
                alerts = self.self_check(
                    domain=scope_filter.get("domain"),
                    topic=scope_filter.get("topic"),
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            elif scope_type == "portfolio":
                alerts = self.self_check(
                    portfolio=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            else:
                alerts = self.self_check(
                    horizon=scope_ref,
                    stale_days=stale_days,
                    now=now_ts,
                    auto_score=auto_score or bool(review.get("auto_score")),
                    auto_postmortem=auto_postmortem or bool(review.get("auto_postmortem")),
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                    large_delta_threshold=large_delta_threshold,
                )
            next_run_at = self._advance_cadence(
                now_ts, review["cadence"], deadlines=deadlines
            )
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE scheduled_reviews
                    SET last_run_at = ?, next_run_at = ?
                    WHERE id = ?
                    """,
                    (now_ts, next_run_at, review["id"]),
                )
            run = self._record_scheduled_review_run(
                review=review,
                run_at=now_ts,
                next_run_at=next_run_at,
                alerts=alerts,
            )
            results.append(
                {
                    "review": self.get_scheduled_review(review["id"]),
                    "run": run,
                    "alerts": alerts,
                    "refresh": refresh_result,
                    "refresh_error": refresh_error,
                }
            )
        return results

    def _refresh_due_question(
        self, question_id: str, *, fetcher: Any, now: str | None
    ) -> dict[str, Any] | None:
        """Deterministically self-refresh a due question when it is refreshable.

        Refreshable = a baseline snapshot with structured ensemble_components AND
        at least one active watched source. Returns ``None`` (skipped) otherwise,
        so a bare/no-source question is quietly left for the agent-tier re-reason.
        Opens its own write context so the commit is permitted even when the caller
        did not (e.g. the tool's direct ``run_scheduled_reviews``)."""
        current = self.get_current_snapshot(question_id)
        if current is None:
            return None
        components = current.ensemble_components
        if not isinstance(components, dict) or not components:
            return None
        watches = self.list_watched_sources(
            scope_type="question", scope_ref=question_id, status="active"
        )
        if not watches:
            return None
        with allow_ledger_writes(reason="scheduled_refresh"):
            return self.refresh_forecast(
                question_id,
                fetcher=fetcher,
                now=now,
                trigger_reason="scheduled_refresh",
            )

    def _record_scheduled_review_run(
        self,
        *,
        review: dict[str, Any],
        run_at: str,
        next_run_at: str,
        alerts: list[AlertEvent],
    ) -> dict[str, Any]:
        score_count = sum(1 for alert in alerts if alert.reason.startswith("score_created:"))
        postmortem_count = sum(1 for alert in alerts if alert.reason.startswith("postmortem_created:"))
        learning_review_count = sum(1 for alert in alerts if self._is_learning_alert_reason(alert.reason))
        run_id = f"srr_{uuid.uuid4().hex[:12]}"
        metadata = {
            "scope_type": review.get("scope_type"),
            "scope_ref": review.get("scope_ref"),
            "cadence": review.get("cadence"),
            "trigger_reason": review.get("trigger_reason"),
            "auto_score": bool(review.get("auto_score")),
            "auto_postmortem": bool(review.get("auto_postmortem")),
            "alert_reasons": [alert.reason for alert in alerts],
            "alert_ids": [alert.id for alert in alerts],
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_review_runs (
                    id, scheduled_review_id, run_at, next_run_at, alert_count,
                    score_count, postmortem_count, learning_review_count,
                    status, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    review["id"],
                    run_at,
                    next_run_at,
                    len(alerts),
                    score_count,
                    postmortem_count,
                    learning_review_count,
                    "completed",
                    json_dumps(metadata),
                ),
            )
        return self.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=1)[0]

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
    ) -> dict[str, Any]:
        snapshot_id = f"ss_{uuid.uuid4().hex[:12]}"
        parsed_values = {
            "signature": signature,
            "previous_signature": previous_signature,
            "changed": changed,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO source_snapshots (
                    id, question_id, watched_source_id, source_type, source_url,
                    retrieved_at, raw_payload_sha256, parsed_values,
                    adapter_version, status, error_message, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    question_id,
                    watch["id"],
                    watch["source_type"],
                    watch["source"],
                    retrieved_at,
                    signature,
                    json_dumps(parsed_values),
                    f"{watch['source_type']}-watch-v1",
                    status,
                    error_message,
                    json_dumps(
                        {
                            "autopilot_policy_id": watch.get("metadata", {}).get("autopilot_policy_id"),
                            "required": bool((watch.get("metadata") or {}).get("required")),
                        }
                    ),
                ),
            )
        return self.list_source_snapshots(watched_source_id=watch["id"], limit=1)[0]

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
        run_id = f"apr_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    id, policy_id, question_id, started_at, finished_at, status,
                    trigger_reason, sources_checked, sources_changed,
                    material_changes, proposal_id, forecast_snapshot_id,
                    alerts_created, diagnostics
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    policy_id,
                    question_id,
                    started_at,
                    finished_at,
                    status,
                    trigger_reason,
                    sources_checked,
                    sources_changed,
                    material_changes,
                    proposal_id,
                    forecast_snapshot_id,
                    alerts_created,
                    json_dumps(diagnostics),
                ),
            )
        return self.list_autopilot_runs(policy_id=policy_id, limit=1)[0]

    @staticmethod
    def _autopilot_material_change(policy: dict[str, Any], changed: list[dict[str, Any]]) -> bool:
        minimum = int((policy.get("materiality_policy") or {}).get("min_source_changes") or 1)
        return len(changed) >= max(minimum, 1)

    @staticmethod
    def _default_autopilot_rationale(
        *,
        changed: list[dict[str, Any]],
        current: ForecastSnapshot,
    ) -> str:
        drivers = ", ".join(
            f"{row['source_type']}:{row['watched_source_id']}"
            for row in changed[:3]
        )
        return (
            "Autopilot detected material watched-source changes "
            f"({drivers or 'source change'}) after prior forecast {current.forecast_id}. "
            "This proposal preserves the previous probability until an explicit model or operator "
            "adjustment supplies a different distribution."
        )

    def _autopilot_guardrail_violations(
        self,
        *,
        policy: dict[str, Any],
        prior_payload: Any,
        proposed_payload: Any,
        source_snapshots: list[dict[str, Any]],
    ) -> list[str]:
        guardrails = policy.get("guardrail_policy") or {}
        violations: list[str] = []
        if guardrails.get("require_no_critical_source_failures", True):
            failures = [row["id"] for row in source_snapshots if row.get("status") == "failed"]
            if failures:
                violations.append("critical source failures: " + ", ".join(failures))
        required_sources = int(guardrails.get("min_independent_sources_for_auto_commit") or 0)
        successful_sources = len([row for row in source_snapshots if row.get("status") == "success"])
        if required_sources and successful_sources < required_sources:
            violations.append(
                f"successful sources {successful_sources} below required {required_sources}"
            )
        max_delta = guardrails.get("max_single_run_probability_delta")
        if max_delta is None:
            max_delta = guardrails.get("max_auto_delta")
        if max_delta is not None:
            prior_probability = self._numeric_probability(prior_payload)
            proposed_probability = self._numeric_probability(proposed_payload)
            if prior_probability is not None and proposed_probability is not None:
                delta = abs(proposed_probability - prior_probability)
                if delta > float(max_delta):
                    violations.append(
                        f"proposed probability delta {delta:.3f} exceeds max {float(max_delta):.3f}"
                    )
        return violations

    @staticmethod
    def _is_learning_alert_reason(reason: str | None) -> bool:
        text = str(reason or "")
        return text in {"calibration_lesson_review", "domain_error_profile_review"} or text.startswith(
            "domain_error_profile_applies:"
        )

    def create_alert(
        self,
        *,
        severity: str,
        scope_type: str,
        scope_ref: str,
        reason: str,
        recommended_action: str,
    ) -> AlertEvent:
        alert_id = f"al_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alert_events (
                    id, created_at, severity, scope_type, scope_ref, reason,
                    recommended_action
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id,
                    utc_now_iso(),
                    severity,
                    scope_type,
                    scope_ref,
                    reason,
                    recommended_action,
                ),
            )
        return self.get_alert(alert_id)

    def get_alert(self, alert_id: str) -> AlertEvent:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM alert_events WHERE id = ?", (alert_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"alert not found: {alert_id}")
        return self._row_to_alert(row)

    def list_alerts(self, *, unresolved_only: bool = True) -> list[AlertEvent]:
        where = "WHERE acknowledged_at IS NULL" if unresolved_only else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM alert_events {where} ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def acknowledge_alert(self, alert_id: str, *, acknowledged_at: str | None = None) -> AlertEvent:
        self.get_alert(alert_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE alert_events SET acknowledged_at = ? WHERE id = ?",
                (parse_timestamp(acknowledged_at, field_name="acknowledged_at") or utc_now_iso(), alert_id),
            )
        return self.get_alert(alert_id)

    def record_alert_attempt(self, alert_id: str, *, now: str | None = None) -> AlertEvent:
        """Record a FAILED paid-tier resolution attempt: stamp ``last_attempted_at``
        and increment ``attempt_count`` so the per-alert exponential backoff window
        opens.

        This is the *opposite* of an acknowledgement — it NEVER sets
        ``acknowledged_at``. The alert stays OPEN (the underlying condition still
        holds, so it must re-surface) but is now COOLED DOWN: the continuous paid
        (LLM) tier will not re-attempt it until the backoff window elapses, so an
        unattended loop cannot re-spend on the same gated/failing alert every cycle.
        Each repeated failure (after the window passes and it is retried) bumps
        ``attempt_count`` again, doubling the next window. Idempotency is NOT a goal
        here — every real spend that failed should advance the count.
        """
        self.get_alert(alert_id)  # raises LedgerNotFoundError on an unknown id
        stamped = parse_timestamp(now, field_name="now") or utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                "UPDATE alert_events "
                "SET last_attempted_at = ?, attempt_count = COALESCE(attempt_count, 0) + 1 "
                "WHERE id = ?",
                (stamped, alert_id),
            )
        return self.get_alert(alert_id)

    # Default re-surface window for a dismissed group (the design's TTL). A
    # dismissal silences a group for this many days; once the window elapses the
    # group re-surfaces (self_check re-emits the alert IF the condition still
    # holds). A dismissal is NEVER an indefinite silence.
    DISMISS_TTL_DAYS_DEFAULT = 7

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
        """Explicitly DISMISS (silence) a set of OPEN alerts — a RECORDED human
        silence, NOT a resolution.

        This is the bulk "ignore-this-group" path. It bulk-sets ``acknowledged_at``
        on every still-OPEN alert in ``alert_ids`` (so the group drops out of the
        open backlog) WITHOUT invoking any runner and WITHOUT doing any gated
        forecast work. Crucially it ALSO stamps the dismissal audit trail
        (``dismissed_at`` / ``dismiss_note`` / ``dismiss_actor`` / ``dismiss_reason``
        / ``dismiss_ttl_days``), which is what makes a dismissal auditable and
        visibly distinct from a runner-resolution (the latter leaves
        ``dismissed_at`` NULL). The silence is bounded: after ``ttl_days`` the group
        re-surfaces (``self_check`` respects an active dismissal and re-emits once
        the window elapses — see :meth:`active_dismissal_keys`).

        A non-empty ``note`` is REQUIRED: a mass-dismiss must always carry a human
        rationale (no silent bare-ack). Already-acknowledged alerts are skipped (a
        dismissal never overwrites a real resolution). Returns the alerts that were
        actually dismissed.
        """
        if not (note or "").strip():
            raise ValueError("dismiss_alerts requires a non-empty note (no silent mass-dismiss)")
        if not (actor or "").strip():
            raise ValueError("dismiss_alerts requires a non-empty actor")
        ttl = self.DISMISS_TTL_DAYS_DEFAULT if ttl_days is None else int(ttl_days)
        if ttl <= 0:
            raise ValueError("dismiss_alerts ttl_days must be a positive number of days")
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        note_text = note.strip()
        actor_text = actor.strip()
        reason_text = (dismiss_reason or "").strip() or None

        dismissed_ids: list[str] = []
        seen: set[str] = set()
        with self._connect() as conn:
            for alert_id in alert_ids:
                if not alert_id or alert_id in seen:
                    continue
                seen.add(alert_id)
                row = conn.execute(
                    "SELECT acknowledged_at FROM alert_events WHERE id = ?", (alert_id,)
                ).fetchone()
                if row is None:
                    continue
                if row["acknowledged_at"] is not None:
                    # Already resolved/dismissed — never clobber a real resolution.
                    continue
                conn.execute(
                    """
                    UPDATE alert_events
                       SET acknowledged_at = ?,
                           dismissed_at = ?,
                           dismiss_note = ?,
                           dismiss_actor = ?,
                           dismiss_reason = ?,
                           dismiss_ttl_days = ?
                     WHERE id = ? AND acknowledged_at IS NULL
                    """,
                    (now_ts, now_ts, note_text, actor_text, reason_text, ttl, alert_id),
                )
                dismissed_ids.append(alert_id)
        # Re-read AFTER the write transaction has committed so the returned objects
        # reflect the persisted dismissal trail (get_alert opens its own connection,
        # which would not see the still-open transaction's uncommitted rows).
        return [self.get_alert(alert_id) for alert_id in dismissed_ids]

    def active_dismissal_keys(self, *, now: str | None = None) -> "set[tuple[str, str]]":
        """The ``(scope_ref, reason)`` pairs currently inside an UNEXPIRED dismissal
        window — the silences ``self_check`` must respect so a dismissed group is
        not immediately re-emitted.

        A dismissal is active while ``dismissed_at + dismiss_ttl_days >= now``. Once
        the window elapses the pair drops out of this set, so the very next
        ``self_check`` re-creates the alert IF the underlying condition still holds —
        i.e. the group RE-SURFACES after the TTL rather than being silenced forever.
        """
        now_dt = timestamp_to_datetime(parse_timestamp(now, field_name="now") or utc_now_iso())
        active: set[tuple[str, str]] = set()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT scope_ref, reason, dismissed_at, dismiss_ttl_days "
                "FROM alert_events WHERE dismissed_at IS NOT NULL"
            ).fetchall()
        for row in rows:
            dismissed_dt = timestamp_to_datetime(row["dismissed_at"])
            if dismissed_dt is None:
                continue
            ttl = row["dismiss_ttl_days"]
            ttl_days = int(ttl) if ttl is not None else self.DISMISS_TTL_DAYS_DEFAULT
            if dismissed_dt + timedelta(days=ttl_days) >= now_dt:
                active.add((row["scope_ref"], row["reason"]))
        return active

    def reconcile_alerts(self, *, now: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        """Close the loop: source-changed -> evidence-imported -> forecast-updated
        -> acknowledged. A question-scoped alert that fired BEFORE both fresh
        evidence was imported AND a new forecast snapshot was committed has already
        been consumed by the operator/agent — leaving it open is just alert fatigue,
        so acknowledge it. Alerts still missing evidence or an update stay open with
        an explicit reason. dry_run reports what WOULD be acknowledged without
        mutating (so a cautious caller can preview). Idempotent.

        Acking liberally (any fresh evidence + any forecast update after the alert,
        not necessarily from the alert's exact source) is intentional + safe for
        source-driven alerts: it clears the backlog the operator already worked
        past, and if the underlying source is still dirty the next self_check
        re-raises a fresh alert — so a genuinely-open signal is never lost.

        EXCEPTION — the MANUAL classes (NO_AUTO: domain-error profiles, assumption /
        reference-class checks, central-in-band, calibration-lesson review; and
        CONTESTED_LABEL: a triage auto-label the verifier disputes) are explicitly
        EXCLUDED from auto-ack. These are human-judgment alerts the warning
        dispatcher deliberately *surfaces* and never auto-resolves, and a new
        forecast + fresh evidence does NOT address them (an invalidated assumption
        is still invalidated; a band is still off-centre; a contested label is
        closed only when the operator records a real expert label via
        relabel_route). Reconciling one on unrelated forecast activity would
        silently close a still-valid signal the operator must act on — the same
        bare-ack the dispatcher forbids — so they always stay OPEN here."""
        now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
        # Local import keeps reconcile_alerts free of any module import-order
        # coupling with the (model-only) warnings dispatcher.
        from forecasting.warnings import ResolutionKind, classify_warning

        reconciled: list[dict[str, Any]] = []
        still_open: list[dict[str, Any]] = []

        for alert in self.list_alerts(unresolved_only=True):
            if alert.scope_type != "question":
                still_open.append(
                    {"id": alert.id, "reason": alert.reason, "open_because": "scope is not a single question"}
                )
                continue

            if classify_warning(alert.reason) in (
                ResolutionKind.NO_AUTO,
                ResolutionKind.CONTESTED_LABEL,
            ):
                still_open.append(
                    {
                        "id": alert.id,
                        "reason": alert.reason,
                        "open_because": "manual class (no-auto / contested-label) — surfaced for human review, never auto-reconciled",
                    }
                )
                continue

            question_id = alert.scope_ref

            # under_saturated is a SCORE-based signal, not an evidence-based one: it
            # clears when the current snapshot's STORED saturation score is back
            # at/above the bar, regardless of whether new evidence was imported. A
            # non-evidence re-saturation (added reasoning tags, a re-run panel, a
            # fuller decomposition) is a legitimate fix; the score on an immutable
            # snapshot only rises via a fresh commit, so a current score >= bar
            # already implies a re-forecast landed. Evidence-gated reconcile would
            # leave an evidence-free re-saturation stuck open forever (alert fatigue,
            # since the deduped sweep won't re-raise it).
            if alert.reason == self._SATURATION_ALERT_REASON:
                _sat_score: float | None = None
                _sat_bar: float | None = None
                try:
                    from forecasting.hooks import saturation_summary, sweep_alert_threshold

                    _snap = self.get_current_snapshot(question_id)
                    _meta = getattr(_snap, "metadata", None) if _snap is not None else None
                    _summary = saturation_summary(_meta.get("saturation") if isinstance(_meta, dict) else None)
                    _raw = _summary.get("score") if _summary else None
                    _sat_score = float(_raw) if isinstance(_raw, (int, float)) else None
                    _sat_bar = float(sweep_alert_threshold())
                except Exception:
                    _sat_score, _sat_bar = None, None
                if _sat_score is not None and _sat_bar is not None and _sat_score >= _sat_bar:
                    if not dry_run:
                        self.acknowledge_alert(alert.id, acknowledged_at=now_ts)
                    reconciled.append({"id": alert.id, "reason": alert.reason, "scope_ref": question_id})
                else:
                    still_open.append({
                        "id": alert.id,
                        "reason": alert.reason,
                        "open_because": (
                            "saturation still below the bar"
                            if _sat_score is not None
                            else "no saturation score on the current snapshot"
                        ),
                    })
                continue

            try:
                evidence_after = any(
                    (getattr(item, "captured_at", None) or getattr(item, "available_at", None) or "") > alert.created_at
                    for item in self.list_evidence(question_id)
                )
            except Exception:
                evidence_after = False

            snapshot = None
            try:
                snapshot = self.get_current_snapshot(question_id)
            except Exception:
                snapshot = None
            snapshot_ts = (getattr(snapshot, "created_at", None) or getattr(snapshot, "as_of", None) or "") if snapshot else ""
            update_after = bool(snapshot_ts and snapshot_ts > alert.created_at)

            if evidence_after and update_after:
                if not dry_run:
                    self.acknowledge_alert(alert.id, acknowledged_at=now_ts)
                reconciled.append({"id": alert.id, "reason": alert.reason, "scope_ref": question_id})
            else:
                missing = []
                if not evidence_after:
                    missing.append("no fresh evidence imported since the alert")
                if not update_after:
                    missing.append("no forecast update committed since the alert")
                still_open.append({"id": alert.id, "reason": alert.reason, "open_because": "; ".join(missing)})

        return {
            "reconciled": reconciled,
            "reconciled_count": len(reconciled),
            "still_open": still_open,
            "dry_run": dry_run,
        }

    def self_check(
        self,
        *,
        question_id: str | None = None,
        domain: str | None = None,
        topic: str | None = None,
        horizon: str | None = None,
        portfolio: str | None = None,
        stale_days: int = 7,
        now: str | None = None,
        auto_score: bool = False,
        auto_postmortem: bool = False,
        confidence_below: float | None = None,
        confidence_above: float | None = None,
        large_delta_threshold: float | None = None,
    ) -> list[AlertEvent]:
        self._validate_confidence_filters(
            confidence_below=confidence_below,
            confidence_above=confidence_above,
        )
        self._validate_probability_threshold(
            large_delta_threshold,
            field_name="large_delta_threshold",
        )
        if question_id:
            questions = [self.get_question(question_id)]
        else:
            questions = self.list_questions(domain=domain)
            if topic:
                questions = [q for q in questions if topic in q.topics]
            if horizon:
                questions = [
                    q
                    for q in questions
                    if (snapshot := self.get_current_snapshot(q.id)) is not None
                    and self._horizon_matches(snapshot.forecast_horizon_days, horizon)
                ]
            if portfolio:
                questions = [q for q in questions if self._question_in_portfolio(q, portfolio)]
        if confidence_below is not None or confidence_above is not None:
            questions = [
                q
                for q in questions
                if self._question_matches_confidence(
                    q.id,
                    confidence_below=confidence_below,
                    confidence_above=confidence_above,
                )
            ]

        # Respect any UNEXPIRED dismissal (Slice 5): a group an operator explicitly
        # silenced must NOT be re-emitted while its TTL window is live. Once the
        # window elapses the (scope_ref, reason) pair drops out of this set and the
        # alert is re-created below — i.e. the group RE-SURFACES after the TTL.
        active_dismissals = self.active_dismissal_keys(now=now)

        alerts: list[AlertEvent] = []
        for row in self.review_questions(
            stale=True,
            last_days=stale_days,
            domain=domain,
            topic=topic,
            horizon=horizon,
            confidence_below=confidence_below,
            confidence_above=confidence_above,
            large_delta_threshold=large_delta_threshold,
            now=now,
        ):
            question = row["question"]
            if question_id and question.id != question_id:
                continue
            if portfolio and not self._question_in_portfolio(question, portfolio):
                continue
            for reason in row["reasons"]:
                if (question.id, reason) in active_dismissals:
                    continue  # silenced by an active dismissal — re-surfaces after TTL
                action = self._recommended_action(reason)
                alerts.append(
                    self.create_alert(
                        severity="warning" if reason != "resolution_check_due" else "high",
                        scope_type="question",
                        scope_ref=question.id,
                        reason=reason,
                        recommended_action=action,
                    )
                )
        # Dedupe guard (mirrors check_update_triggers' open_reasons set): re-running
        # self_check before reconcile must NOT accumulate duplicate postmortem_due
        # alerts for the same question. One open postmortem alert per question until
        # it is acknowledged. Both severity variants (postmortem_due /
        # high_impact_postmortem_due) count as "already surfaced" for this question.
        open_postmortem_questions = {
            alert.scope_ref
            for alert in self.list_alerts(unresolved_only=True)
            if alert.scope_type == "question"
            and alert.reason in ("postmortem_due", "high_impact_postmortem_due")
        }
        for question in questions:
            if question.status != "resolved":
                continue
            if self.get_latest_resolution(question.id, confirmed_only=True) is None:
                continue
            current = self.get_current_snapshot(question.id)
            scores = [score for score in self.list_scores() if score.question_id == question.id]
            if current is not None and not scores:
                if auto_score:
                    try:
                        score = self.score_question(question.id)
                    except ForecastingError as exc:
                        alerts.append(
                            self.create_alert(
                                severity="high",
                                scope_type="question",
                                scope_ref=question.id,
                                reason="score_blocked",
                                recommended_action=f"Inspect resolution and scoring setup: {exc}",
                            )
                        )
                        continue
                    alerts.append(
                        self.create_alert(
                            severity="info",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"score_created:{score.id}",
                            recommended_action="Run `forecast postmortem` so the score can update calibration memory.",
                        )
                    )
                    scores = [score]
                else:
                    high_impact = self._is_high_impact_question(question)
                    alerts.append(
                        self.create_alert(
                            severity="high",
                            scope_type="question",
                            scope_ref=question.id,
                            reason="high_impact_score_due" if high_impact else "score_due",
                            recommended_action=(
                                "Prioritize scoring this high-impact confirmed resolution before updating calibration memory."
                                if high_impact
                                else "Run `forecast score` for the confirmed resolution."
                            ),
                        )
                    )
                    continue
            if scores and not self.list_postmortems(question.id):
                if auto_postmortem:
                    latest_score = scores[0]
                    postmortem = self.create_postmortem(
                        question_id=question.id,
                        summary="Auto-created by forecast self-check after confirmed resolution and scoring.",
                        what_happened="The forecast resolved and was scored during a scheduled or manual self-check.",
                        what_was_expected="See the linked forecast snapshot and score record for the prior probability.",
                        lesson=self._auto_postmortem_lesson(question, latest_score),
                        calibration_adjustment=self._auto_postmortem_adjustment(question, latest_score),
                    )
                    alerts.append(
                        self.create_alert(
                            severity="info",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"postmortem_created:{postmortem['id']}",
                            recommended_action=(
                                "Review the auto-created postmortem and any tentative calibration lesson "
                                "before relying on it for future updates."
                            ),
                        )
                    )
                    continue
                if question.id in open_postmortem_questions:
                    continue  # one open postmortem_due alert per question until acked
                high_impact = self._is_high_impact_question(question)
                alerts.append(
                    self.create_alert(
                        severity="high" if high_impact else "warning",
                        scope_type="question",
                        scope_ref=question.id,
                        reason="high_impact_postmortem_due" if high_impact else "postmortem_due",
                        recommended_action=(
                            "Prioritize a postmortem for this high-impact resolution before reusing the lesson."
                            if high_impact
                            else "Run `forecast postmortem` so the resolved forecast can update learning artifacts."
                        ),
                    )
                )
                open_postmortem_questions.add(question.id)
        alerts.extend(self._domain_error_profile_alerts(domain=domain, topic=topic, questions=questions))
        alerts.extend(
            self._calibration_lesson_review_alerts(
                domain=domain,
                topic=topic,
                questions=questions,
            )
        )
        if not any([question_id, domain, topic, horizon, portfolio]):
            alerts.extend(self._benchmark_evidence_alerts())
        watch_scope_type, watch_scope_ref = self._self_check_watch_scope(
            question_id=question_id,
            domain=domain,
            topic=topic,
            portfolio=portfolio,
        )
        alerts.extend(
            self.check_watched_sources(
                scope_type=watch_scope_type,
                scope_ref=watch_scope_ref,
                now=now,
            )
        )
        # Fire executable update_triggers for in-scope questions against their
        # latest imported values (idempotent — one open alert per source).
        for question in questions:
            if any(trigger.get("operator") for trigger in question.update_triggers):
                alerts.extend(self.check_update_triggers(question_id=question.id, now=now))
        return alerts

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

        non_manual_source_types = {"manual_note", "note"}
        for question in questions:
            snapshots = self.list_snapshots(question.id)
            evidence = self.list_evidence(question.id)
            model_runs = self.list_model_runs(question.id)
            reference_classes = self.list_reference_classes(question.id)
            resolution = self.get_latest_resolution(question.id, confirmed_only=False)
            postmortems = self.list_postmortems(question.id)
            scores = [score for score in self.list_scores() if score.question_id == question.id]
            source_types = Counter(item.source_type or "unknown" for item in evidence)
            structured_source_types = sorted(
                source_type for source_type in source_types if source_type not in non_manual_source_types
            )

            if snapshots:
                questions_with_forecasts += 1
            if evidence:
                questions_with_evidence += 1
            if structured_source_types:
                questions_with_structured_sources += 1
            if model_runs:
                questions_with_models += 1
            if reference_classes:
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
                    "forecast_count": len(snapshots),
                    "evidence_count": len(evidence),
                    "source_types": dict(sorted(source_types.items())),
                    "structured_source_types": structured_source_types,
                    "reference_class_count": len(reference_classes),
                    "model_run_count": len(model_runs),
                    "score_count": len(scores),
                    "postmortem_count": len(postmortems),
                    "resolved": resolution is not None,
                }
            )

        scores = self.list_scores()
        score_origin_counts.update(score.forecast_origin for score in scores)
        postmortems = self.list_postmortems()
        schedules = self.list_scheduled_reviews()
        scheduled_review_runs = self.list_scheduled_review_runs(limit=1000)
        watched_sources = self.list_watched_sources(status=None)
        autopilot_policies = self.list_autopilot_policies(enabled_only=False)
        autopilot_runs = self.list_autopilot_runs(limit=1000)
        forecast_update_proposals = self.list_forecast_update_proposals(status=None, limit=1000)
        alerts = self.list_alerts(unresolved_only=False)
        open_alert_count = sum(1 for alert in alerts if alert.acknowledged_at is None)
        open_learned_error_review_alerts = [
            alert
            for alert in alerts
            if alert.acknowledged_at is None
            and str(alert.reason or "").startswith("domain_error_profile_applies:")
        ]
        lessons = self.list_calibration_lessons()
        active_lessons = [lesson for lesson in lessons if lesson["status"] == "active"]

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
                len([row for row in schedules if row.get("enabled")]),
                min_scheduled_reviews,
                "Schedule review work with `forecast schedule add --question <id> ...`.",
            ),
            check(
                "scheduled_self_check_runs",
                "scheduled self-checks run",
                len(scheduled_review_runs),
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
                len(postmortems),
                min_postmortems,
                "Write at least one postmortem with `forecast postmortem <id> ...`.",
            ),
            max_check(
                "learned_error_reviews_cleared",
                "open learned-error profile review alerts",
                len(open_learned_error_review_alerts),
                0,
                "Review active forecasts flagged by learned error profiles, then acknowledge the alerts with `forecast alerts --ack <id>`.",
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
                "postmortem_count": len(postmortems),
                "scheduled_review_count": len(schedules),
                "enabled_scheduled_review_count": len([row for row in schedules if row.get("enabled")]),
                "scheduled_review_run_count": len(scheduled_review_runs),
                "watched_source_count": len(watched_sources),
                "autopilot_policy_count": len(autopilot_policies),
                "active_autopilot_policy_count": len(
                    [row for row in autopilot_policies if row.get("enabled")]
                ),
                "autopilot_run_count": len(autopilot_runs),
                "pending_autopilot_proposal_count": len(
                    [row for row in forecast_update_proposals if row.get("status") == "pending"]
                ),
                "alert_count": len(alerts),
                "open_alert_count": open_alert_count,
                "open_learned_error_review_alert_count": len(open_learned_error_review_alerts),
                "calibration_lesson_count": len(lessons),
                "active_calibration_lesson_count": len(active_lessons),
            },
            "domains": dict(sorted(domain_counts.items())),
            "topics": dict(sorted(topic_counts.items())),
            "source_types": dict(sorted(source_type_counts.items())),
            "questions": question_rows,
        }

    def export_question(self, question_id: str, *, fmt: str = "markdown") -> str:
        question = self.get_question(question_id)
        snapshots = self.list_snapshots(question_id)
        evidence = self.list_evidence(question_id)
        assumptions = self.list_assumptions(question_id)
        reference_classes = self.list_reference_classes(question_id)
        model_runs = self.list_model_runs(question_id)
        source_snapshots = self.list_source_snapshots(question_id=question_id, limit=1000)
        watched_sources = self.list_watched_sources(scope_type="question", scope_ref=question_id, status=None)
        scheduled_reviews = [
            row
            for row in self.list_scheduled_reviews()
            if row.get("scope_type") == "question" and row.get("scope_ref") == question_id
        ]
        scheduled_review_runs = [
            run
            for review in scheduled_reviews
            for run in self.list_scheduled_review_runs(scheduled_review_id=review["id"], limit=100)
        ]
        autopilot_policies = self.list_autopilot_policies(question_id=question_id, enabled_only=False)
        autopilot_runs = self.list_autopilot_runs(question_id=question_id, limit=100)
        forecast_update_proposals = self.list_forecast_update_proposals(question_id=question_id, status=None, limit=100)
        postmortems = self.list_postmortems(question_id, include_invalidated=True)
        baselines = self.list_baseline_comparisons(question_id)
        resolution = self.get_latest_resolution(question_id)
        scores = [s for s in self.list_scores(include_invalidated=True) if s.question_id == question_id]
        calibration_lessons = self._calibration_lessons_for_question(scores, postmortems)
        domain_error_profiles = self._domain_error_profiles_for_question(question)
        corrections = self._corrections_for_question(
            question_id=question_id,
            snapshots=snapshots,
            evidence=evidence,
            assumptions=assumptions,
            reference_classes=reference_classes,
            model_runs=model_runs,
            resolution=resolution,
            scores=scores,
            postmortems=postmortems,
            calibration_lessons=calibration_lessons,
        )
        related_forecasts, related_shared_sources = self.related_forecast_views(question_id)
        if fmt == "json":
            return json_dumps(
                {
                    "product": _export_metadata(),
                    "generated_at": utc_now_iso(),
                    "question": self._question_to_dict(question),
                    "forecast_history": [self._snapshot_to_dict(snapshot) for snapshot in snapshots],
                    "evidence": [self._evidence_to_dict(item) for item in evidence],
                    "assumptions": assumptions,
                    "reference_classes": reference_classes,
                    "model_runs": model_runs,
                    "source_snapshots": source_snapshots,
                    "watched_sources": watched_sources,
                    "scheduled_reviews": scheduled_reviews,
                    "scheduled_review_runs": scheduled_review_runs,
                    "autopilot_policies": autopilot_policies,
                    "autopilot_runs": autopilot_runs,
                    "forecast_update_proposals": forecast_update_proposals,
                    "baseline_comparisons": baselines,
                    "resolution": self._resolution_to_dict(resolution) if resolution else None,
                    "scores": [self._score_to_dict(score) for score in scores],
                    "postmortems": postmortems,
                    "calibration_lessons": calibration_lessons,
                    "domain_error_profiles": domain_error_profiles,
                    "corrections": corrections,
                    "panel_runs": self.list_panel_runs(question_id, limit=20),
                    "analyst_notes": self.list_analyst_notes(question_id),
                    "analyst_note": self.latest_analyst_note(question_id, kind="brief"),
                    "retrospective": self.latest_analyst_note(question_id, kind="retrospective"),
                    # forecast_links round-trips the raw edges; related_forecasts /
                    # related_shared_sources are the derived audit copy the TUI reads.
                    "forecast_links": self.list_forecast_links(question_id, direction="both"),
                    # Thesis membership + entities round-trip the raw rows; the
                    # import orphan-guard skips edges whose endpoint questions
                    # aren't also in the packet.
                    "thesis_members": self.list_thesis_members(question_id),
                    "thesis_entities": self.list_thesis_entities(question_id),
                    "related_forecasts": related_forecasts,
                    "related_shared_sources": [{"signature": s} for s in related_shared_sources],
                }
            )
        if fmt != "markdown":
            raise ValidationError("export format must be markdown or json")
        lines = [
            f"# Forecast Packet: {question.title}",
            "",
            f"- Product: {PRODUCT_NAME}",
            f"- North star: {NORTH_STAR}",
            f"- ID: `{question.id}`",
            f"- Generated at: {utc_now_iso()}",
            f"- Status: {question.status}",
            f"- Domain: {question.domain or ''}",
            f"- Close time: {question.close_time or ''}",
            f"- Resolution time: {question.resolution_time or ''}",
            f"- Resolution criteria: {question.resolution_criteria}",
            "",
            "## Current Forecast",
        ]
        current = snapshots[-1] if snapshots else None
        if current:
            lines.extend(
                [
                    f"- Forecast ID: `{current.forecast_id}`",
                    f"- As of: {current.as_of}",
                    f"- Probability/distribution: `{current.probability_or_distribution}`",
                    f"- Confidence: {current.confidence if current.confidence is not None else ''}",
                    f"- Rationale: {current.rationale}",
                    "",
                ]
            )
        else:
            lines.extend(["No forecast snapshot recorded.", ""])
        lines.append("## Forecast History")
        if snapshots:
            for snapshot in snapshots:
                lines.append(
                    f"- {snapshot.as_of}: `{snapshot.probability_or_distribution}` "
                    f"({snapshot.method or 'unspecified'}) - {snapshot.rationale}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Evidence"])
        if evidence:
            for item in evidence:
                label = item.source_url or item.source_name or "manual note"
                lines.append(f"- {item.available_at}: {label} - {item.claim or item.summary}")
        else:
            lines.append("- None")
        lines.extend(["", "## Assumptions"])
        if assumptions:
            for item in assumptions:
                lines.append(f"- {item['status']}: {item['text']}")
        else:
            lines.append("- None")
        lines.extend(["", "## Reference Classes"])
        if reference_classes:
            for item in reference_classes:
                lines.append(
                    f"- {item['name']}: base_rate={item['base_rate']} "
                    f"uncertainty={item['base_rate_uncertainty']}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Model Runs"])
        if model_runs:
            for item in model_runs:
                lines.append(f"- {item['created_at']}: {item['model_type']} `{item['id']}`")
        else:
            lines.append("- None")
        lines.extend(["", "## Watched Sources"])
        if watched_sources:
            for item in watched_sources:
                lines.append(f"- {item['id']} {item['scope_type']}:{item['scope_ref']} {item['source_type']} {item['source']}")
        else:
            lines.append("- None")
        lines.extend(["", "## Scheduled Self-Checks"])
        if scheduled_reviews:
            for item in scheduled_reviews:
                lines.append(
                    f"- {item['id']} {item['scope_type']}:{item['scope_ref']} "
                    f"cadence={item['cadence']} next={item['next_run_at']} "
                    f"learning=score:{bool(item.get('auto_score'))}/postmortem:{bool(item.get('auto_postmortem'))}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Scheduled Self-Check Runs"])
        if scheduled_review_runs:
            for item in scheduled_review_runs:
                lines.append(
                    f"- {item['id']} schedule={item['scheduled_review_id']} "
                    f"run_at={item['run_at']} alerts={item['alert_count']} "
                    f"scores={item['score_count']} postmortems={item['postmortem_count']} "
                    f"learning_reviews={item['learning_review_count']} next={item['next_run_at']}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Autopilot"])
        if autopilot_policies:
            for item in autopilot_policies:
                lines.append(
                    f"- {item['id']} mode={item['mode']} cadence={item['cadence']} "
                    f"enabled={item['enabled']}"
                )
        else:
            lines.append("- None")
        if forecast_update_proposals:
            lines.append("")
            lines.append("### Update Proposals")
            for item in forecast_update_proposals:
                lines.append(
                    f"- {item['id']} {item['status']}: prior={item['prior_forecast_id']} "
                    f"run={item['run_id']}"
                )
        lines.extend(["", "## Resolution"])
        if resolution:
            lines.append(
                f"- {resolution.resolved_at}: `{resolution.outcome}` "
                f"({resolution.resolution_status}, criteria_satisfied={resolution.criteria_satisfied})"
            )
        else:
            lines.append("- Unresolved")
        lines.extend(["", "## Scores"])
        if scores:
            for score in scores:
                suffix = f", invalidated_by={score.invalidated_by_correction_id}" if score.invalidated_by_correction_id else ""
                lines.append(
                    f"- {score.scored_at}: Brier={score.brier_score}, "
                    f"bucket={score.calibration_bucket}, origin={score.forecast_origin}{suffix}"
                )
        else:
            lines.append("- None")
        lines.extend(["", "## Postmortems"])
        if postmortems:
            for item in postmortems:
                suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
                lines.append(f"- {item['created_at']}: {item['summary']}{suffix}")
        else:
            lines.append("- None")
        lines.extend(["", "## Calibration Lessons"])
        if calibration_lessons:
            for item in calibration_lessons:
                suffix = f" invalidated_by={item['invalidated_by_correction_id']}" if item.get("invalidated_by_correction_id") else ""
                lines.append(f"- {item['id']} {item['status']}: {item['lesson']}{suffix}")
        else:
            lines.append("- None")
        lines.extend(["", "## Corrections"])
        if corrections:
            for item in corrections:
                lines.append(f"- {item['id']} {item['status']}: {item['target_type']} `{item['target_id']}` - {item['reason']}")
        else:
            lines.append("- None")
        return "\n".join(lines) + "\n"

    def export_all(self, *, fmt: str = "markdown") -> str:
        questions = self.list_questions()
        if fmt == "json":
            return json_dumps(
                {
                    "product": _export_metadata(),
                    "generated_at": utc_now_iso(),
                    "questions": [
                        json_loads(self.export_question(question.id, fmt="json"), {})
                        for question in questions
                    ],
                    "ingest_candidates": self.list_ingest_candidates(),
                    "source_snapshots": self.list_source_snapshots(),
                    "watched_sources": self.list_watched_sources(status=None),
                    "scheduled_reviews": self.list_scheduled_reviews(),
                    "scheduled_review_runs": self.list_scheduled_review_runs(limit=1000),
                    "autopilot_policies": self.list_autopilot_policies(enabled_only=False),
                    "autopilot_runs": self.list_autopilot_runs(limit=1000),
                    "forecast_update_proposals": self.list_forecast_update_proposals(status=None),
                    "domain_error_profiles": self.list_domain_error_profiles(),
                    "alerts": [alert.__dict__ for alert in self.list_alerts(unresolved_only=False)],
                }
            )
        if fmt != "markdown":
            raise ValidationError("export format must be markdown or json")
        lines = [
            "# Forecast Portfolio Export",
            "",
            f"- Product: {PRODUCT_NAME}",
            f"- North star: {NORTH_STAR}",
            f"- Generated at: {utc_now_iso()}",
            f"- Questions: {len(questions)}",
            "",
        ]
        for question in questions:
            lines.append(self.export_question(question.id, fmt="markdown"))
        return "\n".join(lines)

    def import_packet(self, packet: dict[str, Any], *, conflict: str = "error") -> dict[str, Any]:
        """Import a JSON packet produced by ``export_question`` or ``export_all``."""

        if conflict not in {"error", "skip", "replace"}:
            raise ValidationError("conflict must be error, skip, or replace")
        if not isinstance(packet, dict):
            raise ValidationError("forecast packet must be a JSON object")

        question_packets = self._question_packets_from_import(packet)
        if not question_packets and not any(
            isinstance(packet.get(key), list)
            for key in (
                "ingest_candidates",
                "watched_sources",
                "source_snapshots",
                "scheduled_reviews",
                "scheduled_review_runs",
                "autopilot_policies",
                "autopilot_runs",
                "forecast_update_proposals",
                "domain_error_profiles",
                "alerts",
            )
        ):
            raise ValidationError("forecast packet has no importable records")

        summary: dict[str, Any] = {
            "product": _export_metadata(),
            "imported_at": utc_now_iso(),
            "source_product": packet.get("product") if isinstance(packet.get("product"), dict) else None,
            "source_generated_at": packet.get("generated_at"),
            "conflict": conflict,
            "imported": defaultdict(int),
            "skipped_existing": 0,
            "replaced_existing": 0,
            "duplicates_in_packet": 0,
        }
        seen: set[tuple[str, str]] = set()

        with self._connect() as conn:
            for question_packet in question_packets:
                self._import_question_packet(conn, question_packet, conflict=conflict, summary=summary, seen=seen)
            self._import_packet_rows(
                conn,
                "ingest_candidates",
                packet.get("ingest_candidates"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "watched_sources",
                packet.get("watched_sources"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "source_snapshots",
                packet.get("source_snapshots"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "scheduled_reviews",
                packet.get("scheduled_reviews"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "scheduled_review_runs",
                packet.get("scheduled_review_runs"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "autopilot_policies",
                packet.get("autopilot_policies"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "autopilot_runs",
                packet.get("autopilot_runs"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "forecast_update_proposals",
                packet.get("forecast_update_proposals"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "domain_error_profiles",
                packet.get("domain_error_profiles"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )
            self._import_packet_rows(
                conn,
                "alert_events",
                packet.get("alerts"),
                conflict=conflict,
                summary=summary,
                seen=seen,
            )

        imported = dict(sorted(summary["imported"].items()))
        summary["imported"] = imported
        summary["imported_total"] = sum(imported.values())
        return summary

    def _question_packets_from_import(self, packet: dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(packet.get("question"), dict):
            return [packet]
        questions = packet.get("questions")
        if questions is None:
            return []
        if not isinstance(questions, list):
            raise ValidationError("forecast packet questions field must be a list")
        result: list[dict[str, Any]] = []
        for index, question_packet in enumerate(questions):
            if not isinstance(question_packet, dict):
                raise ValidationError(f"forecast packet question entry {index} must be an object")
            result.append(question_packet)
        return result

    def _import_question_packet(
        self,
        conn: sqlite3.Connection,
        packet: dict[str, Any],
        *,
        conflict: str,
        summary: dict[str, Any],
        seen: set[tuple[str, str]],
    ) -> None:
        question = packet.get("question")
        if not isinstance(question, dict):
            raise ValidationError("question packet must include a question object")
        self._insert_packet_row(conn, "forecast_questions", question, conflict=conflict, summary=summary, seen=seen)
        for table, key in (
            ("assumptions", "assumptions"),
            ("reference_classes", "reference_classes"),
            ("model_runs", "model_runs"),
            ("evidence_items", "evidence"),
            ("forecast_snapshots", "forecast_history"),
            ("resolutions", "resolution"),
            ("score_records", "scores"),
            ("postmortems", "postmortems"),
            ("calibration_lessons", "calibration_lessons"),
            ("forecast_corrections", "corrections"),
            ("baseline_comparisons", "baseline_comparisons"),
            ("watched_sources", "watched_sources"),
            ("source_snapshots", "source_snapshots"),
            ("scheduled_reviews", "scheduled_reviews"),
            ("scheduled_review_runs", "scheduled_review_runs"),
            ("autopilot_policies", "autopilot_policies"),
            ("autopilot_runs", "autopilot_runs"),
            ("forecast_update_proposals", "forecast_update_proposals"),
            ("domain_error_profiles", "domain_error_profiles"),
            ("analyst_notes", "analyst_notes"),
            # forecast_links + thesis membership/entities LAST so the endpoint
            # questions are imported first.
            ("forecast_links", "forecast_links"),
            ("thesis_members", "thesis_members"),
            ("thesis_entities", "thesis_entities"),
        ):
            self._import_packet_rows(conn, table, packet.get(key), conflict=conflict, summary=summary, seen=seen)

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
        if rows is None:
            return
        if isinstance(rows, dict):
            rows_to_import = [rows]
        elif isinstance(rows, list):
            rows_to_import = rows
        else:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} must be an object or list")
        for index, row in enumerate(rows_to_import):
            if row is None:
                continue
            if not isinstance(row, dict):
                raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} entry {index} must be an object")
            self._insert_packet_row(conn, table, row, conflict=conflict, summary=summary, seen=seen)

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
        pk = _PACKET_PRIMARY_KEYS.get(table, "id")
        record_id = str(row.get(pk) or "").strip()
        if not record_id:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} import row is missing {pk}")
        seen_key = (table, record_id)
        if seen_key in seen:
            summary["duplicates_in_packet"] += 1
            return
        seen.add(seen_key)

        # A link / membership / entity can reference a question not present in
        # this packet; with foreign_keys=ON that would IntegrityError. Skip the
        # dangling row rather than abort the import.
        _orphan_fk_columns = {
            "forecast_links": ("from_question_id", "to_question_id"),
            "thesis_members": ("thesis_question_id", "member_question_id"),
            "thesis_entities": ("thesis_question_id",),
        }.get(table)
        if _orphan_fk_columns:
            for column in _orphan_fk_columns:
                if conn.execute(
                    "SELECT 1 FROM forecast_questions WHERE id = ?", (row.get(column),)
                ).fetchone() is None:
                    summary["skipped_existing"] += 1
                    return

        existing = conn.execute(f"SELECT 1 FROM {table} WHERE {pk} = ?", (record_id,)).fetchone()
        if existing is not None:
            if conflict == "error":
                raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} record already exists: {record_id}")
            if conflict == "skip":
                summary["skipped_existing"] += 1
                return
            conn.execute(f"DELETE FROM {table} WHERE {pk} = ?", (record_id,))
            summary["replaced_existing"] += 1

        table_columns = [column["name"] for column in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        columns = [column for column in table_columns if column in row]
        if pk not in columns:
            raise ValidationError(f"{_PACKET_RECORD_LABELS[table]} import row is missing {pk}")
        json_fields = _PACKET_JSON_FIELDS.get(table, set())
        bool_fields = _PACKET_BOOL_FIELDS.get(table, set())
        values: list[Any] = []
        for column in columns:
            value = row[column]
            if column in json_fields:
                value = json_dumps(value)
            elif column in bool_fields:
                value = 1 if bool(value) else 0
            values.append(value)
        placeholders = ", ".join("?" for _ in columns)
        conn.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        summary["imported"][_PACKET_RECORD_LABELS[table]] += 1

    def _existing_score(self, forecast_id: str, resolution_id: str) -> ScoreRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM score_records
                WHERE forecast_id = ? AND resolution_id = ?
                  AND invalidated_by_correction_id IS NULL
                ORDER BY scored_at DESC
                LIMIT 1
                """,
                (forecast_id, resolution_id),
            ).fetchone()
        return self._row_to_score(row) if row else None

    def _validate_evidence_refs(
        self,
        question_id: str,
        evidence_refs: list[str],
        evidence_cutoff: str | None,
    ) -> None:
        if not evidence_refs:
            return
        cutoff_dt = timestamp_to_datetime(evidence_cutoff)
        for evidence_id in evidence_refs:
            evidence = self.get_evidence(evidence_id)
            if evidence.question_id != question_id:
                raise ValidationError(f"evidence {evidence_id} does not belong to question {question_id}")
            if cutoff_dt is None:
                continue
            available_dt = timestamp_to_datetime(evidence.available_at)
            if available_dt and available_dt > cutoff_dt:
                raise ValidationError(
                    f"evidence {evidence_id} was available after the evidence cutoff"
                )

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
        score_refs: list[str] = []
        postmortem_refs: list[str] = []
        lesson_refs: list[str] = []
        with self._connect() as conn:
            if target_type == "resolution":
                score_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM score_records WHERE resolution_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
                postmortem_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM postmortems WHERE resolution_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
            elif target_type == "score_record":
                score_refs = [target_id]
                postmortem_refs = [
                    row["id"]
                    for row in conn.execute(
                        "SELECT id FROM postmortems WHERE score_record_id = ?",
                        (target_id,),
                    ).fetchall()
                ]
            elif target_type == "postmortem":
                postmortem_refs = [target_id]
            elif target_type == "calibration_lesson":
                lesson_refs = [target_id]

            if postmortem_refs:
                all_lessons = conn.execute("SELECT id, source_postmortem_refs FROM calibration_lessons").fetchall()
                postmortem_set = set(postmortem_refs)
                for row in all_lessons:
                    refs = set(json_loads(row["source_postmortem_refs"], []))
                    if refs & postmortem_set:
                        lesson_refs.append(row["id"])
            if score_refs:
                all_lessons = conn.execute("SELECT id, source_score_record_refs FROM calibration_lessons").fetchall()
                score_set = set(score_refs)
                for row in all_lessons:
                    refs = set(json_loads(row["source_score_record_refs"], []))
                    if refs & score_set:
                        lesson_refs.append(row["id"])
        return sorted(set(score_refs)), sorted(set(postmortem_refs)), sorted(set(lesson_refs))

    def _invalidate_learning_records_for_correction(
        self,
        conn: sqlite3.Connection,
        *,
        correction_id: str,
        score_refs: list[str],
        postmortem_refs: list[str],
        lesson_refs: list[str],
    ) -> None:
        if score_refs:
            conn.executemany(
                "UPDATE score_records SET invalidated_by_correction_id = ? WHERE id = ?",
                [(correction_id, score_id) for score_id in score_refs],
            )
        if postmortem_refs:
            conn.executemany(
                "UPDATE postmortems SET invalidated_by_correction_id = ? WHERE id = ?",
                [(correction_id, postmortem_id) for postmortem_id in postmortem_refs],
            )
        if lesson_refs:
            conn.executemany(
                """
                UPDATE calibration_lessons
                SET invalidated_by_correction_id = ?, status = 'superseded', updated_at = ?
                WHERE id = ?
                """,
                [(correction_id, utc_now_iso(), lesson_id) for lesson_id in lesson_refs],
            )

    def _disable_backtest_calibration(self, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forecast_snapshots
                SET calibration_eligible = 0, calibration_weight = 0
                WHERE backtest_run_id = ? AND forecast_origin = 'backtest'
                """,
                (run_id,),
            )
            conn.execute(
                """
                UPDATE score_records
                SET calibration_eligible = 0, calibration_weight = 0
                WHERE forecast_origin = 'backtest'
                  AND forecast_id IN (
                    SELECT forecast_id FROM forecast_snapshots WHERE backtest_run_id = ?
                  )
                """,
                (run_id,),
            )

    def _run_backtest_case(
        self,
        *,
        run_id: str,
        case: dict[str, Any],
        default_cutoff: str | None,
        allow_calibration_memory: bool,
        leak_judge_runner: "LeakJudgeRunner | None" = None,
    ) -> dict[str, Any]:
        simulated_time = parse_timestamp(
            case.get("simulated_forecast_time") or case.get("as_of") or default_cutoff,
            field_name="simulated_forecast_time",
        )
        if simulated_time is None:
            raise ValidationError("each backtest case needs simulated_forecast_time, as_of, or --as-of")
        evidence_cutoff = parse_timestamp(
            case.get("evidence_cutoff") or simulated_time,
            field_name="evidence_cutoff",
        )
        assert evidence_cutoff is not None

        outcome_data = case.get("outcome_space") or {}
        outcome_space = OutcomeSpace.from_dict(outcome_data) if outcome_data else OutcomeSpace()
        question = self.create_question(
            title=str(case.get("title") or "Untitled backtest case"),
            description=str(case.get("description") or ""),
            resolution_criteria=str(case.get("resolution_criteria") or "Backtest dataset supplied resolution criteria."),
            resolution_source=case.get("resolution_source"),
            outcome_space=outcome_space,
            close_time=case.get("close_time"),
            resolution_time=case.get("resolution_time"),
            tags=list(case.get("tags") or ["backtest"]),
            domain=case.get("domain"),
            topics=list(case.get("topics") or []),
            metadata={"backtest_run_id": run_id, "external_id": case.get("id")},
        )

        excluded = 0
        ambiguous = 0
        leak_flagged = 0
        evidence_refs: list[str] = []
        cutoff_dt = timestamp_to_datetime(evidence_cutoff)
        for item in case.get("evidence") or []:
            available_raw = item.get("available_at") or item.get("published_at")
            if not available_raw:
                ambiguous += 1
                continue
            available = parse_timestamp(available_raw, field_name="available_at")
            available_dt = timestamp_to_datetime(available)
            if cutoff_dt and available_dt and available_dt > cutoff_dt:
                excluded += 1
                continue
            source_or_note = str(
                item.get("source")
                or item.get("url")
                or item.get("note")
                or item.get("summary")
                or item.get("claim")
                or "backtest evidence"
            )
            evidence = self.add_evidence(
                question_id=question.id,
                source_or_note=source_or_note,
                claim=str(item.get("claim") or ""),
                summary=str(item.get("summary") or ""),
                source_url=item.get("url"),
                source_name=item.get("source_name"),
                source_type=item.get("source_type"),
                published_at=item.get("published_at"),
                available_at=available,
                reliability_rating=item.get("reliability_rating"),
                relevance_rating=item.get("relevance_rating"),
                stance=item.get("stance") or "context",
                claim_type=item.get("claim_type") or "fact",
                metadata={"backtest_run_id": run_id},
            )
            if (evidence.metadata or {}).get("leak_domain"):
                leak_flagged += 1
            evidence_refs.append(evidence.id)

        # AIA P2.4 — model-cutoff gate. If the case's base model has a pretraining
        # cutoff at-or-after the event being predicted (resolution/close time),
        # the model may already "know" the answer; force calibration OFF for this
        # case and raise a readiness flag (mirrors the AIA paper rejecting a too-
        # fresh base model for the liquid-market benchmark). Unknown models and
        # cutoffs strictly before the event are a no-op.
        model_cutoff = lookup_model_pretraining_cutoff(case.get("agent_model"))
        event_time = case.get("resolution_time") or case.get("close_time")
        event_dt = timestamp_to_datetime(event_time) if event_time else None
        cutoff_model_dt = timestamp_to_datetime(model_cutoff) if model_cutoff else None
        model_cutoff_too_fresh = bool(
            cutoff_model_dt is not None and event_dt is not None and cutoff_model_dt >= event_dt
        )

        generated_forecast_id = None
        score_record_id = None
        if "outcome" in case:
            self.resolve_question(
                question_id=question.id,
                outcome=case["outcome"],
                resolution_source=case.get("resolution_source"),
                resolver_type="source_adapter",
                resolution_status="confirmed",
                criteria_satisfied=True,
            )
        probability = case.get("probability", case.get("forecast_probability"))
        distribution = case.get("distribution")
        if probability is not None or distribution is not None:
            calibration_eligible = (
                allow_calibration_memory and ambiguous == 0 and not model_cutoff_too_fresh
            )
            snapshot_metadata = self._backtest_snapshot_metadata(case)
            if model_cutoff_too_fresh:
                snapshot_metadata["model_cutoff_too_fresh"] = True
                snapshot_metadata["model_pretraining_cutoff"] = model_cutoff
                snapshot_metadata["readiness_flag"] = "model_cutoff_after_event"
            snapshot = self.create_snapshot(
                question_id=question.id,
                probability_or_distribution=distribution if distribution is not None else probability,
                rationale=str(case.get("rationale") or "Backtest dataset forecast replay."),
                as_of=simulated_time,
                confidence=self._optional_unit_float(case.get("confidence")),
                method=str(case.get("method") or "backtest_replay"),
                ensemble_components=self._backtest_snapshot_components(case),
                evidence_refs=evidence_refs,
                forecast_origin="backtest",
                agent_model=case.get("agent_model"),
                prompt_version=case.get("prompt_version"),
                forecasting_protocol_version=case.get("forecasting_protocol_version"),
                evidence_cutoff=evidence_cutoff,
                backtest_run_id=run_id,
                calibration_eligible=calibration_eligible,
                calibration_weight=1.0 if calibration_eligible else 0.0,
                metadata=snapshot_metadata,
            )
            generated_forecast_id = snapshot.forecast_id
            if "outcome" in case:
                score = self.score_question(question.id)
                score_record_id = score.id

        baseline_refs = []
        for baseline in self._backtest_case_baselines(case, outcome_space):
            if "probability" not in baseline and "distribution" not in baseline:
                continue
            baseline_forecast_id = None
            baseline_score_id = None
            if "outcome" in case:
                baseline_snapshot = self.create_snapshot(
                    question_id=question.id,
                    probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                    rationale=f"Imported baseline from {baseline.get('source') or 'dataset'}.",
                    as_of=baseline.get("as_of") or simulated_time,
                    method=str(baseline.get("baseline_type") or "imported"),
                    forecast_origin="imported_baseline",
                    backtest_run_id=run_id,
                    calibration_eligible=False,
                    calibration_weight=0.0,
                    set_current=False,
                )
                baseline_forecast_id = baseline_snapshot.forecast_id
                baseline_score_id = self.score_snapshot(baseline_forecast_id).id
            comparison = self.add_baseline_comparison(
                question_id=question.id,
                source=str(baseline.get("source") or "dataset"),
                baseline_type=str(baseline.get("baseline_type") or "imported"),
                probability_or_distribution=baseline.get("distribution", baseline.get("probability")),
                as_of=baseline.get("as_of") or simulated_time,
                forecast_id=baseline_forecast_id,
                score_record_id=baseline_score_id,
                metadata={"backtest_run_id": run_id, "generated_forecast_id": generated_forecast_id},
            )
            baseline_refs.append(comparison["id"])

        leakage_status = "passed" if ambiguous == 0 else "ambiguous_evidence"

        # AIA P1.2 — SECOND, content-aware leakage channel. The cheap date
        # pre-filter above already dropped post-cutoff *timestamped* evidence; the
        # judge reads the cited evidence TEXT + rationale for foreknowledge that
        # rides inside admissible text. OPT-IN: with no runner (the default) this
        # block is skipped entirely and the persisted columns keep their unflagged
        # defaults — making the run byte-identical to a pre-P1.2 backtest.
        leakage_verdict: dict[str, Any] = {}
        content_flag_count = 0
        if leak_judge_runner is not None:
            leakage_verdict = self._run_leak_judge(
                runner=leak_judge_runner,
                case=case,
                question=question,
                evidence_cutoff=evidence_cutoff,
            )
            if leakage_verdict.get("has_foreknowledge"):
                content_flag_count = 1
                # Never weaken a pre-existing non-passing status (e.g. ambiguous).
                if leakage_status == "passed":
                    leakage_status = "content_flagged"

        case_id = f"btc_{uuid.uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO backtest_cases (
                    id, backtest_run_id, question_id, simulated_forecast_time,
                    evidence_cutoff, generated_forecast_id, baseline_comparison_refs,
                    score_record_id, leakage_check_status, excluded_evidence_count,
                    ambiguous_evidence_count, leakage_verdicts, content_flag_count, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    case_id,
                    run_id,
                    question.id,
                    simulated_time,
                    evidence_cutoff,
                    generated_forecast_id,
                    json_dumps(baseline_refs),
                    score_record_id,
                    leakage_status,
                    excluded,
                    ambiguous,
                    json_dumps(leakage_verdict),
                    content_flag_count,
                    case.get("notes"),
                ),
            )
        row = self.get_backtest_case(case_id)
        if score_record_id:
            row["score_brier"] = self.get_score(score_record_id).brier_score
        # AIA P2.4 — surface the per-case leak-domain flag count + model-cutoff
        # readiness flag alongside the case row for evidence summaries.
        row["leak_flagged_evidence_count"] = leak_flagged
        row["model_cutoff_too_fresh"] = model_cutoff_too_fresh
        return row

    def _run_leak_judge(
        self,
        *,
        runner: "LeakJudgeRunner",
        case: dict[str, Any],
        question: ForecastQuestion,
        evidence_cutoff: str | None,
    ) -> dict[str, Any]:
        """Run the content-aware foreknowledge judge over one case.

        Builds the (pure) prompt, calls the supplied ``runner`` (the only
        network touch in this whole feature), and returns the tolerant-parsed
        verdict. Any runner exception fails CLOSED to the safe default so a flaky
        judge call can never manufacture a leak flag or take down the backtest.
        """

        from forecasting.leak_judge import (
            build_leak_judge_prompt,
            parse_leak_verdict,
        )

        # Assemble the cited evidence text + rationale the judge must read. We use
        # the case's own evidence/rationale (the model output under audit).
        evidence_lines: list[str] = []
        for item in case.get("evidence") or []:
            if not isinstance(item, dict):
                continue
            parts = [
                str(item.get(field) or "")
                for field in ("claim", "summary", "note", "source", "url")
            ]
            text = " | ".join(part for part in parts if part)
            if text:
                evidence_lines.append(f"- {text}")
        rationale = str(case.get("rationale") or "")
        model_output = "\n".join(
            block
            for block in (
                ("Rationale:\n" + rationale) if rationale else "",
                ("Cited evidence:\n" + "\n".join(evidence_lines)) if evidence_lines else "",
            )
            if block
        )
        resolution = case.get("outcome")
        prompt = build_leak_judge_prompt(
            question=question.title,
            cutoff=evidence_cutoff,
            resolution=str(resolution) if resolution is not None else None,
            model_output=model_output,
        )
        try:
            raw = runner(prompt, case)
        except Exception:  # noqa: BLE001 — fail closed, never break the backtest.
            return parse_leak_verdict(None)
        return parse_leak_verdict(raw)

    # AIA P1.2 — read-only leakage robustness re-scores.
    _RESCORE_MODES = ("baseline", "filtered", "worst_case")

    def rescore_backtest_run(self, run_id: str, mode: str) -> dict[str, Any]:
        """Recompute the agent mean Brier under a leakage-robustness *mode*.

        PURE recompute over STORED cases — it never edits a stored score, never
        touches calibration, never re-runs the judge, and WRITES NOTHING (a
        robustness what-if must be freely repeatable with no side effects).

        Modes:
          * ``baseline``    — every scored case as-scored (the headline).
          * ``filtered``    — DROP every content-flagged case (drop-all-flagged).
          * ``worst_case``  — raise the Brier to AT LEAST 0.25 (the coin-flip floor;
            it NEVER improves an already-worse case, so worst_case is a genuine
            upper bound on our Brier under leakage) on every case belonging to a
            QUESTION that accumulated >= :data:`WORST_CASE_FLAG_THRESHOLD` content
            flags across its cases; all other cases keep their Brier.

        Returns ``{baseline, filtered, worst_case, abs_delta, rel_delta}`` where
        ``baseline``/``filtered``/``worst_case`` are mean-Brier dicts and the
        deltas compare the REQUESTED mode against baseline. Always computes all
        three means so deltas are available regardless of ``mode``.
        """

        if mode not in self._RESCORE_MODES:
            raise ValidationError(
                f"rescore mode must be one of {sorted(self._RESCORE_MODES)}, got {mode!r}"
            )
        cases = self.list_backtest_cases(run_id)
        # Per-question flag tally. A dataset question recurs across rolling cutoffs
        # as MULTIPLE backtest cases, each with its own internal question_id, so we
        # group on the stable LOGICAL key (the dataset external_id stored in the
        # question metadata) and fall back to the internal id when absent.
        case_keys: dict[str, str] = {}
        flags_by_question: dict[str, int] = defaultdict(int)
        for case in cases:
            key = self._backtest_case_question_key(case)
            case_keys[case["id"]] = key
            flags_by_question[key] += int(case.get("content_flag_count") or 0)
        worst_case_questions = {
            key
            for key, count in flags_by_question.items()
            if count >= WORST_CASE_FLAG_THRESHOLD
        }

        baseline_briers: list[float] = []
        filtered_briers: list[float] = []
        worst_briers: list[float] = []
        for case in cases:
            brier = case.get("score_brier")
            if brier is None and case.get("score_record_id"):
                brier = self.get_score(case["score_record_id"]).brier_score
            if brier is None:
                continue  # unscored case (e.g. no resolution) — not in any mean.
            brier = float(brier)
            baseline_briers.append(brier)
            # filtered: drop the case entirely if it carries any content flag.
            if int(case.get("content_flag_count") or 0) == 0:
                filtered_briers.append(brier)
            # worst_case: raise the Brier to AT LEAST the coin-flip floor for cases
            # of a heavily-flagged question — never improving an already-worse case,
            # so worst_case is a genuine UPPER bound on our Brier under leakage.
            if case_keys.get(case["id"]) in worst_case_questions:
                worst_briers.append(max(brier, BRIER_COIN_FLIP_FLOOR))
            else:
                worst_briers.append(brier)

        baseline = self._rescore_brier_summary(baseline_briers)
        filtered = self._rescore_brier_summary(filtered_briers)
        worst_case = self._rescore_brier_summary(worst_briers)

        chosen = {"baseline": baseline, "filtered": filtered, "worst_case": worst_case}[mode]
        base_mean = baseline.get("mean_brier")
        chosen_mean = chosen.get("mean_brier")
        if base_mean is None or chosen_mean is None:
            abs_delta = None
            rel_delta = None
        else:
            abs_delta = chosen_mean - base_mean
            rel_delta = (abs_delta / base_mean) if base_mean else None

        return {
            "run_id": run_id,
            "mode": mode,
            "worst_case_flag_threshold": WORST_CASE_FLAG_THRESHOLD,
            "worst_case_question_count": len(worst_case_questions),
            "baseline": baseline,
            "filtered": filtered,
            "worst_case": worst_case,
            "abs_delta": abs_delta,
            "rel_delta": rel_delta,
        }

    @staticmethod
    def _rescore_brier_summary(briers: list[float]) -> dict[str, Any]:
        return {
            "count": len(briers),
            "mean_brier": (sum(briers) / len(briers)) if briers else None,
        }

    def _backtest_case_question_key(self, case: dict[str, Any]) -> str:
        """Stable LOGICAL-question key for per-question flag aggregation.

        A dataset question that recurs across rolling cutoffs produces multiple
        backtest cases, each with its own internal ``question_id``. Group them on
        the dataset ``external_id`` carried in the question metadata so a question
        with cases at several cutoffs accumulates ONE flag tally; fall back to the
        internal id when no external id was supplied.
        """

        question_id = case.get("question_id")
        if question_id:
            try:
                metadata = self.get_question(question_id).metadata or {}
            except LedgerNotFoundError:
                metadata = {}
            external_id = metadata.get("external_id")
            if external_id:
                return f"ext:{external_id}"
            return f"qid:{question_id}"
        return f"case:{case['id']}"

    def _build_leak_robustness_summary(
        self,
        run_id: str,
        *,
        content_flagged_cases: int,
    ) -> dict[str, Any]:
        """Assemble the read-only leak-judge summary for ``result_summary``.

        Carries the three robustness re-scores, the honest true-leak-rate
        back-out, and a graded ``leakage_material`` verdict that REPLACES the old
        binary kill-switch: leakage is non-material iff the worst-case mean Brier
        stays within :data:`LEAK_ROBUSTNESS_REL_TOLERANCE` (relative) of baseline.
        """

        from forecasting.leak_prevalence import (
            LEAK_JUDGE_CALIBRATION,
            estimate_true_leak_rate,
        )

        rescore = self.rescore_backtest_run(run_id, "worst_case")
        case_count = int(rescore["baseline"].get("count") or 0)
        prevalence = estimate_true_leak_rate(case_count, content_flagged_cases)

        worst_rel = rescore.get("rel_delta")
        # Non-material iff the worst-case mean Brier did not rise by more than the
        # relative tolerance. A missing delta (no scored cases) fails OPEN to
        # non-material rather than asserting harm we cannot measure.
        leakage_material = bool(worst_rel is not None and worst_rel > LEAK_ROBUSTNESS_REL_TOLERANCE)

        return {
            "channel": "content_aware_judge",
            "prompt_version": "leak-judge-v0",
            "content_flagged_cases": content_flagged_cases,
            "rescore": rescore,
            "true_leak_rate": prevalence,
            "calibration": LEAK_JUDGE_CALIBRATION,
            "rel_tolerance": LEAK_ROBUSTNESS_REL_TOLERANCE,
            "leakage_material": leakage_material,
            "leakage_non_material": not leakage_material,
        }

    def get_backtest_case(self, case_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM backtest_cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"backtest case not found: {case_id}")
        return self._row_to_backtest_case(row)

    @staticmethod
    def _backtest_snapshot_components(case: dict[str, Any]) -> dict[str, Any]:
        components = case.get("ensemble_components")
        if isinstance(components, dict):
            return components
        component_forecasts = case.get("component_forecasts")
        if isinstance(component_forecasts, dict):
            return component_forecasts
        if not isinstance(component_forecasts, list):
            return {}
        normalized: dict[str, Any] = {}
        for index, component in enumerate(component_forecasts, start=1):
            if isinstance(component, dict):
                name = component.get("name") or component.get("source") or f"component_{index}"
                normalized[str(name)] = component
            else:
                normalized[f"component_{index}"] = component
        return normalized

    @staticmethod
    def _backtest_snapshot_metadata(case: dict[str, Any]) -> dict[str, Any]:
        metadata = dict(case.get("forecast_metadata") or {})
        if case.get("probability_source"):
            metadata["probability_source"] = case["probability_source"]
        if case.get("id"):
            metadata["external_case_id"] = case["id"]
        return metadata

    @staticmethod
    def _optional_unit_float(value: Any) -> float | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, (int, float)):
            number = float(value)
        elif isinstance(value, str):
            try:
                number = float(value)
            except ValueError:
                return None
        else:
            return None
        if 0 <= number <= 1:
            return number
        return None

    def _backtest_case_baselines(
        self,
        case: dict[str, Any],
        outcome_space: OutcomeSpace,
    ) -> list[dict[str, Any]]:
        baselines = [dict(row) for row in case.get("baselines") or [] if isinstance(row, dict)]
        # MARKET-HIDDEN ARM: ``hidden_from_agent`` is an agent-VISIBILITY marker
        # consumed only by agent_protocol._pre_cutoff_baselines. It must NOT alter
        # scoring — a hidden baseline is still recorded + scored as a
        # baseline_comparison — so strip the marker here before persistence rather
        # than carrying an unknown key into create_snapshot / add_baseline_comparison.
        for row in baselines:
            row.pop("hidden_from_agent", None)
        has_explicit_baselines = bool(baselines)
        if not has_explicit_baselines and outcome_space.type == "binary" and not self._has_baseline(baselines, "naive_0_5", "auto"):
            baselines.append(
                {
                    "source": "auto",
                    "baseline_type": "naive_0_5",
                    "probability": 0.5,
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        elif (
            not has_explicit_baselines
            and outcome_space.type == "categorical"
            and outcome_space.choices
            and not self._has_baseline(baselines, "uniform", "auto")
        ):
            probability = 1.0 / len(outcome_space.choices)
            baselines.append(
                {
                    "source": "auto",
                    "baseline_type": "uniform",
                    "distribution": {choice: probability for choice in outcome_space.choices},
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        base_rate = case.get("base_rate")
        if base_rate is None:
            base_rate = case.get("base_rate_probability")
        if base_rate is not None and not self._has_baseline(baselines, "base_rate", "dataset"):
            baselines.append(
                {
                    "source": "dataset",
                    "baseline_type": "base_rate",
                    "probability": base_rate,
                    "as_of": case.get("simulated_forecast_time") or case.get("as_of"),
                }
            )
        return baselines

    def _has_baseline(self, baselines: list[dict[str, Any]], baseline_type: str, source: str) -> bool:
        return any(
            str(baseline.get("baseline_type") or "") == baseline_type
            and str(baseline.get("source") or "") == source
            for baseline in baselines
        )

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
        if isinstance(probability_or_distribution, (int, float)):
            probability = float(probability_or_distribution)
            yes_labels = {"yes", "y", "true", "1", "occurred", "success"}
            outcome_label = str(outcome).strip().lower()
            observed = 1.0 if outcome_label in yes_labels or outcome_label == str(outcome_space.choices[0]).lower() else 0.0
            return (probability - observed) ** 2
        if isinstance(probability_or_distribution, dict):
            outcome_label = str(outcome).strip().lower()
            lowered = {str(key).lower(): float(value) for key, value in probability_or_distribution.items()}
            labels = {str(choice).lower() for choice in outcome_space.choices}
            labels.update(lowered.keys())
            return sum(
                (lowered.get(label, 0.0) - (1.0 if label == outcome_label else 0.0)) ** 2
                for label in labels
            )
        raise ValidationError("unsupported probability payload")

    def _log_score(self, resolved_probability: float) -> float:
        return -math.log(max(min(resolved_probability, 1.0), 1e-15))

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
        bounds = outcome_space.bounds or []
        if len(bounds) == 2:
            low, high = float(bounds[0]), float(bounds[1])
            if math.isfinite(low) and math.isfinite(high) and high > low:
                ratio = min(max((value - low) / (high - low), 0.0), 0.999999)
                return self._probability_bucket(ratio)
        return "numeric"

    def _vote_share_vector_score(self, forecast: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any] | None:
        """Vector MAE/RMSE (percentage points) for a candidate-SHARE forecast scored
        against a candidate-SHARE outcome. Forecast values may be probabilities (0-1,
        auto-scaled to pp) or already pp; outcome values are pp (0-100). Returns None
        when there are no shared numeric candidate keys, so the caller falls through
        to the existing scorer. This is an ACCURACY metric (100 - MAE), not a strictly
        proper score — labeled as such; it makes vote-share forecasts machine-scoreable
        instead of mis-read as categorical labels (lesson cl_ec9059c809ba)."""
        def _numeric_shares(raw: dict[str, Any]) -> dict[str, float]:
            out: dict[str, float] = {}
            for key, value in raw.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[str(key).strip().lower()] = float(value)
            return out

        f_shares = _numeric_shares(forecast)
        o_shares = _numeric_shares(outcome)
        shared = sorted(set(f_shares) & set(o_shares))
        if not shared:
            return None
        # Forecast in [0,1] -> scale to pp; if it already looks like pp, leave it.
        scale = 100.0 if max(f_shares[k] for k in shared) <= 1.5 else 1.0
        diffs = [abs(f_shares[k] * scale - o_shares[k]) for k in shared]
        mae = sum(diffs) / len(diffs)
        rmse = math.sqrt(sum(d * d for d in diffs) / len(diffs))
        return {
            "brier_score": None,
            "log_score": None,
            "proper_score": max(0.0, 100.0 - mae),
            "score_rule": "vector_mae_percentage_points",
            "calibration_bucket": None,
            "notes": f"Vector accuracy across {len(shared)} candidate share(s): MAE={mae:.2f}pp, RMSE={rmse:.2f}pp (accuracy, not a proper score).",
        }

    def _normal_distribution_score(
        self,
        probability_or_distribution: dict[str, Any],
        outcome: Any,
        outcome_space: OutcomeSpace,
    ) -> dict[str, Any] | None:
        mean_key = next((key for key in ("mean", "expected", "value", "point") if key in probability_or_distribution), None)
        sd_key = next((key for key in ("sd", "std", "sigma", "stdev") if key in probability_or_distribution), None)
        if mean_key is None or sd_key is None:
            return None
        mean = float(probability_or_distribution[mean_key])
        sd = float(probability_or_distribution[sd_key])
        outcome_value = self._numeric_outcome(outcome)
        if not math.isfinite(mean) or not math.isfinite(sd) or sd <= 0:
            raise ValidationError("normal distribution scoring requires finite mean and positive standard deviation")
        variance = sd * sd
        negative_log_likelihood = 0.5 * math.log(2 * math.pi * variance) + ((outcome_value - mean) ** 2) / (2 * variance)
        mean_error, mean_rule = self._numeric_squared_error(mean, outcome_value, outcome_space)
        return {
            "brier_score": None,
            "log_score": negative_log_likelihood,
            "proper_score": negative_log_likelihood,
            "score_rule": "normal_negative_log_likelihood",
            "calibration_bucket": self._numeric_bucket(mean, outcome_space),
            "notes": f"Normal-distribution negative log likelihood; mean {mean_rule}={mean_error:.6g}.",
        }

    def _probability_bucket(self, probability: float) -> str:
        lower = min(int(probability * 10), 9) / 10
        upper = lower + 0.1
        return f"{lower:.1f}-{upper:.1f}"

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
        score_ids = {score.id for score in scores}
        postmortem_ids = {postmortem["id"] for postmortem in postmortems}
        lessons = []
        for lesson in self.list_calibration_lessons():
            if score_ids & set(lesson["source_score_record_refs"]):
                lessons.append(lesson)
            elif postmortem_ids & set(lesson["source_postmortem_refs"]):
                lessons.append(lesson)
        return lessons

    def _domain_error_profiles_for_question(self, question: ForecastQuestion) -> list[dict[str, Any]]:
        if not question.domain:
            return []
        profiles = []
        for profile in self.list_domain_error_profiles(domain=question.domain):
            profile_topic = profile.get("topic")
            if profile_topic and profile_topic not in question.topics:
                continue
            profile_type = profile.get("question_type")
            if profile_type and profile_type != question.outcome_space.type:
                continue
            profiles.append(profile)
        return profiles

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
        del model_runs
        ids_by_type = {
            "forecast_snapshot": {snapshot.forecast_id for snapshot in snapshots},
            "evidence_item": {item.id for item in evidence},
            "assumption": {item["id"] for item in assumptions},
            "reference_class": {item["id"] for item in reference_classes},
            "resolution": {resolution.id} if resolution else set(),
            "score_record": {score.id for score in scores},
            "postmortem": {item["id"] for item in postmortems},
            "calibration_lesson": {item["id"] for item in calibration_lessons},
        }
        corrections = []
        for correction in self.list_corrections():
            if correction["target_type"] in ids_by_type and correction["target_id"] in ids_by_type[correction["target_type"]]:
                corrections.append(correction)
        return corrections

    def _score_summary(self, scores: list[ScoreRecord]) -> dict[str, Any]:
        return {
            "count": len(scores),
            "mean_brier": self._mean([score.brier_score for score in scores]),
            "mean_log_score": self._mean([score.log_score for score in scores]),
        }

    def _score_breakdown(
        self,
        scores: list[ScoreRecord],
        key_fn,
    ) -> dict[str, dict[str, Any]]:
        buckets: dict[str, list[ScoreRecord]] = defaultdict(list)
        for score in scores:
            buckets[str(key_fn(score))].append(score)
        return {key: self._score_summary(bucket_scores) for key, bucket_scores in sorted(buckets.items())}

    def _score_horizon_bucket(self, score: ScoreRecord) -> str:
        horizon = score.forecast_horizon_days
        if horizon is None:
            return "unknown"
        if horizon <= 7:
            return "0-7d"
        if horizon <= 30:
            return "8-30d"
        if horizon <= 90:
            return "31-90d"
        if horizon <= 365:
            return "91-365d"
        return "365d+"

    def _paired_brier_summary(
        self,
        pairs: list[tuple[ScoreRecord, ScoreRecord]],
    ) -> dict[str, Any]:
        deltas: list[float] = []
        agent_scores: list[float] = []
        baseline_scores: list[float] = []
        agent_wins = baseline_wins = ties = 0
        for agent, baseline in pairs:
            if agent.brier_score is None or baseline.brier_score is None:
                continue
            agent_brier = float(agent.brier_score)
            baseline_brier = float(baseline.brier_score)
            agent_scores.append(agent_brier)
            baseline_scores.append(baseline_brier)
            deltas.append(baseline_brier - agent_brier)
            if agent_brier < baseline_brier:
                agent_wins += 1
            elif agent_brier > baseline_brier:
                baseline_wins += 1
            else:
                ties += 1

        count = len(deltas)
        # Point estimate is UNCHANGED from the prior parametric implementation:
        # the mean paired Brier edge. Only the significance statistics around it
        # (CI + p-value) move from the normal approximation to a seeded bootstrap.
        mean_delta = self._mean(deltas)
        bootstrap = self._paired_bootstrap(deltas, mean_delta)
        return {
            "paired_brier_count": count,
            "paired_agent_mean_brier": self._mean(agent_scores),
            "paired_baseline_mean_brier": self._mean(baseline_scores),
            "paired_agent_edge_mean_brier": mean_delta,
            "paired_agent_edge_ci95_low": bootstrap["ci_low"],
            "paired_agent_edge_ci95_high": bootstrap["ci_high"],
            "paired_p_value": bootstrap["p_value"],
            "paired_bootstrap_draws": PAIRED_BOOTSTRAP_DRAWS,
            "paired_brier_coin_flip_floor": BRIER_COIN_FLIP_FLOOR,
            "paired_agent_wins": agent_wins,
            "paired_baseline_wins": baseline_wins,
            "paired_ties": ties,
        }

    def _paired_bootstrap(
        self,
        deltas: list[float],
        mean_delta: float | None,
    ) -> dict[str, float | None]:
        """Seeded paired bootstrap over per-question Brier deltas.

        deltas[i] = baseline_brier_i - agent_brier_i (POSITIVE = agent better).

        - Two-sided p-value tests H0: no paired difference. We recenter the deltas
          at zero (d0 = x - mean_delta), draw PAIRED_BOOTSTRAP_DRAWS resample-means
          of d0, and report the fraction whose magnitude is >= |mean_delta|.
        - The 95% CI is the 2.5/97.5 percentiles of the UNCENTERED resample-means.
        - n < 2, no mean, or a degenerate all-equal-deltas spread -> p=None, ci=None.

        Deterministic: a single seeded random.Random(PAIRED_BOOTSTRAP_SEED) drives
        every draw, so identical inputs always yield identical p-value and CI.
        """

        none_result: dict[str, float | None] = {"p_value": None, "ci_low": None, "ci_high": None}
        count = len(deltas)
        if count < 2 or mean_delta is None:
            return none_result
        # Degenerate: every paired delta identical. The recentered series is all
        # zeros, so every bootstrap mean is exactly 0. If the edge itself is 0 the
        # data carry no signal at all (p undefined); if the edge is non-zero but
        # variance-free, the bootstrap cannot characterize it either.
        spread = max(deltas) - min(deltas)
        if spread == 0.0:
            return none_result

        observed = abs(mean_delta)
        d0 = [x - mean_delta for x in deltas]
        rng = random.Random(PAIRED_BOOTSTRAP_SEED)
        ge_count = 0
        uncentered_means: list[float] = []
        for _ in range(PAIRED_BOOTSTRAP_DRAWS):
            # One shared index draw per iteration keeps the recentered (p-value)
            # and uncentered (CI) resamples on the same deterministic stream.
            idx = [rng.randrange(count) for _ in range(count)]
            boot_centered = statistics.fmean(d0[i] for i in idx)
            if abs(boot_centered) >= observed:
                ge_count += 1
            uncentered_means.append(statistics.fmean(deltas[i] for i in idx))

        # Add-one (plus-one) correction so a Monte-Carlo p-value is never exactly
        # 0.0 — the true tail is bounded below by ~1/B, not 0.
        p_value = (ge_count + 1) / (PAIRED_BOOTSTRAP_DRAWS + 1)
        uncentered_means.sort()
        return {
            "p_value": p_value,
            "ci_low": self._percentile(uncentered_means, 2.5),
            "ci_high": self._percentile(uncentered_means, 97.5),
        }

    @staticmethod
    def _percentile(sorted_values: list[float], pct: float) -> float:
        """Linear-interpolated percentile over an ascending list (pct in 0..100)."""

        if not sorted_values:
            raise ValueError("percentile of empty sequence")
        if len(sorted_values) == 1:
            return sorted_values[0]
        rank = (pct / 100.0) * (len(sorted_values) - 1)
        low = math.floor(rank)
        high = math.ceil(rank)
        if low == high:
            return sorted_values[low]
        frac = rank - low
        return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * frac

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
        close_dt = timestamp_to_datetime(close_time)
        as_of_dt = timestamp_to_datetime(as_of)
        if not close_dt or not as_of_dt:
            return None
        return max((close_dt - as_of_dt).total_seconds() / 86400.0, 0.0)

    def _review_priority(self, reasons: list[str]) -> int:
        if any(reason.startswith("new_evidence:") for reason in reasons):
            return 0
        if any(
            reason in {"resolution_check_due", "close_time_passed"}
            or reason.startswith("close_time_within_")
            for reason in reasons
        ):
            return 1
        if any(reason.startswith(("assumption_invalidated:", "reference_class_invalidated:")) for reason in reasons):
            return 2
        if any(
            reason in {"review_due", "no_forecast_snapshot", "no_evidence"}
            or reason.startswith(("large_forecast_delta:", "assumption_check_due:", "reference_class_check_due:", "assumption_stale:", "reference_class_stale:"))
            for reason in reasons
        ):
            return 3
        if any(reason.startswith(("last_update_", "evidence_stale_")) for reason in reasons):
            return 4
        return 9

    def _recommended_action(self, reason: str) -> str:
        if reason.startswith("assumption_invalidated:"):
            return "Update the forecast or replace the invalidated assumption."
        if reason.startswith("assumption_stale:") or reason.startswith("assumption_check_due:"):
            return "Re-check the assumption and record fresh evidence or mark it resolved/invalidated."
        if reason.startswith("reference_class_invalidated:"):
            return "Replace the reference class or rerun the base-rate estimate before updating probability."
        if reason.startswith("reference_class_stale:") or reason.startswith("reference_class_check_due:"):
            return "Refresh the reference class and base-rate evidence."
        if reason == "no_evidence":
            return "Run `forecast research` or add evidence before trusting the current probability."
        if reason.startswith("new_evidence:"):
            return "Review the new evidence and append a forecast update if it changes the probability."
        if reason.startswith("evidence_stale_"):
            return "Refresh evidence and decide whether a new forecast snapshot is warranted."
        if reason.startswith("large_forecast_delta:"):
            return "Review the large probability move; record what changed and whether assumptions or calibration lessons need updates."
        if reason.startswith("close_time_within_"):
            return "Review evidence and prepare for close/resolution before the question closes."
        return {
            "no_forecast_snapshot": "Run `forecast update` to create an explicit probability.",
            "review_due": "Run a research pass or update the forecast rationale.",
            "close_time_passed": "Check whether the question should be closed or resolved.",
            "resolution_check_due": "Confirm resolution criteria and score if resolved.",
        }.get(reason, "Review the forecast and decide whether a new snapshot is warranted.")

    def _auto_postmortem_lesson(self, question: ForecastQuestion, score: ScoreRecord) -> str:
        if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
            return ""
        if score.brier_score is None or score.brier_score < 0.25:
            return ""
        scope = question.domain or "global"
        origin_prefix = (
            "Recent"
            if score.forecast_origin == "live"
            else f"Eligible {score.forecast_origin} replay"
        )
        tags = self._auto_postmortem_error_tags(score)
        if "overconfidence" in tags:
            return (
                f"{origin_prefix} high-confidence miss in {scope}; require explicit base-rate, "
                "counterevidence, and assumption-staleness checks before similar extreme probabilities."
            )
        return (
            f"{origin_prefix} high-Brier resolved forecast in {scope}; check base rates, "
            "missed evidence, and confidence before similar updates."
        )

    def _auto_postmortem_adjustment(self, question: ForecastQuestion, score: ScoreRecord) -> dict[str, Any]:
        if not score.calibration_eligible or score.forecast_origin not in {"live", "backtest"}:
            return {}
        tags = self._auto_postmortem_error_tags(score)
        if not tags:
            return {}
        checklist = [
            "Compare against a current reference class before changing probability.",
            "Look for counterevidence from at least one independent source class.",
            "Re-check active assumptions and evidence freshness before the next update.",
        ]
        return {
            "error_tags": tags,
            "forecast_origin": score.forecast_origin,
            "requires_review_before_live_use": score.forecast_origin != "live",
            "review_checklist": checklist,
            "scope": question.domain or "global",
        }

    def _auto_postmortem_error_tags(self, score: ScoreRecord) -> list[str]:
        if score.brier_score is None or score.brier_score < 0.25:
            return []
        tags = ["high_brier_miss"]
        try:
            snapshot = self.get_snapshot(score.forecast_id)
        except LedgerNotFoundError:
            return tags
        sharpness = self._sharpness(snapshot.probability_or_distribution)
        if sharpness is not None and sharpness >= 0.6:
            tags.insert(0, "overconfidence")
        return tags

    def _question_in_portfolio(self, question: ForecastQuestion, portfolio: str) -> bool:
        portfolio = portfolio.strip()
        if not portfolio:
            return True
        expected_tags = {portfolio, f"portfolio:{portfolio}", f"portfolio={portfolio}"}
        if any(tag in expected_tags for tag in question.tags):
            return True
        metadata_portfolio = question.metadata.get("portfolio")
        if isinstance(metadata_portfolio, str) and metadata_portfolio == portfolio:
            return True
        metadata_portfolios = question.metadata.get("portfolios")
        if isinstance(metadata_portfolios, list) and portfolio in metadata_portfolios:
            return True
        return False

    def _question_matches_confidence(
        self,
        question_id: str,
        *,
        confidence_below: float | None,
        confidence_above: float | None,
    ) -> bool:
        if confidence_below is None and confidence_above is None:
            return True
        snapshot = self.get_current_snapshot(question_id)
        if snapshot is None or snapshot.confidence is None:
            return False
        if confidence_below is not None and snapshot.confidence >= confidence_below:
            return False
        if confidence_above is not None and snapshot.confidence <= confidence_above:
            return False
        return True

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
        """Return final-minus-initial probability movement for the scored forecast path."""

        try:
            question = self.get_question(score.question_id)
        except LedgerNotFoundError:
            return None
        scored_as_of = timestamp_to_datetime(scored_snapshot.as_of)
        close_time = timestamp_to_datetime(question.close_time) if question.close_time else None
        cutoff = close_time or scored_as_of
        numeric_snapshots: list[ForecastSnapshot] = []
        for snapshot in self.list_snapshots(score.question_id):
            if snapshot.forecast_origin != scored_snapshot.forecast_origin:
                continue
            if snapshot.backtest_run_id != scored_snapshot.backtest_run_id:
                continue
            snapshot_as_of = timestamp_to_datetime(snapshot.as_of)
            if cutoff and snapshot_as_of and snapshot_as_of > cutoff:
                continue
            if scored_as_of and snapshot_as_of and snapshot_as_of > scored_as_of:
                continue
            if self._numeric_probability(snapshot.probability_or_distribution) is None:
                continue
            numeric_snapshots.append(snapshot)
        if len(numeric_snapshots) < 2:
            return None
        first = self._numeric_probability(numeric_snapshots[0].probability_or_distribution)
        last = self._numeric_probability(numeric_snapshots[-1].probability_or_distribution)
        if first is None or last is None:
            return None
        return last - first

    @staticmethod
    def _numeric_probability(payload: Any) -> float | None:
        if isinstance(payload, bool):
            return None
        if isinstance(payload, (int, float)):
            return float(payload)
        return None

    def _snapshot_component_contributions(self, snapshot: ForecastSnapshot) -> list[dict[str, Any]]:
        forecast_probability = self._numeric_probability(snapshot.probability_or_distribution)
        rows = self._ensemble_component_rows(snapshot.ensemble_components)
        total_weight = sum(row["weight"] for row in rows)
        if total_weight <= 0:
            return []
        contributions: list[dict[str, Any]] = []
        for row in rows:
            weight_share = row["weight"] / total_weight
            contribution = row["probability"] * weight_share
            distance = (
                row["probability"] - forecast_probability
                if forecast_probability is not None
                else None
            )
            contributions.append(
                {
                    "name": row["name"],
                    "probability": row["probability"],
                    "weight": row["weight"],
                    "weight_share": weight_share,
                    "contribution": contribution,
                    "distance_from_forecast": distance,
                }
            )
        return contributions

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
        return (question.impact or "").strip().lower() in {"high", "critical", "material"}

    def _domain_error_profile_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        profile_filters: set[tuple[str | None, str | None]] = set()
        if domain or topic:
            profile_filters.add((domain, topic))
        for question in questions:
            if question.domain:
                profile_filters.add((question.domain, None))
                for question_topic in question.topics:
                    profile_filters.add((question.domain, question_topic))
        alerts: list[AlertEvent] = []
        seen_profiles: set[str] = set()
        for profile_domain, profile_topic in profile_filters:
            for profile in self.list_domain_error_profiles(domain=profile_domain, topic=profile_topic):
                if profile["id"] in seen_profiles:
                    continue
                if not profile["recurring_errors"] and not profile["recommended_adjustments"]:
                    continue
                seen_profiles.add(profile["id"])
                matching_questions = self._active_questions_for_error_profile(profile, questions)
                matching_ids = [question.id for question in matching_questions[:5]]
                matching_summary = (
                    f" Active matching forecasts: {', '.join(matching_ids)}."
                    if matching_ids
                    else ""
                )
                alerts.append(
                    self.create_alert(
                        severity="info",
                        scope_type="domain_error_profile",
                        scope_ref=profile["id"],
                        reason="domain_error_profile_review",
                        recommended_action=(
                            "Review active forecasts in this scope against recurring errors: "
                            + ", ".join(profile["recurring_errors"] or profile["recommended_adjustments"])
                            + "."
                            + matching_summary
                        ),
                    )
                )
                for question in matching_questions:
                    alerts.append(
                        self.create_alert(
                            severity="warning",
                            scope_type="question",
                            scope_ref=question.id,
                            reason=f"domain_error_profile_applies:{profile['id']}",
                            recommended_action=self._error_profile_question_action(profile, question),
                        )
                    )
        return alerts

    def _active_questions_for_error_profile(
        self,
        profile: dict[str, Any],
        questions: list[ForecastQuestion],
    ) -> list[ForecastQuestion]:
        profile_domain = profile.get("domain")
        profile_topic = profile.get("topic")
        profile_question_type = profile.get("question_type")
        result: list[ForecastQuestion] = []
        seen: set[str] = set()
        for question in questions:
            if question.id in seen or question.status != "active":
                continue
            if profile_domain and question.domain != profile_domain:
                continue
            if profile_topic and profile_topic not in question.topics:
                continue
            if profile_question_type and question.outcome_space.type != profile_question_type:
                continue
            result.append(question)
            seen.add(question.id)
        return result

    def _error_profile_question_action(
        self,
        profile: dict[str, Any],
        question: ForecastQuestion,
    ) -> str:
        recurring = list(profile.get("recurring_errors") or profile.get("recommended_adjustments") or [])
        patterns = ", ".join(str(item) for item in recurring[:4]) or "recent misses"
        return (
            "Review this active forecast against learned error patterns "
            f"({patterns}). Inspect `forecast show {question.id}`, refresh evidence, "
            "and save any probability change explicitly with `forecast update`."
        )

    def _calibration_lesson_review_alerts(
        self,
        *,
        domain: str | None,
        topic: str | None,
        questions: list[ForecastQuestion],
    ) -> list[AlertEvent]:
        candidates: dict[str, dict[str, Any]] = {}

        def add_lesson(lesson: dict[str, Any]) -> None:
            if lesson.get("status") != "tentative":
                return
            if lesson.get("invalidated_by_correction_id"):
                return
            candidates[lesson["id"]] = lesson

        if domain:
            for lesson in self.list_calibration_lessons(scope_type="domain", scope_ref=domain):
                add_lesson(lesson)
        if topic:
            for lesson in self.list_calibration_lessons(scope_type="topic", scope_ref=topic):
                add_lesson(lesson)

        all_scores = self.list_scores()
        for question in questions:
            if question.domain:
                for lesson in self.list_calibration_lessons(scope_type="domain", scope_ref=question.domain):
                    add_lesson(lesson)
            for question_topic in question.topics:
                for lesson in self.list_calibration_lessons(scope_type="topic", scope_ref=question_topic):
                    add_lesson(lesson)
            question_scores = [score for score in all_scores if score.question_id == question.id]
            postmortems = self.list_postmortems(question.id)
            for lesson in self._calibration_lessons_for_question(question_scores, postmortems):
                add_lesson(lesson)

        if not any([domain, topic, questions]):
            for lesson in self.list_calibration_lessons(scope_type="global", scope_ref=None):
                add_lesson(lesson)

        alerts: list[AlertEvent] = []
        for lesson in sorted(candidates.values(), key=lambda item: item["updated_at"], reverse=True):
            alerts.append(
                self.create_alert(
                    severity="info",
                    scope_type="calibration_lesson",
                    scope_ref=lesson["id"],
                    reason="calibration_lesson_review",
                    recommended_action=(
                        f"Review tentative lesson {lesson['id']} with `forecast lesson status {lesson['id']} "
                        "--status active` or reject/supersede it before relying on it for future updates."
                    ),
                )
            )
        return alerts

    def _benchmark_evidence_alerts(self) -> list[AlertEvent]:
        from forecasting.backtesting import (
            build_backtest_performance_summaries,
            build_forecasting_evidence_status,
        )

        rows = self.list_backtest_runs()[:20]
        status = build_forecasting_evidence_status(
            self,
            build_backtest_performance_summaries(self, rows),
        )
        gaps = list(status.get("gaps") or [])
        if not gaps:
            return []
        command_hints = [
            commands[0]
            for action in list(status.get("next_actions") or [])[:3]
            if (commands := list(action.get("commands") or []))
        ]
        command_hint = (
            f" Suggested commands: {'; '.join(command_hints)}."
            if command_hints
            else ""
        )
        return [
            self.create_alert(
                severity="warning",
                scope_type="global",
                scope_ref="benchmark_evidence",
                reason="benchmark_evidence_gaps",
                recommended_action=(
                    "Run `forecast performance --json` and close evidence gaps: "
                    f"{', '.join(gaps[:5])}. Collect live scored forecasts and "
                    "agent-protocol held-out runs, and include external resolved-question "
                    "corpora from at least two source families before claiming live "
                    f"superiority.{command_hint}"
                ),
            )
        ]

    def _advance_cadence(
        self, now_ts: str, cadence: str, *, deadlines: list[str | None] | None = None
    ) -> str:
        now_dt = timestamp_to_datetime(now_ts)
        assert now_dt is not None
        delta = self._cadence_delta(cadence)
        delta = self._clamp_cadence_to_deadline(now_dt, delta, deadlines)
        return (now_dt + delta).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def _clamp_cadence_to_deadline(
        self, now_dt, delta: timedelta, deadlines: list[str | None] | None
    ) -> timedelta:
        """Escalate (never slow) the cadence as the nearest deadline nears.

        Within 7 days of the nearest of close/resolution/decision deadline -> at
        most daily; within 48h -> at most twice-daily. Only SHORTENS the interval
        (``min`` with the base cadence), so a slow base cadence still speeds up near
        the wire but a fast one is never slowed. Past deadlines are ignored."""
        if not deadlines:
            return delta
        nearest = None
        for ts in deadlines:
            dt = timestamp_to_datetime(ts) if ts else None
            if dt is None or dt <= now_dt:
                continue
            if nearest is None or dt < nearest:
                nearest = dt
        if nearest is None:
            return delta
        horizon = nearest - now_dt
        if horizon <= timedelta(hours=48):
            cap = timedelta(hours=12)
        elif horizon <= timedelta(days=7):
            cap = timedelta(days=1)
        else:
            return delta
        return min(delta, cap)

    def _cadence_due(self, last_checked_at: str | None, cadence: str | None, now_dt) -> bool:
        if not last_checked_at or not cadence:
            return False
        last_dt = timestamp_to_datetime(last_checked_at)
        if last_dt is None:
            return False
        return last_dt + self._cadence_delta(cadence) <= now_dt

    def _cadence_delta(self, cadence: str) -> timedelta:
        raw = re.sub(r"\s+", " ", cadence.strip().lower())
        if raw.startswith("every "):
            raw = raw[len("every "):].strip()
        if raw in {"daily", "1d"}:
            return timedelta(days=1)
        elif raw in {"weekly", "1w"}:
            return timedelta(days=7)
        elif raw == "hourly":
            return timedelta(hours=1)
        elif raw == "minutely":
            return timedelta(minutes=1)

        match = re.fullmatch(
            r"(?P<count>\d*)\s*(?P<unit>w|week|weeks|d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes)",
            raw,
        )
        if match:
            count = max(int(match.group("count") or "1"), 1)
            unit = match.group("unit")
            if unit in {"w", "week", "weeks"}:
                return timedelta(days=count * 7)
            if unit in {"d", "day", "days"}:
                return timedelta(days=count)
            if unit in {"h", "hr", "hrs", "hour", "hours"}:
                return timedelta(hours=count)
            return timedelta(minutes=count)
        return timedelta(days=1)

    def _row_to_question(self, row: sqlite3.Row) -> ForecastQuestion:
        return _questions._row_to_question(self, row=row)

    def _row_to_snapshot(self, row: sqlite3.Row) -> ForecastSnapshot:
        row_keys = row.keys()
        return ForecastSnapshot(
            forecast_id=row["forecast_id"],
            question_id=row["question_id"],
            created_at=row["created_at"],
            as_of=row["as_of"],
            probability_or_distribution=json_loads(row["probability_or_distribution"], None),
            confidence=row["confidence"],
            forecast_horizon_days=row["forecast_horizon_days"],
            method=row["method"],
            ensemble_components=json_loads(row["ensemble_components"], {}),
            rationale=row["rationale"],
            key_assumptions=json_loads(row["key_assumptions"], []),
            assumption_refs=json_loads(row["assumption_refs"], []),
            reference_class_refs=json_loads(row["reference_class_refs"], []),
            evidence_refs=json_loads(row["evidence_refs"], []),
            model_run_refs=json_loads(row["model_run_refs"], []),
            parent_forecast_id=row["parent_forecast_id"],
            forecast_origin=row["forecast_origin"],
            agent_model=row["agent_model"],
            prompt_version=row["prompt_version"],
            forecasting_protocol_version=row["forecasting_protocol_version"],
            toolset_version=row["toolset_version"],
            source_snapshot_refs=json_loads(row["source_snapshot_refs"], []),
            evidence_cutoff=row["evidence_cutoff"],
            backtest_run_id=row["backtest_run_id"],
            calibration_eligible=bool(row["calibration_eligible"]),
            calibration_weight=row["calibration_weight"],
            calibration_lesson_refs=json_loads(row["calibration_lesson_refs"], []),
            calibration_adjustment=json_loads(row["calibration_adjustment"], {}),
            metadata=json_loads(row["metadata"], {}),
            reasons_up=json_loads(row["reasons_up"], []) if "reasons_up" in row_keys else [],
            reasons_down=json_loads(row["reasons_down"], []) if "reasons_down" in row_keys else [],
            change_my_mind=(
                json_loads(row["change_my_mind"], []) if "change_my_mind" in row_keys else []
            ),
        )

    def _row_to_evidence(self, row: sqlite3.Row) -> EvidenceItem:
        return _evidence._row_to_evidence(self, row=row)

    def _row_to_ingest_candidate(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["outcome_space"] = json_loads(data["outcome_space"], {})
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_resolution(self, row: sqlite3.Row) -> Resolution:
        return Resolution(
            id=row["id"],
            question_id=row["question_id"],
            resolved_at=row["resolved_at"],
            outcome=json_loads(row["outcome"], row["outcome"]),
            resolution_source=row["resolution_source"],
            resolution_source_snapshot_ref=row["resolution_source_snapshot_ref"],
            resolver_type=row["resolver_type"],
            resolution_status=row["resolution_status"],
            criteria_satisfied=bool(row["criteria_satisfied"]),
            confidence=row["confidence"],
            confirmed_at=row["confirmed_at"],
            confirmed_by=row["confirmed_by"],
            resolver_notes=row["resolver_notes"],
            disputed_at=row["disputed_at"],
            correction_ref=row["correction_ref"],
            scoreable=bool(row["scoreable"]),
            trusted_policy_id=row["trusted_policy_id"],
        )

    def _row_to_score(self, row: sqlite3.Row) -> ScoreRecord:
        return ScoreRecord(
            id=row["id"],
            question_id=row["question_id"],
            forecast_id=row["forecast_id"],
            resolution_id=row["resolution_id"],
            scored_at=row["scored_at"],
            brier_score=row["brier_score"],
            log_score=row["log_score"],
            proper_score=row["proper_score"],
            score_rule=row["score_rule"],
            calibration_bucket=row["calibration_bucket"],
            forecast_horizon_days=row["forecast_horizon_days"],
            domain=row["domain"],
            forecast_origin=row["forecast_origin"],
            calibration_eligible=bool(row["calibration_eligible"]),
            calibration_weight=row["calibration_weight"],
            baseline_ref=row["baseline_ref"],
            invalidated_by_correction_id=row["invalidated_by_correction_id"],
            notes=row["notes"],
        )

    def _row_to_alert(self, row: sqlite3.Row) -> AlertEvent:
        keys = set(row.keys())
        ttl = row["dismiss_ttl_days"] if "dismiss_ttl_days" in keys else None
        attempts = row["attempt_count"] if "attempt_count" in keys else 0
        return AlertEvent(
            id=row["id"],
            created_at=row["created_at"],
            severity=row["severity"],
            scope_type=row["scope_type"],
            scope_ref=row["scope_ref"],
            reason=row["reason"],
            recommended_action=row["recommended_action"],
            acknowledged_at=row["acknowledged_at"],
            dismissed_at=row["dismissed_at"] if "dismissed_at" in keys else None,
            dismiss_note=row["dismiss_note"] if "dismiss_note" in keys else None,
            dismiss_actor=row["dismiss_actor"] if "dismiss_actor" in keys else None,
            dismiss_reason=row["dismiss_reason"] if "dismiss_reason" in keys else None,
            dismiss_ttl_days=int(ttl) if ttl is not None else None,
            last_attempted_at=row["last_attempted_at"] if "last_attempted_at" in keys else None,
            attempt_count=int(attempts) if attempts is not None else 0,
        )

    def _row_to_scheduled_review_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_model_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        for field in ("inputs", "parameters", "output", "diagnostics"):
            data[field] = json_loads(data[field], {})
        data["artifact_paths"] = json_loads(data["artifact_paths"], [])
        return data

    def _row_to_calibration_lesson(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["recommended_adjustment"] = json_loads(data["recommended_adjustment"], {})
        data["source_postmortem_refs"] = json_loads(data["source_postmortem_refs"], [])
        data["source_score_record_refs"] = json_loads(data["source_score_record_refs"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_domain_error_profile(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["calibration_summary"] = json_loads(data["calibration_summary"], {})
        data["recurring_errors"] = json_loads(data["recurring_errors"], [])
        data["recommended_adjustments"] = json_loads(data["recommended_adjustments"], [])
        return data

    def _row_to_watched_source(self, row: sqlite3.Row) -> dict[str, Any]:
        return _watches._row_to_watched_source(self, row=row)

    def _row_to_source_snapshot(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["parsed_values"] = json_loads(data["parsed_values"], {})
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _row_to_autopilot_policy(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(data["enabled"])
        data["materiality_policy"] = json_loads(data["materiality_policy"], {})
        data["guardrail_policy"] = json_loads(data["guardrail_policy"], {})
        data["notification_policy"] = json_loads(data["notification_policy"], {})
        return data

    def _row_to_autopilot_run(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["diagnostics"] = json_loads(data["diagnostics"], {})
        return data

    def _row_to_forecast_update_proposal(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["proposed_probability_or_distribution"] = json_loads(
            data["proposed_probability_or_distribution"],
            None,
        )
        for field in (
            "evidence_refs",
            "source_snapshot_refs",
            "model_run_refs",
            "assumption_refs",
            "reference_class_refs",
        ):
            data[field] = json_loads(data[field], [])
        return data

    def _row_to_backtest_case(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["baseline_comparison_refs"] = json_loads(data["baseline_comparison_refs"], [])
        # AIA P1.2 columns are optional on rows read from pre-migration DBs.
        data["leakage_verdicts"] = json_loads(data.get("leakage_verdicts"), {})
        data["content_flag_count"] = int(data.get("content_flag_count") or 0)
        return data

    def _row_to_benchmark_dataset(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["cases"] = json_loads(data["cases"], [])
        data["metadata"] = json_loads(data["metadata"], {})
        return data

    def _domain_error_profile_id(
        self,
        domain: str | None,
        topic: str | None,
        horizon: str | None,
        question_type: str | None,
    ) -> str:
        raw = "|".join([domain or "", topic or "", horizon or "", question_type or ""])
        return "dep_" + uuid.uuid5(uuid.NAMESPACE_URL, raw).hex[:12]

    def _infer_ingest_source_type(self, source: str) -> str:
        if source.startswith(("http://", "https://")):
            return "url"
        if Path(source).expanduser().is_file():
            return "file"
        return "manual_note"

    def _extract_ingest_metadata(self, source: str, source_type: str) -> dict[str, Any]:
        if source_type == "url":
            return self._extract_url_ingest_metadata(source)
        if source_type != "file":
            return {}
        path = Path(source).expanduser()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ValidationError(f"could not read ingest file: {path}") from exc
        suffix = path.suffix.lower()
        if suffix == ".json":
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"ingest file is not valid JSON: {path}") from exc
            if not isinstance(payload, dict):
                raise ValidationError("ingest JSON file must contain an object")
            return self._metadata_from_ingest_payload(payload)
        if suffix == ".csv":
            rows = list(csv.DictReader(text.splitlines()))
            if not rows:
                raise ValidationError("ingest CSV file must contain at least one row")
            return self._metadata_from_ingest_payload(rows[0])
        return self._metadata_from_text_source(text)

    def _extract_url_ingest_metadata(self, source: str) -> dict[str, Any]:
        request = Request(source, headers={"User-Agent": "superforecasting-agent/0.1"})
        try:
            with urlopen(request, timeout=8) as response:
                content_type = response.headers.get("content-type", "")
                raw = response.read(512 * 1024)
        except (OSError, URLError) as exc:
            return {"metadata": {"source_fetch_error": str(exc)}}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")

        if "json" in content_type.lower() or urlparse(source).path.lower().endswith(".json"):
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                return {"metadata": {"source_fetch_error": f"invalid JSON response: {exc}"}}
            if isinstance(payload, dict):
                return self._metadata_from_ingest_payload(payload)
            return {"metadata": {"source_fetch_error": "JSON response was not an object"}}

        html_metadata = self._metadata_from_html_source(text)
        html_metadata.setdefault("metadata", {})
        html_metadata["metadata"]["source_content_type"] = content_type
        return html_metadata

    def _metadata_from_ingest_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        baselines: list[dict[str, Any]] = []
        raw_baselines = payload.get("baselines")
        if isinstance(raw_baselines, list):
            baselines.extend(self._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
        baseline = payload.get("baseline")
        if isinstance(baseline, dict):
            baselines.append(self._normalize_ingest_baseline(baseline))

        explicit_probability_fields = (
            ("baseline_probability", payload.get("baseline_type") or "imported", "baseline"),
            ("crowd_probability", "crowd", "crowd"),
            ("market_probability", "market", "market"),
            ("prior_probability", "prior", "prior"),
            ("posterior_probability", "posterior", "posterior"),
            ("forecast_probability", "imported_forecast", "forecast"),
        )
        for field, baseline_type, prefix in explicit_probability_fields:
            if payload.get(field) is None:
                continue
            baselines.append(
                {
                    "source": (
                        payload.get(f"{prefix}_source")
                        or payload.get("baseline_source")
                        or payload.get("source_name")
                        or payload.get("platform")
                        or "ingest_file"
                    ),
                    "baseline_type": baseline_type,
                    "probability_or_distribution": self._coerce_ingest_probability(payload[field]),
                    "as_of": payload.get(f"{prefix}_as_of") or payload.get("baseline_as_of") or payload.get("as_of"),
                }
            )
        if not baselines and payload.get("probability") is not None:
            baselines.append(
                {
                    "source": payload.get("baseline_source") or payload.get("source_name") or "ingest_file",
                    "baseline_type": payload.get("baseline_type") or "imported",
                    "probability_or_distribution": self._coerce_ingest_probability(payload["probability"]),
                    "as_of": payload.get("baseline_as_of") or payload.get("as_of"),
                }
            )
        baselines = self._dedupe_ingest_baselines(baselines)
        if baselines:
            metadata["baselines"] = baselines
            metadata["baseline"] = baselines[0]
        result = {
            "title": payload.get("title") or payload.get("question") or payload.get("question_title"),
            "description": payload.get("description") or payload.get("body") or "",
            "resolution_criteria": payload.get("resolution_criteria") or payload.get("criteria") or "",
            "resolution_source": payload.get("resolution_source"),
            "close_time": payload.get("close_time") or payload.get("close_date"),
            "resolution_time": payload.get("resolution_time") or payload.get("resolution_date"),
            "outcome_space": payload.get("outcome_space"),
            "metadata": metadata,
        }
        return {key: value for key, value in result.items() if value not in (None, "")}

    def _coerce_ingest_probability(self, value: Any) -> Any:
        if isinstance(value, str):
            raw = value.strip()
            if raw == "":
                return value
            if raw.endswith("%"):
                try:
                    return float(raw[:-1].strip()) / 100.0
                except ValueError:
                    return value
            try:
                return float(raw)
            except ValueError:
                return value
        return value

    def _dedupe_ingest_baselines(self, baselines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for baseline in baselines:
            if "probability_or_distribution" not in baseline and "probability" not in baseline:
                continue
            key = json_dumps(
                {
                    "source": baseline.get("source"),
                    "baseline_type": baseline.get("baseline_type"),
                    "as_of": baseline.get("as_of"),
                    "probability": self._baseline_probability_value(baseline),
                }
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(dict(baseline))
        return deduped

    def _candidate_baseline_payloads(self, metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(metadata, dict):
            return []
        baselines: list[dict[str, Any]] = []
        raw_baselines = metadata.get("baselines")
        if isinstance(raw_baselines, list):
            baselines.extend(self._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
        baseline = metadata.get("baseline")
        if isinstance(baseline, dict):
            baselines.append(self._normalize_ingest_baseline(baseline))
        return self._dedupe_ingest_baselines(baselines)

    def _baseline_probability_value(self, baseline: dict[str, Any]) -> Any:
        return baseline.get("probability_or_distribution", baseline.get("probability"))

    def _normalize_ingest_baseline(self, baseline: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(baseline)
        if "probability_or_distribution" in normalized:
            normalized["probability_or_distribution"] = self._coerce_ingest_probability(
                normalized["probability_or_distribution"]
            )
        if "probability" in normalized:
            normalized["probability"] = self._coerce_ingest_probability(normalized["probability"])
        return normalized

    def _metadata_from_text_source(self, text: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        description_lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if line.startswith("#") and "title" not in result:
                result["title"] = line.lstrip("#").strip()
                continue
            for label, field in (
                ("title:", "title"),
                ("question:", "title"),
                ("resolution criteria:", "resolution_criteria"),
                ("criteria:", "resolution_criteria"),
                ("resolution source:", "resolution_source"),
                ("close time:", "close_time"),
                ("close date:", "close_time"),
                ("resolution time:", "resolution_time"),
                ("resolution date:", "resolution_time"),
            ):
                if lowered.startswith(label):
                    result[field] = line[len(label):].strip()
                    break
            else:
                if len(description_lines) < 3:
                    description_lines.append(line)
        if "description" not in result and description_lines:
            result["description"] = "\n".join(description_lines)
        return result

    def _metadata_from_html_source(self, text: str) -> dict[str, Any]:
        parser = _IngestHTMLParser()
        try:
            parser.feed(text)
        except Exception:
            return self._metadata_from_text_source(text)
        result = self._metadata_from_text_source("\n".join(parser.text_lines))
        if parser.title and "title" not in result:
            result["title"] = parser.title.strip()
        description = parser.meta.get("description") or parser.meta.get("og:description")
        if description and not result.get("description"):
            result["description"] = description.strip()
        og_title = parser.meta.get("og:title")
        if og_title and not result.get("title"):
            result["title"] = og_title.strip()
        return result

    def _infer_watch_source_type(self, source: str) -> str:
        return _watches._infer_watch_source_type(self, source=source)

    def _rss_relevance_filters(self, metadata: dict[str, Any]) -> dict[str, list[str]]:
        raw_filters = metadata.get("relevance_filters") if isinstance(metadata, dict) else {}
        if not isinstance(raw_filters, dict):
            raw_filters = {}
        return {
            "keywords": self._rss_filter_terms(raw_filters.get("keywords")),
            "exclude_keywords": self._rss_filter_terms(raw_filters.get("exclude_keywords")),
        }

    def _rss_filter_terms(self, value: Any) -> list[str]:
        if value is None:
            return []
        values = value if isinstance(value, list) else [value]
        terms: list[str] = []
        for item in values:
            for chunk in str(item).split(","):
                term = chunk.strip()
                if term and term not in terms:
                    terms.append(term)
        return terms

    def _rss_filter_cli_args(self, filters: dict[str, list[str]]) -> str:
        parts: list[str] = []
        for term in filters.get("keywords") or []:
            parts.append(f" --keyword {self._shell_arg(term)}")
        for term in filters.get("exclude_keywords") or []:
            parts.append(f" --exclude-keyword {self._shell_arg(term)}")
        return "".join(parts)

    def _shell_arg(self, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9_./:+=,@%-]+", value):
            return value
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _source_signature(
        self,
        source: str,
        source_type: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        return _watches._source_signature(self, source=source, source_type=source_type, metadata=metadata)

    def _url_source_signature(self, source: str) -> str:
        parsed = urlparse(source)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"missing:url:{source}:invalid"
        request = Request(source, headers={"User-Agent": f"{PRODUCT_SLUG}/forecast-watch"})
        digest = hashlib.sha256()
        total = 0
        try:
            with urlopen(request, timeout=10) as response:
                while total < 2 * 1024 * 1024:
                    chunk = response.read(min(1024 * 1024, 2 * 1024 * 1024 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    digest.update(chunk)
                headers = response.headers
                return ":".join(
                    [
                        "url",
                        str(response.getcode()),
                        str(headers.get("ETag") or ""),
                        str(headers.get("Last-Modified") or ""),
                        str(headers.get("Content-Length") or ""),
                        str(total),
                        digest.hexdigest(),
                    ]
                )
        except (OSError, URLError, ValueError) as exc:
            return f"missing:url:{source}:{exc.__class__.__name__}"

    def _rss_source_signature(self, source: str, *, metadata: dict[str, Any] | None = None) -> str:
        feed_source = source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source
        filters = self._rss_relevance_filters(metadata or {})
        try:
            from forecasting.source_adapters import load_news_feed_items

            items = load_news_feed_items(
                feed_source,
                limit=50,
                keywords=filters["keywords"],
                exclude_keywords=filters["exclude_keywords"],
            )
        except Exception as exc:
            return f"missing:rss:{feed_source}:{exc.__class__.__name__}"
        payload = {
            "filters": filters,
            "items": [
                {
                    "entry_id": item.entry_id,
                    "published_at": item.published_at,
                    "title": item.title,
                    "url": item.url,
                }
                for item in items
            ],
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"rss:{len(items)}:{digest}"

    def _gdelt_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("gdelt:") else source.strip()
        if not query:
            return "missing:gdelt:empty-query"
        try:
            from forecasting.source_adapters import load_gdelt_articles

            articles = load_gdelt_articles(query, limit=50)
        except Exception as exc:
            return f"missing:gdelt:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": article.entry_id,
                "published_at": article.published_at,
                "title": article.title,
                "url": article.url,
                "domain": article.domain,
            }
            for article in articles
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"gdelt:{len(payload)}:{digest}"

    def _fivethirtyeight_source_signature(self, source: str) -> str:
        source_value = (
            source.split(":", 1)[1].strip()
            if source.startswith(("fivethirtyeight:", "538:"))
            else source.strip()
        )
        if not source_value:
            return "missing:fivethirtyeight:empty-source"
        try:
            from forecasting.source_adapters import load_fivethirtyeight_polls

            observations = load_fivethirtyeight_polls(source_value, limit=50)
        except Exception as exc:
            return f"missing:fivethirtyeight:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": observation.dataset,
                "poll_id": observation.poll_id,
                "question_id": observation.question_id,
                "pollster": observation.pollster,
                "state": observation.state,
                "cycle": observation.cycle,
                "candidate_name": observation.candidate_name,
                "answer": observation.answer,
                "pct": observation.pct,
                "sample_size": observation.sample_size,
                "end_date": observation.end_date,
                "published_at": observation.published_at,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fivethirtyeight:{len(payload)}:{digest}"

    def _github_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("github:") else source.strip()
        if not source_value:
            return "missing:github:empty-repo"
        try:
            from forecasting.source_adapters import load_github_releases

            releases = load_github_releases(source_value, limit=50)
        except Exception as exc:
            return f"missing:github:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "created_at": release.created_at,
                "draft": release.draft,
                "entry_id": release.entry_id,
                "prerelease": release.prerelease,
                "published_at": release.published_at,
                "release_id": release.release_id,
                "repo": release.repo,
                "tag_name": release.tag_name,
            }
            for release in releases
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"github:{len(payload)}:{digest}"

    def _github_repo_metadata_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubrepo:") else source.strip()
        if not source_value:
            return "missing:githubrepo:empty-repo"
        try:
            from forecasting.source_adapters import load_github_repository_snapshots

            snapshots = load_github_repository_snapshots(source_value, limit=1)
        except Exception as exc:
            return f"missing:githubrepo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "repo": item.repo,
                "default_branch": item.default_branch,
                "stargazers_count": item.stargazers_count,
                "watchers_count": item.watchers_count,
                "forks_count": item.forks_count,
                "open_issues_count": item.open_issues_count,
                "subscribers_count": item.subscribers_count,
                "network_count": item.network_count,
                "updated_at": item.updated_at,
                "pushed_at": item.pushed_at,
                "archived": item.archived,
                "disabled": item.disabled,
            }
            for item in snapshots
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubrepo:{len(payload)}:{digest}"

    def _github_issues_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubissues:") else source.strip()
        if not source_value:
            return "missing:githubissues:empty-repo"
        try:
            from forecasting.source_adapters import load_github_issues

            issues = load_github_issues(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubissues:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "closed_at": issue.closed_at,
                "comments": issue.comments,
                "entry_id": issue.entry_id,
                "is_pull_request": issue.is_pull_request,
                "issue_number": issue.issue_number,
                "labels": issue.labels,
                "state": issue.state,
                "title": issue.title,
                "updated_at": issue.updated_at,
            }
            for issue in issues
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubissues:{len(payload)}:{digest}"

    def _github_commits_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubcommits:") else source.strip()
        if not source_value:
            return "missing:githubcommits:empty-repo"
        try:
            from forecasting.source_adapters import load_github_commits

            commits = load_github_commits(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubcommits:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "author_login": commit.author_login,
                "committed_at": commit.committed_at,
                "entry_id": commit.entry_id,
                "message": commit.message,
                "repo": commit.repo,
                "sha": commit.sha,
            }
            for commit in commits
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubcommits:{len(payload)}:{digest}"

    def _github_actions_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubactions:") else source.strip()
        if not source_value:
            return "missing:githubactions:empty-repo"
        try:
            from forecasting.source_adapters import load_github_workflow_runs

            runs = load_github_workflow_runs(source_value, limit=50)
        except Exception as exc:
            return f"missing:githubactions:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "conclusion": run.conclusion,
                "display_title": run.display_title,
                "entry_id": run.entry_id,
                "event": run.event,
                "head_branch": run.head_branch,
                "head_sha": run.head_sha,
                "name": run.name,
                "repo": run.repo,
                "run_id": run.run_id,
                "status": run.status,
                "updated_at": run.updated_at,
            }
            for run in runs
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"githubactions:{len(payload)}:{digest}"

    def _coingecko_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source.strip()
        if not source_value:
            return "missing:coingecko:empty-source"
        try:
            from forecasting.source_adapters import load_coingecko_market_snapshots

            snapshots = load_coingecko_market_snapshots(source_value, limit=50)
        except Exception as exc:
            return f"missing:coingecko:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "coin_id": snapshot.coin_id,
                "symbol": snapshot.symbol,
                "vs_currency": snapshot.vs_currency,
                "current_price": snapshot.current_price,
                "market_cap": snapshot.market_cap,
                "market_cap_rank": snapshot.market_cap_rank,
                "total_volume": snapshot.total_volume,
                "price_change_percentage_24h": snapshot.price_change_percentage_24h,
                "last_updated": snapshot.last_updated,
            }
            for snapshot in snapshots
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"coingecko:{len(payload)}:{digest}"

    def _pypi_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source.strip()
        if not source_value:
            return "missing:pypi:empty-package"
        try:
            from forecasting.source_adapters import load_pypi_releases

            releases = load_pypi_releases(source_value, limit=50)
        except Exception as exc:
            return f"missing:pypi:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": release.entry_id,
                "file_count": release.file_count,
                "latest_upload_at": release.latest_upload_at,
                "package": release.package,
                "package_types": release.package_types,
                "python_versions": release.python_versions,
                "uploaded_at": release.uploaded_at,
                "version": release.version,
                "yanked": release.yanked,
                "yanked_reason": release.yanked_reason,
            }
            for release in releases
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"pypi:{len(payload)}:{digest}"

    def _npm_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source.strip()
        if not source_value:
            return "missing:npm:empty-package"
        try:
            from forecasting.source_adapters import load_npm_package_versions

            versions = load_npm_package_versions(source_value, limit=50)
        except Exception as exc:
            return f"missing:npm:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dependency_count": version.dependency_count,
                "deprecated": version.deprecated,
                "entry_id": version.entry_id,
                "license": version.license,
                "package": version.package,
                "published_at": version.published_at,
                "version": version.version,
            }
            for version in versions
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"npm:{len(payload)}:{digest}"

    def _hackernews_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source.strip()
        if not query:
            return "missing:hackernews:empty-query"
        try:
            from forecasting.source_adapters import load_hackernews_items

            items = load_hackernews_items(query, limit=50)
        except Exception as exc:
            return f"missing:hackernews:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "comments": item.comments,
                "created_at": item.created_at,
                "entry_id": item.entry_id,
                "object_id": item.object_id,
                "points": item.points,
                "title": item.title,
                "url": item.url,
            }
            for item in items
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"hackernews:{len(payload)}:{digest}"

    def _reddit_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source.strip()
        if not query:
            return "missing:reddit:empty-query"
        try:
            from forecasting.source_adapters import load_reddit_posts

            posts = load_reddit_posts(query, limit=50)
        except Exception as exc:
            return f"missing:reddit:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "comments": post.comments,
                "created_at": post.created_at,
                "entry_id": post.entry_id,
                "post_id": post.post_id,
                "score": post.score,
                "subreddit": post.subreddit,
                "title": post.title,
                "url": post.url,
                "upvote_ratio": post.upvote_ratio,
            }
            for post in posts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"reddit:{len(payload)}:{digest}"

    def _bluesky_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source.strip()
        if not query:
            return "missing:bluesky:empty-query"
        try:
            from forecasting.source_adapters import load_bluesky_posts

            posts = load_bluesky_posts(query, limit=50)
        except Exception as exc:
            return f"missing:bluesky:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "created_at": post.created_at,
                "entry_id": post.entry_id,
                "indexed_at": post.indexed_at,
                "like_count": post.like_count,
                "post_uri": post.post_uri,
                "reply_count": post.reply_count,
                "repost_count": post.repost_count,
                "text": post.text,
                "url": post.url,
            }
            for post in posts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"bluesky:{len(payload)}:{digest}"

    def _mastodon_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source.strip()
        if not source_value:
            return "missing:mastodon:empty-source"
        try:
            from forecasting.source_adapters import load_mastodon_statuses

            statuses = load_mastodon_statuses(source_value, limit=40)
        except Exception as exc:
            return f"missing:mastodon:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "account_acct": status.account_acct,
                "content_text": status.content_text,
                "created_at": status.created_at,
                "entry_id": status.entry_id,
                "favourites_count": status.favourites_count,
                "reblogs_count": status.reblogs_count,
                "replies_count": status.replies_count,
                "status_id": status.status_id,
                "url": status.url,
            }
            for status in statuses
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"mastodon:{len(payload)}:{digest}"

    def _federalregister_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("federalregister:") else source.strip()
        if not query:
            return "missing:federalregister:empty-query"
        try:
            from forecasting.source_adapters import load_federal_register_documents

            documents = load_federal_register_documents(query, limit=50)
        except Exception as exc:
            return f"missing:federalregister:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "agencies": document.agencies,
                "document_number": document.document_number,
                "document_type": document.document_type,
                "entry_id": document.entry_id,
                "published_at": document.published_at,
                "title": document.title,
                "url": document.url,
            }
            for document in documents
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"federalregister:{len(payload)}:{digest}"

    def _courtlistener_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source.strip()
        if not query:
            return "missing:courtlistener:empty-query"
        try:
            from forecasting.source_adapters import load_courtlistener_search_results

            results = load_courtlistener_search_results(query, limit=50)
        except Exception as exc:
            return f"missing:courtlistener:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "citation": result.citation,
                "court_id": result.court_id,
                "date_filed": result.date_filed,
                "docket_number": result.docket_number,
                "entry_id": result.entry_id,
                "result_id": result.result_id,
                "status": result.status,
                "title": result.title,
                "url": result.url,
            }
            for result in results
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"courtlistener:{len(payload)}:{digest}"

    def _nvd_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("nvd:") else source.strip()
        if not query:
            return "missing:nvd:empty-query"
        try:
            from forecasting.source_adapters import load_nvd_cves

            cves = load_nvd_cves(query, limit=50)
        except Exception as exc:
            return f"missing:nvd:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "base_score": cve.base_score,
                "cve_id": cve.cve_id,
                "entry_id": cve.entry_id,
                "last_modified_at": cve.last_modified_at,
                "published_at": cve.published_at,
                "severity": cve.severity,
                "vuln_status": cve.vuln_status,
            }
            for cve in cves
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"nvd:{len(payload)}:{digest}"

    def _cisa_kev_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source.strip()
        if not query:
            return "missing:cisakev:empty-query"
        try:
            from forecasting.source_adapters import load_cisa_kev_vulnerabilities

            vulnerabilities = load_cisa_kev_vulnerabilities(query, limit=50)
        except Exception as exc:
            return f"missing:cisakev:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "cve_id": vulnerability.cve_id,
                "date_added": vulnerability.date_added,
                "due_date": vulnerability.due_date,
                "entry_id": vulnerability.entry_id,
                "product": vulnerability.product,
                "ransomware_use": vulnerability.ransomware_use,
                "vendor_project": vulnerability.vendor_project,
                "vulnerability_name": vulnerability.vulnerability_name,
            }
            for vulnerability in vulnerabilities
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"cisakev:{len(payload)}:{digest}"

    def _openmeteo_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("openmeteo:") else source.strip()
        if not source_value:
            return "missing:openmeteo:empty-coordinates"
        try:
            from forecasting.source_adapters import load_openmeteo_daily_forecasts

            forecasts = load_openmeteo_daily_forecasts(source_value, limit=16, forecast_days=16)
        except Exception as exc:
            return f"missing:openmeteo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": forecast.entry_id,
                "forecast_date": forecast.forecast_date,
                "precipitation_sum": forecast.precipitation_sum,
                "temperature_2m_max": forecast.temperature_2m_max,
                "temperature_2m_min": forecast.temperature_2m_min,
                "wind_speed_10m_max": forecast.wind_speed_10m_max,
            }
            for forecast in forecasts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openmeteo:{len(payload)}:{digest}"

    def _airquality_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("airquality:") else source.strip()
        if not source_value:
            return "missing:airquality:empty-coordinates"
        try:
            from forecasting.source_adapters import load_openmeteo_air_quality_forecasts

            forecasts = load_openmeteo_air_quality_forecasts(source_value, limit=48, forecast_days=5)
        except Exception as exc:
            return f"missing:airquality:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": forecast.entry_id,
                "forecast_time": forecast.forecast_time,
                "carbon_monoxide": forecast.carbon_monoxide,
                "european_aqi": forecast.european_aqi,
                "nitrogen_dioxide": forecast.nitrogen_dioxide,
                "ozone": forecast.ozone,
                "pm10": forecast.pm10,
                "pm2_5": forecast.pm2_5,
                "us_aqi": forecast.us_aqi,
            }
            for forecast in forecasts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"airquality:{len(payload)}:{digest}"

    def _weatherhistory_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source.strip()
        if not source_value:
            return "missing:weatherhistory:empty-source"
        try:
            from forecasting.source_adapters import load_openmeteo_historical_weather

            observations = load_openmeteo_historical_weather(source_value, limit=366)
        except Exception as exc:
            return f"missing:weatherhistory:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "precipitation_sum": observation.precipitation_sum,
                "temperature_2m_mean": observation.temperature_2m_mean,
                "temperature_2m_max": observation.temperature_2m_max,
                "temperature_2m_min": observation.temperature_2m_min,
                "wind_speed_10m_max": observation.wind_speed_10m_max,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"weatherhistory:{len(payload)}:{digest}"

    def _usgs_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source.strip()
        if not source_value:
            return "missing:usgs:empty-query"
        try:
            from forecasting.source_adapters import load_usgs_earthquakes

            events = load_usgs_earthquakes(source_value, limit=50)
        except Exception as exc:
            return f"missing:usgs:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "depth_km": event.depth_km,
                "entry_id": event.entry_id,
                "event_id": event.event_id,
                "event_type": event.event_type,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "magnitude": event.magnitude,
                "place": event.place,
                "significance": event.significance,
                "status": event.status,
                "time": event.time,
                "updated_at": event.updated_at,
            }
            for event in events
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"usgs:{len(payload)}:{digest}"

    def _eonet_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source.strip()
        if not source_value:
            return "missing:eonet:empty-query"
        try:
            from forecasting.source_adapters import load_nasa_eonet_events

            events = load_nasa_eonet_events(source_value, limit=50)
        except Exception as exc:
            return f"missing:eonet:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "categories": event.categories,
                "closed_at": event.closed_at,
                "entry_id": event.entry_id,
                "event_id": event.event_id,
                "latest_geometry_at": event.latest_geometry_at,
                "latitude": event.latitude,
                "longitude": event.longitude,
                "source_names": event.source_names,
                "status": event.status,
                "title": event.title,
            }
            for event in events
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"eonet:{len(payload)}:{digest}"

    def _nws_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("nws:") else source.strip()
        if not source_value:
            return "missing:nws:empty-query"
        try:
            from forecasting.source_adapters import load_nws_alerts

            alerts = load_nws_alerts(source_value, limit=50)
        except Exception as exc:
            return f"missing:nws:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "alert_id": alert.alert_id,
                "area_desc": alert.area_desc,
                "certainty": alert.certainty,
                "effective_at": alert.effective_at,
                "ends_at": alert.ends_at,
                "event": alert.event,
                "expires_at": alert.expires_at,
                "headline": alert.headline,
                "severity": alert.severity,
                "status": alert.status,
                "urgency": alert.urgency,
            }
            for alert in alerts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"nws:{len(payload)}:{digest}"

    def _clinicaltrials_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source.strip()
        if not source_value:
            return "missing:clinicaltrials:empty-query"
        try:
            from forecasting.source_adapters import load_clinicaltrials_studies

            studies = load_clinicaltrials_studies(source_value, limit=50)
        except Exception as exc:
            return f"missing:clinicaltrials:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "completion_date": study.completion_date,
                "conditions": study.conditions,
                "entry_id": study.entry_id,
                "has_results": study.has_results,
                "last_update_posted_at": study.last_update_posted_at,
                "nct_id": study.nct_id,
                "phases": study.phases,
                "primary_completion_date": study.primary_completion_date,
                "status": study.status,
                "title": study.brief_title,
            }
            for study in studies
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"clinicaltrials:{len(payload)}:{digest}"

    def _openfda_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source.strip()
        if not source_value:
            return "missing:openfda:empty-query"
        try:
            from forecasting.source_adapters import load_openfda_drug_applications

            applications = load_openfda_drug_applications(source_value, limit=50)
        except Exception as exc:
            return f"missing:openfda:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "application_number": application.application_number,
                "brand_names": application.brand_names,
                "entry_id": application.entry_id,
                "generic_names": application.generic_names,
                "latest_submission_status": application.latest_submission_status,
                "latest_submission_status_date": application.latest_submission_status_date,
                "latest_submission_type": application.latest_submission_type,
                "marketing_statuses": application.marketing_statuses,
                "sponsor_name": application.sponsor_name,
            }
            for application in applications
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openfda:{len(payload)}:{digest}"

    def _pubmed_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source.strip()
        if not source_value:
            return "missing:pubmed:empty-query"
        try:
            from forecasting.source_adapters import load_pubmed_articles

            articles = load_pubmed_articles(source_value, limit=50)
        except Exception as exc:
            return f"missing:pubmed:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "doi": article.doi,
                "entry_id": article.entry_id,
                "journal": article.journal,
                "pmid": article.pmid,
                "publication_types": article.publication_types,
                "published_at": article.published_at,
                "revised_at": article.revised_at,
                "title": article.title,
            }
            for article in articles
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"pubmed:{len(payload)}:{digest}"

    def _owid_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source.strip()
        if not source_value:
            return "missing:owid:empty-source"
        try:
            from forecasting.source_adapters import load_owid_observations

            observations = load_owid_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:owid:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "code": observation.code,
                "entity": observation.entity,
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "slug": observation.slug,
                "value": observation.value,
                "value_column": observation.value_column,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"owid:{len(payload)}:{digest}"

    def _who_gho_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source.strip()
        if not source_value:
            return "missing:whogho:empty-source"
        try:
            from forecasting.source_adapters import load_who_gho_observations

            observations = load_who_gho_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:whogho:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dim1": observation.dim1,
                "dim2": observation.dim2,
                "dim3": observation.dim3,
                "entry_id": observation.entry_id,
                "high": observation.high,
                "indicator": observation.indicator,
                "low": observation.low,
                "numeric_value": observation.numeric_value,
                "published_at": observation.published_at,
                "spatial_dim": observation.spatial_dim,
                "time_dim": observation.time_dim,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"whogho:{len(payload)}:{digest}"

    def _fema_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source.strip()
        if not source_value:
            return "missing:fema:empty-source"
        try:
            from forecasting.source_adapters import load_fema_disaster_declarations

            declarations = load_fema_disaster_declarations(source_value, limit=50)
        except Exception as exc:
            return f"missing:fema:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "declaration_date": declaration.declaration_date,
                "declaration_string": declaration.declaration_string,
                "declaration_type": declaration.declaration_type,
                "designated_area": declaration.designated_area,
                "disaster_number": declaration.disaster_number,
                "entry_id": declaration.entry_id,
                "fiscal_year": declaration.fiscal_year,
                "incident_begin_date": declaration.incident_begin_date,
                "incident_end_date": declaration.incident_end_date,
                "incident_type": declaration.incident_type,
                "last_refresh": declaration.last_refresh,
                "state": declaration.state,
                "title": declaration.title,
            }
            for declaration in declarations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fema:{len(payload)}:{digest}"

    def _fred_source_signature(self, source: str) -> str:
        series_id = source.split(":", 1)[1].strip() if source.startswith("fred:") else source.strip()
        if not series_id:
            return "missing:fred:empty-series"
        try:
            from forecasting.source_adapters import load_fred_observations

            observations = load_fred_observations(series_id, limit=50)
        except Exception as exc:
            return f"missing:fred:{series_id}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"fred:{len(payload)}:{digest}"

    def _eia_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("eia:") else source.strip()
        if not source_value:
            return "missing:eia:empty-source"
        try:
            from forecasting.source_adapters import load_eia_observations

            observations = load_eia_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:eia:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_period": observation.observation_period,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "unit": observation.unit,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"eia:{len(payload)}:{digest}"

    def _treasury_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("treasury:") else source.strip()
        if not source_value:
            return "missing:treasury:empty-source"
        try:
            from forecasting.source_adapters import load_treasury_records

            records = load_treasury_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:treasury:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": record.dataset,
                "entry_id": record.entry_id,
                "published_at": record.published_at,
                "record_date": record.record_date,
                "value": record.value,
                "value_field": record.value_field,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"treasury:{len(payload)}:{digest}"

    def _bls_source_signature(self, source: str) -> str:
        series_id = source.split(":", 1)[1].strip() if source.startswith("bls:") else source.strip()
        if not series_id:
            return "missing:bls:empty-series"
        try:
            from forecasting.source_adapters import load_bls_observations

            observations = load_bls_observations(series_id, limit=50)
        except Exception as exc:
            return f"missing:bls:{series_id}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": observation.entry_id,
                "observation_date": observation.observation_date,
                "period": observation.period,
                "published_at": observation.published_at,
                "series_id": observation.series_id,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"bls:{len(payload)}:{digest}"

    def _worldbank_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("worldbank:") else source.strip()
        if not source_value:
            return "missing:worldbank:empty-source"
        try:
            from forecasting.source_adapters import load_worldbank_observations

            observations = load_worldbank_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:worldbank:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "country": observation.country,
                "entry_id": observation.entry_id,
                "indicator": observation.indicator,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"worldbank:{len(payload)}:{digest}"

    def _imf_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("imf:") else source.strip()
        if not source_value:
            return "missing:imf:empty-source"
        try:
            from forecasting.source_adapters import load_imf_datamapper_observations

            observations = load_imf_datamapper_observations(source_value, limit=50)
        except Exception as exc:
            return f"missing:imf:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "country": observation.country,
                "entry_id": observation.entry_id,
                "indicator": observation.indicator,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "value": observation.value,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"imf:{len(payload)}:{digest}"

    def _census_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("census:") else source.strip()
        if not source_value:
            return "missing:census:empty-source"
        try:
            from forecasting.source_adapters import load_census_records

            records = load_census_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:census:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset": record.dataset,
                "entry_id": record.entry_id,
                "geography": record.geography,
                "observation_date": record.observation_date,
                "published_at": record.published_at,
                "values": record.values,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"census:{len(payload)}:{digest}"

    def _socrata_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source.strip()
        if not source_value:
            return "missing:socrata:empty-source"
        try:
            from forecasting.source_adapters import load_socrata_records

            records = load_socrata_records(source_value, limit=50)
        except Exception as exc:
            return f"missing:socrata:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "dataset_id": record.dataset_id,
                "domain": record.domain,
                "entry_id": record.entry_id,
                "observation_time": record.observation_time,
                "row_id": record.row_id,
                "updated_at": record.updated_at,
                "values": record.values,
            }
            for record in records
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"socrata:{len(payload)}:{digest}"

    def _ckan_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source.strip()
        if not source_value:
            return "missing:ckan:empty-source"
        try:
            from forecasting.source_adapters import load_ckan_datasets

            datasets = load_ckan_datasets(source_value, limit=50)
        except Exception as exc:
            return f"missing:ckan:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": dataset.entry_id,
                "metadata_created": dataset.metadata_created,
                "metadata_modified": dataset.metadata_modified,
                "name": dataset.name,
                "package_id": dataset.package_id,
                "portal": dataset.portal,
                "resource_count": len(dataset.resources),
                "tags": dataset.tags,
                "title": dataset.title,
            }
            for dataset in datasets
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"ckan:{len(payload)}:{digest}"

    def _stooq_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("stooq:") else source.strip()
        if not source_value:
            return "missing:stooq:empty-source"
        try:
            from forecasting.source_adapters import load_stooq_prices

            observations = load_stooq_prices(source_value, limit=50)
        except Exception as exc:
            return f"missing:stooq:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "close_price": observation.close_price,
                "entry_id": observation.entry_id,
                "interval": observation.interval,
                "observation_date": observation.observation_date,
                "published_at": observation.published_at,
                "symbol": observation.symbol,
                "volume": observation.volume,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"stooq:{len(payload)}:{digest}"

    def _yahoo_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source.strip()
        if not source_value:
            return "missing:yahoo:empty-symbol"
        try:
            from forecasting.source_adapters import load_yahoo_finance_prices

            observations = load_yahoo_finance_prices(source_value, limit=50)
        except Exception as exc:
            return f"missing:yahoo:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "close_price": observation.close_price,
                "currency": observation.currency,
                "entry_id": observation.entry_id,
                "interval": observation.interval,
                "observation_time": observation.observation_time,
                "symbol": observation.symbol,
                "volume": observation.volume,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"yahoo:{len(payload)}:{digest}"

    def _sec_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("sec:") else source.strip()
        if not source_value:
            return "missing:sec:empty-cik"
        try:
            from forecasting.source_adapters import load_sec_filings

            filings = load_sec_filings(source_value, limit=50)
        except Exception as exc:
            return f"missing:sec:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "accession_number": filing.accession_number,
                "cik": filing.cik,
                "filing_date": filing.filing_date,
                "form": filing.form,
                "published_at": filing.published_at,
                "report_date": filing.report_date,
            }
            for filing in filings
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"sec:{len(payload)}:{digest}"

    def _sec_company_facts_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("secfacts:") else source.strip()
        if not source_value:
            return "missing:secfacts:empty-source"
        try:
            from forecasting.source_adapters import load_sec_company_facts

            facts = load_sec_company_facts(source_value, limit=50)
        except Exception as exc:
            return f"missing:secfacts:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "accession_number": fact.accession_number,
                "cik": fact.cik,
                "concept": fact.concept,
                "entry_id": fact.entry_id,
                "filed_at": fact.filed_at,
                "frame": fact.frame,
                "observation_date": fact.observation_date,
                "published_at": fact.published_at,
                "taxonomy": fact.taxonomy,
                "unit": fact.unit,
                "value": fact.value,
            }
            for fact in facts
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"secfacts:{len(payload)}:{digest}"

    def _arxiv_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("arxiv:") else source.strip()
        if not query:
            return "missing:arxiv:empty-query"
        try:
            from forecasting.source_adapters import load_arxiv_papers

            papers = load_arxiv_papers(query, limit=50)
        except Exception as exc:
            return f"missing:arxiv:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "arxiv_id": paper.arxiv_id,
                "categories": paper.categories,
                "entry_id": paper.entry_id,
                "published_at": paper.published_at,
                "title": paper.title,
                "updated_at": paper.updated_at,
            }
            for paper in papers
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"arxiv:{len(payload)}:{digest}"

    def _openalex_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("openalex:") else source.strip()
        if not query:
            return "missing:openalex:empty-query"
        try:
            from forecasting.source_adapters import load_openalex_works

            works = load_openalex_works(query, limit=50)
        except Exception as exc:
            return f"missing:openalex:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "concepts": work.concepts,
                "doi": work.doi,
                "entry_id": work.entry_id,
                "published_at": work.published_at,
                "title": work.title,
                "updated_at": work.updated_at,
                "work_id": work.work_id,
            }
            for work in works
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"openalex:{len(payload)}:{digest}"

    def _crossref_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("crossref:") else source.strip()
        if not query:
            return "missing:crossref:empty-query"
        try:
            from forecasting.source_adapters import load_crossref_works

            works = load_crossref_works(query, limit=50)
        except Exception as exc:
            return f"missing:crossref:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "cited_by_count": work.cited_by_count,
                "container_title": work.container_title,
                "doi": work.doi,
                "entry_id": work.entry_id,
                "published_at": work.published_at,
                "publisher": work.publisher,
                "reference_count": work.reference_count,
                "title": work.title,
                "updated_at": work.updated_at,
                "work_type": work.work_type,
            }
            for work in works
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"crossref:{len(payload)}:{digest}"

    def _reliefweb_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("reliefweb:") else source.strip()
        if not query:
            return "missing:reliefweb:empty-query"
        try:
            from forecasting.source_adapters import load_reliefweb_reports

            reports = load_reliefweb_reports(query, limit=50)
        except Exception as exc:
            return f"missing:reliefweb:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "changed_at": report.changed_at,
                "countries": report.countries,
                "disasters": report.disasters,
                "entry_id": report.entry_id,
                "published_at": report.published_at,
                "report_id": report.report_id,
                "sources": report.sources,
                "title": report.title,
                "url": report.url,
            }
            for report in reports
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"reliefweb:{len(payload)}:{digest}"

    def _wikipedia_source_signature(self, source: str) -> str:
        query = source.split(":", 1)[1].strip() if source.startswith("wikipedia:") else source.strip()
        if not query:
            return "missing:wikipedia:empty-query"
        try:
            from forecasting.source_adapters import load_wikipedia_pages

            pages = load_wikipedia_pages(query, limit=50)
        except Exception as exc:
            return f"missing:wikipedia:{query}:{exc.__class__.__name__}"
        payload = [
            {
                "entry_id": page.entry_id,
                "page_id": page.page_id,
                "title": page.title,
                "updated_at": page.updated_at,
                "url": page.url,
            }
            for page in pages
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"wikipedia:{len(payload)}:{digest}"

    def _wikipediapageviews_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source.strip()
        if not source_value:
            return "missing:wikipediapageviews:empty-source"
        try:
            from forecasting.source_adapters import load_wikimedia_pageviews

            observations = load_wikimedia_pageviews(source_value, limit=50)
        except Exception as exc:
            return f"missing:wikipediapageviews:{source_value}:{exc.__class__.__name__}"
        payload = [
            {
                "access": observation.access,
                "agent": observation.agent,
                "article": observation.article,
                "entry_id": observation.entry_id,
                "granularity": observation.granularity,
                "observation_date": observation.observation_date,
                "project": observation.project,
                "views": observation.views,
            }
            for observation in observations
        ]
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"wikipediapageviews:{len(payload)}:{digest}"

    def _manifold_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("manifold:") else source.strip()
        if not source_value:
            return "missing:manifold:empty-source"
        try:
            from forecasting.source_adapters import load_manifold_market

            market = load_manifold_market(source_value)
        except Exception as exc:
            return f"missing:manifold:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "distribution": market.distribution,
            "is_resolved": market.is_resolved,
            "market_id": market.market_id,
            "probability": market.probability,
            "question": market.question,
            "resolution": market.resolution,
            "resolution_time": market.resolution_time,
            "slug": market.slug,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"manifold:1:{digest}"

    def _metaculus_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("metaculus:") else source.strip()
        if not source_value:
            return "missing:metaculus:empty-source"
        try:
            from forecasting.source_adapters import load_metaculus_question

            question = load_metaculus_question(source_value)
        except Exception as exc:
            return f"missing:metaculus:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": question.close_time,
            "distribution": question.distribution,
            "probability": question.probability,
            "question_id": question.question_id,
            "resolution": question.resolution,
            "resolution_time": question.resolution_time,
            "status": question.status,
            "title": question.title,
            "url": question.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"metaculus:1:{digest}"

    def _polymarket_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("polymarket:") else source.strip()
        if not source_value:
            return "missing:polymarket:empty-source"
        try:
            from forecasting.source_adapters import load_polymarket_market

            market = load_polymarket_market(source_value)
        except Exception as exc:
            return f"missing:polymarket:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "distribution": market.distribution,
            "market_id": market.market_id,
            "probability": market.probability,
            "question": market.question,
            "resolution_time": market.resolution_time,
            "slug": market.slug,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"polymarket:1:{digest}"

    def _kalshi_source_signature(self, source: str) -> str:
        source_value = source.split(":", 1)[1].strip() if source.startswith("kalshi:") else source.strip()
        if not source_value:
            return "missing:kalshi:empty-source"
        try:
            from forecasting.source_adapters import load_kalshi_market

            market = load_kalshi_market(source_value)
        except Exception as exc:
            return f"missing:kalshi:{source_value}:{exc.__class__.__name__}"
        payload = {
            "close_time": market.close_time,
            "event_ticker": market.event_ticker,
            "probability": market.probability,
            "question": market.question,
            "resolution_time": market.resolution_time,
            "result": market.result,
            "status": market.status,
            "ticker": market.ticker,
            "url": market.url,
        }
        digest = hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()
        return f"kalshi:1:{digest}"

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
        text = str(value or "").strip()
        if re.fullmatch(r"[A-Za-z0-9_./:@%+=,-]+", text):
            return text
        return json.dumps(text)

    def _candidate_title_from_source(self, source: str, source_type: str) -> str:
        if source_type == "url":
            parsed = urlparse(source)
            path = parsed.path.strip("/").split("/")[-1]
            label = path.replace("-", " ").replace("_", " ").strip()
            return label or parsed.netloc or "Ingested forecast candidate"
        if source_type == "file":
            return Path(source).expanduser().stem.replace("-", " ").replace("_", " ") or "Ingested forecast candidate"
        return source[:80] or "Ingested forecast candidate"

    def _question_to_dict(self, question: ForecastQuestion) -> dict[str, Any]:
        return _questions._question_to_dict(self, question=question)

    def _snapshot_to_dict(self, snapshot: ForecastSnapshot) -> dict[str, Any]:
        return snapshot.__dict__.copy()

    def _evidence_to_dict(self, item: EvidenceItem) -> dict[str, Any]:
        return _evidence._evidence_to_dict(self, item=item)

    def _resolution_to_dict(self, resolution: Resolution) -> dict[str, Any]:
        return resolution.__dict__.copy()

    def _score_to_dict(self, score: ScoreRecord) -> dict[str, Any]:
        return score.__dict__.copy()
