"""Publication provenance must survive the shared tool and watched-source boundary."""

import json
from dataclasses import asdict

import pytest

from forecasting.application.source_imports import (
    FredImportRequest,
    import_fred_evidence,
)
from forecasting.ledger import ForecastLedger
from forecasting.sources.economic_records import FredObservation
from forecasting.sources.evidence import source_evidence_payload
from forecasting.sources.requests import CommonSourceOptions
from forecasting.sources.watched import fetch_watched_source_payloads


@pytest.fixture
def reading():
    return FredObservation(
        series_id="UNRATE",
        observation_date="2020-01-01",
        value=3.6,
        published_at=None,
        source_url=None,
        source_name="FRED",
        entry_id="UNRATE:2020-01-01",
        raw={"value": "3.6"},
    )


@pytest.mark.parametrize(
    "adapter", ["fred", "bls", "eia", "treasury", "worldbank", "owid", "yahoo"]
)
def test_explicit_unknown_publication_never_falls_back_to_other_dates(adapter, reading):
    data = {
        **asdict(reading),
        "updated_at": "2020-02-01",
        "forecast_time": "2020-03-01",
    }
    payload = source_evidence_payload(adapter, "source", data, {})
    assert payload["published_at"] is None
    assert payload["available_at"] is None
    assert payload["metadata"]["adapter_item"] == data


@pytest.mark.parametrize(
    "field",
    [
        "time",
        "observation_date",
        "observation_time",
        "forecast_date",
        "forecast_time",
        "due_date",
        "run_started_at",
        "date_argued",
        "last_refresh",
        "latest_geometry_at",
    ],
)
def test_unclassified_event_dates_cannot_become_publication(field):
    payload = source_evidence_payload("source", "identity", {field: "2020-01-01"}, {})
    assert payload["published_at"] is None
    assert payload["available_at"] is None


def test_explicit_publication_and_caller_availability_remain_distinct(reading):
    data = {**asdict(reading), "published_at": "2020-02-03T12:00:00Z"}
    payload = source_evidence_payload(
        "fred", "UNRATE", data, {"available_at": "2020-02-04T12:00:00Z"}
    )
    assert payload["published_at"] == data["published_at"]
    assert payload["available_at"] == "2020-02-04T12:00:00Z"


def test_cli_owner_tool_and_watch_preserve_unknown_publication(
    tmp_path, monkeypatch, reading
):
    from forecasting.sources import watched
    from tools import forecasting_tool
    from tools.forecast_actions.evidence import import_source_evidence

    ledger = ForecastLedger(tmp_path / "desk.db")
    question = ledger.create_question(
        title="Publication provenance",
        resolution_criteria="Resolves yes if the official release confirms the observation.",
    )
    monkeypatch.setattr(
        forecasting_tool, "_load_source_adapter_items", lambda *a: [reading]
    )
    tool = json.loads(
        import_source_evidence(
            {"question_id": question.id, "source_type": "fred", "source": "UNRATE"},
            ledger,
        )
    )
    assert tool["success"]
    imported = tool["imported"][0]["evidence"]
    assert imported["published_at"] is None
    assert not imported["available_at"].startswith("2020-01-01")
    monkeypatch.setattr(watched, "load_source_items", lambda *a: [reading])
    result = fetch_watched_source_payloads([
        {"source_type": "fred", "source": "UNRATE"}
    ])[0]
    assert result["success"]
    assert result["payloads"][0]["published_at"] is None
    assert result["payloads"][0]["available_at"] is None
    cli = import_fred_evidence(
        ledger,
        FredImportRequest(
            source="UNRATE", question_id=question.id, options=CommonSourceOptions()
        ),
        fetch=lambda *a, **kw: [reading],
    )
    assert cli[0].published_at is None
    assert not cli[0].available_at.startswith("2020-01-01")
