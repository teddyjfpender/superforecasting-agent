"""Idempotently attach an explicitly selected article claim without refetching it."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from forecasting.interviews.service import InterviewService
from forecasting.models import ValidationError, timestamp_to_datetime, utc_now_iso
from protocol.interviews import ForecastArticleClaim, InterviewDraft

if TYPE_CHECKING:
    from forecasting.ledger import ForecastLedger


def canonical_article_url(url: str) -> str:
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        urlencode(query),
        "",
    ))


def attach_article(
    ledger: ForecastLedger,
    question_id: str,
    article: ForecastArticleClaim,
    *,
    prepare_update: bool = False,
) -> dict:
    article = ForecastArticleClaim.model_validate(article.model_dump())
    canonical = canonical_article_url(article.url)
    payload = article.model_dump()
    payload["url"] = canonical
    # Equivalent tracking URLs and whitespace are one capture; changed content is
    # a new claim with the same source group, not new independent corroboration.
    payload["content"] = " ".join(article.content.split())
    payload.pop("feed_url")
    payload.pop("extraction")
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    now = utc_now_iso()
    published = timestamp_to_datetime(article.published_at)
    captured = timestamp_to_datetime(now)
    if published is not None and captured is not None and published > captured:
        raise ValidationError(
            "article publication time is in the future; correct the feed timestamp first"
        )
    with ledger.transaction(immediate=True) as conn:
        question = ledger.get_question(question_id)
        if prepare_update and question.status != "active":
            raise ValidationError("only active questions can receive update interviews")
        receipt = conn.execute(
            "SELECT * FROM forecast_article_attachments WHERE question_id = ? AND digest = ?",
            (question_id, digest),
        ).fetchone()
        if receipt:
            evidence_id, interview_id = receipt["evidence_id"], receipt["interview_id"]
        else:
            evidence = ledger.add_evidence(
                question_id=question_id,
                source_or_note=canonical,
                source_url=canonical,
                source_name=article.publisher or None,
                source_type="news_selection",
                published_at=article.published_at,
                available_at=now,
                claim=article.title,
                summary=article.content,
                claim_type="fact",
                archive_url_snapshot=False,
                admissible_for_backtests=False,
                metadata={
                    "attachment_digest": digest,
                    "original_url": article.url,
                    "feed_url": article.feed_url,
                    "extraction": article.extraction,
                    "verification_status": "user_selected_claim",
                    "publication_time_status": "source_reported"
                    if article.published_at
                    else "unknown",
                    "independence_key": canonical,
                    "syndication_independence": "unassessed",
                    "content_sha256": hashlib.sha256(
                        article.content.encode()
                    ).hexdigest(),
                },
            )
            evidence_id, interview_id = evidence.id, None
            conn.execute(
                "INSERT INTO forecast_article_attachments (question_id, digest, evidence_id, interview_id) "
                "VALUES (?, ?, ?, NULL)",
                (question_id, digest, evidence_id),
            )
        if prepare_update and not interview_id:
            interview_id = (
                "news_"
                + hashlib.sha256(f"{question_id}:{digest}".encode()).hexdigest()[:32]
            )
            service = InterviewService(ledger)
            record = service.begin(interview_id, question_id=question_id)
            draft = InterviewDraft.model_validate(record["document"])
            draft.evidence_refs = list(
                dict.fromkeys([*draft.evidence_refs, evidence_id])
            )
            draft.status = "needs_research"
            service.store.save(
                interview_id,
                draft,
                expected_revision=record["revision"],
                request_id="attach_article",
                actor="user",
            )
            conn.execute(
                "UPDATE forecast_article_attachments SET interview_id = ? WHERE question_id = ? AND digest = ?",
                (interview_id, question_id, digest),
            )
        return {
            "question_id": question_id,
            "evidence_id": evidence_id,
            "interview_id": interview_id,
            "already_attached": receipt is not None,
        }
