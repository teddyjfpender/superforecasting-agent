"""Editor persistence must never confirm a belief or resurrect discarded text."""

import json
import os
import subprocess
import sys
from contextlib import contextmanager

import pytest
from pydantic import ValidationError as ModelError

from forecasting.interviews.buffers import read_buffers, save_buffer
from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger
from forecasting.models import ValidationError
from protocol.interviews import InterviewDraft, InterviewEditorBuffer
from protocol.rpc.interviews import InterviewBufferSaveRequest


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    service = InterviewService(ledger)
    service.begin("draft")
    return ledger, service


def edit(**overrides):
    return InterviewBufferSaveRequest.model_validate({
        "interview_id": "draft",
        "question_id": "title",
        "base_revision": 1,
        "expected_buffer_revision": 0,
        "request_id": "save-1",
        "buffer": {"text": "Unconfirmed question", "note": "Check the source"},
        **overrides,
    })


def test_retry_and_discard_do_not_resurrect_text(desk):
    ledger, service = desk
    request = edit()
    ack = save_buffer(ledger, request)
    assert save_buffer(ledger, request) == ack
    assert service.store.read("draft")["revision"] == 1
    assert service.store.read("draft")["document"]["answers"] == []
    assert (
        read_buffers(ledger, "draft")["buffers"][0]["buffer"]["text"]
        == "Unconfirmed question"
    )
    discard = save_buffer(
        ledger, edit(buffer=None, expected_buffer_revision=1, request_id="discard")
    )
    assert discard["discarded"] and discard["buffer_revision"] == 2
    assert save_buffer(ledger, request) == ack
    current = read_buffers(ledger, "draft")["buffers"][0]
    assert current["buffer"] is None and current["discarded"]
    with ledger._connect() as conn:
        assert all(
            "Unconfirmed question" not in row[0]
            for row in conn.execute(
                "SELECT receipt FROM forecast_interview_buffer_receipts"
            )
        )
    assert ledger.list_questions() == []


def test_conflicting_writers_and_changed_interview_fail_closed(desk):
    ledger, service = desk
    request = edit()
    save_buffer(ledger, request)
    with pytest.raises(ValidationError, match="identifier reused"):
        save_buffer(ledger, edit(buffer={"text": "Changed retry"}))
    with pytest.raises(ValidationError, match="buffer changed"):
        save_buffer(ledger, edit(request_id="competing-tab"))
    service.answer(
        "draft",
        expected_revision=1,
        request_id="confirm",
        question_id="title",
        status="answered",
        value="Confirmed title",
    )
    assert read_buffers(ledger, "draft")["buffers"][0]["stale"]
    with pytest.raises(ValidationError, match="interview changed"):
        save_buffer(ledger, edit(request_id="late", expected_buffer_revision=1))
    assert (
        service.store.read("draft")["document"]["answers"][0]["value"]
        == "Confirmed title"
    )


def test_receipt_failure_rolls_back_editor_write(desk, monkeypatch):
    ledger, _ = desk
    transaction = ledger.transaction

    class FailingReceipt:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if sql.startswith("INSERT INTO forecast_interview_buffer_receipts"):
                raise RuntimeError("interrupted receipt write")
            return self.conn.execute(sql, params)

    @contextmanager
    def interrupted(*args, **kwargs):
        with transaction(*args, **kwargs) as conn:
            yield FailingReceipt(conn)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "transaction", interrupted)
        with pytest.raises(RuntimeError, match="interrupted receipt"):
            save_buffer(ledger, edit())
    assert read_buffers(ledger, "draft") == {"buffers": []}
    assert save_buffer(ledger, edit())["buffer_revision"] == 1


def test_acknowledged_buffer_survives_process_exit(desk):
    ledger, service = desk
    # A separate process commits and exits without Python cleanup. The parent
    # verifies the durable receipt and draft rather than relying on process memory.
    with ledger._connect() as conn:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
    program = """
import json, os, sys
from forecasting.ledger import ForecastLedger
from forecasting.interviews.buffers import save_buffer
from protocol.rpc.interviews import InterviewBufferSaveRequest
r = save_buffer(ForecastLedger(sys.argv[1]), InterviewBufferSaveRequest.model_validate_json(sys.argv[2]))
print(json.dumps(r), flush=True)
os._exit(0)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, path, edit().model_dump_json()],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
        env=os.environ.copy(),
    )
    assert json.loads(result.stdout)["buffer_revision"] == 1
    restored = read_buffers(ForecastLedger(path), "draft")["buffers"][0]
    assert restored["buffer"]["note"] == "Check the source"
    assert not restored["stale"]
    assert service.store.read("draft")["document"]["answers"] == []


def test_cancel_removes_draft_content_and_rejects_new_writes(desk):
    ledger, service = desk
    save_buffer(ledger, edit())
    record = service.store.read("draft")
    draft = InterviewDraft.model_validate(record["document"])
    draft.status = "cancelled"
    service.store.save(
        "draft", draft, expected_revision=1, request_id="cancel", actor="user"
    )
    assert read_buffers(ledger, "draft") == {"buffers": []}
    with ledger._connect() as conn:
        assert (
            conn.execute("SELECT document FROM forecast_interview_buffers").fetchone()[
                0
            ]
            is None
        )
    with pytest.raises(ValidationError, match="closed interviews"):
        save_buffer(
            ledger, edit(request_id="late", base_revision=2, expected_buffer_revision=1)
        )


@pytest.mark.parametrize(
    "payload", [{"password": "secret"}, {"choice": True}, {"text": "x" * 32001}]
)
def test_buffer_shape_is_strict_and_bounded(payload):
    with pytest.raises(ModelError):
        InterviewEditorBuffer.model_validate(payload)


def test_profile_database_isolation(desk, tmp_path):
    ledger, _ = desk
    save_buffer(ledger, edit())
    other = ForecastLedger(tmp_path / "other.db")
    InterviewService(other).begin("draft")
    assert read_buffers(other, "draft") == {"buffers": []}


def test_additive_schema_upgrade_preserves_confirmed_interviews(desk):
    ledger, service = desk
    original = service.store.read("draft")
    with ledger._connect() as conn:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
        conn.execute("DROP TABLE forecast_interview_buffer_receipts")
        conn.execute("DROP TABLE forecast_interview_buffers")
    upgraded = ForecastLedger(path)
    assert InterviewService(upgraded).store.read("draft") == original
    assert save_buffer(upgraded, edit())["buffer_revision"] == 1
