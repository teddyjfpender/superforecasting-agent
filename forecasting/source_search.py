"""Search configured textual watched sources for forecast evidence candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastQuestion, json_loads
from forecasting.source_adapters import NewsFeedItem, load_news_feed_items


@dataclass(frozen=True)
class WatchedTextSourceCandidate:
    watched_source_id: str
    source_type: str
    source: str
    source_label: str
    title: str
    summary: str
    url: str | None
    published_at: str | None
    entry_id: str | None
    relevance_score: int
    matched_terms: list[str] = field(default_factory=list)
    materiality: str = "medium"
    direction: str = "ambiguous"
    affected_components: list[str] = field(default_factory=list)
    import_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "watched_source_id": self.watched_source_id,
            "source_type": self.source_type,
            "source": self.source,
            "source_label": self.source_label,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "published_at": self.published_at,
            "entry_id": self.entry_id,
            "relevance_score": self.relevance_score,
            "matched_terms": list(self.matched_terms),
            "materiality": self.materiality,
            "direction": self.direction,
            "affected_components": list(self.affected_components),
            "import_command": self.import_command,
        }


@dataclass(frozen=True)
class WatchedTextSourceSearchResult:
    question_id: str
    query: str
    searched_sources: int
    candidates: list[WatchedTextSourceCandidate]
    errors: list[dict[str, str]]
    no_silent_probability_mutation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "query": self.query,
            "searched_sources": self.searched_sources,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "errors": list(self.errors),
            "no_silent_probability_mutation": self.no_silent_probability_mutation,
        }


@dataclass(frozen=True)
class CapturedWatchedTextCandidate:
    candidate: WatchedTextSourceCandidate
    evidence: Any | None
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "evidence": self.evidence.__dict__ if self.evidence is not None else None,
            "skipped_reason": self.skipped_reason,
        }


_SOURCE_SEARCH_STOPWORDS = {
    "about",
    "after",
    "before",
    "being",
    "could",
    "during",
    "forecast",
    "from",
    "have",
    "into",
    "over",
    "question",
    "resolved",
    "than",
    "that",
    "their",
    "there",
    "this",
    "will",
    "with",
    "would",
}


def search_watched_text_sources(
    ledger: ForecastLedger,
    question_id: str,
    *,
    query: str | None = None,
    limit: int = 20,
    since: str | None = None,
) -> WatchedTextSourceSearchResult:
    """Search active watched RSS/Atom streams for candidate evidence.

    This function reads configured watched sources and feed content, but it does
    not write evidence or change probabilities. Use
    ``capture_watched_text_candidates`` when the operator or agent explicitly
    wants to promote candidates into timestamped evidence.
    """

    question = ledger.get_question(question_id)
    explicit_query_terms = _terms_from_query(query)
    query_terms = explicit_query_terms or _terms_from_question(question)
    watches = [
        row
        for row in ledger.list_watched_sources(status="active")
        if _watch_applies_to_question(row, question) and row.get("source_type") == "rss"
    ]
    candidates: list[WatchedTextSourceCandidate] = []
    errors: list[dict[str, str]] = []
    seen: set[str] = set()

    for watch in watches:
        metadata = watch.get("metadata") if isinstance(watch.get("metadata"), dict) else {}
        filters = _relevance_filters(metadata)
        include_terms = (
            _dedupe_terms([*explicit_query_terms, *filters["keywords"]])[:12]
            if filters["keywords"]
            else query_terms[:12]
        )
        exclude_terms = filters["exclude_keywords"]
        source = str(watch.get("source") or "")
        feed_source = _feed_source(source)
        try:
            items = load_news_feed_items(
                feed_source,
                limit=max(limit * 3, 20),
                since=since,
                keywords=include_terms,
                exclude_keywords=exclude_terms,
                dedupe=True,
            )
        except Exception as exc:
            errors.append(
                {
                    "watched_source_id": str(watch.get("id") or ""),
                    "source": source,
                    "error": f"{exc.__class__.__name__}: {exc}",
                }
            )
            continue

        for item in items:
            candidate = _candidate_from_feed_item(
                question_id=question_id,
                watch=watch,
                item=item,
                query_terms=query_terms,
                include_terms=include_terms,
            )
            if candidate.relevance_score <= 0:
                continue
            key = _candidate_dedupe_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)

    candidates.sort(key=lambda item: (-item.relevance_score, item.published_at or "", item.title))
    return WatchedTextSourceSearchResult(
        question_id=question_id,
        query=" ".join(query_terms),
        searched_sources=len(watches),
        candidates=candidates[: max(int(limit), 1)],
        errors=errors,
    )


def capture_watched_text_candidates(
    ledger: ForecastLedger,
    question_id: str,
    candidates: list[WatchedTextSourceCandidate],
    *,
    limit: int | None = None,
) -> list[CapturedWatchedTextCandidate]:
    """Promote selected watched-source candidates into evidence items.

    The capture is append-only evidence, not a forecast update. Existing
    evidence with the same candidate URL or entry id is skipped.
    """

    max_items = len(candidates) if limit is None else max(int(limit), 0)
    existing = _existing_evidence_keys(ledger, question_id)
    captured: list[CapturedWatchedTextCandidate] = []
    for candidate in candidates[:max_items]:
        keys = _candidate_existing_keys(candidate)
        duplicate_key = next((key for key in keys if key in existing), None)
        if duplicate_key:
            captured.append(
                CapturedWatchedTextCandidate(
                    candidate=candidate,
                    evidence=None,
                    skipped_reason=f"duplicate evidence candidate: {duplicate_key}",
                )
            )
            continue
        metadata = {
            "adapter": "watched_text_source_search",
            "watched_source_id": candidate.watched_source_id,
            "source_search": candidate.to_dict(),
            "forecast_impact": {
                "materiality": candidate.materiality,
                "direction": candidate.direction,
                "affected_components": list(candidate.affected_components),
            },
            "news_triage": {
                "materiality": candidate.materiality,
                "direction": candidate.direction,
                "affected_components": list(candidate.affected_components),
                "candidate_evidence": True,
                "no_silent_probability_mutation": True,
            },
        }
        evidence = ledger.add_evidence(
            question_id=question_id,
            source_or_note=candidate.url or candidate.title,
            claim=candidate.title,
            summary=candidate.summary,
            source_url=candidate.url,
            source_name=candidate.source_label,
            source_type=f"adapter:{candidate.source_type}",
            published_at=candidate.published_at,
            available_at=candidate.published_at,
            reliability_rating=None,
            relevance_rating=min(1.0, candidate.relevance_score / 20.0),
            stance="context",
            claim_type="fact",
            metadata=metadata,
        )
        existing.update(keys)
        captured.append(CapturedWatchedTextCandidate(candidate=candidate, evidence=evidence))
    return captured


def _candidate_from_feed_item(
    *,
    question_id: str,
    watch: dict[str, Any],
    item: NewsFeedItem,
    query_terms: list[str],
    include_terms: list[str],
) -> WatchedTextSourceCandidate:
    metadata = watch.get("metadata") if isinstance(watch.get("metadata"), dict) else {}
    impact = _forecast_impact(metadata)
    terms = _dedupe_terms([*query_terms, *include_terms])
    matched, score = _score_feed_item(item, terms)
    source = str(watch.get("source") or "")
    feed_source = _feed_source(source)
    filter_terms = include_terms or matched
    return WatchedTextSourceCandidate(
        watched_source_id=str(watch.get("id") or ""),
        source_type=str(watch.get("source_type") or "rss"),
        source=source,
        source_label=str(metadata.get("source_plan_label") or item.source_name or source),
        title=item.title,
        summary=item.summary,
        url=item.url,
        published_at=item.published_at,
        entry_id=item.entry_id,
        relevance_score=score,
        matched_terms=matched,
        materiality=impact["materiality"],
        direction=impact["direction"],
        affected_components=impact["affected_components"],
        import_command=_import_command(question_id, feed_source, filter_terms, item.published_at),
    )


def _score_feed_item(item: NewsFeedItem, terms: list[str]) -> tuple[list[str], int]:
    title = _normalize(item.title)
    summary = _normalize(item.summary)
    other = _normalize(" ".join(value for value in [item.url or "", item.entry_id or "", item.source_name or ""] if value))
    matched: list[str] = []
    score = 0
    for term in terms:
        normalized = _normalize(term)
        if not normalized:
            continue
        term_score = 0
        if normalized in title:
            term_score += 5
        if normalized in summary:
            term_score += 3
        if normalized in other:
            term_score += 1
        if term_score:
            matched.append(term)
            score += term_score
    return _dedupe_terms(matched), score


def _watch_applies_to_question(watch: dict[str, Any], question: ForecastQuestion) -> bool:
    scope_type = str(watch.get("scope_type") or "")
    scope_ref = watch.get("scope_ref")
    if scope_type == "question":
        return scope_ref == question.id
    if scope_type == "domain":
        return bool(question.domain and scope_ref == question.domain)
    if scope_type == "topic":
        return bool(scope_ref and scope_ref in (question.topics or []))
    if scope_type == "domain_topic":
        payload = json_loads(str(scope_ref or ""), {})
        return (
            isinstance(payload, dict)
            and bool(question.domain and payload.get("domain") == question.domain)
            and bool(payload.get("topic") in (question.topics or []))
        )
    return scope_type == "global"


def _terms_from_query(query: str | None) -> list[str]:
    return _dedupe_terms(
        token
        for token in re.findall(r"[a-z][a-z0-9-]{2,}", _normalize(query or ""))
        if token not in _SOURCE_SEARCH_STOPWORDS
    )[:12]


def _terms_from_question(question: ForecastQuestion) -> list[str]:
    parts = [
        question.title,
        question.description,
        question.resolution_criteria,
        question.resolution_source or "",
        question.domain or "",
        " ".join(question.topics or []),
        " ".join(question.tags or []),
    ]
    return _terms_from_query(" ".join(part for part in parts if part))


def _relevance_filters(metadata: dict[str, Any]) -> dict[str, list[str]]:
    raw = metadata.get("relevance_filters") if isinstance(metadata, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "keywords": _filter_terms(raw.get("keywords")),
        "exclude_keywords": _filter_terms(raw.get("exclude_keywords")),
    }


def _forecast_impact(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("forecast_impact") if isinstance(metadata, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    triage = metadata.get("news_triage") if isinstance(metadata, dict) else {}
    if not isinstance(triage, dict):
        triage = {}
    return {
        "materiality": str(raw.get("materiality") or triage.get("materiality") or metadata.get("materiality") or "medium"),
        "direction": str(raw.get("direction") or triage.get("direction") or "ambiguous"),
        "affected_components": _filter_terms(raw.get("affected_components") or triage.get("affected_components")),
    }


def _filter_terms(value: Any) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    terms: list[str] = []
    for item in values:
        for chunk in str(item).split(","):
            term = chunk.strip()
            if term and term not in terms:
                terms.append(term)
    return terms


def _feed_source(source: str) -> str:
    return source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source


def _candidate_dedupe_key(candidate: WatchedTextSourceCandidate) -> str:
    if candidate.url:
        return f"url:{_canonical_url(candidate.url)}"
    if candidate.entry_id:
        return f"id:{candidate.entry_id.strip().lower()}"
    return f"title:{_normalize(candidate.title)}:{candidate.published_at or ''}"


def _candidate_existing_keys(candidate: WatchedTextSourceCandidate) -> set[str]:
    keys = {_candidate_dedupe_key(candidate)}
    if candidate.url:
        keys.add(f"source_url:{_canonical_url(candidate.url)}")
    if candidate.entry_id:
        keys.add(f"entry_id:{candidate.entry_id.strip().lower()}")
    return keys


def _existing_evidence_keys(ledger: ForecastLedger, question_id: str) -> set[str]:
    keys: set[str] = set()
    for item in ledger.list_evidence(question_id):
        if item.source_url:
            keys.add(f"source_url:{_canonical_url(item.source_url)}")
            keys.add(f"url:{_canonical_url(item.source_url)}")
        metadata = item.metadata if isinstance(item.metadata, dict) else {}
        search = metadata.get("source_search") if isinstance(metadata, dict) else {}
        if isinstance(search, dict):
            entry_id = search.get("entry_id")
            if entry_id:
                keys.add(f"entry_id:{str(entry_id).strip().lower()}")
    return keys


def _import_command(question_id: str, feed_source: str, keywords: list[str], published_at: str | None) -> str:
    parts = ["forecast import news", _shell_quote(feed_source), "--question", question_id]
    if published_at:
        parts.extend(["--since", _shell_quote(published_at)])
    for term in keywords[:8]:
        parts.extend(["--keyword", _shell_quote(term)])
    return " ".join(parts)


def _shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:+=,@%-]+", value):
        return value
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9_ -]+", " ", str(value or "").lower())).strip()


def _dedupe_terms(terms: Any) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for term in terms or []:
        cleaned = str(term).strip()
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        output.append(cleaned)
    return output


def _canonical_url(value: str) -> str:
    parsed = urlparse(value.strip())
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))
