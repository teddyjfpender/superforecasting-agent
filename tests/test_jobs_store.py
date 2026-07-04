"""JobStore lifecycle + atomicity + id validation + active/list (Arc B1)."""

from __future__ import annotations

import json

import pytest

from forecasting.jobs.model import JobRecord
from forecasting.jobs.store import JobStore


def _store(tmp_path):
    return JobStore(home=tmp_path)


def test_new_id_is_prefixed_job(tmp_path):
    assert JobStore.new_id().startswith("job_")


def test_write_read_roundtrip(tmp_path):
    store = _store(tmp_path)
    rec = JobRecord(job_id="job_abc", type="warnings", spec={"dry_run": True})
    store.write(rec)
    got = store.read("job_abc")
    assert got.job_id == "job_abc"
    assert got.type == "warnings"
    assert got.spec == {"dry_run": True}
    assert got.status == "queued"
    # write() stamps updated_at.
    assert got.updated_at is not None


def test_read_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        _store(tmp_path).read("job_missing")


def test_exists(tmp_path):
    store = _store(tmp_path)
    assert store.exists("job_x") is False
    store.write(JobRecord(job_id="job_x", type="warnings"))
    assert store.exists("job_x") is True
    # A traversal id is rejected, not resolved.
    assert store.exists("../evil") is False


@pytest.mark.parametrize("bad", ["", "a/b", "a\\b", "..", ".hidden", "x/../y"])
def test_invalid_ids_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        _store(tmp_path).path(bad)


def test_write_is_atomic_no_partial_file(tmp_path):
    """The temp file is renamed into place — a reader never sees a half-written
    file, and no stray .tmp is left behind."""
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_atom", type="warnings"))
    files = sorted(p.name for p in store.jobs_dir().iterdir())
    assert files == ["job_atom.json"]
    # The persisted bytes are valid JSON with the full record shape.
    data = json.loads((store.jobs_dir() / "job_atom.json").read_text())
    assert set(data) >= {"job_id", "type", "status", "spec", "created_at", "progress"}


def test_list_newest_first_and_globs_only_job_files(tmp_path):
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_1", type="warnings", created_at="2026-01-01T00:00:00+00:00"))
    store.write(JobRecord(job_id="job_2", type="warnings", created_at="2026-02-01T00:00:00+00:00"))
    # A non-job file in the dir must be ignored by the glob.
    (store.jobs_dir() / "notes.txt").write_text("ignore me")
    ids = [r.job_id for r in store.list()]
    assert ids == ["job_2", "job_1"]


def test_active_filters_terminal_and_by_type(tmp_path):
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_run", type="warnings", status="running"))
    store.write(JobRecord(job_id="job_q", type="reforecast", status="queued"))
    store.write(JobRecord(job_id="job_done", type="warnings", status="done"))
    store.write(JobRecord(job_id="job_err", type="warnings", status="error"))

    all_active = {r.job_id for r in store.active()}
    assert all_active == {"job_run", "job_q"}

    warnings_active = {r.job_id for r in store.active(types=["warnings"])}
    assert warnings_active == {"job_run"}


def test_active_keeps_a_fresh_running_job(tmp_path):
    """Regression: a running job with a FRESH heartbeat stays active — the freshness
    gate must never hide a genuinely live agent (the chip must still light)."""
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_fresh", type="reforecast", status="running"))
    assert {r.job_id for r in store.active()} == {"job_fresh"}


def test_active_excludes_crashed_worker_with_stale_heartbeat(tmp_path):
    """Reproduces the stuck-chip bug (server layer 1): a worker that CRASHED or was
    KILLED never reaches the runtime's try/except, so it never writes a terminal
    ``done``/``error`` status — its record is stuck at ``running`` forever. Once its
    heartbeat (``updated_at``) goes stale it must drop out of ``active()``; otherwise
    the "N agents running" chip reads it as live for the whole session.

    Before the fix ``active()`` returned BOTH records (status-only filter); now the
    stale one is excluded. ``max_stale_s=None`` is the escape hatch that restores the
    old status-only behaviour."""
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_live", type="reforecast", status="running"))
    store.write(JobRecord(job_id="job_dead", type="reforecast", status="running"))

    # Simulate job_dead's worker dying long ago: patch the file directly (write()
    # would restamp updated_at to "now", masking the death).
    dead = store.path("job_dead")
    data = json.loads(dead.read_text())
    data["created_at"] = data["updated_at"] = "2020-01-01T00:00:00+00:00"
    dead.write_text(json.dumps(data))

    assert {r.job_id for r in store.active()} == {"job_live"}
    # Disabling the gate returns to the pure status filter (both come back).
    assert {r.job_id for r in store.active(max_stale_s=None)} == {"job_live", "job_dead"}


