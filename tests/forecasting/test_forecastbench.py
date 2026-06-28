"""ForecastBench ingestion adapter tests.

The network boundary is ``forecastbench._fetch_json``; every test monkeypatches
it with a canned (question set, resolution set) pair so nothing here touches the
network. We assert the join, the field mapping (as_of==freeze,
outcome==resolved_to, baseline==freeze_value), the drop rules (combination /
unresolved / non-market-source / fractional), limit, the binary_only/
resolved_only toggles, the honest dropped counts, the CLOSED-BOOK seal (no live
URL reaches the agent-visible sanitized case or evidence), a real end-to-end run
of a PRODUCED case through ``ForecastLedger.run_backtest_dataset``, and an
additive-only guard that no existing default (builtin benchmark case shape,
agent-protocol toolsets) changed.
"""

from __future__ import annotations

import pytest

from forecasting import forecastbench
from forecasting.forecastbench import (
    MARKET_SOURCES,
    ForecastBenchError,
    build_forecastbench_case,
    forecastbench_dataset_label,
    load_forecastbench_cases,
)
from forecasting.models import EVIDENCE_CLAIM_TYPES


QUESTION_SET_DATE = "2099-01-01"


def _question_payload() -> dict:
    return {
        "forecast_due_date": QUESTION_SET_DATE,
        "question_set": f"{QUESTION_SET_DATE}-llm.json",
        "questions": [
            # 0: clean binary manifold question (should be produced)
            {
                "id": "mf-1",
                "source": "manifold",
                "question": "Will event A happen by close?",
                "resolution_criteria": "Resolves YES if A occurs.",
                "background": "Some background about A.",
                "url": "https://manifold.markets/q/a",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "0.62",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
                "resolution_dates": ["2099-02-15T00:00:00Z"],
            },
            # 1: clean binary metaculus question, resolved NO (produced)
            {
                "id": "mc-2",
                "source": "metaculus",
                "question": "Will event B happen?",
                "resolution_criteria": "Resolves YES if B occurs.",
                "background": "",
                "url": "https://metaculus.com/q/b",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "0.20",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
            },
            # 2: NON-BINARY (fred level -> freeze value far outside [0,1]) -> dropped
            {
                "id": "fred-3",
                "source": "fred",
                "question": "What will CPI be?",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "317.5",
            },
            # 3: UNRESOLVED (resolution row resolved=false) -> dropped
            {
                "id": "mf-4",
                "source": "manifold",
                "question": "Will event D happen?",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "0.40",
            },
            # 4: COMBINATION — its resolution row has a non-null direction; the
            # question has no matching SINGLE resolution -> dropped as unresolved
            {
                "id": "mf-5",
                "source": "manifold",
                "question": "Will combo E happen?",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "0.55",
            },
            # 5: market source (metaculus) but FRACTIONAL resolution (0.49) ->
            # dropped_fractional (must NOT be coerced to a yes/no via >=0.5).
            {
                "id": "mc-6",
                "source": "metaculus",
                "question": "How much of X by close?",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "0.49",
                "market_info_close_datetime": "2099-03-01T00:00:00Z",
            },
            # 6: DATASET source (acled) with an "N/A" close datetime and an
            # unsubstituted {resolution_date} placeholder title; resolved_to is a
            # clean 1.0 but the source is not a market -> dropped_non_binary. Its
            # "N/A" close time would crash create_question if it ever survived.
            {
                "id": "acled-7",
                "source": "acled",
                "question": "Will there be >= N events by {resolution_date}?",
                "freeze_datetime": "2099-01-01T00:00:00Z",
                "freeze_datetime_value": "42",
                "market_info_close_datetime": "N/A",
            },
        ],
    }


