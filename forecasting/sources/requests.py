"""Common acquisition admission; provider-specific options stay with each adapter."""

from datetime import date, datetime
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class CommonSourceOptions(BaseModel):
    """Validate shared fields without interpreting adapter-specific measurements.

    Unknown fields belong to the selected adapter and remain in the original mapping.
    None on optional fields means omitted; false and zero never mean omitted.
    """

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    limit: int = Field(default=10, gt=0)
    since: str | None = None
    api_base_url: str | None = None
    dedupe: bool = True
    local: bool = False
    only_media: bool = False
    forecast_days: int | None = Field(default=None, gt=0)

    @field_validator("since")
    @classmethod
    def validate_since(cls, value: str | None) -> str | None:
        if value is None:
            return None
        # Annual adapters accept a year without inventing a day or timezone.
        if (
            len(value) == 4
            and value.isascii()
            and value.isdigit()
            and 1 <= int(value) <= 9999
        ):
            return value
        try:
            date.fromisoformat(value)
        except ValueError:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("timestamp requires a timezone")
        return value

    @field_validator("api_base_url")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("endpoint requires an HTTP URL")
        # Accessing the port validates malformed and out-of-range port numbers.
        _ = parsed.port
        return value

    @classmethod
    def read(cls, args: dict[str, object]) -> Self:
        try:
            return cls.model_validate(args)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors()})
            # Do not echo values: endpoints can contain credentials or tokens.
            raise ValueError("invalid source options: " + ", ".join(fields)) from None


class SourceImportOptions(CommonSourceOptions):
    """Shared import controls; malformed flags must not enable persistence effects."""

    auto_watch: bool = False
    admissible_for_backtests: bool = True
    reliability_rating: float | None = Field(default=None, ge=0, le=1)
    relevance_rating: float | None = Field(default=None, ge=0, le=1)


class SourceBatchOptions(SourceImportOptions):
    concurrency: int = Field(default=4, ge=1, le=8)


class SourceIdentity(BaseModel):
    """Admission before source dispatch, without stringifying arbitrary objects."""

    model_config = ConfigDict(
        strict=True, extra="ignore", frozen=True, str_strip_whitespace=True
    )
    source_type: str = Field(min_length=1)
    source: str = Field(min_length=1)

    @classmethod
    def read(cls, args: dict[str, object]) -> Self:
        try:
            return cls.model_validate(args)
        except ValidationError as exc:
            fields = sorted({str(error["loc"][0]) for error in exc.errors()})
            raise ValueError("invalid source identity: " + ", ".join(fields)) from None
