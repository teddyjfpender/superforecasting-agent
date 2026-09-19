"""Typed evidence import operations shared by presentation adapters."""

import math
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from forecasting.ledger import ForecastLedger
from forecasting.models import EVIDENCE_CLAIM_TYPES, EvidenceItem, parse_timestamp
from forecasting.sources.economic_records import FredObservation
from forecasting.sources.requests import CommonSourceOptions


class FredImportRequest(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, str_strip_whitespace=True
    )

    source: str = Field(min_length=1)
    question_id: str = Field(min_length=1)
    options: CommonSourceOptions
    as_of: str | None = None
    reliability: float | None = Field(default=None, ge=0, le=1)
    relevance: float | None = Field(default=None, ge=0, le=1)
    claim_type: str = "fact"

    @field_validator("claim_type")
    @classmethod
    def validate_claim_type(cls, value: str) -> str:
        if value not in EVIDENCE_CLAIM_TYPES:
            raise ValueError("unsupported evidence claim type")
        return value

    @field_validator("as_of")
    @classmethod
    def validate_as_of(cls, value: str | None) -> str | None:
        return parse_timestamp(value, field_name="as_of") if value is not None else None


class FredFetcher(Protocol):
    def __call__(
        self, source: str, *, limit: int, since: str | None, api_base_url: str = ...
    ) -> Sequence[FredObservation]: ...


def import_fred_evidence(
    ledger: ForecastLedger, request: FredImportRequest, *, fetch: FredFetcher
) -> list[EvidenceItem]:
    """Fetch outside the transaction; admit the complete batch before writing.

    Raw observations remain evidence claims, not locally verified settlement bindings.
    This operation does not create or promote a forecast probability.
    """
    request = FredImportRequest.model_validate(request.model_dump())
    ledger.get_question(request.question_id)
    options = request.options
    if options.api_base_url is None:
        observations = list(
            fetch(request.source, limit=options.limit, since=options.since)
        )
    else:
        observations = list(
            fetch(
                request.source,
                limit=options.limit,
                since=options.since,
                api_base_url=options.api_base_url,
            )
        )
    seen: dict[str, FredObservation] = {}
    for observation in observations:
        if observation.series_id != request.source:
            raise ValueError("FRED observation belongs to a different series")
        date.fromisoformat(observation.observation_date)
        if (
            isinstance(observation.value, bool)
            or not isinstance(observation.value, (int, float))
            or not math.isfinite(observation.value)
        ):
            raise ValueError("FRED observation must be a finite numeric measurement")
        if not observation.entry_id:
            raise ValueError("FRED observation requires an entry identity")
        prior = seen.get(observation.entry_id)
        if prior is not None and prior != observation:
            raise ValueError("conflicting FRED observations share an entry identity")
        seen[observation.entry_id] = observation

    evidence_items: list[EvidenceItem] = []
    with ledger.transaction(immediate=True):
        for observation in seen.values():
            evidence_items.append(
                ledger.add_evidence(
                    question_id=request.question_id,
                    source_or_note=observation.source_url
                    or f"FRED:{observation.series_id}",
                    source_url=observation.source_url,
                    source_name=observation.source_name,
                    source_type="adapter:fred",
                    published_at=observation.published_at,
                    available_at=observation.published_at or request.as_of,
                    claim=f"{observation.series_id} {observation.observation_date}: {observation.value}",
                    summary=f"FRED observation for {observation.series_id} on {observation.observation_date}: {observation.value}.",
                    reliability_rating=request.reliability,
                    relevance_rating=request.relevance,
                    stance="context",
                    claim_type=request.claim_type,
                    metadata={
                        "adapter": "fred",
                        "series_id": observation.series_id,
                        "observation_date": observation.observation_date,
                        "value": observation.value,
                        "api_base_url": request.options.api_base_url,
                        "raw": observation.raw,
                    },
                )
            )
    return evidence_items