def _resolution_payload() -> dict:
    return {
        "forecast_due_date": QUESTION_SET_DATE,
        "question_set": f"{QUESTION_SET_DATE}-llm.json",
        "resolutions": [
            # SINGLE, resolved YES
            {
                "id": "mf-1",
                "source": "manifold",
                "direction": None,
                "resolution_date": "2099-02-15T00:00:00Z",
                "resolved_to": 1.0,
                "resolved": True,
            },
            # SINGLE, resolved NO
            {
                "id": "mc-2",
                "source": "metaculus",
                "direction": None,
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 0.0,
                "resolved": True,
            },
            # SINGLE, resolved YES (matches non-binary fred-3)
            {
                "id": "fred-3",
                "source": "fred",
                "direction": None,
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 1.0,
                "resolved": True,
            },
            # SINGLE but resolved=false (matches mf-4) -> unresolved drop when
            # resolved_only; carries a resolved_to so the resolved_only=False
            # toggle can still map a scorable outcome.
            {
                "id": "mf-4",
                "source": "manifold",
                "direction": None,
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 0.0,
                "resolved": False,
            },
            # COMBINATION — non-null direction (matches mf-5 id but is a
            # conditional pair) -> counted as dropped_combination, never joined
            {
                "id": "mf-5",
                "source": "manifold",
                "direction": [1, 0],
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 1.0,
                "resolved": True,
            },
            # SINGLE metaculus, FRACTIONAL resolved_to 0.49 (matches mc-6) ->
            # dropped_fractional
            {
                "id": "mc-6",
                "source": "metaculus",
                "direction": None,
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 0.49,
                "resolved": True,
            },
            # SINGLE acled, clean 1.0 but dataset source (matches acled-7) ->
            # dropped_non_binary on the source gate
            {
                "id": "acled-7",
                "source": "acled",
                "direction": None,
                "resolution_date": "2099-02-20T00:00:00Z",
                "resolved_to": 1.0,
                "resolved": True,
            },
        ],
    }


@pytest.fixture
def patched_fetch(monkeypatch):
    """Monkeypatch the network boundary with the canned payload pair."""

    q = _question_payload()
    r = _resolution_payload()

    def fake_fetch(url: str):
        if "question_sets" in url:
            return q
        if "resolution_sets" in url:
            return r
        raise AssertionError(f"unexpected fetch url: {url}")

    monkeypatch.setattr(forecastbench, "_fetch_json", fake_fetch)
    return fake_fetch


# --------------------------------------------------------------------------- #
# field mapping
# --------------------------------------------------------------------------- #
def test_field_mapping_as_of_outcome_baseline(patched_fetch, tmp_path):
    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    cases = {c["id"]: c for c in report["cases"]}

    yes_case = cases[f"forecastbench-{QUESTION_SET_DATE}-manifold-mf-1"]
    # as_of == evidence_cutoff == simulated_forecast_time == freeze_datetime
    assert yes_case["as_of"] == "2099-01-01T00:00:00Z"
    assert yes_case["evidence_cutoff"] == "2099-01-01T00:00:00Z"
    assert yes_case["simulated_forecast_time"] == "2099-01-01T00:00:00Z"
    # outcome mapped from resolved_to 1.0 -> yes
    assert yes_case["outcome"] == "yes"
    # resolution_time == resolution_date
    assert yes_case["resolution_time"] == "2099-02-15T00:00:00Z"
    assert yes_case["title"] == "Will event A happen by close?"
    # freeze market value -> market baseline
    market = [b for b in yes_case["baselines"] if b["baseline_type"] == "market"]
    assert market and market[0]["probability"] == pytest.approx(0.62)
    # naive baseline is also present
    assert any(b["baseline_type"] == "naive_0_5" for b in yes_case["baselines"])
    # source + url carried in metadata
    assert yes_case["metadata"]["forecastbench_source"] == "manifold"
    assert yes_case["metadata"]["forecastbench_url"] == "https://manifold.markets/q/a"

    no_case = cases[f"forecastbench-{QUESTION_SET_DATE}-metaculus-mc-2"]
    assert no_case["outcome"] == "no"  # resolved_to 0.0 -> no
    market = [b for b in no_case["baselines"] if b["baseline_type"] == "market"]
    assert market[0]["probability"] == pytest.approx(0.20)


