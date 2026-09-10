"""GATE 2 (#181) — the LIVE supervisor search_runner wiring + its backend.

Two layers are pinned here:

  1. ``forecasting.supervisor_search.build_supervisor_search_runner`` — the real
     fresh-search backend adapter: it reshapes web-search rows into the quorum's
     ``{title, summary, source, url, available_at}`` evidence dicts, is BOUNDED
     (caps queries/results, dedups), and is ROBUST (a failing backend yields
     ``[]`` and never throws).

  2. ``forecasting.jobs.types.quorum.execute`` — the live caller. With the gate OFF
     (the default) it passes NO search_runner so the run is byte-identical
     (research_rounds 0, supervisor_evidence empty). With the gate ON + a MOCK
     backend + a judge that flags an information gap, the supervisor loop runs
     exactly one research round, folds the mock evidence into the re-synthesis,
     and persists research_rounds=1 + supervisor_evidence.
"""

from __future__ import annotations

import json

import pytest

import forecasting.quorum as quorum
import forecasting.supervisor_search as ss
from forecasting.jobs.types import quorum as qj
from forecasting.ledger import ForecastLedger
from forecasting.supervisor_search import build_supervisor_search_runner


# ── 1. the search_runner backend adapter ──────────────────────────────────────


def _web_payload(rows):
    return json.dumps({"success": True, "data": {"web": rows}})


def test_runner_reshapes_web_rows_into_evidence_dicts():
    def backend(query, limit):
        return _web_payload(
            [
                {"title": "Fresh poll", "url": "https://ex.com/a", "description": "challenger +4"},
            ]
        )

    runner = build_supervisor_search_runner(backend=backend, available_at="2026-06-28T00:00:00Z")
    out = runner(["latest poll?"])
    assert out == [
        {
            "title": "Fresh poll",
            "summary": "challenger +4",
            "source": "ex.com",
            "url": "https://ex.com/a",
            "available_at": "2026-06-28T00:00:00Z",
        }
    ]


def test_runner_caps_queries_and_results():
    calls: list[tuple[str, int]] = []

    def backend(query, limit):
        calls.append((query, limit))
        # Return more rows than the per-query cap to prove we slice.
        return _web_payload(
            [
                {"title": f"{query}-{i}", "url": f"https://ex.com/{query}/{i}", "description": "d"}
                for i in range(10)
            ]
        )

    runner = build_supervisor_search_runner(
        backend=backend, max_queries=2, max_results_per_query=3, total_cap=100
    )
    out = runner(["q1", "q2", "q3", "q4"])  # 4 asked; only 2 issued

    assert [q for q, _ in calls] == ["q1", "q2"]  # query cap honoured
    assert all(limit == 3 for _, limit in calls)  # per-query result cap requested
    assert len(out) == 6  # 2 queries x 3 results


def test_runner_total_cap_bounds_output():
    def backend(query, limit):
        return _web_payload(
            [{"title": f"t{i}", "url": f"https://ex.com/{query}/{i}", "description": "d"} for i in range(5)]
        )

    runner = build_supervisor_search_runner(
        backend=backend, max_queries=3, max_results_per_query=5, total_cap=4
    )
    out = runner(["a", "b", "c"])
    assert len(out) == 4  # total_cap wins over per-query * queries


def test_runner_dedupes_by_url_across_queries():
    def backend(query, limit):
        # Both queries surface the SAME url — must appear once.
        return _web_payload([{"title": "same", "url": "https://ex.com/x?utm_source=z", "description": "d"}])

    runner = build_supervisor_search_runner(backend=backend, max_queries=2)
    out = runner(["q1", "q2"])
    assert len(out) == 1


def test_runner_returns_empty_on_backend_failure_never_throws():
    def backend(query, limit):
        raise RuntimeError("provider down")

    runner = build_supervisor_search_runner(backend=backend)
    # Must not raise; a failed search contributes nothing.
    assert runner(["q1", "q2"]) == []


def test_runner_tolerates_unsuccessful_or_garbage_payload():
    def backend(query, limit):
        return json.dumps({"success": False, "error": "no provider configured"})

    assert build_supervisor_search_runner(backend=backend)(["q"]) == []
    assert build_supervisor_search_runner(backend=lambda q, l: "not json")(["q"]) == []


def test_runner_empty_queries_yield_empty():
    called = {"n": 0}

    def backend(query, limit):
        called["n"] += 1
        return _web_payload([])

    assert build_supervisor_search_runner(backend=backend)([]) == []
    assert called["n"] == 0  # no queries -> no backend calls


# ── 2. execute_job wiring (gate OFF default / gate ON) ─────────────────────────


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    return tmp_path


