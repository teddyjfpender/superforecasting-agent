"""Public records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsFeedItem:
    title: str
    summary: str
    url: str | None
    published_at: str | None
    source_name: str | None
    entry_id: str | None


@dataclass(frozen=True)
class GdeltArticle:
    title: str
    summary: str
    url: str | None
    published_at: str | None
    source_name: str | None
    entry_id: str | None
    domain: str | None
    source_country: str | None
    language: str | None
    image_url: str | None
    raw: dict


@dataclass(frozen=True)
class HackerNewsItem:
    object_id: str
    title: str
    url: str | None
    hn_url: str | None
    author: str | None
    created_at: str | None
    points: int | None
    comments: int | None
    story_id: int | None
    story_text: str
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class RedditPost:
    post_id: str
    title: str
    subreddit: str | None
    author: str | None
    url: str | None
    permalink: str | None
    created_at: str | None
    score: int | None
    comments: int | None
    upvote_ratio: float | None
    selftext: str
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class BlueskyPost:
    post_uri: str
    cid: str | None
    text: str
    author_handle: str | None
    author_display_name: str | None
    author_did: str | None
    created_at: str | None
    indexed_at: str | None
    reply_count: int | None
    repost_count: int | None
    like_count: int | None
    quote_count: int | None
    url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class MastodonStatus:
    status_id: str
    uri: str | None
    url: str | None
    content_text: str
    account_acct: str | None
    account_username: str | None
    account_display_name: str | None
    account_url: str | None
    created_at: str | None
    replies_count: int | None
    reblogs_count: int | None
    favourites_count: int | None
    language: str | None
    visibility: str | None
    tags: list[str]
    card_url: str | None
    card_title: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class ReliefWebReport:
    report_id: str | None
    title: str
    summary: str
    url: str | None
    published_at: str | None
    changed_at: str | None
    sources: list[str]
    countries: list[str]
    disasters: list[str]
    formats: list[str]
    themes: list[str]
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class FederalRegisterDocument:
    document_number: str | None
    title: str
    abstract: str
    url: str | None
    pdf_url: str | None
    published_at: str | None
    document_type: str | None
    agencies: list[str]
    citation: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CourtListenerSearchResult:
    result_id: str | None
    title: str
    snippet: str
    url: str | None
    court: str | None
    court_id: str | None
    docket_number: str | None
    date_filed: str | None
    date_argued: str | None
    status: str | None
    citation: str | None
    judge: str | None
    cite_count: int | None
    search_type: str | None
    source_name: str
    entry_id: str | None
    raw: dict
