"""AIA P1.2 — content-aware foreknowledge judge + leakage robustness bounds.

Everything load-bearing here is PURE (prompt builder, parser, prevalence
back-out, rescore arithmetic). The single backtest test confirms the judge
channel defaults OFF so existing backtests are byte-identical.
"""

from __future__ import annotations

import pytest

from forecasting.ledger import (
    BRIER_COIN_FLIP_FLOOR,
    LEAK_ROBUSTNESS_REL_TOLERANCE,
    WORST_CASE_FLAG_THRESHOLD,
    ForecastLedger,
)
from forecasting.leak_judge import (
    FOUR_TELLS,
    NOT_LEAKAGE_GUARDRAIL,
    build_leak_judge_prompt,
    parse_leak_verdict,
)
from forecasting.leak_prevalence import (
    LEAK_JUDGE_CALIBRATION,
    estimate_true_leak_rate,
)


# --------------------------------------------------------------------------- #
# parse_leak_verdict — well-formed / missing-keys / garbage -> safe default
# --------------------------------------------------------------------------- #


def test_parse_leak_verdict_well_formed():
    raw = (
        '{"has_foreknowledge": true, "confidence_level": "high", '
        '"evidence_quotes": ["the incumbent lost"], '
        '"key_indicators": ["explicit outcome reference"], '
        '"overall_assessment": "states the resolved outcome as fact"}'
    )
    verdict = parse_leak_verdict(raw)
    assert verdict["has_foreknowledge"] is True
    assert verdict["confidence_level"] == "high"
    assert verdict["evidence_quotes"] == ["the incumbent lost"]
    assert verdict["key_indicators"] == ["explicit outcome reference"]
    assert verdict["overall_assessment"] == "states the resolved outcome as fact"


def test_parse_leak_verdict_well_formed_negative_in_code_fence():
    raw = '```json\n{"has_foreknowledge": false, "confidence_level": "medium"}\n```'
    verdict = parse_leak_verdict(raw)
    assert verdict["has_foreknowledge"] is False
    assert verdict["confidence_level"] == "medium"
    assert verdict["evidence_quotes"] == []
    assert verdict["key_indicators"] == []


def test_parse_leak_verdict_missing_keys_safe_defaults():
    # Only has_foreknowledge present; everything else must fall to safe defaults.
    verdict = parse_leak_verdict('{"has_foreknowledge": true}')
    assert verdict["has_foreknowledge"] is True
    assert verdict["confidence_level"] == "low"  # missing -> low
    assert verdict["evidence_quotes"] == []
    assert verdict["key_indicators"] == []
    assert verdict["overall_assessment"] == ""


def test_parse_leak_verdict_dict_envelope():
    # An LLM-client style envelope is unwrapped like agent_protocol does.
    raw = {"response": {"has_foreknowledge": True, "confidence_level": "low"}}
    verdict = parse_leak_verdict(raw)
    assert verdict["has_foreknowledge"] is True


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "this is not json at all",
        "{not valid json",
        None,
        12345,
        ["has_foreknowledge", True],
        '{"has_foreknowledge": "definitely yes maybe"}',  # non-bool, non-truthy string
    ],
)
def test_parse_leak_verdict_garbage_fails_closed(raw):
    verdict = parse_leak_verdict(raw)
    # Garbage can NEVER manufacture a leak flag.
    assert verdict["has_foreknowledge"] is False
    assert verdict["confidence_level"] == "low"
    assert verdict["evidence_quotes"] == []
    assert verdict["key_indicators"] == []


# --------------------------------------------------------------------------- #
# build_leak_judge_prompt — cutoff + four tells + not-leakage guardrail
# --------------------------------------------------------------------------- #


def test_build_leak_judge_prompt_contains_cutoff_tells_guardrail():
    prompt = build_leak_judge_prompt(
        question="Will candidate A win the 2024 election?",
        cutoff="2024-10-01T00:00:00Z",
        resolution="yes",
        model_output="Rationale: base rate of incumbency is ~60%.",
    )
    # cutoff date is present
    assert "2024-10-01T00:00:00Z" in prompt
    # the question is present
    assert "Will candidate A win the 2024 election?" in prompt
    # all four tells appear verbatim
    for tell in FOUR_TELLS:
        assert tell in prompt
    assert len(FOUR_TELLS) == 4
    # the not-leakage guardrail appears verbatim
    assert NOT_LEAKAGE_GUARDRAIL in prompt
    assert "base rates" in NOT_LEAKAGE_GUARDRAIL  # guardrail names good forecasting
    # the model output is embedded for the judge to read
    assert "base rate of incumbency" in prompt


