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
