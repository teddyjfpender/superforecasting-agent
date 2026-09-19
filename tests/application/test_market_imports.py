"""Evidence and prediction-market baselines must share an atomic boundary."""

from dataclasses import replace

import pytest

from forecasting.application.market_imports import (
    MarketEvidenceRequest,
    import_market_evidence,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import OutcomeSpace, ValidationError
from forecasting.sources.market_records import (
    KalshiMarketImport,
    PolymarketMarketImport,
)


@pytest.fixture
def desk(tmp_path):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will a baseline attach?",
        resolution_criteria="Resolved yes if a market baseline attaches.",
    )
    return ledger, MarketEvidenceRequest(
        question_id=question.id, source="source-id", as_of="2026-09-01T00:00:00Z"
    )


def market(provider):
    if provider == "kalshi":
        return KalshiMarketImport(
            "KXTEST",
            "KX",
            "Question?",
            "Rules",
            None,
            OutcomeSpace(),
            0.4,
            None,
            None,
            "active",
            None,
            None,
            {},
        )
    return PolymarketMarketImport(
        "123",
        "question",
        "Question?",
        "Rules",
        None,
        OutcomeSpace(),
        0.4,
        None,
        None,
        None,
        None,
        {},
    )


@pytest.mark.parametrize("provider", ["kalshi", "polymarket"])
def test_import_preserves_evidence_without_promoting_a_forecast(desk, provider):
    ledger, request = desk
    result = import_market_evidence(ledger, request, market(provider))
    assert result.evidence.source_type == f"adapter:{provider}"
    assert result.evidence.published_at is None
    assert result.comparison["probability_or_distribution"] == 0.4
    assert ledger.get_question(request.question_id).current_forecast_id is None


@pytest.mark.parametrize("provider", ["kalshi", "polymarket"])
def test_invalid_probability_rolls_back_evidence(desk, provider):
    ledger, request = desk
    with pytest.raises(ValidationError, match="between 0 and 1"):
        import_market_evidence(
            ledger, request, replace(market(provider), probability=2.0)
        )
    assert ledger.list_evidence(request.question_id) == []
    assert ledger.list_baseline_comparisons(request.question_id) == []


@pytest.mark.parametrize("provider", ["kalshi", "polymarket"])
def test_comparison_storage_failure_rolls_back_evidence(desk, provider, monkeypatch):
    ledger, request = desk

    def fail(**kwargs):
        raise RuntimeError("comparison storage interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "add_baseline_comparison", fail)
        with pytest.raises(RuntimeError, match="storage interrupted"):
            import_market_evidence(ledger, request, market(provider))
    assert ledger.list_evidence(request.question_id) == []
    result = import_market_evidence(ledger, request, market(provider))
    assert result.comparison is not None
    assert len(ledger.list_evidence(request.question_id)) == 1


def test_unquoted_market_does_not_invent_a_baseline(desk):
    ledger, request = desk
    result = import_market_evidence(
        ledger, request, replace(market("kalshi"), probability=None)
    )
    assert result.comparison is None
    assert ledger.list_baseline_comparisons(request.question_id) == []
