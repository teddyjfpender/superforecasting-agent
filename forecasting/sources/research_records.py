"""Research records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str | None
    title: str
    abstract: str
    url: str | None
    pdf_url: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    categories: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class OpenAlexWork:
    work_id: str | None
    title: str
    abstract: str
    url: str | None
    doi: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    concepts: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CrossrefWork:
    doi: str | None
    title: str
    abstract: str
    url: str | None
    published_at: str | None
    updated_at: str | None
    authors: list[str]
    subjects: list[str]
    container_title: str | None
    publisher: str | None
    work_type: str | None
    reference_count: int | None
    cited_by_count: int | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class PubMedArticle:
    pmid: str
    title: str
    abstract: str
    journal: str | None
    url: str | None
    doi: str | None
    published_at: str | None
    revised_at: str | None
    authors: list[str]
    publication_types: list[str]
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class WikipediaPage:
    page_id: str | None
    title: str
    extract: str
    url: str | None
    updated_at: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class WikimediaPageviewObservation:
    project: str
    article: str
    access: str
    agent: str
    granularity: str
    observation_date: str
    views: int
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ClinicalTrialStudy:
    nct_id: str
    brief_title: str
    official_title: str | None
    url: str | None
    status: str | None
    phases: list[str]
    study_type: str | None
    conditions: list[str]
    interventions: list[str]
    sponsors: list[str]
    start_date: str | None
    primary_completion_date: str | None
    completion_date: str | None
    last_update_submitted_at: str | None
    last_update_posted_at: str | None
    has_results: bool
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class OpenFdaDrugApplication:
    application_number: str
    sponsor_name: str | None
    brand_names: list[str]
    generic_names: list[str]
    routes: list[str]
    substances: list[str]
    dosage_forms: list[str]
    marketing_statuses: list[str]
    latest_submission_status: str | None
    latest_submission_status_date: str | None
    latest_submission_type: str | None
    latest_submission_class: str | None
    url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class OwidObservation:
    slug: str
    entity: str | None
    code: str | None
    observation_date: str
    value: float | str | None
    value_column: str
    published_at: str
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class WhoGhoObservation:
    indicator: str
    spatial_dim: str | None
    time_dim: str | None
    dim1: str | None
    dim2: str | None
    dim3: str | None
    value: float | str | None
    numeric_value: float | None
    low: float | None
    high: float | None
    published_at: str | None
    source_url: str | None
    source_name: str
    entry_id: str
    raw: dict
