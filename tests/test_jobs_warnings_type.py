"""The WARNINGS job type end-to-end on the runtime, against a seeded ledger, and
the runtime's terminal-state contract (Arc B1)."""

from __future__ import annotations

import pytest

from forecasting.jobs import runtime
from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore
from forecasting.jobs.types import register, resolve, JobType


def _seed_ledger():
    from forecasting.ledger import ForecastLedger

    lg = ForecastLedger()  # default home DB (per-test HERMES_HOME)
    lg.create_alert(
        severity="high", scope_type="question", scope_ref="fq_a",
        reason="postmortem_due", recommended_action="Run a postmortem.")
    lg.create_alert(
        severity="warning", scope_type="question", scope_ref="fq_d",
        reason="domain_error_profile_applies:politics", recommended_action="Human review.")
    lg.create_alert(
        severity="info", scope_type="question", scope_ref="fq_f",
        reason="autopilot_enabled", recommended_action="Informational.")
    return lg


def _start(store, spec):
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="warnings", spec=spec))
    return job_id


def test_warnings_type_is_registered():
    wt = resolve("warnings")
    assert wt.alias_namespace == "forecast.warnings.automode"
    assert wt.min_interval_s == 0.125


def test_warnings_dry_run_end_to_end(tmp_path, monkeypatch):
    _seed_ledger()
    store = JobStore(home=tmp_path)
    job_id = _start(store, {"dry_run": True})

    events: list[dict] = []
    completed: list[dict] = []
    record = runtime.run(
        job_id, store=store, sink=events.append, on_complete=completed.append
    )

    assert record.status == "done"
    assert record.result["dry_run"] is True
    assert record.result["total"] == 3
    # The runtime fired on_complete with the same summary.
    assert completed and completed[0]["total"] == 3
    # Progress streamed (coalesced) and the terminal phase landed.
    phases = [e.get("phase") for e in events]
    assert "start" in phases and "done" in phases
    # The persisted record reflects the accounting.
    assert store.read(job_id).total == 3


def test_warnings_real_run_resolves_and_records(tmp_path):
    """A non-dry run drains the auto-resolvable backlog (bookkeeping resolves)."""
    lg = _seed_ledger()
    store = JobStore(home=tmp_path)
    job_id = _start(store, {"dry_run": False})

    record = runtime.run(job_id, store=store)
    assert record.status == "done"
    assert record.result["dry_run"] is False
    # The autopilot_enabled bookkeeping notice closed out; the manual-review one
    # stays open (surfaced, never acked).
    open_reasons = {a.reason for a in lg.list_alerts(unresolved_only=True)}
    assert "autopilot_enabled" not in open_reasons
    assert "domain_error_profile_applies:politics" in open_reasons


def test_warnings_cancellation_is_graceful(tmp_path):
    """A cancel before the run stops it cleanly: status 'cancelled', a summary
    with cancelled=True, on_complete (NOT on_error) fires, work is durable."""
    _seed_ledger()
    store = JobStore(home=tmp_path)
    job_id = _start(store, {"dry_run": True})
    # Request cancel up front so the very first should_cancel poll trips.
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
    # The stop file is cleaned up on exit.
    assert store.stop_path(job_id).exists() is False


def test_runtime_unknown_type_records_error(tmp_path):
    store = JobStore(home=tmp_path)
    job_id = store.new_id()
    store.write(JobRecord(job_id=job_id, type="does_not_exist"))
    errors: list[str] = []
    record = runtime.run(job_id, store=store, on_error=errors.append)
    assert record.status == "error"
    assert "unknown job type" in record.error
    assert errors and "unknown job type" in errors[0]


def test_runtime_execute_exception_records_error(tmp_path):
    """A crashing job type is recorded as error (on_error), never re-raised."""
    def _boom(spec, ctx):
        ctx.progress({"phase": "start"})
        raise RuntimeError("kaboom")

    register(JobType(name="_test_boom", execute=_boom))
    try:
        store = JobStore(home=tmp_path)
        job_id = store.new_id()
        store.write(JobRecord(job_id=job_id, type="_test_boom"))
        errors: list[str] = []
        record = runtime.run(job_id, store=store, on_error=errors.append)
        assert record.status == "error"
        assert "RuntimeError: kaboom" in record.error
        assert errors and "kaboom" in errors[0]
    finally:
        # Keep the registry clean for other tests.
        from forecasting.jobs.types import _REGISTRY

        _REGISTRY.pop("_test_boom", None)


def test_main_entrypoint_runs_a_job(tmp_path, monkeypatch):
    """python -m forecasting.jobs run <id> executes the job and exit-codes on
    its terminal status."""
    from forecasting.jobs.__main__ import main

    _seed_ledger()
    store = JobStore(home=tmp_path)
    # The CLI resolves a default JobStore() → get_agent_home(); point the store
    # at the same per-test home by writing through the default store.
    default_store = JobStore()
    job_id = default_store.new_id()
    default_store.write(JobRecord(job_id=job_id, type="warnings", spec={"dry_run": True}))

    assert main(["run", job_id]) == 0
    assert default_store.read(job_id).status == "done"
    # Bad usage exits 2.
    assert main([]) == 2
