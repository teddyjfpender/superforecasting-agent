"""The watched_sources write gate + the bulk add_watched_sources tool action.

The observed bypass: the desk agent, asked to watch a 35-race thesis, wrote a
script raw-INSERTing into watched_sources (245 single tool calls was the only
alternative). The fix pair: (1) watched_sources joins GATED_LEDGER_TABLES so
raw SQL is refused with a teaching error; (2) add_watched_sources gives the
legitimate path the same one-shot ergonomics the script had.
"""

from __future__ import annotations

import sqlite3

import pytest

from forecasting.ledger import ForecastLedger


@pytest.fixture()
def ledger(tmp_path):
    led = ForecastLedger(tmp_path / "test.db")
    from forecasting.ledger import allow_ledger_writes

    with allow_ledger_writes("test seed"):
        led.create_question(
            title="Will X happen?",
            resolution_criteria="Resolves YES if the official X registry reports the event by 2026-12-31; otherwise NO.",
            close_time="2027-01-01T00:00:00Z",
        )
    return led


def _qid(led):
    return led.list_questions()[0].id


def test_raw_insert_into_watched_sources_is_refused(ledger, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "on")
    qid = _qid(ledger)
    with ledger._connect() as conn, pytest.raises(sqlite3.DatabaseError):
        conn.execute(
            "INSERT INTO watched_sources (id, scope_type, scope_ref, source, source_type,"
            " created_at, last_checked_at, last_seen_signature, status, metadata, role)"
            " VALUES ('ws_raw', 'question', ?, 'https://x.test/feed', 'url',"
            " '2026-07-03T00:00:00Z', NULL, NULL, 'active', '{}', NULL)",
            (qid,),
        )


def test_method_path_still_works(ledger):
    qid = _qid(ledger)
    watch = ledger.add_watched_source(
        scope_type="question", scope_ref=qid, source="https://x.test/feed"
    )
    assert watch["id"].startswith("ws_")
    assert len(ledger.list_watched_sources(scope_type="question", scope_ref=qid)) == 1


def test_bulk_action_adds_and_isolates_failures(ledger, monkeypatch):
    from tools import forecasting_tool as ft

    qid = _qid(ledger)
    import json

    result = json.loads(ft.forecast_ledger_tool({
        "action": "add_watched_sources",
        "db": str(ledger.db_path),
        "watches": [
            {"question_id": qid, "source": "https://a.test/feed"},
            {"question_id": qid, "source": ""},  # invalid: empty source
            {"question_id": qid, "source": "https://b.test/feed"},
        ],
    }))
    assert result["added"] == 2 and result["failed"] == 1
    rows = result["results"]
    assert rows[0]["success"] and rows[2]["success"] and not rows[1]["success"]
    assert "error" in rows[1]
    assert len(ledger.list_watched_sources(scope_type="question", scope_ref=qid)) == 2


def test_bulk_action_refuses_empty_and_oversized(ledger):
    from tools import forecasting_tool as ft

    import json

    for bad in ([], [{"question_id": "x", "source": "s"}] * 401):
        result = json.loads(ft.forecast_ledger_tool({
            "action": "add_watched_sources", "db": str(ledger.db_path), "watches": bad,
        }))
        assert not result.get("success", True) or "error" in result
