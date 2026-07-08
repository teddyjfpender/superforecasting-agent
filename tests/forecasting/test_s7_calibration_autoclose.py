"""S7 calibration auto-close: the learning loop closes itself.

Covers:
  * S7.1 — resolve_question fires bias-lesson synthesis (monkeypatched observer +
    a real-gated integration on thin data that writes nothing and never raises).
  * S7.2 — use_active_lessons defaults ON in the update_forecast tool (measured
    correction applies automatically, raw_probability preserved), with an explicit
    opt-out and exploratory commits left untouched.
  * S7.3 — the time-bucketed calibration trend (mean Brier + SCE + direction).
  * S7.4 — the lessons-correcting-this surface (active lessons + coverage + dormant).
"""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from tools.forecasting_tool import forecast_ledger_tool

CRITERIA = "Resolves YES if the named official source reports the condition on the close date."


def _ledger(tmp_path, name="s7.db"):
    lg = ForecastLedger(db_path=str(tmp_path / name))
    lg.initialize_schema()
    return lg


def _committed(ledger, *, title, domain="macro", probability=0.6):
    q = ledger.create_question(title=title, resolution_criteria=CRITERIA, domain=domain)
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=probability,
        rationale="planted",
    )
    return q


# ---------------------------------------------------------------------------
# S7.1 — auto bias-lesson synthesis on resolution
# ---------------------------------------------------------------------------

class TestAutoSynthesis:
    def test_resolution_fires_synthesis_scoped_to_domain(self, tmp_path, monkeypatch):
        ledger = _ledger(tmp_path)
        q = _committed(ledger, title="Will synthesis fire on resolve?", domain="macro")

        # Clear the cheap ESS-floor pre-gate so a single live resolve triggers it.
        monkeypatch.setattr(ledger, "_live_score_count", lambda domain: 999)
        calls: list[dict] = []
        monkeypatch.setattr(
            ledger,
            "synthesize_bias_lessons",
            lambda **kwargs: calls.append(kwargs) or [],
        )
        ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)

        assert len(calls) == 1
        # Scoped to the resolved question's domain to bound cost.
        assert calls[0]["scope"] == "macro"

    def test_global_scope_when_question_has_no_domain(self, tmp_path, monkeypatch):
        ledger = _ledger(tmp_path)
        q = ledger.create_question(
            title="Will a domainless question synthesise globally?",
            resolution_criteria=CRITERIA,
        )
        ledger.create_snapshot(
            question_id=q.id, probability_or_distribution=0.4, rationale="planted"
        )
        monkeypatch.setattr(ledger, "_live_score_count", lambda domain: 999)
        calls: list[dict] = []
        monkeypatch.setattr(
            ledger, "synthesize_bias_lessons", lambda **kwargs: calls.append(kwargs) or []
        )
        ledger.resolve_question(question_id=q.id, outcome="no", auto_score=True)
        assert calls and calls[0]["scope"] == "global"

    def test_burst_resolutions_debounce_to_one_synthesis(self, tmp_path, monkeypatch):
        ledger = _ledger(tmp_path)
        # Clear the ESS-floor pre-gate; a burst of live resolutions in one process
        # must re-synthesise a scope AT MOST ONCE per debounce window (spend bound).
        monkeypatch.setattr(ledger, "_live_score_count", lambda domain: 999)
        calls: list[dict] = []
        monkeypatch.setattr(
            ledger, "synthesize_bias_lessons", lambda **kwargs: calls.append(kwargs) or []
        )
        for i in range(4):
            q = _committed(ledger, title=f"Burst macro #{i}?", domain="macro")
            ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)
        assert len(calls) == 1

    def test_thin_scope_skips_synthesis_entirely(self, tmp_path, monkeypatch):
        ledger = _ledger(tmp_path)
        q = _committed(ledger, title="Will a thin scope skip the scan?", domain="macro")
        # A single live score is far below the ESS floor → the pre-gate must skip
        # the synthesis call entirely (spend bound), not merely emit nothing.
        calls: list[dict] = []
        monkeypatch.setattr(
            ledger, "synthesize_bias_lessons", lambda **kwargs: calls.append(kwargs) or []
        )
        ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)
        assert calls == []

    def test_thin_data_writes_no_lesson_and_never_raises(self, tmp_path):
        ledger = _ledger(tmp_path)
        q = _committed(ledger, title="Will thin data stay quiet?", domain="macro")
        # Real (un-monkeypatched) gated path on a single observation: nothing is
        # written and the resolution completes cleanly.
        resolution = ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)
        assert resolution.resolution_status == "confirmed"
        active = [
            lesson for lesson in ledger.list_calibration_lessons(active_only=True)
        ]
        assert active == []

    def test_synthesis_hiccup_never_breaks_resolution(self, tmp_path, monkeypatch):
        ledger = _ledger(tmp_path)
        q = _committed(ledger, title="Will a synthesis crash break resolve?", domain="macro")

        monkeypatch.setattr(ledger, "_live_score_count", lambda domain: 999)

        def _boom(**kwargs):
            raise RuntimeError("synthesis exploded")

        monkeypatch.setattr(ledger, "synthesize_bias_lessons", _boom)
        # Resolution must still succeed and score (fail-open).
        resolution = ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)
        assert resolution.resolution_status == "confirmed"
        assert ledger.get_current_score(q.id) is not None


