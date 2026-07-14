"""Review-safe transcript rendering from explicitly linked local sessions."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from forecasting.change_control.models import content_digest


MARKER_START = "<!-- forecast-agent-transcript:start -->"
MARKER_END = "<!-- forecast-agent-transcript:end -->"
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("authorization_header", re.compile(r"\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{16,}", re.I)),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{8,}\b")),
    (
        "session_cookie",
        re.compile(r"\b(?:user_session|_gh_sess|session_cookie|GH_SESSION_TOKEN)\b", re.I),
    ),
    (
        "secret_assignment",
        re.compile(r"\b(?:token|api[_-]?key|client[_-]?secret|password)\s*[:=]\s*\S+", re.I),
    ),
    (
        "authentication_url",
        re.compile(r"https?://\S+[?&](?:token|key|secret|signature|access_token|auth)=", re.I),
    ),
)
_PATH = re.compile(r"(?:/Users|/home)/[^\s`\"'>)]+|~/[^\s`\"'>)]+")
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
_PHONE = re.compile(r"\b(?:\+?\d[\d .()-]{7,}\d)\b")
_WORD = re.compile(r"[A-Za-z0-9_.:-]{3,}")


@dataclass(frozen=True)
class TranscriptRender:
    safe: bool
    status: str
    markdown: str
    html: str
    digest: str
    findings: tuple[dict[str, str], ...]
    included_entries: int
    omitted_entries: int


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return "\n".join(part for item in value if (part := _text(item)))
    if isinstance(value, Mapping):
        for key in ("text", "content", "message", "summary"):
            if key in value:
                return _text(value[key])
    return ""


def _find_secrets(text: str, location: str) -> list[dict[str, str]]:
    return [
        {"class": secret_class, "location": location}
        for secret_class, pattern in _SECRET_PATTERNS
        if pattern.search(text)
    ]


def review_transcript_findings(text: str, *, location: str = "transcript") -> tuple[dict[str, str], ...]:
    """Re-scan a rendered transcript before it crosses a publication boundary."""

    findings = _find_secrets(text, location)
    if MARKER_START not in text or MARKER_END not in text:
        findings.append({"class": "invalid_transcript_markers", "location": location})
    return tuple(findings)


def _sanitize(text: str, *, max_chars: int) -> str:
    value = _PATH.sub("[LOCAL_PATH]", text)
    value = _EMAIL.sub("[REDACTED_EMAIL]", value)
    value = _PHONE.sub("[REDACTED_PHONE]", value)
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"\n{3,}", "\n\n", value).strip()
    if len(value) > max_chars:
        value = value[:max_chars].rstrip() + "\n…[entry truncated]"
    return value


def _scope_terms(
    *,
    goal: str,
    branch: str | None,
    changed_object_ids: Iterable[str],
    changed_files: Iterable[str],
) -> set[str]:
    source = " ".join(
        [goal, branch or "", *changed_object_ids, *changed_files]
    ).lower()
    stop = {"this", "that", "with", "from", "into", "forecast", "changeset", "agent"}
    return {match.group(0) for match in _WORD.finditer(source) if match.group(0) not in stop}


def _tool_family(name: str) -> str:
    value = name.lower()
    if re.search(r"read|open|find|search|list|view|status|diff", value):
        return "read"
    if re.search(r"write|edit|patch|create|update|save|comment", value):
        return "write"
    if re.search(r"web|http|browser|github|slack", value):
        return "network"
    if re.search(r"exec|command|run|test|build|lint|git", value):
        return "execute"
    return "other"


def render_review_transcript(
    *,
    changeset_id: str,
    goal: str,
    sessions: Mapping[str, Sequence[Mapping[str, Any]]],
    runs: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    branch: str | None = None,
    changed_object_ids: Iterable[str] = (),
    changed_files: Iterable[str] = (),
    max_chars: int = 50_000,
    entry_max_chars: int = 6_000,
) -> TranscriptRender:
    """Render only explicitly linked, task-relevant dialogue; never discovers sessions."""

    terms = _scope_terms(
        goal=goal,
        branch=branch,
        changed_object_ids=changed_object_ids,
        changed_files=changed_files,
    )
    candidates: list[tuple[str, str, str]] = []
    findings: list[dict[str, str]] = []
    tool_counts: dict[str, int] = {}
    omitted = 0
    for session_id, messages in sessions.items():
        for index, message in enumerate(messages):
            role = str(message.get("role") or "").lower()
            location = f"session:{session_id}:message:{index}"
            raw = _text(message.get("content"))
            if role in {"system", "developer", "tool", "tool_result", "function"}:
                omitted += 1
                if role in {"tool", "tool_result", "function"}:
                    name = str(message.get("tool_name") or message.get("name") or "tool")
                    family = _tool_family(name)
                    tool_counts[family] = tool_counts.get(family, 0) + 1
                continue
            if role not in {"user", "assistant"} or not raw.strip():
                omitted += 1
                continue
            findings.extend(_find_secrets(raw, location))
            for call in message.get("tool_calls") or ():
                name = str((call.get("function") or {}).get("name") or call.get("name") or "tool")
                family = _tool_family(name)
                tool_counts[family] = tool_counts.get(family, 0) + 1
            candidates.append((role, raw, location))

    for run_id, events in (runs or {}).items():
        for index, event in enumerate(events):
            location = f"run:{run_id}:event:{index}"
            raw = _text(event.get("summary") or event.get("message"))
            findings.extend(_find_secrets(raw, location))
            event_type = str(event.get("event") or event.get("type") or "")
            if event_type.startswith(("test.", "check.")) or event_type in {
                "run.completed",
                "run.failed",
            }:
                summary = _sanitize(raw or event_type, max_chars=entry_max_chars)
                candidates.append(("proof", summary, location))
            else:
                omitted += 1

    if findings:
        return TranscriptRender(
            safe=False,
            status="transcript_unavailable_safety_failure",
            markdown="",
            html="",
            digest=content_digest({"status": "unsafe", "findings": findings}),
            findings=tuple(findings),
            included_entries=0,
            omitted_entries=omitted + len(candidates),
        )

    matched = {
        index
        for index, (_, text, _) in enumerate(candidates)
        if not terms or any(term in text.lower() for term in terms)
    }
    selected = matched
    entries: list[str] = []
    for index, (role, raw, _) in enumerate(candidates):
        if role != "proof" and index not in selected:
            omitted += 1
            continue
        clean = _sanitize(raw, max_chars=entry_max_chars)
        if clean:
            label = {"user": "User", "assistant": "Agent", "proof": "Test / proof"}[role]
            entries.append(f"**{label}:**\n\n{clean}")
    if tool_counts:
        summary = ", ".join(f"{count} {family}" for family, count in sorted(tool_counts.items()))
        entries.append(f"**Tool summary:** {summary}; raw tool inputs and outputs omitted.")
    body = "\n\n".join(entries)
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n\n…[transcript truncated]"
    if not body:
        return TranscriptRender(
            safe=True,
            status="no_relevant_transcript",
            markdown="",
            html="",
            digest=content_digest({"status": "empty", "changeset_id": changeset_id}),
            findings=(),
            included_entries=0,
            omitted_entries=omitted,
        )
    markdown = (
        f"{MARKER_START}\n"
        "## Agent Transcript\n\n"
        "<details><summary>Redacted, task-scoped agent transcript</summary>\n\n"
        f"{body}\n\n"
        "_System/developer prompts, provider reasoning, raw tool data, environment values, "
        "credentials, auth details, broad paths, and unrelated turns are omitted._\n\n"
        "</details>\n"
        f"{MARKER_END}\n"
    )
    digest = content_digest(markdown)
    html_preview = (
        "<!doctype html><meta charset='utf-8'><title>Transcript preview</title>"
        "<main style='max-width:900px;margin:40px auto;font:16px system-ui;white-space:pre-wrap'>"
        f"{html.escape(markdown)}</main>"
    )
    return TranscriptRender(
        safe=True,
        status="safe",
        markdown=markdown,
        html=html_preview,
        digest=digest,
        findings=(),
        included_entries=len(entries),
        omitted_entries=omitted,
    )


def update_marked_section(body: str, transcript_markdown: str) -> str:
    """Insert or replace a real transcript section; an empty transcript is a no-op."""

    if not transcript_markdown:
        return body
    start, end = body.find(MARKER_START), body.find(MARKER_END)
    if start >= 0 and end > start:
        end += len(MARKER_END)
        return body[:start].rstrip() + "\n\n" + transcript_markdown.strip() + "\n\n" + body[end:].lstrip()
    return body.rstrip() + "\n\n" + transcript_markdown.strip() + "\n"


__all__ = [
    "MARKER_END",
    "MARKER_START",
    "TranscriptRender",
    "render_review_transcript",
    "review_transcript_findings",
    "update_marked_section",
]
