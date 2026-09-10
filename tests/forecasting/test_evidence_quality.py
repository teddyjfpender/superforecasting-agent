"""Adversarial provenance checks without deleting original evidence records."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS

import pytest

from forecasting.evidence_quality import observation_identity, source_identity
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.research_audit import deterministic_research_checks


def _item(url, **kw):
    return NS(source_url=url, source_name="Article title", source_type="url", claim="same observation",
              summary="", available_at="2026-09-10T10:00:00Z", published_at="2026-09-10T10:00:00Z", **kw)


def test_article_names_and_tracking_do_not_create_independence():
    first = _item("https://www.usgs.gov/report?utm_source=newsletter#top")
    second = _item("https://usgs.gov/report?utm_source=social")
    assert source_identity(first) == source_identity(second) == "usgs.gov"
    assert observation_identity(first) == observation_identity(second)
    assert observation_identity(first) != observation_identity(_item("https://usgs.gov/report?version=2"))


def test_syndication_uses_declared_original_source():
    original = _item("https://usgs.gov/report")
    mirror = _item("https://news.example/story", metadata={"original_source_url": original.source_url})
    assert source_identity(mirror) == source_identity(original)
    assert observation_identity(mirror) == observation_identity(original)
    assert source_identity(_item("https://a.example/x", metadata={"independence_group": "Shared Wire"})) == "shared wire"


def test_copies_and_future_observations_fail_research_gates():
    items = [_item(f"https://usgs.gov/report?utm_source={i}") for i in range(3)]
    for item in items:
        item.available_at = "2027-01-01T00:00:00Z"
    checks = deterministic_research_checks(
        question=NS(title="Will the event occur?", update_triggers=[]), evidence=items,
        reference_classes=[], watched_sources=[], reasons_down=[], evidence_refs=[],
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )["checks"]
    assert not checks["source_independence"]
    assert not checks["evidence_floor"]
    assert not checks["recency"]


def test_publication_chronology_and_timezone_normalization(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(title="Will the event occur by the deadline?",
        resolution_criteria="Yes if the named event occurs before 2027-01-01 UTC; no otherwise.",
        outcome_space=OutcomeSpace(type="binary"))
    with pytest.raises(ValidationError, match="cannot precede"):
        ledger.add_evidence(question_id=question.id, source_or_note="observation",
            published_at="2026-09-10T12:00:00+04:00", available_at="2026-09-10T07:00:00Z")
    assert ledger.list_evidence(question.id) == []
    item = ledger.add_evidence(question_id=question.id, source_or_note="observation",
        published_at="2026-09-10T12:00:00+04:00", available_at="2026-09-10T08:00:00Z")
    assert item.published_at == item.available_at == "2026-09-10T08:00:00Z"
