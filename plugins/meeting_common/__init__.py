"""Shared meeting primitives used by both meeting surfaces (Teams pipeline + Google
Meet followup): a common MeetingSummary model and a transcript -> summary/action-item
summarizer, so action items are extracted the same way everywhere."""

from plugins.meeting_common.summarize import (
    MeetingSummary,
    build_summary_prompt,
    heuristic_summary,
    parse_summary_json,
    summarize_transcript,
    summarize_transcript_sync,
)

__all__ = [
    "MeetingSummary",
    "build_summary_prompt",
    "heuristic_summary",
    "parse_summary_json",
    "summarize_transcript",
    "summarize_transcript_sync",
]
