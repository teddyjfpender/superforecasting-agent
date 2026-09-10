"""Brand rewriting and bounded Markdown memory entry merging."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from _forecast_migration_files import normalize_text, read_text
from _forecast_migration_options import ENTRY_DELIMITER


# ── Brand rewriting ─────────────────────────────────────────
# Replace OpenClaw brand names with Superforecasting Agent in migrated text so that
# memory entries, user profiles, SOUL.md, and workspace instructions
# read as self-referential to the new agent identity.
#
# Case-preserving: ``OpenClaw`` → ``Superforecasting Agent`` (prose), but
# lowercase matches like ``openclaw`` → ``superforecasting-agent`` so filesystem
# paths like ``~/.openclaw`` become ``~/.superforecasting-agent``.
_REBRAND_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r'\bOpen[\s-]?Claw\b', re.IGNORECASE), 'Superforecasting Agent'),
    (re.compile(r'\bClawdBot\b', re.IGNORECASE), 'Superforecasting Agent'),
    (re.compile(r'\bMoltBot\b', re.IGNORECASE), 'Superforecasting Agent'),
]


def _case_preserving_replacement(replacement: str):
    """Return a re.sub replacement fn that lowercases the result when the
    matched text was all-lowercase.

    Keeps ``OpenClaw`` → ``Superforecasting Agent`` but maps ``openclaw`` to
    ``superforecasting-agent`` so a filesystem path like
    ``~/.openclaw/config.yaml`` rewrites to
    ``~/.superforecasting-agent/config.yaml``.
    """
    def _sub(match: "re.Match[str]") -> str:
        matched = match.group(0)
        if matched and matched.islower():
            return replacement.lower().replace(" ", "-")
        return replacement
    return _sub


def rebrand_text(text: str) -> str:
    """Replace OpenClaw / ClawdBot / MoltBot brand names with Superforecasting Agent.

    Preserves case so filesystem-path matches (lowercase) don't become
    capitalized directory names that don't exist.
    """
    for pattern, replacement in _REBRAND_PATTERNS:
        text = pattern.sub(_case_preserving_replacement(replacement), text)
    return text


def parse_existing_memory_entries(path: Path) -> List[str]:
    if not path.exists():
        return []
    raw = read_text(path)
    if not raw.strip():
        return []
    if ENTRY_DELIMITER in raw:
        return [e.strip() for e in raw.split(ENTRY_DELIMITER) if e.strip()]
    return extract_markdown_entries(raw)


def extract_markdown_entries(text: str) -> List[str]:
    entries: List[str] = []
    headings: List[str] = []
    paragraph_lines: List[str] = []

    def context_prefix() -> str:
        filtered = [h for h in headings if h and not re.search(r"\b(MEMORY|USER|SOUL|AGENTS|TOOLS|IDENTITY)\.md\b", h, re.I)]
        return " > ".join(filtered)

    def flush_paragraph() -> None:
        nonlocal paragraph_lines
        if not paragraph_lines:
            return
        text_block = " ".join(line.strip() for line in paragraph_lines).strip()
        paragraph_lines = []
        if not text_block:
            return
        prefix = context_prefix()
        if prefix:
            entries.append(f"{prefix}: {text_block}")
        else:
            entries.append(text_block)

    in_code_block = False
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            flush_paragraph()
            continue
        if in_code_block:
            continue

        heading_match = re.match(r"^(#{1,6})\s+(.*\S)\s*$", stripped)
        if heading_match:
            flush_paragraph()
            level = len(heading_match.group(1))
            text_value = heading_match.group(2).strip()
            while len(headings) >= level:
                headings.pop()
            headings.append(text_value)
            continue

        bullet_match = re.match(r"^\s*(?:[-*]|\d+\.)\s+(.*\S)\s*$", line)
        if bullet_match:
            flush_paragraph()
            content = bullet_match.group(1).strip()
            prefix = context_prefix()
            entries.append(f"{prefix}: {content}" if prefix else content)
            continue

        if not stripped:
            flush_paragraph()
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            flush_paragraph()
            continue

        paragraph_lines.append(stripped)

    flush_paragraph()

    deduped: List[str] = []
    seen = set()
    for entry in entries:
        normalized = normalize_text(entry)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(entry.strip())
    return deduped


def merge_entries(
    existing: Sequence[str],
    incoming: Sequence[str],
    limit: int,
) -> Tuple[List[str], Dict[str, int], List[str]]:
    merged = list(existing)
    seen = {normalize_text(entry) for entry in existing if entry.strip()}
    stats = {"existing": len(existing), "added": 0, "duplicates": 0, "overflowed": 0}
    overflowed: List[str] = []

    current_len = len(ENTRY_DELIMITER.join(merged)) if merged else 0

    for entry in incoming:
        normalized = normalize_text(entry)
        if not normalized:
            continue
        if normalized in seen:
            stats["duplicates"] += 1
            continue

        candidate_len = len(entry) if not merged else current_len + len(ENTRY_DELIMITER) + len(entry)
        if candidate_len > limit:
            stats["overflowed"] += 1
            overflowed.append(entry)
            continue

        merged.append(entry)
        seen.add(normalized)
        current_len = candidate_len
        stats["added"] += 1

    return merged, stats, overflowed
