"""AIA P1.1 — the agentic-supervisor fresh-search loop.

The supervisor is what turns "matches the mean" into "beats the mean": it reads
the judge synthesis, detects an UNRESOLVED CRUX (information_gap +
clarifying_queries), runs FRESH search, and re-synthesises with the new
evidence. It does NOT re-weight the panel.

These tests pin the deterministic, testable core:
  * JudgeSynthesis tolerantly parses information_gap + clarifying_queries;
  * should_research is the pure, bounded research-gate truth table;
  * run_quorum with a MOCK search_runner + a gap-flagging judge does exactly
    one research round, appends the fresh evidence, re-synthesises, and records
    research_rounds=1 + supervisor_evidence;
  * the HARD CONSTRAINT: with NO search_runner the result is byte-identical to a
    baseline run (same probability, final_source, applied_alpha, research_rounds
    0, supervisor_evidence empty);
  * the loop never exceeds max_research_rounds;
  * the terminal Platt lands EXACTLY ONCE even with a research round.
"""

from __future__ import annotations

import json

import pytest

from forecasting.bayes_toolkit import platt_scale, prob_to_odds
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace
from forecasting.quorum import (
    JudgeSynthesis,
    parse_judge_response,
    run_quorum,
    should_research,
)


# ── 1. JudgeSynthesis parse: information_gap + clarifying_queries ──────────────


def test_parse_extracts_information_gap_and_queries():
    payload = {
        "probability": 0.6,
        "information_gap": True,
        "clarifying_queries": ["q1", "q2"],
    }
    judge = parse_judge_response(json.dumps(payload), "opus")
    assert judge.information_gap is True
    assert judge.clarifying_queries == ["q1", "q2"]


def test_parse_tolerates_absent_gap_fields():
    judge = parse_judge_response(json.dumps({"probability": 0.6}), "opus")
    assert judge.information_gap is False
    assert judge.clarifying_queries == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True),
        ("true", True),
        ("YES", True),
        (1, True),
        (False, False),
        ("no", False),
        (0, False),
        ("garbage", False),
        (None, False),
    ],
)
def test_parse_information_gap_is_tolerant(raw, expected):
    judge = parse_judge_response(
        json.dumps({"probability": 0.6, "information_gap": raw}), "opus"
    )
    assert judge.information_gap is expected


def test_parse_garbage_queries_yield_empty_list():
    judge = parse_judge_response(
        json.dumps({"probability": 0.6, "clarifying_queries": 5}), "opus"
    )
    assert judge.clarifying_queries == []


def test_judge_default_gap_fields_are_non_triggering():
    j = JudgeSynthesis(probability=0.7, rationale="")
    assert j.information_gap is False and j.clarifying_queries == []


# ── 2. should_research truth table (pure, bounded) ────────────────────────────


def _gap_judge(gap=True, queries=("need x",)):
    return JudgeSynthesis(
        probability=0.6,
        rationale="r",
        information_gap=gap,
        clarifying_queries=list(queries),
    )


def test_should_research_true_when_gap_queries_under_cap():
    assert should_research(_gap_judge(), rounds_done=0, max_rounds=1) is True


def test_should_research_false_no_gap():
    assert should_research(_gap_judge(gap=False), rounds_done=0, max_rounds=1) is False


def test_should_research_false_empty_queries():
    assert should_research(_gap_judge(queries=()), rounds_done=0, max_rounds=1) is False


def test_should_research_false_at_cap():
    assert should_research(_gap_judge(), rounds_done=1, max_rounds=1) is False


def test_should_research_false_over_cap():
    assert should_research(_gap_judge(), rounds_done=2, max_rounds=1) is False


def test_should_research_false_when_judge_none():
    assert should_research(None, rounds_done=0, max_rounds=1) is False


# ── shared runner helpers ─────────────────────────────────────────────────────


def _panel_runner(p_by_model):
    def runner(model, system, user):
        assert model in p_by_model, f"unexpected model {model}"
        p = p_by_model[model]
        return json.dumps(
            {
                "probability": p,
                "rationale": f"{model} says {p}",
                "reasons_up": ["a"],
                "reasons_down": ["b"],
                "change_my_mind": ["c"],
                "crux": "x",
            }
        )

    return runner