def _gap_runner_factory():
    """A runner whose JUDGE pass ALWAYS flags an information gap with queries, so a
    wired supervisor loop has something to act on; panelists return a flat prob."""

    def make(**_kwargs):
        def runner(model, system, user):
            if "JUDGE" in system:
                return json.dumps(
                    {
                        "probability": 0.4,
                        "rationale": "judge synthesis",
                        "directional_confidence": "medium",
                        "information_gap": True,
                        "clarifying_queries": ["latest poll?", "turnout model?"],
                        "blind_spots": ["regime shift unpriced"],
                    }
                )
            return json.dumps(
                {
                    "probability": 0.5,
                    "confidence_low": 0.2,
                    "confidence_high": 0.7,
                    "rationale": "panelist reasoning",
                    "reasons_up": ["up"],
                    "reasons_down": ["down"],
                    "change_my_mind": ["cmm"],
                    "crux": "the crux",
                }
            )

        return runner

    return make


def _question(ledger):
    return ledger.create_question(
        title="Will the challenger flip the seat in 2026?",
        resolution_criteria="Resolves YES if the challenger wins per the certified result.",
        impact="high",
    )


def test_off_switch_via_spec_flag_byte_identical(home, tmp_path, monkeypatch):
    # The appconfig-tunable OFF switch: an EXPLICIT supervisor_search=False in the
    # spec (mirrors `forecast quorum --no-supervisor-search` / quorum.supervisor_search
    # = false) keeps the run byte-identical to the pre-edge behaviour — no search
    # runner is built even though the judge flags a gap.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)

    monkeypatch.setattr(quorum, "make_aiagent_runner", _gap_runner_factory())
    # If anything tried to build a live search runner, fail loudly.
    monkeypatch.setattr(
        ss,
        "build_supervisor_search_runner",
        lambda **_k: (_ for _ in ()).throw(AssertionError("search_runner must not be built when OFF")),
    )

    spec = {
        "question_id": q.id, "db": db, "models": ["a/m1", "b/m2"], "trim": 0,
        "supervisor_search": False,  # OFF switch
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    result = job["result"]
    # Even though the judge flagged a gap, with the gate OFF no research runs.
    assert result["research_rounds"] == 0
    assert result["supervisor_evidence"] == []

    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["research_rounds"] == 0
    assert panel["supervisor_evidence"] == []
    stages = [p["stage"] for p in job["progress"]]
    assert "supervisor_search" not in stages


def test_live_default_on_fires_runner_without_any_config(home, tmp_path, monkeypatch):
    # DEFAULT ON (finding #1): with NO supervisor_search key in the spec AND no config
    # override at all, a LIVE quorum still runs the fresh-search loop. This pins the
    # code-level default so a regression back to 0/223 is caught.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)

    monkeypatch.setattr(quorum, "make_aiagent_runner", _gap_runner_factory())
    monkeypatch.setattr(
        ss, "build_supervisor_search_runner",
        lambda **_k: (lambda queries: [{"title": "fresh"}]),
    )
    # Empty config (no quorum key at all) -> the code fallback must default ON.
    import superforecasting_agent.runtime.config as hc

    monkeypatch.setattr(hc, "load_config", lambda: {})

    spec = {"question_id": q.id, "db": db, "models": ["a/m1", "b/m2"], "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    result = job["result"]
    # The proven edge fired on its own: one research round + the fresh evidence.
    assert result["research_rounds"] == 1
    assert result["supervisor_evidence"] == [{"title": "fresh"}]
    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["research_rounds"] == 1
    stages = [p["stage"] for p in job["progress"]]
    assert "supervisor_search" in stages


def test_gate_on_runs_one_research_round_and_persists_evidence(home, tmp_path, monkeypatch):
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)

    monkeypatch.setattr(quorum, "make_aiagent_runner", _gap_runner_factory())

    seen_queries: list[list[str]] = []
    mock_evidence = [
        {
            "title": "Fresh poll",
            "summary": "challenger +4",
            "source": "pollster.com",
            "url": "https://pollster.com/a",
            "available_at": "2026-06-28T00:00:00Z",
        }
    ]

    def fake_build(**_kwargs):
        def runner(queries):
            seen_queries.append(list(queries))
            return list(mock_evidence)

        return runner

    # Stub the backend-builder so the wiring uses a MOCK search instead of the
    # live provider (this is the seam GATE 2 lights up).
    monkeypatch.setattr(ss, "build_supervisor_search_runner", fake_build)

    spec = {
        "question_id": q.id,
        "db": db,
        "models": ["a/m1", "b/m2"],
        "trim": 0,
        "supervisor_search": True,  # GATE ON for this run
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    result = job["result"]
    # Exactly one research round fired and folded the mock evidence in.
    assert result["research_rounds"] == 1
    assert seen_queries == [["latest poll?", "turnout model?"]]
    assert result["supervisor_evidence"] == mock_evidence

    # Persisted on the panel run.
    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["research_rounds"] == 1
    assert panel["supervisor_evidence"] == mock_evidence

    stages = [p["stage"] for p in job["progress"]]
    assert "supervisor_search" in stages
    assert "research_start" in stages and "research_done" in stages


def test_gate_on_via_config_flag(home, tmp_path, monkeypatch):
    """No per-run spec key -> the quorum.supervisor_search config flag turns it on
    (the market-nightly / operator fleet switch)."""

    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)

    monkeypatch.setattr(quorum, "make_aiagent_runner", _gap_runner_factory())
    monkeypatch.setattr(
        ss, "build_supervisor_search_runner", lambda **_k: (lambda queries: [{"title": "cfg"}])
    )
    # _supervisor_search_enabled does a function-local `from superforecasting_agent.runtime.config import
    # load_config`, so the real seam is superforecasting_agent.runtime.config.load_config.
    import superforecasting_agent.runtime.config as hc

    monkeypatch.setattr(hc, "load_config", lambda: {"quorum": {"supervisor_search": True}})

    spec = {"question_id": q.id, "db": db, "models": ["a/m1", "b/m2"], "trim": 0}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    assert job["result"]["research_rounds"] == 1
    assert job["result"]["supervisor_evidence"] == [{"title": "cfg"}]


def test_gate_on_but_historical_cutoff_disables_search(home, tmp_path, monkeypatch):
    # LEAKAGE GUARD (the review MAJOR): even with the gate ON, a HISTORICAL
    # evidence_cutoff (a backtest/replay snapshot) must DISABLE the supervisor
    # search — fresh web search returns present-day content that cannot be pinned
    # to a past cutoff, so it would leak post-cutoff information.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)
    # A snapshot pinned to a long-past as_of => execute_job derives a historical cutoff.
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5,
        rationale="seed", as_of="2020-06-01T00:00:00Z",
    )

    monkeypatch.setattr(quorum, "make_aiagent_runner", _gap_runner_factory())
    # If a search runner were built for a historical cutoff, fail loudly.
    monkeypatch.setattr(
        ss, "build_supervisor_search_runner",
        lambda **_k: (_ for _ in ()).throw(
            AssertionError("search must be disabled for a historical cutoff")
        ),
    )

    spec = {"question_id": q.id, "db": db, "models": ["a/m1", "b/m2"], "trim": 0,
            "supervisor_search": True}
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    assert job["result"]["research_rounds"] == 0  # disabled by the cutoff guard
    stages = {p["stage"]: p["detail"] for p in job["progress"]}
    assert "supervisor_search" in stages and "DISABLED" in stages["supervisor_search"]


