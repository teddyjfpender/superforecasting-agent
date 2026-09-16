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
    start: str = Field(max_length=10)
    end: str = Field(max_length=10)

    @model_validator(mode="after")
    def valid_period(self) -> Self:
        for value in (self.start, self.end):
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("Use ISO calendar dates")
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
        if (
            value is not None
            and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None
        ):
            raise ValueError("Timestamp needs a timezone")
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
    version: Literal[1]
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
        for feed in self.feeds:
            if (
                feed.points[0].start < self.horizon.start
                or feed.points[-1].end > self.horizon.end
            ):
                raise ValueError("Observations fall outside the declared horizon")
        if len({(f.provider, f.symbol) for f in self.feeds}) != len(self.feeds):
            raise ValueError("Duplicate feed identities")
        return self