# --------------------------------------------------------------------------- #
# drop rules + honest counts
# --------------------------------------------------------------------------- #
def test_drops_and_counts(patched_fetch, tmp_path):
    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    counts = report["counts"]

    # only the two clean binary resolved MARKET singles survive
    produced_ids = {c["id"] for c in report["cases"]}
    assert produced_ids == {
        f"forecastbench-{QUESTION_SET_DATE}-manifold-mf-1",
        f"forecastbench-{QUESTION_SET_DATE}-metaculus-mc-2",
    }
    assert counts["produced"] == 2
    # the combination resolution row (direction != null) is dropped + counted
    assert counts["dropped_combination"] == 1
    # fred-3 + acled-7 are DATASET sources -> dropped on the market-source gate
    assert counts["dropped_non_binary"] == 2
    # mc-6 is a market source but FRACTIONAL (0.49) -> dropped_fractional, NOT
    # coerced to a yes/no via >=0.5
    assert counts["dropped_fractional"] == 1
    # mf-4 (resolved=false) and mf-5 (no single resolution) -> unresolved
    assert counts["dropped_unresolved"] == 2
    assert counts["dropped_no_outcome"] == 0
    assert counts["questions"] == 7
    assert counts["resolutions"] == 7
    assert report["resolution_set_date"] == QUESTION_SET_DATE
    assert report["dataset"] == forecastbench_dataset_label(QUESTION_SET_DATE)
    # per-source produced counts surfaced for the proof
    assert report["produced_by_source"] == {"manifold": 1, "metaculus": 1}
    # every produced case is from a market source
    assert all(c["metadata"]["forecastbench_source"] in MARKET_SOURCES for c in report["cases"])


# --------------------------------------------------------------------------- #
# id-join correctness
# --------------------------------------------------------------------------- #
def test_id_join_pairs_correct_outcome(patched_fetch, tmp_path):
    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    by_id = {c["metadata"]["forecastbench_id"]: c for c in report["cases"]}
    # mf-1 resolved YES, mc-2 resolved NO — join must not cross them
    assert by_id["mf-1"]["outcome"] == "yes"
    assert by_id["mc-2"]["outcome"] == "no"


# --------------------------------------------------------------------------- #
# limit
# --------------------------------------------------------------------------- #
def test_limit_caps_produced(patched_fetch, tmp_path):
    report = load_forecastbench_cases(QUESTION_SET_DATE, limit=1, cache_dir=tmp_path)
    assert report["counts"]["produced"] == 1
    assert len(report["cases"]) == 1
    assert report["counts"]["dropped_limit"] == 1


# --------------------------------------------------------------------------- #
# binary_only / resolved_only toggles
# --------------------------------------------------------------------------- #
def test_binary_only_false_still_drops_dataset_sources(patched_fetch, tmp_path):
    # binary_only=False relaxes ONLY the freeze-probability requirement; the
    # MARKET-SOURCE restriction always holds, because a dataset-source freeze
    # value is a raw level (not a probability) and its resolved_to is unreliable.
    report = load_forecastbench_cases(
        QUESTION_SET_DATE, binary_only=False, cache_dir=tmp_path
    )
    produced_ids = {c["metadata"]["forecastbench_id"] for c in report["cases"]}
    # fred-3 / acled-7 are dataset sources -> STILL dropped (no longer garbage)
    assert "fred-3" not in produced_ids
    assert "acled-7" not in produced_ids
    # the two clean market binaries still survive; the fractional metaculus
    # (mc-6) is still dropped even with binary_only off
    assert produced_ids == {"mf-1", "mc-2"}
    assert report["counts"]["dropped_non_binary"] == 2  # fred-3 + acled-7 on the source gate
    assert report["counts"]["dropped_fractional"] == 1  # mc-6


def test_resolved_only_false_still_requires_a_single_resolution(patched_fetch, tmp_path):
    # resolved_only=False relaxes the resolved flag, but mf-4's row is present
    # (resolved=false) so it can now produce; mf-5 has no SINGLE resolution and
    # stays dropped.
    report = load_forecastbench_cases(
        QUESTION_SET_DATE, resolved_only=False, cache_dir=tmp_path
    )
    produced_ids = {c["metadata"]["forecastbench_id"] for c in report["cases"]}
    assert "mf-4" in produced_ids  # resolved_to None -> mapped no, now produced
    assert "mf-5" not in produced_ids  # combination, no single resolution


