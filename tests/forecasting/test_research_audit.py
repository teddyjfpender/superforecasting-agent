"""VOI-directed research planning + the research-adequacy judge (Arc 2, slice R1).

Covers: plan derivation from the question's own levers; each deterministic adequacy
check (positive + negative); the adequacy threshold + ERROR-gap gate; the two tool
actions; the chain re-runs research on inadequate then stops at the cap; and the
research_adequate hook rule's per-profile severity.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.research_audit import (
    audit_research,
    audit_research_for_commit,
    build_research_plan,
    deterministic_research_checks,
    research_stage_incomplete,
)


def _fresh() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale(days: int = 90) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "ra.db"))
    lg.initialize_schema()
    return lg


def _question(lg, **over):
    kw = dict(
        title="Will the Fed cut rates by September 2026?",
        resolution_criteria="Resolves YES if the FOMC lowers the target range per its statement on or before 2026-09-30; otherwise NO.",
    )
    kw.update(over)
    return lg.create_question(**kw)


# ── build_research_plan ───────────────────────────────────────────────────────
def test_plan_has_standard_angles():
    from types import SimpleNamespace as NS

    q = NS(id="q1", title="Will X happen by 2026?", update_triggers=[])
    plan = build_research_plan(q, snapshot=None)
    kinds = {a["kind"] for a in plan["angles"]}
    assert {"primary_source", "base_rate", "recent_developments", "contrarian"} <= kinds
    # every angle carries at least one suggested query
    assert all(a["suggested_queries"] for a in plan["angles"])


def test_plan_derives_voi_angles_from_levers():
    from types import SimpleNamespace as NS

    q = NS(
        id="q1",
        title="Will the Fed cut rates by September 2026?",
        update_triggers=[
            {"mechanism": "CPI year-over-year", "source_ref": "fred:CPIAUCSL", "operator": ">", "threshold": 3.0},
        ],
    )
    snap = NS(
        change_my_mind=["If unemployment rises above 5%"],
        reasons_down=[],
        evidence_refs=[],
        metadata={"tail_audit": {"verdicts": [{"name": "Cut", "path": "a dovish pivot on soft data"}]}},
    )
    plan = build_research_plan(q, snapshot=snap)
    by_kind = {}
    for a in plan["angles"]:
        by_kind.setdefault(a["kind"], []).append(a)
    # one angle per lever
    assert len(by_kind["update_trigger"]) == 1
    assert len(by_kind["change_my_mind"]) == 1
    assert len(by_kind["outcome_path"]) == 1
    # the trigger angle's query mentions the source_ref
    assert any("fred:CPIAUCSL" in q for q in by_kind["update_trigger"][0]["suggested_queries"])


# ── deterministic checks: positive + negative ─────────────────────────────────
def _good_evidence():
    from types import SimpleNamespace as NS

    return [
        NS(source_url="https://a.com", source_name="A", source_type="rss", stance="supports", available_at=_fresh(), claim="up", summary=""),
        NS(source_url="https://b.com", source_name="B", source_type="rss", stance="opposes", available_at=_fresh(), claim="down", summary=""),
        NS(source_url="https://c.com", source_name="C", source_type="fred", stance="context", available_at=_fresh(), claim="fred:CPIAUCSL", summary=""),
    ]


def _q_with_trigger():
    from types import SimpleNamespace as NS

    return NS(
        id="q1", title="Will the Fed cut rates?",
        update_triggers=[{"mechanism": "CPI", "source_ref": "fred:CPIAUCSL", "operator": ">", "threshold": 3.0}],
    )


def test_all_checks_pass():
    q = _q_with_trigger()
    res = deterministic_research_checks(
        question=q, evidence=_good_evidence(),
        reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL", "source_type": "fred"}],
        reasons_down=["a risk"], evidence_refs=["e1"],
        now=datetime.now(timezone.utc),
    )
    assert res["checks"] == {
        "reference_class_present": True, "evidence_floor": True, "source_independence": True,
        "disconfirming_present": True, "recency": True, "triggers_covered": True,
    }
    assert res["score"] == 100.0
    assert res["adequate_deterministic"] is True


def test_reference_class_gap_is_error_weight():
    q = _q_with_trigger()
    res = deterministic_research_checks(
        question=q, evidence=_good_evidence(), reference_classes=[],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=["r"], evidence_refs=["e1"],
        now=datetime.now(timezone.utc),
    )
    assert res["checks"]["reference_class_present"] is False
    # an ERROR-weight gap => not adequate even though every other check passes
    assert res["adequate_deterministic"] is False
    assert any(g["kind"] == "reference_class_present" for g in res["gaps"])


def test_evidence_floor_negative():
    from types import SimpleNamespace as NS

    q = _q_with_trigger()
    one = [NS(source_url="https://a.com", source_name="A", source_type="rss", stance="opposes", available_at=_fresh(), claim="x", summary="")]
    res = deterministic_research_checks(
        question=q, evidence=one, reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=["r"], evidence_refs=["e1"],
        now=datetime.now(timezone.utc),
    )
    assert res["checks"]["evidence_floor"] is False
    assert res["adequate_deterministic"] is False  # ERROR-weight


def test_source_independence_negative():
    from types import SimpleNamespace as NS

    q = _q_with_trigger()
    # three rows, ONE distinct source identity
    same = [NS(source_url="https://a.com", source_name="A", source_type="rss", stance="opposes", available_at=_fresh(), claim="x", summary="") for _ in range(3)]
    res = deterministic_research_checks(
        question=q, evidence=same, reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=["r"], evidence_refs=["e1"],
        now=datetime.now(timezone.utc),
    )
    assert res["checks"]["source_independence"] is False


def test_disconfirming_stance_and_structural_proxy():
    from types import SimpleNamespace as NS

    q = _q_with_trigger()
    # no opposing/mixed stance, but the structural proxy (reasons_down + a cited ref) holds
    only_supports = [NS(source_url=f"https://{c}.com", source_name=c, source_type="rss", stance="supports", available_at=_fresh(), claim="x", summary="") for c in "abc"]
    proxy = deterministic_research_checks(
        question=q, evidence=only_supports, reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=["a downside risk"], evidence_refs=["e1"],
        now=datetime.now(timezone.utc),
    )
    assert proxy["checks"]["disconfirming_present"] is True  # structural proxy
    # remove the proxy too => the check fails
    no_proxy = deterministic_research_checks(
        question=q, evidence=only_supports, reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=[], evidence_refs=[],
        now=datetime.now(timezone.utc),
    )
    assert no_proxy["checks"]["disconfirming_present"] is False


def test_recency_negative_when_all_stale():
    from types import SimpleNamespace as NS

    q = _q_with_trigger()
    stale = [NS(source_url=f"https://{c}.com", source_name=c, source_type="rss", stance="opposes", available_at=_stale(), claim="x", summary="") for c in "abc"]
    res = deterministic_research_checks(
        question=q, evidence=stale, reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL"}], reasons_down=["r"], evidence_refs=["e1"],
        stale_evidence_days=30, now=datetime.now(timezone.utc),
    )
    assert res["checks"]["recency"] is False


def test_triggers_covered_positive_and_negative():
    q = _q_with_trigger()
    # covered: a watched source keyed on the trigger's source_ref
    covered = deterministic_research_checks(
        question=q, evidence=_good_evidence(), reference_classes=[{"status": "active"}],
        watched_sources=[{"source": "fred:CPIAUCSL", "source_type": "fred"}],
        reasons_down=["r"], evidence_refs=["e1"], now=datetime.now(timezone.utc),
    )
    assert covered["checks"]["triggers_covered"] is True
    # uncovered: no watched source and no evidence naming the series
    from types import SimpleNamespace as NS

    bare = [NS(source_url=f"https://{c}.com", source_name=c, source_type="rss", stance="opposes", available_at=_fresh(), claim="unrelated", summary="") for c in "ab"]
    uncovered = deterministic_research_checks(
        question=q, evidence=bare, reference_classes=[{"status": "active"}],
        watched_sources=[], reasons_down=["r"], evidence_refs=["e1"], now=datetime.now(timezone.utc),
    )
    assert uncovered["checks"]["triggers_covered"] is False


def test_research_stage_incomplete_excludes_reference_class():
    # reference class missing but every research-stage check passes => the chain's
    # research re-run trigger is NOT tripped (reference class is base_rate's job).
    audit = {"checks": {
        "reference_class_present": False, "evidence_floor": True, "source_independence": True,
        "disconfirming_present": True, "recency": True, "triggers_covered": True,
    }}
    assert research_stage_incomplete(audit) is False
    audit["checks"]["evidence_floor"] = False
    assert research_stage_incomplete(audit) is True


# ── audit_research over a live ledger + the commit-time helper + threshold ─────
def test_audit_research_threshold_gate(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    # thin: one evidence row, no reference class
    lg.add_evidence(question_id=q.id, source_or_note="a note", source_name="a", available_at=_fresh())
    audit = audit_research(lg, q)
    assert audit["adequate"] is False
    assert audit["score"] < audit["threshold"]

    # a low threshold still cannot rescue an ERROR-weight gap (no reference class)
    audit_low = audit_research(lg, q, threshold=1.0)
    assert audit_low["adequate"] is False


def test_audit_research_for_commit_uses_candidate_reasons_down(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    for c in "abc":
        lg.add_evidence(question_id=q.id, source_or_note=f"note {c}", source_name=f"src-{c}", available_at=_fresh(), stance="supports")
    lg.add_reference_class(question_id=q.id, name="recent", inclusion_criteria="last 12", base_rate=0.4)
    # candidate commit carries reasons_down + a cited ref => disconfirming proxy holds
    ev_ids = [e.id for e in lg.list_evidence(q.id)]
    audit = audit_research_for_commit(
        lg, q, reasons_down=["a downside risk"], evidence_refs=ev_ids, threshold=70,
    )
    assert audit["checks"]["disconfirming_present"] is True
    assert audit["adequate"] is True


# ── tool actions ──────────────────────────────────────────────────────────────
def test_tool_research_plan_and_audit_actions(tmp_path, monkeypatch):
    from tools.forecasting_tool import forecast_ledger_tool

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    lg = _ledger(tmp_path)
    q = _question(lg)

    plan_out = json.loads(forecast_ledger_tool({"action": "research_plan", "db": str(tmp_path / "ra.db"), "question_id": q.id}))
    assert plan_out["success"] is True
    assert plan_out["plan"]["angles"]

    audit_out = json.loads(forecast_ledger_tool({"action": "research_audit", "db": str(tmp_path / "ra.db"), "question_id": q.id}))
    assert audit_out["success"] is True
    assert audit_out["audit"]["adequate"] is False  # empty question is inadequate
    # deterministic-only: no LLM check when no model passed
    assert "llm_check" not in audit_out["audit"]


# ── chain loop: re-run research on inadequate, stop at cap ─────────────────────
def test_chain_reruns_research_then_stops_at_cap(tmp_path, monkeypatch):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _question(lg)
    calls: list[str] = []

    # A stub that lands nothing: research stays inadequate. The loop re-runs research,
    # the no-progress guard bounds it to ONE extra pass.
    def stub(ledger, qid, *, stage="update", supplemental=None, **kw):
        calls.append(stage)
        return {}

    monkeypatch.setattr(cli, "_run_update_agent", stub)
    res = cli.run_forecast_chain(lg, q.id, stages=["research"], commit_policy=None)
    assert calls == ["research", "research"]  # original + one adequacy re-run
    assert res["research_audit_rounds"] == 1
    assert res["research_audit"] is not None and res["research_audit"]["adequate"] is False


def test_chain_no_rerun_when_research_adequate(tmp_path, monkeypatch):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _question(lg)
    calls: list[str] = []

    def stub(ledger, qid, *, stage="update", supplemental=None, **kw):
        calls.append(stage)
        if stage == "research":
            for c in "abc":
                ledger.add_evidence(question_id=qid, source_or_note=f"note {c}", source_name=f"src-{c}", available_at=_fresh(), stance=("opposes" if c == "b" else "supports"))
        return {}

    monkeypatch.setattr(cli, "_run_update_agent", stub)
    res = cli.run_forecast_chain(lg, q.id, stages=["research"], commit_policy=None)
    # research-stage checks all pass (reference_class is base_rate's job, excluded) => no re-run
    assert calls == ["research"]
    assert res["research_audit_rounds"] == 0


def test_chain_respects_max_audit_rounds_zero(tmp_path, monkeypatch):
    import forecasting.cli as cli

    lg = _ledger(tmp_path)
    q = _question(lg)
    calls: list[str] = []
    monkeypatch.setattr(cli, "_run_update_agent", lambda ledger, qid, *, stage="update", supplemental=None, **kw: calls.append(stage) or {})
    # force max_audit_rounds=0 via config. DEEP-COPY the cached config before mutating
    # — load_config_readonly returns the shared in-process cache, so mutating it in
    # place would corrupt config for every later test.
    import copy

    import hermes_cli.config as config

    real = config.load_config_readonly

    def patched():
        cfg = copy.deepcopy(real())
        cfg.setdefault("forecasting", {}).setdefault("research", {})["max_audit_rounds"] = 0
        return cfg

    monkeypatch.setattr(config, "load_config_readonly", patched)
    res = cli.run_forecast_chain(lg, q.id, stages=["research"], commit_policy=None)
    assert calls == ["research"]  # no extra pass when the cap is 0
    assert res["research_audit_rounds"] == 0


# ── hook rule severity per profile ────────────────────────────────────────────
def test_research_adequate_rule_severity_per_profile():
    from forecasting.hooks.builtins import BUILTIN_RULE_IDS
    from forecasting.hooks.profiles import profile_severities
    from forecasting.hooks.spec import Severity

    assert "research_adequate" in BUILTIN_RULE_IDS
    assert profile_severities("exploratory-lenient")["research_adequate"] is Severity.OFF
    assert profile_severities("standard")["research_adequate"] is Severity.WARN
    assert profile_severities("strict")["research_adequate"] is Severity.ERROR


def test_research_adequate_rule_fires_only_when_inadequate():
    from forecasting.hooks import HookContext, run_hooks
    from forecasting.hooks.profiles import profile_severities

    policy = profile_severities("strict")
    inadequate = HookContext(
        question_id="q", forecast_origin="live", event="update",
        research_adequate=False, research_adequacy_score=30.0,
    )
    report = run_hooks(inadequate, policy)
    blocked = {v.rule_id for v in report.blocking_failures()}
    assert "research_adequate" in blocked

    adequate = HookContext(
        question_id="q", forecast_origin="live", event="update",
        research_adequate=True, research_adequacy_score=90.0,
    )
    report2 = run_hooks(adequate, policy)
    assert "research_adequate" not in {v.rule_id for v in report2.blocking_failures()}
