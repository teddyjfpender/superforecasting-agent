"""Session text operations behind the SessionDB API."""

import re


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for safe use in FTS5 MATCH queries.

    FTS5 has its own query syntax where characters like ``"``, ``(``, ``)``,
    ``+``, ``*``, ``{``, ``}`` and bare boolean operators (``AND``, ``OR``,
    ``NOT``) have special meaning.  Passing raw user input directly to
    MATCH can cause ``sqlite3.OperationalError``.

    Strategy:
    - Preserve properly paired quoted phrases (``"exact phrase"``)
    - Strip unmatched FTS5-special characters that would cause errors
    - Wrap unquoted hyphenated and dotted terms in quotes so FTS5
      matches them as exact phrases instead of splitting on the
      hyphen/dot (e.g. ``chat-send``, ``P2.2``, ``my-app.config.ts``)
    """
    # Step 1: Extract balanced double-quoted phrases and protect them
    # from further processing via numbered placeholders.
    _quoted_parts: list = []

    def _preserve_quoted(m: re.Match) -> str:
        _quoted_parts.append(m.group(0))
        return f"\x00Q{len(_quoted_parts) - 1}\x00"

    sanitized = re.sub(r'"[^"]*"', _preserve_quoted, query)
    # Step 2: Strip remaining (unmatched) FTS5-special characters
    sanitized = re.sub(r"[+{}()\"^]", " ", sanitized)
    # Step 3: Collapse repeated * (e.g. "***") into a single one,
    # and remove leading * (prefix-only needs at least one char before *)
    sanitized = re.sub(r"\*+", "*", sanitized)
    sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)
    # Step 4: Remove dangling boolean operators at start/end that would
    # cause syntax errors (e.g. "hello AND" or "OR world")
    sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
    sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())
    # Step 5: Wrap unquoted dotted and/or hyphenated terms in double
    # quotes.  FTS5's tokenizer splits on dots and hyphens, turning
    # ``chat-send`` into ``chat AND send`` and ``P2.2`` into ``p2 AND 2``.
    # Quoting preserves phrase semantics.  A single pass avoids the
    # double-quoting bug that would occur if dotted, hyphenated and underscored
    # patterns were applied sequentially (e.g. ``my-app.config``).
    sanitized = re.sub(r"\b(\w+(?:[._-]\w+)+)\b", r'"\1"', sanitized)
    # Step 6: Restore preserved quoted phrases
    for i, quoted in enumerate(_quoted_parts):
        sanitized = sanitized.replace(f"\x00Q{i}\x00", quoted)
    return sanitized.strip()


def _is_cjk_codepoint(cp: int) -> bool:
    return (
        0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
        or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
        or 0x20000 <= cp <= 0x2A6DF  # CJK Extension B
        or 0x3000 <= cp <= 0x303F  # CJK Symbols
        or 0x3040 <= cp <= 0x309F  # Hiragana
        or 0x30A0 <= cp <= 0x30FF  # Katakana
        or 0xAC00 <= cp <= 0xD7AF
    )  # Hangul Syllables


def _contains_cjk(text: str) -> bool:
    """Check if text contains CJK (Chinese, Japanese, Korean) characters."""
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK Unified Ideographs
            or 0x3400 <= cp <= 0x4DBF  # CJK Extension A
            or 0x20000 <= cp <= 0x2A6DF  # CJK Extension B
            or 0x3000 <= cp <= 0x303F  # CJK Symbols
            or 0x3040 <= cp <= 0x309F  # Hiragana
            or 0x30A0 <= cp <= 0x30FF  # Katakana
            or 0xAC00 <= cp <= 0xD7AF
        ):  # Hangul Syllables
            return True
    return False


def _count_cjk(cls, text: str) -> int:
    """Count CJK characters in text."""
    return sum(1 for ch in text if cls._is_cjk_codepoint(ord(ch)))
