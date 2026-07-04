"""Conformance for the ``jobs.*`` protocol models (Arc B on Arc A).

* every jobs RPC is registered with request + response models;
* a real gateway frame (built from a JobRecord.to_dict) round-trips through the
  response model and model_dump reproduces it;
* the jobs.* events round-trip;
* requests validate — the required field is named on rejection.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from forecasting.jobs.model import JobRecord
from protocol import EVENT_SPECS, RPC_BY_METHOD, RPC_SPECS
from protocol.events.jobs import JobComplete, JobError, JobProgress

JOBS_METHODS = {"jobs.start", "jobs.status", "jobs.active", "jobs.cancel"}


def _record_frame() -> dict:
    rec = JobRecord(
        job_id="job_abc123",
        type="warnings",
        status="running",
        spec={"dry_run": True},
        created_at="2026-07-04T00:00:00+00:00",
        updated_at="2026-07-04T00:00:01+00:00",
        done_count=2,
        total=3,
        current="al_1",
        progress=[{"phase": "alert", "done": 2, "total": 3}],
        result=None,
        error=None,
        cancel_requested=False,
        annotations={"spend_class": "free"},
    )
    return rec.to_dict()


def test_registry_covers_every_jobs_rpc():
    registered = {s.method for s in RPC_SPECS if s.method.startswith("jobs.")}
    assert registered == JOBS_METHODS
    for spec in RPC_SPECS:
        if spec.method in JOBS_METHODS:
            assert spec.request is not None and spec.response is not None


def test_jobs_events_are_registered():
    names = {e.name for e in EVENT_SPECS}
    assert {"jobs.progress", "jobs.complete", "jobs.error"} <= names


def test_status_response_frame_roundtrips():
    spec = RPC_BY_METHOD["jobs.status"]
    frame = {"found": True, "job": _record_frame()}
    dumped = spec.response.model_validate(frame).model_dump(mode="json")
    assert dumped == frame


def test_status_response_not_found_roundtrips():
    spec = RPC_BY_METHOD["jobs.status"]
    frame = {"found": False, "job": None}
    dumped = spec.response.model_validate(frame).model_dump(mode="json")
    assert dumped == frame


def test_active_response_frame_roundtrips():
    spec = RPC_BY_METHOD["jobs.active"]
    frame = {"jobs": [_record_frame()], "count": 1}
    dumped = spec.response.model_validate(frame).model_dump(mode="json")
    assert dumped == frame


def test_start_and_cancel_response_roundtrip():
    start = RPC_BY_METHOD["jobs.start"]
    sframe = {"job_id": "job_x", "type": "warnings"}
    assert start.response.model_validate(sframe).model_dump(mode="json") == sframe

    cancel = RPC_BY_METHOD["jobs.cancel"]
    cframe = {"job_id": "job_x", "found": True, "cancelled": True}
    assert cancel.response.model_validate(cframe).model_dump(mode="json") == cframe


@pytest.mark.parametrize(
    "method,payload",
    [
        ("jobs.start", {"type": "warnings", "spec": {"dry_run": True}, "session_id": "s1"}),
        ("jobs.start", {"type": "warnings"}),  # spec/session optional
        ("jobs.status", {"job_id": "job_x"}),
        ("jobs.active", {}),  # types optional
        ("jobs.active", {"types": ["warnings", "reforecast"]}),
        ("jobs.cancel", {"job_id": "job_x"}),
    ],
)
def test_valid_jobs_requests_accepted(method, payload):
    RPC_BY_METHOD[method].request.model_validate(payload)  # must not raise


@pytest.mark.parametrize(
    "method,payload,field",
    [
        ("jobs.start", {}, "type"),
        ("jobs.status", {}, "job_id"),
        ("jobs.cancel", {}, "job_id"),
    ],
)
def test_invalid_jobs_requests_rejected_naming_field(method, payload, field):
    with pytest.raises(ValidationError) as excinfo:
        RPC_BY_METHOD[method].request.model_validate(payload)
    locs = {str(part) for err in excinfo.value.errors() for part in err["loc"]}
    assert field in locs


@pytest.mark.parametrize(
    "model,frame",
    [
        (JobProgress, {"job_id": "job_x", "type": "warnings",
                       "progress": {"phase": "alert", "done": 1, "total": 3}}),
        (JobComplete, {"job_id": "job_x", "type": "warnings",
                       "result": {"total": 3, "cancelled": False}}),
        (JobError, {"job_id": "job_x", "type": "warnings", "message": "boom"}),
    ],
)
def test_jobs_events_roundtrip(model, frame):
    assert model.model_validate(frame).model_dump(mode="json") == frame