def test_build_leak_judge_prompt_handles_missing_cutoff_and_resolution():
    prompt = build_leak_judge_prompt(
        question="Q?",
        cutoff=None,
        resolution=None,
        model_output=None,
    )
    assert "unknown" in prompt  # cutoff fallback
    assert "not provided" in prompt  # resolution fallback
    for tell in FOUR_TELLS:
        assert tell in prompt


# --------------------------------------------------------------------------- #
# estimate_true_leak_rate — reproduce ~1.65% from the paper's working numbers
# --------------------------------------------------------------------------- #


def test_estimate_true_leak_rate_reproduces_paper_value():
    result = estimate_true_leak_rate(N=4411, flags=236, precision=0.198, recall=0.64)
    # ~1.65% true rate (abs tol 0.3 percentage points), well below the raw 5.4%
    # flag rate.
    assert result["true_rate"] * 100 == pytest.approx(1.65, abs=0.3)
    assert result["flag_rate"] * 100 == pytest.approx(5.35, abs=0.2)
    # the true rate is much lower than the raw flag rate (precision/recall back-out)
    assert result["true_rate"] < result["flag_rate"]
    # component identities hold: TP = precision*flags, FN = TP/recall - TP
    assert result["true_positives"] == pytest.approx(0.198 * 236)
    tp = 0.198 * 236
    assert result["false_negatives"] == pytest.approx(tp / 0.64 - tp)
    assert result["true_leaks"] == pytest.approx(result["true_positives"] + result["false_negatives"])


def test_estimate_true_leak_rate_defaults_to_calibration_block():
    result = estimate_true_leak_rate(N=4411, flags=236)
    assert result["precision"] == LEAK_JUDGE_CALIBRATION["precision"]
    assert result["recall"] == LEAK_JUDGE_CALIBRATION["recall"]
    # The calibration block is clearly labelled UNCALIBRATED.
    assert LEAK_JUDGE_CALIBRATION["calibrated"] is False
    assert "UNCALIBRATED" in LEAK_JUDGE_CALIBRATION["version"]
    assert result["calibrated"] is False


@pytest.mark.parametrize(
    "N,flags,recall",
    [
        (0, 5, 0.64),  # no cases -> no denominator
        (100, 0, 0.64),  # no flags -> no true leaks
        (100, 5, 0.0),  # unusable recall -> fail safe
    ],
)
def test_estimate_true_leak_rate_edge_cases(N, flags, recall):
    result = estimate_true_leak_rate(N=N, flags=flags, precision=0.2, recall=recall)
    assert result["true_rate"] == 0.0


# --------------------------------------------------------------------------- #
# rescore_backtest_run — baseline / filtered / worst_case math on a fixture
# --------------------------------------------------------------------------- #


def _seed_run(ledger: ForecastLedger, *, judge_runner=None) -> str:
    """Seed a 4-case backtest. Two distinct questions: q1 (3 cases) and q2 (1).

    Probabilities/outcomes are chosen so each case has a clean, known Brier:
      - p=0.9 outcome yes -> Brier (1-0.9)^2 = 0.01
      - p=0.8 outcome yes -> Brier 0.04
      - p=0.2 outcome yes -> Brier 0.64
      - p=0.5 outcome yes -> Brier 0.25
    """

    cases = [
        {
            "id": "q1",  # shared external id -> q1-a/b/c are ONE logical question
            "title": "Q1 first cutoff",
            "resolution_criteria": "Resolved yes if the audited condition is confirmed by the cited source.",
            "as_of": "2024-01-01T00:00:00Z",
            "probability": 0.9,
            "outcome": "yes",
            "evidence": [{"claim": "leaky: the answer was yes", "available_at": "2023-12-01T00:00:00Z"}],
        },
        {
            "id": "q1",  # same logical question, second rolling cutoff
            "title": "Q1 second cutoff",
            "resolution_criteria": "Resolved yes if the audited condition is confirmed by the cited source.",
            "as_of": "2024-02-01T00:00:00Z",
            "probability": 0.8,
            "outcome": "yes",
            "evidence": [{"claim": "leaky: outcome known", "available_at": "2024-01-15T00:00:00Z"}],
        },
        {
            "id": "q1",  # same logical question, third rolling cutoff
            "title": "Q1 third cutoff",
            "resolution_criteria": "Resolved yes if the audited condition is confirmed by the cited source.",
            "as_of": "2024-03-01T00:00:00Z",
            "probability": 0.2,
            "outcome": "yes",
            "evidence": [{"claim": "clean prior reasoning", "available_at": "2024-02-15T00:00:00Z"}],
        },
        {
            "id": "q2",  # distinct logical question, single cutoff
            "title": "Q2 only cutoff",
            "resolution_criteria": "Resolved yes if the audited condition is confirmed by the cited source.",
            "as_of": "2024-01-01T00:00:00Z",
            "probability": 0.5,
            "outcome": "yes",
            "evidence": [{"claim": "clean base rate", "available_at": "2023-12-01T00:00:00Z"}],
        },
    ]
    run = ledger.run_backtest_dataset(
        dataset="leak-fixture",
        cases=cases,
        leak_judge_runner=judge_runner,
    )
    return run["id"]