# --------------------------------------------------------------------------- #
# cache: second call must NOT re-fetch
# --------------------------------------------------------------------------- #
def test_cache_avoids_refetch(monkeypatch, tmp_path):
    calls = {"n": 0}
    q, r = _question_payload(), _resolution_payload()

    def counting_fetch(url: str):
        calls["n"] += 1
        return q if "question_sets" in url else r

    monkeypatch.setattr(forecastbench, "_fetch_json", counting_fetch)

    load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    first = calls["n"]
    assert first == 2  # one question set + one resolution set

    load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    assert calls["n"] == first  # served entirely from the on-disk cache


# --------------------------------------------------------------------------- #
# error surface
# --------------------------------------------------------------------------- #
def test_malformed_payload_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(forecastbench, "_fetch_json", lambda url: {"nope": True})
    with pytest.raises(ForecastBenchError):
        load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)


# --------------------------------------------------------------------------- #
# build_forecastbench_case is a pure mapping helper
# --------------------------------------------------------------------------- #
def test_build_case_pure_mapping():
    q = _question_payload()["questions"][0]
    r = _resolution_payload()["resolutions"][0]
    case = build_forecastbench_case(q, r, question_set_date=QUESTION_SET_DATE)
    assert case["outcome"] == "yes"
    assert case["as_of"] == case["evidence_cutoff"] == "2099-01-01T00:00:00Z"
    assert case["close_time"] == "2099-03-01T00:00:00Z"
    # exactly one pre-cutoff context evidence row, pinned at the freeze
    assert len(case["evidence"]) == 1
    row = case["evidence"][0]
    assert row["available_at"] == "2099-01-01T00:00:00Z"
    assert row["stance"] == "context"
    # claim_type MUST be a valid EVIDENCE_CLAIM_TYPE (not "context"), else
    # add_evidence raises for every case.
    assert row["claim_type"] in EVIDENCE_CLAIM_TYPES
    assert row["claim_type"] == "fact"


# --------------------------------------------------------------------------- #
# CLOSED-BOOK seal: the live source URL must NOT reach the agent
# --------------------------------------------------------------------------- #
def test_closed_book_seal_url_only_in_metadata(patched_fetch, tmp_path):
    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    case = {c["metadata"]["forecastbench_id"]: c for c in report["cases"]}["mf-1"]

    # the live URL rides ONLY in metadata, never in resolution_source...
    assert case["resolution_source"] is None
    assert case["metadata"]["forecastbench_url"] == "https://manifold.markets/q/a"
    # ...and never in the context-evidence row (no url key; source is not the URL)
    row = case["evidence"][0]
    assert "url" not in row
    assert "manifold.markets" not in row["source"]
    assert "manifold.markets" not in row.get("summary", "")
    assert "manifold.markets" not in row.get("claim", "")


def test_sanitized_agent_case_has_no_url_or_answer_field(patched_fetch, tmp_path):
    # The REAL consumer of agent-visible context is
    # agent_protocol.sanitize_backtest_case_for_agent. Assert it hands the agent
    # no source URL and no answer-side field.
    from forecasting.agent_protocol import (
        _ANSWER_SIDE_FIELDS,
        sanitize_backtest_case_for_agent,
    )

    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    case = {c["metadata"]["forecastbench_id"]: c for c in report["cases"]}["mf-1"]
    public = sanitize_backtest_case_for_agent(case)

    # no answer-side field reaches the agent
    for field in _ANSWER_SIDE_FIELDS:
        assert field not in public
    # resolution_source must be sealed (either absent or never a live URL)
    assert not public.get("resolution_source")
    # the live market slug appears nowhere in the agent-visible blob
    import json as _json

    blob = _json.dumps(public)
    assert "manifold.markets" not in blob
    # the pre-cutoff evidence the agent sees carries no leaking URL
    for ev in public.get("evidence") or []:
        assert "manifold.markets" not in _json.dumps(ev)


def test_resolution_source_is_answer_side_field():
    # Belt-and-braces: even if a non-forecastbench case pins a live URL into
    # resolution_source, the sanitizer must withhold it from the agent.
    from forecasting.agent_protocol import _ANSWER_SIDE_FIELDS

    assert "resolution_source" in _ANSWER_SIDE_FIELDS


