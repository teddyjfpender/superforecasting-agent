"""Summary RPC uses the command query and counts the entire durable history."""

from unittest.mock import Mock

import pytest

from superforecasting_agent.storage.session import SessionDB
from tui_gateway import server


def summary(params):
    return server.handle_request({"id": 1, "method": "insights.get", "params": params})


@pytest.mark.parametrize("params", [
    {"days": True}, {"days": 0}, {"days": -1}, {"days": "30"},
    {"days": 1.5}, {"days": None}, {"source": " "}, {"source": 5},
])
def test_invalid_query_does_not_acquire_storage(monkeypatch, params):
    acquire = Mock(side_effect=AssertionError("invalid input reached storage"))
    monkeypatch.setattr(server, "_get_db", acquire)
    assert summary(params)["error"]["code"] == 4004
    acquire.assert_not_called()


def test_complete_history_and_source_filter(monkeypatch, tmp_path):
    db = SessionDB(tmp_path / "sessions.db")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    try:
        assert summary({})["result"] == {"days": 30, "sessions": 0, "messages": 0}
        for index in range(505):
            sid = str(index)
            db.create_session(sid, "cli" if index < 503 else "tui")
            db.append_message(sid, "user", "A question")
        assert summary({})["result"] == {"days": 30, "sessions": 505, "messages": 505}
        assert summary({"source": "tui"})["result"] == {"days": 30, "sessions": 2, "messages": 2}
        # A successful inspection borrows the host store, never closes it.
        db.create_session("after-inspection", "cli")
    finally:
        db.close()


def test_report_failure_keeps_host_store_open(monkeypatch, tmp_path):
    db = SessionDB(tmp_path / "sessions.db")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr("agent.insights.InsightsEngine.generate", Mock(side_effect=RuntimeError("report failed")))
    try:
        assert summary({})["error"]["code"] == 5017
        db.create_session("after-failure", "cli")
    finally:
        db.close()