# ── 3. Delphi ⟷ supervisor-search interaction (spec §"Supervisor Search Interaction") ─


_PANELIST_JSON = json.dumps(
    {
        "probability": 0.5,
        "confidence_low": 0.2,
        "confidence_high": 0.7,
        "rationale": "panelist reasoning",
        "reasons_up": ["up"],
        "reasons_down": ["down"],
        "change_my_mind": ["cmm"],
        "crux": "the crux",
    }
)

_GAP_JUDGE_JSON = json.dumps(
    {
        "probability": 0.4,
        "rationale": "judge synthesis",
        "directional_confidence": "medium",
        "information_gap": True,
        "clarifying_queries": ["latest poll?", "turnout model?"],
        "blind_spots": ["regime shift unpriced"],
    }
)


def test_delphi_supervisor_search_feeds_revision_round(home, tmp_path, monkeypatch):
    # Gate ON + delphi_rounds=1: the round-1 judge flags an information gap, the mock
    # supervisor search returns one fresh evidence item, and that item must be folded
    # into the ANONYMOUS Delphi reveal handed to every revision-round panelist. The
    # persisted result carries BOTH research_rounds=1 and delphi_rounds=1.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)

    revision_prompts: list[str] = []

    def make(**_kwargs):
        def runner(model, system, user):
            if "JUDGE" in system:
                return _GAP_JUDGE_JSON
            # The private revision round appends the "## Delphi Revision Context".
            if "Delphi Revision Context" in user:
                revision_prompts.append(user)
            return _PANELIST_JSON

        return runner

    monkeypatch.setattr(quorum, "make_aiagent_runner", make)

    seen_queries: list[list[str]] = []
    mock_evidence = [
        {
            "title": "Fresh poll",
            "summary": "challenger +4",
            "source": "pollster.com",
            "url": "https://pollster.com/a",
            "available_at": "2026-06-28T00:00:00Z",
        }
    ]

    def fake_build(**_kwargs):
        def runner(queries):
            seen_queries.append(list(queries))
            return list(mock_evidence)

        return runner

    monkeypatch.setattr(ss, "build_supervisor_search_runner", fake_build)

    spec = {
        "question_id": q.id,
        "db": db,
        "models": ["a/m1", "b/m2"],
        "trim": 0,
        "supervisor_search": True,  # GATE ON
        "delphi_rounds": 1,  # one private revision round
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    result = job["result"]
    # One research round fired on the round-1 judge's gap queries, and one Delphi round.
    assert result["research_rounds"] == 1
    assert result["delphi_rounds"] == 1
    assert seen_queries == [["latest poll?", "turnout model?"]]
    assert result["supervisor_evidence"] == mock_evidence

    # The fresh evidence reached the revision-round panelist prompt (via the anonymous
    # Delphi summary's "fresh evidence added after round 1" line).
    assert revision_prompts, "expected at least one Delphi revision-round panelist prompt"
    assert all("Fresh poll: challenger +4" in p for p in revision_prompts)

    # Persisted on the panel run.
    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["research_rounds"] == 1
    assert panel["delphi_rounds"] == 1
    assert panel["supervisor_evidence"] == mock_evidence

    stages = [p["stage"] for p in job["progress"]]
    assert "supervisor_search" in stages
    assert "research_start" in stages and "research_done" in stages
    assert "delphi_start" in stages and "delphi_done" in stages


def test_delphi_historical_cutoff_disables_fresh_search(home, tmp_path, monkeypatch):
    # LEAKAGE GUARD under Delphi: even with the gate ON and delphi_rounds=1, a
    # HISTORICAL evidence_cutoff must DISABLE the fresh supervisor search (present-day
    # web content can't be pinned to a past cutoff). The Delphi revision round STILL
    # runs — it just relies on the supplied historical context, adding NO fresh evidence.
    db = str(tmp_path / "forecasts.db")
    ledger = ForecastLedger(db)
    q = _question(ledger)
    # A snapshot pinned to a long-past as_of => execute_job derives a historical cutoff.
    ledger.create_snapshot(
        question_id=q.id,
        probability_or_distribution=0.5,
        rationale="seed",
        as_of="2020-06-01T00:00:00Z",
    )

    revision_prompts: list[str] = []

    def make(**_kwargs):
        def runner(model, system, user):
            if "JUDGE" in system:
                return _GAP_JUDGE_JSON
            if "Delphi Revision Context" in user:
                revision_prompts.append(user)
            return _PANELIST_JSON

        return runner

    monkeypatch.setattr(quorum, "make_aiagent_runner", make)
    # If a search runner were built for a historical cutoff, fail loudly.
    monkeypatch.setattr(
        ss,
        "build_supervisor_search_runner",
        lambda **_k: (_ for _ in ()).throw(
            AssertionError("search must be disabled for a historical cutoff")
        ),
    )

    spec = {
        "question_id": q.id,
        "db": db,
        "models": ["a/m1", "b/m2"],
        "trim": 0,
        "supervisor_search": True,  # GATE ON, but the cutoff guard overrides it
        "delphi_rounds": 1,
    }
    run_id = qj.start_job(spec, wait=True)
    job = qj.read_job(run_id)

    assert job["status"] == "done", job.get("error")
    result = job["result"]
    # No fresh search under a historical cutoff: no research round, no supervisor evidence.
    assert result["research_rounds"] == 0
    assert result["supervisor_evidence"] == []
    # ...but Delphi still ran on the historical context.
    assert result["delphi_rounds"] == 1
    assert result["delphi_audit"].get("rounds")
    assert revision_prompts, "Delphi revision round should still run without fresh search"
    assert all(
        "fresh evidence added after round 1: (none)" in p for p in revision_prompts
    )

    panel = ledger.get_panel_run(job["panel_run_id"])
    assert panel["research_rounds"] == 0
    assert panel["delphi_rounds"] == 1
    assert panel["supervisor_evidence"] == []

    stages = {p["stage"]: p["detail"] for p in job["progress"]}
    assert "supervisor_search" in stages and "DISABLED" in stages["supervisor_search"]
    assert "delphi_start" in stages and "delphi_done" in stages


def test_resolve_active_model_id_handles_codex_dict_config():
    # Regression: config["model"] is a structured dict since the codex auth overhaul.
    # _quorum_run must extract the id STRING — passing the raw dict downstream made the
    # quorum's self/judge model a dict and crashed every panelist with
    # `'dict' object has no attribute 'lower'` (a silent, total quorum failure).
    from forecasting.cli import _resolve_active_model_id

    assert _resolve_active_model_id(
        {"base_url": "https://x/codex", "default": "gpt-5.5", "provider": "openai-codex"}
    ) == "gpt-5.5"
    assert _resolve_active_model_id({"model": "legacy-id"}) == "legacy-id"  # legacy key
    assert _resolve_active_model_id("bare-string-id") == "bare-string-id"  # legacy bare string
    assert _resolve_active_model_id(None) is None
    assert _resolve_active_model_id({}) is None
    assert _resolve_active_model_id({"default": ""}) is None
