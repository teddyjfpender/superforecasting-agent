"""Slice 1 — warning-resolution dispatcher (forecasting/warnings.py).

The load-bearing invariant under test: a warning is acknowledged ONLY as the
natural consequence of real gated work succeeding (a truthy runner), or as genuine
bookkeeping. NO_AUTO classes are surfaced, never acked. A failing / no-op runner
leaves the alert OPEN.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from forecasting.cron_runner import run_warning_resolution
from forecasting.ledger import ForecastLedger
from forecasting.warnings import (
    WARNING_TIERS,
    NormalizedWarning,
    ResolutionKind,
    ResolutionRunners,
    classify_warning,
    coerce_kind,
    expand_tier,
    iter_warnings,
    resolve_alert,
    resolve_kind_filter,
    select_open_warnings,
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
        ("watched_source_unavailable", ResolutionKind.NO_AUTO),
        # REFORECAST
        ("evidence_stale_7d_plus", ResolutionKind.REFORECAST),
        ("last_update_30d", ResolutionKind.REFORECAST),
        ("new_evidence:ev_123", ResolutionKind.REFORECAST),
        ("close_time_within_7d", ResolutionKind.REFORECAST),
        ("trigger_fired:fred:DGS10", ResolutionKind.REFORECAST),
        ("learned_error_update_required:dep_1", ResolutionKind.REFORECAST),
        # EVIDENCE_COLLECTION — no evidence / no snapshot yet: collect first, then
        # (re)forecast. Routed to its own kind so the zero-evidence-gated REFORECAST
        # runner never silently swallows them as "skipped: update gated".
        ("no_evidence", ResolutionKind.EVIDENCE_COLLECTION),
        ("no_forecast_snapshot", ResolutionKind.EVIDENCE_COLLECTION),
        # BOOKKEEPING
        ("autopilot_enabled:pol_1", ResolutionKind.BOOKKEEPING),
        ("autopilot_source_failed:w2", ResolutionKind.MATERIAL_CHANGE),
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


# ---------------------------------------------------------------------------
# Tier / kinds filter — per-tier bulk selection
# ---------------------------------------------------------------------------

def test_coerce_kind_accepts_enum_value_and_name():
    assert coerce_kind(ResolutionKind.SCORE) is ResolutionKind.SCORE
    # by enum value (the wire form a JSON RPC / CLI would send)
    assert coerce_kind("score") is ResolutionKind.SCORE
    assert coerce_kind("material_change") is ResolutionKind.MATERIAL_CHANGE
    # hyphen/underscore + case insensitive
    assert coerce_kind("Material-Change") is ResolutionKind.MATERIAL_CHANGE
    # by enum NAME
    assert coerce_kind("REFORECAST") is ResolutionKind.REFORECAST


def test_coerce_kind_rejects_unknown():
    with pytest.raises(ValueError):
        coerce_kind("not_a_kind")


def test_expand_tier_free_and_reforecast():
    assert expand_tier("free") == frozenset(
        {
            ResolutionKind.BOOKKEEPING,
            ResolutionKind.SCORE,
            ResolutionKind.POSTMORTEM,
            ResolutionKind.MATERIAL_CHANGE,
        }
    )
    # The heavy "reforecast"/agent tier holds both LLM kinds.
    assert expand_tier("reforecast") == frozenset(
        {ResolutionKind.REFORECAST, ResolutionKind.EVIDENCE_COLLECTION}
    )
    # NO_AUTO is in no tier (never auto-resolved, so it can't be bulk-actioned).
    all_tier_kinds = set().union(*WARNING_TIERS.values())
    assert ResolutionKind.NO_AUTO not in all_tier_kinds


def test_expand_tier_aliases():
    assert expand_tier("run-free-pass") == expand_tier("free")
    assert expand_tier("reforecast-tier") == expand_tier("reforecast")


def test_expand_tier_rejects_unknown():
    with pytest.raises(ValueError):
        expand_tier("nope")


def test_resolve_kind_filter_none_when_unfiltered():
    # No tier + no kinds => None ("match everything"), distinct from an empty set.
    assert resolve_kind_filter() is None
    assert resolve_kind_filter(kinds=[]) == frozenset()  # explicit "match nothing"


def test_resolve_kind_filter_unions_tier_and_kinds():
    got = resolve_kind_filter(tier="free", kinds=["reforecast"])
    assert got == expand_tier("free") | {ResolutionKind.REFORECAST}


def _seed_one_per_kind(lg):
    """Create one open alert per resolution kind; return {kind: alert_id}."""
    reasons = {
        ResolutionKind.MATERIAL_CHANGE: "watched_source_changed:w1",
        ResolutionKind.REFORECAST: "evidence_stale_7d_plus",
        ResolutionKind.SCORE: "score_due",
        ResolutionKind.POSTMORTEM: "postmortem_due",
        ResolutionKind.BOOKKEEPING: "autopilot_enabled:p1",
        ResolutionKind.NO_AUTO: "domain_error_profile_review",
    }
    ids = {}
    for kind, reason in reasons.items():
        a = _alert(lg, reason=reason, scope_ref=f"fq_{kind.value}")
        ids[kind] = a.id
    return ids


def test_select_open_warnings_kinds_filter(tmp_path):
    lg = _ledger(tmp_path)
    ids = _seed_one_per_kind(lg)

    got = select_open_warnings(lg, kinds=[ResolutionKind.SCORE, "postmortem"])
    assert {w.kind for w in got} == {ResolutionKind.SCORE, ResolutionKind.POSTMORTEM}
    assert {w.id for w in got} == {ids[ResolutionKind.SCORE], ids[ResolutionKind.POSTMORTEM]}


def test_select_open_warnings_free_tier(tmp_path):
    lg = _ledger(tmp_path)
    _seed_one_per_kind(lg)

    got = select_open_warnings(lg, tier="free")
    assert {w.kind for w in got} == expand_tier("free")
    # REFORECAST + NO_AUTO are excluded from the free tier.
    assert ResolutionKind.REFORECAST not in {w.kind for w in got}
    assert ResolutionKind.NO_AUTO not in {w.kind for w in got}


def test_select_open_warnings_reforecast_tier(tmp_path):
    lg = _ledger(tmp_path)
    _seed_one_per_kind(lg)

    got = select_open_warnings(lg, tier="reforecast")
    assert {w.kind for w in got} == {ResolutionKind.REFORECAST}


def test_select_open_warnings_no_filter_returns_all(tmp_path):
    lg = _ledger(tmp_path)
    ids = _seed_one_per_kind(lg)

    got = select_open_warnings(lg)
    assert {w.id for w in got} == set(ids.values())


def test_select_open_warnings_kind_filter_applies_before_limit(tmp_path):
    lg = _ledger(tmp_path)
    # Two SCORE alerts + a higher-priority MATERIAL_CHANGE that the limit would
    # otherwise eat first. The tier filter must run BEFORE the limit so limit caps
    # the TIER's backlog, not the whole one.
    _alert(lg, reason="watched_source_changed:w1", severity="high", scope_ref="fq_mc")
    s1 = _alert(lg, reason="score_due", scope_ref="fq_s1")
    s2 = _alert(lg, reason="score_due", scope_ref="fq_s2")

    got = select_open_warnings(lg, kinds=["score"], limit=1)
    assert len(got) == 1
    assert got[0].kind is ResolutionKind.SCORE
    assert got[0].id in {s1.id, s2.id}


def test_concurrent_warning_workers_share_one_durable_alert_task(tmp_path):
    first_ledger = _ledger(tmp_path)
    second_ledger = ForecastLedger(first_ledger.db_path)
    alert = _alert(
        first_ledger,
        reason="evidence_stale_7d_plus",
        scope_ref="fq_concurrent",
    )
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def runner(_ledger, _warning):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return {"status": "committed"}

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            run_warning_resolution,
            ledger=first_ledger,
            tier="reforecast",
            reforecast_runner=runner,
            reconcile=False,
        )
        assert started.wait(timeout=5)
        second = pool.submit(
            run_warning_resolution,
            ledger=second_ledger,
            tier="reforecast",
            reforecast_runner=runner,
            reconcile=False,
        )
        second_result = second.result(timeout=5)
        release.set()
        first_result = first.result(timeout=5)

    assert calls == 1
    assert first_result["tally"] == {"resolved": 1}
    assert second_result["tally"] == {"claimed_elsewhere": 1}
    tasks = first_ledger.list_operational_tasks()
    assert len(tasks) == 1
    assert tasks[0]["alert_id"] == alert.id
    assert tasks[0]["status"] == "completed"


def test_estimation_alerts_for_one_question_consume_one_paid_run(tmp_path):
    ledger = _ledger(tmp_path)
    for model_run_id in ("mr_old", "mr_new"):
        _alert(
            ledger,
            reason=f"forecast_estimation_required:{model_run_id}",
            scope_ref="fq_same_question",
        )
    calls = []

    result = run_warning_resolution(
        ledger=ledger,
        tier="reforecast",
        reforecast_runner=lambda _ledger, warning: calls.append(warning.id) or True,
        reconcile=False,
    )

    assert result["processed"] == 1
    assert len(calls) == 1
