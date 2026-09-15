"""News desk contracts shared by setup, backend and terminal consumers."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from protocol.types import WireModel


class NewsSubscription(WireModel):
    url: str = Field(max_length=2048)
    title: str = Field(max_length=240)
    category: str = Field(max_length=80)
    addedAt: int = 0
    custom: bool = False

    @field_validator("url")
    @classmethod
    def public_scheme(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.hostname
            or parts.username
            or parts.password
        ):
            raise ValueError("Use an HTTP(S) feed URL without credentials")
        return value


class NewsDeskRequest(WireModel):
    pass


class NewsDeskResponse(WireModel):
    feeds: list[NewsSubscription]
    starter: list[NewsSubscription]
    state: Literal["unconfigured", "configured"]


class NewsConfigureRequest(WireModel):
    action: Literal["starter", "empty", "add", "remove"]
    feed: NewsSubscription | None = None


class NewsFeedRequest(WireModel):
    url: str = Field(max_length=2048)


class NewsFeedResponse(WireModel):
    xml: str
    url: str


class NewsArticleResponse(WireModel):
    text: str
    url: str
    status: Literal["article", "excerpt", "unavailable"]
    message: str
