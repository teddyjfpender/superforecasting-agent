"""Slice 1 — warning-resolution dispatcher (forecasting/warnings.py).

The load-bearing invariant under test: a warning is acknowledged ONLY as the
natural consequence of real gated work succeeding (a truthy runner), or as genuine
bookkeeping. NO_AUTO classes are surfaced, never acked. A failing / no-op runner
leaves the alert OPEN.
"""

from __future__ import annotations

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.warnings import (
    NormalizedWarning,
    ResolutionKind,
    ResolutionRunners,
    classify_warning,
    iter_warnings,
    resolve_alert,
)

CRIT = "Resolves yes if the reported value exceeds the stated threshold at the close date."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "warnings.db"))
    lg.initialize_schema()
    return lg


def _alert(lg, *, reason: str, severity: str = "warning", scope_ref: str = "fq_x"):
    return lg.create_alert(
        severity=severity,
        scope_type="question",
        scope_ref=scope_ref,
        reason=reason,
        recommended_action="review",
    )


# ---------------------------------------------------------------------------
# classify_warning — every reason bucket
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "reason,expected",
    [
        # POSTMORTEM
        ("postmortem_due", ResolutionKind.POSTMORTEM),
        ("high_impact_postmortem_due", ResolutionKind.POSTMORTEM),
        # MATERIAL_CHANGE
        ("watched_source_changed", ResolutionKind.MATERIAL_CHANGE),
        ("watched_source_changed:w1", ResolutionKind.MATERIAL_CHANGE),
        ("watched_source_unavailable", ResolutionKind.MATERIAL_CHANGE),
        ("trigger_fired:fred:DGS10", ResolutionKind.MATERIAL_CHANGE),
        # REFORECAST
        ("evidence_stale_7d_plus", ResolutionKind.REFORECAST),
        ("last_update_30d", ResolutionKind.REFORECAST),
        ("new_evidence:ev_123", ResolutionKind.REFORECAST),
        ("no_evidence", ResolutionKind.REFORECAST),
        ("no_forecast_snapshot", ResolutionKind.REFORECAST),
        ("close_time_within_7d", ResolutionKind.REFORECAST),
        # BOOKKEEPING
        ("autopilot_enabled:pol_1", ResolutionKind.BOOKKEEPING),
        ("autopilot_source_failed:w2", ResolutionKind.BOOKKEEPING),
        ("review_due", ResolutionKind.BOOKKEEPING),
        # SCORE — a resolved question due a Brier score is REAL gated work, not a
        # bookkeeping notice (it must never be bare-acked).
        ("score_due", ResolutionKind.SCORE),
        ("high_impact_score_due", ResolutionKind.SCORE),
        # NO_AUTO — human-judgment classes
        ("domain_error_profile_applies:dep_1", ResolutionKind.NO_AUTO),
        ("domain_error_profile_review", ResolutionKind.NO_AUTO),
        ("assumption_check_due:as_1", ResolutionKind.NO_AUTO),
        ("assumption_invalidated:as_2", ResolutionKind.NO_AUTO),
        ("assumption_stale:as_3", ResolutionKind.NO_AUTO),
        ("reference_class_stale:rc_1", ResolutionKind.NO_AUTO),
        ("reference_class_invalidated:rc_2", ResolutionKind.NO_AUTO),
        ("central_in_band", ResolutionKind.NO_AUTO),
        ("calibration_lesson_review", ResolutionKind.NO_AUTO),
        # Fail-safe defaults
        ("totally_unknown_reason_xyz", ResolutionKind.NO_AUTO),
        ("", ResolutionKind.NO_AUTO),
        (None, ResolutionKind.NO_AUTO),
    ],
)
def test_classify_covers_every_bucket(reason, expected):
    assert classify_warning(reason) is expected


def test_no_auto_prefix_wins_over_stale_matching():
    # `assumption_stale` must NOT be swept into REFORECAST by the "stale" family.
    assert classify_warning("assumption_stale:x") is ResolutionKind.NO_AUTO


# ---------------------------------------------------------------------------
# iter_warnings — normalization, priority ordering, scope filter
# ---------------------------------------------------------------------------

def test_iter_warnings_orders_worst_oldest_first(tmp_path):
    lg = _ledger(tmp_path)
    info = _alert(lg, reason="autopilot_enabled:p", severity="info", scope_ref="fq_a")
    warn = _alert(lg, reason="evidence_stale_7d_plus", severity="warning", scope_ref="fq_b")
    high = _alert(lg, reason="postmortem_due", severity="high", scope_ref="fq_c")

    ordered = list(iter_warnings(lg))
    assert [w.id for w in ordered] == [high.id, warn.id, info.id]
    assert all(isinstance(w, NormalizedWarning) for w in ordered)
    assert ordered[0].kind is ResolutionKind.POSTMORTEM


def test_iter_warnings_scope_filter(tmp_path):
    lg = _ledger(tmp_path)
    _alert(lg, reason="evidence_stale_7d_plus", scope_ref="fq_a")
    keep = _alert(lg, reason="postmortem_due", scope_ref="fq_b")

    scoped = list(iter_warnings(lg, scope="fq_b"))
    assert [w.id for w in scoped] == [keep.id]


# ---------------------------------------------------------------------------
# resolve_alert — the acknowledgement contract
# ---------------------------------------------------------------------------

def _is_open(lg, alert_id: str) -> bool:
    return any(a.id == alert_id for a in lg.list_alerts(unresolved_only=True))


