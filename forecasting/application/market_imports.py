"""Prediction-market evidence imports; candidate promotion remains explicit."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem, parse_timestamp
from forecasting.sources.market_records import (
    KalshiMarketImport,
    PolymarketMarketImport,
)

MarketImport = KalshiMarketImport | PolymarketMarketImport


class MarketEvidenceRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, str_strip_whitespace=True
    )

    question_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    as_of: str | None = None

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str | None) -> str | None:
        return parse_timestamp(value, field_name="as_of") if value is not None else None


@dataclass(frozen=True)
class MarketEvidenceResult:
    evidence: EvidenceItem
    comparison: dict[str, Any] | None


def market_import_metadata(market: MarketImport, source: str) -> dict[str, Any]:
    if isinstance(market, KalshiMarketImport):
        return {
            "adapter": "kalshi",
            "source": source,
            "ticker": market.ticker,
            "event_ticker": market.event_ticker,
            "status": market.status,
            "market_url": market.url,
        }
    if isinstance(market, PolymarketMarketImport):
        return {
            "adapter": "polymarket",
            "source": source,
            "market_id": market.market_id,
            "slug": market.slug,
            "market_url": market.url,
        }
    raise ValueError("unsupported prediction-market import record")


def import_market_evidence(
    ledger: ForecastLedger,
    request: MarketEvidenceRequest,
    market: MarketImport,
) -> MarketEvidenceResult:
    """Persist evidence and its comparison together, without an active forecast write.

    Callers acquire and parse the market before entering this operation. Comparisons
    are admitted by the ledger against the target question's outcome space.
    """
    request = MarketEvidenceRequest.model_validate(request.model_dump())
    metadata = market_import_metadata(market, request.source)
    adapter = metadata["adapter"]
    value = (
        market.distribution
        if isinstance(market, PolymarketMarketImport)
        and market.distribution is not None
        else market.probability
    )
    with ledger.transaction(immediate=True):
        evidence = ledger.add_evidence(
            question_id=request.question_id,
            source_or_note=market.url or request.source,
            source_url=market.url,
            source_name="Kalshi" if adapter == "kalshi" else "Polymarket",
            source_type=f"adapter:{adapter}",
            published_at=market.as_of,
            available_at=market.as_of or request.as_of,
            claim=market.question,
            summary=market.description,
            stance="context",
            claim_type="estimate",
            metadata=metadata,
        )
        comparison = None
        if value is not None:
            comparison = ledger.add_baseline_comparison(
                question_id=request.question_id,
                source=market.baseline_source,
                baseline_type="market",
                probability_or_distribution=value,
                as_of=market.as_of or request.as_of or "",
                metadata=metadata,
            )
    return MarketEvidenceResult(evidence, comparison)