def test_active_freshness_gate_uses_injected_now(tmp_path):
    """The cutoff is ``now - max_stale_s``; an injected ``now`` far in the future
    stales even a just-written record, proving the gate keys off the heartbeat age."""
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_x", type="reforecast", status="running"))
    assert {r.job_id for r in store.active()} == {"job_x"}
    # 10 days later, a 30-min window has long since elapsed.
    future = __import__("time").time() + 10 * 86400
    assert store.active(now=future) == []


def test_request_cancel_sets_flag_and_stop_file(tmp_path):
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_c", type="warnings", status="running"))
    assert store.request_cancel("job_c") is True
    assert store.stop_path("job_c").exists()
    assert store.read("job_c").cancel_requested is True
    assert store.is_cancel_requested("job_c") is True
    # Unknown job: no-op, no stop file created.
    assert store.request_cancel("job_none") is False
    assert store.stop_path("job_none").exists() is False


def test_is_cancel_requested_flag_only_path(tmp_path):
    """A record with cancel_requested set but NO stop file still reads cancelled
    (the record-flag path, independent of the stop-file path)."""
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_f", type="warnings", status="running", cancel_requested=True))
    assert store.stop_path("job_f").exists() is False
    assert store.is_cancel_requested("job_f") is True


def test_clear_stop(tmp_path):
    store = _store(tmp_path)
    store.write(JobRecord(job_id="job_s", type="warnings", status="running"))
    store.request_cancel("job_s")
    assert store.stop_path("job_s").exists()
    store.clear_stop("job_s")
    assert store.stop_path("job_s").exists() is False
    # Idempotent.
    store.clear_stop("job_s")


# ── legacy read-shim (rf_/qr_ files that predate the runtime; Arc B4) ──────────


def test_from_dict_maps_legacy_run_id_and_mode():
    """A pre-migration record keyed its id as run_id and (reforecast/task) its kind
    as mode / spec.mode — from_dict shims all three onto job_id / type."""
    rec = JobRecord.from_dict(
        {"run_id": "rf_legacy1", "mode": "task", "status": "running", "spec": {"question_ids": ["q1"]}}
    )
    assert rec.job_id == "rf_legacy1"
    assert rec.type == "task"

    # type resolves from spec.mode when there is no top-level mode.
    rec2 = JobRecord.from_dict({"run_id": "rf_legacy2", "status": "queued", "spec": {"mode": "reforecast"}})
    assert rec2.job_id == "rf_legacy2"
    assert rec2.type == "reforecast"

    # A canonical record is untouched by the fallbacks.
    rec3 = JobRecord.from_dict({"job_id": "job_x", "type": "warnings"})
    assert (rec3.job_id, rec3.type) == ("job_x", "warnings")


def _seed_legacy_reforecast(tmp_path, *, run_id="rf_live1", status="running", mode="reforecast", n=2):
    from forecasting.jobs.types import reforecast as rf

    rf.write_job(
        {
            "run_id": run_id,
            "status": status,
            "created_at": rf._now_iso(),
            "spec": {"question_ids": [f"q{i}" for i in range(n)], "mode": mode},
            "total": n,
            "done_count": 0,
            "current": None,
            "results": [],
            "error": None,
        }
    )


def _seed_legacy_quorum(tmp_path, *, run_id="qr_live1", status="running", question_id="fq_a"):
    from forecasting.jobs.types import quorum as qr

    qr.write_job(
        {
            "run_id": run_id,
            "question_id": question_id,
            "status": status,
            "created_at": qr._now_iso(),
            "spec": {"question_id": question_id},
            "progress": [],
            "result": None,
            "panel_run_id": None,
            "error": None,
        }
    )


@pytest.fixture
def legacy_home(tmp_path, monkeypatch):
    # rf/qr write_job() resolve their dir via get_hermes_home(); pin both env vars
    # so the legacy files AND JobStore() land in the same tempdir.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    return tmp_path


