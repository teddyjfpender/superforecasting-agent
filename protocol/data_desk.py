"""Pure data-desk contracts shared by acquisition, application and transport.

No filesystem, provider or credential access belongs in this module. Catalog
content and loading live in forecasting.marketdata; profile edits live in the
DataDesk application owner.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DataKind = Literal[
    "quote", "observation", "forecast", "reanalysis", "estimate", "event", "probability"
]
Frequency = Literal[
    "tick", "hourly", "daily", "weekly", "monthly", "quarterly", "annual", "event"
]


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DataCategory(CatalogModel):
    id: str
    name: str
    group: str
    aliases: tuple[str, ...] = ()


class DataRegion(CatalogModel):
    id: str
    name: str
    members: tuple[str, ...] = ()


class DataCountry(CatalogModel):
    id: str = Field(pattern=r"^[A-Z]{3}$")
    name: str
    region: str


class DataProvider(CatalogModel):
    id: str
    name: str
    description: str
    website: str
    auth: Literal["none", "optional", "required"] = "none"
    key_env: str | None = None
    signup_url: str | None = None
    access_note: str = ""
    capabilities: tuple[
        Literal["latest", "history", "search", "events", "stream"], ...
    ] = ("latest",)

    @model_validator(mode="after")
    def check_auth(self) -> DataProvider:
        if self.auth != "none" and not self.key_env:
            raise ValueError(
                "authenticated providers must declare their credential slot"
            )
        return self


class DataLocation(CatalogModel):
    name: str
    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)
    timezone: str = "UTC"


ChangeBasis = Literal["previous_observation", "last_transition"]


class ObservationComparison(CatalogModel):
    basis: ChangeBasis
    previous_period: str
    previous_value: float = Field(allow_inf_nan=False)
    current_period: str
    current_value: float = Field(allow_inf_nan=False)


class DataSeries(CatalogModel):
    id: str
    provider: str
    symbol: str
    name: str
    category: str
    region: str
    country: str | None = None
    location: DataLocation | None = None
    kind: DataKind
    frequency: Frequency
    unit: str
    dimensions: dict[str, str] = Field(default_factory=dict)
    # Equivalent concepts are assigned only after semantic qualification, never
    # guessed from display names or numerical proximity.
    concept_id: str
    source_family: str
    source_url: str
    revision_policy: Literal["latest", "first_release", "as_issued", "unknown"] = (
        "unknown"
    )
    refresh_seconds: int = Field(default=3600, ge=30)
    expected_lag_seconds: int | None = Field(default=None, ge=0)
    change_basis: ChangeBasis = "previous_observation"
    history_points: int = Field(default=24, ge=0, le=366)
    tags: tuple[str, ...] = ()
    line: str | None = None


class DataPreset(CatalogModel):
    id: str
    version: int = Field(ge=1)
    name: str
    description: str
    series_ids: tuple[str, ...]


class DataCatalog(CatalogModel):
    version: int = Field(ge=1)
    providers: tuple[DataProvider, ...]
    categories: tuple[DataCategory, ...]
    regions: tuple[DataRegion, ...]
    countries: tuple[DataCountry, ...] = ()
    series: tuple[DataSeries, ...]
    presets: tuple[DataPreset, ...]

    @model_validator(mode="after")
    def check_references(self) -> DataCatalog:
        for entries in (
            self.providers,
            self.categories,
            self.regions,
            self.countries,
            self.series,
            self.presets,
        ):
            ids = [entry.id for entry in entries]
            if len(set(ids)) != len(ids):
                raise ValueError("catalog contains duplicate identities")
        providers = {entry.id for entry in self.providers}
        categories = {entry.id for entry in self.categories}
        regions = {entry.id for entry in self.regions}
        series = {entry.id for entry in self.series}
        countries = {entry.id: entry for entry in self.countries}
        for country in self.countries:
            if country.region not in regions:
                raise ValueError(f"Unknown country region: {country.id}")
        for entry in self.series:
            if entry.country and (
                entry.country not in countries
                or countries[entry.country].region != entry.region
            ):
                raise ValueError(
                    f"Unknown country or inconsistent geography: {entry.id}"
                )
            if (
                entry.provider not in providers
                or entry.category not in categories
                or entry.region not in regions
            ):
                raise ValueError(f"unresolved catalog reference: {entry.id}")
        for preset in self.presets:
            if (
                len(preset.series_ids) != len(set(preset.series_ids))
                or set(preset.series_ids) - series
            ):
                raise ValueError(f"invalid preset membership: {preset.id}")
        return self

    @property
    def revision(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()

    def find_series(
        self,
        query: str = "",
        *,
        category: str = "",
        region: str = "",
        provider: str = "",
        country: str = "",
        kind: str = "",
    ) -> list[DataSeries]:
        terms = query.casefold().split()
        country_names = {item.id: item.name for item in self.countries}
        region_def = next((item for item in self.regions if item.id == region), None)
        allowed_regions = {region, *(region_def.members if region_def else ())}
        return [
            entry
            for entry in self.series
            if (not category or entry.category == category)
            and (not region or entry.region in allowed_regions)
            and (not provider or entry.provider == provider)
            and (not country or entry.country == country)
            and (not kind or entry.kind == kind)
            and all(
                term
                in " ".join((
                    entry.name,
                    entry.symbol,
                    entry.provider,
                    entry.country or "",
                    country_names.get(entry.country or "", ""),
                    entry.location.name if entry.location else "",
                    *entry.tags,
                )).casefold()
                for term in terms
            )
        ]


class DatedValue(BaseModel):
    """One dated measurement; absence and unknown release times stay explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    period_start: str
    period_end: str
    value: float | None = Field(allow_inf_nan=False)
    published_at: str | None = None
    status: str | None = None

    @field_validator("value", mode="before")
    @classmethod
    def numeric_value(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("A measurement cannot be boolean")
        return value

    @model_validator(mode="after")
    def validate_period(self) -> "DatedValue":
        def parse(value: str) -> datetime:
            if len(value) == 10:
                return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("Timestamp requires a timezone")
            return parsed

        start, end = parse(self.period_start), parse(self.period_end)
        if (len(self.period_start) == 10) != (len(self.period_end) == 10):
            raise ValueError("Period boundaries must use the same precision")
        if end < start:
            raise ValueError("Observation period ends before it starts")
        if self.published_at is not None:
            if len(self.published_at) == 10:
                raise ValueError("Publication time requires an explicit timezone")
            parse(self.published_at)
        return self


class DataEvent(BaseModel):
    """An event feed item, deliberately separate from numerical observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    title: str
    description: str
    area: str | None
    severity: str | None
    issued_at: str | None
    effective_at: str | None
    expires_at: str | None
    source_url: str | None


class DataEvents(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    series_id: str
    events: list[DataEvent]
    retrieved_at: str
    truncated: bool


class DeskModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeskCustomSeries(BaseModel):
    """Compatibility view of custom symbols; unknown disk metadata is retained."""

    provider: str
    symbol: str
    name: str = ""
    category: str = ""
    unit: str = ""
    line: str | None = None


class DeskSavedEvent(BaseModel):
    event_id: str
    venue: str


class DeskSelection(DeskModel):
    revision: str
    state: Literal["unconfigured", "empty", "custom", "preset"]
    series_ids: list[str]
    # Legacy fields remain available while consumers migrate; credentials never
    # belong in this document. Unknown fields are preserved on disk, not exposed.
    categories: list[str]
    providers: list[str]
    custom: list[DeskCustomSeries]
    watchlist: list[DeskCustomSeries]
    pm_saved: list[DeskSavedEvent]
    server_side: list[str] | None = None
    home_region: str | None = None
    weather_locations: list[str] | None = None


class DeskPatch(DeskModel):
    """Explicit fields only; selection membership is edited through preview/apply."""

    custom: list[DeskCustomSeries] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    watchlist: list[DeskCustomSeries] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    pm_saved: list[DeskSavedEvent] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    providers: list[str] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    categories: list[str] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    server_side: list[str] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )


class DeskEdit(DeskModel):
    catalog_revision: str
    preset_id: str | None = None
    add: list[str] = Field(default_factory=list, max_length=2000)
    remove: list[str] = Field(default_factory=list, max_length=2000)
    start_empty: bool = False
    home_region: str | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )
    weather_locations: list[str] | None = Field(
        default=None, json_schema_extra={"wireOptional": True, "wireNullable": True}
    )


class DeskPreview(DeskModel):
    revision: str
    catalog_revision: str
    added: list[str]
    removed: list[str]
    already_selected: list[str]
    credential_providers: list[str]
    selection: DeskSelection
