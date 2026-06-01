from __future__ import annotations

import json

import pytest

from forecasting import ForecastLedger
from forecasting.dashboard import build_workspace_payload
from forecasting.models import LedgerNotFoundError, ValidationError


def _question_with_snapshot(ledger: ForecastLedger):
    question = ledger.create_question(
        title="Will the Republican win the Texas Senate seat?",
        resolution_criteria="Resolves to the certified winner's party.",
        close_time="2026-11-03T00:00:00Z",
        domain="politics",
    )
    snapshot = ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.59,
        rationale="Fundamentals favor the Republican.",
        as_of="2026-06-01T00:00:00Z",
        confidence=0.66,
    )
    return question, snapshot


def test_add_and_get_analyst_note_round_trip(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, snapshot = _question_with_snapshot(ledger)

    note = ledger.add_analyst_note(
        question_id=question.id,
        kind="brief",
        body="Comfortable.\n\nFundamentals.",
        headline="Lean Republican",
        how_it_feels="Comfortable.",
        how_it_thinks="Fundamentals.",
        looking_for="Polls.",
        be_aware="Early.",
        stance="lean_yes",
        forecast_id=snapshot.forecast_id,
        as_of=snapshot.as_of,
        probability_at_write=0.59,
        confidence_at_write=0.66,
    )
    assert note["id"].startswith("an_")
    assert note["kind"] == "brief"
    assert note["headline"] == "Lean Republican"
    assert note["forecast_id"] == snapshot.forecast_id
    assert note["metadata"]["probability_at_write"] == 0.59

    fetched = ledger.get_analyst_note(note["id"])
    assert fetched["body"] == "Comfortable.\n\nFundamentals."
    assert fetched["stance"] == "lean_yes"


def test_analyst_note_validation(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, _ = _question_with_snapshot(ledger)

    with pytest.raises(ValidationError):
        ledger.add_analyst_note(question_id=question.id, body="x", kind="memo")
    with pytest.raises(ValidationError):
        ledger.add_analyst_note(question_id=question.id, body="   ")
    with pytest.raises(ValidationError):
        ledger.add_analyst_note(question_id=question.id, body="x", kind="retrospective", verdict="meh")
    with pytest.raises(ValidationError):
        ledger.add_analyst_note(question_id=question.id, body="x", stance="strong_yes")


def test_get_missing_analyst_note_raises(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    with pytest.raises(LedgerNotFoundError):
        ledger.get_analyst_note("an_does_not_exist")


def test_list_is_ascending_and_latest_is_descending(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, snapshot = _question_with_snapshot(ledger)

    first = ledger.add_analyst_note(question_id=question.id, body="first", headline="first")
    second = ledger.add_analyst_note(question_id=question.id, body="second", headline="second")
    retro = ledger.add_analyst_note(
        question_id=question.id, kind="retrospective", body="retro", headline="retro", verdict="close"
    )

    notes = ledger.list_analyst_notes(question.id)
    assert [n["id"] for n in notes] == [first["id"], second["id"], retro["id"]]

    briefs = ledger.list_analyst_notes(question.id, kind="brief")
    assert [n["id"] for n in briefs] == [first["id"], second["id"]]

    assert ledger.latest_analyst_note(question.id)["id"] == retro["id"]
    assert ledger.latest_analyst_note(question.id, kind="brief")["id"] == second["id"]
    assert ledger.latest_analyst_note(question.id, kind="retrospective")["id"] == retro["id"]


def test_add_note_with_unknown_forecast_id_raises(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, _ = _question_with_snapshot(ledger)
    with pytest.raises(LedgerNotFoundError):
        ledger.add_analyst_note(question_id=question.id, body="x", forecast_id="fc_nope")


def test_notes_survive_export_import_round_trip(tmp_path):
    # Guards the packet round-trip path: notes that are exported must re-import,
    # which only works if analyst_notes is wired into the import loop + labels.
    source = ForecastLedger(tmp_path / "source.db")
    question, snapshot = _question_with_snapshot(source)
    source.add_analyst_note(
        question_id=question.id,
        body="brief body",
        headline="brief headline",
        forecast_id=snapshot.forecast_id,
        stance="lean_yes",
        probability_at_write=0.59,
    )

    packet = json.loads(source.export_question(question.id, fmt="json"))
    assert packet["analyst_note"]["headline"] == "brief headline"
    assert len(packet["analyst_notes"]) == 1

    target = ForecastLedger(tmp_path / "target.db")
    target.import_packet(packet)

    imported = target.list_analyst_notes(question.id)
    assert len(imported) == 1
    assert imported[0]["headline"] == "brief headline"
    assert imported[0]["metadata"]["probability_at_write"] == 0.59


def test_workspace_payload_exposes_analyst_notes(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, snapshot = _question_with_snapshot(ledger)
    ledger.add_analyst_note(
        question_id=question.id,
        body="latest body",
        headline="latest headline",
        forecast_id=snapshot.forecast_id,
        stance="lean_yes",
    )

    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["analyst_note"]["headline"] == "latest headline"
    assert forecast["analyst_note"]["stance"] == "lean_yes"
    assert len(forecast["analyst_notes"]) == 1
    assert forecast["retrospective"] is None


def test_workspace_payload_surfaces_retrospective(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecasting.db")
    question, snapshot = _question_with_snapshot(ledger)
    ledger.add_analyst_note(question_id=question.id, body="brief", headline="brief", forecast_id=snapshot.forecast_id)
    ledger.add_analyst_note(
        question_id=question.id, kind="retrospective", body="retro", headline="retro headline", verdict="close"
    )

    forecast = build_workspace_payload(ledger=ledger)["forecasts"][0]
    assert forecast["retrospective"]["headline"] == "retro headline"
    assert forecast["retrospective"]["verdict"] == "close"
    # The latest note overall is the retrospective.
    assert forecast["analyst_note"]["kind"] == "retrospective"
