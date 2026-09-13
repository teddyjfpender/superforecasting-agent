"""Pure environment-file repair, independent of credential discovery and I/O."""

from collections.abc import Collection
from io import StringIO


def sanitize_env_lines(lines: list[str], known_keys: Collection[str]) -> list[str]:
    """Fix corrupted .env lines before reading or writing.

    Repairs concatenation and normalizes surrounding whitespace and line endings:
    1. Concatenated KEY=VALUE pairs on a single line (missing newline between
       entries, e.g. ``ANTHROPIC_API_KEY=sk-...OPENAI_BASE_URL=https://...``).
    Placeholder values are preserved; credential usability is a separate policy.

    Uses the caller-supplied known keys so we only
    split on real agent env var names, avoiding false positives from values
    that happen to contain uppercase text with ``=``.
    """
    sanitized: list[str] = []
    for line in lines:
        raw = line.rstrip("\r\n")
        stripped = raw.strip()

        # Preserve blank lines and comments
        if not stripped or stripped.startswith("#"):
            sanitized.append(raw + "\n")
            continue

        # Detect concatenated KEY=VALUE pairs on one line.
        # Search for known KEY= patterns at any position in the line.
        # We collect full needle ranges so we can drop matches that are
        # fully contained within a longer overlapping needle. Without this,
        # suffix collisions corrupt the file: e.g. LM_API_KEY= inside
        # GLM_API_KEY= would otherwise split the line into "G\nLM_API_KEY=...".
        match_ranges: list[tuple[int, int]] = []
        for key_name in known_keys:
            needle = key_name + "="
            idx = stripped.find(needle)
            while idx >= 0:
                match_ranges.append((idx, idx + len(needle)))
                idx = stripped.find(needle, idx + len(needle))

        split_positions = sorted({
            s
            for s, e in match_ranges
            if not any(
                s2 <= s and e2 >= e and (s2, e2) != (s, e) for s2, e2 in match_ranges
            )
        })

        if len(split_positions) > 1:
            for i, pos in enumerate(split_positions):
                end = (
                    split_positions[i + 1]
                    if i + 1 < len(split_positions)
                    else len(stripped)
                )
                part = stripped[pos:end].strip()
                if part:
                    sanitized.append(part + "\n")
        else:
            sanitized.append(stripped + "\n")

    return sanitized


def parse_environment(contents: str, known_keys: Collection[str]) -> dict[str, str]:
    """Parse the legacy KEY=VALUE grammar after repairing concatenated keys.

    Values remain strings. This preserves the existing quote stripping and
    last-assignment-wins behavior; it does not execute shell or dotenv expansion.
    """
    values: dict[str, str] = {}
    # Match text-file universal newlines, preserving other Unicode separators
    # inside values (str.splitlines would treat those as additional records).
    with StringIO(contents, newline=None) as stream:
        lines = stream.readlines()
    for line in sanitize_env_lines(lines, known_keys):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    return values