def _scripted_judge_runner(scripts):
    """A judge runner that returns one scripted JSON per call, in order. The last
    script repeats once exhausted so an extra (post-research) judge pass is fine."""

    calls = {"n": 0}

    def runner(model, system, user):
        i = min(calls["n"], len(scripts) - 1)
        calls["n"] += 1
        return json.dumps(scripts[i])

    runner.calls = calls  # type: ignore[attr-defined]
    return runner


def _ledger(tmp_path):
    return ForecastLedger(db_path=str(tmp_path / "q.db"))


def _question(lg):
    return lg.create_question(
        title="Will the challenger flip the Ohio Senate seat in 2026?",
        resolution_criteria="Resolves YES if the challenger wins per the certified result.",
        domain="politics",
        outcome_space=OutcomeSpace(type="binary"),
    )


# ── 3. run_quorum: a gap-flagging judge drives exactly one research round ──────


def test_research_round_runs_once_and_records_evidence():
    p_by_model = {"m1": 0.6, "m2": 0.5}
    # First judge flags a gap; the second (post-research) judge resolves it.
    judge_runner = _scripted_judge_runner(
        [
            {
                "probability": 0.6,
                "directional_confidence": "medium",
                "information_gap": True,
                "clarifying_queries": ["latest poll?", "turnout model?"],
            },
            {
                "probability": 0.62,
                "directional_confidence": "medium",
                "information_gap": False,
                "clarifying_queries": [],
            },
        ]
    )
    seen_queries: list[list[str]] = []

    def search_runner(queries):
        seen_queries.append(list(queries))
        return [
            {"title": "Fresh poll", "summary": "challenger +4", "source": "pollster"},
        ]

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=list(p_by_model),
        runner=_panel_runner(p_by_model),
        judge_model="judge/model",
        judge_runner=judge_runner,
        trim=0,
        max_concurrency=1,
        search_runner=search_runner,
        max_research_rounds=1,
    )

    assert res.research_rounds == 1
    assert seen_queries == [["latest poll?", "turnout model?"]]
    assert res.supervisor_evidence == [
        {"title": "Fresh poll", "summary": "challenger +4", "source": "pollster"}
    ]
    # Re-synthesised: the second judge ran (gap cleared), and the committed
    # number flows through the final pass.
    assert res.judge is not None and res.judge.information_gap is False
    assert res.final_source == "pool"


def test_research_loop_never_exceeds_max_rounds():
    p_by_model = {"m1": 0.6, "m2": 0.5}
    # EVERY judge pass keeps flagging a gap — only the cap can stop the loop.
    judge_runner = _scripted_judge_runner(
        [
            {
                "probability": 0.6,
                "information_gap": True,
                "clarifying_queries": ["still unsure?"],
            }
        ]
    )
    search_calls = {"n": 0}

    def search_runner(queries):
        search_calls["n"] += 1
        return [{"title": f"item {search_calls['n']}"}]

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=list(p_by_model),
        runner=_panel_runner(p_by_model),
        judge_model="judge/model",
        judge_runner=judge_runner,
        trim=0,
        max_concurrency=1,
        search_runner=search_runner,
        max_research_rounds=2,
    )
    assert res.research_rounds == 2
    assert search_calls["n"] == 2
    assert len(res.supervisor_evidence) == 2


# ── 4. HARD CONSTRAINT: no search_runner ⇒ byte-identical to baseline ──────────


def _baseline(p_by_model, judge_script, *, alpha=1.0, search_runner=None,
              max_research_rounds=1):
    return run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=list(p_by_model),
        runner=_panel_runner(p_by_model),
        judge_model="judge/model",
        judge_runner=_scripted_judge_runner([judge_script]),
        trim=0,
        alpha_extremize=alpha,
        max_concurrency=1,
        search_runner=search_runner,
        max_research_rounds=max_research_rounds,
    )


