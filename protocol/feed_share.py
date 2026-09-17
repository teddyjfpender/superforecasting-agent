"""Transport-neutral, untrusted feed snapshots. Never a settlement binding."""

import re
from datetime import date, datetime
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, field_validator, model_validator

from protocol.types import WireModel


class ShareModel(WireModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def plain_text(cls, value: object) -> object:
        if isinstance(value, str) and re.search(r"[\x00-\x1f\x7f-\x9f]", value):
            raise ValueError("Control characters are not allowed in feed snapshots")
        return value


class SharedPeriod(ShareModel):
    start: str = Field(max_length=24)
    end: str = Field(max_length=24)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        for value in (self.start, self.end):
            if len(value) == 10:
                valid = date.fromisoformat(value).isoformat() == value
            else:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                valid = (
                    value.endswith("Z")
                    and parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")
                    == value
                )
            if not valid:
                raise ValueError("Use ISO calendar dates or canonical UTC milliseconds")
        if len(self.start) != len(self.end):
            raise ValueError("Period precision must match")
        if self.end < self.start:
            raise ValueError("Period end precedes start")
        return self


class SharedObservation(SharedPeriod):
    value: float | None


class SharedFeed(ShareModel):
    provider: str = Field(min_length=1, max_length=80)
    symbol: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=240)
    unit: str = Field(max_length=80)
    kind: str = Field(max_length=40)
    source_url: str | None = Field(max_length=2048)
    retrieved_at: str | None = Field(max_length=40)
    revision_policy: str = Field(max_length=80)
    points: list[SharedObservation] = Field(min_length=1, max_length=120)

    @field_validator("source_url")
    @classmethod
    def safe_source(cls, value: str | None) -> str | None:
        if value is not None:
            url = urlsplit(value)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError(
                    "Use a public source URL without credentials or query parameters"
                )
        return value

    @field_validator("retrieved_at")
    @classmethod
    def timestamp(cls, value: str | None) -> str | None:
        if value is not None:
            if not re.fullmatch(
                r"(?!0000)\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d"
                r"(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
                value,
            ):
                raise ValueError("Use an ISO timestamp with an explicit timezone")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value

    @model_validator(mode="after")
    def ordered_points(self) -> Self:
        if any(a.end >= b.start for a, b in zip(self.points, self.points[1:])):
            raise ValueError(
                "Observations must be ordered, distinct and nonoverlapping"
            )
        return self


class FeedShare(ShareModel):
    type: Literal["sfa.feed"]
    version: Literal[1, 2]
    presentation: Literal["bar-chart", "line-chart"]
    horizon: SharedPeriod
    feeds: list[SharedFeed] = Field(min_length=1, max_length=4)

    @field_validator("version", mode="before")
    @classmethod
    def integer_version(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Version must be an integer")
        return value

    @model_validator(mode="after")
    def bounded_horizon(self) -> Self:
        precision = len(self.horizon.start)
        if self.version == 1 and precision != 10:
            raise ValueError("Version 1 only supports calendar dates")
        for feed in self.feeds:
            if any(len(p.start) != precision for p in feed.points):
                raise ValueError("All observations must use the horizon precision")
            if (
                feed.points[0].start < self.horizon.start
                or feed.points[-1].end > self.horizon.end
            ):
                raise ValueError("Observations fall outside the declared horizon")
        if len({(f.provider, f.symbol) for f in self.feeds}) != len(self.feeds):
            raise ValueError("Duplicate feed identities")
        return self
