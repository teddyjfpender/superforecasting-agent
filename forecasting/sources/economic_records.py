"""Economic records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FiveThirtyEightPollObservation:
    dataset: str
    poll_id: str | None
    question_id: str | None
    pollster: str | None
    pollster_grade: str | None
    race_id: str | None
    office_type: str | None
    state: str | None
    cycle: int | None
    stage: str | None
    candidate_name: str | None
    answer: str | None
    party: str | None
    pct: float | None
    sample_size: float | int | None
    population: str | None
    start_date: str | None
    end_date: str | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class FredObservation:
    series_id: str
    observation_date: str
    value: float | str
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class EiaObservation:
    series_id: str
    series_name: str | None
    observation_period: str
    value: float | str
    unit: str | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class TreasuryRecord:
    dataset: str
    record_date: str
    value: float | str | None
    value_field: str | None
    value_label: str | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class BlsObservation:
    series_id: str
    observation_date: str
    period: str
    period_name: str | None
    value: float | str
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class WorldBankObservation:
    country: str
    country_name: str | None
    indicator: str
    indicator_name: str | None
    observation_date: str
    value: float | str
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ImfDataMapperObservation:
    indicator: str
    indicator_name: str | None
    country: str
    country_name: str | None
    observation_date: str
    value: float | str
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class CensusRecord:
    dataset: str
    dataset_year: int | None
    observation_date: str | None
    values: dict[str, float | str]
    geography: dict[str, str]
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SocrataRecord:
    domain: str
    dataset_id: str
    row_id: str | None
    observation_time: str | None
    updated_at: str | None
    values: dict[str, object]
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class CkanDataset:
    portal: str
    package_id: str | None
    name: str | None
    title: str
    notes: str
    url: str | None
    organization: str | None
    groups: list[str]
    tags: list[str]
    license_title: str | None
    metadata_created: str | None
    metadata_modified: str | None
    resources: list[dict[str, object]]
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class StooqPriceObservation:
    symbol: str
    interval: str
    observation_date: str
    open_price: float | str | None
    high_price: float | str | None
    low_price: float | str | None
    close_price: float | str
    volume: float | int | str | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class YahooFinancePriceObservation:
    symbol: str
    interval: str
    observation_time: str
    open_price: float | str | None
    high_price: float | str | None
    low_price: float | str | None
    close_price: float | str
    volume: float | int | str | None
    published_at: str | None
    currency: str | None
    exchange_name: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SecFiling:
    cik: str
    company_name: str | None
    ticker: str | None
    form: str
    filing_date: str
    report_date: str | None
    acceptance_time: str | None
    published_at: str
    accession_number: str
    primary_document: str | None
    description: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class SecCompanyFact:
    cik: str
    company_name: str | None
    taxonomy: str
    concept: str
    label: str | None
    description: str | None
    unit: str
    observation_date: str
    value: float | int | str
    filed_at: str | None
    published_at: str
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    accession_number: str | None
    frame: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict
