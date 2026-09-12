"""Read-only candidate matching shared by question creation and forecast entrypoints."""

from __future__ import annotations

from typing import Any

from forecasting.search import search_forecasts

# Duplicate-detection thresholds over the search ranker's integer scores. The floor
# keeps a single trivial token hit from surfacing as a "duplicate"; the higher warn
# threshold is roughly a title-substring-level match (the ranker gives title weight
# 18, ×3 for substring containment) and only nudges — it never blocks a commit.
DUPLICATE_SCORE_FLOOR = 18
DUPLICATE_WARN_SCORE = 54


def find_possible_duplicates(
    ledger: Any, title: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    """Rank existing active questions against a draft title and return the top few
    above a sane score floor. Pure reuse of the forecast search ranker — no new
    subsystem. Empty when the title is blank/trivial or nothing scores."""
    title = (title or "").strip()
    if not title:
        return []
    matches = search_forecasts(ledger, title, status="active", limit=limit)
    out: list[dict[str, Any]] = []
    for match in matches:
        if match.score < DUPLICATE_SCORE_FLOOR:
            continue
        out.append({
            "id": match.question.id,
            "title": match.question.title,
            "score": match.score,
            "status": match.question.status,
        })
    return out
