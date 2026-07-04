"""The REFRESH job type end-to-end on the runtime (Arc B, the first NET-NEW job
type — the operator's Desk "Update now" mass sweep).

The deterministic re-pool that runs per question is
:meth:`ForecastLedger.refresh_forecast` (the SAME code path the CLI ``forecast
refresh <id>`` invokes, NOT the agent chain). The real re-pool needs live watched
sources, so we stub ``ForecastLedger.refresh_forecast`` at the class level to script
each question's status — asserting the type: runs the re-pool per question
sequentially, opens the ledger WRITE GATE around every call (the "same gated path,
nothing weakened" contract), classifies each outcome honestly, isolates a single
failing question (fail-open), and rolls the honest updated/unchanged/no-sources/error
tally into the result.
"""

from __future__ import annotations

import pytest

from forecasting.jobs import runtime
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import resolve
from forecasting.jobs.types.refresh import classify_refresh_status


@pytest.fixture
def home(tmp_path, monkeypatch):
    # Pin both home env vars (get_hermes_home checks SUPERFORECASTING_AGENT_HOME
    # first) so execute's ForecastLedger(None) + the JobStore land in the tempdir.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.delenv("FORECAST_LEDGER_DB", raising=False)
    return tmp_path


def _start(store, spec):
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="refresh", spec=spec))
    return job_id


def _script_refresh(monkeypatch, *, seen=None, assert_gate_open=True):
    """Stub ``ForecastLedger.refresh_forecast`` to script a status per question id.

    fq_a → committed (refreshed), fq_b → no_change (unchanged), fq_c →
    no_watched_sources (no_sources), fq_d → raises (error). Asserts the ledger write
    gate is OPEN during the call — proving the type reproduces the CLI's
    ``allow_ledger_writes`` environment (nothing weakened)."""
    from forecasting.ledger import ForecastLedger, forecast_commit_active

    def fake_refresh(self, qid, **kwargs):
        if seen is not None:
            seen.append(qid)
        if assert_gate_open:
            # The commit context MUST be active — the type opens it exactly as
            # cmd_forecast does, so create_snapshot's gate would permit the commit.
            assert forecast_commit_active() is True
        if qid == "fq_a":
            return {
                "status": "committed",
                "forecast_id": "fc_1",
                "prior_probability": 0.40,
                "proposed_probability": 0.55,
            }
        if qid == "fq_b":
            return {"status": "no_change", "message": "no new readings"}
        if qid == "fq_c":
            return {"status": "no_watched_sources", "message": "NO active watched sources"}
        if qid == "fq_d":
            raise ValueError("kaboom")
        return {"status": "committed"}

    monkeypatch.setattr(ForecastLedger, "refresh_forecast", fake_refresh, raising=True)


# ── registration ──────────────────────────────────────────────────────────────


def test_refresh_type_is_registered():
    rt = resolve("refresh")
    assert rt.name == "refresh"
    # A net-new capability: no legacy alias family, no LLM spend.
    assert rt.alias_namespace is None
    assert rt.spend_class == "free"


def test_classifier_ports_the_desk_client_logic():
    # The server-side port of the desk's old classifyRefresh.
    assert classify_refresh_status("committed") == "refreshed"
    assert classify_refresh_status("re_pooled") == "refreshed"
    assert classify_refresh_status("carry_forward") == "refreshed"
    assert classify_refresh_status("no_change") == "unchanged"
    assert classify_refresh_status("no_watched_sources") == "no_sources"
    assert classify_refresh_status(None) == "refreshed"


# ── lifecycle: mixed outcomes → honest tally ─────────────────────────────────


def test_mixed_outcomes_roll_into_an_honest_tally(home, monkeypatch):
    seen: list[str] = []
    _script_refresh(monkeypatch, seen=seen)
    store = JobStore(home=home)
    job_id = _start(store, {"question_ids": ["fq_a", "fq_b", "fq_c", "fq_d"]})

    events: list[dict] = []
    completed: list[dict] = []
    record = runtime.run(
        job_id, store=store, sink=events.append, on_complete=completed.append
    )

    assert record.status == "done"
    # Ran the re-pool once per question, in order.
    assert seen == ["fq_a", "fq_b", "fq_c", "fq_d"]

    # The honest tally never claims four updates: 1 refreshed, 1 unchanged, 1
    # no-sources, 1 error.
    assert record.result["tally"] == {
        "refreshed": 1,
        "unchanged": 1,
        "no_sources": 1,
        "error": 1,
    }
    assert record.result["total"] == 4
    assert record.result["done_count"] == 4
    assert record.result["cancelled"] is False

    outcomes = {r["question_id"]: r["outcome"] for r in record.result["results"]}
    assert outcomes == {
        "fq_a": "refreshed",
        "fq_b": "unchanged",
        "fq_c": "no_sources",
        "fq_d": "error",
    }
    # The refreshed row carries the honest probability move; the error row carries
    # the exception; the no-op rows carry the ledger's own message.
    detail = {r["question_id"]: r["detail"] for r in record.result["results"]}
    assert detail["fq_a"] == "0.4000→0.5500"
    assert "kaboom" in detail["fq_d"]
    assert detail["fq_b"] == "no new readings"

    # Progress streamed both the in-flight pointer and the per-question tick.
    phases = [e.get("phase") for e in events]
    assert "refresh" in phases and "question" in phases
    # The runtime fired on_complete with the same summary.
    assert completed and completed[0]["tally"]["error"] == 1

    # The persisted record reflects the accounting + the partial-results annotation
    # the desk polls to drop the ⋯ marker off completed rows.
    persisted = store.read(job_id)
    assert persisted.done_count == 4
    assert persisted.total == 4
    assert len(persisted.annotations["results"]) == 4


def test_one_failing_question_never_kills_the_batch(home, monkeypatch):
    """fq_d raises, but fq_a/fq_b/fq_c still complete (fail-open per question)."""
    _script_refresh(monkeypatch)
    store = JobStore(home=home)
    job_id = _start(store, {"question_ids": ["fq_d", "fq_a", "fq_b", "fq_c"]})

    record = runtime.run(job_id, store=store)
    assert record.status == "done"
    assert record.result["done_count"] == 4
    assert record.result["tally"]["error"] == 1
    assert record.result["tally"]["refreshed"] == 1


def test_cancel_before_run_is_graceful(home, monkeypatch):
    """A cancel requested up front stops the loop cleanly: status 'cancelled', a
    summary with cancelled=True, on_complete (NOT on_error) fires."""
    seen: list[str] = []
    _script_refresh(monkeypatch, seen=seen)
    store = JobStore(home=home)
    job_id = _start(store, {"question_ids": ["fq_a", "fq_b"]})
    store.request_cancel(job_id)

    errors: list[str] = []
    completed: list[dict] = []
    record = runtime.run(
        job_id, store=store, on_complete=completed.append, on_error=errors.append
    )

    assert record.status == "cancelled"
    assert record.result["cancelled"] is True
    assert completed and completed[0]["cancelled"] is True
    assert errors == []
    # It stopped BEFORE touching any question (the very first should_cancel tripped).
    assert seen == []
    assert store.stop_path(job_id).exists() is False


def test_empty_batch_is_a_clean_no_op(home, monkeypatch):
    _script_refresh(monkeypatch)
    store = JobStore(home=home)
    job_id = _start(store, {"question_ids": []})
    record = runtime.run(job_id, store=store)
    assert record.status == "done"
    assert record.result["total"] == 0
    assert record.result["tally"] == {
        "refreshed": 0,
        "unchanged": 0,
        "no_sources": 0,
        "error": 0,
    }
