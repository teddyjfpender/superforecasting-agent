"""Shared meeting summarizer: transcript -> {summary, key_decisions, action_items,
risks}.

One implementation behind both the Teams pipeline and the Google Meet post-call
followup, so every surface extracts action items the same way. LLM-backed with a
deterministic heuristic fallback, so a missing or failed LLM still yields a usable
TODO list rather than nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MeetingSummary:
    """A meeting's distilled outcome. ``action_items`` is the post-call TODO list."""

    summary: str = ""
    key_decisions: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: str = "medium"
    confidence_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "key_decisions": list(self.key_decisions),
            "action_items": list(self.action_items),
            "risks": list(self.risks),
            "confidence": self.confidence,
            "confidence_notes": self.confidence_notes,
        }


def parse_summary_json(content: str) -> dict[str, Any]:
    """Parse the LLM's JSON summary, tolerant of surrounding prose; falls back to the
    heuristic on empty/garbage input rather than raising."""
    text = (content or "").strip()
    if not text:
        return heuristic_summary("")
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        payload = json.loads(text)
    except Exception:
        return heuristic_summary(content or "")
    if not isinstance(payload, dict):
        return heuristic_summary(content or "")
    return {
        "summary": str(payload.get("summary") or "").strip(),
        "key_decisions": [str(i).strip() for i in (payload.get("key_decisions") or []) if str(i).strip()],
        "action_items": [str(i).strip() for i in (payload.get("action_items") or []) if str(i).strip()],
        "risks": [str(i).strip() for i in (payload.get("risks") or []) if str(i).strip()],
        "confidence": str(payload.get("confidence") or "medium").strip(),
        "confidence_notes": str(payload.get("confidence_notes") or "").strip(),
    }


def heuristic_summary(transcript_text: str) -> dict[str, Any]:
    """Deterministic, no-LLM summary — the fallback so a thin/failed LLM still yields a
    usable TODO list. Picks lines that announce actions / risks / decisions."""
    lines = [line.strip(" -*\t") for line in (transcript_text or "").splitlines() if line.strip()]
    summary = " ".join(lines[:3])[:1200] or "Transcript unavailable or too sparse for a confident summary."
    action_items = [
        line for line in lines
        if line.lower().startswith(("action:", "todo:", "next step:", "follow up:", "follow-up:", "ai:"))
    ][:12]
    risks = [line for line in lines if "risk" in line.lower() or "blocker" in line.lower()][:6]
    decisions = [line for line in lines if "decide" in line.lower() or "decision" in line.lower()][:6]
    confidence = "low" if len((transcript_text or "").strip()) < 300 else "medium"
    return {
        "summary": summary,
        "key_decisions": decisions,
        "action_items": action_items,
        "risks": risks,
        "confidence": confidence,
        "confidence_notes": "Generated with the heuristic fallback (no LLM summary available).",
    }


def build_summary_prompt(transcript_text: str, *, title: str | None = None, context: str = "") -> str:
    """A surface-agnostic summary prompt (no Teams/Meet-specific coupling)."""
    head = f"Title: {title or 'Unknown'}\n"
    if context:
        head += f"Context:\n{context}\n"
    return f"{head}\nTranscript:\n{(transcript_text or '')[:18000]}"


_SYSTEM = (
    "You summarize meeting transcripts. Return only valid JSON with keys: "
    "summary, key_decisions, action_items, risks, confidence, confidence_notes. "
    "action_items must be concrete, owner-addressable next steps."
)


async def summarize_transcript(
    transcript_text: str, *, title: str | None = None, context: str = ""
) -> MeetingSummary:
    """LLM summary with a heuristic fallback. Never raises — a failed LLM degrades to
    the deterministic heuristic so the caller always gets a TODO list."""
    prompt = build_summary_prompt(transcript_text, title=title, context=context)
    try:
        from agent.auxiliary_client import async_call_llm, extract_content_or_reasoning

        response = await async_call_llm(
            task="call",
            messages=[{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=900,
        )
        parsed = parse_summary_json(extract_content_or_reasoning(response))
    except Exception:
        parsed = heuristic_summary(transcript_text)
    return MeetingSummary(**parsed)


def summarize_transcript_sync(
    transcript_text: str, *, title: str | None = None, context: str = ""
) -> MeetingSummary:
    """Synchronous wrapper for tool/CLI handlers. Runs the async summarizer when no
    event loop is already running; otherwise (or on any failure) returns the heuristic
    summary so a sync caller never blocks on / breaks against the loop."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        try:
            return asyncio.run(summarize_transcript(transcript_text, title=title, context=context))
        except Exception:
            return MeetingSummary(**heuristic_summary(transcript_text))
    # already inside a running loop — don't nest; heuristic is the safe sync answer
    return MeetingSummary(**heuristic_summary(transcript_text))
