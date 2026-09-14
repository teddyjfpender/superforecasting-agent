"""Durable background outcomes, group barriers and transactional notifications."""

import pytest

from superforecasting_agent.storage.background_research import BackgroundResearchJournal


def test_independent_results_arrive_before_group_and_survive_reopen(tmp_path):
    journal = BackgroundResearchJournal(tmp_path)
    ids = journal.admit([
        {"goal": "independent"},
        {"goal": "first", "delivery_group": "economics"},
        {"goal": "second", "delivery_group": "economics"},
    ], session="one", owner="worker")
    for task in ids:
        journal.start(task, "worker")
    journal.finish(ids[1], "worker", "completed", {"summary": "first"})
    assert not journal.pending("one")
    journal.finish(ids[0], "worker", "completed", {"summary": "early"})
    resumed = BackgroundResearchJournal(tmp_path)
    early = resumed.pending("one")
    assert len(early) == 1 and early[0]["tasks"][0]["delegation_id"] == ids[0]
    assert not resumed.pending("another-session")
    resumed.acknowledge(early[0]["event_id"], "one")
    resumed.acknowledge(early[0]["event_id"], "one")
    journal.finish(ids[2], "worker", "completed", {"summary": "second"})
    grouped = resumed.pending("one")
    assert len(grouped) == 1 and grouped[0]["kind"] == "group_complete"
    assert [task["delegation_id"] for task in grouped[0]["tasks"]] == ids[1:]


def test_group_failure_is_visible_before_barrier_and_retry_is_idempotent(tmp_path):
    journal = BackgroundResearchJournal(tmp_path)
    first, second = journal.admit([
        {"goal": "fails", "delivery_group": "g"},
        {"goal": "slower", "delivery_group": "g"},
    ], session="s", owner="o")
    journal.start(first, "o")
    journal.start(second, "o")
    journal.finish(first, "o", "error", {"error": "provider unavailable"})
    journal.finish(first, "o", "error", {"error": "provider unavailable"})
    events = journal.pending("s")
    assert len(events) == 1 and events[0]["kind"] == "member_failure"
    with pytest.raises(ValueError, match="Conflicting"):
        journal.finish(first, "o", "completed", {"summary": "invented"})
    journal.finish(second, "o", "interrupted", {"error": "cancelled"})
    events = journal.pending("s")
    assert [event["kind"] for event in events].count("group_complete") == 1
    assert journal.tasks("s")[0]["status"] in {"error", "interrupted"}


def test_completion_and_notification_commit_together(tmp_path, monkeypatch):
    journal = BackgroundResearchJournal(tmp_path)
    task = journal.admit([{"goal": "research"}], session="s", owner="o")[0]
    journal.start(task, "o")
    def fail(*args):
        raise OSError("event storage unavailable")
    with monkeypatch.context() as scoped:
        scoped.setattr(journal, "_event", fail)
        with pytest.raises(OSError):
            journal.finish(task, "o", "completed", {"summary": "done"})
    assert journal.tasks("s")[0]["status"] == "running"
    assert not journal.pending("s")
    journal.finish(task, "o", "completed", {"summary": "done"})
    assert journal.tasks("s")[0]["status"] == "completed"
    assert len(journal.pending("s")) == 1


def test_admission_and_outcome_ownership_fail_closed(tmp_path):
    journal = BackgroundResearchJournal(tmp_path)
    with pytest.raises(ValueError):
        journal.admit([{"goal": "valid"}, {"goal": ""}], session="s", owner="o")
    assert journal.tasks("s") == []
    task = journal.admit([{"goal": "valid"}], session="s", owner="o")[0]
    with pytest.raises(ValueError):
        journal.start(task, "replacement")
    with pytest.raises(ValueError, match="Unstarted"):
        journal.finish(task, "o", "completed", {})
    journal.start(task, "o")
    with pytest.raises(ValueError):
        journal.start(task, "o")
    with pytest.raises(ValueError, match="owner mismatch"):
        journal.finish(task, "replacement", "completed", {})
    journal.finish(task, "o", "completed", {})
    event = journal.pending("s")[0]
    with pytest.raises(ValueError):
        journal.acknowledge(event["event_id"], "replacement-session")
    assert journal.pending("s")


def test_recovery_after_real_owner_exit_preserves_uncertainty_and_never_reexecutes(tmp_path):
    import os
    import subprocess
    import sys
    import json

    source = '''
import json, sys
from pathlib import Path
from superforecasting_agent.storage.background_research import BackgroundResearchJournal
journal = BackgroundResearchJournal(Path(sys.argv[1]))
task = journal.admit([{"goal": "interrupted research"}], session="session", owner="child-owner")[0]
journal.start(task, "child-owner")
print(json.dumps(task), flush=True)
'''
    completed = subprocess.run([sys.executable, "-c", source, str(tmp_path)],
                               cwd=os.getcwd(), capture_output=True, text=True, timeout=10, check=True)
    task = json.loads(completed.stdout)
    journal = BackgroundResearchJournal(tmp_path)
    assert journal.recover("session") == 1
    assert journal.recover("session") == 0
    row = journal.tasks("session")[0]
    assert row["delegation_id"] == task and row["status"] == "interrupted"
    assert row["result"]["automatic_retry"] is False
    assert len(journal.pending("session")) == 1


def test_recovery_does_not_steal_live_or_unknown_owners(tmp_path, monkeypatch):
    import superforecasting_agent.storage.background_research as storage
    journal = BackgroundResearchJournal(tmp_path)
    task = journal.admit([{"goal": "still alive"}], session="s", owner="live")[0]
    journal.start(task, "live")
    assert journal.recover("s") == 0
    monkeypatch.setattr(storage, "_host_identity", lambda: "different-machine")
    assert journal.recover("s") == 0
    assert journal.tasks("s")[0]["status"] == "running"


def test_reused_pid_cannot_keep_old_owner_running(tmp_path, monkeypatch):
    from superforecasting_agent.storage import turns
    journal = BackgroundResearchJournal(tmp_path)
    task = journal.admit([{"goal": "old owner"}], session="s", owner="old")[0]
    journal.start(task, "old")
    original = turns._process_started
    monkeypatch.setattr(turns, "_process_started", lambda pid: original(pid) + 1)
    assert journal.recover("s") == 1
    assert journal.tasks("s")[0]["status"] == "interrupted"
