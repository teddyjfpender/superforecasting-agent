"""Prediction-market evidence imports; candidate promotion remains explicit."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forecasting.application.import_receipts import (
    ImportReceipt,
    ensure_receipts,
    read_receipt,
    write_receipt,
)
from forecasting.ledger import ForecastLedger
from forecasting.models import EvidenceItem, parse_timestamp
from forecasting.sources.market_records import (
    KalshiMarketImport,
    PolymarketMarketImport,
)
from forecasting.sources.requests import CommonSourceOptions

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


class MarketAcquisitionRequest(MarketEvidenceRequest):
    provider: Literal["kalshi", "polymarket"]
    api_base_url: str
    request_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("api_base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        CommonSourceOptions(api_base_url=value)
        return value


class MarketFetcher(Protocol):
    def __call__(self, source: str, *, api_base_url: str) -> MarketImport: ...


def acquire_market_evidence(
    ledger: ForecastLedger, request: MarketAcquisitionRequest, *, fetch: MarketFetcher
) -> MarketEvidenceResult:
    """Replay committed imports before fetching; serialize concurrent commit winners."""
    request = MarketAcquisitionRequest.model_validate(request.model_dump())
    ledger.get_question(request.question_id)
    digest = hashlib.sha256(
        json.dumps(
            {
                "version": 1,
                "adapter": request.provider,
                "request": request.model_dump(exclude={"request_id"}),
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()

    def restore(receipt: ImportReceipt) -> MarketEvidenceResult:
        if len(receipt.evidence) != 1 or len(receipt.comparisons) > 1:
            raise ValueError("invalid prediction-market import receipt")
        return MarketEvidenceResult(
            receipt.evidence[0], receipt.comparisons[0] if receipt.comparisons else None
        )

    if request.request_id is not None:
        with ledger.transaction(immediate=True) as conn:
            ensure_receipts(conn)
            prior = read_receipt(
                ledger,
                conn,
                question_id=request.question_id,
                request_id=request.request_id,
                digest=digest,
            )
            if prior is not None:
                return restore(prior)
    market = fetch(request.source, api_base_url=request.api_base_url)
    if market_import_metadata(market, request.source)["adapter"] != request.provider:
        raise ValueError("acquired market belongs to another provider")
    with ledger.transaction(immediate=True) as conn:
        if request.request_id is not None:
            prior = read_receipt(
                ledger,
                conn,
                question_id=request.question_id,
                request_id=request.request_id,
                digest=digest,
            )
            if prior is not None:
                return restore(prior)
        result = import_market_evidence(
            ledger,
            MarketEvidenceRequest(
                question_id=request.question_id,
                source=request.source,
                as_of=request.as_of,
            ),
            market,
        )
        if request.request_id is not None:
            write_receipt(
                conn,
                question_id=request.question_id,
                request_id=request.request_id,
                digest=digest,
                receipt=ImportReceipt(
                    [result.evidence],
                    [result.comparison] if result.comparison is not None else [],
                ),
            )
        return result