# --------------------------------------------------------------------------- #
# THE REAL CONSUMER: a produced case runs end-to-end through run_backtest_dataset
# (this is the coverage gap that let every case crash while unit tests passed).
# --------------------------------------------------------------------------- #
def test_produced_case_runs_through_backtest_dataset(patched_fetch, tmp_path):
    from forecasting.ledger import ForecastLedger

    report = load_forecastbench_cases(QUESTION_SET_DATE, cache_dir=tmp_path)
    cases = report["cases"]
    assert cases, "fixture must produce at least one clean market binary case"

    # Stub probability source (the agent-protocol output would supply this).
    scored_cases = []
    for case in cases:
        c = dict(case)
        c["probability"] = 0.7  # any in-range YES probability
        c["probability_source"] = "stub"
        c["agent_model"] = "test-model"
        scored_cases.append(c)

    ledger = ForecastLedger(db_path=str(tmp_path / "ledger.db"))
    # Must NOT raise — would have caught the "context" claim_type ValidationError
    # (every case) and the "N/A" close_time non-ISO crash.
    run = ledger.run_backtest_dataset(dataset=report["dataset"], cases=scored_cases)
    summary = run["result_summary"]
    assert summary["case_count"] == len(scored_cases)
    # every produced case is scorable (clean binary outcome present)
    assert summary["scored_cases"] == len(scored_cases)


# --------------------------------------------------------------------------- #
# ADDITIVE-ONLY guard: existing defaults unchanged
# --------------------------------------------------------------------------- #
def test_existing_backtest_defaults_unchanged():
    # The builtin benchmark case shape (the template we mirror) is untouched.
    from forecasting.benchmarks import load_builtin_benchmark

    cases = load_builtin_benchmark("builtin:manifold-public-120-binary")
    assert cases, "builtin manifold benchmark must still load"
    sample = cases[0]
    assert sample["as_of"] == sample["evidence_cutoff"] == sample["simulated_forecast_time"]
    assert sample["outcome"] in {"yes", "no"}

    # The agent-protocol default toolset is unchanged (closed-book is opt-in):
    # without --closed-book the web toolset is still enabled. We assert the
    # default source list literal so a regression that silently strips web is
    # caught here.
    import inspect

    from forecasting import cli

    src = inspect.getsource(cli._backtest_agent_protocol_runner)
    assert '["forecasting", "file", "web"]' in src
    assert "closed_book" in src  # opt-in branch present
    # CLOSED-BOOK SEAL: the closed-book toolset must be EMPTY. Stripping "web" +
    # "forecasting" is not enough — the "file" toolset's read_file/search_files can
    # read the on-disk ForecastBench resolution-set cache (which holds resolved_to,
    # the answer). The replay scores the agent's parsed JSON output and needs no
    # tools, so closed-book runs reason-only.
    assert "[] if closed_book" in src


def test_closed_book_toolset_has_no_reachable_tool():
    # The closed-book toolset is empty: no network fetch AND no file read of the
    # on-disk resolution-set cache.
    from toolsets import resolve_multiple_toolsets

    closed_book_tools = set(resolve_multiple_toolsets([]))
    assert closed_book_tools == set()
    # explicitly: the answer-reaching tools are absent.
    for leaky in ("forecast_ledger", "web_search", "web_extract", "read_file", "search_files"):
        assert leaky not in closed_book_tools


def test_recorded_agent_model_defaults_to_resolved_model():
    # P2.4 model-cutoff gate fires on the recorded agent_model. When
    # --agent-model is omitted, the recorded model defaults to the runner's
    # resolved default model rather than an empty string.
    import argparse

    from forecasting import cli

    class _Runner:
        resolved_agent_model = "resolved-default-model"

    args = argparse.Namespace(agent_model=None)
    assert cli._resolved_recorded_agent_model(args, _Runner()) == "resolved-default-model"

    args_explicit = argparse.Namespace(agent_model="explicit-model")
    assert cli._resolved_recorded_agent_model(args_explicit, _Runner()) == "explicit-model"