def test_list_surfaces_legacy_rf_and_qr_files(legacy_home):
    """The GENERIC store list() answers for old rf_/qr_ files — a real legacy-shaped
    reforecast run and quorum run both shim into JobRecords with the right type."""
    _seed_legacy_reforecast(legacy_home, run_id="rf_live1", mode="reforecast")
    _seed_legacy_quorum(legacy_home, run_id="qr_live1", question_id="fq_senate")

    store = JobStore()  # resolves home from the pinned env
    by_id = {r.job_id: r for r in store.list()}
    assert set(by_id) == {"rf_live1", "qr_live1"}
    assert by_id["rf_live1"].type == "reforecast"
    assert by_id["rf_live1"].spec.get("question_ids") == ["q0", "q1"]
    assert by_id["qr_live1"].type == "quorum"
    assert by_id["qr_live1"].spec.get("question_id") == "fq_senate"


def test_legacy_task_mode_resolves_task_type(legacy_home):
    _seed_legacy_reforecast(legacy_home, run_id="rf_task1", mode="task", n=1)
    store = JobStore()
    rec = {r.job_id: r for r in store.list()}["rf_task1"]
    assert rec.type == "task"


def test_active_includes_only_in_flight_legacy(legacy_home):
    _seed_legacy_reforecast(legacy_home, run_id="rf_run", status="running")
    _seed_legacy_reforecast(legacy_home, run_id="rf_done", status="done")
    _seed_legacy_quorum(legacy_home, run_id="qr_run", status="queued")
    _seed_legacy_quorum(legacy_home, run_id="qr_err", status="error")

    store = JobStore()
    assert {r.job_id for r in store.active()} == {"rf_run", "qr_run"}
    # The types filter reaches legacy records too.
    assert {r.job_id for r in store.active(types=["quorum"])} == {"qr_run"}


def test_active_excludes_statusless_legacy_record(legacy_home):
    """Reproduces the stuck-chip bug (server layer 2): a pre-migration legacy
    ``rf_``/``qr_`` file that carries NO ``status`` key rebuilds with the JobRecord
    DEFAULT ``status='queued'`` (an active status) — so a finished/abandoned legacy
    run would scan as forever-in-flight. Such files predate the migration, so their
    ancient ``created_at`` heartbeat stales them out of ``active()``."""
    from forecasting.jobs.types import reforecast as rf

    (rf.jobs_dir() / "rf_nostatus.json").write_text(
        json.dumps(
            {
                "run_id": "rf_nostatus",
                # NOTE: no "status" key → JobRecord defaults it to "queued".
                "created_at": "2020-01-01T00:00:00+00:00",
                "spec": {"question_ids": ["q0"], "mode": "reforecast"},
            }
        ),
        encoding="utf-8",
    )
    store = JobStore()

    # It DOES shim into a (default) queued record on the raw list...
    listed = {r.job_id: r for r in store.list()}
    assert listed["rf_nostatus"].status == "queued"
    # ...but the stale heartbeat keeps it OUT of the live-agents count.
    assert "rf_nostatus" not in {r.job_id for r in store.active()}


def test_read_finds_a_legacy_file(legacy_home):
    _seed_legacy_quorum(legacy_home, run_id="qr_read", question_id="fq_x")
    store = JobStore()
    rec = store.read("qr_read")
    assert rec.job_id == "qr_read"
    assert rec.type == "quorum"
    # A missing id still raises (legacy scan exhausted).
    with pytest.raises(FileNotFoundError):
        store.read("qr_absent")


def test_new_and_legacy_records_coexist_newest_first(legacy_home):
    """A migrated ``job_`` record and surviving legacy files list together, newest
    first — the generic store is the single source across the migration boundary."""
    store = JobStore()
    store.write(
        JobRecord(job_id="job_new", type="quorum", status="running", created_at="2026-07-04T00:00:00+00:00")
    )
    _seed_legacy_reforecast(legacy_home, run_id="rf_old", status="running")  # _now_iso → newer
    ids = [r.job_id for r in store.list()]
    assert set(ids) == {"job_new", "rf_old"}
    assert ids[0] == "rf_old"  # seeded "now" sorts ahead of the 2026-07-04 fixture


def test_include_legacy_false_scopes_to_new_store(legacy_home):
    _seed_legacy_reforecast(legacy_home, run_id="rf_only")
    store = JobStore()
    assert store.list(include_legacy=False) == []
    assert store.active(include_legacy=False) == []