def test_no_auto_is_surfaced_and_never_acked(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="domain_error_profile_applies:dep_1", severity="high")

    called = {"n": 0}

    def boom(_ledger, _w):  # must never be invoked for NO_AUTO
        called["n"] += 1
        return {"ok": True}

    runners = ResolutionRunners(
        reforecast_runner=boom, autopilot_runner=boom, score_runner=boom,
        postmortem_runner=boom,
    )
    res = resolve_alert(lg, a, runners=runners)

    assert res["status"] == "surfaced"
    assert res["acknowledged"] is False
    assert called["n"] == 0
    assert _is_open(lg, a.id)  # still OPEN


def test_failing_runner_does_not_ack(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="evidence_stale_7d_plus")

    def raises(_ledger, _w):
        raise RuntimeError("model unavailable")

    res = resolve_alert(lg, a, runners=ResolutionRunners(reforecast_runner=raises))
    assert res["status"] == "failed"
    assert res["acknowledged"] is False
    assert "model unavailable" in res["detail"]
    assert _is_open(lg, a.id)


def test_noop_runner_does_not_ack(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="watched_source_changed:w1")

    # Runner ran but performed no real gated work (returned falsy) → leave OPEN.
    res = resolve_alert(lg, a, runners=ResolutionRunners(autopilot_runner=lambda _l, _w: None))
    assert res["status"] == "failed"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)


def test_missing_runner_is_skipped_not_acked(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="evidence_stale_7d_plus")

    res = resolve_alert(lg, a, runners=ResolutionRunners())  # no reforecast_runner
    assert res["status"] == "skipped"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)


def test_successful_runner_acks(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="evidence_stale_7d_plus")

    seen = {}

    def ok(_ledger, w):
        seen["scope"] = w.scope_ref
        return {"snapshot_id": "fs_1"}

    res = resolve_alert(lg, a, runners=ResolutionRunners(reforecast_runner=ok))
    assert res["status"] == "resolved"
    assert res["acknowledged"] is True
    assert seen["scope"] == "fq_x"
    assert not _is_open(lg, a.id)  # acked


def test_material_change_routes_to_autopilot_runner(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="watched_source_changed:w1")
    routed = {}

    res = resolve_alert(
        lg,
        a,
        runners=ResolutionRunners(
            autopilot_runner=lambda _l, _w: routed.setdefault("autopilot", True),
            reforecast_runner=lambda _l, _w: routed.setdefault("reforecast", True),
        ),
    )
    assert res["status"] == "resolved"
    assert routed == {"autopilot": True}  # only the autopilot runner fired


def test_postmortem_routes_to_postmortem_runner(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="postmortem_due", severity="high")
    routed = {}

    res = resolve_alert(
        lg,
        a,
        runners=ResolutionRunners(
            postmortem_runner=lambda _l, _w: routed.setdefault("postmortem", {"ok": 1}),
            # The SCORE runner must NOT fire for a postmortem_due alert.
            score_runner=lambda _l, _w: routed.setdefault("score", "WRONG"),
        ),
    )
    assert res["status"] == "resolved"
    assert res["acknowledged"] is True
    assert routed == {"postmortem": {"ok": 1}}


def test_score_due_routes_to_score_runner_and_does_real_work(tmp_path):
    """A `score_due` alert must route to the SCORE runner (real scoring), NOT be
    bare-acked as bookkeeping. It acks ONLY on the runner's truthy result, and the
    POSTMORTEM runner must not fire for it."""
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="score_due", severity="high")
    routed = {}

    res = resolve_alert(
        lg,
        a,
        runners=ResolutionRunners(
            score_runner=lambda _l, _w: routed.setdefault("score", {"score_id": "sc_1"}),
            postmortem_runner=lambda _l, _w: routed.setdefault("postmortem", "WRONG"),
        ),
    )
    assert res["status"] == "resolved"
    assert res["acknowledged"] is True
    assert routed == {"score": {"score_id": "sc_1"}}
    assert not _is_open(lg, a.id)  # acked as the natural consequence of real scoring


def test_score_due_without_runner_stays_open_never_bare_acked(tmp_path):
    """The load-bearing rule for the old BOOKKEEPING bug: with NO score runner a
    `score_due` alert is honestly SKIPPED (left OPEN), never silently acked to drop
    the count."""
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="high_impact_score_due", severity="high")

    res = resolve_alert(lg, a, runners=ResolutionRunners())  # no score_runner
    assert res["status"] == "skipped"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)  # still OPEN — not bare-acked


def test_score_due_failing_runner_stays_open(tmp_path):
    """A scoring runner that raises (e.g. unscoreable question) must NOT ack."""
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="score_due")

    def raises(_l, _w):
        raise RuntimeError("cannot score a question with no forecast snapshot")

    res = resolve_alert(lg, a, runners=ResolutionRunners(score_runner=raises))
    assert res["status"] == "failed"
    assert res["acknowledged"] is False
    assert _is_open(lg, a.id)


def test_bookkeeping_acks_without_a_runner(tmp_path):
    lg = _ledger(tmp_path)
    a = _alert(lg, reason="autopilot_enabled:pol_1", severity="info")

    # No runners at all — bookkeeping notices are acked directly as a close-out.
    res = resolve_alert(lg, a, runners=ResolutionRunners())
    assert res["status"] == "resolved"
    assert res["acknowledged"] is True
    assert not _is_open(lg, a.id)