# ---------------------------------------------------------------------------
# S7.2 — use_active_lessons defaults ON in the tool
# ---------------------------------------------------------------------------

def _make_active_delta_lesson(ledger, *, delta=0.05, domain="macro"):
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref=domain,
        lesson="Measured under-confidence in macro; nudge toward the leaned side.",
        recommended_adjustment={"probability_delta": delta},
        status="active",
    )
    return lesson


def _update(db, question_id, **extra):
    args = {
        "db": db,
        "action": "update_forecast",
        "require_components": False,
        "reasons_up": ["base rate and recent signal point higher"],
        "reasons_down": ["small sample; reversion risk"],
        "change_my_mind": ["a confirmed contradicting data release"],
        "question_id": question_id,
        "probability": 0.70,
        "rationale": "Evidence supports yes.",
        "as_of": "2026-01-02T00:00:00Z",
        # G3: a first commit needs a linked outside-view anchor.
        "reference_class": {"name": "macro base", "inclusion_criteria": "prior macro cases", "base_rate": 0.5},
    }
    args.update(extra)
    return json.loads(forecast_ledger_tool(args))


class TestUseActiveLessonsDefault:
    def test_default_applies_measured_adjustment_with_audit_trail(self, tmp_path):
        db = str(tmp_path / "s7tool.db")
        ledger = ForecastLedger(db_path=db)
        ledger.initialize_schema()
        q = ledger.create_question(
            title="Will the default-on adjustment land?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        _make_active_delta_lesson(ledger, delta=0.05)
        # Agent commits enforce the require_evidence floor; attach one record so this
        # test isolates the calibration-lesson auto-apply behavior.
        ledger.add_evidence(question_id=q.id, source_or_note="macro print", claim="supports yes")

        # No use_active_lessons key passed at all — should apply by default.
        out = _update(db, q.id)
        assert out["success"] is True
        snap = ledger.get_current_snapshot(q.id)
        assert snap.probability_or_distribution == 0.75  # 0.70 + 0.05
        # Net movement stays auditable: raw_probability recorded before adjustment.
        assert snap.calibration_adjustment.get("raw_probability") == 0.70
        assert snap.calibration_adjustment.get("applied_probability_delta") == 0.05

    def test_explicit_opt_out_commits_raw_number(self, tmp_path):
        db = str(tmp_path / "s7tool2.db")
        ledger = ForecastLedger(db_path=db)
        ledger.initialize_schema()
        q = ledger.create_question(
            title="Will opt-out commit the raw number?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        _make_active_delta_lesson(ledger, delta=0.05)
        # Agent commits enforce the require_evidence floor; attach one record so this
        # test isolates the explicit opt-out behavior.
        ledger.add_evidence(question_id=q.id, source_or_note="macro print", claim="supports yes")

        out = _update(db, q.id, use_active_lessons=False)
        assert out["success"] is True
        snap = ledger.get_current_snapshot(q.id)
        assert snap.probability_or_distribution == 0.70  # unchanged
        assert "applied_probability_delta" not in (snap.calibration_adjustment or {})

    def test_exploratory_origin_left_unaffected(self, tmp_path):
        db = str(tmp_path / "s7tool3.db")
        ledger = ForecastLedger(db_path=db)
        ledger.initialize_schema()
        q = ledger.create_question(
            title="Will exploratory stay raw?",
            resolution_criteria=CRITERIA,
            domain="macro",
        )
        _make_active_delta_lesson(ledger, delta=0.05)

        out = _update(db, q.id, forecast_origin="exploratory")
        assert out["success"] is True
        snap = ledger.get_current_snapshot(q.id)
        assert snap.probability_or_distribution == 0.70  # exploratory never adjusted


# ---------------------------------------------------------------------------
# S7.3 — calibration trend buckets
# ---------------------------------------------------------------------------

class TestCalibrationTrend:
    def test_trend_math_improving(self, tmp_path):
        ledger = _ledger(tmp_path)
        now = "2026-07-01T00:00:00Z"
        # 5 recent (within 30d) low-Brier points + 5 old (60d ago) high-Brier points.
        points = []
        for _ in range(5):
            points.append(
                {"scored_at": "2026-06-28T00:00:00Z", "brier": 0.05, "p_yes": 0.9, "outcome": 1.0}
            )
        for _ in range(5):
            points.append(
                {"scored_at": "2026-05-02T00:00:00Z", "brier": 0.30, "p_yes": 0.8, "outcome": 0.0}
            )
        trend = ledger._calibration_trend(points, now=now)
        windows = {w["period"]: w for w in trend["windows"]}
        assert windows["30d"]["n"] == 5
        assert windows["30d"]["brier"] == 0.05
        assert windows["90d"]["n"] == 10
        assert windows["90d"]["brier"] == pytest.approx(0.175)
        # Recent Brier materially lower than the longer window → improving.
        assert trend["direction"] == "improving"
        # SCE present for the binary points in each window.
        assert windows["30d"]["sce"] is not None

    def test_trend_insufficient_on_thin_window(self, tmp_path):
        ledger = _ledger(tmp_path)
        now = "2026-07-01T00:00:00Z"
        points = [
            {"scored_at": "2026-06-30T00:00:00Z", "brier": 0.1, "p_yes": None, "outcome": None}
        ]
        trend = ledger._calibration_trend(points, now=now)
        assert trend["direction"] == "insufficient"

    def test_trend_ignores_unparseable_timestamps(self, tmp_path):
        ledger = _ledger(tmp_path)
        points = [{"scored_at": "not-a-date", "brier": 0.1, "p_yes": None, "outcome": None}]
        trend = ledger._calibration_trend(points, now="2026-07-01T00:00:00Z")
        assert trend["windows"][0]["n"] == 0

    def test_summary_includes_trend_key(self, tmp_path):
        ledger = _ledger(tmp_path)
        q = _committed(ledger, title="Will the summary carry a trend?", domain="macro")
        ledger.resolve_question(question_id=q.id, outcome="yes", auto_score=True)
        summary = ledger.calibration_summary(calibration_eligible=None)
        assert "calibration_trend" in summary
        assert "windows" in summary["calibration_trend"]


# ---------------------------------------------------------------------------
# S7.4 — lessons-correcting-this
# ---------------------------------------------------------------------------

class TestCorrectingLessons:
    def test_active_lesson_surfaces_with_coverage(self, tmp_path):
        ledger = _ledger(tmp_path)
        _make_active_delta_lesson(ledger, delta=0.05, domain="macro")
        rows = ledger.calibration_correcting_lessons()
        assert len(rows) == 1
        row = rows[0]
        assert row["scope"] == "domain:macro"
        assert row["recommended_adjustment"].get("probability_delta") == 0.05
        # Never encountered at a commit yet → dormant.
        assert row["dormant"] is True
        assert row["coverage"]["in_scope_count"] == 0

    def test_domain_filter_keeps_global_but_drops_other_domains(self, tmp_path):
        ledger = _ledger(tmp_path)
        _make_active_delta_lesson(ledger, delta=0.05, domain="macro")
        _make_active_delta_lesson(ledger, delta=-0.03, domain="politics")
        ledger.create_calibration_lesson(
            scope_type="global",
            scope_ref=None,
            lesson="Global de-hedge.",
            recommended_adjustment={"logit_scale": 1.2},
            status="active",
        )
        rows = ledger.calibration_correcting_lessons(domain="macro")
        scopes = {r["scope"] for r in rows}
        assert "domain:macro" in scopes
        assert "global:*" in scopes  # global applies broadly
        assert "domain:politics" not in scopes