def test_no_search_runner_is_byte_identical_to_baseline():
    p_by_model = {"m1": 0.62, "m2": 0.48}
    judge_script = {
        "probability": 0.9,
        "directional_confidence": "medium",
        # Even though the judge flags a gap, with NO search_runner the loop must
        # never run — proving the default path is untouched.
        "information_gap": True,
        "clarifying_queries": ["should be ignored"],
    }
    res = _baseline(p_by_model, judge_script, alpha=1.0, search_runner=None)

    # research did NOT run
    assert res.research_rounds == 0
    assert res.supervisor_evidence == []

    # committed number is the bare geomean-of-odds pool, byte-for-byte
    odds = [prob_to_odds(p) for p in p_by_model.values()]
    geo = (odds[0] * odds[1]) ** 0.5
    expected_pool = geo / (1.0 + geo)
    assert res.committed_probability == res.aggregate_probability
    assert res.committed_probability == pytest.approx(expected_pool, abs=1e-12)
    assert res.final_source == "pool"
    # applied alpha marker: identity leaves pre_extremize unset
    assert res.aggregation.pre_extremize_probability is None


def test_supplying_search_runner_but_no_gap_is_also_baseline():
    p_by_model = {"m1": 0.62, "m2": 0.48}
    judge_script = {
        "probability": 0.7,
        "directional_confidence": "medium",
        "information_gap": False,  # no gap -> no research even with a runner
        "clarifying_queries": [],
    }

    def search_runner(queries):  # pragma: no cover - must never be called
        raise AssertionError("search_runner must not run without a flagged gap")

    res = _baseline(p_by_model, judge_script, search_runner=search_runner)
    assert res.research_rounds == 0
    assert res.supervisor_evidence == []
    assert res.committed_probability == pytest.approx(res.aggregate_probability)


# ── 5. terminal Platt applied EXACTLY ONCE even with a research round ──────────


def test_platt_applied_once_with_research_round():
    p_by_model = {"m1": 0.6, "m2": 0.5}
    # First judge flags a gap; after research it overrides at HIGH confidence so
    # the judge branch wins and gets Platt'd once.
    judge_runner = _scripted_judge_runner(
        [
            {
                "probability": 0.6,
                "directional_confidence": "medium",
                "information_gap": True,
                "clarifying_queries": ["decisive evidence?"],
            },
            {
                "probability": 0.85,
                "directional_confidence": "high",
                "information_gap": False,
                "clarifying_queries": [],
            },
        ]
    )

    def search_runner(queries):
        return [{"title": "decisive", "summary": "settles it"}]

    res = run_quorum(
        question_title="Q",
        resolution_criteria="R",
        models=list(p_by_model),
        runner=_panel_runner(p_by_model),
        judge_model="judge/model",
        judge_runner=judge_runner,
        trim=0,
        alpha_extremize=1.5,
        max_concurrency=1,
        search_runner=search_runner,
        max_research_rounds=1,
    )
    assert res.research_rounds == 1
    assert res.final_source == "judge_high"
    once = platt_scale(0.85, alpha=1.5, d=1.0)
    assert res.committed_probability == pytest.approx(once, abs=1e-12)
    # not raw, not double
    assert res.committed_probability != pytest.approx(0.85, abs=1e-6)
    twice = platt_scale(once, alpha=1.5, d=1.0)
    assert res.committed_probability != pytest.approx(twice, abs=1e-9)


# ── 6. ledger persistence: additive, default-unchanged ────────────────────────


def _estimates():
    return [
        {"perspective": "base_rate", "probability": 0.58, "agent_model": "m1"},
        {"perspective": "insider", "probability": 0.52, "agent_model": "m2"},
    ]


def test_record_panel_run_persists_supervisor_fields(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    evidence = [{"title": "fresh", "summary": "s", "source": "src"}]
    pr = lg.record_panel_run(
        question_id=q.id,
        estimates=_estimates(),
        triggered_by="quorum",
        research_rounds=1,
        supervisor_evidence=evidence,
    )
    got = lg.get_panel_run(pr["id"])
    assert got["research_rounds"] == 1
    assert got["supervisor_evidence"] == evidence


def test_record_panel_run_defaults_are_unchanged(tmp_path):
    lg = _ledger(tmp_path)
    q = _question(lg)
    pr = lg.record_panel_run(question_id=q.id, estimates=_estimates())
    got = lg.get_panel_run(pr["id"])
    assert got["research_rounds"] == 0
    assert got["supervisor_evidence"] == []
