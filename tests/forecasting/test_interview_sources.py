"""Source handoffs preserve identity, unknown times and explicit commit boundaries."""

import pytest
from pydantic import ValidationError as ModelError

from forecasting.interviews.news import attach_article
from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger, allow_ledger_writes
from forecasting.models import ValidationError
from protocol.interviews import ForecastArticleClaim, ForecastMarketSeed, InterviewDraft


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "desk.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Will annual CPI exceed 3 percent in June 2030?",
            resolution_criteria="Resolves yes if the BLS first release for June 2030 reports annual CPI above 3 percent.",
        )
    return ledger, question


def article(**changes):
    return ForecastArticleClaim.model_validate({
        "title": "Inflation report",
        "url": "https://example.org/news?id=1&utm_source=feed#headline",
        "feed_url": "https://example.org/rss",
        "publisher": "Example",
        "content": "The report describes price changes.",
        "extraction": "feed",
        **changes,
    })


def test_article_retry_then_update_preserves_one_evidence_item(desk):
    ledger, question = desk
    first = attach_article(ledger, question.id, article())
    second = attach_article(
        ledger,
        question.id,
        article(url="https://example.org/news?id=1"),
        prepare_update=True,
    )
    again = attach_article(ledger, question.id, article(), prepare_update=True)
    assert first["evidence_id"] == second["evidence_id"] == again["evidence_id"]
    assert first["interview_id"] is None
    assert second["interview_id"] == again["interview_id"]
    evidence = ledger.get_evidence(first["evidence_id"])
    assert evidence.published_at is None
    assert evidence.available_at is not None
    assert evidence.captured_at is not None
    assert evidence.admissible_for_backtests is False
    assert evidence.metadata["publication_time_status"] == "unknown"
    draft = InterviewService(ledger).store.read(second["interview_id"])["document"]
    assert draft["evidence_refs"] == [first["evidence_id"]]
    assert draft["status"] == "needs_research"
    assert ledger.get_question(question.id).current_forecast_id is None
    assert len(ledger.list_evidence(question.id)) == 1


def test_changed_article_is_a_revision_not_independent_corroboration(desk):
    ledger, question = desk
    first = attach_article(ledger, question.id, article())
    second = attach_article(
        ledger,
        question.id,
        article(content="Corrected report: earlier figures were revised."),
    )
    assert first["evidence_id"] != second["evidence_id"]
    old, new = (
        ledger.get_evidence(first["evidence_id"]),
        ledger.get_evidence(second["evidence_id"]),
    )
    assert old.metadata["independence_key"] == new.metadata["independence_key"]
    assert old.metadata["content_sha256"] != new.metadata["content_sha256"]


def test_failed_interview_creation_rolls_back_attachment(desk, monkeypatch):
    ledger, question = desk

    def fail(*args, **kwargs):
        raise RuntimeError("interrupted interview")

    with monkeypatch.context() as patch:
        patch.setattr(InterviewService, "begin", fail)
        with pytest.raises(RuntimeError, match="interrupted"):
            attach_article(ledger, question.id, article(), prepare_update=True)
    assert ledger.list_evidence(question.id) == []
    assert attach_article(ledger, question.id, article(), prepare_update=True)[
        "interview_id"
    ]


def test_future_publication_time_is_not_backdated(desk):
    ledger, question = desk
    with pytest.raises(ValidationError, match="future"):
        attach_article(
            ledger, question.id, article(published_at="2099-01-01T00:00:00Z")
        )
    assert ledger.list_evidence(question.id) == []


@pytest.mark.parametrize(
    "bad",
    [
        {"url": "file:///tmp/private"},
        {"url": "https://user:secret@example.org/x"},
        {"published_at": "2030-01-01"},
    ],
)
def test_source_claim_validation(bad):
    with pytest.raises(ModelError):
        article(**bad)


def test_market_seed_retains_selected_outcome_without_seeding_belief(desk):
    ledger, _ = desk
    seed = ForecastMarketSeed(
        kind="prediction_market",
        provider="kalshi",
        symbol="outcome-b",
        event_id="event",
        outcome_id="outcome-b",
        title="Will B happen?",
        market_price=0.2,
        captured_at="2026-09-18T00:00:00Z",
    )
    service = InterviewService(ledger)
    record = service.begin("selected", seed=seed)
    assert record["document"]["seed"]["outcome_id"] == "outcome-b"
    assert record["document"]["answers"] == []
    revised = InterviewDraft.model_validate(record["document"])
    revised.seed.outcome_id = "outcome-a"
    revised.seed.symbol = "outcome-a"
    with pytest.raises(ValidationError, match="immutable"):
        service.store.save(
            "selected", revised, expected_revision=1, request_id="change", actor="user"
        )


def test_numeric_series_seed_keeps_sparse_observation_metadata(desk):
    ledger, _ = desk
    seed = ForecastMarketSeed(
        kind="series",
        provider="bcb",
        symbol="433",
        title="Brazil IPCA",
        units="percent",
        captured_at="2026-09-18T00:00:00Z",
        observed_value=0.0,
        period_start="2026-08-01",
        period_end="2026-08-31",
    )
    document = InterviewService(ledger).begin("series", seed=seed)["document"]
    assert document["seed"]["observed_value"] == 0.0
    assert document["seed"]["published_at"] is None
    assert "quantile_50" in {q["id"] for q in document["questions"]}


@pytest.mark.parametrize(
    "period",
    [
        {"period_start": "2030-01-01"},
        {"period_start": "2030-02-30", "period_end": "2030-03-01"},
        {"period_start": "2030-02-01", "period_end": "2030-01-01"},
    ],
)
def test_seed_rejects_ambiguous_observation_periods(period):
    with pytest.raises(ModelError):
        ForecastMarketSeed(
            kind="series",
            provider="fred",
            symbol="CPI",
            title="CPI",
            captured_at="2026-09-18T00:00:00Z",
            **period,
        )