def _flag_title_substrings(*needles):
    """A judge runner that flags any case whose prompt contains one of *needles*."""

    def runner(prompt, case):
        title = str(case.get("title") or "")
        if any(n in title for n in needles):
            return '{"has_foreknowledge": true, "confidence_level": "high"}'
        return '{"has_foreknowledge": false, "confidence_level": "low"}'

    return runner


def test_rescore_baseline_filtered_worst_case_math(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    # Flag the two Q1 cases q1-a and q1-b (Q1 gets >= WORST_CASE_FLAG_THRESHOLD=2
    # flags); q1-c and q2-a stay clean.
    run_id = _seed_run(ledger, judge_runner=_flag_title_substrings("first cutoff", "second cutoff"))

    # Confirm the flags landed where we expect.
    cases = {c["id"]: c for c in ledger.list_backtest_cases(run_id)}
    # cases are keyed by generated btc id, so look up by question title via flags
    flag_total = sum(int(c["content_flag_count"]) for c in cases.values())
    assert flag_total == 2

    baseline_briers = [0.01, 0.04, 0.64, 0.25]
    baseline_mean = sum(baseline_briers) / 4

    rescore = ledger.rescore_backtest_run(run_id, "baseline")
    assert rescore["baseline"]["count"] == 4
    assert rescore["baseline"]["mean_brier"] == pytest.approx(baseline_mean)
    assert rescore["abs_delta"] == pytest.approx(0.0)
    assert rescore["rel_delta"] == pytest.approx(0.0)

    # filtered: drop the 2 flagged cases (0.01 and 0.04) -> [0.64, 0.25]
    filtered = ledger.rescore_backtest_run(run_id, "filtered")
    assert filtered["filtered"]["count"] == 2
    filtered_mean = (0.64 + 0.25) / 2
    assert filtered["filtered"]["mean_brier"] == pytest.approx(filtered_mean)
    assert filtered["abs_delta"] == pytest.approx(filtered_mean - baseline_mean)
    assert filtered["rel_delta"] == pytest.approx((filtered_mean - baseline_mean) / baseline_mean)

    # worst_case: Q1 has 2 flags >= threshold, so each Q1 case Brier is raised to
    # AT LEAST 0.25 — but the already-worse 0.64 case is NOT improved (worst_case is
    # an UPPER bound, never lowers a score). q2-a (0 flags) keeps its 0.25.
    # -> [max(.01,.25), max(.04,.25), max(.64,.25), .25] = [.25, .25, .64, .25]
    worst = ledger.rescore_backtest_run(run_id, "worst_case")
    assert worst["worst_case_question_count"] == 1
    assert worst["worst_case"]["count"] == 4
    worst_mean = (0.25 + 0.25 + 0.64 + 0.25) / 4
    assert worst["worst_case"]["mean_brier"] == pytest.approx(worst_mean)
    assert worst["abs_delta"] == pytest.approx(worst_mean - baseline_mean)
    # a genuine upper bound: worst_case can never read better than baseline.
    assert worst["worst_case"]["mean_brier"] >= rescore["baseline"]["mean_brier"]


def test_rescore_does_not_mutate_calibration_state(tmp_path):
    # A robustness what-if must be a PURE recompute that writes NOTHING — the old
    # impl called _disable_backtest_calibration, corrupting the run's calibration
    # eligibility just by being invoked (and during a normal judge-on backtest).
    ledger = ForecastLedger(tmp_path / "f.db")
    run_id = _seed_run(ledger)
    # Force calibration ON so any stray write would be visible.
    with ledger._connect() as conn:
        conn.execute("UPDATE score_records SET calibration_eligible = 1, calibration_weight = 1.0")
        conn.execute("UPDATE forecast_snapshots SET calibration_eligible = 1")

    def _cal_state():
        with ledger._connect() as conn:
            s = conn.execute(
                "SELECT calibration_eligible, calibration_weight FROM score_records ORDER BY rowid"
            ).fetchall()
            f = conn.execute(
                "SELECT calibration_eligible FROM forecast_snapshots ORDER BY rowid"
            ).fetchall()
        return [tuple(r) for r in s], [tuple(r) for r in f]

    before = _cal_state()
    for mode in ("baseline", "filtered", "worst_case"):
        ledger.rescore_backtest_run(run_id, mode)
    assert _cal_state() == before  # the recompute wrote nothing


def test_rescore_single_flag_does_not_trip_worst_case(tmp_path):
    # Only one Q1 case flagged -> below WORST_CASE_FLAG_THRESHOLD -> no question
    # forced to 0.25 in worst_case.
    assert WORST_CASE_FLAG_THRESHOLD == 2
    ledger = ForecastLedger(tmp_path / "f.db")
    run_id = _seed_run(ledger, judge_runner=_flag_title_substrings("first cutoff"))

    worst = ledger.rescore_backtest_run(run_id, "worst_case")
    assert worst["worst_case_question_count"] == 0
    # worst_case mean == baseline mean (nothing forced)
    assert worst["worst_case"]["mean_brier"] == pytest.approx(worst["baseline"]["mean_brier"])
    # but filtered still drops the single flagged case
    filtered = ledger.rescore_backtest_run(run_id, "filtered")
    assert filtered["filtered"]["count"] == 3


def test_rescore_rejects_unknown_mode(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    run_id = _seed_run(ledger)
    with pytest.raises(Exception):
        ledger.rescore_backtest_run(run_id, "bogus")


def test_leak_judge_summary_and_robustness_verdict(tmp_path):
    ledger = ForecastLedger(tmp_path / "f.db")
    run_id = _seed_run(ledger, judge_runner=_flag_title_substrings("first cutoff", "second cutoff"))
    run = ledger.get_backtest_run(run_id)
    leak = run["result_summary"]["leak_judge"]
    assert leak["channel"] == "content_aware_judge"
    assert leak["content_flagged_cases"] == 2
    # true-leak-rate back-out is present and uses the calibration block.
    assert leak["true_leak_rate"]["flags"] == 2
    assert leak["calibration"]["calibrated"] is False
    # worst_case mean (0.25) vs baseline (0.235) -> rel rise ~6.4% > 0.6% tol -> material.
    assert leak["rel_tolerance"] == LEAK_ROBUSTNESS_REL_TOLERANCE
    assert leak["leakage_material"] is True
    assert leak["leakage_non_material"] is False


# --------------------------------------------------------------------------- #
# Channel OFF -> backtest byte-identical to before (no judge, no new fields)
# --------------------------------------------------------------------------- #


def test_judge_channel_off_is_byte_identical(tmp_path):
    # Two runs with the SAME cases: one with the channel explicitly OFF (default),
    # one passing leak_judge_runner=None. Both must (a) omit the leak_judge block,
    # (b) leave every case unflagged with the default verdict, and (c) keep the
    # leakage status at the pre-P1.2 'passed'.
    def build(db_name):
        ledger = ForecastLedger(tmp_path / db_name)
        run_id = _seed_run(ledger)  # no judge runner -> channel OFF
        run = ledger.get_backtest_run(run_id)
        cases = ledger.list_backtest_cases(run_id)
        return ledger, run, cases

    ledger_a, run_a, cases_a = build("a.db")
    _, run_b, cases_b = build("b.db")

    # No leak_judge block is added when the channel is OFF.
    assert "leak_judge" not in run_a["result_summary"]
    assert "leak_judge" not in run_b["result_summary"]

    # Every case is unflagged with the empty default verdict, status still 'passed'.
    for case in cases_a:
        assert case["content_flag_count"] == 0
        assert case["leakage_verdicts"] == {}
        assert case["leakage_check_status"] == "passed"

    # The result summary (minus the non-deterministic nothing — these are pure)
    # matches between the two channel-OFF runs.
    def normalize(summary):
        return {k: v for k, v in summary.items()}

    assert normalize(run_a["result_summary"]) == normalize(run_b["result_summary"])

    # And a manual judge call would have been required to flag anything: with the
    # channel off the stored verdict is the safe default even though q1-a/q1-b
    # contain blatantly "leaky" evidence text.
    leaky_cases = [c for c in cases_a if c["content_flag_count"] > 0]
    assert leaky_cases == []
