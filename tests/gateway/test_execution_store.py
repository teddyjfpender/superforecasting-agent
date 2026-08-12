import sqlite3

import pytest

from gateway.execution_store import ExecutionStore


def test_run_status_and_events_survive_reopen(tmp_path):
    path = tmp_path / "executions.db"
    store = ExecutionStore(path)
    store.create_run(
        "run_1",
        thread_key="slack:T:C:1",
        session_id="session-1",
        data={"object": "hermes.run", "status": "queued"},
    )
    first = store.append_event("run_1", {"event": "execution.queued"})
    store.update_run("run_1", "completed", output="done")

    reopened = ExecutionStore(path)
    assert reopened.get_run("run_1")["output"] == "done"
    assert reopened.list_events("run_1", after_event_id=0) == [first]
    assert reopened.list_events("run_1", after_event_id=first["event_id"]) == []


def test_close_releases_connection(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.close()

    with pytest.raises(sqlite3.ProgrammingError):
        store.get_run("run_1")


def test_only_one_active_execution_per_thread(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.create_run(
        "run_1",
        thread_key="slack:T:C:1",
        session_id="session-1",
        data={"status": "running"},
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_run(
            "run_2",
            thread_key="slack:T:C:1",
            session_id="session-1",
            data={"status": "queued"},
        )
    store.update_run("run_1", "completed")
    store.create_run(
        "run_2",
        thread_key="slack:T:C:1",
        session_id="session-1",
        data={"status": "queued"},
    )


def test_run_and_initial_message_commit_atomically(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.create_run(
        "run_1", thread_key="thread", session_id="session",
        data={"status": "running"},
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_run(
            "run_2", thread_key="thread", session_id="session",
            data={"status": "queued"},
            initial_message={"message_id": "message-2", "parts": "must roll back"},
        )
    assert store.list_messages("thread") == []


def test_duplicate_initial_message_does_not_create_execution(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    message = {
        "message_id": "message-1", "client_message_id": "client-1", "parts": "hello",
    }
    store.create_run(
        "run_1", thread_key="thread", session_id="session",
        data={"status": "completed"}, initial_message=message,
    )
    assert store.create_run(
        "run_2", thread_key="thread", session_id="session",
        data={"status": "queued"}, initial_message={**message, "message_id": "message-2"},
    ) is None
    assert store.get_run("run_2") is None


def test_idempotency_key_is_unique_per_thread(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.create_run(
        "run_1",
        thread_key="api:thread",
        session_id="session",
        idempotency_key="message-1",
        data={"status": "completed"},
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.create_run(
            "run_2",
            thread_key="api:thread",
            session_id="session",
            idempotency_key="message-1",
            data={"status": "queued"},
        )


def test_inbound_message_redelivery_is_idempotent(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    kwargs = {
        "message_id": "slack:T:Ev1",
        "thread_key": "slack:T:C:1",
        "client_message_id": "Ev1",
        "role": "user",
        "parts": {"text": "hello"},
        "platform": "slack",
    }
    assert store.append_message(**kwargs) is True
    assert store.append_message(**kwargs) is False
    assert [message["parts"] for message in store.list_messages("slack:T:C:1")] == [
        {"text": "hello"}
    ]


def test_delivery_lease_and_renderer_checkpoint_survive_restart(tmp_path):
    path = tmp_path / "executions.db"
    store = ExecutionStore(path)
    store.create_run(
        "run_1", thread_key="slack:T:C:1", session_id="s1",
        data={"status": "queued"},
    )
    store.create_delivery(
        "delivery_1", run_id="run_1", platform="slack", destination="C:1",
    )

    claim = store.claim_delivery(platform="slack", owner="renderer-a")
    assert claim["obligation_id"] == "delivery_1"
    assert store.claim_delivery(platform="slack", owner="renderer-b") is None
    assert store.checkpoint_delivery(
        "delivery_1", owner="renderer-a", last_event_id=7,
        renderer_state={"progress_ts": "123.4"}, state="completed",
    )

    reopened = ExecutionStore(path)
    assert reopened.claim_delivery(platform="slack", owner="renderer-b") is None


def test_restart_terminalizes_active_runs_and_unblocks_thread(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.create_run(
        "run_1", thread_key="slack:T:C:1", session_id="s1",
        data={"status": "running"},
    )

    assert store.fail_active_runs() == ["run_1"]
    assert store.get_run("run_1")["error"] == "control_plane_restarted"
    assert store.list_events("run_1")[-1]["event"] == "run.failed"
    store.create_run(
        "run_2", thread_key="slack:T:C:1", session_id="s1",
        data={"status": "queued"},
    )


def test_terminal_run_cannot_be_resurrected(tmp_path):
    store = ExecutionStore(tmp_path / "executions.db")
    store.create_run(
        "run_1", thread_key="thread", session_id="session",
        data={"status": "completed", "output": "done"},
    )
    result = store.update_run("run_1", "running", output="late callback")
    assert result["status"] == "completed"
    assert result["output"] == "done"
