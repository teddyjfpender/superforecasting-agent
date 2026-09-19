"""Shared imports preserve admission and atomic ledger behavior across consumers."""

from dataclasses import replace

import pytest

from forecasting.application.source_imports import (
    FredImportRequest,
    import_fred_evidence,
)
from forecasting.ledger import ForecastLedger
from forecasting.sources.economic_records import FredObservation
from forecasting.sources.requests import CommonSourceOptions


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "forecast.db")
    question = ledger.create_question(
        title="Evidence import",
        resolution_criteria="Resolved yes if FRED evidence is imported.",
    )
    request = FredImportRequest(
        source="UNRATE",
        question_id=question.id,
        options=CommonSourceOptions(),
        as_of="2026-09-01T00:00:00Z",
    )
    return ledger, request


def row(**changes):
    return replace(
        FredObservation(
            "UNRATE",
            "2026-01-01",
            4.2,
            None,
            None,
            "FRED",
            "UNRATE:2026-01-01",
            {"value": "4.2"},
        ),
        **changes,
    )


def test_identical_rows_collapse_without_fabricating_publication(desk):
    ledger, request = desk
    evidence = import_fred_evidence(
        ledger, request, fetch=lambda *a, **kw: [row(), row()]
    )
    assert len(evidence) == 1
    assert evidence[0].published_at is None
    assert evidence[0].available_at == request.as_of
    assert ledger.get_question(request.question_id).current_forecast_id is None


@pytest.mark.parametrize(
    "invalid",
    [
        row(series_id="CPIAUCSL"),
        row(value=float("nan")),
        row(value="4.2"),
        row(value=True),
        row(value=4.3),
    ],
)
def test_invalid_or_conflicting_batch_writes_nothing(desk, invalid):
    ledger, request = desk
    with pytest.raises(ValueError):
        import_fred_evidence(ledger, request, fetch=lambda *a, **kw: [row(), invalid])
    assert ledger.list_evidence(request.question_id) == []


def test_mid_batch_storage_failure_rolls_back_every_row(desk, monkeypatch):
    ledger, request = desk
    add = ledger.add_evidence
    calls = 0

    def interrupted(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("storage interrupted")
        return add(**kwargs)

    monkeypatch.setattr(ledger, "add_evidence", interrupted)
    rows = [row(), row(entry_id="UNRATE:2026-02-01", observation_date="2026-02-01")]
    with pytest.raises(RuntimeError, match="storage interrupted"):
        import_fred_evidence(ledger, request, fetch=lambda *a, **kw: rows)
    assert ledger.list_evidence(request.question_id) == []
    monkeypatch.setattr(ledger, "add_evidence", add)
    assert len(import_fred_evidence(ledger, request, fetch=lambda *a, **kw: rows)) == 2


def test_fetch_uses_provider_defaults_outside_write_transaction(desk):
    ledger, request = desk

    def fetch(source, *, limit, since):
        assert ledger._transaction_connection.get() is None
        assert source == "UNRATE"
        assert limit == 10 and since is None
        return [row()]

    assert len(import_fred_evidence(ledger, request, fetch=fetch)) == 1
